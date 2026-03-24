"""Unit tests for the Kafka producer module.

Run:
    docker compose run --rm test pytest tests/test_kafka_producer.py -v
"""
from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest

from kafka_producer import get_producer, publish_event
from models import RequestEvent


def test_get_producer_creates_and_starts_producer():
    """get_producer() should create an AIOKafkaProducer and call start()."""
    mock_producer = AsyncMock()
    with patch("kafka_producer.AIOKafkaProducer", return_value=mock_producer) as mock_cls:
        producer = asyncio.run(get_producer())
    mock_cls.assert_called_once()
    mock_producer.start.assert_awaited_once()
    assert producer is mock_producer


def test_get_producer_passes_config():
    """get_producer() should use settings for bootstrap_servers and acks."""
    mock_producer = AsyncMock()
    with patch("kafka_producer.AIOKafkaProducer", return_value=mock_producer) as mock_cls:
        asyncio.run(get_producer())
    call_kwargs = mock_cls.call_args.kwargs
    assert "bootstrap_servers" in call_kwargs
    assert call_kwargs["acks"] == 1


def test_publish_event_sends_json():
    """publish_event() should serialize the event and send to the configured topic."""
    mock_producer = AsyncMock()
    event = RequestEvent(
        client_id="client_abc",
        endpoint="/api/v1/products",
        method="GET",
        status="allowed",
        latency_ms=12.5,
        tokens_remaining=87.0,
        upstream_status=200,
    )
    asyncio.run(publish_event(mock_producer, event))
    mock_producer.send.assert_awaited_once()
    call_args = mock_producer.send.call_args
    assert call_args.args[0] == "request_events"
    payload = json.loads(call_args.kwargs["value"])
    assert payload["client_id"] == "client_abc"
    assert payload["status"] == "allowed"
    assert payload["latency_ms"] == 12.5


def test_publish_event_noop_when_producer_is_none():
    """publish_event() should silently do nothing if producer is None."""
    event = RequestEvent(
        client_id="client_abc",
        endpoint="/api/v1/products",
        method="GET",
        status="allowed",
        latency_ms=0.0,
        tokens_remaining=99.0,
    )
    asyncio.run(publish_event(None, event))


def test_publish_event_logs_error_on_failure(caplog):
    """publish_event() should log errors but never raise."""
    mock_producer = AsyncMock()
    mock_producer.send = AsyncMock(side_effect=Exception("kafka down"))
    event = RequestEvent(
        client_id="client_abc",
        endpoint="/api/v1/products",
        method="GET",
        status="rejected",
        latency_ms=0.0,
        tokens_remaining=0.0,
    )
    with caplog.at_level(logging.ERROR):
        asyncio.run(publish_event(mock_producer, event))
    assert "failed to publish event to kafka" in caplog.text
