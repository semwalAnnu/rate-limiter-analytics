# Setup & Running Guide

Complete instructions for running every part of this project.

## Prerequisites

- Docker and Docker Compose (v2+)
- Git
- A terminal

That's it. Everything runs in Docker — no local Python, Redis, Kafka, or Postgres needed.

## 1. Initial Setup

Clone the repo and create your env file:

```bash
git clone https://github.com/semwalAnnu/rate-limiter-analytics.git
cd rate-limiter-analytics
cp .env.example .env
```

The `.env` file contains all configuration. Default values work out of the box:

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379` | Redis connection for rate limiter |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Kafka broker address |
| `KAFKA_TOPIC` | `request_events` | Kafka topic for events |
| `TIMESCALE_URL` | `postgresql://metrics_user:metrics_pass@timescaledb:5432/metrics` | TimescaleDB connection |
| `RATE_LIMIT_CAPACITY` | `100` | Max tokens per client bucket |
| `RATE_LIMIT_REFILL_RATE` | `10` | Tokens added per second |
| `JWT_SECRET` | `change-me-in-production` | JWT signing secret |
| `UPSTREAM_URL` | `http://upstream:8001` | Mock upstream service |
| `GF_SECURITY_ADMIN_USER` | `admin` | Grafana login username |
| `GF_SECURITY_ADMIN_PASSWORD` | `admin` | Grafana login password |
| `JUPYTER_TOKEN` | `analytics` | Jupyter access token/password |

## 2. Start the Stack

Build and start everything:

```bash
docker compose build
docker compose up -d
```

This starts 8 services:

| Service | Port | What it does |
|---|---|---|
| **redis** | 6379 | Stores token bucket state for rate limiting |
| **zookeeper** | 2181 | Kafka coordination (internal) |
| **kafka** | 9092 | Message queue for request events |
| **timescaledb** | 5432 | Time-series database for analytics |
| **upstream** | 8001 | Mock backend APIs (products, orders) |
| **gateway** | 8000 | The API gateway with rate limiting + circuit breaker |
| **consumer** | — | Faust worker: reads Kafka, writes to TimescaleDB |
| **grafana** | 3000 | Live dashboard |
| **jupyter** | 8888 | Batch analysis notebook |

Check everything is running:

```bash
docker compose ps
```

All services should show `Up` or `Running`. Redis, Kafka, and TimescaleDB should show `(healthy)`.

## 3. Verify the Gateway

Health check:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Send an authenticated request:

```bash
TOKEN=$(python3 -c "from jose import jwt; print(jwt.encode({'sub': 'test-client'}, 'change-me-in-production', algorithm='HS256'))")
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/products
```

You should get back a JSON product list. If you don't have `python-jose` installed locally, you can generate the token inside Docker:

```bash
TOKEN=$(docker compose run --rm test python -c "from jose import jwt; print(jwt.encode({'sub': 'test-client'}, 'change-me-in-production', algorithm='HS256'))")
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/products
```

### What happens on each request

1. Gateway validates the JWT Bearer token
2. Token bucket rate limiter checks if the client has tokens left (Redis)
3. Circuit breaker checks if the upstream endpoint is healthy
4. Request is proxied to the upstream service
5. Event (allowed/rejected/circuit_open) is published to Kafka
6. Faust consumer picks it up and writes to TimescaleDB

## 4. Grafana Dashboard

Open http://localhost:3000 in your browser.

**Login:** `admin` / `admin` (or whatever you set in `.env`)

The dashboard is auto-provisioned — no manual setup needed. Navigate to **Dashboards → Rate Limiter Analytics**.

Panels:
1. **Requests/sec + Rejection Rate** — live time series
2. **Top 10 Clients by Traffic** — bar chart
3. **Top 5 Clients by Rejection Count** — table
4. **P99 Latency** — time series
5. **Requests by Endpoint** — pie chart
6. **Circuit Breaker Trips** — annotation markers on the timeline

The dashboard will show "No data" until you send traffic through the gateway. Run the load test (step 6) to populate it.

### Troubleshooting Grafana

If you see "Datasource timescaledb was not found":

```bash
docker compose down grafana
docker volume rm rate-limiter-analytics_grafana_data
docker compose up -d grafana
```

This wipes the stale Grafana state and re-provisions the datasource.

## 5. Jupyter Notebook

Open http://localhost:8888 in your browser.

**Token/password:** `analytics` (or whatever you set as `JUPYTER_TOKEN` in `.env`)

Navigate to `work/traffic_analysis.ipynb` and run all cells (Kernel → Restart & Run All).

The notebook answers 5 questions:
1. Which hour of the day has the highest rejection rate?
2. Are there clients with automated request patterns?
3. What is the correlation between traffic volume and p99 latency?
4. Which endpoint gets hit most by rejected clients?
5. What % of rejections come from the top 3 clients? (Pareto analysis)

You need data in TimescaleDB for the notebook to produce charts. Run the load test first.

### Changing the Jupyter password

Set `JUPYTER_TOKEN` in your `.env` file:

```bash
JUPYTER_TOKEN=your-password-here
```

Then restart Jupyter:

```bash
docker compose up -d jupyter
```

To disable the password entirely:

```bash
JUPYTER_TOKEN=
```

## 6. Load Testing

### Web UI mode

```bash
docker compose run --rm -p 8089:8089 locust --host=http://gateway:8000
```

Open http://localhost:8089, set the number of users and spawn rate, and start the test.

### Headless mode (benchmark run)

```bash
docker compose run --rm locust --host=http://gateway:8000 --users 500 --spawn-rate 50 --run-time 5m --headless
```

This runs 500 concurrent users for 5 minutes and prints results to the terminal.

Two user profiles:
- **NormalUser** (80% of users) — sends requests every 0.1–0.5s, spreads across 50 client IDs
- **AggressiveUser** (20% of users) — sends requests every 1–10ms, 5 client IDs, designed to trigger rate limiting

### What to watch during load tests

- **Gateway logs:** `docker compose logs -f gateway`
- **Consumer logs:** `docker compose logs -f consumer`
- **Grafana dashboard:** http://localhost:3000 — should update in real time
- **Rate limiting:** aggressive users should get 429s
- **Circuit breaker:** if upstream gets overwhelmed, you'll see 503s

## 7. Running Tests

Full test suite (45 tests):

```bash
docker compose run --rm test
```

Individual test files:

```bash
docker compose run --rm test pytest tests/test_gateway.py -v
docker compose run --rm test pytest tests/test_rate_limiter.py -v
docker compose run --rm test pytest tests/test_auth.py -v
docker compose run --rm test pytest tests/test_kafka_producer.py -v
docker compose run --rm test pytest tests/test_circuit_breaker.py -v
docker compose run --rm test pytest tests/test_consumer.py -v
```

Single test:

```bash
docker compose run --rm test pytest tests/test_gateway.py::test_circuit_breaker_opens_after_upstream_failures -v
```

## 8. Stopping and Cleaning Up

Stop all services (keeps data):

```bash
docker compose down
```

Stop and delete all data (fresh start):

```bash
docker compose down -v
```

This removes the TimescaleDB and Grafana volumes. You'll need to re-run the load test to get data back.

## 9. Viewing Logs

All services:

```bash
docker compose logs -f
```

Specific service:

```bash
docker compose logs -f gateway
docker compose logs -f consumer
docker compose logs -f kafka
```

Last 50 lines:

```bash
docker compose logs --tail 50 gateway
```

## 10. Common Issues

### Gateway returns 401

Your JWT token is missing or invalid. Make sure you're sending an `Authorization: Bearer <token>` header with a valid JWT signed using the `JWT_SECRET` from `.env`.

### Gateway returns 429

Your client has exceeded its rate limit. Wait a few seconds for tokens to refill, or use a different client ID. Default: 100 tokens, refilling at 10/sec.

### Gateway returns 503

Either Redis is down (rate limiter unavailable) or the circuit breaker has tripped for that endpoint. Check `docker compose logs gateway` for details.

### Consumer keeps crashing

Check `docker compose logs consumer`. Common causes:
- Kafka not ready yet — consumer will retry automatically
- TimescaleDB not ready — wait for healthcheck to pass

### Grafana shows "No data"

You need traffic flowing through the gateway. Send some requests or run the load test. Data flows: Gateway → Kafka → Consumer → TimescaleDB → Grafana.

### Jupyter can't connect to TimescaleDB

Make sure the Jupyter container is on the `backend` network and `TIMESCALE_URL` is set correctly. The default value in docker-compose uses the Docker hostname `timescaledb`.
