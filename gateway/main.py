"""FastAPI gateway entry point.

Startup: connect Redis, start Kafka producer.
Every request: validate JWT → check rate limit → proxy to upstream →
               publish event to Kafka.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response

from auth import get_client_id
from config import settings
from rate_limiter import check_rate_limit, get_redis

logger = logging.getLogger(__name__)

STRIP_HEADERS = {"host", "authorization", "cookie"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = get_redis()
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=2.0, read=10.0, write=5.0, pool=5.0),
    )
    app.state.producer = None  # Phase 2: Kafka producer
    yield
    await app.state.http_client.aclose()
    await app.state.redis.aclose()


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
        # Phase 2: publish rejection event to Kafka here
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate limit exceeded",
                "retry_after_seconds": round(1.0 / settings.rate_limit_refill_rate, 2),
            },
        )

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
        raise HTTPException(status_code=504, detail="upstream timeout")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="upstream unreachable")

    latency_ms = (time.monotonic() - start) * 1000  # noqa: F841 — Phase 2: include in event

    # Phase 2: publish allowed event to Kafka here

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=dict(upstream_response.headers),
        media_type=upstream_response.headers.get("content-type"),
    )
