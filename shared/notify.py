"""shared/notify.py — Unified notification dispatch.

Sends desktop notifications via notify-send (KDE Plasma native D-Bus).
All egress paths in the system converge here.

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
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from shared.governance.consent_label import ConsentLabel


def _run_subprocess(*args, **kwargs):
    """Wrapper for subprocess.run, patchable without global side effects."""
    return subprocess.run(*args, **kwargs)  # noqa: S603


_log = logging.getLogger(__name__)

# ── Watershed event emission ────────────────────────────────────────────────
# When logos is running, notifications also appear as ephemeral ripples in the
# watershed region. Routine events suppress desktop when logos is active.

_WATERSHED_FILE = Path("/dev/shm/hapax-compositor/watershed-events.json")
_VL_STATE_FILE = Path("/dev/shm/hapax-compositor/visual-layer-state.json")

# tag → (signal category, base severity, ttl_s)
_TAG_ROUTING: dict[str, tuple[str, float, float]] = {
    # Sync completions — routine, short ripple
    "git": ("system_state", 0.15, 30.0),
    "robot": ("system_state", 0.15, 30.0),
    "chrome": ("system_state", 0.15, 30.0),
    "obsidian": ("system_state", 0.15, 30.0),
    "cloud": ("system_state", 0.15, 30.0),
    "mail": ("system_state", 0.15, 30.0),
    "calendar": ("system_state", 0.15, 30.0),
    "langfuse": ("system_state", 0.15, 30.0),
    # Media processing
    "microphone": ("ambient_sensor", 0.20, 30.0),
    "movie_camera": ("ambient_sensor", 0.20, 30.0),
    "link": ("ambient_sensor", 0.20, 30.0),
    # Actionable content
    "clipboard": ("context_time", 0.35, 60.0),
    "books": ("context_time", 0.35, 60.0),
    "telescope": ("context_time", 0.35, 60.0),
    # Maintenance
    "broom": ("system_state", 0.25, 45.0),
    # Governance
    "warning": ("governance", 0.45, 60.0),
    "gear": ("governance", 0.30, 45.0),
    # Critical
    "skull": ("health_infra", 0.90, 120.0),
    "rotating_light": ("health_infra", 0.90, 120.0),
    "white_check_mark": ("health_infra", 0.15, 30.0),
    # Consent
    "bust_in_silhouette": ("governance", 0.85, 120.0),
}


def _logos_is_active() -> bool:
    """Check if logos visual layer is running (state file fresh < 10s)."""
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
    """Write a watershed event for the visual layer aggregator to pick up."""
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


# ── Configuration ────────────────────────────────────────────────────────────

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
    consent_label: ConsentLabel | None = None,
) -> bool:
    """Send a desktop notification via notify-send (KDE Plasma native D-Bus)."""
    try:
        from shared.speech_safety import censor as _censor_speech

        title_r = _censor_speech(title)
        message_r = _censor_speech(message)
        if title_r.was_modified or message_r.was_modified:
            _log.warning(
                "notify safety-gate: redacted %d title-token(s) + %d message-token(s)",
                title_r.hit_count,
                message_r.hit_count,
            )
            title = title_r.text
            message = message_r.text
    except Exception:
        _log.debug("notify: speech_safety censor import/call failed", exc_info=True)

    if consent_label is not None and consent_label != ConsentLabel.bottom():
        _log.info("Notification suppressed: consent label non-public (%s)", title)
        return True

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


def send_webhook(
    url: str,
    payload: dict,
    *,
    timeout: float = 10.0,
) -> bool:
    """POST JSON to a webhook URL (e.g. n8n workflow trigger)."""
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
    """Generate an obsidian:// URI to open a note in Obsidian."""
    if vault_path.endswith(".md"):
        vault_path = vault_path[:-3]
    return f"obsidian://open?vault={quote(OBSIDIAN_VAULT_NAME)}&file={quote(vault_path)}"


def briefing_uri(date_str: str) -> str:
    """Generate an Obsidian URI for a specific briefing note."""
    return obsidian_uri(f"30-system/briefings/{date_str}")


def nudges_uri() -> str:
    """Generate an Obsidian URI for the nudges note."""
    return obsidian_uri("30-system/nudges")


# ── LLM-Enriched Notifications ──────────────────────────────────────────────

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
    """Call claude-haiku via LiteLLM to produce an actionable summary."""
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
    """Enrich a raw diagnostic message via LLM, then send as desktop notification."""
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


def _send_desktop(title: str, message: str, *, priority: str = "default") -> bool:
    """Send notification via notify-send (KDE Plasma native D-Bus)."""
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
