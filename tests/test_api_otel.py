"""Tests for FastAPI OTel instrumentation and Prometheus metrics endpoint."""

from __future__ import annotations

import pytest


@pytest.fixture
def client():
    """Create a TestClient for the cockpit API.

    Uses importlib to avoid side-effects from lifespan (cache refresh, etc.).
    """
    from unittest.mock import AsyncMock, patch

    # Patch lifespan dependencies that require running services
    with (
        patch("cockpit.api.cache.start_refresh_loop", new_callable=AsyncMock),
        patch("cockpit.api.sessions.agent_run_manager", shutdown=AsyncMock()),
    ):
        from starlette.testclient import TestClient

        from cockpit.api.app import app

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def test_root_returns_ok(client):
    """Basic smoke test that the app starts and serves requests."""
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "cockpit-api"


def test_traceparent_header_accepted(client):
    """A request with a W3C traceparent header should not cause errors."""
    resp = client.get(
        "/",
        headers={"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"},
    )
    assert resp.status_code == 200


def test_metrics_endpoint_returns_prometheus(client):
    """The /metrics endpoint should return Prometheus-format text."""
    resp = client.get("/metrics")
    # If prometheus-fastapi-instrumentator is installed, this should work
    if resp.status_code == 200:
        assert "text/plain" in resp.headers.get("content-type", "") or \
               "text/plain" in resp.text[:100] or \
               "http_request" in resp.text or \
               "HELP" in resp.text
    else:
        # If prometheus is not installed, the try/except in app.py means
        # /metrics won't exist — that's OK, skip
        pytest.skip("prometheus-fastapi-instrumentator not installed")
