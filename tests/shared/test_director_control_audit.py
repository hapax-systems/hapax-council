"""Tests for director control-move audit records and writer."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from shared.director_control_audit import (
    AuditEvidence,
    AuditTrail,
    ChapterCandidate,
    ClipCandidate,
    DirectorControlMoveAuditLog,
    DirectorControlMoveAuditRecord,
    FallbackRecord,
    GateResult,
    GateResults,
    MarkBoundaryProjection,
    MetricSummary,
    MoveReason,
    RenderedEvidence,
    SourceMoveRef,
    emit_director_control_move_metric,
)


def _gate(gate: str, *, passed: bool = True, state: str = "pass") -> GateResult:
    return GateResult(
        gate=gate,
        state=state,
        passed=passed,
        evidence_refs=[f"{gate}:evidence"] if passed else [],
        denial_reasons=[] if passed else [f"{gate}_blocked"],
    )


def _gate_results() -> GateResults:
    return GateResults(
        no_expert_system=_gate("no_expert_system"),
        public_claim=_gate("public_claim", passed=False, state="dry_run"),
        rights=_gate("rights"),
        privacy=_gate("privacy"),
        egress=_gate("egress", passed=False, state="dry_run"),
        audio=_gate("audio", state="not_applicable"),
        monetization=_gate("monetization", passed=False, state="unavailable"),
        archive=_gate("archive"),
        cuepoint_chapter=_gate("cuepoint_chapter", passed=False, state="dry_run"),
    )


def _record() -> DirectorControlMoveAuditRecord:
    return DirectorControlMoveAuditRecord(
        audit_id="dcma_20260429t024000z_rank_boundary_001",
        recorded_at=datetime(2026, 4, 29, 2, 40, tzinfo=UTC),
        decision_id="dsm-20260429t023957z-rank-boundary",
        programme_id="programme_tierlist_models_20260429",
        run_id="run_20260429_models_a",
        lane_id="programme_cuepoints",
        verb="mark_boundary",
        reason=MoveReason(
            summary="Ranking boundary preserved as dry-run replay evidence.",
            category="mark_boundary",
            source_refs=["boundary:pbe_20260429t023957z_rank_003"],
        ),
        source_move=SourceMoveRef(
            director_move_ref="director-control/dsm-20260429t023957z-rank-boundary.json",
            director_tier="programme",
            target_type="cuepoint",
            target_id="programme_boundary",
        ),
        execution_state="dry_run",
        result_state="dry_run",
        evidence=[
            AuditEvidence(
                source_type="programme_boundary_event",
                ref="pbe_20260429t023957z_rank_003",
                status="fresh",
                observed_at=datetime(2026, 4, 29, 2, 39, 57, tzinfo=UTC),
                age_s=3.0,
                ttl_s=60.0,
                detail="Boundary event carried rank.assigned with chapter fallback.",
            )
        ],
        gate_results=_gate_results(),
        fallback=FallbackRecord(
            mode="chapter_only",
            reason="Keep a VOD chapter candidate and do not send a live cuepoint.",
            applied=True,
            operator_facing=False,
            substitute_ref="chapter:dcma_20260429t024000z_rank_boundary_001",
            next_action="public-event adapter may consume after gates pass",
        ),
        rendered_evidence=RenderedEvidence(
            summary="Dry-run mark_boundary preserved as replay chapter evidence.",
            payload_ref="director-control/dcma_20260429t024000z_rank_boundary_001.json",
            artifact_refs=["director-control/dcma_20260429t024000z_rank_boundary_001.json"],
            replay_ref="replay:programme_tierlist_models_20260429:00:00",
            scorecard_ref="grounding-scorecard:run_20260429_models_a",
        ),
        mark_boundary_projection=MarkBoundaryProjection(
            is_mark_boundary=True,
            programme_boundary_ref="pbe_20260429t023957z_rank_003",
            chapter_candidate=ChapterCandidate(
                candidate_id="chapter_20260429t024000z_rank_boundary",
                label="Model grounding provider ranking",
                timecode="00:00",
                allowed=True,
            ),
            clip_candidate=ClipCandidate(
                candidate_id="clip_20260429t024000z_rank_boundary",
                start_s=0.0,
                end_s=45.0,
                allowed=False,
                unavailable_reasons=["shorts_rights_gate_pending"],
            ),
            public_event_ref=None,
        ),
        audit_trail=AuditTrail(
            sinks=[
                "jsonl",
                "artifact_payload",
                "prometheus_counter",
                "replay_index",
                "grounding_scorecard",
                "public_event_adapter",
            ],
            consumers=["replay", "metrics", "grounding_scorecard", "public_event_adapter"],
            duplicate_key="programme:run:mark_boundary:003",
            jsonl_ref="hapax-state/director-control/moves.jsonl",
            artifact_ref=(
                "hapax-state/director-control/artifacts/"
                "dcma_20260429t024000z_rank_boundary_001.json"
            ),
        ),
        metrics=MetricSummary(
            counter_name="hapax_director_control_move_total",
            labels={
                "verb": "mark_boundary",
                "execution_state": "dry_run",
                "result_state": "dry_run",
                "public_claim_allowed": "false",
            },
            outcome="chapter_candidate_preserved",
        ),
        public_claim_allowed=False,
    )


def test_record_contains_required_acceptance_fields() -> None:
    record = _record()

    assert record.programme_id == "programme_tierlist_models_20260429"
    assert record.run_id == "run_20260429_models_a"
    assert record.lane_id == "programme_cuepoints"
    assert record.verb == "mark_boundary"
    assert record.reason.category == "mark_boundary"
    assert record.evidence[0].status == "fresh"
    assert record.gate_results.public_claim.state == "dry_run"
    assert record.fallback.mode == "chapter_only"
    assert record.rendered_evidence.replay_ref is not None


def test_writer_persists_jsonl_and_artifact(tmp_path) -> None:
    record = _record()
    audit_log = DirectorControlMoveAuditLog(root=tmp_path)

    audit_log.record(record)

    jsonl_path = tmp_path / "moves.jsonl"
    artifact_path = tmp_path / "artifacts" / f"{record.audit_id}.json"
    assert jsonl_path.exists()
    assert artifact_path.exists()

    line_payload = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert line_payload["audit_id"] == record.audit_id
    assert artifact_payload["audit_id"] == record.audit_id
    assert audit_log.read_all()[0]["audit_id"] == record.audit_id


def test_mark_boundary_requires_projection_evidence() -> None:
    payload = _record().model_dump()
    payload["mark_boundary_projection"]["is_mark_boundary"] = False

    with pytest.raises(ValueError, match="is_mark_boundary=true"):
        DirectorControlMoveAuditRecord.model_validate(payload)


def test_non_boundary_move_cannot_claim_boundary_projection() -> None:
    payload = _record().model_dump()
    payload["verb"] = "foreground"

    with pytest.raises(ValueError, match="non-mark_boundary"):
        DirectorControlMoveAuditRecord.model_validate(payload)


def test_unavailable_state_is_explicit_and_valid() -> None:
    payload = _record().model_dump()
    payload["verb"] = "foreground"
    payload["execution_state"] = "unavailable"
    payload["result_state"] = "unavailable"
    payload["fallback"]["mode"] = "unavailable"
    payload["fallback"]["applied"] = False
    payload["mark_boundary_projection"] = MarkBoundaryProjection(
        is_mark_boundary=False,
        programme_boundary_ref=None,
        chapter_candidate=None,
        clip_candidate=None,
        public_event_ref=None,
    ).model_dump()

    record = DirectorControlMoveAuditRecord.model_validate(payload)

    assert record.result_state == "unavailable"
    assert record.fallback.mode == "unavailable"


def test_metrics_emitter_does_not_raise() -> None:
    emit_director_control_move_metric(_record())
