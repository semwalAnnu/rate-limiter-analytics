"""Kafka producer for request events.

Publishes RequestEvent JSON to the configured topic. Uses leader-ack
delivery (acks=1) with batching (linger_ms=10). Errors are logged, never raised.
"""
from __future__ import annotations

import json
import logging

from aiokafka import AIOKafkaProducer

from config import settings
from models import RequestEvent

logger = logging.getLogger(__name__)


async def get_producer() -> AIOKafkaProducer:
    """Create and start an AIOKafkaProducer. Call once at startup."""
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks=1,
        linger_ms=10,
        max_batch_size=16384,
    )
    await producer.start()
    return producer


async def publish_event(producer: AIOKafkaProducer | None, event: RequestEvent) -> None:
    """Serialize *event* to JSON and send to Kafka topic.

    No-op if producer is None. Errors are logged but never raised.
    """
    if producer is None:
        return
    try:
        payload = json.dumps(event.model_dump(mode="json")).encode("utf-8")
        await producer.send(settings.kafka_topic, value=payload)
    except Exception:
        logger.exception("failed to publish event to kafka")
