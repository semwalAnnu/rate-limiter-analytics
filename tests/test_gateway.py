"""Integration tests for the API gateway routing layer.

Uses FastAPI TestClient (synchronous). Redis, Kafka, and the upstream HTTP
service are replaced with lightweight doubles — no running infrastructure needed.

Run:
    pytest tests/test_gateway.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from jose import jwt

# ── Stub heavy dependencies before importing anything from gateway/ ────────────
_mock_exc = MagicMock()
_mock_exc.WatchError = type("WatchError", (Exception,), {})
sys.modules.setdefault("aioredis", MagicMock())
sys.modules["aioredis.exceptions"] = _mock_exc
sys.modules.setdefault("aiokafka", MagicMock())

_mock_settings = MagicMock()
_mock_settings.jwt_secret = "test-secret"
_mock_settings.rate_limit_capacity = 100.0
_mock_settings.rate_limit_refill_rate = 10.0
_mock_settings.upstream_url = "http://upstream:8001"
_mock_config = MagicMock()
_mock_config.settings = _mock_settings
sys.modules["config"] = _mock_config

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gateway"))

from auth import get_client_id  # noqa: E402
from main import app  # noqa: E402

CLIENT_ID = "client_test"


def _fake_upstream(status: int = 200, body: bytes = b'{"ok": true}') -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.content = body
    resp.headers = {"content-type": "application/json"}
    return resp


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health_returns_200():
    """/health is publicly accessible with no auth."""
    with patch("main.get_redis", new=AsyncMock(return_value=AsyncMock())):
        with TestClient(app) as c:
            response = c.get("/health")
    assert response.status_code == 200


def test_unauthenticated_request_returns_401():
    """Request with no Authorization header is rejected before rate limiting."""
    with patch("main.get_redis", new=AsyncMock(return_value=AsyncMock())):
        with TestClient(app) as c:
            response = c.get("/api/v1/products")
    assert response.status_code == 401


def test_allowed_request_proxied_to_upstream():
    """Valid JWT + tokens available → request forwarded, upstream response returned."""
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_fake_upstream(200))

    with patch("main.get_redis", new=AsyncMock(return_value=AsyncMock())):
        app.dependency_overrides[get_client_id] = lambda: CLIENT_ID
        try:
            with patch("main.check_rate_limit", new=AsyncMock(return_value=(True, 95.0))):
                with TestClient(app) as c:
                    app.state.http_client = mock_http
                    response = c.get("/api/v1/products")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_http.request.assert_called_once()


def test_rate_limited_request_returns_429():
    """Valid JWT but empty bucket → 429, upstream is never contacted."""
    with patch("main.get_redis", new=AsyncMock(return_value=AsyncMock())):
        app.dependency_overrides[get_client_id] = lambda: CLIENT_ID
        try:
            with patch("main.check_rate_limit", new=AsyncMock(return_value=(False, 0.3))):
                with TestClient(app) as c:
                    response = c.get("/api/v1/products")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 429


def test_upstream_unreachable_returns_502():
    """When upstream refuses connection, gateway returns 502."""
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with patch("main.get_redis", new=AsyncMock(return_value=AsyncMock())):
        app.dependency_overrides[get_client_id] = lambda: CLIENT_ID
        try:
            with patch("main.check_rate_limit", new=AsyncMock(return_value=(True, 95.0))):
                with TestClient(app) as c:
                    app.state.http_client = mock_http
                    response = c.get("/api/v1/products")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 502


def test_upstream_timeout_returns_504():
    """When upstream times out, gateway returns 504."""
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(side_effect=httpx.ReadTimeout("read timed out"))

    with patch("main.get_redis", new=AsyncMock(return_value=AsyncMock())):
        app.dependency_overrides[get_client_id] = lambda: CLIENT_ID
        try:
            with patch("main.check_rate_limit", new=AsyncMock(return_value=(True, 95.0))):
                with TestClient(app) as c:
                    app.state.http_client = mock_http
                    response = c.get("/api/v1/products")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 504


def test_redis_down_returns_503():
    """When Redis is unreachable during rate limiting, gateway returns 503."""
    with patch("main.get_redis", new=AsyncMock(return_value=AsyncMock())):
        app.dependency_overrides[get_client_id] = lambda: CLIENT_ID
        try:
            with patch("main.check_rate_limit", new=AsyncMock(side_effect=ConnectionError("Redis down"))):
                with TestClient(app) as c:
                    response = c.get("/api/v1/products")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 503
