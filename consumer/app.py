"""Faust stream processor.

Reads RequestEvent messages from Kafka → inserts raw events into TimescaleDB →
aggregates into 1-minute rollups and flushes completed minutes.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import asyncpg
import faust

from consumer_helpers import Aggregator, flush_rollups, insert_raw_event

logger = logging.getLogger(__name__)

KAFKA_BROKER = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TIMESCALE_URL = os.environ.get("TIMESCALE_URL", "postgresql://metrics_user:metrics_pass@localhost:5432/metrics")

app = faust.App(
    "rate-limiter-consumer",
    broker=f"kafka://{KAFKA_BROKER}",
    value_serializer="json",
)

request_events_topic = app.topic("request_events")

aggregator = Aggregator()
db_pool = None


@app.task
async def on_started():
    """Create the asyncpg connection pool when the worker starts."""
    global db_pool
    db_pool = await asyncpg.create_pool(dsn=TIMESCALE_URL, min_size=2, max_size=10)
    logger.info("connected to timescaledb")


@app.agent(request_events_topic)
async def process_events(events):
    """Consume request events: write raw rows and flush rollups."""
    async for event in events:
        try:
            await insert_raw_event(db_pool, event)
        except Exception:
            logger.exception("failed to insert raw event")
            continue

        aggregator.add(event)

        now = datetime.now(timezone.utc).isoformat()
        completed = aggregator.flush_completed(now)
        if completed:
            try:
                await flush_rollups(db_pool, completed)
                logger.info("flushed %d rollup rows", len(completed))
            except Exception:
                logger.exception("failed to flush rollups")


@app.on_shutdown.connect
async def on_shutdown(sender, **kwargs):
    """Flush remaining aggregates and close the DB pool on shutdown."""
    global db_pool
    if db_pool:
        now = datetime.now(timezone.utc).replace(year=2099).isoformat()
        remaining = aggregator.flush_completed(now)
        if remaining:
            try:
                await flush_rollups(db_pool, remaining)
            except Exception:
                logger.exception("failed to flush remaining rollups on shutdown")
        await db_pool.close()


if __name__ == "__main__":
    app.main()
