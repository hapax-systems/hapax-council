"""Gate-event OUTCOME producer — a learning GateEvent from a WITNESSED verdict.

The admission producer (``shared/gate_event_producer.py``, #4330) writes observational events
(``gate_type="none"``, empty learning eligibility) that never move a posterior. This module is
its witnessed-outcome counterpart: given a real cc-task-gate / CI / typecheck / review
accept|reject verdict, it assembles a ``GateEvent`` with a LEARNING ``gate_type`` +
``thompson_update_allowed=True`` + ``provenance="witnessed"``, joining admission↔outcome by
``task_hash``. One such event, fed to ``SdlcRouter.record_gate_event`` (directly or via
``gate-events.jsonl`` → ``ingest_gate_events``), moves the Thompson posterior — closing the SDLC
learning loop the spine left open.

It REUSES the #4330 builders (``build_requirement_vector`` with its derivation,
``resolve_routing_class``) so the admission and outcome planes derive an identical 5-tuple and
join cleanly. ``provenance`` defaults to ``"witnessed"``; synthetic callers (tests, replays)
pass a non-witnessed value so ``record_gate_event`` refuses to move the Beta (fixtures must not
poison it).

Design: agentic-native dispatch CCEF/H STEP 7; the token-economics measurement-loop redirect.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shared.gate_event_producer import build_requirement_vector, resolve_routing_class
from shared.gate_log import GateEvent, GateResult, GateType, Provenance, append_gate_event
from shared.route_metadata_schema import (
    DemandVector,
    FreshnessState,
    LearningEligibility,
    LearningEvidenceKind,
    stable_payload_hash,
)

#: gate_types that represent a correctness VERDICT (i.e. may move a posterior). Excludes "none"
#: (the admission gate). Mirrors LEARNING_GATE_TYPES in shared.sdlc_router; kept local to avoid
#: a router import cycle (the router imports the gate-log schema, not this producer).
_LEARNING_GATE_TYPES = ("deterministic", "gold_verifier", "llm_acceptor", "frontier_review")
#: verifiers whose verdict is certain by construction, so confidence defaults to 1.0.
_CERTAIN_GATE_TYPES = ("deterministic", "gold_verifier")


def build_outcome_gate_event(
    task_fields: Mapping[str, Any],
    *,
    route: str,
    gate_result: GateResult,
    gate_type: GateType = "deterministic",
    demand_vector: DemandVector | None = None,
    p_correct: float | None = None,
    provenance: Provenance = "witnessed",
) -> GateEvent:
    """Assemble one LEARNING ``GateEvent`` from a witnessed accept/reject verdict.

    ``gate_type`` must be a correctness verdict (not ``"none"``) — an outcome event with
    ``"none"`` would silently never learn. ``confidence`` defaults to 1.0 for the certain
    verifiers (deterministic/gold) and 0.0 otherwise; pass ``p_correct`` for judge/review gates.
    """
    if gate_type not in _LEARNING_GATE_TYPES:
        raise ValueError(
            f"outcome gate_type must be a learning verdict {_LEARNING_GATE_TYPES}, got {gate_type!r}"
        )
    task_hash = (
        demand_vector.work_item.frontmatter_hash
        if demand_vector is not None
        else stable_payload_hash(dict(task_fields))
    )
    default_confidence = 1.0 if gate_type in _CERTAIN_GATE_TYPES else 0.0
    return GateEvent(
        route=route,
        routing_class=resolve_routing_class(task_fields, demand_vector),
        requirement_vector=build_requirement_vector(task_fields, demand_vector),
        model_resolved="",  # the concrete model joins on task_hash via the admission plane
        task_hash=task_hash,
        gate_result=gate_result,
        gate_type=gate_type,
        p_correct=p_correct,
        provenance=provenance,
        learning_eligibility=LearningEligibility(
            thompson_update_allowed=True,
            local_posterior_update_allowed=True,
            evidence_kind=LearningEvidenceKind.WITNESSED,
            evidence_freshness=FreshnessState.FRESH,
            confidence=p_correct if p_correct is not None else default_confidence,
            envelope_valid=True,
            support_only=False,
            hkp_only=False,
            public_projection_forbidden=False,
            evidence_refs=[f"{gate_type}:{task_hash}"],
            reason_codes=["witnessed_outcome_gate"],
        ),
    )


def emit_outcome_gate_event(
    task_fields: Mapping[str, Any],
    *,
    route: str,
    gate_result: GateResult,
    gate_type: GateType = "deterministic",
    demand_vector: DemandVector | None = None,
    p_correct: float | None = None,
    provenance: Provenance = "witnessed",
    path: Path | str | None = None,
) -> GateEvent:
    """Build + append a learning outcome event to the gate log — the loop's WRITE side.

    The router's ``ingest_gate_events`` drains that log and moves the posterior; this is the
    function a witnessed cc-task-gate / CI / review verdict calls to feed it.
    """
    event = build_outcome_gate_event(
        task_fields,
        route=route,
        gate_result=gate_result,
        gate_type=gate_type,
        demand_vector=demand_vector,
        p_correct=p_correct,
        provenance=provenance,
    )
    append_gate_event(event, path=path)
    return event
