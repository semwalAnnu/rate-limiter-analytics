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
```

| Service    | URL                          | Notes            |
|------------|------------------------------|------------------|
| Gateway    | http://localhost:8000         |                  |
| Grafana    | http://localhost:3000         | admin / admin    |
| Jupyter    | http://localhost:8888         |                  |

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

```bash
cd load_tests && pip install -r requirements.txt && locust --host=http://localhost:8000
```

Opens the Locust web UI at http://localhost:8089. Two user profiles are included:
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

> To be filled after running Locust at 500 concurrent users for 5 minutes.

| Metric | Target | Actual |
|---|---|---|
| Gateway throughput | 5,000+ req/s | TBD |
| Rate limit overhead (p99) | < 5ms | TBD |
| False positives | 0 | TBD |
| Kafka lag | < 1s | TBD |
| Grafana lag | < 5s | TBD |
