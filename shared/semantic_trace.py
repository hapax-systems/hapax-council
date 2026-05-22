"""Semantic trace emission helpers for the socio-linguistic tracing layer.

Thin wrappers around chronicle.record() that build correctly-shaped
ChronicleEvents with evidence_class="semantic_interpretation" and
the appropriate event_type and payload structure.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from shared.chronicle import CHRONICLE_FILE, ChronicleEvent, record


def emit_interpretation(
    *,
    source: str,
    input_summary: str,
    interpreted_as: str,
    confidence: float,
    alternatives_considered: list[str],
    routing_reason: str,
    context_sources: list[str],
    trace_id: str = "0" * 32,
    span_id: str = "0" * 16,
    parent_span_id: str | None = None,
    extra_payload: dict[str, Any] | None = None,
    chronicle_path: Path = CHRONICLE_FILE,
) -> str:
    payload: dict[str, Any] = {
        "interpretation": {
            "input_summary": input_summary[:200],
            "interpreted_as": interpreted_as,
            "confidence": confidence,
            "alternatives_considered": alternatives_considered,
            "routing_reason": routing_reason,
            "context_sources": context_sources,
        }
    }
    if extra_payload:
        payload.update(extra_payload)
    event = ChronicleEvent(
        ts=time.time(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        source=source,
        event_type="semantics.interpretation_decided",
        payload=payload,
        evidence_class="semantic_interpretation",
    )
    record(event, path=chronicle_path)
    return event.event_id


def emit_transformation(
    *,
    source: str,
    source_node: str,
    source_fields_read: list[str],
    prior_state: dict[str, Any],
    posterior_state: dict[str, Any],
    delta_reason: str,
    trace_id: str = "0" * 32,
    span_id: str = "0" * 16,
    parent_span_id: str | None = None,
    chronicle_path: Path = CHRONICLE_FILE,
) -> str:
    event = ChronicleEvent(
        ts=time.time(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        source=source,
        event_type="semantics.transformation_logged",
        payload={
            "transformation": {
                "source_node": source_node,
                "source_fields_read": source_fields_read,
                "prior_state": prior_state,
                "posterior_state": posterior_state,
                "delta_reason": delta_reason,
            }
        },
        evidence_class="semantic_interpretation",
    )
    record(event, path=chronicle_path)
    return event.event_id


def emit_grounding(
    *,
    source: str,
    checks_evaluated: list[str],
    converged: bool,
    confidence_bound: float,
    participants: list[str],
    trace_id: str = "0" * 32,
    span_id: str = "0" * 16,
    parent_span_id: str | None = None,
    chronicle_path: Path = CHRONICLE_FILE,
) -> str:
    event_type = "semantics.grounding_converged" if converged else "semantics.grounding_diverged"
    event = ChronicleEvent(
        ts=time.time(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        source=source,
        event_type=event_type,
        payload={
            "grounding": {
                "checks_evaluated": checks_evaluated,
                "converged": converged,
                "confidence_bound": confidence_bound,
                "participants": participants,
            }
        },
        evidence_class="semantic_interpretation",
    )
    record(event, path=chronicle_path)
    return event.event_id


def emit_relay_uptake(
    *,
    source: str,
    message_id: str,
    interpretation_summary: str,
    interpretation_confidence: float,
    trace_id: str = "0" * 32,
    span_id: str = "0" * 16,
    chronicle_path: Path = CHRONICLE_FILE,
) -> str:
    event = ChronicleEvent(
        ts=time.time(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=None,
        source=source,
        event_type="semantics.relay_uptake",
        payload={
            "relay_uptake": {
                "message_id": message_id,
                "interpretation_summary": interpretation_summary,
                "interpretation_confidence": interpretation_confidence,
            }
        },
        evidence_class="semantic_interpretation",
        evidence_refs=(message_id,),
    )
    record(event, path=chronicle_path)
    return event.event_id
