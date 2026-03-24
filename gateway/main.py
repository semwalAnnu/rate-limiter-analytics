"""FastAPI gateway entry point.

Startup: connect Redis, start Kafka producer.
Every request: validate JWT → check rate limit → check circuit breaker →
               proxy to upstream → publish event to Kafka.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response

from auth import get_client_id
from circuit_breaker import CircuitBreaker
from config import settings
from kafka_producer import get_producer, publish_event
from models import RequestEvent
from rate_limiter import check_rate_limit, get_redis

logger = logging.getLogger(__name__)

STRIP_HEADERS = {"host", "authorization", "cookie"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = get_redis()
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=2.0, read=10.0, write=5.0, pool=5.0),
    )
    app.state.breakers: dict[str, CircuitBreaker] = {}
    try:
        app.state.producer = await get_producer()
        logger.info("kafka producer started")
    except Exception:
        logger.warning("kafka producer unavailable, events will not be published")
        app.state.producer = None
    yield
    await app.state.http_client.aclose()
    await app.state.redis.aclose()
    if app.state.producer:
        await app.state.producer.flush()
        await app.state.producer.stop()


app = FastAPI(title="Rate Limiter Gateway", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(
    path: str,
    request: Request,
    client_id: str = Depends(get_client_id),
) -> Response:
    redis = request.app.state.redis

    try:
        allowed, tokens = await check_rate_limit(redis, client_id)
    except Exception:
        logger.exception("redis error during rate limit check")
        raise HTTPException(status_code=503, detail="rate limiter unavailable")

    if not allowed:
        event = RequestEvent(
            client_id=client_id,
            endpoint=path,
            method=request.method,
            status="rejected",
            latency_ms=0.0,
            tokens_remaining=tokens,
        )
        await publish_event(request.app.state.producer, event)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate limit exceeded",
                "retry_after_seconds": round(1.0 / settings.rate_limit_refill_rate, 2),
            },
        )

    breakers = request.app.state.breakers
    if path not in breakers:
        breakers[path] = CircuitBreaker()
    breaker = breakers[path]

    if breaker.is_open:
        event = RequestEvent(
            client_id=client_id,
            endpoint=path,
            method=request.method,
            status="circuit_open",
            latency_ms=0.0,
            tokens_remaining=tokens,
        )
        await publish_event(request.app.state.producer, event)
        raise HTTPException(status_code=503, detail="circuit breaker open")

    start = time.monotonic()
    try:
        upstream_response = await request.app.state.http_client.request(
            method=request.method,
            url=f"{settings.upstream_url}/{path}",
            headers={k: v for k, v in request.headers.items() if k.lower() not in STRIP_HEADERS},
            content=await request.body(),
            params=dict(request.query_params),
        )
    except httpx.TimeoutException:
        breaker.record_failure()
        raise HTTPException(status_code=504, detail="upstream timeout")
    except httpx.HTTPError:
        breaker.record_failure()
        raise HTTPException(status_code=502, detail="upstream unreachable")

    latency_ms = (time.monotonic() - start) * 1000

    if upstream_response.status_code >= 500:
        breaker.record_failure()
    else:
        breaker.record_success()

    event = RequestEvent(
        client_id=client_id,
        endpoint=path,
        method=request.method,
        status="allowed",
        latency_ms=round(latency_ms, 2),
        tokens_remaining=tokens,
        upstream_status=upstream_response.status_code,
    )
    await publish_event(request.app.state.producer, event)

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=dict(upstream_response.headers),
        media_type=upstream_response.headers.get("content-type"),
    )
