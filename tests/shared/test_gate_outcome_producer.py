"""Tests for the SDLC outcome producer — witnessed verdicts that close the learning loop.

The admission producer (shared/gate_event_producer.py, #4330) emits observational events
(gate_type="none") that never move a posterior. This module covers its WITNESSED-OUTCOME
counterpart: a real accept/reject verdict must move the Thompson posterior, and only when its
provenance is "witnessed" (fixtures/admission events must not poison the Beta).
"""

from __future__ import annotations

from pathlib import Path

from shared.gate_outcome_producer import build_outcome_gate_event, emit_outcome_gate_event
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS, SdlcRouter


def _task_fields() -> dict[str, object]:
    """A minimal cc-task surface that derives a complete vector + source_python class."""
    return {
        "requirement_vector": {dim: 3 for dim in REQUIREMENT_VECTOR_DIMENSIONS},
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/example.py"],
    }


def test_witnessed_accept_moves_the_posterior() -> None:
    router = SdlcRouter()
    event = build_outcome_gate_event(
        _task_fields(),
        route="local_tool.local.worker",
        gate_result="accept",
        gate_type="deterministic",
    )
    # a LEARNING event, not an admission observation
    assert event.gate_type == "deterministic"
    assert event.gate_result == "accept"
    assert event.provenance == "witnessed"
    assert event.learning_eligibility.thompson_update_allowed is True
    assert event.routing_class == "source_python"

    assert router.record_gate_event(event) is True
    posterior = router.state.posterior_for_read(event.routing_class, event.route)
    assert posterior.use_count == 1
    assert posterior.ts_alpha > 2.0  # accept -> alpha up
    assert posterior.ts_beta == 1.0


def test_witnessed_reject_moves_the_posterior_down() -> None:
    router = SdlcRouter()
    event = build_outcome_gate_event(
        _task_fields(),
        route="local_tool.local.worker",
        gate_result="reject",
        gate_type="deterministic",
    )
    assert router.record_gate_event(event) is True
    posterior = router.state.posterior_for_read(event.routing_class, event.route)
    assert posterior.use_count == 1
    assert posterior.ts_beta > 1.0  # reject -> beta up


def test_non_witnessed_event_does_not_move_the_posterior() -> None:
    """Fixtures / non-witnessed provenance must NOT move the Beta."""
    router = SdlcRouter()
    event = build_outcome_gate_event(
        _task_fields(),
        route="local_tool.local.worker",
        gate_result="accept",
        gate_type="deterministic",
        provenance="fixture",
    )
    assert event.provenance == "fixture"
    assert router.record_gate_event(event) is False
    assert router.state.route_posteriors == {}


def test_emit_then_ingest_closes_the_loop(tmp_path: Path) -> None:
    """STEP-8 miniature: a witnessed verdict written to the log, ingested, moves the posterior.

    This is the open-vs-closed loop in one assertion — the write side (emit ->
    gate-events.jsonl) joined to the router's read side (ingest_gate_events).
    """
    log = tmp_path / "gate-events.jsonl"
    event = emit_outcome_gate_event(
        _task_fields(),
        route="local_tool.local.worker",
        gate_result="accept",
        gate_type="deterministic",
        path=log,
    )
    assert event.provenance == "witnessed"

    router = SdlcRouter()
    assert router.ingest_gate_events(path=log) == 1
    posterior = router.state.posterior_for_read(event.routing_class, event.route)
    assert posterior.use_count == 1
    assert posterior.ts_alpha > 2.0
