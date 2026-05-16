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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.chronicle import ChronicleEvent, current_otel_ids
from shared.chronicle import record as chronicle_record

log = logging.getLogger(__name__)


_IMPINGEMENT_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")


@dataclass(frozen=True)
class EmitResult:
    """Outcome for the three autonomous-narration emission sinks."""

    impingement_written: bool
    jsonl_chronicle_written: bool
    chronicle_recorded: bool
    impingement_id: str | None = None

    @property
    def success(self) -> bool:
        """Narration succeeds when the impingement bus write lands."""
        return self.impingement_written

    @property
    def partial_success(self) -> bool:
        return self.impingement_written and not (
            self.jsonl_chronicle_written and self.chronicle_recorded
        )

    def __bool__(self) -> bool:
        return self.success


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
    impulse_id: str | None = None,
    speech_event_id: str | None = None,
    triad_ids: tuple[str, ...] = (),
    impingement_path: Path | None = None,
    now: float | None = None,
) -> EmitResult:
    """Append the impingement + chronicle event for one narration.

    Returns an :class:`EmitResult`. Narration success is keyed to the
    impingement write because that is the speech path; chronicle sinks
    are diagnostic and can fail partially without suppressing speech.
    """
    path = impingement_path or _IMPINGEMENT_PATH
    ts = now if now is not None else time.time()
    impingement_id = speech_event_id or uuid.uuid4().hex[:12]

    content: dict[str, Any] = {
        "narrative": text,
        "programme_id": programme_id,
        "operator_referent": operator_referent,
        "impulse_id": impulse_id,
        "speech_event_id": impingement_id,
        "triad_ids": list(triad_ids),
    }
    if programme_id:
        content["public_broadcast_intent"] = True
        content["channel"] = "broadcast"
        content["bridge_outcome"] = "public_action_proposal"
        content["route_posture"] = "broadcast_authorized"
        content["claim_ceiling"] = "evidence_bound"
        content["programme_authorization"] = {
            "authorized": True,
            "authorized_at": ts,
            "evidence_ref": f"programme:{programme_id}",
        }
        content["programme_authorization_ref"] = f"programme:{programme_id}"

    impingement = {
        "id": impingement_id,
        "ts": ts,
        "timestamp": ts,
        "source": "autonomous_narrative",
        "type": "absolute_threshold",
        "strength": 0.6,
        "content": content,
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
            "impulse_id": impulse_id,
            "impingement_id": impingement_id,
            "speech_event_id": impingement_id,
            "triad_ids": list(triad_ids),
        },
    }

    impingement_written = False
    jsonl_chronicle_written = False
    chronicle_recorded = False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(impingement, default=str) + "\n")
            impingement_written = True
            fh.write(json.dumps(chronicle_event, default=str) + "\n")
            jsonl_chronicle_written = True
    except Exception as exc:
        log.warning("autonomous_narrative impingement/jsonl write failed: %s", exc)

    try:
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
                "impulse_id": impulse_id,
                "impingement_id": impingement_id,
                "speech_event_id": impingement_id,
                "triad_ids": list(triad_ids),
                "salience": 0.6,
            },
        )
        chronicle_record(ev)
        chronicle_recorded = True
    except Exception as exc:
        log.warning("autonomous_narrative chronicle record failed: %s", exc)

    return EmitResult(
        impingement_written=impingement_written,
        jsonl_chronicle_written=jsonl_chronicle_written,
        chronicle_recorded=chronicle_recorded,
        impingement_id=impingement_id,
    )
