"""Integration tests for the API gateway routing layer.

Uses FastAPI TestClient (synchronous). Redis, Kafka, and the upstream HTTP
service are replaced with lightweight doubles — no running infrastructure needed.

Run:
    docker compose run --rm test pytest tests/test_gateway.py -v
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
import jwt

from auth import get_client_id
from main import app

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
    with patch("main.get_redis", return_value=AsyncMock()):
        with TestClient(app) as c:
            response = c.get("/health")
    assert response.status_code == 200


def test_unauthenticated_request_returns_401():
    """Request with no Authorization header is rejected before rate limiting."""
    with patch("main.get_redis", return_value=AsyncMock()):
        with TestClient(app) as c:
            response = c.get("/api/v1/products")
    assert response.status_code == 401


def test_allowed_request_proxied_to_upstream():
    """Valid JWT + tokens available → request forwarded, upstream response returned."""
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_fake_upstream(200))

    with patch("main.get_redis", return_value=AsyncMock()):
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
    with patch("main.get_redis", return_value=AsyncMock()):
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

    with patch("main.get_redis", return_value=AsyncMock()):
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

    with patch("main.get_redis", return_value=AsyncMock()):
        app.dependency_overrides[get_client_id] = lambda: CLIENT_ID
        try:
            with patch("main.check_rate_limit", new=AsyncMock(return_value=(True, 95.0))):
                with TestClient(app) as c:
                    app.state.http_client = mock_http
                    response = c.get("/api/v1/products")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 504


def test_allowed_request_publishes_event():
    """Allowed request publishes a Kafka event with latency and upstream status."""
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_fake_upstream(200))

    with patch("main.get_redis", return_value=AsyncMock()):
        app.dependency_overrides[get_client_id] = lambda: "pub-client"
        try:
            with patch("main.check_rate_limit", new=AsyncMock(return_value=(True, 95.0))):
                with patch("main.publish_event", new_callable=AsyncMock) as mock_publish:
                    with TestClient(app) as c:
                        app.state.http_client = mock_http
                        response = c.get("/api/v1/products")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_publish.assert_called_once()
    event = mock_publish.call_args[0][1]
    assert event.status == "allowed"
    assert event.client_id == "pub-client"
    assert event.endpoint == "products"
    assert event.latency_ms > 0
    assert event.upstream_status == 200


def test_rejected_request_publishes_event():
    """Rejected request publishes a Kafka event with status=rejected."""
    with patch("main.get_redis", return_value=AsyncMock()):
        app.dependency_overrides[get_client_id] = lambda: "rej-client"
        try:
            with patch("main.check_rate_limit", new=AsyncMock(return_value=(False, 0.3))):
                with patch("main.publish_event", new_callable=AsyncMock) as mock_publish:
                    with TestClient(app) as c:
                        response = c.get("/api/v1/products")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 429
    mock_publish.assert_called_once()
    event = mock_publish.call_args[0][1]
    assert event.status == "rejected"
    assert event.client_id == "rej-client"


def test_circuit_breaker_opens_after_upstream_failures():
    """After repeated upstream 5xx, circuit breaker trips and returns 503."""
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=_fake_upstream(500))

    with patch("main.get_redis", return_value=AsyncMock()):
        app.dependency_overrides[get_client_id] = lambda: CLIENT_ID
        try:
            with patch("main.check_rate_limit", new=AsyncMock(return_value=(True, 95.0))):
                with patch("main.publish_event", new_callable=AsyncMock) as mock_publish:
                    with TestClient(app) as c:
                        app.state.http_client = mock_http
                        # clear any existing breakers from previous tests
                        app.state.breakers = {}
                        # 5 failures to trip the breaker
                        for _ in range(5):
                            resp = c.get("/api/v1/cbtest")
                            assert resp.status_code == 500
                        # next request should be blocked by circuit breaker
                        resp = c.get("/api/v1/cbtest")
                        assert resp.status_code == 503

                        # check the last event was circuit_open
                        last_event = mock_publish.call_args[0][1]
                        assert last_event.status == "circuit_open"
        finally:
            app.dependency_overrides.clear()


def test_redis_down_returns_503():
    """When Redis is unreachable during rate limiting, gateway returns 503."""
    with patch("main.get_redis", return_value=AsyncMock()):
        app.dependency_overrides[get_client_id] = lambda: CLIENT_ID
        try:
            with patch("main.check_rate_limit", new=AsyncMock(side_effect=ConnectionError("Redis down"))):
                with TestClient(app) as c:
                    response = c.get("/api/v1/products")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 503
