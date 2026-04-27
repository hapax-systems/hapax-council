"""Emit a composed narrative through the impingement bus + chronicle + metric.

Three sinks, all best-effort:
    * **Impingement** to ``/dev/shm/hapax-dmn/impingements.jsonl`` with
      ``source="autonomous_narrative"``. ``CpalRunner.process_impingement``
      picks it up via the existing daimonion CPAL consumer cursor and
      routes through ``ConversationPipeline.generate_spontaneous_speech()``
      → existing TTS path.
    * **Chronicle event** to the same JSONL with
      ``source="self_authored_narrative"``. Filtered out of future
      composition reads to prevent the feedback-loop novelty
      degradation.
    * **Prometheus counter** ``hapax_narrative_emissions_total{result}``
      with one of: ``allow`` (emitted), ``rate_limit``,
      ``operator_present``, ``programme_quiet``, ``stimmung_quiet``,
      ``cadence``, ``llm_silent``.

Sink failures don't propagate: the loop keeps running.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from shared.chronicle import ChronicleEvent, current_otel_ids
from shared.chronicle import record as chronicle_record

log = logging.getLogger(__name__)


_IMPINGEMENT_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")

try:
    from prometheus_client import Counter

    _EMISSIONS_TOTAL = Counter(
        "hapax_narrative_emissions_total",
        "Autonomous narrative tick outcomes by result label.",
        ("result",),
    )

    def record_metric(result: str) -> None:
        _EMISSIONS_TOTAL.labels(result=result).inc()

except ImportError:  # pragma: no cover

    def record_metric(result: str) -> None:
        log.debug("prometheus unavailable; result=%s", result)


def emit_narrative(
    text: str,
    *,
    programme_id: str | None = None,
    operator_referent: str | None = None,
    impingement_path: Path | None = None,
    now: float | None = None,
) -> bool:
    """Append the impingement + chronicle event for one narration.

    Returns True on success (both writes landed). False on any I/O
    failure — the loop will increment ``llm_silent`` (or appropriate
    failure label) at the call site rather than counting a failed
    write as an emission.
    """
    path = impingement_path or _IMPINGEMENT_PATH
    ts = now if now is not None else time.time()
    impingement_id = uuid.uuid4().hex[:12]

    impingement = {
        "id": impingement_id,
        "ts": ts,
        "timestamp": ts,
        "source": "autonomous_narrative",
        "type": "absolute_threshold",
        "strength": 0.6,
        "content": {
            "narrative": text,
            "programme_id": programme_id,
            "operator_referent": operator_referent,
        },
        "intent_family": "narrative.autonomous_speech",
    }
    chronicle_event = {
        "ts": ts,
        "source": "self_authored_narrative",
        "event_type": "narrative.emitted",
        "salience": 0.6,
        "payload": {
            "narrative": text,
            "programme_id": programme_id,
            "impingement_id": impingement_id,
        },
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(impingement, default=str) + "\n")
            fh.write(json.dumps(chronicle_event, default=str) + "\n")

        trace_id, span_id = current_otel_ids()
        ev = ChronicleEvent(
            ts=ts,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            source="self_authored_narrative",
            event_type="narrative.emitted",
            payload={
                "narrative": text,
                "programme_id": programme_id,
                "impingement_id": impingement_id,
                "salience": 0.6,
            },
        )
        chronicle_record(ev)
    except OSError as exc:
        log.warning("autonomous_narrative emit write failed: %s", exc)
        return False
    return True
