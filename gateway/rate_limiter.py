"""Token bucket rate limiter backed by Redis.

Each client gets two Redis keys:
  bucket:{client_id}:tokens      — current token count (float)
  bucket:{client_id}:last_refill — Unix timestamp of last refill

Read-modify-write uses WATCH/MULTI/EXEC so no other request can interleave
between reading the bucket state and writing the updated values.
"""
from __future__ import annotations

import time
from typing import Tuple

import redis.asyncio as aioredis
from redis.exceptions import WatchError

from config import settings

MAX_RETRIES = 5


def get_redis() -> aioredis.Redis:
    """Return an async Redis client. Call once at startup."""
    return aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


async def check_rate_limit(redis: aioredis.Redis, client_id: str) -> Tuple[bool, float]:
    """Check whether *client_id* is within its rate limit.

    Uses WATCH/MULTI/EXEC to atomically read-compute-write the token bucket.
    Retries automatically on contention (WatchError).

    Returns:
        (allowed, tokens_remaining)
        allowed=True  → request may proceed
        allowed=False → reject with HTTP 429
    """
    tokens_key = f"bucket:{client_id}:tokens"
    refill_key = f"bucket:{client_id}:last_refill"
    key_ttl = int(settings.rate_limit_capacity / settings.rate_limit_refill_rate) + 60

    async with redis.pipeline(transaction=True) as pipe:
        for _attempt in range(MAX_RETRIES):
            try:
                await pipe.watch(tokens_key, refill_key)

                raw_tokens = await pipe.get(tokens_key)
                raw_last_refill = await pipe.get(refill_key)

                now = time.time()
                tokens = float(raw_tokens) if raw_tokens is not None else settings.rate_limit_capacity
                last_refill = float(raw_last_refill) if raw_last_refill is not None else now

                elapsed = now - last_refill
                tokens = min(
                    settings.rate_limit_capacity,
                    tokens + elapsed * settings.rate_limit_refill_rate,
                )

                allowed = tokens >= 1.0
                if allowed:
                    tokens -= 1.0

                pipe.multi()
                pipe.set(tokens_key, tokens, ex=key_ttl)
                pipe.set(refill_key, now, ex=key_ttl)
                await pipe.execute()

                return allowed, tokens

            except WatchError:
                # Another request modified the bucket — retry
                continue

    raise RuntimeError(f"rate limit check failed after {MAX_RETRIES} retries")
