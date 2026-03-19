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
