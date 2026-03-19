-- TimescaleDB schema initialization
-- Runs automatically on first container start via docker-entrypoint-initdb.d

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Raw request events hypertable (partitioned by time automatically)
CREATE TABLE IF NOT EXISTS request_events (
  time             TIMESTAMPTZ      NOT NULL,
  client_id        TEXT,
  endpoint         TEXT,
  method           TEXT,
  status           TEXT,
  latency_ms       DOUBLE PRECISION,
  tokens_remaining DOUBLE PRECISION,
  upstream_status  INTEGER
);

SELECT create_hypertable('request_events', 'time', if_not_exists => TRUE);

-- Pre-aggregated 1-minute rollup (written by Faust consumer)
CREATE TABLE IF NOT EXISTS request_metrics_1m (
  bucket          TIMESTAMPTZ      NOT NULL,
  client_id       TEXT,
  endpoint        TEXT,
  total_requests  INTEGER,
  allowed         INTEGER,
  rejected        INTEGER,
  avg_latency_ms  DOUBLE PRECISION,
  p99_latency_ms  DOUBLE PRECISION
);

SELECT create_hypertable('request_metrics_1m', 'bucket', if_not_exists => TRUE);

-- Useful indexes for Grafana queries
CREATE INDEX IF NOT EXISTS idx_events_client_time    ON request_events (client_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_events_endpoint_time  ON request_events (endpoint, time DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_client_bucket ON request_metrics_1m (client_id, bucket DESC);
