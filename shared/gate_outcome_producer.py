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
pass a non-witnessed value, and the emitted ``learning_eligibility`` is made CONSISTENT with it
(non-witnessed → a non-learning eligibility), so a receipt never contradicts its provenance and
``record_gate_event`` refuses to move the Beta (fixtures must not poison it).

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
#: gate_results that ARE a verdict the posterior learns from. A non-verdict result (abstain /
#: escalate / error) would be silently dropped by record_gate_event — a lost-learning write — so
#: the producer fails closed on it rather than emitting a misleading "witnessed" receipt.
_LEARNING_GATE_RESULTS = ("accept", "reject")
#: verifiers whose verdict is certain by construction, so confidence defaults to 1.0.
_CERTAIN_GATE_TYPES = ("deterministic", "gold_verifier")


def _outcome_eligibility(
    *, provenance: Provenance, gate_type: GateType, task_hash: str, p_correct: float | None
) -> LearningEligibility:
    """LearningEligibility CONSISTENT with provenance.

    A witnessed verdict carries full learning eligibility (thompson-enabled, witnessed/fresh,
    authoritative). A non-witnessed event carries a NON-learning eligibility so the serialized
    receipt never contradicts its ``provenance`` field — record_gate_event then drops it on both
    the eligibility flag and the provenance guard (defense in depth).
    """
    if provenance != "witnessed":
        return LearningEligibility(
            thompson_update_allowed=False,
            local_posterior_update_allowed=False,
            reason_codes=[f"non_witnessed_provenance:{provenance}"],
        )
    default_confidence = 1.0 if gate_type in _CERTAIN_GATE_TYPES else 0.0
    return LearningEligibility(
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
    )


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

    Fails closed on a non-learning ``gate_type`` (``"none"``) or a non-verdict ``gate_result``
    (abstain/escalate/error) — either would be silently dropped downstream, turning a producer
    contract error into a lost-learning write. ``confidence`` defaults to 1.0 for the certain
    verifiers (deterministic/gold) and 0.0 otherwise; pass ``p_correct`` for judge/review gates.
    The emitted ``learning_eligibility`` is kept consistent with ``provenance``.
    """
    if gate_type not in _LEARNING_GATE_TYPES:
        raise ValueError(
            f"outcome gate_type must be a learning verdict {_LEARNING_GATE_TYPES}, got {gate_type!r}"
        )
    if gate_result not in _LEARNING_GATE_RESULTS:
        raise ValueError(
            f"outcome gate_result must be a verdict {_LEARNING_GATE_RESULTS}, got {gate_result!r} "
            "— a non-verdict result is silently dropped by record_gate_event (lost-learning write)"
        )
    task_hash = (
        demand_vector.work_item.frontmatter_hash
        if demand_vector is not None
        else stable_payload_hash(dict(task_fields))
    )
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
        learning_eligibility=_outcome_eligibility(
            provenance=provenance, gate_type=gate_type, task_hash=task_hash, p_correct=p_correct
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
