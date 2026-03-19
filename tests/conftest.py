"""pytest fixtures shared across all tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
