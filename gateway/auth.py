"""JWT validation middleware.

Expects a Bearer token in the Authorization header.
Extracts client_id from the 'sub' claim.
"""
from __future__ import annotations

from fastapi import Header, HTTPException
from jose import JWTError, jwt

from config import settings


async def get_client_id(authorization: str | None = Header(None)) -> str:
    """Validate JWT and return the client_id (sub claim).

    Raises HTTP 401 if the token is missing or invalid.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = parts[1]
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    client_id = payload.get("sub")
    if not client_id:
        raise HTTPException(status_code=401, detail="Token missing subject claim")

    return client_id
