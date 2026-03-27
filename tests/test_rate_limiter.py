"""Unit tests for the rate limiter (token bucket + sliding window).

Uses a FakeRedis that mimics aioredis WATCH/MULTI/EXEC in memory,
so no real Redis instance is needed. Time is patched to make
calculations deterministic.

Run:
    docker compose run --rm test pytest tests/test_rate_limiter.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from redis.exceptions import WatchError
from rate_limiter import check_rate_limit

# Fixed "now" used across all tests so time never drifts
T0 = 1_000_000.0


# ── Fake Redis ────────────────────────────────────────────────────────────────

class _FakePipeline:
    """Minimal async pipeline that replays WATCH/MULTI/EXEC against an in-memory dict."""

    def __init__(self, store: dict, sorted_sets: dict) -> None:
        self._store = store
        self._sorted_sets = sorted_sets
        self._queued: list[tuple] = []
        self._in_multi = False

    async def watch(self, *keys: str) -> None:
        self._queued = []
        self._in_multi = False

    async def unwatch(self) -> None:
        self._in_multi = False

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    def multi(self) -> None:
        self._queued = []
        self._in_multi = True

    def set(self, key: str, value: object, ex: int | None = None) -> None:
        self._queued.append(("set", key, str(value)))

    def expire(self, key: str, seconds: int) -> None:
        self._queued.append(("expire", key, seconds))

    # sorted set operations
    async def zremrangebyscore(self, key: str, min_score: str, max_score: float) -> int:
        if key not in self._sorted_sets:
            return 0
        zset = self._sorted_sets[key]
        to_remove = [m for m, s in zset.items() if s <= max_score]
        for m in to_remove:
            del zset[m]
        return len(to_remove)

    async def zcard(self, key: str) -> int:
        return len(self._sorted_sets.get(key, {}))

    def zadd(self, key: str, mapping: dict) -> None:
        self._queued.append(("zadd", key, mapping))

    async def execute(self) -> list:
        for op in self._queued:
            if op[0] == "set":
                self._store[op[1]] = op[2]
            elif op[0] == "zadd":
                key, mapping = op[1], op[2]
                if key not in self._sorted_sets:
                    self._sorted_sets[key] = {}
                self._sorted_sets[key].update(mapping)
            elif op[0] == "expire":
                pass  # TTL not simulated
        result = [True] * len(self._queued)
        self._queued = []
        return result

    async def __aenter__(self) -> "_FakePipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        pass


class FakeRedis:
    """In-memory Redis stand-in for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._sorted_sets: dict[str, dict[str, float]] = {}

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self._store, self._sorted_sets)


# ── Token Bucket Tests ───────────────────────────────────────────────────────

def test_tokens_decrease_on_allowed_request():
    """First request on a new client consumes exactly one token."""
    redis = FakeRedis()
    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0
        mock_settings.rate_limit_capacity = 100.0
        mock_settings.rate_limit_refill_rate = 10.0
        mock_settings.rate_limit_algorithm = "token_bucket"
        allowed, tokens = asyncio.run(check_rate_limit(redis, "client_a"))

    assert allowed is True
    assert tokens == pytest.approx(99.0)


def test_request_rejected_when_tokens_exhausted():
    """A request is rejected and no token is consumed when bucket has < 1 token."""
    redis = FakeRedis()
    redis._store["bucket:client_b:tokens"] = "0.5"
    redis._store["bucket:client_b:last_refill"] = str(T0)

    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0
        mock_settings.rate_limit_capacity = 100.0
        mock_settings.rate_limit_refill_rate = 10.0
        mock_settings.rate_limit_algorithm = "token_bucket"
        allowed, tokens = asyncio.run(check_rate_limit(redis, "client_b"))

    assert allowed is False
    assert tokens == pytest.approx(0.5)


def test_tokens_refill_over_time():
    """Bucket refills at RATE_LIMIT_REFILL_RATE tokens per second."""
    redis = FakeRedis()
    redis._store["bucket:client_c:tokens"] = "0.0"
    redis._store["bucket:client_c:last_refill"] = str(T0)

    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0 + 5.0
        mock_settings.rate_limit_capacity = 100.0
        mock_settings.rate_limit_refill_rate = 10.0
        mock_settings.rate_limit_algorithm = "token_bucket"
        allowed, tokens = asyncio.run(check_rate_limit(redis, "client_c"))

    assert allowed is True
    assert tokens == pytest.approx(49.0)


def test_tokens_capped_at_capacity():
    """Token count never exceeds RATE_LIMIT_CAPACITY regardless of elapsed time."""
    redis = FakeRedis()
    redis._store["bucket:client_d:tokens"] = "90.0"
    redis._store["bucket:client_d:last_refill"] = str(T0)

    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0 + 100.0
        mock_settings.rate_limit_capacity = 100.0
        mock_settings.rate_limit_refill_rate = 10.0
        mock_settings.rate_limit_algorithm = "token_bucket"
        allowed, tokens = asyncio.run(check_rate_limit(redis, "client_d"))

    assert allowed is True
    assert tokens == pytest.approx(99.0)


def test_different_clients_are_independent():
    redis = FakeRedis()
    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0
        mock_settings.rate_limit_capacity = 100.0
        mock_settings.rate_limit_refill_rate = 10.0
        mock_settings.rate_limit_algorithm = "token_bucket"

        redis._store["bucket:client_d:tokens"] = "0.0"
        redis._store["bucket:client_d:last_refill"] = str(T0)

        allowed_d, tokens_d = asyncio.run(
            check_rate_limit(redis, "client_d")
        )
        assert allowed_d is False
        assert tokens_d == pytest.approx(0.0)

        allowed_e, tokens_e = asyncio.run(
            check_rate_limit(redis, "client_e")
        )
        assert allowed_e is True
        assert tokens_e == pytest.approx(99.0)

        allowed_d2, tokens_d2 = asyncio.run(
            check_rate_limit(redis, "client_d")
        )
        assert allowed_d2 is False
        assert tokens_d2 == pytest.approx(0.0)


def test_watcherror_retry_succeeds():
    """Rate limiter retries and succeeds after a WatchError on first attempt."""
    redis = FakeRedis()
    call_count = 0
    original_execute = _FakePipeline.execute

    async def flaky_execute(self):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise WatchError()
        return await original_execute(self)

    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0
        mock_settings.rate_limit_capacity = 100.0
        mock_settings.rate_limit_refill_rate = 10.0
        mock_settings.rate_limit_algorithm = "token_bucket"
        with patch.object(_FakePipeline, "execute", flaky_execute):
            allowed, tokens = asyncio.run(check_rate_limit(redis, "client_f"))

    assert allowed is True
    assert tokens == pytest.approx(99.0)
    assert call_count == 2


def test_watcherror_exhausts_max_retries():
    """Rate limiter raises after exhausting all retry attempts."""
    redis = FakeRedis()

    async def always_fail(self):
        raise WatchError()

    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0
        mock_settings.rate_limit_capacity = 100.0
        mock_settings.rate_limit_refill_rate = 10.0
        mock_settings.rate_limit_algorithm = "token_bucket"
        with patch.object(_FakePipeline, "execute", always_fail):
            with pytest.raises(RuntimeError, match="rate limit check failed"):
                asyncio.run(check_rate_limit(redis, "client_g"))


# ── Sliding Window Tests ─────────────────────────────────────────────────────

def test_sliding_window_allows_within_capacity():
    """Sliding window allows requests when under the capacity limit."""
    redis = FakeRedis()
    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0
        mock_settings.rate_limit_capacity = 5.0
        mock_settings.rate_limit_window_seconds = 10.0
        mock_settings.rate_limit_algorithm = "sliding_window"

        allowed, remaining = asyncio.run(check_rate_limit(redis, "sw_a"))

    assert allowed is True
    assert remaining == pytest.approx(4.0)


def test_sliding_window_rejects_over_capacity():
    """Sliding window rejects once capacity is reached within the window."""
    redis = FakeRedis()
    # pre-fill with 5 requests inside the window
    redis._sorted_sets["swlog:sw_b"] = {
        f"{T0 - i}": T0 - i for i in range(5)
    }

    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0
        mock_settings.rate_limit_capacity = 5.0
        mock_settings.rate_limit_window_seconds = 10.0
        mock_settings.rate_limit_algorithm = "sliding_window"

        allowed, remaining = asyncio.run(check_rate_limit(redis, "sw_b"))

    assert allowed is False
    assert remaining == pytest.approx(0.0)


def test_sliding_window_expired_entries_cleared():
    """Old entries outside the window are removed, freeing capacity."""
    redis = FakeRedis()
    # 5 entries all older than the window (T0 - 20s, window is 10s)
    redis._sorted_sets["swlog:sw_c"] = {
        f"{T0 - 20 - i}": T0 - 20 - i for i in range(5)
    }

    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0
        mock_settings.rate_limit_capacity = 5.0
        mock_settings.rate_limit_window_seconds = 10.0
        mock_settings.rate_limit_algorithm = "sliding_window"

        allowed, remaining = asyncio.run(check_rate_limit(redis, "sw_c"))

    assert allowed is True
    assert remaining == pytest.approx(4.0)


def test_sliding_window_different_clients_independent():
    """Each client has its own sliding window counter."""
    redis = FakeRedis()
    # fill sw_d to capacity
    redis._sorted_sets["swlog:sw_d"] = {
        f"{T0 - i}": T0 - i for i in range(5)
    }

    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0
        mock_settings.rate_limit_capacity = 5.0
        mock_settings.rate_limit_window_seconds = 10.0
        mock_settings.rate_limit_algorithm = "sliding_window"

        allowed_d, _ = asyncio.run(check_rate_limit(redis, "sw_d"))
        allowed_e, remaining_e = asyncio.run(check_rate_limit(redis, "sw_e"))

    assert allowed_d is False
    assert allowed_e is True
    assert remaining_e == pytest.approx(4.0)


def test_sliding_window_partial_expiry():
    """Only expired entries are removed; recent ones still count."""
    redis = FakeRedis()
    # 3 expired entries + 2 recent ones = capacity of 5
    redis._sorted_sets["swlog:sw_f"] = {
        f"{T0 - 15}": T0 - 15,  # expired (outside 10s window)
        f"{T0 - 12}": T0 - 12,  # expired
        f"{T0 - 11}": T0 - 11,  # expired
        f"{T0 - 3}": T0 - 3,    # still in window
        f"{T0 - 1}": T0 - 1,    # still in window
    }

    with patch("rate_limiter.time") as mock_time, \
         patch("rate_limiter.settings") as mock_settings:
        mock_time.time.return_value = T0
        mock_settings.rate_limit_capacity = 5.0
        mock_settings.rate_limit_window_seconds = 10.0
        mock_settings.rate_limit_algorithm = "sliding_window"

        allowed, remaining = asyncio.run(check_rate_limit(redis, "sw_f"))

    assert allowed is True
    # 2 existing + 1 new = 3, so remaining = 5 - 3 = 2
    assert remaining == pytest.approx(2.0)


# ── Redis Failure (Fail-Open) Tests ──────────────────────────────────────────

def test_redis_connection_error_fails_open_token_bucket():
    """When Redis raises ConnectionError, token bucket fails open."""
    redis = MagicMock()
    redis.pipeline.side_effect = ConnectionError("connection refused")

    with patch("rate_limiter.settings") as mock_settings:
        mock_settings.rate_limit_algorithm = "token_bucket"
        allowed, tokens = asyncio.run(check_rate_limit(redis, "fail_client"))

    assert allowed is True
    assert tokens == -1.0


def test_redis_connection_error_fails_open_sliding_window():
    """When Redis raises ConnectionError, sliding window fails open."""
    redis = MagicMock()
    redis.pipeline.side_effect = ConnectionError("connection refused")

    with patch("rate_limiter.settings") as mock_settings:
        mock_settings.rate_limit_algorithm = "sliding_window"
        allowed, tokens = asyncio.run(check_rate_limit(redis, "fail_client"))

    assert allowed is True
    assert tokens == -1.0


def test_redis_timeout_fails_open():
    """When Redis times out, the limiter fails open."""
    import redis.asyncio as aioredis
    redis = MagicMock()
    redis.pipeline.side_effect = aioredis.TimeoutError("timed out")

    with patch("rate_limiter.settings") as mock_settings:
        mock_settings.rate_limit_algorithm = "token_bucket"
        allowed, tokens = asyncio.run(check_rate_limit(redis, "timeout_client"))

    assert allowed is True
    assert tokens == -1.0
