"""Unit tests for JWT authentication middleware.

Calls get_client_id() directly (bypassing FastAPI's DI) so no running server
is needed. PyJWT is used to mint test tokens.

Run:
    docker compose run --rm test pytest tests/test_auth.py -v
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from auth import get_client_id
from config import settings

SECRET = "test-secret"
WRONG_SECRET = "wrong-secret"
ALGORITHM = "HS256"


def _token(payload: dict, secret: str = SECRET) -> str:
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def _valid_payload(sub: str = "client_abc") -> dict:
    return {"sub": sub, "exp": int(time.time()) + 3600}


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_valid_token_returns_client_id():
    """A well-formed Bearer JWT with 'sub' and 'exp' claims returns the client_id."""
    original_secret = settings.jwt_secret
    settings.jwt_secret = SECRET
    try:
        token = _token(_valid_payload("client_abc"))
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


def test_token_without_exp_raises_401():
    """A JWT missing the 'exp' claim → HTTP 401."""
    token = _token({"sub": "client_abc"})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_client_id(authorization=f"Bearer {token}"))
    assert exc.value.status_code == 401


def test_token_without_sub_raises_401():
    """A valid JWT that is missing the 'sub' claim → HTTP 401."""
    token = _token({"exp": int(time.time()) + 3600})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_client_id(authorization=f"Bearer {token}"))
    assert exc.value.status_code == 401


def test_wrong_secret_raises_401():
    """A JWT signed with the wrong secret → HTTP 401."""
    token = _token(_valid_payload(), secret=WRONG_SECRET)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_client_id(authorization=f"Bearer {token}"))
    assert exc.value.status_code == 401


def test_invalid_client_id_format_raises_401():
    """A JWT with a client_id containing invalid characters → HTTP 401."""
    original_secret = settings.jwt_secret
    settings.jwt_secret = SECRET
    try:
        token = _token({"sub": "client:with:colons", "exp": int(time.time()) + 3600})
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_client_id(authorization=f"Bearer {token}"))
        assert exc.value.status_code == 401
    finally:
        settings.jwt_secret = original_secret


def test_oversized_client_id_raises_401():
    """A JWT with an excessively long client_id → HTTP 401."""
    original_secret = settings.jwt_secret
    settings.jwt_secret = SECRET
    try:
        token = _token({"sub": "a" * 200, "exp": int(time.time()) + 3600})
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_client_id(authorization=f"Bearer {token}"))
        assert exc.value.status_code == 401
    finally:
        settings.jwt_secret = original_secret
