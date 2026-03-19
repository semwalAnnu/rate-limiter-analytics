"""Simple in-memory circuit breaker per upstream endpoint.

States: CLOSED → OPEN (after N failures) → HALF_OPEN (after timeout) → CLOSED
"""
from __future__ import annotations

from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Track failure rate and open/close the circuit accordingly."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        raise NotImplementedError

    def record_success(self) -> None:
        raise NotImplementedError

    def record_failure(self) -> None:
        raise NotImplementedError

    @property
    def is_open(self) -> bool:
        raise NotImplementedError
