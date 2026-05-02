"""Tests for the conversion broker JSONL runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import CollectorRegistry

from agents.conversion_broker.runner import ConversionBrokerRunner
from shared.content_programme_run_store import (
    ContentProgrammeRunEnvelope,
    build_fixture_envelope,
)
from shared.conversion_broker import ConversionBrokerMetrics
from shared.format_public_event_adapter import ProgrammeBoundaryEvent


def _boundary(run: ContentProgrammeRunEnvelope, **overrides: Any) -> ProgrammeBoundaryEvent:
    payload = {
        "boundary_id": "pbe_conversion_runner_001",
        "emitted_at": datetime(2026, 4, 29, 13, 54, tzinfo=UTC),
        "programme_id": run.programme_id,
        "run_id": run.run_id,
        "format_id": run.format_id,
        "sequence": 1,
        "boundary_type": "rank.assigned",
        "public_private_mode": run.public_private_mode,
        "grounding_question": run.grounding_question,
        "summary": "Assigned a public-safe evidence audit rank.",
        "evidence_refs": ("source:primary_doc_a", "grounding-gate:evidence_audit_a"),
        "no_expert_system_gate": {
            "gate_ref": run.gate_refs.grounding_gate_refs[0],
            "gate_state": "pass",
            "claim_allowed": True,
            "public_claim_allowed": True,
            "infractions": (),
        },
        "claim_shape": {
            "claim_kind": "ranking",
            "authority_ceiling": "evidence_bound",
            "confidence_label": "medium_high",
            "uncertainty": "Scope is limited to the cited evidence window.",
            "scope_limit": "Ranks only the declared source bundle.",
        },
        "public_event_mapping": {
            "internal_only": False,
            "research_vehicle_event_type": "programme.boundary",
            "state_kind": "programme_state",
            "source_substrate_id": "programme_cuepoints",
            "allowed_surfaces": ("youtube_chapters", "archive"),
            "denied_surfaces": ("youtube_cuepoints", "youtube_shorts", "monetization"),
            "fallback_action": "chapter_only",
            "unavailable_reasons": (),
        },
        "cuepoint_chapter_policy": {
            "live_ad_cuepoint_allowed": False,
            "vod_chapter_allowed": True,
            "live_cuepoint_distinct_from_vod_chapter": True,
            "chapter_label": "Evidence audit claim",
            "timecode": "00:00",
            "cuepoint_unavailable_reason": None,
        },
        "dry_run_unavailable_reasons": (),
        "duplicate_key": f"{run.programme_id}:{run.run_id}:rank.assigned:001",
    }
    payload.update(overrides)
    return ProgrammeBoundaryEvent.model_validate(payload)


def test_runner_processes_unseen_boundaries_and_persists_cursor(tmp_path: Path) -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    boundary = _boundary(run)
    run_path = tmp_path / "runs.jsonl"
    boundary_path = tmp_path / "boundaries.jsonl"
    public_event_path = tmp_path / "events.jsonl"
    candidate_path = tmp_path / "candidates.jsonl"
    cursor_path = tmp_path / "cursor.json"
    run_path.write_text(run.model_dump_json() + "\n", encoding="utf-8")
    boundary_path.write_text(boundary.model_dump_json() + "\n", encoding="utf-8")
    runner = ConversionBrokerRunner(
        run_envelope_path=run_path,
        boundary_event_path=boundary_path,
        public_event_path=public_event_path,
        candidate_path=candidate_path,
        cursor_path=cursor_path,
        metrics=ConversionBrokerMetrics(CollectorRegistry()),
    )

    assert runner.run_once() == 1
    assert public_event_path.exists()
    assert candidate_path.exists()
    cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
    assert cursor["processed_boundary_keys"] == [
        f"{boundary.run_id}:{boundary.boundary_id}:{boundary.duplicate_key}"
    ]
    candidate_line_count = len(candidate_path.read_text(encoding="utf-8").splitlines())
    public_event_line_count = len(public_event_path.read_text(encoding="utf-8").splitlines())

    assert runner.run_once() == 0
    assert len(candidate_path.read_text(encoding="utf-8").splitlines()) == candidate_line_count
    assert len(public_event_path.read_text(encoding="utf-8").splitlines()) == (
        public_event_line_count
    )
