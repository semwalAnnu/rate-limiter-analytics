"""Unit tests for the Faust consumer aggregation and DB write logic.

Tests the helper functions directly — no running Faust/Kafka/TimescaleDB needed.

Run:
    docker compose run --rm test pytest tests/test_consumer.py -v
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from consumer_helpers import (
    insert_raw_event,
    flush_rollups,
    Aggregator,
)


def _event(client_id="client_a", endpoint="/api/v1/products", status="allowed",
           latency_ms=10.0, ts="2026-01-01T00:00:30Z"):
    return {
        "event_id": "test-uuid",
        "timestamp": ts,
        "client_id": client_id,
        "endpoint": endpoint,
        "method": "GET",
        "status": status,
        "latency_ms": latency_ms,
        "tokens_remaining": 90.0,
        "upstream_status": 200 if status == "allowed" else None,
    }


class TestInsertRawEvent:
    def test_inserts_correct_columns(self):
        """insert_raw_event should INSERT into request_events with mapped fields."""
        pool = AsyncMock()
        event = _event()
        asyncio.run(insert_raw_event(pool, event))
        pool.execute.assert_awaited_once()
        sql = pool.execute.call_args.args[0]
        assert "request_events" in sql

    def test_maps_timestamp_to_time_column(self):
        """timestamp field should be parsed to datetime for the 'time' column."""
        pool = AsyncMock()
        event = _event(ts="2026-06-15T12:30:00Z")
        asyncio.run(insert_raw_event(pool, event))
        time_arg = pool.execute.call_args.args[1]
        assert isinstance(time_arg, datetime)
        assert time_arg.year == 2026
        assert time_arg.month == 6


class TestAggregator:
    def test_add_increments_counters(self):
        """Adding an allowed event should increment total and allowed."""
        agg = Aggregator()
        agg.add(_event(status="allowed", latency_ms=10.0))
        assert len(agg.buckets) == 1
        bucket = list(agg.buckets.values())[0]
        assert bucket["total_requests"] == 1
        assert bucket["allowed"] == 1
        assert bucket["rejected"] == 0

    def test_add_rejected_increments_rejected(self):
        """Adding a rejected event should increment rejected counter."""
        agg = Aggregator()
        agg.add(_event(status="rejected", latency_ms=0.0))
        bucket = list(agg.buckets.values())[0]
        assert bucket["rejected"] == 1

    def test_add_tracks_latencies(self):
        """Aggregator should store latency values for p99 computation."""
        agg = Aggregator()
        agg.add(_event(latency_ms=10.0))
        agg.add(_event(latency_ms=20.0))
        agg.add(_event(latency_ms=30.0))
        bucket = list(agg.buckets.values())[0]
        assert len(bucket["latencies"]) == 3

    def test_flush_computes_avg_and_p99(self):
        """flush() should compute correct avg and p99 latency."""
        agg = Aggregator()
        for i in range(100):
            agg.add(_event(latency_ms=float(i)))
        rows = agg.flush_completed("2026-01-01T00:01:00Z")
        assert len(rows) == 1
        row = rows[0]
        assert row["total_requests"] == 100
        assert row["avg_latency_ms"] == pytest.approx(49.5)
        assert row["p99_latency_ms"] == pytest.approx(99.0, abs=1.0)

    def test_flush_only_completed_minutes(self):
        """flush_completed should not flush the current minute."""
        agg = Aggregator()
        agg.add(_event(ts="2026-01-01T00:00:30Z"))
        rows = agg.flush_completed("2026-01-01T00:00:45Z")
        assert len(rows) == 0

    def test_flush_removes_flushed_buckets(self):
        """Flushed buckets should be removed from internal state."""
        agg = Aggregator()
        agg.add(_event(ts="2026-01-01T00:00:30Z"))
        agg.flush_completed("2026-01-01T00:01:00Z")
        assert len(agg.buckets) == 0


class TestFlushRollups:
    def test_inserts_rows_to_metrics_table(self):
        """flush_rollups should INSERT each row into request_metrics_1m."""
        pool = AsyncMock()
        rows = [
            {
                "bucket": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "client_id": "client_a",
                "endpoint": "/api/v1/products",
                "total_requests": 10,
                "allowed": 8,
                "rejected": 2,
                "avg_latency_ms": 15.0,
                "p99_latency_ms": 45.0,
            }
        ]
        asyncio.run(flush_rollups(pool, rows))
        pool.execute.assert_awaited_once()
        sql = pool.execute.call_args.args[0]
        assert "request_metrics_1m" in sql
