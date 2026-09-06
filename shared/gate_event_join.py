"""Admission-to-outcome join helper for the SDLC routing measurement loop.

The admission producer writes observational gate events at dispatch time. A later
witnessed verdict does not know the selected route, so it recovers that context by
joining on the stable task hash and then emits a witnessed outcome event to the same
``gate-events.jsonl`` plane. This module is deliberately pure/additive: it never writes
to ``dispatch-events.jsonl`` and has no live caller until the next wiring slice.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.gate_event_producer import REQUIREMENT_VECTOR_DIMENSIONS
from shared.gate_log import DEFAULT_GATE_LOG, GateEvent, GateResult, GateType, append_gate_event
from shared.gate_outcome_producer import build_outcome_gate_event
from shared.route_metadata_schema import DemandVector, stable_payload_hash


@dataclass(frozen=True)
class AdmissionContext:
    route: str
    routing_class: str
    requirement_vector: dict[str, int]
    admitted_at: str


def recover_admission_context(
    task_hash: str, *, path: Path | str | None = None
) -> AdmissionContext | None:
    """Return the latest non-witnessed admission context for ``task_hash``.

    Admission is ``provenance != "witnessed"``. The scan tolerates malformed JSON
    lines and rows that are not full ``GateEvent`` instances, because legacy live
    admission rows may carry null provenance while still containing the route facts
    required for the join.
    """
    if not task_hash.strip():
        return None
    latest: AdmissionContext | None = None
    for payload in _iter_gate_payloads(path=path):
        if payload.get("task_hash") != task_hash:
            continue
        if payload.get("provenance") == "witnessed":
            continue
        context = _admission_context_from_payload(payload)
        if context is not None:
            latest = context
    return latest


def emit_witnessed_outcome(
    task_fields: Mapping[str, Any],
    *,
    gate_result: GateResult,
    gate_type: GateType,
    demand_vector: DemandVector | None = None,
    p_correct: float | None = None,
    path: Path | str | None = None,
) -> GateEvent | None:
    """Emit a witnessed outcome event joined to the latest admission event.

    Returns ``None`` and writes nothing when no admission context exists. When a
    context is found, the resulting event mirrors the admission route, routing
    class, and requirement vector, then appends to ``gate-events.jsonl`` via the
    shared gate log writer.
    """
    task_hash = _join_task_hash(task_fields, demand_vector)
    context = recover_admission_context(task_hash, path=path)
    if context is None:
        return None

    event = build_outcome_gate_event(
        task_fields,
        route=context.route,
        gate_result=gate_result,
        gate_type=gate_type,
        demand_vector=demand_vector,
        p_correct=p_correct,
    ).model_copy(
        update={
            "task_hash": task_hash,
            "routing_class": context.routing_class,
            "requirement_vector": dict(context.requirement_vector),
        }
    )
    append_gate_event(event, path=path)
    return event


def _join_task_hash(task_fields: Mapping[str, Any], demand_vector: DemandVector | None) -> str:
    return (
        demand_vector.work_item.frontmatter_hash
        if demand_vector is not None
        else stable_payload_hash(dict(task_fields))
    )


def _iter_gate_payloads(*, path: Path | str | None = None) -> Iterator[Mapping[str, Any]]:
    target = Path(path) if path is not None else DEFAULT_GATE_LOG
    if not target.exists():
        return
    with target.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping):
                yield payload


def _admission_context_from_payload(payload: Mapping[str, Any]) -> AdmissionContext | None:
    route = payload.get("route")
    routing_class = payload.get("routing_class")
    admitted_at = payload.get("ts")
    requirement_vector = _requirement_vector_from_payload(payload.get("requirement_vector"))
    if (
        not isinstance(route, str)
        or not route.strip()
        or not isinstance(routing_class, str)
        or not routing_class.strip()
        or not isinstance(admitted_at, str)
        or requirement_vector is None
    ):
        return None
    return AdmissionContext(
        route=route,
        routing_class=routing_class,
        requirement_vector=requirement_vector,
        admitted_at=admitted_at,
    )


def _requirement_vector_from_payload(value: object) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    if set(value) != set(REQUIREMENT_VECTOR_DIMENSIONS):
        return None
    vector: dict[str, int] = {}
    for dimension in REQUIREMENT_VECTOR_DIMENSIONS:
        score = value[dimension]
        if isinstance(score, bool) or not isinstance(score, int):
            return None
        if not (0 <= score <= 5):
            return None
        vector[dimension] = score
    return vector
