"""FastAPI gateway entry point.

Startup: connect Redis, start Kafka producer.
Every request: validate JWT → check rate limit → proxy to upstream →
               publish event to Kafka.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response

from auth import get_client_id
from config import settings
from rate_limiter import check_rate_limit, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = await get_redis()
    app.state.producer = None  # Phase 2: Kafka producer
    yield
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
    allowed, tokens = await check_rate_limit(redis, client_id)

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
    async with httpx.AsyncClient() as client:
        upstream_response = await client.request(
            method=request.method,
            url=f"{settings.upstream_url}/{path}",
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            content=await request.body(),
            params=dict(request.query_params),
        )
    latency_ms = (time.monotonic() - start) * 1000  # noqa: F841 — Phase 2: include in event

    # Phase 2: publish allowed event to Kafka here

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=dict(upstream_response.headers),
        media_type=upstream_response.headers.get("content-type"),
    )
