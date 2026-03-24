"""Helper functions for the Faust consumer.

Handles raw event insertion and 1-minute rollup aggregation.
Separated from app.py so the logic can be unit-tested without Faust.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime

logger = logging.getLogger(__name__)


async def insert_raw_event(pool, event: dict) -> None:
    """INSERT a single raw event into the request_events hypertable."""
    ts = datetime.fromisoformat(event["timestamp"])
    await pool.execute(
        """INSERT INTO request_events (time, client_id, endpoint, method, status,
           latency_ms, tokens_remaining, upstream_status)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
        ts,
        event["client_id"],
        event["endpoint"],
        event["method"],
        event["status"],
        event["latency_ms"],
        event["tokens_remaining"],
        event.get("upstream_status"),
    )


def _minute_bucket(ts_str: str) -> datetime:
    """Truncate an ISO timestamp string to the start of its minute."""
    dt = datetime.fromisoformat(ts_str)
    return dt.replace(second=0, microsecond=0)


class Aggregator:
    """In-memory accumulator for 1-minute rollup buckets.

    Stores counters and latency lists keyed by (client_id, endpoint, minute_bucket).
    Call flush_completed(current_time) to get rows for completed minutes.
    """

    def __init__(self):
        self.buckets: dict[tuple, dict] = {}

    def add(self, event: dict) -> None:
        minute = _minute_bucket(event["timestamp"])
        key = (event["client_id"], event["endpoint"], minute)

        if key not in self.buckets:
            self.buckets[key] = {
                "total_requests": 0,
                "allowed": 0,
                "rejected": 0,
                "latencies": [],
            }

        b = self.buckets[key]
        b["total_requests"] += 1
        if event["status"] == "allowed":
            b["allowed"] += 1
        elif event["status"] == "rejected":
            b["rejected"] += 1
        b["latencies"].append(event["latency_ms"])

    def flush_completed(self, current_time_iso: str) -> list[dict]:
        """Return rollup rows for minutes that have completed (not the current minute).

        Removes flushed buckets from the internal state.
        """
        current_minute = _minute_bucket(current_time_iso)
        completed = []
        keys_to_remove = []

        for key, b in self.buckets.items():
            client_id, endpoint, minute = key
            if minute < current_minute:
                latencies = sorted(b["latencies"])
                p99_idx = max(0, math.ceil(len(latencies) * 0.99) - 1)
                completed.append({
                    "bucket": minute,
                    "client_id": client_id,
                    "endpoint": endpoint,
                    "total_requests": b["total_requests"],
                    "allowed": b["allowed"],
                    "rejected": b["rejected"],
                    "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
                    "p99_latency_ms": latencies[p99_idx] if latencies else 0.0,
                })
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.buckets[key]

        return completed


async def flush_rollups(pool, rows: list[dict]) -> None:
    """INSERT rollup rows into request_metrics_1m using a batch insert."""
    if not rows:
        return
    args = [
        (
            row["bucket"],
            row["client_id"],
            row["endpoint"],
            row["total_requests"],
            row["allowed"],
            row["rejected"],
            row["avg_latency_ms"],
            row["p99_latency_ms"],
        )
        for row in rows
    ]
    await pool.executemany(
        """INSERT INTO request_metrics_1m (bucket, client_id, endpoint,
           total_requests, allowed, rejected, avg_latency_ms, p99_latency_ms)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
        args,
    )
