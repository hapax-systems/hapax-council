"""Tests for the agentic-native SDLC prioritization contract."""

from __future__ import annotations

from shared.dispatch_frontier import FRONTIER_AXES
from shared.sdlc_agentic_priority import (
    AGENTIC_DECOMPOSITION_CRITERIA,
    CALCULUS_CUTOVER_SEQUENCE,
    FRONTIER_AXIS_ROLES,
    FRONTIER_SELECTION_OUTCOMES,
    FROZEN_ROUTING_CLASSES,
    OPERATOR_VALUE_TIER_BOUNDARY,
    REQUIREMENT_VECTOR_CONTRACT_DIMENSIONS,
    SCALAR_PRIORITY_SURFACES,
    TASK_CAPABILITY_CELL_CONTRACT,
)


def _cell_contract_by_key() -> dict[str, object]:
    return {field.key: field for field in TASK_CAPABILITY_CELL_CONTRACT}


def _scalar_surfaces_by_phase() -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for surface in SCALAR_PRIORITY_SURFACES:
        grouped.setdefault(surface.phase, []).append(surface.path)
    return {phase: tuple(paths) for phase, paths in grouped.items()}


def _cutover_files() -> tuple[str, ...]:
    seen: set[str] = set()
    files: list[str] = []
    for step in CALCULUS_CUTOVER_SEQUENCE:
        for path in step.files:
            if path not in seen:
                seen.add(path)
                files.append(path)
    return tuple(files)


def test_agentic_decomposition_criteria_cover_machine_native_reasons() -> None:
    keys = {criterion.key for criterion in AGENTIC_DECOMPOSITION_CRITERIA}

    assert keys == {
        "capability_fit",
        "context_state_locality",
        "dependency_mitigation",
        "parallelizability",
        "verifiability",
        "information_gain",
        "cost_optimal_granularity",
        "blast_radius_isolation",
        "reversibility",
    }
    assert all(criterion.rejects for criterion in AGENTIC_DECOMPOSITION_CRITERIA)
    assert not any(
        "human sized" in criterion.decision_rule.lower()
        for criterion in AGENTIC_DECOMPOSITION_CRITERIA
    )


def test_task_capability_cell_contract_contains_frontier_axes_and_honest_status() -> None:
    fields = _cell_contract_by_key()

    for axis, direction in FRONTIER_AXES.items():
        assert fields[axis].role == direction
        assert fields[axis].required_for_frontier is True

    assert FRONTIER_AXIS_ROLES == FRONTIER_AXES
    assert set(FRONTIER_AXIS_ROLES) == {"v_hat", "fit", "u", "c_hat", "mu"}
    assert "measured, projected, absent" in fields["value_status"].invariant
    assert "never imputed as zero" in fields["c_hat"].invariant
    assert "machine-checkable acceptance predicate" in fields["acceptance_predicate_ref"].invariant


def test_cell_contract_pins_frozen_routing_classes_and_requirement_dimensions() -> None:
    fields = _cell_contract_by_key()

    assert len(FROZEN_ROUTING_CLASSES) == 11
    assert "unknown" not in FROZEN_ROUTING_CLASSES
    assert "frozen 11-class" in fields["routing_class"].invariant
    assert REQUIREMENT_VECTOR_CONTRACT_DIMENSIONS == (
        "quality_floor",
        "information_scope",
        "context_length",
        "mutation_risk",
        "verification_demand",
        "ambiguity_novelty",
        "composition_coupling",
        "governance_sensitivity",
    )
    assert fields["requirement_vector"].role == "demand"


def test_scalar_surface_inventory_covers_current_wsjf_decision_and_display_surfaces() -> None:
    paths = {surface.path for surface in SCALAR_PRIORITY_SURFACES}

    assert {
        "agents/coordinator/core.py",
        "shared/dispatch_service_time.py",
        "shared/intake_fit_scorer.py",
        "shared/orchestration_ledger.py",
        "scripts/request-intake-consumer",
        "agents/coordination_tui/data.py",
        "agents/coordination_tui/app.py",
        "scripts/braided_value_snapshot_runner.py",
        "scripts/request-decompose",
        "agents/request_decomposer/writer.py",
        "scripts/security-signal-intake",
    } <= paths
    assert any("wsjf" in surface.current_scalar.lower() for surface in SCALAR_PRIORITY_SURFACES)
    assert all(
        "sort by wsjf" not in surface.replacement.lower() for surface in SCALAR_PRIORITY_SURFACES
    )

    by_phase = _scalar_surfaces_by_phase()
    assert {"demand_backfill", "frontier_shadow", "scheduler_cutover", "surface_cutover"} <= set(
        by_phase
    )


def test_cutover_sequence_connects_producers_router_scheduler_and_surfaces() -> None:
    step_keys = [step.key for step in CALCULUS_CUTOVER_SEQUENCE]

    assert step_keys == [
        "backfill_task_demand",
        "produce_cell_evidence",
        "shadow_frontier_selection",
        "cut_over_scheduler",
        "cut_over_read_surfaces",
        "enforce_no_scalar_recollapse",
    ]
    assert FRONTIER_SELECTION_OUTCOMES == ("FRONTIER", "HOLD", "INCOMPARABLE")
    assert "shared/gate_outcome_producer.py" in _cutover_files()
    assert "shared/sdlc_router.py" in _cutover_files()
    assert "shared/dispatch_service_time.py" in _cutover_files()
    assert "agents/coordinator/core.py" in _cutover_files()
    assert "tests/shared/test_sdlc_agentic_priority.py" in _cutover_files()
    assert any("route posteriors" in step.exit_predicate for step in CALCULUS_CUTOVER_SEQUENCE)


def test_operator_value_tier_boundary_is_a_filter_not_a_weight() -> None:
    boundary = OPERATOR_VALUE_TIER_BOUNDARY

    assert boundary.parameter == "routing_class -> served_tier"
    assert boundary.allowed_role.lower().startswith("filter")
    assert "multiplicative_weight" in boundary.forbidden_roles
    assert "priority_scalar" in boundary.forbidden_roles
    assert "owner_attention_proxy" in boundary.forbidden_roles
    assert "weight" not in boundary.allowed_role.split(";")[0].lower()


def test_cell_contract_has_unique_keys() -> None:
    keys = [field.key for field in TASK_CAPABILITY_CELL_CONTRACT]

    assert len(keys) == len(set(keys))
