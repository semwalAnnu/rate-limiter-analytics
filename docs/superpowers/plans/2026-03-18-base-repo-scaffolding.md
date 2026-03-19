# Base Repo Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the full directory scaffold, config files, Dockerfiles, requirements stubs, and initial commit + push for the rate-limiter-analytics project.

**Architecture:** All infrastructure is Docker Compose; the gateway, consumer, upstream, and load_test components each live in their own directory with a Dockerfile and requirements.txt. Secrets are never committed — only .env.example is tracked.

**Tech Stack:** Python 3.11, FastAPI, Redis, Kafka, TimescaleDB, Grafana, Locust, Faust, Jupyter

---

## File Map

| File / Dir | Action | Responsibility |
|---|---|---|
| `.gitignore` | Create | Excludes .env, __pycache__, .ipynb_checkpoints, etc. |
| `.env.example` | Create | Template for all env vars (no secrets) |
| `README.md` | Create | Project overview stub (to be filled after benchmarks) |
| `docker-compose.yml` | Create | Wires Redis, Kafka, Zookeeper, TimescaleDB, Grafana, gateway, consumer, upstream |
| `gateway/Dockerfile` | Create | Python 3.11-slim, installs requirements, runs uvicorn |
| `gateway/requirements.txt` | Create | fastapi, uvicorn, aioredis, aiokafka, python-jose, pydantic-settings |
| `gateway/config.py` | Create | Pydantic Settings loading from .env |
| `gateway/main.py` | Create | FastAPI stub — single health check endpoint |
| `gateway/rate_limiter.py` | Create | Stub with function signatures only |
| `gateway/kafka_producer.py` | Create | Stub with function signatures only |
| `gateway/circuit_breaker.py` | Create | Stub with function signatures only |
| `gateway/auth.py` | Create | Stub with function signatures only |
| `gateway/models.py` | Create | Pydantic request/response models (full, not stub) |
| `consumer/Dockerfile` | Create | Python 3.11-slim, runs faust worker |
| `consumer/requirements.txt` | Create | faust-streaming, asyncpg, python-dotenv |
| `consumer/app.py` | Create | Faust app stub — topic defined, agent stub |
| `upstream/Dockerfile` | Create | Python 3.11-slim, runs uvicorn |
| `upstream/requirements.txt` | Create | fastapi, uvicorn |
| `upstream/main.py` | Create | Two simple endpoints: /products, /orders |
| `load_tests/requirements.txt` | Create | locust |
| `load_tests/locustfile.py` | Create | Locust stub with two user classes |
| `notebooks/traffic_analysis.ipynb` | Create | Jupyter stub with section headers |
| `grafana/provisioning/datasources/timescaledb.yml` | Create | Auto-connects Grafana to TimescaleDB |
| `grafana/provisioning/dashboards/provider.yml` | Create | Tells Grafana where to find dashboard JSONs |
| `grafana/provisioning/dashboards/main.json` | Create | Minimal stub dashboard (7 panels defined, no queries yet) |
| `tests/conftest.py` | Create | pytest fixtures stub |
| `tests/test_rate_limiter.py` | Create | Placeholder tests (skipped with TODO markers) |
| `tests/test_gateway.py` | Create | Placeholder tests (skipped with TODO markers) |
| `docs/superpowers/plans/` | Keep | This plan lives here |

---

### Task 1: Root config files — .gitignore, .env.example, README.md

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`

- [ ] **Step 1: Create .gitignore**

```gitignore
# Secrets
.env

# Python
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
dist/
build/
*.so
.venv/
venv/
env/

# Jupyter
.ipynb_checkpoints/
*.ipynb_checkpoints

# macOS
.DS_Store

# IDE
.idea/
.vscode/
*.swp

# Docker
*.log

# Test / coverage
.pytest_cache/
.coverage
htmlcov/
```

- [ ] **Step 2: Create .env.example**

```env
# Redis
REDIS_URL=redis://redis:6379

# Kafka
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
KAFKA_TOPIC=request_events

# TimescaleDB
TIMESCALE_URL=postgresql://metrics_user:metrics_pass@timescaledb:5432/metrics

# Gateway
RATE_LIMIT_CAPACITY=100
RATE_LIMIT_REFILL_RATE=10
JWT_SECRET=change-me-in-production
UPSTREAM_URL=http://upstream:8001

# Grafana
GF_SECURITY_ADMIN_PASSWORD=admin
GF_SECURITY_ADMIN_USER=admin
```

- [ ] **Step 3: Create README.md stub**

```markdown
# Rate Limiter + Real-Time Analytics Platform

A Python API gateway with token-bucket rate limiting backed by Redis, streaming all request events through Kafka → Faust → TimescaleDB → Grafana.

## Architecture

```
Clients (Locust)
    │
    ▼
[FastAPI Gateway] ──► [Redis]  (token buckets)
    │
    ├──► [Mock Upstream]
    │
    └──► [Kafka] ──► [Faust Consumer] ──► [TimescaleDB]
                                               │
                                         [Grafana]  [Jupyter]
```

## Quick Start

```bash
cp .env.example .env
docker compose up -d
# Gateway:  http://localhost:8000
# Grafana:  http://localhost:3000  (admin/admin)
# Jupyter:  http://localhost:8888
```

## Running Tests

```bash
pytest tests/ -v
```

## Load Testing

```bash
cd load_tests && locust --host=http://localhost:8000
```

## Benchmark Results

> To be filled after running Locust at 500 concurrent users for 5 minutes.

| Metric | Target | Actual |
|---|---|---|
| Gateway throughput | 5,000+ req/s | TBD |
| Rate limit overhead (p99) | < 5ms | TBD |
| False positives | 0 | TBD |
| Kafka lag | < 1s | TBD |
| Grafana lag | < 5s | TBD |
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore .env.example README.md
git commit -m "chore: add root config files (gitignore, env example, readme stub)"
```

---

### Task 2: docker-compose.yml

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
version: "3.9"

networks:
  frontend:       # gateway ↔ clients and gateway ↔ upstream
  backend:        # gateway ↔ Redis, Kafka, TimescaleDB; consumer ↔ Kafka, TimescaleDB

services:
  # ── Infrastructure ────────────────────────────────────────────

  redis:
    image: redis:7-alpine
    networks: [backend]
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5

  zookeeper:
    image: confluentinc/cp-zookeeper:7.6.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
    networks: [backend]

  kafka:
    image: confluentinc/cp-kafka:7.6.0
    depends_on: [zookeeper]
    networks: [backend]
    ports: ["9092:9092"]
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
    healthcheck:
      test: ["CMD", "kafka-topics", "--bootstrap-server", "localhost:9092", "--list"]
      interval: 10s
      retries: 10

  timescaledb:
    image: timescale/timescaledb:latest-pg15
    networks: [backend]
    ports: ["5432:5432"]
    environment:
      POSTGRES_USER: metrics_user
      POSTGRES_PASSWORD: metrics_pass
      POSTGRES_DB: metrics
    volumes:
      - timescale_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U metrics_user -d metrics"]
      interval: 5s
      retries: 10

  grafana:
    image: grafana/grafana:10.3.3
    networks: [backend]
    ports: ["3000:3000"]
    depends_on: [timescaledb]
    environment:
      GF_SECURITY_ADMIN_USER: ${GF_SECURITY_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GF_SECURITY_ADMIN_PASSWORD:-admin}
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning
      - grafana_data:/var/lib/grafana

  # ── Application services ───────────────────────────────────────

  upstream:
    build: ./upstream
    networks: [frontend]
    ports: ["8001:8001"]

  gateway:
    build: ./gateway
    networks: [frontend, backend]
    ports: ["8000:8000"]
    depends_on:
      redis:
        condition: service_healthy
      kafka:
        condition: service_healthy
      timescaledb:
        condition: service_healthy
    env_file: .env
    environment:
      UPSTREAM_URL: http://upstream:8001

  consumer:
    build: ./consumer
    networks: [backend]
    depends_on:
      kafka:
        condition: service_healthy
      timescaledb:
        condition: service_healthy
    env_file: .env

  jupyter:
    image: jupyter/scipy-notebook:latest
    networks: [backend]
    ports: ["8888:8888"]
    volumes:
      - ./notebooks:/home/jovyan/work
    environment:
      JUPYTER_ENABLE_LAB: "yes"

volumes:
  timescale_data:
  grafana_data:
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add docker-compose with full infrastructure stack"
```

---

### Task 3: Gateway scaffolding

**Files:**
- Create: `gateway/Dockerfile`
- Create: `gateway/requirements.txt`
- Create: `gateway/config.py`
- Create: `gateway/models.py`
- Create: `gateway/main.py`
- Create: `gateway/rate_limiter.py`
- Create: `gateway/kafka_producer.py`
- Create: `gateway/circuit_breaker.py`
- Create: `gateway/auth.py`

- [ ] **Step 1: gateway/Dockerfile**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: gateway/requirements.txt**

```
fastapi==0.110.0
uvicorn[standard]==0.27.1
aioredis==2.0.1
aiokafka==0.10.0
python-jose[cryptography]==3.3.0
pydantic-settings==2.2.1
httpx==0.27.0
```

- [ ] **Step 3: gateway/config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "request_events"
    timescale_url: str = "postgresql://metrics_user:metrics_pass@localhost:5432/metrics"
    rate_limit_capacity: float = 100.0
    rate_limit_refill_rate: float = 10.0  # tokens per second
    jwt_secret: str = "change-me-in-production"
    upstream_url: str = "http://localhost:8001"

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 4: gateway/models.py**

```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RequestEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    client_id: str
    endpoint: str
    method: str
    status: Literal["allowed", "rejected", "circuit_open"]
    latency_ms: float
    tokens_remaining: float
    upstream_status: Optional[int] = None


class RateLimitResponse(BaseModel):
    detail: str
    client_id: str
    retry_after_seconds: float
```

- [ ] **Step 5: gateway/rate_limiter.py (stub)**

```python
"""Token bucket rate limiter backed by Redis (aioredis).

Each client gets two Redis keys:
  bucket:{client_id}:tokens      — current token count (float)
  bucket:{client_id}:last_refill — Unix timestamp of last refill

All Redis calls are async to keep the gateway non-blocking.
"""
from __future__ import annotations

from typing import Tuple

import aioredis

from config import settings


async def get_redis() -> aioredis.Redis:
    """Return a connected aioredis client.  Call once at startup."""
    raise NotImplementedError


async def check_rate_limit(redis: aioredis.Redis, client_id: str) -> Tuple[bool, float]:
    """Check whether *client_id* is within its rate limit.

    Returns:
        (allowed, tokens_remaining)
        allowed=True  → request may proceed
        allowed=False → request must be rejected with HTTP 429
    """
    raise NotImplementedError
```

- [ ] **Step 6: gateway/kafka_producer.py (stub)**

```python
"""Fire-and-forget Kafka producer.

Publishes RequestEvent JSON to the configured topic without blocking
the hot path — errors are logged but never raised to the caller.
"""
from __future__ import annotations

from aiokafka import AIOKafkaProducer

from config import settings
from models import RequestEvent


async def get_producer() -> AIOKafkaProducer:
    """Create and start an AIOKafkaProducer.  Call once at startup."""
    raise NotImplementedError


async def publish_event(producer: AIOKafkaProducer, event: RequestEvent) -> None:
    """Serialize *event* to JSON and send to Kafka topic (fire-and-forget)."""
    raise NotImplementedError
```

- [ ] **Step 7: gateway/circuit_breaker.py (stub)**

```python
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
```

- [ ] **Step 8: gateway/auth.py (stub)**

```python
"""JWT validation middleware.

Expects a Bearer token in the Authorization header.
Extracts client_id from the 'sub' claim.
"""
from __future__ import annotations

from fastapi import Header, HTTPException


async def get_client_id(authorization: str = Header(...)) -> str:
    """Validate JWT and return the client_id (sub claim).

    Raises HTTP 401 if the token is missing or invalid.
    """
    raise NotImplementedError
```

- [ ] **Step 9: gateway/main.py (health check stub)**

```python
"""FastAPI gateway entry point.

Startup: connect Redis, start Kafka producer.
Every request: validate JWT → check rate limit → proxy to upstream →
               publish event to Kafka.
"""
from fastapi import FastAPI

app = FastAPI(title="Rate Limiter Gateway")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 10: Commit**

```bash
git add gateway/
git commit -m "feat: add gateway scaffolding (Dockerfile, config, models, stubs)"
```

---

### Task 4: Consumer scaffolding

**Files:**
- Create: `consumer/Dockerfile`
- Create: `consumer/requirements.txt`
- Create: `consumer/app.py`

- [ ] **Step 1: consumer/Dockerfile**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "app.py", "worker", "-l", "info"]
```

- [ ] **Step 2: consumer/requirements.txt**

```
faust-streaming==0.10.14
asyncpg==0.29.0
python-dotenv==1.0.1
```

- [ ] **Step 3: consumer/app.py (stub)**

```python
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
```

- [ ] **Step 4: Commit**

```bash
git add consumer/
git commit -m "feat: add faust consumer scaffolding"
```

---

### Task 5: Upstream mock services

**Files:**
- Create: `upstream/Dockerfile`
- Create: `upstream/requirements.txt`
- Create: `upstream/main.py`

- [ ] **Step 1: upstream/Dockerfile**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
```

- [ ] **Step 2: upstream/requirements.txt**

```
fastapi==0.110.0
uvicorn[standard]==0.27.1
```

- [ ] **Step 3: upstream/main.py**

```python
"""Mock upstream services simulating real backends.

/api/v1/products — returns a fake product list
/api/v1/orders   — returns a fake order list

Adds a small random delay to simulate real-world latency.
"""
from __future__ import annotations

import asyncio
import random

from fastapi import FastAPI

app = FastAPI(title="Mock Upstream")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/products")
async def get_products() -> dict:
    await asyncio.sleep(random.uniform(0.001, 0.010))  # 1–10 ms simulated latency
    return {
        "products": [
            {"id": 1, "name": "Widget A", "price": 9.99},
            {"id": 2, "name": "Widget B", "price": 19.99},
        ]
    }


@app.get("/api/v1/orders")
async def get_orders() -> dict:
    await asyncio.sleep(random.uniform(0.001, 0.010))
    return {
        "orders": [
            {"id": 101, "product_id": 1, "quantity": 3},
            {"id": 102, "product_id": 2, "quantity": 1},
        ]
    }
```

- [ ] **Step 4: Commit**

```bash
git add upstream/
git commit -m "feat: add mock upstream services"
```

---

### Task 6: Load tests, notebooks, Grafana provisioning

**Files:**
- Create: `load_tests/requirements.txt`
- Create: `load_tests/locustfile.py`
- Create: `notebooks/traffic_analysis.ipynb`
- Create: `grafana/provisioning/datasources/timescaledb.yml`
- Create: `grafana/provisioning/dashboards/provider.yml`
- Create: `grafana/provisioning/dashboards/main.json`

- [ ] **Step 1: load_tests/requirements.txt**

```
locust==2.24.0
```

- [ ] **Step 2: load_tests/locustfile.py**

```python
"""Locust load test simulating multiple client profiles.

Run:
    locust --host=http://localhost:8000

Profiles:
  - NormalUser:   moderate traffic, stays within rate limit
  - AggressiveUser: hammers the gateway to trigger 429 responses
"""
from __future__ import annotations

import random

from locust import HttpUser, between, task


def _auth_header(client_id: str) -> dict:
    # TODO: generate a real JWT once auth.py is implemented
    return {"X-API-Key": client_id}


class NormalUser(HttpUser):
    wait_time = between(0.1, 0.5)
    weight = 4

    @task(3)
    def get_products(self):
        client_id = f"normal-{self.user_id % 50}"
        self.client.get(
            "/api/v1/products",
            headers=_auth_header(client_id),
            name="/api/v1/products",
        )

    @task(1)
    def get_orders(self):
        client_id = f"normal-{self.user_id % 50}"
        self.client.get(
            "/api/v1/orders",
            headers=_auth_header(client_id),
            name="/api/v1/orders",
        )


class AggressiveUser(HttpUser):
    wait_time = between(0.001, 0.01)
    weight = 1

    @task
    def hammer_products(self):
        client_id = f"aggressive-{self.user_id % 5}"
        self.client.get(
            "/api/v1/products",
            headers=_auth_header(client_id),
            name="/api/v1/products [aggressive]",
        )
```

- [ ] **Step 3: notebooks/traffic_analysis.ipynb (minimal stub)**

```json
{
 "nbformat": 4,
 "nbformat_minor": 5,
 "metadata": {
  "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
  "language_info": {"name": "python", "version": "3.11.0"}
 },
 "cells": [
  {"cell_type": "markdown", "metadata": {}, "source": ["# Rate Limiter Traffic Analysis\n", "\nBatch analysis of request events stored in TimescaleDB."]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": [
   "import pandas as pd\n",
   "import sqlalchemy\n",
   "import matplotlib.pyplot as plt\n",
   "import os\n",
   "\n",
   "engine = sqlalchemy.create_engine(os.environ['TIMESCALE_URL'])"
  ]},
  {"cell_type": "markdown", "metadata": {}, "source": ["## 1. Which hour of the day has the highest rejection rate?"]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": ["# TODO"]},
  {"cell_type": "markdown", "metadata": {}, "source": ["## 2. Are there clients with automated request patterns?"]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": ["# TODO"]},
  {"cell_type": "markdown", "metadata": {}, "source": ["## 3. Correlation between traffic volume and p99 latency"]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": ["# TODO"]},
  {"cell_type": "markdown", "metadata": {}, "source": ["## 4. Most-hit endpoint by rejected clients"]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": ["# TODO"]},
  {"cell_type": "markdown", "metadata": {}, "source": ["## 5. Pareto: top 3 clients' share of total rejections"]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": ["# TODO"]}
 ]
}
```

- [ ] **Step 4: grafana/provisioning/datasources/timescaledb.yml**

```yaml
apiVersion: 1

datasources:
  - name: TimescaleDB
    type: postgres
    url: timescaledb:5432
    database: metrics
    user: metrics_user
    secureJsonData:
      password: metrics_pass
    jsonData:
      sslmode: disable
      postgresVersion: 1500
      timescaledb: true
    isDefault: true
    editable: false
```

- [ ] **Step 5: grafana/provisioning/dashboards/provider.yml**

```yaml
apiVersion: 1

providers:
  - name: default
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
```

- [ ] **Step 6: grafana/provisioning/dashboards/main.json**

Minimal valid Grafana dashboard JSON with 7 panel stubs (no queries yet — queries added in Phase 2).

```json
{
  "title": "Rate Limiter Analytics",
  "uid": "rate-limiter-main",
  "schemaVersion": 38,
  "version": 1,
  "refresh": "5s",
  "time": {"from": "now-30m", "to": "now"},
  "panels": [
    {"id": 1, "title": "Total Requests/sec",       "type": "timeseries", "gridPos": {"x":0,"y":0,"w":12,"h":8}},
    {"id": 2, "title": "Rejection Rate %",          "type": "timeseries", "gridPos": {"x":12,"y":0,"w":12,"h":8}},
    {"id": 3, "title": "Top 10 Clients by Traffic", "type": "barchart",   "gridPos": {"x":0,"y":8,"w":12,"h":8}},
    {"id": 4, "title": "Top 5 Clients by Rejections","type": "table",     "gridPos": {"x":12,"y":8,"w":12,"h":8}},
    {"id": 5, "title": "P99 Latency (ms)",          "type": "timeseries", "gridPos": {"x":0,"y":16,"w":12,"h":8}},
    {"id": 6, "title": "Requests by Endpoint",      "type": "piechart",   "gridPos": {"x":12,"y":16,"w":12,"h":8}},
    {"id": 7, "title": "Circuit Breaker Trips",     "type": "timeseries", "gridPos": {"x":0,"y":24,"w":24,"h":8}}
  ]
}
```

- [ ] **Step 7: Commit**

```bash
git add load_tests/ notebooks/ grafana/
git commit -m "feat: add load tests, notebook stub, and Grafana provisioning"
```

---

### Task 7: Test scaffolding

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_rate_limiter.py`
- Create: `tests/test_gateway.py`

- [ ] **Step 1: tests/conftest.py**

```python
"""pytest fixtures shared across all tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 2: tests/test_rate_limiter.py (placeholder)**

```python
"""Unit tests for the token bucket rate limiter.

These tests are stubs — they will be fleshed out in Phase 1
once rate_limiter.py is implemented.
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
```

- [ ] **Step 3: tests/test_gateway.py (placeholder)**

```python
"""Integration tests for the FastAPI gateway.

These tests are stubs — they will be fleshed out in Phase 2
once the full gateway is implemented.
"""
import pytest


@pytest.mark.skip(reason="TODO: implement after gateway is wired up")
def test_health_endpoint_returns_200():
    pass


@pytest.mark.skip(reason="TODO: implement after auth.py is complete")
def test_request_without_jwt_returns_401():
    pass


@pytest.mark.skip(reason="TODO: implement after rate_limiter is complete")
def test_rate_limited_request_returns_429():
    pass


@pytest.mark.skip(reason="TODO: implement after rate_limiter is complete")
def test_allowed_request_proxied_to_upstream():
    pass
```

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "feat: add test scaffolding with placeholder tests"
```

---

### Task 8: Push to GitHub

**Files:** None (git operations only)

- [ ] **Step 1: Create GitHub repo and push**

```bash
# Create public GitHub repo (requires gh CLI authenticated)
gh repo create rate-limiter-analytics \
  --public \
  --description "FastAPI gateway with Redis token-bucket rate limiting, Kafka analytics pipeline, TimescaleDB, and Grafana dashboard" \
  --source=. \
  --remote=origin \
  --push
```

- [ ] **Step 2: Verify**

```bash
gh repo view --web
```

Expected: GitHub repo opens in browser with clean commit history.

---

## Notes

- **Secrets:** `.env` is in `.gitignore`. Never commit it. Only `.env.example` is tracked.
- **Phase 2 work** (not in this plan): implement rate_limiter.py, kafka_producer.py, auth.py, circuit_breaker.py, wire everything in main.py, write real tests, fill Grafana queries, fill Jupyter notebook.
- **Two Docker networks** are intentional per CLAUDE.md: `frontend` (gateway ↔ upstream) and `backend` (gateway ↔ data tier).
