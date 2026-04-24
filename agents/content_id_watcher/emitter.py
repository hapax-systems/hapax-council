"""Emit ``ChangeEvent`` to the impingement bus + ntfy + Prometheus.

Three sinks, all best-effort:
    * **Impingement.** Append-only JSONL line on
      ``/dev/shm/hapax-dmn/impingements.jsonl``. The daimonion's
      affordance + CPAL consumers pick up via their cursor files.
    * **ntfy.** Fires for ``HIGH_SALIENCE_KINDS`` only — phone alerts
      are reserved for changes that demand operator decision.
    * **Prometheus counter.** ``hapax_broadcast_content_id_events_total``
      with a ``kind`` label, scraped by the existing watcher rig.

Sink failures don't propagate: a failed ntfy or metric must not stop
the poll loop. Failures are logged at WARN.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from agents.content_id_watcher.change_detector import ChangeEvent

log = logging.getLogger(__name__)

_IMPINGEMENT_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")


try:
    from prometheus_client import Counter

    _EVENTS_TOTAL = Counter(
        "hapax_broadcast_content_id_events_total",
        "Content-ID watcher events emitted to the impingement bus.",
        ["kind"],
    )

    def _record_metric(kind: str) -> None:
        _EVENTS_TOTAL.labels(kind=kind).inc()

except ImportError:  # pragma: no cover

    def _record_metric(kind: str) -> None:
        log.debug("prometheus unavailable; kind=%s metric dropped", kind)


def emit_change(
    event: ChangeEvent,
    *,
    impingement_path: Path | None = None,
    notify_fn=None,
    metric_fn=None,
) -> None:
    """Send the change event to all sinks.

    ``impingement_path`` / ``notify_fn`` / ``metric_fn`` are
    test-injection hooks. Production callers leave them None and the
    function dispatches to the production sinks.
    """
    path = impingement_path or _IMPINGEMENT_PATH
    _write_impingement(event, path)
    if event.ntfy_eligible:
        _notify(event, notify_fn=notify_fn)
    (metric_fn or _record_metric)(event.kind)


def _write_impingement(event: ChangeEvent, path: Path) -> None:
    record = {
        "ts": time.time(),
        "source": "content_id_watcher",
        "intent_family": event.intent_family,
        "salience": event.salience,
        "narrative": event.narrative(),
        "broadcast_id": event.broadcast_id,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "kind": event.kind,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except OSError as exc:
        log.warning("impingement write failed for %s: %s", event.kind, exc)


def _notify(event: ChangeEvent, *, notify_fn=None) -> None:
    if notify_fn is None:
        try:
            from shared.notify import send_notification  # noqa: PLC0415
        except ImportError:
            log.debug("shared.notify unavailable; skipping ntfy for %s", event.kind)
            return
        notify_fn = send_notification
    title = f"YouTube: {event.kind}"
    body = event.narrative()
    try:
        notify_fn(title, body, priority="high", tags=["warning"])
    except Exception as exc:
        log.warning("ntfy notify failed for %s: %s", event.kind, exc)
