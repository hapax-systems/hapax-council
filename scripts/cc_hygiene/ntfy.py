"""ntfy alert dispatch + per-topic-class throttle (PR5 of task-list hygiene).

Surface A of the operator-visibility tier. Only **high-severity** events
push to ntfy:

* ``duplicate_claim`` (severity ``violation``)
* ``orphan_pr`` (severity ``warning``) — gated to age >= 6h via metadata
* ``relay_yaml_stale`` (severity ``warning``) — gated to age >= 60min via metadata

Steady-state pulses + ``info`` events stay out of the operator's phone:
research §3 says ntfy is for actionable violations, not heartbeats.

Throttle: max 1 alert per topic-class (``check_id``) per ``THROTTLE_MIN``
minutes. State at ``~/.cache/hapax/cc-hygiene-ntfy-throttle.json``.

The actual HTTP send is delegated to ``shared/notify.send_notification``;
this module only handles selection + throttle.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import HygieneEvent

LOG = logging.getLogger("cc-hygiene-ntfy")

NTFY_TOPIC = "hapax-workstream-hygiene"
"""Existing operator topic; PR5 reuses this single channel."""

NTFY_PRIORITY = "high"
"""Maps to ntfy priority 4 (research §3 recommendation)."""

THROTTLE_MIN = 5
"""Max 1 alert per (topic-class, ntfy topic) per this many minutes."""

DEFAULT_THROTTLE_PATH = Path.home() / ".cache" / "hapax" / "cc-hygiene-ntfy-throttle.json"
"""Throttle state file."""

ORPHAN_PR_NTFY_AGE_HOURS = 6
"""Per research §3: orphan-PR alerts at >6h, not at the 1h sweeper trigger."""

RELAY_STALE_NTFY_AGE_MIN = 60
"""Per research §3: session-silent alerts at >60min, not the 30min sweeper trigger."""

KILLSWITCH_ENV = "HAPAX_CC_HYGIENE_OFF"

OBSIDIAN_VAULT = "Personal"
"""Operator's vault name for obsidian:// click-through URIs."""


@dataclass(frozen=True)
class AlertResult:
    """One alert decision (send / skip)."""

    check_id: str
    task_id: str | None
    sent: bool
    reason: str
    """Either 'sent', 'throttled', 'sub-threshold', 'low-severity'."""


# ---------------------------------------------------------------------------
# throttle state
# ---------------------------------------------------------------------------


def _load_throttle(path: Path) -> dict[str, str]:
    """Return ``{topic_class: iso8601_last_sent}``. Tolerant of missing/garbage."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


def _save_throttle(state: dict[str, str], path: Path) -> None:
    """Write atomically (tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _is_throttled(state: dict[str, str], key: str, now: datetime) -> bool:
    """True if the last alert for ``key`` was within ``THROTTLE_MIN`` minutes."""
    raw = state.get(key)
    if not raw:
        return False
    try:
        last = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (now - last) < timedelta(minutes=THROTTLE_MIN)


# ---------------------------------------------------------------------------
# event-selection
# ---------------------------------------------------------------------------


def _is_high_severity(event: HygieneEvent) -> bool:
    """Per research §3: ntfy gates on duplicate-claim + orphan-PR>6h + session>60min.

    Concretely:

    * ``severity == "violation"`` → always alert (e.g. duplicate_claim,
      ghost_claimed). Constitutional-grade signals.
    * ``check_id == "orphan_pr"`` AND ``age_hours >= 6`` → alert.
    * ``check_id == "relay_yaml_stale"`` AND ``age_minutes >= 60`` → alert.
    * everything else → no ntfy (steady-state).
    """
    if event.severity == "violation":
        return True
    if event.check_id == "orphan_pr":
        # The sweeper does not yet emit an explicit age field; derive from
        # the createdAt metadata if present.
        try:
            created_raw = event.metadata.get("createdAt", "")
            if not created_raw:
                return False
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            age = event.timestamp - created
            return age >= timedelta(hours=ORPHAN_PR_NTFY_AGE_HOURS)
        except (ValueError, KeyError):
            return False
    if event.check_id == "relay_yaml_stale":
        try:
            age_min = int(event.metadata.get("age_minutes", "0"))
        except ValueError:
            return False
        return age_min >= RELAY_STALE_NTFY_AGE_MIN
    return False


# ---------------------------------------------------------------------------
# obsidian click-through
# ---------------------------------------------------------------------------


def _vault_click_url(task_id: str | None) -> str | None:
    """Build an ``obsidian://open?vault=...&file=...`` URL for the cc-task note."""
    if not task_id:
        return None
    from urllib.parse import quote

    note_path = f"20-projects/hapax-cc-tasks/active/{task_id}"
    return f"obsidian://open?vault={quote(OBSIDIAN_VAULT)}&file={quote(note_path)}"


# ---------------------------------------------------------------------------
# message-formatting
# ---------------------------------------------------------------------------


def _format_title(event: HygieneEvent) -> str:
    return f"[VIOLATION] {event.check_id}"


def _format_body(event: HygieneEvent) -> str:
    """Terse one-line body: ``[VIOLATION] {check_id} {task_id}: {summary}``."""
    parts = [f"[VIOLATION] {event.check_id}"]
    if event.task_id:
        parts.append(event.task_id)
    if event.session:
        parts.append(f"@{event.session}")
    return " ".join(parts) + f": {event.message}"


# ---------------------------------------------------------------------------
# sender adapter (decoupled for tests)
# ---------------------------------------------------------------------------

NotifySender = Callable[..., bool]
"""Type of ``shared.notify.send_notification`` (kwargs include ``priority``,
``tags``, ``topic``, ``click_url``)."""


def _default_sender() -> NotifySender:
    """Return the canonical ``shared.notify.send_notification`` adapter."""
    from shared.notify import send_notification

    return send_notification


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def dispatch_alerts(
    events: Iterable[HygieneEvent],
    *,
    now: datetime | None = None,
    throttle_path: Path = DEFAULT_THROTTLE_PATH,
    sender: NotifySender | None = None,
    topic: str = NTFY_TOPIC,
    priority: str = NTFY_PRIORITY,
) -> list[AlertResult]:
    """Send one alert per high-severity event, modulo per-topic-class throttle.

    Honors ``HAPAX_CC_HYGIENE_OFF=1`` killswitch (no alerts dispatched).

    Returns one ``AlertResult`` per inspected high-severity event so the
    sweeper can log decisions.
    """
    now = now or datetime.now(UTC)
    if os.environ.get(KILLSWITCH_ENV) == "1":
        LOG.info("ntfy: killswitch active, skipping all alerts")
        return []

    sender = sender or _default_sender()
    state = _load_throttle(throttle_path)

    results: list[AlertResult] = []
    mutated = False
    for event in events:
        if not _is_high_severity(event):
            results.append(
                AlertResult(
                    check_id=event.check_id,
                    task_id=event.task_id,
                    sent=False,
                    reason="sub-threshold",
                )
            )
            continue

        # throttle-key is per-topic-class so duplicate-claim across many
        # tasks in the same sweep collapses to one alert per 5-min window.
        key = f"{topic}::{event.check_id}"
        if _is_throttled(state, key, now):
            results.append(
                AlertResult(
                    check_id=event.check_id,
                    task_id=event.task_id,
                    sent=False,
                    reason="throttled",
                )
            )
            continue

        title = _format_title(event)
        body = _format_body(event)
        click_url = _vault_click_url(event.task_id)
        try:
            sender(
                title,
                body,
                priority=priority,
                tags=["warning"],
                topic=topic,
                click_url=click_url,
            )
        except Exception as exc:  # noqa: BLE001
            # ntfy failure must never crash the sweeper.
            LOG.warning("ntfy send failed for %s: %s", event.check_id, exc)
            results.append(
                AlertResult(
                    check_id=event.check_id,
                    task_id=event.task_id,
                    sent=False,
                    reason="send-error",
                )
            )
            continue

        state[key] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        mutated = True
        results.append(
            AlertResult(
                check_id=event.check_id,
                task_id=event.task_id,
                sent=True,
                reason="sent",
            )
        )

    if mutated:
        try:
            _save_throttle(state, throttle_path)
        except OSError as exc:
            LOG.warning("ntfy throttle persist failed: %s", exc)

    return results


def is_high_severity(event: HygieneEvent) -> bool:
    """Public wrapper for the gate predicate (used by tests + sweeper logging)."""
    return _is_high_severity(event)


__all__ = [
    "DEFAULT_THROTTLE_PATH",
    "KILLSWITCH_ENV",
    "NTFY_PRIORITY",
    "NTFY_TOPIC",
    "ORPHAN_PR_NTFY_AGE_HOURS",
    "RELAY_STALE_NTFY_AGE_MIN",
    "THROTTLE_MIN",
    "AlertResult",
    "NotifySender",
    "dispatch_alerts",
    "is_high_severity",
]
