"""Faust stream processor.

Reads RequestEvent messages from Kafka → aggregates into 1-minute buckets →
writes raw events and rollups to TimescaleDB.
"""
from __future__ import annotations

import faust

app = faust.App(
    "rate-limiter-consumer",
    broker="kafka://localhost:9092",
    value_serializer="json",
)

request_events_topic = app.topic("request_events")


@app.agent(request_events_topic)
async def process_events(events):
    """Consume request events and write to TimescaleDB."""
    async for event in events:
        # TODO: parse event, write raw row, update 1-minute rollup
        pass


if __name__ == "__main__":
    app.main()
