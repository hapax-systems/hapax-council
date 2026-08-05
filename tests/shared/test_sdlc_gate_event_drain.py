"""N1 gate-event drain — report-only by default; apply is explicit."""

from __future__ import annotations

from pathlib import Path

from shared.gate_log import GateEvent, append_gate_event
from shared.route_metadata_schema import (
    FreshnessState,
    LearningEligibility,
    LearningEvidenceKind,
)
from shared.sdlc_gate_event_drain import drain_gate_events, observe_status
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS, SdlcRouter


def _requirement_vector() -> dict[str, int]:
    return {dim: 2 for dim in REQUIREMENT_VECTOR_DIMENSIONS}


def _learning_eligibility() -> LearningEligibility:
    return LearningEligibility(
        thompson_update_allowed=True,
        local_posterior_update_allowed=True,
        evidence_kind=LearningEvidenceKind.WITNESSED,
        evidence_freshness=FreshnessState.FRESH,
        confidence=1.0,
        envelope_valid=True,
        support_only=False,
        hkp_only=False,
        public_projection_forbidden=False,
        evidence_refs=["deterministic:test"],
        reason_codes=["test"],
    )


def _accept_event(**overrides) -> GateEvent:
    base = dict(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector=_requirement_vector(),
        task_hash="sha256:n1-drain-test",
        gate_result="accept",
        gate_type="deterministic",
        provenance="witnessed",
        ts="2026-08-05T00:00:00+00:00",
        learning_eligibility=_learning_eligibility(),
    )
    base.update(overrides)
    return GateEvent(**base)


def test_report_only_does_not_write_state(tmp_path: Path) -> None:
    log = tmp_path / "gate-events.jsonl"
    state = tmp_path / "router-state.json"
    append_gate_event(_accept_event(), path=log)

    report = drain_gate_events(gate_log=log, router_state=state, apply=False)

    assert report.mode == "report"
    assert report.state_written is False
    assert not state.exists()
    assert report.total_events == 1
    assert report.eligible_witnessed_learning == 1
    assert report.would_apply == 1
    assert report.applied == 0
    assert report.as_dict()["dispatch_selection_changed"] is False


def test_apply_writes_state_and_is_idempotent(tmp_path: Path) -> None:
    log = tmp_path / "gate-events.jsonl"
    state = tmp_path / "router-state.json"
    append_gate_event(_accept_event(), path=log)

    first = drain_gate_events(gate_log=log, router_state=state, apply=True)
    assert first.applied == 1
    assert first.state_written is True
    assert state.exists()

    router = SdlcRouter.load(state)
    posterior = router.state.posterior_for_read("source_python", "local_tool.local.worker")
    assert posterior.use_count == 1

    second = drain_gate_events(gate_log=log, router_state=state, apply=True)
    assert second.applied == 0
    assert second.skipped_already_applied == 1
    assert second.state_written is False


def test_skips_non_witnessed(tmp_path: Path) -> None:
    log = tmp_path / "gate-events.jsonl"
    append_gate_event(_accept_event(provenance="fixture"), path=log)

    report = drain_gate_events(gate_log=log, router_state=tmp_path / "r.json", apply=False)
    assert report.would_apply == 0
    assert report.skipped_not_witnessed == 1


def test_observe_status_includes_next_actions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_OUTCOME_GATE_ON_CLOSE", raising=False)
    log = tmp_path / "gate-events.jsonl"
    status = observe_status(gate_log=log, router_state=tmp_path / "r.json")
    assert status["total_events"] == 0
    assert status["outcome_gate_on_close_enabled_now"] is False
    assert any("HAPAX_OUTCOME_GATE_ON_CLOSE" in a for a in status["next_actions"])
