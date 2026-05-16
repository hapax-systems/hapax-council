"""Vendored notification dispatch for the logos package.

Full copy of shared/notify.py -- unified notification via KDE Plasma
notify-send + watershed visual layer.
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import os
import subprocess
import time
from pathlib import Path


def _run_subprocess(*args, **kwargs):
    """Wrapper for subprocess.run, patchable without global side effects."""
    return subprocess.run(*args, **kwargs)  # noqa: S603


_log = logging.getLogger(__name__)

# -- Watershed event emission --------------------------------------------------

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


def _logos_is_active() -> bool:
    try:
        stat = _VL_STATE_FILE.stat()
        return (time.time() - stat.st_mtime) < 10.0
    except (FileNotFoundError, OSError):
        return False


def _emit_watershed_event(
    title: str,
    message: str,
    tags: list[str] | None,
    priority: str,
) -> None:
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


# -- Deduplication -------------------------------------------------------------

_DEDUP_FILE = Path(os.environ.get("NTFY_DEDUP_FILE", Path.home() / ".cache" / "ntfy-dedup.json"))
_DEDUP_COOLDOWN = int(os.environ.get("NTFY_DEDUP_COOLDOWN_SECONDS", "3600"))


def _dedup_key(title: str, message: str) -> str:
    return hashlib.sha256(f"{title}\x00{message}".encode()).hexdigest()[:16]


def _is_duplicate(title: str, message: str) -> bool:
    key = _dedup_key(title, message)
    now = time.time()
    state: dict = {}
    try:
        if _DEDUP_FILE.exists():
            state = _json.loads(_DEDUP_FILE.read_text())
    except Exception:
        pass
    last_sent = state.get(key, 0)
    if now - last_sent < _DEDUP_COOLDOWN:
        return True
    state[key] = now
    state = {k: v for k, v in state.items() if now - v < _DEDUP_COOLDOWN * 4}
    try:
        _DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DEDUP_FILE.write_text(_json.dumps(state))
    except Exception:
        pass
    return False


# -- Configuration -------------------------------------------------------------


_DESKTOP_URGENCY = {
    "min": "low",
    "low": "low",
    "default": "normal",
    "high": "critical",
    "urgent": "critical",
}


# -- Public API ----------------------------------------------------------------


def send_notification(
    title: str,
    message: str,
    *,
    priority: str = "default",
    tags: list[str] | None = None,
    topic: str | None = None,
    click_url: str | None = None,
) -> bool:
    """Send a push notification. KDE Plasma native D-Bus via notify-send."""
    if _is_duplicate(title, message):
        _log.debug("Suppressed duplicate notification: %s", title)
        return True

    _emit_watershed_event(title, message, tags, priority)

    logos_active = _logos_is_active()
    if logos_active and priority in ("min", "low", "default"):
        _log.debug("Logos active, watershed-only for routine: %s", title)
        return True

    try:
        delivered = _send_desktop(title, message, priority=priority)
    except Exception as exc:
        _log.debug("notify-send failed: %s", exc)
        delivered = False

    if not delivered and not logos_active:
        _log.warning("Notification delivery failed for: %s", title)

    return delivered or logos_active


# -- Private helpers -----------------------------------------------------------


def _send_desktop(title: str, message: str, *, priority: str = "default") -> bool:
    urgency = _DESKTOP_URGENCY.get(priority, "normal")
    cmd = [
        "notify-send",
        f"--urgency={urgency}",
        "--app-name=LLM Stack",
        title,
        message,
    ]
    try:
        result = _run_subprocess(cmd, timeout=5, capture_output=True)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
