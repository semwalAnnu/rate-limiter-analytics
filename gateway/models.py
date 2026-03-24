from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RequestEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    client_id: str
    endpoint: str
    method: str
    status: Literal["allowed", "rejected", "circuit_open"]
    latency_ms: float
    tokens_remaining: float
    upstream_status: Optional[int] = None


class RateLimitResponse(BaseModel):
    detail: str
    client_id: str
    retry_after_seconds: float
