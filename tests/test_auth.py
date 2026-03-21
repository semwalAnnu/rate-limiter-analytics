"""Unit tests for JWT authentication middleware.

Calls get_client_id() directly (bypassing FastAPI's DI) so no running server
is needed. python-jose is used to mint test tokens.

Run:
    pytest tests/test_auth.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from jose import jwt

# Stub config before importing auth so pydantic-settings doesn't read .env
_mock_settings = MagicMock()
_mock_settings.jwt_secret = "test-secret"
_mock_config = MagicMock()
_mock_config.settings = _mock_settings
sys.modules["config"] = _mock_config

# gateway/ is a sibling of tests/ — add it so we can import auth directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gateway"))

from auth import get_client_id  # noqa: E402  (must come after sys.path)

SECRET = "test-secret"
WRONG_SECRET = "wrong-secret"
ALGORITHM = "HS256"


def _token(payload: dict, secret: str = SECRET) -> str:
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_valid_token_returns_client_id():
    """A well-formed Bearer JWT with a 'sub' claim returns the client_id."""
    token = _token({"sub": "client_abc"})
    result = asyncio.run(get_client_id(authorization=f"Bearer {token}"))
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
