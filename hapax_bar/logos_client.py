"""HTTP client for Logos API polling via GLib timers."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gi.repository import GLib

LOGOS_API_BASE = "http://localhost:8051"
HEALTH_HISTORY_FILE = (
    Path.home() / "projects" / "hapax-council" / "profiles" / "health-history.jsonl"
)
_TIMEOUT_SECS = 2


def _fetch_json(endpoint: str) -> dict[str, Any] | None:
    """Fetch JSON from a Logos API endpoint. Returns None on failure."""
    url = f"{LOGOS_API_BASE}{endpoint}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECS) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def fetch_health() -> dict[str, Any]:
    """Fetch health status. Falls back to health-history.jsonl if API is down."""
    data = _fetch_json("/api/health")
    if data is not None:
        return data

    # Fallback: read last line of health history
    try:
        lines = HEALTH_HISTORY_FILE.read_text().strip().split("\n")
        if lines:
            return json.loads(lines[-1])
    except Exception:
        pass
    return {"status": "unknown", "healthy": 0, "total_checks": 0, "failed_checks": []}


def fetch_gpu() -> dict[str, Any]:
    """Fetch GPU status from Logos API."""
    return _fetch_json("/api/gpu") or {}


def fetch_working_mode() -> dict[str, Any]:
    """Fetch working mode from Logos API."""
    return _fetch_json("/api/working-mode") or {"mode": "rnd"}


def fetch_infrastructure() -> dict[str, Any]:
    """Fetch infrastructure data (containers, timers) from Logos API."""
    return _fetch_json("/api/infrastructure") or {"containers": []}


def fetch_cost() -> dict[str, Any]:
    """Fetch LLM cost data from Logos API."""
    return _fetch_json("/api/cost") or {}


def poll_api(
    endpoint_fn: Callable[[], dict[str, Any]],
    interval_ms: int,
    callback: Callable[[dict[str, Any]], None],
) -> int:
    """Poll an API function on interval, call callback with result.

    Returns the GLib source ID for cancellation.
    """

    def tick(*_args: Any) -> bool:
        data = endpoint_fn()
        callback(data)
        return GLib.SOURCE_CONTINUE

    # Initial fetch
    tick()
    return GLib.timeout_add(interval_ms, tick)
