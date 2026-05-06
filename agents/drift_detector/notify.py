"""Notification dispatch — dedup, ntfy, desktop, watershed."""

from __future__ import annotations

import hashlib
import json as _json
import logging
import os
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .watershed import emit_watershed_event, logos_is_active

_log = logging.getLogger(__name__)


def _run_subprocess(*args, **kwargs):
    """Wrapper for subprocess.run, patchable without global side effects."""
    return subprocess.run(*args, **kwargs)  # noqa: S603


# ── Deduplication ────────────────────────────────────────────────────────────

_DEDUP_FILE = Path(os.environ.get("NTFY_DEDUP_FILE", Path.home() / ".cache" / "ntfy-dedup.json"))
_DEDUP_COOLDOWN = int(os.environ.get("NTFY_DEDUP_COOLDOWN_SECONDS", "3600"))


def _dedup_key(title: str, message: str) -> str:
    return hashlib.sha256(f"{title}\x00{message}".encode()).hexdigest()[:16]


def _is_duplicate(title: str, message: str) -> bool:
    """Return True if this exact notification was sent within the cooldown window."""
    key = _dedup_key(title, message)
    now = time.time()
    state: dict = {}
    try:
        if _DEDUP_FILE.exists():
            parsed = _json.loads(_DEDUP_FILE.read_text())
            if isinstance(parsed, dict):
                state = parsed
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


# ── Configuration ────────────────────────────────────────────────────────────

NTFY_BASE_URL: str = os.environ.get("NTFY_BASE_URL", "http://localhost:8090")
NTFY_TOPIC: str = os.environ.get("NTFY_TOPIC", "cockpit")

_NTFY_PRIORITIES = {
    "min": "1",
    "low": "2",
    "default": "3",
    "high": "4",
    "urgent": "5",
}

_DESKTOP_URGENCY = {
    "min": "low",
    "low": "low",
    "default": "normal",
    "high": "critical",
    "urgent": "critical",
}


# ── Public API ───────────────────────────────────────────────────────────────


def send_notification(
    title: str,
    message: str = "",
    *,
    body: str = "",
    priority: str = "default",
    tags: list[str] | None = None,
    topic: str | None = None,
    click_url: str | None = None,
) -> bool:
    """Send a push notification. Tries ntfy first, falls back to notify-send."""
    msg = message or body

    if _is_duplicate(title, msg):
        _log.debug("Suppressed duplicate notification: %s", title)
        return True

    emit_watershed_event(title, msg, tags, priority)

    active = logos_is_active()
    if active and priority in ("min", "low", "default"):
        _log.debug("Logos active, watershed-only for routine: %s", title)
        return True

    delivered = False

    try:
        delivered = _send_ntfy(
            title, msg, priority=priority, tags=tags, topic=topic, click_url=click_url
        )
    except Exception as exc:
        _log.debug("ntfy failed: %s", exc)

    if not active:
        try:
            if _send_desktop(title, msg, priority=priority):
                delivered = True
        except Exception as exc:
            _log.debug("notify-send failed: %s", exc)

    if not delivered and not active:
        _log.warning("All notification channels failed for: %s", title)

    return delivered or active


# ── Private helpers ──────────────────────────────────────────────────────────


def _send_ntfy(
    title: str,
    message: str,
    *,
    priority: str = "default",
    tags: list[str] | None = None,
    topic: str | None = None,
    click_url: str | None = None,
) -> bool:
    """Send notification via ntfy HTTP API."""
    target_topic = topic or NTFY_TOPIC
    url = f"{NTFY_BASE_URL.rstrip('/')}/{target_topic}"

    req = Request(url, data=message.encode("utf-8"), method="POST")
    req.add_header("Title", title)
    req.add_header("Priority", _NTFY_PRIORITIES.get(priority, "3"))

    if tags:
        req.add_header("Tags", ",".join(tags))
    if click_url:
        req.add_header("Click", click_url)

    try:
        with urlopen(req, timeout=5) as resp:
            ok = 200 <= resp.status < 300
            if ok:
                _log.debug("ntfy: sent to %s (HTTP %d)", target_topic, resp.status)
            return ok
    except (URLError, OSError) as exc:
        _log.debug("ntfy unreachable at %s: %s", url, exc)
        return False


def _send_desktop(title: str, message: str, *, priority: str = "default") -> bool:
    """Send notification via notify-send (desktop only)."""
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
