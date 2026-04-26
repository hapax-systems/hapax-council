"""``users.watch()`` invocation + watch-state persistence.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §5.2.

The Gmail watch is the load-bearing privacy substrate — calling it
with ``labelFilterAction=INCLUDE`` and the four ``Hapax/*`` label ids
guarantees Pub/Sub events fire only for Hapax-labelled mail. A
regression in this invariant turns the daemon into a full-mailbox
reader; CI tests pin it.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Spec §5.2 invariant. Tests assert this constant flows into every
# watch() body. Do not parameterise.
WATCH_LABEL_FILTER_ACTION = "INCLUDE"

WATCH_STATE_PATH = Path("~/.cache/mail-monitor/watch.json").expanduser()

# Gmail enforces a 7-day max watch lifetime (Google reference). The
# renewal timer fires daily so watches never expire under normal
# conditions.
GMAIL_WATCH_LIFETIME_S = 7 * 24 * 3600.0


class WatchError(RuntimeError):
    """Raised when watch() cannot be invoked (empty label_ids, etc.)."""


def call_watch(
    service: Any,
    *,
    topic_path: str,
    label_ids: list[str],
) -> dict[str, Any]:
    """Invoke ``users.watch()`` with the INCLUDE filter; persist the result.

    The Gmail discovery client is fluent: ``service.users().watch(
    userId="me", body={...}).execute()``. Body fields are the spec
    invariants:

    - ``topicName`` — full Pub/Sub topic path
      (``projects/<p>/topics/hapax-mail-monitor``)
    - ``labelIds`` — list of the four ``Hapax/*`` label ids
    - ``labelFilterAction`` — ``INCLUDE`` (substrate of §5.2)

    Returns the response dict (contains ``historyId`` + ``expiration``)
    after persisting it atomically to :data:`WATCH_STATE_PATH`.
    """
    if not label_ids:
        raise WatchError(
            "label_ids is empty; users.watch() refuses to run without "
            "INCLUDE filter (spec §5.2 invariant)."
        )

    body = {
        "topicName": topic_path,
        "labelIds": list(label_ids),
        "labelFilterAction": WATCH_LABEL_FILTER_ACTION,
    }
    response = service.users().watch(userId="me", body=body).execute()
    _persist(response)
    return response


def _persist(response: dict[str, Any]) -> None:
    """Atomic tmp+rename write to :data:`WATCH_STATE_PATH`."""
    WATCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WATCH_STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(response, indent=2))
    tmp.rename(WATCH_STATE_PATH)


def load_watch_state() -> dict[str, Any] | None:
    """Read the persisted watch response, or ``None`` if no prior call."""
    if not WATCH_STATE_PATH.exists():
        return None
    try:
        return json.loads(WATCH_STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to read %s: %s", WATCH_STATE_PATH, exc)
        return None


def watch_age_s(*, now: float | None = None) -> float | None:
    """Return seconds since the last successful watch() call.

    Computed from the persisted ``expiration`` (Gmail returns a unix-ms
    timestamp 7 days after the call). Returns ``None`` when no watch
    state is persisted or the field is missing.
    """
    state = load_watch_state()
    if not state:
        return None
    expiration_ms = state.get("expiration")
    if expiration_ms is None:
        return None
    try:
        expiration_s = float(expiration_ms) / 1000.0
    except (ValueError, TypeError):
        return None
    last_call_s = expiration_s - GMAIL_WATCH_LIFETIME_S
    return (now if now is not None else time.time()) - last_call_s
