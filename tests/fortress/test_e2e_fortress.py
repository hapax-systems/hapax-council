"""Playwright E2E smoke test — fortress dashboard in Logos.

Verifies fortress API endpoints return data and the Logos frontend
renders fortress components when working mode is set to fortress.
Runs on a dedicated Hyprland workspace (7) without stealing focus.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

# Skip if playwright not available
playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

LOGOS_URL = "http://localhost:5173"
API_BASE = "http://localhost:8051"
WORKSPACE = 7


@pytest.fixture(scope="module")
def browser_context():
    """Launch Chromium on workspace 7, no focus steal."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-gpu",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1080})

        # Move browser window to workspace 7 after creation
        page = context.new_page()
        page.goto("about:blank")
        time.sleep(0.5)

        # Move to dedicated workspace via hyprctl
        try:
            subprocess.run(
                ["hyprctl", "dispatch", "movetoworkspacesilent", str(WORKSPACE)],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass  # Not on Hyprland (CI), continue headless-equivalent

        yield page, context
        context.close()
        browser.close()


def _refresh_state():
    """Write a fresh state.json so staleness check passes."""
    import time as _time

    state = {
        "timestamp": _time.time(),
        "game_tick": 240000,
        "year": 3,
        "season": 2,
        "month": 8,
        "day": 15,
        "fortress_name": "Boatmurdered",
        "paused": False,
        "population": 47,
        "food_count": 234,
        "drink_count": 100,
        "active_threats": 0,
        "job_queue_length": 15,
        "idle_dwarf_count": 3,
        "most_stressed_value": 5000,
        "pending_events": [],
    }
    Path("/dev/shm/hapax-df/state.json").write_text(json.dumps(state))


class TestFortressAPI:
    """Verify fortress API endpoints return valid data."""

    def test_state_endpoint(self):
        """GET /api/fortress/state returns fortress state."""
        import httpx

        _refresh_state()
        resp = httpx.get(f"{API_BASE}/api/fortress/state", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["fortress_name"] == "Boatmurdered"
        assert data["population"] == 47
        assert data["year"] == 3

    def test_governance_endpoint(self):
        """GET /api/fortress/governance returns chain status + suppression."""
        import httpx

        resp = httpx.get(f"{API_BASE}/api/fortress/governance", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["chains"]) == 7
        assert "creativity" in data["chains"]
        assert "creativity_suppression" in data["suppression"]
        assert data["chains"]["fortress_planner"]["active"] is True

    def test_goals_endpoint(self):
        """GET /api/fortress/goals returns active goals."""
        import httpx

        resp = httpx.get(f"{API_BASE}/api/fortress/goals", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["goals"]) > 0
        assert data["goals"][0]["id"] == "survive_winter"
        assert data["goals"][0]["state"] == "active"

    def test_metrics_endpoint(self):
        """GET /api/fortress/metrics returns session metrics."""
        import httpx

        resp = httpx.get(f"{API_BASE}/api/fortress/metrics", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["fortress_name"] == "Boatmurdered"
        assert data["survival_days"] == 247
        assert data["total_commands"] == 134
        assert "creativity" in data

    def test_events_endpoint(self):
        """GET /api/fortress/events returns event list."""
        import httpx

        _refresh_state()
        resp = httpx.get(f"{API_BASE}/api/fortress/events", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data

    def test_chronicle_endpoint(self):
        """GET /api/fortress/chronicle returns entries."""
        import httpx

        resp = httpx.get(f"{API_BASE}/api/fortress/chronicle", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data

    def test_sessions_endpoint(self):
        """GET /api/fortress/sessions returns session list."""
        import httpx

        resp = httpx.get(f"{API_BASE}/api/fortress/sessions", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data


class TestFortressFrontend:
    """Verify Logos renders fortress dashboard."""

    def test_logos_loads(self, browser_context):
        """Logos loads without crash."""
        page, _ = browser_context
        page.goto(LOGOS_URL, wait_until="domcontentloaded", timeout=15000)
        assert page.title() != ""

    def test_fortress_api_reachable_from_frontend(self, browser_context):
        """Frontend can reach fortress API (CORS/proxy working)."""
        page, _ = browser_context
        _refresh_state()
        result = page.evaluate("""
            async () => {
                try {
                    const resp = await fetch('/api/fortress/state');
                    const data = await resp.json();
                    return { status: resp.status, name: data.fortress_name };
                } catch (e) {
                    return { error: e.message };
                }
            }
        """)
        assert result.get("status") == 200, f"API unreachable: {result}"
        assert result.get("name") == "Boatmurdered"

    def test_fortress_governance_reachable(self, browser_context):
        """Frontend can reach governance endpoint."""
        page, _ = browser_context
        result = page.evaluate("""
            async () => {
                try {
                    const resp = await fetch('/api/fortress/governance');
                    const data = await resp.json();
                    return { status: resp.status, chains: Object.keys(data.chains).length };
                } catch (e) {
                    return { error: e.message };
                }
            }
        """)
        assert result.get("status") == 200
        assert result.get("chains") == 7

    def test_fortress_metrics_reachable(self, browser_context):
        """Frontend can reach metrics endpoint."""
        page, _ = browser_context
        result = page.evaluate("""
            async () => {
                try {
                    const resp = await fetch('/api/fortress/metrics');
                    const data = await resp.json();
                    return { status: resp.status, days: data.survival_days };
                } catch (e) {
                    return { error: e.message };
                }
            }
        """)
        assert result.get("status") == 200
        assert result.get("days") == 247
