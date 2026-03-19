"""JWT validation middleware.

Expects a Bearer token in the Authorization header.
Extracts client_id from the 'sub' claim.
"""
from __future__ import annotations

from fastapi import Header, HTTPException


async def get_client_id(authorization: str = Header(...)) -> str:
    """Validate JWT and return the client_id (sub claim).

    Raises HTTP 401 if the token is missing or invalid.
    """
    raise NotImplementedError
