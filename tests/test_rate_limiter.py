"""Unit tests for the token bucket rate limiter.

Stubs — implemented in Phase 1 once rate_limiter.py is complete.
"""
import pytest


@pytest.mark.skip(reason="TODO: implement after rate_limiter.py is complete")
def test_tokens_decrease_on_allowed_request():
    """Each allowed request should consume one token."""
    pass


@pytest.mark.skip(reason="TODO: implement after rate_limiter.py is complete")
def test_request_rejected_when_tokens_exhausted():
    """A request should be rejected (allowed=False) when tokens < 1."""
    pass


@pytest.mark.skip(reason="TODO: implement after rate_limiter.py is complete")
def test_tokens_refill_over_time():
    """Tokens should refill at RATE_LIMIT_REFILL_RATE tokens per second."""
    pass


@pytest.mark.skip(reason="TODO: implement after rate_limiter.py is complete")
def test_tokens_capped_at_capacity():
    """Token count must never exceed RATE_LIMIT_CAPACITY."""
    pass
