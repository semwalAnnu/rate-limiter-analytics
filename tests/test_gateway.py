"""Integration tests for the FastAPI gateway.

Stubs — implemented in Phase 2 once the full gateway is wired up.
"""
import pytest


@pytest.mark.skip(reason="TODO: implement after gateway is wired up")
def test_health_endpoint_returns_200():
    pass


@pytest.mark.skip(reason="TODO: implement after auth.py is complete")
def test_request_without_jwt_returns_401():
    pass


@pytest.mark.skip(reason="TODO: implement after rate_limiter is complete")
def test_rate_limited_request_returns_429():
    pass


@pytest.mark.skip(reason="TODO: implement after rate_limiter is complete")
def test_allowed_request_proxied_to_upstream():
    pass
