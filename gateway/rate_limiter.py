"""Rate limiter backed by Redis.

Supports two algorithms (configured via RATE_LIMIT_ALGORITHM env var):

  token_bucket (default)
    Each client gets two Redis keys for token count and last refill time.
    Read-modify-write uses WATCH/MULTI/EXEC for atomicity.

  sliding_window
    Each client gets a sorted set of request timestamps. On each request
    we remove expired entries, count remaining ones, and allow if under
    the capacity limit within the window.

When Redis is unreachable, the limiter fails open — requests are allowed
through and a warning is logged.
"""
from __future__ import annotations

import logging
import time
from typing import Tuple

import redis.asyncio as aioredis
from redis.exceptions import WatchError

from config import settings

logger = logging.getLogger(__name__)

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

    Dispatches to the configured algorithm. If Redis is unreachable,
    fails open (allows the request) and logs a warning.

    Returns:
        (allowed, tokens_remaining)
        allowed=True  → request may proceed
        allowed=False → reject with HTTP 429
    """
    try:
        if settings.rate_limit_algorithm == "sliding_window":
            return await _check_sliding_window(redis, client_id)
        return await _check_token_bucket(redis, client_id)
    except (OSError, ConnectionError, aioredis.ConnectionError, aioredis.TimeoutError) as exc:
        logger.warning("redis unavailable, failing open for client %s: %s", client_id, exc)
        return True, -1.0


async def _check_token_bucket(redis: aioredis.Redis, client_id: str) -> Tuple[bool, float]:
    """Token bucket algorithm using WATCH/MULTI/EXEC."""
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
                continue

    raise RuntimeError(f"rate limit check failed after {MAX_RETRIES} retries")


async def _check_sliding_window(redis: aioredis.Redis, client_id: str) -> Tuple[bool, float]:
    """Sliding window log algorithm using a sorted set.

    Each request timestamp is stored as a member in a sorted set keyed
    by client_id. On each request we:
      1. Remove entries older than (now - window_seconds)
      2. Count remaining entries
      3. If count < capacity: add this request's timestamp, allow
      4. If count >= capacity: reject
    """
    key = f"swlog:{client_id}"
    now = time.time()
    window_start = now - settings.rate_limit_window_seconds
    key_ttl = int(settings.rate_limit_window_seconds) + 60

    async with redis.pipeline(transaction=True) as pipe:
        for _attempt in range(MAX_RETRIES):
            try:
                await pipe.watch(key)

                # remove expired entries and count current ones
                await pipe.zremrangebyscore(key, "-inf", window_start)
                count = await pipe.zcard(key)

                remaining = settings.rate_limit_capacity - count

                if remaining >= 1:
                    pipe.multi()
                    # use timestamp as both score and member (add microseconds for uniqueness)
                    member = f"{now}:{id(pipe)}"
                    pipe.zadd(key, {member: now})
                    pipe.expire(key, key_ttl)
                    await pipe.execute()
                    return True, remaining - 1
                else:
                    # over limit — don't write anything
                    await pipe.unwatch()
                    return False, 0.0

            except WatchError:
                continue

    raise RuntimeError(f"rate limit check failed after {MAX_RETRIES} retries")
