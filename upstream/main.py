"""Mock upstream services simulating real backends.

/api/v1/products — fake product list (GET) or create (POST)
/api/v1/orders   — fake order list (GET) or create (POST)

Catch-all handles PUT/DELETE/PATCH for any /api/v1/ path.
Adds a small random delay to simulate real-world latency.
"""
from __future__ import annotations

import asyncio
import random

from fastapi import FastAPI, Request

app = FastAPI(title="Mock Upstream")


async def _simulate_latency():
    await asyncio.sleep(random.uniform(0.001, 0.010))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/products")
async def get_products() -> dict:
    await _simulate_latency()
    return {
        "products": [
            {"id": 1, "name": "Widget A", "price": 9.99},
            {"id": 2, "name": "Widget B", "price": 19.99},
        ]
    }


@app.post("/api/v1/products")
async def create_product(request: Request) -> dict:
    await _simulate_latency()
    return {"id": 3, "status": "created"}


@app.get("/api/v1/orders")
async def get_orders() -> dict:
    await _simulate_latency()
    return {
        "orders": [
            {"id": 101, "product_id": 1, "quantity": 3},
            {"id": 102, "product_id": 2, "quantity": 1},
        ]
    }


@app.post("/api/v1/orders")
async def create_order(request: Request) -> dict:
    await _simulate_latency()
    return {"id": 103, "status": "created"}


@app.api_route("/api/v1/{path:path}", methods=["PUT", "DELETE", "PATCH"])
async def catch_all_write(path: str, request: Request) -> dict:
    await _simulate_latency()
    return {"path": path, "method": request.method, "status": "ok"}
