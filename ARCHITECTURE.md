# Architecture & Implementation Guide

This document explains how every component in this project works, how they connect,
and the design decisions behind them. Written for anyone who needs to understand or
extend the system.

---

## What This Project Is

An API gateway that sits in front of backend services, rate-limits clients using a
token bucket algorithm backed by Redis, and streams every request event into a
real-time analytics pipeline (Kafka → Faust → TimescaleDB → Grafana).

It demonstrates two stories:
- **Backend/SWE:** gateway, rate limiting, circuit breaker, Redis, load testing
- **Data/analytics:** Kafka pipeline, stream processing, TimescaleDB, Grafana, Jupyter

---

## System Data Flow

```
Client Request
    │
    ▼
┌──────────────────────────────────────────────┐
│  GATEWAY (FastAPI)                           │
│                                              │
│  1. Validate JWT (auth.py)                   │
│     └─ extract client_id from 'sub' claim    │
│     └─ enforce expiration, validate format   │
│                                              │
│  2. Check rate limit (rate_limiter.py)        │
│     └─ Redis WATCH/MULTI/EXEC               │
│     └─ token bucket: refill → check → deduct│
│     └─ reject with 429 if tokens < 1        │
│                                              │
│  3. Check circuit breaker (circuit_breaker.py)│
│     └─ per-endpoint state machine            │
│     └─ reject with 503 if OPEN              │
│                                              │
│  4. Proxy to upstream                        │
│     └─ forward method, headers, body         │
│     └─ strip host/auth/cookie headers        │
│     └─ record success/failure for breaker    │
│                                              │
│  5. Publish event to Kafka                   │
│     └─ fire-and-forget, never blocks         │
│     └─ no-op if Kafka unavailable            │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│  KAFKA (request_events topic)                │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│  CONSUMER (Faust)                            │
│                                              │
│  1. Read event from Kafka                    │
│  2. INSERT raw event → request_events table  │
│  3. Feed to in-memory Aggregator             │
│     └─ bucket by (client, endpoint, minute)  │
│     └─ track counts + latency list           │
│  4. Flush completed minutes                  │
│     └─ compute avg/p99 latency               │
│     └─ INSERT → request_metrics_1m table     │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│  TIMESCALEDB                                 │
│  ├─ request_events (raw, per-request)        │
│  └─ request_metrics_1m (pre-aggregated)      │
└──────────────────────────────────────────────┘
    │
    ├──► GRAFANA (live dashboard, 5s refresh)
    └──► JUPYTER (batch analysis with pandas)
```

---

## Component Details

### Gateway (`gateway/`)

**Entry point:** `main.py`

The FastAPI app handles all `/api/v1/{path}` requests. On startup it connects to
Redis, creates an httpx client for upstream calls, and optionally starts a Kafka
producer. If Kafka is unavailable, the gateway still works — events just don't get
published.

**Request handling order:**
1. JWT validation (dependency injection via `get_client_id`)
2. Rate limit check against Redis
3. Circuit breaker check for the target endpoint
4. Proxy the request to upstream
5. Publish a Kafka event (allowed, rejected, or circuit_open)

The `/health` endpoint is public with no auth.

---

### Rate Limiter (`gateway/rate_limiter.py`)

Supports two algorithms, selectable via `RATE_LIMIT_ALGORITHM` env var.

#### Token Bucket (default)

Each client gets a bucket in Redis with two keys:
- `bucket:{client_id}:tokens` — current token count (float)
- `bucket:{client_id}:last_refill` — Unix timestamp of last refill

**How it works:**
1. WATCH both keys (optimistic locking)
2. Read current tokens and last_refill
3. Calculate elapsed time since last refill
4. Add `elapsed × refill_rate` tokens, cap at capacity
5. If tokens >= 1: allow, subtract 1. If < 1: reject.
6. MULTI/EXEC to write atomically
7. If another request modified the keys (WatchError), retry (up to 5 times)

**Why WATCH/MULTI/EXEC instead of Lua scripts:**
Simpler to read and debug. The retry loop handles contention without distributed locks.
Redis keys have a TTL so stale buckets get cleaned up automatically.

**Defaults:** 100 tokens capacity, 10 tokens/second refill rate.

#### Sliding Window Log

Each client gets a Redis sorted set (`swlog:{client_id}`) where each member is a
request timestamp (score = Unix time).

**How it works:**
1. WATCH the sorted set key
2. ZREMRANGEBYSCORE to remove entries older than `now - window_seconds`
3. ZCARD to count remaining entries
4. If count < capacity: MULTI → ZADD the new timestamp → EXEC → allow
5. If count >= capacity: UNWATCH → reject
6. Retry on WatchError (up to 5 times)

**Tradeoff vs token bucket:** More memory (O(n) per client vs O(1)), but exact
enforcement with no burst allowance. Better for abuse prevention scenarios.

**Defaults:** 100 requests per 10-second window.

#### Redis Failure Handling (Fail-Open)

When Redis is unreachable (connection error, timeout), the rate limiter **fails open** —
the request is allowed through and a warning is logged. This prevents a Redis outage
from taking down the entire gateway.

**Why fail-open instead of fail-closed:**
- The gateway's primary job is proxying requests to upstream services. Rate limiting is
  a safety layer, not the core function.
- A Redis outage is typically brief (restart, network blip). Blocking all traffic during
  that window is worse than temporarily allowing unthrottled requests.
- The upstream services have their own capacity limits (circuit breaker, timeouts) that
  still protect against overload.

**What gets caught:** `ConnectionError`, `OSError`, `redis.ConnectionError`,
`redis.TimeoutError`. Other exceptions (like `WatchError` exhaustion) still propagate
since they indicate a logic error, not an infrastructure outage.

**How to tell it's happening:** Look for log lines like:
`WARNING - redis unavailable, failing open for client <id>: <error>`

---

### Circuit Breaker (`gateway/circuit_breaker.py`)

**State machine:** CLOSED → OPEN → HALF_OPEN → CLOSED

Per-endpoint (each unique path gets its own breaker instance).

| State | Behavior |
|-------|----------|
| CLOSED | All requests pass through. Consecutive failures tracked. |
| OPEN | All requests rejected with 503. Entered after 5 consecutive failures. |
| HALF_OPEN | Entered after 30s timeout. First success closes, any failure re-opens. |

**What counts as failure:** upstream 5xx, timeout, connection error.
**What counts as success:** any 2xx-4xx response.

---

### JWT Auth (`gateway/auth.py`)

Expects `Authorization: Bearer <jwt>` header. Tokens must:
- Be signed with HS256 using the configured `JWT_SECRET`
- Include an `exp` (expiration) claim — tokens without expiration are rejected
- Include a `sub` (subject) claim — this becomes the `client_id`
- Have a `client_id` matching `^[a-zA-Z0-9_\-]+$` and <= 128 characters

Uses PyJWT (not python-jose, which is unmaintained and has known CVEs).

---

### Kafka Producer (`gateway/kafka_producer.py`)

Uses `aiokafka` with:
- `acks=1` (leader acknowledgment only)
- `linger_ms=10` (batch events for 10ms before sending)
- `max_batch_size=16384` bytes

Errors are logged but never raised — the gateway never blocks or fails because of Kafka.
If the producer is None (Kafka was unavailable at startup), publishing is a no-op.

---

### Event Schema (`gateway/models.py`)

Every request (allowed, rejected, circuit_open) produces this event:

```json
{
  "event_id": "uuid4",
  "timestamp": "2026-01-01T00:00:00Z",
  "client_id": "client_abc",
  "endpoint": "/api/v1/products",
  "method": "GET",
  "status": "allowed|rejected|circuit_open",
  "latency_ms": 12.4,
  "tokens_remaining": 87.0,
  "upstream_status": 200
}
```

---

### Consumer (`consumer/`)

**Entry point:** `app.py` — a Faust worker that reads from the `request_events` Kafka topic.

For each event:
1. **Raw insert** — writes the full event to the `request_events` hypertable in TimescaleDB
2. **Aggregation** — feeds the event to an in-memory `Aggregator` that accumulates
   1-minute buckets keyed by `(client_id, endpoint, minute)`. When a minute completes
   (the next event has a later minute), the aggregator flushes:
   - total_requests, allowed, rejected counts
   - avg_latency_ms, p99_latency_ms (computed from sorted latency list)

The flushed rows are batch-inserted into `request_metrics_1m`.

**Why aggregate in the consumer instead of SQL?**
Pre-computing rollups in the consumer means Grafana queries the small `request_metrics_1m`
table instead of scanning millions of raw events. This keeps dashboard refresh fast.

**Helper module:** `consumer_helpers.py` contains `insert_raw_event()`, `flush_rollups()`,
and the `Aggregator` class.

---

### Database (`timescaledb/init.sql`)

Two hypertables (TimescaleDB auto-partitions by time):

**`request_events`** — raw, per-request
```sql
time, client_id, endpoint, method, status, latency_ms, tokens_remaining, upstream_status
```
Indexes on `(client_id, time DESC)` and `(endpoint, time DESC)`.

**`request_metrics_1m`** — pre-aggregated, per-minute
```sql
bucket, client_id, endpoint, total_requests, allowed, rejected, avg_latency_ms, p99_latency_ms
```
Index on `(client_id, bucket DESC)`.

---

### Upstream Mock (`upstream/`)

Two simple FastAPI endpoints (`/api/v1/products`, `/api/v1/orders`) that return
static JSON with 1-10ms random delay to simulate real network latency. A catch-all
handles PUT/DELETE/PATCH.

---

### Grafana Dashboard (`grafana/`)

Auto-provisioned on startup (no manual setup needed). Five panels querying `request_metrics_1m`:

1. **Requests/sec + Rejection Rate** — dual Y-axis time series
2. **Top 10 Clients by Traffic** — bar chart
3. **Top 5 Clients by Rejections** — table with rejection %
4. **P99 Latency** — time series
5. **Requests by Endpoint** — pie chart

Plus circuit breaker trip annotations from `request_events`.

Refreshes every 5 seconds. Datasource auto-configured via `timescaledb.yml`.

---

### Load Testing (`load_tests/`)

Locust with two user profiles:

| Profile | Weight | Wait Time | Clients | Behavior |
|---------|--------|-----------|---------|----------|
| NormalUser | 4 (80%) | 0.1-0.5s | 50 unique IDs | Stays within limit |
| AggressiveUser | 1 (20%) | 0.001-0.01s | 5 unique IDs | Hammers to trigger 429s |

Run: `docker compose run --rm locust --host=http://gateway:8000 --users 500 --spawn-rate 50 --run-time 5m --headless`

---

### Jupyter Notebook — Observability Analytics (`notebooks/traffic_analysis.ipynb`)

Batch analysis on 356K+ request events stored in TimescaleDB, using Pandas for
data wrangling and Matplotlib for visualization. Connects directly to TimescaleDB
via SQLAlchemy and loads both raw events and pre-aggregated 1-minute rollups.

Five analyses focused on understanding rate limiter behavior under load:

1. **Peak rejection hour** — bar chart of rejection rate by hour of day, identifies
   the UTC hour with the highest rejection percentage
2. **Automated client detection** — computes coefficient of variation (CV) of
   inter-arrival times per client. Clients with CV < 0.5 flagged as potentially
   automated (low variance = regular interval = scripted traffic)
3. **Traffic volume vs P99 latency** — dual-axis time series with Pearson correlation
   to show whether tail latency degrades under load
4. **Most-rejected endpoint** — pie chart showing which endpoints absorb the most
   rate-limited traffic
5. **Pareto analysis** — bar chart proving whether the top 3 clients account for
   the majority of all rejections (expected ~80%, Pareto principle)

---

### Tests (`tests/`)

| File | What it tests | Mocking strategy |
|------|---------------|------------------|
| `test_rate_limiter.py` | Token bucket logic | FakeRedis (in-memory, mimics WATCH/MULTI/EXEC) |
| `test_auth.py` | JWT validation | Patches `settings.jwt_secret` |
| `test_circuit_breaker.py` | State machine transitions | Patches `time.time()` for timeout control |
| `test_gateway.py` | Full request flow | AsyncMock for Redis, httpx, Kafka, rate limiter |
| `test_kafka_producer.py` | Producer init + publishing | AsyncMock for AIOKafkaProducer |
| `test_consumer.py` | Aggregation + DB writes | AsyncMock for asyncpg pool |

Run all: `docker compose run --rm test`

---

## Docker Networking

```
┌─────────────────────────────────────────────┐
│  frontend network                           │
│  ┌─────────┐    ┌─────────┐   ┌──────────┐ │
│  │ locust  │───►│ gateway │──►│ upstream │ │
│  └─────────┘    └────┬────┘   └──────────┘ │
└──────────────────────┼──────────────────────┘
                       │
┌──────────────────────┼──────────────────────┐
│  backend network     │                      │
│              ┌───────┴──────┐               │
│              │   gateway    │               │
│              └───┬──┬──┬───┘               │
│                  │  │  │                    │
│  ┌───────┐  ┌───┘  │  └───┐  ┌──────────┐ │
│  │ redis │  │      │      │  │ consumer │ │
│  └───────┘  │  ┌───┘      │  └────┬─────┘ │
│         ┌───┘  │       ┌──┘       │        │
│         │  ┌───┘       │          │        │
│      ┌──┴──┴──┐  ┌─────┴─────┐   │        │
│      │ kafka  │  │timescaledb│◄──┘        │
│      └────────┘  └─────┬─────┘            │
│                        │                   │
│                  ┌─────┴─────┐             │
│                  │  grafana  │             │
│                  └───────────┘             │
└────────────────────────────────────────────┘
```

The gateway lives on both networks — it can reach upstream (frontend) and
infrastructure (backend). Locust and upstream are frontend-only. Consumer,
Redis, Kafka, TimescaleDB, and Grafana are backend-only.

---

## Tech Stack Summary

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Gateway | FastAPI | 0.110.0 | HTTP routing, rate limiting, proxying |
| Rate limit state | Redis | 7-alpine | Token bucket counters per client |
| Message queue | Kafka | 7.6.0 (Confluent) | Streams request events off the hot path |
| Stream processor | Faust | 1.10.4 | Consumes Kafka, aggregates, writes to DB |
| Time-series DB | TimescaleDB | latest-pg15 | Stores metrics keyed by timestamp |
| Dashboard | Grafana | 10.3.3 | Live visualization of metrics |
| Batch analysis | Jupyter + Pandas | scipy-notebook | Deeper pattern analysis on stored data |
| Load testing | Locust | 2.24.0 | Simulates hundreds of concurrent clients |
| HTTP client | httpx | 0.27.0 | Async upstream proxying |
| JWT library | PyJWT | 2.9.0 | Token validation (replaced python-jose) |
| Infrastructure | Docker Compose | - | Runs the entire stack |

---

## Configuration

All settings loaded from `.env` via pydantic-settings. See `.env.example` for the full list.

Key knobs:
- `RATE_LIMIT_CAPACITY` / `RATE_LIMIT_REFILL_RATE` — tune rate limiting aggressiveness
- `JWT_SECRET` — **must be changed from default** (gateway logs a warning if not)
- `UPSTREAM_URL` — where the gateway forwards allowed requests

---

## Quick Start

```bash
cp .env.example .env       # configure secrets
docker compose build        # build all images
docker compose up -d        # start everything
```

Then:
- Gateway: http://localhost:8000/health
- Grafana: http://localhost:3000 (admin/admin)
- Jupyter: http://localhost:8888 (token: analytics)

Generate a test token:
```bash
TOKEN=$(docker compose run --rm test python -c \
  "import jwt, time; print(jwt.encode({'sub': 'test-client', 'exp': int(time.time()) + 3600}, 'change-me-in-production', algorithm='HS256'))")
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/products
```

Run load tests:
```bash
docker compose run --rm locust --host=http://gateway:8000 --users 500 --spawn-rate 50 --run-time 5m --headless
```

Run unit tests:
```bash
docker compose run --rm test
```