"""shared/notify.py — Unified notification dispatch.

Sends push notifications via ntfy (preferred) with automatic fallback
to desktop notify-send. All egress paths in the system converge here.

Configuration:
    NTFY_BASE_URL: ntfy server URL (default: http://localhost:8090)
    NTFY_TOPIC:    default topic (default: cockpit)

Usage:
    from shared.notify import send_notification
    send_notification("Stack Healthy", "All 44 checks passed", priority="default")
    send_notification("Health Alert", "3 checks failed", priority="high", tags=["warning"])
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import os
import subprocess


def _run_subprocess(*args, **kwargs):
    """Wrapper for subprocess.run, patchable without global side effects."""
    return subprocess.run(*args, **kwargs)  # noqa: S603


import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_log = logging.getLogger(__name__)

# ── Deduplication ────────────────────────────────────────────────────────────
# Suppress identical notifications within a cooldown window.
# State is stored in a small JSON file keyed by hash(title+message).

_DEDUP_FILE = Path(os.environ.get("NTFY_DEDUP_FILE", Path.home() / ".cache" / "ntfy-dedup.json"))
_DEDUP_COOLDOWN = int(os.environ.get("NTFY_DEDUP_COOLDOWN_SECONDS", "3600"))  # 1 hour default


def _dedup_key(title: str, message: str) -> str:
    return hashlib.sha256(f"{title}\x00{message}".encode()).hexdigest()[:16]


def _is_duplicate(title: str, message: str) -> bool:
    """Return True if this exact notification was sent within the cooldown window."""
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
    # Record this send and prune old entries
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

# Priority mapping: ntfy uses 1-5 scale
_NTFY_PRIORITIES = {
    "min": "1",
    "low": "2",
    "default": "3",
    "high": "4",
    "urgent": "5",
}

# Map notify-send urgency from our priority levels
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
    message: str,
    *,
    priority: str = "default",
    tags: list[str] | None = None,
    topic: str | None = None,
    click_url: str | None = None,
) -> bool:
    """Send a push notification. Tries ntfy first, falls back to notify-send.

    Args:
        title: Notification title.
        message: Notification body text.
        priority: One of min, low, default, high, urgent.
        tags: ntfy tags/emojis (e.g. ["warning", "robot"]).
        topic: Override default topic.
        click_url: URL to open when notification is clicked (ntfy only).

    Returns:
        True if notification was delivered via at least one channel.
    """
    # Dedup: suppress identical notifications within cooldown window
    if _is_duplicate(title, message):
        _log.debug("Suppressed duplicate notification: %s", title)
        return True  # Pretend delivered — caller shouldn't retry

    delivered = False

    # Try ntfy first
    try:
        delivered = _send_ntfy(
            title, message, priority=priority, tags=tags, topic=topic, click_url=click_url
        )
    except Exception as exc:
        _log.debug("ntfy failed: %s", exc)

    # Always also send desktop notification (may not be visible if no display)
    try:
        if _send_desktop(title, message, priority=priority):
            delivered = True
    except Exception as exc:
        _log.debug("notify-send failed: %s", exc)

    if not delivered:
        _log.warning("All notification channels failed for: %s", title)

    return delivered


def send_webhook(
    url: str,
    payload: dict,
    *,
    timeout: float = 10.0,
) -> bool:
    """POST JSON to a webhook URL (e.g. n8n workflow trigger).

    Args:
        url: Webhook URL.
        payload: JSON-serializable dict.
        timeout: Request timeout in seconds.

    Returns:
        True if webhook returned 2xx.
    """
    import json

    data = json.dumps(payload).encode()
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        _log.warning("Webhook POST to %s failed: %s", url, exc)
        return False


# ── Obsidian URI helpers ─────────────────────────────────────────────────────

OBSIDIAN_VAULT_NAME: str = os.environ.get("OBSIDIAN_VAULT_NAME", "Personal")


def obsidian_uri(vault_path: str) -> str:
    """Generate an obsidian:// URI to open a note in Obsidian.

    Args:
        vault_path: Path relative to vault root (e.g. "30-system/briefings/2026-03-04.md").
                    The .md extension is optional — Obsidian handles both.

    Returns:
        obsidian://open URL string.
    """
    # Strip .md suffix — Obsidian open action uses note name without extension
    if vault_path.endswith(".md"):
        vault_path = vault_path[:-3]
    return f"obsidian://open?vault={quote(OBSIDIAN_VAULT_NAME)}&file={quote(vault_path)}"


def briefing_uri(date_str: str) -> str:
    """Generate an Obsidian URI for a specific briefing note.

    Args:
        date_str: Date in YYYY-MM-DD format.
    """
    return obsidian_uri(f"30-system/briefings/{date_str}")


def nudges_uri() -> str:
    """Generate an Obsidian URI for the nudges note."""
    return obsidian_uri("30-system/nudges")


# ── LLM-Enriched Notifications ──────────────────────────────────────────────

# LiteLLM configuration for enrichment calls
from shared.config import LITELLM_BASE as _LITELLM_BASE_RAW

_LITELLM_BASE: str = _LITELLM_BASE_RAW.rstrip("/")
_LITELLM_OPENAI_BASE: str = (
    _LITELLM_BASE if _LITELLM_BASE.endswith("/v1") else f"{_LITELLM_BASE}/v1"
)
_LITELLM_KEY: str = os.environ.get("LITELLM_API_KEY", "changeme")
_ENRICHMENT_MODEL: str = "claude-haiku"
_ENRICHMENT_TIMEOUT: float = 10.0

_ENRICHMENT_SYSTEM_PROMPT = (
    "You are a concise system health assistant. Given raw diagnostic output, "
    "produce a short actionable summary (2-4 sentences max). Focus on: "
    "what failed, likely cause, and the single most useful next step. "
    "No markdown, no headers — plain text only."
)


def _enrich_message(subject: str, raw_context: str) -> str:
    """Call claude-haiku via LiteLLM to produce an actionable summary.

    Falls back to raw_context if the LLM call fails for any reason.
    """
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=_LITELLM_OPENAI_BASE,
            api_key=_LITELLM_KEY,
            timeout=_ENRICHMENT_TIMEOUT,
        )
        resp = client.chat.completions.create(
            model=_ENRICHMENT_MODEL,
            messages=[
                {"role": "system", "content": _ENRICHMENT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Subject: {subject}\n\n{raw_context}"},
            ],
            max_tokens=256,
            temperature=0.2,
        )
        enriched = resp.choices[0].message.content
        if enriched and enriched.strip():
            return enriched.strip()
        _log.debug("LLM enrichment returned empty response, using raw message")
        return raw_context
    except Exception as exc:
        _log.debug("LLM enrichment failed (falling back to raw): %s", exc)
        return raw_context


def send_enriched_notification(
    title: str,
    raw_context: str,
    *,
    priority: str = "default",
    tags: list[str] | None = None,
    topic: str | None = None,
    click_url: str | None = None,
) -> bool:
    """Enrich a raw diagnostic message via LLM, then send as notification.

    Calls claude-haiku through LiteLLM to produce a concise actionable summary
    from raw diagnostic output. Falls back to the raw message if the LLM call
    fails (timeout, network error, etc.).

    Args:
        title: Notification title (also used as LLM subject context).
        raw_context: Raw diagnostic text to summarize.
        priority: One of min, low, default, high, urgent.
        tags: ntfy tags/emojis.
        topic: Override default topic.
        click_url: URL to open when notification is clicked.

    Returns:
        True if notification was delivered via at least one channel.
    """
    enriched = _enrich_message(title, raw_context)
    return send_notification(
        title,
        enriched,
        priority=priority,
        tags=tags,
        topic=topic,
        click_url=click_url,
    )


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
