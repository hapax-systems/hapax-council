"""Watershed event emission for the visual layer aggregator."""

from __future__ import annotations

import json as _json
import logging
import time
from pathlib import Path

_log = logging.getLogger(__name__)

_WATERSHED_FILE = Path("/dev/shm/hapax-compositor/watershed-events.json")
_VL_STATE_FILE = Path("/dev/shm/hapax-compositor/visual-layer-state.json")

_TAG_ROUTING: dict[str, tuple[str, float, float]] = {
    "git": ("system_state", 0.15, 30.0),
    "robot": ("system_state", 0.15, 30.0),
    "chrome": ("system_state", 0.15, 30.0),
    "obsidian": ("system_state", 0.15, 30.0),
    "cloud": ("system_state", 0.15, 30.0),
    "mail": ("system_state", 0.15, 30.0),
    "calendar": ("system_state", 0.15, 30.0),
    "langfuse": ("system_state", 0.15, 30.0),
    "microphone": ("ambient_sensor", 0.20, 30.0),
    "movie_camera": ("ambient_sensor", 0.20, 30.0),
    "link": ("ambient_sensor", 0.20, 30.0),
    "clipboard": ("context_time", 0.35, 60.0),
    "books": ("context_time", 0.35, 60.0),
    "telescope": ("context_time", 0.35, 60.0),
    "broom": ("system_state", 0.25, 45.0),
    "warning": ("governance", 0.45, 60.0),
    "gear": ("governance", 0.30, 45.0),
    "skull": ("health_infra", 0.90, 120.0),
    "rotating_light": ("health_infra", 0.90, 120.0),
    "white_check_mark": ("health_infra", 0.15, 30.0),
    "bust_in_silhouette": ("governance", 0.85, 120.0),
}


def logos_is_active() -> bool:
    """Check if logos visual layer is running."""
    try:
        stat = _VL_STATE_FILE.stat()
        return (time.time() - stat.st_mtime) < 10.0
    except (FileNotFoundError, OSError):
        return False


def emit_watershed_event(
    title: str,
    message: str,
    tags: list[str] | None,
    priority: str,
) -> None:
    """Write a watershed event for the visual layer aggregator."""
    category = "system_state"
    severity = 0.20
    ttl = 30.0

    if tags:
        for tag in tags:
            if tag in _TAG_ROUTING:
                category, severity, ttl = _TAG_ROUTING[tag]
                break

    if priority in ("high", "urgent"):
        severity = max(severity, 0.70)
        ttl = max(ttl, 60.0)

    event = {
        "category": category,
        "severity": severity,
        "title": title,
        "detail": message[:200] if message else "",
        "emitted_at": time.time(),
        "ttl_s": ttl,
    }

    try:
        events: list[dict] = []
        if _WATERSHED_FILE.exists():
            events = _json.loads(_WATERSHED_FILE.read_text())

        events.append(event)
        now = time.time()
        events = [e for e in events if now - e.get("emitted_at", 0) < e.get("ttl_s", 30)]
        events = events[-20:]

        _WATERSHED_FILE.write_text(_json.dumps(events))
    except Exception:
        _log.debug("Failed to write watershed event", exc_info=True)
