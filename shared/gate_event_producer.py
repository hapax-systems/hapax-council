"""Gate-event PRODUCER — assemble a ``GateEvent`` at the dispatch admission gate.

KEYSTONE (cc-task-gate-event-producer-20260626). ``shared.gate_log.append_gate_event``
had ZERO live callers; this module assembles the event the dispatch site emits, so every
accept/reject writes one ``GateEvent`` to ``~/.cache/hapax/sdlc-routing/gate-events.jsonl``
— the observational evidence stream behind EDT D2/D3/D4/D5 slice measurement.

DELIBERATE (corrects the task md, which asked for ``thompson_update_allowed=True``):
this is the ADMISSION gate, not a correctness verifier, so

  * ``gate_type = "none"``
  * ``learning_eligibility.thompson_update_allowed = False``

``=True`` is both impossible here (the ``LearningEligibility`` validator raises without
witnessed/fresh evidence — ``route_metadata_schema.py``) and wrong (it would reward every
admitted route regardless of outcome). Thompson posteriors are fed by a SEPARATE
outcome-gate producer (follow-up) keyed on the same ``task_hash``.

``requirement_vector``: PREFER the decomposer's explicit, validated vector (the router's
own Thompson key — keeps the gate-event slice identical to live routing); DERIVE from
``TaskDemand`` via the rubric below only when no valid explicit vector is present. Because
``gate_type="none"``, the derived vector affects ONLY EDT slice placement — never Thompson
posteriors and never live route selection (which uses the router's own request). The rubric
+ the open operator decisions are documented in
``30-areas/hapax/gate-event-producer-rubric-2026-06-27.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.gate_log import GateEvent
from shared.route_metadata_schema import (
    ContextBreadth,
    DemandVector,
    LearningEligibility,
    MutationSurface,
    QualityFloor,
    SourceGroundingNeed,
    TaskDemand,
    stable_payload_hash,
)
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS

# --- the live routing-class taxonomy (frozen-11 today; v2 expansion is unlanded) ---------
# The producer is N-agnostic: GateEvent.routing_class is a bare string. To keep the EDT
# denominator honest, the deterministic fallback only emits the 11 live classes by default;
# a hand-authored out-of-set label falls through to the fallback (avoids numerator>denominator).
_ACTIVE_ROUTING_CLASSES = (
    "coordination",
    "research_support",
    "docs_planning",
    "source_python",
    "source_other",
    "source_governance",
    "runtime_ops",
    "public_surface",
    "provider_spend",
    "operator_action",
    "verification",
)
_ACTIVE_ROUTING_CLASS_SET = frozenset(_ACTIVE_ROUTING_CLASSES)

# --- requirement_vector derivation ladders (the delegated rubric) ------------------------
_QF_LADDER = {
    QualityFloor.DETERMINISTIC_OK.value: 1,
    QualityFloor.FRONTIER_REVIEW_REQUIRED.value: 3,
    QualityFloor.FRONTIER_REQUIRED.value: 5,
}
_SGN_LADDER = {
    SourceGroundingNeed.NONE: 0,
    SourceGroundingNeed.LOCAL_DOCS: 1,
    SourceGroundingNeed.OFFICIAL_DOCS_CURRENT: 3,
    SourceGroundingNeed.WEB_CURRENT: 4,
    SourceGroundingNeed.LITERATURE: 4,
    SourceGroundingNeed.MULTIMODAL: 5,
}
_CB_INFO_LADDER = {
    ContextBreadth.NONE: 0,
    ContextBreadth.LOCAL_NOTE: 0,
    ContextBreadth.LOCAL_REPO: 0,
    ContextBreadth.CROSS_REPO: 1,
    ContextBreadth.VAULT_PLUS_REPO: 1,
    ContextBreadth.EXTERNAL_CURRENT: 4,
}
_MUT_LADDER = {
    MutationSurface.NONE: 0,
    MutationSurface.VAULT_DOCS: 1,
    MutationSurface.SOURCE: 3,
    MutationSurface.RUNTIME: 4,
    MutationSurface.PUBLIC: 4,
    MutationSurface.PROVIDER_SPEND: 5,
}
_MUTATING_SURFACES = {
    MutationSurface.SOURCE,
    MutationSurface.RUNTIME,
    MutationSurface.PUBLIC,
    MutationSurface.PROVIDER_SPEND,
}


def _clamp(value: int) -> int:
    return max(0, min(5, int(value)))


def _token_bucket(tokens: int) -> int:
    if tokens <= 0:
        return 0
    if tokens <= 4_000:
        return 1
    if tokens <= 8_000:
        return 2
    if tokens <= 24_000:
        return 3
    if tokens <= 80_000:
        return 4
    return 5


def _derive_requirement_vector(
    td: TaskDemand, *, mutation_surface: MutationSurface, quality_floor: QualityFloor
) -> dict[str, int]:
    """Derive the 8-dim requirement_vector (strict ints 0..5) from a ``TaskDemand``.

    Each dim is a DEMAND FLOOR over named supply capabilities (sdlc_router MIN-over-supply):
    the rubric MAXes the contributing demand signals so the demand floors the weakest mapped
    capability. See the module docstring + the vault rubric artifact for per-dim rationale.
    """
    vd = td.verification_demand

    verification = 0
    if vd.deterministic_tests or vd.static_checks or vd.runtime_observation:
        verification = max(verification, 3)
    if vd.screenshot_or_media_required:
        verification = max(verification, 4)
    if vd.operator_only:
        verification = max(verification, 5)
    if verification > 0:
        verification = max(verification, min(td.failure_cost, 5))
    elif td.failure_cost >= 4:
        verification = 2

    implementation_term = (
        td.implementation_complexity if mutation_surface in _MUTATING_SURFACES else 0
    )

    return {
        # recorded scalar, never a capability floor (router excludes it from scoring/veto)
        "quality_floor": _QF_LADDER.get(quality_floor.value, 5),
        "information_scope": _clamp(
            max(
                td.grounding_criticality,
                _SGN_LADDER.get(td.source_grounding_need, 0),
                _CB_INFO_LADDER.get(td.context_breadth, 0),
            )
        ),
        "context_length": _clamp(
            max(
                _token_bucket(td.estimated_context_tokens),
                5 if td.context_mode_demand == "extended_1m" else 0,
            )
        ),
        "mutation_risk": _clamp(max(_MUT_LADDER.get(mutation_surface, 0), implementation_term)),
        "verification_demand": _clamp(verification),
        "ambiguity_novelty": _clamp(max(td.requirement_ambiguity, td.architectural_novelty)),
        "composition_coupling": _clamp(max(td.coordination_load, td.branch_worktree_conflict_risk)),
        "governance_sensitivity": _clamp(
            max(
                td.governance_claim_risk,
                td.security_privacy_sensitivity,
                td.release_publication_impact,
            )
        ),
    }


def _explicit_requirement_vector(task_fields: Mapping[str, Any]) -> dict[str, int] | None:
    """The decomposer's explicit requirement_vector iff complete + strict-int 0..5."""
    raw = task_fields.get("requirement_vector")
    if not isinstance(raw, Mapping):
        return None
    if set(raw) != set(REQUIREMENT_VECTOR_DIMENSIONS):
        return None
    out: dict[str, int] = {}
    for dim in REQUIREMENT_VECTOR_DIMENSIONS:
        score = raw[dim]
        if isinstance(score, bool) or not isinstance(score, int) or not (0 <= score <= 5):
            return None
        out[dim] = score
    return out


def build_requirement_vector(
    task_fields: Mapping[str, Any], demand_vector: DemandVector | None
) -> dict[str, int]:
    """Prefer the decomposer's explicit vector; derive from TaskDemand only when absent."""
    explicit = _explicit_requirement_vector(task_fields)
    if explicit is not None:
        return explicit
    if demand_vector is not None:
        return _derive_requirement_vector(
            demand_vector.task_demand,
            mutation_surface=demand_vector.mutation_surface,
            quality_floor=demand_vector.quality_floor,
        )
    return {}


# --- routing_class classifier (2-stage: prefer explicit, then deterministic fallback) ----
def _str_field(task_fields: Mapping[str, Any], key: str) -> str:
    value = task_fields.get(key)
    return str(value).strip().lower() if value not in (None, "") else ""


def _paths(task_fields: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("target_paths", "mutation_scope_refs"):
        value = task_fields.get(key)
        if isinstance(value, (list, tuple)):
            out.extend(str(p) for p in value)
    return out


def _is_governance_path(paths: list[str]) -> bool:
    for p in paths:
        if p.endswith((".rs", ".wgsl")) or "CODEOWNERS" in p:
            return True
        segments = p.split("/")
        if "axioms" in segments or "governance" in segments:
            return True
    return False


def _classify_routing_class(task_fields: Mapping[str, Any], surface: str) -> str:
    """Deterministic component/surface cross-product over the live 11 classes."""
    kind = _str_field(task_fields, "kind") or _str_field(task_fields, "task_type")
    paths = _paths(task_fields)
    if surface == MutationSurface.SOURCE.value:
        if _is_governance_path(paths):
            return "source_governance"
        if paths and all(p.endswith(".py") for p in paths):
            return "source_python"
        return "source_other"
    if surface == MutationSurface.RUNTIME.value:
        return "runtime_ops"
    if surface == MutationSurface.PUBLIC.value:
        return "public_surface"
    if surface == MutationSurface.PROVIDER_SPEND.value:
        return "provider_spend"
    if surface == MutationSurface.VAULT_DOCS.value:
        return "docs_planning"
    # surface NONE -> activity-keyed
    if kind == "operator_action":
        return "operator_action"
    if kind == "verification":
        return "verification"
    if kind == "research_packet":
        return "research_support"
    if kind in {"watcher", "recovery_triage"}:
        return "coordination"
    return "coordination"


def resolve_routing_class(
    task_fields: Mapping[str, Any], demand_vector: DemandVector | None
) -> str:
    """Honor the decomposer's class iff in the active set; else deterministic fallback."""
    explicit = _str_field(task_fields, "routing_class")
    # Honor an explicit class only if it is in the live (active) taxonomy; an out-of-set
    # (e.g. hand-authored v2) label falls through to the fallback, so the EDT numerator
    # never exceeds the frozen denominator.
    if explicit and explicit != "unknown" and explicit in _ACTIVE_ROUTING_CLASS_SET:
        return explicit
    surface = (
        demand_vector.mutation_surface.value
        if demand_vector is not None
        else _str_field(task_fields, "mutation_surface")
    )
    return _classify_routing_class(task_fields, surface)


def build_gate_event(
    task_fields: Mapping[str, Any],
    *,
    route: str,
    demand_vector: DemandVector | None,
    gate_result: str,
) -> GateEvent:
    """Assemble one observational GateEvent for a dispatch admission decision."""
    task_hash = (
        demand_vector.work_item.frontmatter_hash
        if demand_vector is not None
        else stable_payload_hash(dict(task_fields))
    )
    return GateEvent(
        route=route,
        routing_class=resolve_routing_class(task_fields, demand_vector),
        requirement_vector=build_requirement_vector(task_fields, demand_vector),
        model_resolved="",  # real post-fallback model resolves in the async lane; outcome plane joins on task_hash
        task_hash=task_hash,
        gate_result=gate_result,
        gate_type="none",  # admission gate, not a correctness verifier
        p_correct=None,
        latency_ms=None,
        cost_usd=None,
        learning_eligibility=LearningEligibility(
            reason_codes=["dispatch_admission_gate_not_outcome"]
        ),
    )
