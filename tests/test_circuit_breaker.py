"""Unit tests for the per-endpoint circuit breaker.

Run:
    docker compose run --rm test pytest tests/test_circuit_breaker.py -v
"""
from __future__ import annotations

from unittest.mock import patch

from circuit_breaker import CircuitBreaker, CircuitState


def test_starts_closed():
    cb = CircuitBreaker()
    assert cb.state == CircuitState.CLOSED
    assert not cb.is_open


def test_stays_closed_below_threshold():
    cb = CircuitBreaker(failure_threshold=5)
    for _ in range(4):
        cb.record_failure()
    assert cb.state == CircuitState.CLOSED


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=3)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.is_open


def test_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED


def test_transitions_to_half_open_after_timeout():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # simulate time passing beyond recovery timeout
    with patch("circuit_breaker.time") as mock_time:
        mock_time.monotonic.return_value = cb._opened_at + 11.0
        assert cb.state == CircuitState.HALF_OPEN
        assert not cb.is_open


def test_half_open_closes_on_success():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
    cb.record_failure()

    with patch("circuit_breaker.time") as mock_time:
        mock_time.monotonic.return_value = cb._opened_at + 11.0
        assert cb.state == CircuitState.HALF_OPEN

    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_half_open_reopens_on_failure():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
    cb.record_failure()

    with patch("circuit_breaker.time") as mock_time:
        mock_time.monotonic.return_value = cb._opened_at + 11.0
        assert cb.state == CircuitState.HALF_OPEN

    cb.record_failure()
    assert cb.state == CircuitState.OPEN
