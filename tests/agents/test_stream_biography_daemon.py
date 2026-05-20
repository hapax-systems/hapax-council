"""Tests for stream biography summary and lifecycle evidence."""

from __future__ import annotations

import json

from agents import stream_biography_daemon
from shared.stream_biography import GroundedConcept, GroundedIntroduction, StreamBiography


def test_stream_biography_summary_names_inchoate_evidence_gaps() -> None:
    bio = StreamBiography()

    summary = bio.to_planner_summary()

    assert "Narrative stage: inchoate" in summary
    assert "Established concepts: NONE" in summary
    assert "Introductions: NONE" in summary
    assert "operator/system introduction absent" in summary
    assert "no completed segments" in summary


def test_stream_biography_summary_names_established_stage_from_evidence() -> None:
    bio = StreamBiography(
        total_segments_completed=3,
        established_concepts=[
            GroundedConcept(concept="density field", grounding_confidence=0.8),
            GroundedConcept(concept="programme planner", grounding_confidence=0.7),
            GroundedConcept(concept="stream biography", grounding_confidence=0.7),
        ],
        introductions=[GroundedIntroduction(subject="operator")],
    )

    assert bio.latest_narrative_stage() == "established"


def test_count_completed_segments_reads_programme_outcome_logs(tmp_path, monkeypatch) -> None:
    store = tmp_path / "programmes.jsonl"
    store.write_text("", encoding="utf-8")
    outcome = tmp_path / "programmes" / "show-a" / "prog-a.jsonl"
    outcome.parent.mkdir(parents=True)
    outcome.write_text(
        json.dumps({"event": "started"}) + "\n" + json.dumps({"event": "ended_planned"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(stream_biography_daemon, "_PROGRAMME_STORE", store)
    monkeypatch.setattr(stream_biography_daemon, "_PROGRAMME_OUTCOME_ROOT", tmp_path / "programmes")

    assert stream_biography_daemon._count_completed_segments() == 1
