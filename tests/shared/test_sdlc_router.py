"""Tests for the standalone SDLC capability router."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.gate_log import GateEvent, append_gate_event
from shared.platform_capability_registry import (
    build_supply_vector,
    load_platform_capability_registry,
)
from shared.route_metadata_schema import LearningEligibility
from shared.sdlc_router import (
    DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID,
    ClassActivationEvidence,
    SdlcRouteCandidate,
    SdlcRouter,
    SdlcRouterAction,
    SdlcRoutingRequest,
    gate_event_learning_allowed,
    gate_event_thompson_update_allowed,
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


def _learning_eligibility(**overrides: object) -> LearningEligibility:
    payload: dict[str, object] = {
        "thompson_update_allowed": True,
        "local_posterior_update_allowed": True,
        "evidence_kind": "witnessed",
        "evidence_freshness": "fresh",
        "confidence": 0.9,
        "envelope_valid": True,
        "support_only": False,
        "hkp_only": False,
        "public_projection_forbidden": False,
        "evidence_refs": ["witness:route-success"],
    }
    payload.update(overrides)
    return LearningEligibility.model_validate(payload)


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


def test_inactive_class_holds_when_frontier_incumbent_is_not_feasible() -> None:
    router = SdlcRouter(thompson_sampler=lambda _state: 0.5)
    request = _request(requirement_vector=_requirement_vector(context_length=4))
    local = _candidate("local_tool.local.worker", score=5)
    frontier = _candidate(
        DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID,
        score=3,
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

    decision = router.route(request, (local, frontier))

    assert decision.action is SdlcRouterAction.HOLD
    assert decision.selected_route_id is None
    assert decision.shadow_route_id == "local_tool.local.worker"
    assert "frontier_incumbent_not_feasible" in decision.reason_codes
    assert any(veto.route_id == DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID for veto in decision.vetoes)


def test_inactive_class_holds_when_frontier_incumbent_is_absent() -> None:
    router = SdlcRouter(thompson_sampler=lambda _state: 0.5)
    request = _request()
    local = _candidate("local_tool.local.worker", score=5)

    decision = router.route(request, (local,))

    assert decision.action is SdlcRouterAction.HOLD
    assert decision.selected_route_id is None
    assert decision.shadow_route_id == "local_tool.local.worker"
    assert "frontier_incumbent_not_feasible" in decision.reason_codes


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


def test_router_validation_errors_include_next_actions() -> None:
    with pytest.raises(ValueError, match="next action: provide requirement_vector"):
        SdlcRoutingRequest.model_validate(
            {"task_id": "task-router-test", "routing_class": "source_python"}
        )

    with pytest.raises(ValueError, match="next action: set each requirement_vector score"):
        _request(requirement_vector=_requirement_vector(context_length=True))

    with pytest.raises(ValueError, match="next action: provide candidate capability_scores"):
        _candidate(
            "local_tool.local.worker",
            score=5,
            capability_scores={
                "information_scope": 5,
                "context_length": 5,
                "unsupported_dimension": 5,
            },
        )


def test_candidate_rejects_unbounded_or_unknown_capability_scores() -> None:
    with pytest.raises(ValueError, match="strict integers 0..5"):
        _candidate("local_tool.local.worker", score=999)

    with pytest.raises(ValueError, match="strict integers 0..5"):
        _candidate(
            "local_tool.local.worker", score=5, capability_confidence={"context_length": True}
        )

    with pytest.raises(ValueError, match="unknown candidate capability dimension"):
        _candidate(
            "local_tool.local.worker",
            score=5,
            capability_scores={
                "information_scope": 5,
                "context_length": 5,
                "unsupported_dimension": 5,
            },
        )


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


def test_active_class_holds_when_all_candidates_are_vetoed() -> None:
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
    frontier = _candidate(
        DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID,
        score=4,
        capability_scores={
            "information_scope": 4,
            "context_length": 3,
            "mutation_risk": 4,
            "verification_demand": 4,
            "ambiguity_novelty": 4,
            "composition_coupling": 4,
            "governance_sensitivity": 4,
        },
    )

    decision = router.route(request, (local, frontier))

    assert decision.action is SdlcRouterAction.HOLD
    assert decision.selected_route_id is None
    assert decision.candidate_scores == ()
    assert decision.route_allowed is False
    assert decision.reason_codes == ("no_feasible_route_candidates",)
    assert {veto.route_id for veto in decision.vetoes} == {
        "local_tool.local.worker",
        DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID,
    }


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


def test_support_request_can_use_read_only_support_ceiling() -> None:
    router = SdlcRouter(
        activation_evidence={"source_python": _active_gate()},
        thompson_sampler=lambda _state: 0.25,
    )
    request = _request(
        authority_level="support_non_authoritative",
        mutation_surface="none",
        requirement_vector=_requirement_vector(mutation_risk=0),
    )
    readonly = _candidate(
        "local_tool.readonly.research",
        score=5,
        authority_ceiling="read_only",
        supported_mutation_surfaces=("none",),
    )
    frontier = _candidate(DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID, score=3)

    decision = router.route(request, (frontier, readonly))

    assert decision.action is SdlcRouterAction.ROUTE
    assert decision.selected_route_id == "local_tool.readonly.research"
    assert all(
        "authority_ceiling_not_satisfied:read_only" not in veto.reason_codes
        for veto in decision.vetoes
    )


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
        requirement_vector=_requirement_vector(),
        task_hash="sha256:task-router-test",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:00:00+00:00",
        learning_eligibility=_learning_eligibility(),
    )
    reject = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector=_requirement_vector(),
        task_hash="sha256:task-router-test",
        gate_result="reject",
        gate_type="deterministic",
        ts="2026-06-25T00:01:00+00:00",
        learning_eligibility=_learning_eligibility(),
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


def test_ingest_gate_events_accepts_explicit_event_iterable() -> None:
    router = SdlcRouter()
    accept = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector=_requirement_vector(),
        task_hash="sha256:task-router-test",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:00:00+00:00",
        learning_eligibility=_learning_eligibility(),
    )

    assert router.ingest_gate_events(events=[accept, accept]) == 1
    posterior = router.state.posterior_for_read("source_python", "local_tool.local.worker")
    assert posterior.use_count == 1
    assert posterior.ts_alpha > 2.0


def test_ingest_gate_events_reads_gate_log_path(tmp_path: Path) -> None:
    path = tmp_path / "gate-events.jsonl"
    accept = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector=_requirement_vector(),
        task_hash="sha256:task-router-test",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:00:00+00:00",
        learning_eligibility=_learning_eligibility(),
    )
    append_gate_event(accept, path=path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not-valid-json}\n")

    router = SdlcRouter()

    assert router.ingest_gate_events(path=path) == 1
    posterior = router.state.posterior_for_read("source_python", "local_tool.local.worker")
    assert posterior.use_count == 1


def test_thompson_gate_update_does_not_require_local_posterior_update() -> None:
    router = SdlcRouter()
    accept = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector=_requirement_vector(),
        task_hash="sha256:task-router-test",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:00:00+00:00",
        learning_eligibility=_learning_eligibility(
            thompson_update_allowed=True,
            local_posterior_update_allowed=False,
        ),
    )

    assert gate_event_learning_allowed(accept) is True
    assert gate_event_thompson_update_allowed(accept) is True
    assert router.record_gate_event(accept) is True
    posterior = router.state.posterior_for_read("source_python", "local_tool.local.worker")
    assert posterior.use_count == 1
    assert posterior.ts_alpha > 2.0


def test_local_only_learning_gate_does_not_update_thompson_posterior() -> None:
    router = SdlcRouter()
    local_only = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector=_requirement_vector(),
        task_hash="sha256:task-router-test",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:00:00+00:00",
        learning_eligibility=_learning_eligibility(
            thompson_update_allowed=False,
            local_posterior_update_allowed=True,
        ),
    )

    assert gate_event_learning_allowed(local_only) is True
    assert gate_event_thompson_update_allowed(local_only) is False
    assert router.record_gate_event(local_only) is False
    assert router.state.route_posteriors == {}


def test_gate_event_learning_allowed_requires_complete_learning_receipt() -> None:
    accept = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector=_requirement_vector(),
        task_hash="sha256:task-router-test",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:00:00+00:00",
        learning_eligibility=_learning_eligibility(),
    )

    assert gate_event_learning_allowed(accept) is True
    assert gate_event_learning_allowed(accept.model_copy(update={"task_hash": ""})) is False
    assert (
        gate_event_learning_allowed(
            accept.model_copy(
                update={
                    "learning_eligibility": _learning_eligibility(
                        thompson_update_allowed=False,
                        local_posterior_update_allowed=False,
                    )
                }
            )
        )
        is False
    )


def test_bare_gate_events_do_not_train_posteriors() -> None:
    router = SdlcRouter()
    bare_accept = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:00:00+00:00",
    )

    assert router.record_gate_event(bare_accept) is False
    assert router.state.route_posteriors == {}


def test_gate_events_need_complete_learning_receipt_to_train_posteriors() -> None:
    router = SdlcRouter()
    missing_task_hash = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector=_requirement_vector(),
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:00:00+00:00",
        learning_eligibility=_learning_eligibility(),
    )
    incomplete_requirement_vector = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector={"quality_floor": 4},
        task_hash="sha256:task-router-test",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:01:00+00:00",
        learning_eligibility=_learning_eligibility(),
    )
    missing_route = GateEvent(
        route=" ",
        routing_class="source_python",
        requirement_vector=_requirement_vector(),
        task_hash="sha256:task-router-test",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:01:30+00:00",
        learning_eligibility=_learning_eligibility(),
    )
    missing_routing_class = GateEvent(
        route="local_tool.local.worker",
        routing_class=" ",
        requirement_vector=_requirement_vector(),
        task_hash="sha256:task-router-test",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:01:45+00:00",
        learning_eligibility=_learning_eligibility(),
    )
    learning_not_allowed = GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector=_requirement_vector(),
        task_hash="sha256:task-router-test",
        gate_result="accept",
        gate_type="deterministic",
        ts="2026-06-25T00:02:00+00:00",
        learning_eligibility=_learning_eligibility(
            thompson_update_allowed=False,
            local_posterior_update_allowed=False,
        ),
    )

    assert router.record_gate_event(missing_task_hash) is False
    assert router.record_gate_event(incomplete_requirement_vector) is False
    assert router.record_gate_event(missing_route) is False
    assert router.record_gate_event(missing_routing_class) is False
    assert router.record_gate_event(learning_not_allowed) is False
    assert router.state.route_posteriors == {}


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
            requirement_vector=_requirement_vector(),
            task_hash="sha256:task-router-test",
            gate_result="accept",
            gate_type="frontier_review",
            ts="2026-06-25T00:00:00+00:00",
            learning_eligibility=_learning_eligibility(),
        )
    )

    written = router.save(path)
    loaded = SdlcRouter.load(path)

    assert written == path
    posterior = loaded.state.posterior_for_read("source_python", "codex.headless.full")
    assert posterior.use_count == 1
    assert loaded.state.applied_gate_event_hashes == router.state.applied_gate_event_hashes
