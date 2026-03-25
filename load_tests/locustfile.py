"""Locust load test simulating multiple client profiles.

Run:
    docker compose run --rm locust --host=http://gateway:8000 --users 500 --spawn-rate 50 --run-time 5m --headless

Profiles:
  - NormalUser:    moderate traffic, stays within rate limit
  - AggressiveUser: hammers the gateway to trigger 429 responses
"""
from __future__ import annotations

import itertools
import os

from jose import jwt
from locust import HttpUser, between, task

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")

_normal_counter = itertools.count()
_aggressive_counter = itertools.count()


def _auth_header(client_id: str) -> dict:
    token = jwt.encode({"sub": client_id}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


class NormalUser(HttpUser):
    wait_time = between(0.1, 0.5)
    weight = 4

    def on_start(self):
        self._client_id = f"normal-{next(_normal_counter) % 50}"

    @task(3)
    def get_products(self):
        self.client.get(
            "/api/v1/products",
            headers=_auth_header(self._client_id),
            name="/api/v1/products",
        )

    @task(1)
    def get_orders(self):
        self.client.get(
            "/api/v1/orders",
            headers=_auth_header(self._client_id),
            name="/api/v1/orders",
        )


class AggressiveUser(HttpUser):
    wait_time = between(0.001, 0.01)
    weight = 1

    def on_start(self):
        self._client_id = f"aggressive-{next(_aggressive_counter) % 5}"

    @task
    def hammer_products(self):
        self.client.get(
            "/api/v1/products",
            headers=_auth_header(self._client_id),
            name="/api/v1/products [aggressive]",
        )
