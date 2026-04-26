"""Append-only payment-event log shared by all receive rails.

Each rail (Lightning, Nostr Zap, Liberapay) calls ``append_event``
with a ``PaymentEvent`` once per confirmed receipt. The log lives at
``/dev/shm/hapax-monetization/events.jsonl`` (operator-overridable
via ``HAPAX_MONETIZATION_LOG_PATH``).

The aggregator tails the log and pushes the most recent event into
the awareness ``MonetizationBlock``. Storage in /dev/shm is
intentional — the log is ephemeral by spec; persistent monetization
records belong in the chronicle (see ``shared.chronicle.record``)
which receivers also call.

Idempotency: rails MUST set ``external_id`` (Alby invoice id, Nostr
zap event id, Liberapay sponsorship id) so the aggregator can skip
duplicates. The log itself is append-only and never deduplicates;
deduplication happens at read time keyed by ``(rail, external_id)``.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from pathlib import Path

from prometheus_client import Counter

from agents.operator_awareness.state import PaymentEvent

log = logging.getLogger(__name__)

DEFAULT_PAYMENT_LOG_PATH = Path(
    os.environ.get(
        "HAPAX_MONETIZATION_LOG_PATH",
        "/dev/shm/hapax-monetization/events.jsonl",
    )
)

# Bounded tail length when reading the log. Aggregator displays the
# latest event; counter math walks the full file but stops early once
# the bounded tail is satisfied — see ``tail_events``.
DEFAULT_TAIL_LIMIT = 200

_lock = threading.Lock()

payment_events_appended_total = Counter(
    "hapax_payment_events_appended_total",
    "Receive-rail payment events appended to the canonical log.",
    ["rail"],
)


def append_event(event: PaymentEvent, *, log_path: Path | None = None) -> bool:
    """Append one event to the JSONL log; return True iff written.

    When ``log_path`` is omitted, re-resolves the module-level
    ``DEFAULT_PAYMENT_LOG_PATH`` at call time so monkeypatching that
    attribute in tests takes effect.

    Thread-safe: serialises concurrent appends so concurrent
    Lightning + Liberapay writers never interleave bytes mid-line.
    Best-effort: file system errors log and return False rather than
    raise — receive-rail emission must never break the rail's polling
    loop.
    """
    target = log_path if log_path is not None else DEFAULT_PAYMENT_LOG_PATH
    line = event.model_dump_json() + "\n"
    with _lock:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
        except OSError:
            log.warning("payment-event log append failed at %s", target, exc_info=True)
            return False
    payment_events_appended_total.labels(rail=event.rail).inc()
    return True


def tail_events(
    *,
    limit: int = DEFAULT_TAIL_LIMIT,
    log_path: Path | None = None,
) -> list[PaymentEvent]:
    """Tail the last ``limit`` valid PaymentEvents from the log.

    When ``log_path`` is omitted, re-resolves the module-level
    ``DEFAULT_PAYMENT_LOG_PATH`` at call time (monkeypatch-friendly).

    Returns events in file order (oldest first). Malformed lines are
    skipped at debug level. Missing file → empty list (no rails have
    fired yet).
    """
    target = log_path if log_path is not None else DEFAULT_PAYMENT_LOG_PATH
    if not target.exists():
        return []
    tail: deque[PaymentEvent] = deque(maxlen=limit)
    try:
        with target.open("r", encoding="utf-8") as fh:
            for raw in fh:
                text = raw.strip()
                if not text:
                    continue
                try:
                    event = PaymentEvent.model_validate_json(text)
                except (ValueError, TypeError):
                    log.debug("malformed payment-event line skipped")
                    continue
                tail.append(event)
    except OSError:
        log.warning("payment-event log read failed at %s", target, exc_info=True)
        return []
    return list(tail)


__all__ = [
    "DEFAULT_PAYMENT_LOG_PATH",
    "DEFAULT_TAIL_LIMIT",
    "append_event",
    "payment_events_appended_total",
    "tail_events",
]
