# CLAUDE.md — Rate Limiter + Real-Time Analytics Platform

## Project Overview

This is a Python-based API gateway with built-in rate limiting and a real-time analytics pipeline.
The system sits in front of mock upstream services, controls request flow using a token bucket
algorithm backed by Redis, and streams all request events into a Kafka → Faust → TimescaleDB
pipeline visualised in Grafana. A Jupyter notebook provides batch analytics on top of the stored data.

The project serves two resume purposes:

- Backend/SWE story: the gateway, rate limiting algorithm, Redis, circuit breaker, load test results
- Data/analytics story: the Kafka pipeline, stream processing, TimescaleDB, Grafana dashboard, Jupyter analysis

---

## Architecture

```
Clients (Locust load tester)
    │
    ▼
[FastAPI Gateway] ──── reads/writes ────► [Redis]
    │                                     (token buckets, counters)
    │── allowed requests ──────────────► [Mock Upstream Services]
    │
    │── every request event ────────────► [Kafka]
                                              │
                                         [Faust Consumer]
                                              │
                                         [TimescaleDB]
                                           /        \
                                     [Grafana]   [Jupyter Notebook]
                                   (live dashboard) (batch analysis)
```

---

## Tech Stack

| Component        | Technology         | Purpose                                        |
| ---------------- | ------------------ | ---------------------------------------------- |
| Gateway          | FastAPI (Python)   | Receives all HTTP requests, runs rate limiting |
| Rate limit state | Redis              | Token bucket counters per client               |
| Message queue    | Kafka (via Docker) | Streams request events off the critical path   |
| Stream processor | Faust (Python)     | Consumes Kafka, aggregates, writes to DB       |
| Time-series DB   | TimescaleDB        | Stores metrics keyed by timestamp              |
| Dashboard        | Grafana            | Live visualisation of metrics                  |
| Batch analysis   | Jupyter + Pandas   | Deeper pattern analysis on stored data         |
| Load testing     | Locust (Python)    | Simulates thousands of clients                 |
| Infrastructure   | Docker Compose     | Runs the entire stack with one command         |

---

## Project Structure

```
rate-limiter-analytics/
├── CLAUDE.md                   ← you are here
├── docker-compose.yml          ← spins up Redis, Kafka, TimescaleDB, Grafana
├── .env                        ← environment variables (never commit secrets)
├── .env.example                ← template for .env
├── README.md                   ← project overview, setup steps, benchmark results
│
├── gateway/                    ← FastAPI application
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 ← FastAPI app entry point
│   ├── rate_limiter.py         ← token bucket logic (Redis-backed)
│   ├── circuit_breaker.py      ← circuit breaker implementation
│   ├── auth.py                 ← JWT validation middleware
│   ├── kafka_producer.py       ← publishes request events to Kafka
│   ├── models.py               ← Pydantic request/response models
│   └── config.py               ← settings loaded from .env
│
├── consumer/                   ← Faust stream processor
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                  ← Faust app: reads Kafka, aggregates, writes TimescaleDB
│
├── upstream/                   ← mock upstream services
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                 ← two simple FastAPI endpoints that simulate real services
│
├── load_tests/                 ← Locust load testing
│   ├── requirements.txt
│   └── locustfile.py           ← simulates multiple client profiles hitting the gateway
│
├── notebooks/                  ← Jupyter batch analysis
│   └── traffic_analysis.ipynb  ← Pandas analysis: patterns, anomalies, peak times
│
├── grafana/                    ← Grafana config
│   └── provisioning/
│       ├── datasources/
│       │   └── timescaledb.yml ← auto-connects Grafana to TimescaleDB on startup
│       └── dashboards/
│           └── main.json       ← pre-built dashboard (imported on startup)
│
└── tests/
    ├── test_rate_limiter.py    ← unit tests for token bucket logic
    ├── test_auth.py            ← unit tests for JWT auth middleware
    ├── test_gateway.py         ← integration tests for the gateway endpoints
    └── conftest.py             ← pytest fixtures
```

---

## Git Workflow

**Branching strategy:**

```
main              ← stable, PRs only, never commit directly
  └── <name>      ← all new work happens here
```

- `main` is always deployable. Only merged via pull request.
- Feature branches are short-lived. One branch per feature/fix.
- After PR merge, delete the feature branch.

**Workflow for every task:**

1. `git checkout -b <name>` from `main`
2. Implement, commit often (short lowercase imperative messages)
3. `git push -u origin <name>`
4. Open PR via `gh pr create`
5. Merge PR, delete branch

**Branch naming:** Keep it short and casual, like a real person would type it.
Don't use verbose or over-structured names. No `feature/` prefix needed.

Good:

- `fixes`
- `kafka-stuff`
- `locust-jwt`
- `dashboard`
- `load-tests`

Bad (sounds like AI wrote it):

- `feature/phase-a-fix-critical-pipeline`
- `feature/implement-kafka-producer-integration`
- `feature/grafana-dashboard-provisioning`

---

## Rate Limiting Design

Algorithm: **Token Bucket**

- Each client (identified by API key in the `X-API-Key` header) gets a bucket in Redis
- Bucket has a `tokens` count and a `last_refill` timestamp
- On each request: calculate tokens earned since last refill, cap at max, subtract 1
- If tokens < 1: reject with HTTP 429, publish rejection event to Kafka
- If tokens >= 1: allow, forward to upstream, publish allowed event to Kafka

Redis key structure:

- `bucket:{client_id}:tokens` — current token count (float)
- `bucket:{client_id}:last_refill` — Unix timestamp of last refill

Default limits (configurable via .env):

- `RATE_LIMIT_CAPACITY` = 100 (max tokens per bucket)
- `RATE_LIMIT_REFILL_RATE` = 10 (tokens added per second)

---

## Kafka Event Schema

Every request (allowed or rejected) publishes this JSON event to the `request_events` topic:

```json
{
  "event_id": "uuid4",
  "timestamp": "2026-01-01T00:00:00Z",
  "client_id": "client_abc",
  "endpoint": "/api/v1/products",
  "method": "GET",
  "status": "allowed",
  "latency_ms": 12.4,
  "tokens_remaining": 87.0,
  "upstream_status": 200
}
```

---

## TimescaleDB Schema

```sql
-- Raw events hypertable (partitioned by time automatically)
CREATE TABLE request_events (
  time          TIMESTAMPTZ NOT NULL,
  client_id     TEXT,
  endpoint      TEXT,
  method        TEXT,
  status        TEXT,
  latency_ms    DOUBLE PRECISION,
  tokens_remaining DOUBLE PRECISION,
  upstream_status  INTEGER
);
SELECT create_hypertable('request_events', 'time');

-- Pre-aggregated 1-minute rollup (written by Faust consumer)
CREATE TABLE request_metrics_1m (
  bucket        TIMESTAMPTZ NOT NULL,
  client_id     TEXT,
  endpoint      TEXT,
  total_requests  INTEGER,
  allowed         INTEGER,
  rejected        INTEGER,
  avg_latency_ms  DOUBLE PRECISION,
  p99_latency_ms  DOUBLE PRECISION
);
SELECT create_hypertable('request_metrics_1m', 'bucket');
```

---

## Grafana Dashboard Panels

Build these panels (all powered by TimescaleDB queries):

1. **Total requests/sec** — time series, last 30 minutes
2. **Rejection rate %** — time series, overlaid on requests/sec
3. **Top 10 clients by traffic** — bar chart, last 1 hour
4. **Top 5 clients by rejection count** — table with client_id, rejections, rejection %
5. **P99 latency** — time series, gateway overhead only
6. **Requests by endpoint** — pie chart
7. **Circuit breaker trips** — annotation markers on the timeline

---

## Commit Message Style

Write commit messages like a junior developer would — casual, slightly imperfect, human.
Short, lowercase, past tense. Max 50 characters on the first line.
Use "cleaned up" not "clean up", "added" not "add", "fixed" not "fix", etc.
No corporate language, no over-explaining, no buzzwords. No colons, no conventional commit prefixes.
Messages should feel like someone quickly typing before pushing, not like a polished changelog.

Good (sounds like a real person wrote it):

- added rate limiter
- fixed redis timeout bug
- wired up kafka producer
- added tests for auth
- fixed the refill logic
- handled upstream errors
- cleaned up main.py
- added retry limit to rate limiter
- oops forgot to strip auth header

Bad (sounds like AI wrote it):

- Implement comprehensive token bucket rate limiting algorithm with Redis backend
- Refactor and optimize the gateway module for improved performance and maintainability
- Add initial project scaffolding with proper directory structure
- harden gateway: retry limits, error handling, timeouts, key ttl
- feat: add test scaffolding with placeholder tests
- fix: resolve edge case in token bucket refill logic

## Jupyter Analysis Goals

The notebook should answer these questions using Pandas on TimescaleDB data:

1. Which hour of the day has the highest rejection rate?
2. Are there clients whose request pattern looks automated (no variance in interval)?
3. What is the correlation between traffic volume and p99 latency?
4. Which endpoint gets hit most frequently by rejected clients?
5. What percentage of total rejections come from the top 3 clients? (should be ~80% — Pareto principle)

---

## Benchmark Targets

Run Locust with 500 concurrent users for 5 minutes and aim for:

- Gateway throughput: 5,000+ requests/second
- Rate limiting overhead: < 5ms added latency (p99)
- Rejection accuracy: 0 false positives (allowed clients should never be rejected)
- Kafka lag: < 1 second under full load
- Grafana dashboard lag: < 5 seconds behind real traffic

Document actual results in README.md.

---

## Build Order

Phase 1 — Core gateway ✅

- docker-compose.yml with Redis, Kafka, TimescaleDB, Grafana
- FastAPI gateway with token bucket rate limiter
- Mock upstream services (GET endpoints)
- JWT auth middleware
- Unit tests for rate limiter
- Circuit breaker stub (implementation in Phase 3)

Phase 2 — Analytics pipeline (current)

- Kafka producer in gateway
- Faust consumer writing to TimescaleDB
- Grafana dashboard provisioning
- Integration tests

Phase 3 — Polish + benchmarks

- Locust load tests + benchmark results
- Circuit breaker
- Jupyter analysis notebook
- README with architecture diagram, setup instructions, benchmark numbers
- Recorded demo (Loom or similar)

---

## What NOT to Do

- Do not use async Kafka producers in the hot path — publish fire-and-forget to avoid adding latency
- Do not store raw events only — always maintain the 1-minute rollup table for fast Grafana queries
- Do not hardcode secrets — all credentials go in .env
- Do not skip the README — benchmark numbers and a recorded demo are required for this to land on a resume
- Do not use a single Docker network for everything — gateway and upstream should be on separate networks to simulate real network boundaries
- Do not use synchronous Redis calls in the rate limiter — use aioredis for async access

---

## Environment Variables (.env.example)

```
# Redis
REDIS_URL=redis://localhost:6379

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_TOPIC=request_events

# TimescaleDB
TIMESCALE_URL=postgresql://user:password@localhost:5432/metrics

# Gateway
RATE_LIMIT_CAPACITY=100
RATE_LIMIT_REFILL_RATE=10
JWT_SECRET=change-me-in-production
UPSTREAM_URL=http://upstream:8001

# Grafana
GF_SECURITY_ADMIN_PASSWORD=admin
```

---

## Key Commands

```bash
# Start entire stack
docker compose up -d

# Run gateway locally (for development)
cd gateway && uvicorn main:app --reload --port 8000

# Run Faust consumer locally
cd consumer && python app.py worker -l info

# Run load tests
cd load_tests && locust --host=http://localhost:8000

# Run tests
docker compose run --rm test

# Start Jupyter (via docker compose)
docker compose up jupyter
```

---

## Definition of Done

The project is resume-ready when:

- [ ] `docker compose up` starts everything with no manual steps
- [ ] Locust benchmark results are documented in README with real numbers
- [ ] Grafana dashboard loads automatically on first run (provisioned, not manual)
- [ ] Jupyter notebook has at least 3 data insights with charts
- [ ] GitHub repo has a clean commit history (not one giant commit)
- [ ] A 3-5 minute demo video is recorded showing the live dashboard under load
- [ ] README explains the architecture, design decisions, and how to run it
