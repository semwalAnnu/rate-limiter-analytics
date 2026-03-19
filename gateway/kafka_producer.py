"""Fire-and-forget Kafka producer.

Publishes RequestEvent JSON to the configured topic without blocking
the hot path — errors are logged but never raised to the caller.
"""
from __future__ import annotations

from aiokafka import AIOKafkaProducer

from config import settings
from models import RequestEvent


async def get_producer() -> AIOKafkaProducer:
    """Create and start an AIOKafkaProducer. Call once at startup."""
    raise NotImplementedError


async def publish_event(producer: AIOKafkaProducer, event: RequestEvent) -> None:
    """Serialize *event* to JSON and send to Kafka topic (fire-and-forget)."""
    raise NotImplementedError
