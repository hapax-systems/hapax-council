"""Tests for cockpit API cycle-mode endpoints."""
from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest
from httpx import AsyncClient, ASGITransport

from cockpit.api.app import app


@pytest.fixture
def mode_file(tmp_path):
    f = tmp_path / "cycle-mode"
    f.write_text("prod\n")
    return f


@pytest.mark.asyncio
async def test_get_cycle_mode_returns_current(mode_file):
    with patch("cockpit.api.routes.cycle_mode.MODE_FILE", mode_file):
        with patch("cockpit.api.cache.start_refresh_loop", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/cycle-mode")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "prod"
    assert "switched_at" in data


@pytest.mark.asyncio
async def test_put_cycle_mode_switches(mode_file):
    async def _fake_run(mode):
        mode_file.write_text(mode + "\n")
        return (0, f"Cycle mode -> {mode}\n")

    with patch("cockpit.api.routes.cycle_mode.MODE_FILE", mode_file):
        with patch("cockpit.api.routes.cycle_mode._run_hapax_mode", side_effect=_fake_run):
            with patch("cockpit.api.cache.start_refresh_loop", new_callable=AsyncMock):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.put("/api/cycle-mode", json={"mode": "dev"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "dev"


@pytest.mark.asyncio
async def test_put_cycle_mode_rejects_invalid(mode_file):
    with patch("cockpit.api.routes.cycle_mode.MODE_FILE", mode_file):
        with patch("cockpit.api.cache.start_refresh_loop", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.put("/api/cycle-mode", json={"mode": "turbo"})
    assert resp.status_code == 422
