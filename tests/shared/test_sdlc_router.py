"""Tests for the standalone SDLC capability router."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.gate_log import GateEvent
from shared.platform_capability_registry import (
    build_supply_vector,
    load_platform_capability_registry,
)
from shared.sdlc_router import (
    DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID,
    ClassActivationEvidence,
    SdlcRouteCandidate,
    SdlcRouter,
    SdlcRouterAction,
    SdlcRoutingRequest,
)


def _requirement_vector(**overrides: int) -> dict[str, int]:
    values = {
        "quality_floor": 4,
        "information_scope": 3,
        "context_length": 3,
        "mutation_risk": 3,
        "verification_demand": 3,
        "ambiguity_novelty": 2,
        "composition_coupling": 2,
        "governance_sensitivity": 2,
    }
    values.update(overrides)
    return values


def _request(**overrides: object) -> SdlcRoutingRequest:
    payload: dict[str, object] = {
        "task_id": "task-router-test",
        "routing_class": "source_python",
        "requirement_vector": _requirement_vector(),
        "quality_floor": "frontier_required",
        "mutation_surface": "source",
        "authority_level": "authoritative",
    }
    payload.update(overrides)
    return SdlcRoutingRequest.model_validate(payload)


def _active_gate(routing_class: str = "source_python") -> ClassActivationEvidence:
    return ClassActivationEvidence(
        routing_class=routing_class,
        information_scope_value_count=1,
        context_length_value_count=1,
        floor_checker_live=True,
        floor_checker_ref="floor-checker:source-python:v1",
        evidence_refs=("eval:source-python:d2-d3",),
    )


def _candidate(route_id: str, *, score: int, **overrides: object) -> SdlcRouteCandidate:
    payload: dict[str, object] = {
        "route_id": route_id,
        "supported_quality_floors": ("frontier_required", "deterministic_ok"),
        "supported_mutation_surfaces": ("source", "vault_docs"),
        "authority_ceiling": "authoritative",
        "capability_scores": {
            "information_scope": score,
            "context_length": score,
            "mutation_risk": score,
            "verification_demand": score,
            "ambiguity_novelty": score,
            "composition_coupling": score,
            "governance_sensitivity": score,
        },
        "capability_confidence": {
            "information_scope": 4,
            "context_length": 4,
        },
        "evidence_refs": (f"candidate:{route_id}:scores",),
    }
    payload.update(overrides)
    return SdlcRouteCandidate.model_validate(payload)


def test_inactive_class_stays_frontier_and_only_shadows_best_candidate() -> None:
    router = SdlcRouter(thompson_sampler=lambda _state: 0.5)
    request = _request()
    local = _candidate("local_tool.local.worker", score=5)
    frontier = _candidate(DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID, score=3)

    decision = router.route(request, (local, frontier))

    assert decision.action is SdlcRouterAction.SHADOW
    assert decision.selected_route_id == DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID
    assert decision.shadow_route_id == "local_tool.local.worker"
    assert "class_activation_gate_not_clear" in decision.reason_codes
    assert "missing_d2_information_scope_value" in decision.reason_codes
    assert "floor_checker_not_live" in decision.reason_codes
    assert router.state.route_posteriors == {}


def test_active_class_routes_to_best_feasible_candidate() -> None:
    router = SdlcRouter(
        activation_evidence={"source_python": _active_gate()},
        thompson_sampler=lambda _state: 0.25,
    )
    request = _request()
    local = _candidate("local_tool.local.worker", score=5)
    frontier = _candidate(DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID, score=3)

    decision = router.route(request, (frontier, local))

    assert decision.action is SdlcRouterAction.ROUTE
    assert decision.selected_route_id == "local_tool.local.worker"
    assert decision.candidate_scores[0].route_id == "local_tool.local.worker"
    assert decision.route_allowed is True


def test_routing_request_requires_complete_requirement_vector() -> None:
    with pytest.raises(ValueError, match="requirement_vector missing dimensions"):
        SdlcRoutingRequest.model_validate(
            {"task_id": "task-router-test", "routing_class": "source_python"}
        )

    with pytest.raises(ValueError, match="requirement_vector missing dimensions"):
        _request(requirement_vector={"quality_floor": 4})


def test_routing_request_rejects_bool_requirement_scores_before_coercion() -> None:
    with pytest.raises(ValueError, match="strict integers"):
        _request(requirement_vector=_requirement_vector(context_length=True))


def test_requirement_floor_veto_runs_before_thompson_scoring() -> None:
    router = SdlcRouter(
        activation_evidence={"source_python": _active_gate()},
        thompson_sampler=lambda _state: 0.99,
    )
    request = _request(requirement_vector=_requirement_vector(context_length=4))
    local = _candidate(
        "local_tool.local.worker",
        score=5,
        capability_scores={
            "information_scope": 5,
            "context_length": 2,
            "mutation_risk": 5,
            "verification_demand": 5,
            "ambiguity_novelty": 5,
            "composition_coupling": 5,
            "governance_sensitivity": 5,
        },
    )
    frontier = _candidate(DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID, score=4)

    decision = router.route(request, (local, frontier))

    assert decision.action is SdlcRouterAction.ROUTE
    assert decision.selected_route_id == DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID
    assert [score.route_id for score in decision.candidate_scores] == [
        DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID
    ]
    veto = decision.vetoes[0]
    assert veto.route_id == "local_tool.local.worker"
    assert "requirement_floor_not_satisfied:context_length:2<4" in veto.reason_codes


def test_quality_floor_veto_prevents_subfloor_route_even_with_high_scores() -> None:
    router = SdlcRouter(
        activation_evidence={"source_python": _active_gate()},
        thompson_sampler=lambda _state: 0.99,
    )
    request = _request(quality_floor="frontier_required")
    local = _candidate(
        "local_tool.local.worker",
        score=5,
        supported_quality_floors=("deterministic_ok",),
    )
    frontier = _candidate(DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID, score=3)

    decision = router.route(request, (local, frontier))

    assert decision.selected_route_id == DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID
    assert decision.vetoes[0].route_id == "local_tool.local.worker"
    assert "quality_floor_not_supported:frontier_required" in decision.vetoes[0].reason_codes


def test_authority_ceiling_veto_prevents_authoritative_route_to_support_only_candidate() -> None:
    router = SdlcRouter(
        activation_evidence={"source_python": _active_gate()},
        thompson_sampler=lambda _state: 0.99,
    )
    request = _request(authority_level="authoritative")
    local = _candidate("local_tool.local.worker", score=5, authority_ceiling="support_only")
    frontier = _candidate(DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID, score=3)

    decision = router.route(request, (local, frontier))

    assert decision.selected_route_id == DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID
    assert "authority_ceiling_not_satisfied:support_only" in decision.vetoes[0].reason_codes


def test_gate_pass_reward_updates_posteriors_and_selection_does_not() -> None:
    router = SdlcRouter(
        activation_evidence={"source_python": _active_gate()},
        thompson_sampler=lambda _state: 0.25,
    )
    request = _request()
    local = _candidate("local_tool.local.worker", score=5)

    decision = router.route(request, (local,))

    assert decision.selected_route_id == "local_tool.local.worker"
    assert router.state.route_posteriors == {}

    accept = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:00:00+00:00",
    )
    reject = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        gate_result="reject",
        gate_type="deterministic",
        ts="2026-06-25T00:01:00+00:00",
    )

    assert router.record_gate_event(accept) is True
    posterior = router.state.posterior_for_read("source_python", "local_tool.local.worker")
    assert posterior.use_count == 1
    assert posterior.ts_alpha > 2.0
    assert posterior.ts_beta == 1.0

    assert router.record_gate_event(reject) is True
    assert router.record_gate_event(reject) is False
    posterior = router.state.posterior_for_read("source_python", "local_tool.local.worker")
    assert posterior.use_count == 2
    assert posterior.ts_beta > 1.0


def test_non_checker_gate_events_do_not_train_posteriors() -> None:
    router = SdlcRouter()
    abstain = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        gate_result="abstain",
        gate_type="none",
        ts="2026-06-25T00:00:00+00:00",
    )

    assert router.record_gate_event(abstain) is False
    assert router.state.route_posteriors == {}


def test_candidate_projects_from_supply_vector() -> None:
    registry = load_platform_capability_registry()
    supply = build_supply_vector(registry.require(DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID))

    candidate = SdlcRouteCandidate.from_supply_vector(
        supply,
        routing_class="source_python",
    )

    assert candidate.route_id == DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID
    assert "frontier_required" in candidate.supported_quality_floors
    assert "source" in candidate.supported_mutation_surfaces
    assert candidate.capability_scores["information_scope"] >= 0
    assert candidate.capability_scores["context_length"] >= 0
    assert candidate.evidence_refs


def test_router_state_round_trips_to_own_state_file(tmp_path: Path) -> None:
    path = tmp_path / "router-state.json"
    router = SdlcRouter()
    router.record_gate_event(
        GateEvent(
            route="codex.headless.full",
            routing_class="source_python",
            gate_result="accept",
            gate_type="frontier_review",
            ts="2026-06-25T00:00:00+00:00",
        )
    )

    written = router.save(path)
    loaded = SdlcRouter.load(path)

    assert written == path
    posterior = loaded.state.posterior_for_read("source_python", "codex.headless.full")
    assert posterior.use_count == 1
    assert loaded.state.applied_gate_event_hashes == router.state.applied_gate_event_hashes
