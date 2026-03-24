"""Unit tests for JWT authentication middleware.

Calls get_client_id() directly (bypassing FastAPI's DI) so no running server
is needed. python-jose is used to mint test tokens.

Run:
    docker compose run --rm test pytest tests/test_auth.py -v
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

from auth import get_client_id
from config import settings

SECRET = "test-secret"
WRONG_SECRET = "wrong-secret"
ALGORITHM = "HS256"


def _token(payload: dict, secret: str = SECRET) -> str:
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_valid_token_returns_client_id():
    """A well-formed Bearer JWT with a 'sub' claim returns the client_id."""
    original_secret = settings.jwt_secret
    settings.jwt_secret = SECRET
    try:
        token = _token({"sub": "client_abc"})
        result = asyncio.run(get_client_id(authorization=f"Bearer {token}"))
    finally:
        settings.jwt_secret = original_secret
    assert result == "client_abc"


def test_missing_authorization_header_raises_401():
    """No Authorization header at all → HTTP 401."""
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_client_id(authorization=None))
    assert exc.value.status_code == 401


def test_invalid_header_format_raises_401():
    """Authorization header present but not 'Bearer <token>' format → HTTP 401."""
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_client_id(authorization="NotBearerFormat"))
    assert exc.value.status_code == 401


def test_expired_token_raises_401():
    """A JWT whose 'exp' is in the past → HTTP 401."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    token = _token({"sub": "client_abc", "exp": past})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_client_id(authorization=f"Bearer {token}"))
    assert exc.value.status_code == 401


def test_token_without_sub_raises_401():
    """A valid JWT that is missing the 'sub' claim → HTTP 401."""
    token = _token({"iss": "test-issuer"})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_client_id(authorization=f"Bearer {token}"))
    assert exc.value.status_code == 401


def test_wrong_secret_raises_401():
    """A JWT signed with the wrong secret → HTTP 401."""
    token = _token({"sub": "client_abc"}, secret=WRONG_SECRET)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_client_id(authorization=f"Bearer {token}"))
    assert exc.value.status_code == 401
