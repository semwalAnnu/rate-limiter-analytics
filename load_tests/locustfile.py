"""Locust load test simulating multiple client profiles.

Run:
    locust --host=http://localhost:8000

Profiles:
  - NormalUser:    moderate traffic, stays within rate limit
  - AggressiveUser: hammers the gateway to trigger 429 responses
"""
from __future__ import annotations

from locust import HttpUser, between, task


def _auth_header(client_id: str) -> dict:
    # TODO: generate a real JWT once auth.py is implemented
    return {"X-API-Key": client_id}


class NormalUser(HttpUser):
    wait_time = between(0.1, 0.5)
    weight = 4

    @task(3)
    def get_products(self):
        client_id = f"normal-{self.user_id % 50}"
        self.client.get(
            "/api/v1/products",
            headers=_auth_header(client_id),
            name="/api/v1/products",
        )

    @task(1)
    def get_orders(self):
        client_id = f"normal-{self.user_id % 50}"
        self.client.get(
            "/api/v1/orders",
            headers=_auth_header(client_id),
            name="/api/v1/orders",
        )


class AggressiveUser(HttpUser):
    wait_time = between(0.001, 0.01)
    weight = 1

    @task
    def hammer_products(self):
        client_id = f"aggressive-{self.user_id % 5}"
        self.client.get(
            "/api/v1/products",
            headers=_auth_header(client_id),
            name="/api/v1/products [aggressive]",
        )
