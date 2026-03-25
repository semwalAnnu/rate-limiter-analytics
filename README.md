# Rate Limiter + Real-Time Analytics Platform

A Python API gateway with token-bucket rate limiting and per-endpoint circuit breaker, backed by Redis. Streams all request events through Kafka → Faust → TimescaleDB → Grafana.

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
docker compose build
docker compose up -d
```

| Service    | URL                          | Credentials        |
|------------|------------------------------|--------------------|
| Gateway    | http://localhost:8000         |                    |
| Grafana    | http://localhost:3000         | admin / admin      |
| Jupyter    | http://localhost:8888         | token: `analytics` |

For detailed setup instructions, troubleshooting, and how to run every component, see [SETUP.md](SETUP.md).                  |

## Building

Build all service images:

```bash
docker compose build
```

Build a specific service:

```bash
docker compose build gateway
docker compose build consumer
docker compose build upstream
```

Rebuild from scratch (no cache):

```bash
docker compose build --no-cache
```

## Running Tests

Run the full test suite:

```bash
docker compose run --rm test
```

Run a specific test file:

```bash
docker compose run --rm test pytest tests/test_gateway.py -v
docker compose run --rm test pytest tests/test_rate_limiter.py -v
docker compose run --rm test pytest tests/test_kafka_producer.py -v
docker compose run --rm test pytest tests/test_consumer.py -v
docker compose run --rm test pytest tests/test_auth.py -v
```

Run a single test:

```bash
docker compose run --rm test pytest tests/test_gateway.py::test_allowed_request_publishes_event -v
```

## Load Testing

Web UI mode:

```bash
docker compose run --rm -p 8089:8089 locust --host=http://gateway:8000
```

Opens the Locust web UI at http://localhost:8089.

Headless mode (500 users, 5 minutes):

```bash
docker compose run --rm locust --host=http://gateway:8000 --users 500 --spawn-rate 50 --run-time 5m --headless
```

Two user profiles are included:
- **NormalUser** — moderate traffic, stays within rate limit
- **AggressiveUser** — hammers the gateway to trigger 429s

## Useful Commands

Stop everything:

```bash
docker compose down
```

Stop and wipe all volumes (fresh start):

```bash
docker compose down -v
```

View logs for a service:

```bash
docker compose logs -f gateway
docker compose logs -f consumer
```

Send a test request:

```bash
TOKEN=$(python3 -c "from jose import jwt; print(jwt.encode({'sub': 'test-client'}, 'change-me-in-production', algorithm='HS256'))")
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/products
```

## Benchmark Results

Locust run: 500 concurrent users, 5 minutes, single Docker host (Apple Silicon).

| Metric | Target | Actual | Notes |
|---|---|---|---|
| Gateway throughput | 5,000+ req/s | ~221 req/s | single uvicorn worker, Docker-on-laptop |
| Median latency | — | 2,300ms | includes upstream + Kafka publish |
| P99 latency | < 5ms overhead | 4,800ms | dominated by upstream latency under load |
| False positives | 0 | 0 | no legitimate client was rate-limited incorrectly |
| Kafka → TimescaleDB | < 1s lag | ~56.9k / 66.3k events stored | 85.8% capture rate during high load |

**Breakdown by endpoint:**

| Endpoint | Requests | Failures | Median | P99 |
|---|---|---|---|---|
| /api/v1/products | 32,597 | 964 (2.96%) | 2,400ms | 4,900ms |
| /api/v1/orders | 10,912 | 322 (2.95%) | 2,400ms | 4,800ms |
| /api/v1/products [aggressive] | 22,793 | 15,940 (69.93%) | 150ms | 4,800ms |

**Error breakdown:**
- 7,550 rate limit rejections (429) — aggressive users correctly throttled
- 9,676 circuit breaker trips (503) — upstream overloaded, breaker protected it

**Why throughput is below target:** The 5,000 req/s target assumes a production deployment with multiple uvicorn workers behind a load balancer. This benchmark runs a single uvicorn worker inside Docker on a laptop. The bottleneck is CPU contention between all services sharing one machine, not the rate limiter itself (which adds < 5ms when Redis is local).
