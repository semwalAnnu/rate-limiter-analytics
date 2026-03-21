"""Unit tests for the token bucket rate limiter.

Uses a FakeRedis that mimics aioredis WATCH/MULTI/EXEC in memory,
so no real Redis instance is needed. Time is patched to make
token refill calculations deterministic.

Run:
    pytest tests/test_rate_limiter.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# ── Stub heavy dependencies before importing rate_limiter
_mock_exc = MagicMock()
_mock_exc.WatchError = type("WatchError", (Exception,), {})
sys.modules.setdefault("aioredis", MagicMock())
sys.modules["aioredis.exceptions"] = _mock_exc

# config.settings reads .env at import time; the .env has Grafana keys that
# pydantic-settings rejects as extra fields. Provide a clean stub instead.
_mock_settings = MagicMock()
_mock_settings.rate_limit_capacity = 100.0
_mock_settings.rate_limit_refill_rate = 10.0
_mock_config = MagicMock()
_mock_config.settings = _mock_settings
sys.modules["config"] = _mock_config

# gateway/ is a sibling of tests/ — add it so we can import rate_limiter directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gateway"))

from rate_limiter import check_rate_limit  # noqa: E402  (must come after sys.path)

# Fixed "now" used across all tests so time never drifts
T0 = 1_000_000.0


# ── Fake Redis ────────────────────────────────────────────────────────────────

class _FakePipeline:
    """Minimal async pipeline that replays WATCH/MULTI/EXEC against an in-memory dict."""

    def __init__(self, store: dict) -> None:
        self._store = store
        self._queued: list[tuple[str, str]] = []

    async def watch(self, *keys: str) -> None:
        self._queued = []

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    def multi(self) -> None:
        self._queued = []

    def set(self, key: str, value: object) -> None:
        # queue without awaiting — mirrors real pipeline behaviour after MULTI
        self._queued.append((key, str(value)))

    async def execute(self) -> list:
        for key, value in self._queued:
            self._store[key] = value
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

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self._store)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_tokens_decrease_on_allowed_request():
    """First request on a new client consumes exactly one token."""
    redis = FakeRedis()
    with patch("rate_limiter.time") as mock_time:
        mock_time.time.return_value = T0
        allowed, tokens = asyncio.run(check_rate_limit(redis, "client_a"))

    assert allowed is True
    assert tokens == pytest.approx(99.0)  # capacity(100) - 1


def test_request_rejected_when_tokens_exhausted():
    """A request is rejected and no token is consumed when bucket has < 1 token."""
    redis = FakeRedis()
    redis._store["bucket:client_b:tokens"] = "0.5"
    redis._store["bucket:client_b:last_refill"] = str(T0)

    with patch("rate_limiter.time") as mock_time:
        mock_time.time.return_value = T0  # no time passes → no refill
        allowed, tokens = asyncio.run(check_rate_limit(redis, "client_b"))

    assert allowed is False
    assert tokens == pytest.approx(0.5)  # unchanged — not consumed


def test_tokens_refill_over_time():
    """Bucket refills at RATE_LIMIT_REFILL_RATE tokens per second."""
    redis = FakeRedis()
    redis._store["bucket:client_c:tokens"] = "0.0"
    redis._store["bucket:client_c:last_refill"] = str(T0)

    with patch("rate_limiter.time") as mock_time:
        mock_time.time.return_value = T0 + 5.0  # 5 s × 10 tok/s = 50 new tokens
        allowed, tokens = asyncio.run(check_rate_limit(redis, "client_c"))

    assert allowed is True
    assert tokens == pytest.approx(49.0)  # 50 refilled − 1 consumed


def test_tokens_capped_at_capacity():
    """Token count never exceeds RATE_LIMIT_CAPACITY regardless of elapsed time."""
    redis = FakeRedis()
    redis._store["bucket:client_d:tokens"] = "90.0"
    redis._store["bucket:client_d:last_refill"] = str(T0)

    with patch("rate_limiter.time") as mock_time:
        mock_time.time.return_value = T0 + 100.0  # would give 1090 tokens without cap
        allowed, tokens = asyncio.run(check_rate_limit(redis, "client_d"))

    assert allowed is True
    assert tokens == pytest.approx(99.0)  # capped at 100, minus 1 consumed

def test_different_clients_are_independent():
    redis = FakeRedis()
    with patch("rate_limiter.time") as mock_time:
        mock_time.time.return_value = T0

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