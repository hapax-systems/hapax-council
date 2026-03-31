"""Paths, cadences, and configuration constants for the visual layer aggregator."""

from __future__ import annotations

import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

PERCEPTION_STATE_PATH = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
OUTPUT_DIR = Path("/dev/shm/hapax-compositor")
OUTPUT_FILE = OUTPUT_DIR / "visual-layer-state.json"
STIMMUNG_DIR = Path("/dev/shm/hapax-stimmung")
STIMMUNG_FILE = STIMMUNG_DIR / "state.json"
TEMPORAL_DIR = Path("/dev/shm/hapax-temporal")
TEMPORAL_FILE = TEMPORAL_DIR / "bands.json"
WATERSHED_FILE = OUTPUT_DIR / "watershed-events.json"

# ── Stimmung data source paths ─────────────────────────────────────────────

PERCEPTION_MINUTES_PATH = Path.home() / ".cache" / "hapax-daimonion" / "perception-minutes.jsonl"

HEALTH_HISTORY_PATH = Path("profiles/health-history.jsonl")
INFRA_SNAPSHOT_PATH = Path("profiles/infra-snapshot.json")
LANGFUSE_STATE_PATH = Path.home() / ".cache" / "langfuse-sync" / "state.json"
WATCH_STATE_DIR = Path.home() / "hapax-state" / "watch"

# ── Cadences ─────────────────────────────────────────────────────────────────

STATE_TICK_BASE_S = 3.0  # Base state tick (adaptive: 0.5-5.0s)
HEALTH_POLL_S = 15.0  # Health + GPU
SLOW_POLL_S = 60.0  # Nudges, briefing, drift, goals, copilot
AMBIENT_CONTENT_INTERVAL_S = 45.0  # Ambient content pool refresh
AMBIENT_POOL_REFRESH_S = 300.0  # Full pool refresh every 5 min

# Legacy alias for backward compat with tests
FAST_INTERVAL_S = STATE_TICK_BASE_S
SLOW_INTERVAL_S = SLOW_POLL_S

# ── API ──────────────────────────────────────────────────────────────────────

LOGOS_BASE: str = os.environ.get("COCKPIT_BASE_URL", "http://localhost:8051/api")

# ── Camera roles and experimental filters ────────────────────────────────────


CAMERA_FILTERS = [
    "sepia(0.8) contrast(1.3) brightness(0.7)",
    "hue-rotate(30deg) saturate(1.8) brightness(0.6)",
    "saturate(2.5) contrast(1.1) brightness(0.5)",
    "grayscale(0.6) contrast(1.4) brightness(0.8) sepia(0.3)",
    "hue-rotate(-20deg) saturate(1.5) contrast(1.2)",
]
