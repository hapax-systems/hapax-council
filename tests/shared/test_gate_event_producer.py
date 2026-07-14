"""Tests for the gate-event producer (keystone: cc-task-gate-event-producer-20260626)."""

from __future__ import annotations

from shared.gate_event_producer import (
    REQUIREMENT_VECTOR_DIMENSIONS,
    _derive_requirement_vector,
    build_gate_event,
    build_requirement_vector,
    resolve_routing_class,
)
from shared.route_metadata_schema import MutationSurface, QualityFloor, TaskDemand


def _td(**overrides: object) -> TaskDemand:
    payload: dict[str, object] = {
        "authority_class": "source_mutation",
        "grounding_criticality": 0,
        "governance_claim_risk": 0,
        "implementation_complexity": 0,
        "architectural_novelty": 0,
        "requirement_ambiguity": 0,
        "estimated_context_tokens": 0,
        "security_privacy_sensitivity": 0,
        "release_publication_impact": 0,
        "coordination_load": 0,
        "branch_worktree_conflict_risk": 0,
        "authority_constraint_dependency": 0,
        "failure_cost": 0,
    }
    payload.update(overrides)
    return TaskDemand.model_validate(payload)


def test_derive_requirement_vector_emits_all_eight_strict_ints() -> None:
    rv = _derive_requirement_vector(
        _td(), mutation_surface=MutationSurface.NONE, quality_floor=QualityFloor.DETERMINISTIC_OK
    )
    assert set(rv) == set(REQUIREMENT_VECTOR_DIMENSIONS)
    for v in rv.values():
        assert isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 5


def test_derive_requirement_vector_ladders() -> None:
    rv = _derive_requirement_vector(
        _td(
            grounding_criticality=2,
            architectural_novelty=4,
            requirement_ambiguity=1,
            coordination_load=3,
            branch_worktree_conflict_risk=5,
            governance_claim_risk=2,
            security_privacy_sensitivity=4,
            estimated_context_tokens=30_000,  # -> bucket 4
            implementation_complexity=5,
        ),
        mutation_surface=MutationSurface.SOURCE,  # MUT_LADDER=3, implementation_term applies
        quality_floor=QualityFloor.FRONTIER_REQUIRED,  # -> 5
    )
    assert rv["quality_floor"] == 5
    assert rv["context_length"] == 4
    # mutation_risk = max(source=3, implementation_complexity=5) = 5 (mutating surface)
    assert rv["mutation_risk"] == 5
    assert rv["ambiguity_novelty"] == 4  # max(req_ambiguity=1, arch_novelty=4)
    assert rv["composition_coupling"] == 5  # max(coord=3, conflict=5)
    assert rv["governance_sensitivity"] == 4  # max(2,4,0)


def test_implementation_complexity_gated_to_mutating_surface() -> None:
    # high complexity on a NON-mutating (planning) surface must NOT inflate mutation_risk
    rv = _derive_requirement_vector(
        _td(implementation_complexity=5),
        mutation_surface=MutationSurface.NONE,
        quality_floor=QualityFloor.DETERMINISTIC_OK,
    )
    assert rv["mutation_risk"] == 0


def test_prefer_explicit_requirement_vector() -> None:
    explicit = {dim: 2 for dim in REQUIREMENT_VECTOR_DIMENSIONS}
    assert build_requirement_vector({"requirement_vector": explicit}, None) == explicit
    # malformed explicit (bool / out of range / missing dim) is rejected -> falls through to {}
    bad = {**explicit, "quality_floor": True}
    assert build_requirement_vector({"requirement_vector": bad}, None) == {}
    assert build_requirement_vector({"requirement_vector": {"quality_floor": 3}}, None) == {}


def test_resolve_routing_class_prefers_active_explicit_then_falls_back() -> None:
    assert resolve_routing_class({"routing_class": "verification"}, None) == "verification"
    # out-of-active-set label falls through to the deterministic fallback
    assert (
        resolve_routing_class(
            {
                "routing_class": "fim_autocomplete",
                "mutation_surface": "source",
                "mutation_scope_refs": ["shared/x.py"],
            },
            None,
        )
        == "source_python"
    )
    # unknown -> fallback by surface
    assert (
        resolve_routing_class({"routing_class": "unknown", "mutation_surface": "vault_docs"}, None)
        == "docs_planning"
    )
    assert (
        resolve_routing_class(
            {"mutation_surface": "source", "mutation_scope_refs": ["axioms/registry.yaml"]}, None
        )
        == "source_governance"
    )


def test_build_gate_event_is_observational_and_valid() -> None:
    ev = build_gate_event(
        {"routing_class": "verification", "mutation_surface": "none"},
        route="claude.headless.full#opus",
        demand_vector=None,
        gate_result="accept",
    )
    assert ev.route == "claude.headless.full#opus"
    assert ev.routing_class == "verification"
    assert ev.gate_result == "accept"
    assert ev.gate_type == "none"  # admission gate, never a verifier
    assert ev.requirement_vector == {}  # no explicit + no demand_vector
    assert ev.task_hash.startswith("sha256:")
    # the corrected choice: observational only, never a Thompson reward
    assert ev.learning_eligibility is not None
    assert ev.learning_eligibility.thompson_update_allowed is False
