"""Token bucket rate limiter backed by Redis (aioredis).

Each client gets two Redis keys:
  bucket:{client_id}:tokens      — current token count (float)
  bucket:{client_id}:last_refill — Unix timestamp of last refill

All Redis calls are async to keep the gateway non-blocking.
"""
from __future__ import annotations

from typing import Tuple

import aioredis

from config import settings


async def get_redis() -> aioredis.Redis:
    """Return a connected aioredis client. Call once at startup."""
    raise NotImplementedError


async def check_rate_limit(redis: aioredis.Redis, client_id: str) -> Tuple[bool, float]:
    """Check whether *client_id* is within its rate limit.

    Returns:
        (allowed, tokens_remaining)
        allowed=True  → request may proceed
        allowed=False → request must be rejected with HTTP 429
    """
    raise NotImplementedError
