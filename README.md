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
