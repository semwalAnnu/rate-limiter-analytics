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
