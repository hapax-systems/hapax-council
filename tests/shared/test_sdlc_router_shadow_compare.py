"""N2 shadow-compare — log-only; no dispatch mutation."""

from __future__ import annotations

from pathlib import Path

from shared.sdlc_router import (
    DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID,
    ClassActivationEvidence,
    SdlcRouteCandidate,
    SdlcRouter,
    SdlcRouterAction,
    SdlcRoutingRequest,
)
from shared.sdlc_router_shadow_compare import compare_route, shadow_compare


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
        "task_id": "task-shadow-n2",
        "routing_class": "source_python",
        "requirement_vector": _requirement_vector(),
        "quality_floor": "frontier_required",
        "mutation_surface": "source",
        "authority_level": "authoritative",
        "frontier_incumbent_route_id": DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID,
    }
    payload.update(overrides)
    return SdlcRoutingRequest.model_validate(payload)


def _candidate(route_id: str, *, score: int) -> SdlcRouteCandidate:
    return SdlcRouteCandidate.model_validate(
        {
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
            "evidence_refs": (f"candidate:{route_id}",),
        }
    )


def test_inactive_class_shadow_disagrees_with_weaker_frontier() -> None:
    router = SdlcRouter(thompson_sampler=lambda _state: 0.5)
    local = _candidate("local_tool.local.worker", score=5)
    frontier = _candidate(DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID, score=3)

    record = compare_route(_request(), (local, frontier), router=router)

    assert record.action == SdlcRouterAction.SHADOW.value
    assert record.live_selected_route_id == DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID
    assert record.shadow_route_id == "local_tool.local.worker"
    assert record.router_would_prefer == "local_tool.local.worker"
    assert record.agree is False
    assert record.dispatch_mutated is False


def test_active_class_route_agrees_with_winner() -> None:
    activation = ClassActivationEvidence(
        routing_class="source_python",
        information_scope_value_count=1,
        context_length_value_count=1,
        floor_checker_live=True,
        floor_checker_ref="floor-checker:source-python:v1",
        evidence_refs=("eval:source-python:d2-d3",),
    )
    router = SdlcRouter(
        thompson_sampler=lambda _state: 0.5,
        activation_evidence={"source_python": activation},
    )
    local = _candidate("local_tool.local.worker", score=5)
    frontier = _candidate(DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID, score=3)

    record = compare_route(_request(), (local, frontier), router=router)

    assert record.action == SdlcRouterAction.ROUTE.value
    assert record.live_selected_route_id == "local_tool.local.worker"
    assert record.router_would_prefer == "local_tool.local.worker"
    assert record.agree is True
    assert record.dispatch_mutated is False


def test_shadow_compare_appends_log(tmp_path: Path) -> None:
    log = tmp_path / "shadow-compare.jsonl"
    router = SdlcRouter(thompson_sampler=lambda _state: 0.5)
    local = _candidate("local_tool.local.worker", score=5)
    frontier = _candidate(DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID, score=3)

    record = shadow_compare(
        _request(),
        (local, frontier),
        router=router,
        log_path=log,
        write_log=True,
    )
    assert log.exists()
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert record.schema == "hapax.sdlc_router_shadow_compare.v1"
    assert '"dispatch_mutated":false' in lines[0].replace(" ", "")
