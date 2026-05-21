"""Tests for the PR merge announcement producer."""

from __future__ import annotations

import json

from shared.pr_merge_announcement_producer import (
    build_pr_merge_event,
    emit_pr_merge_event,
)


class TestBuildEvent:
    def test_builds_valid_event(self):
        event = build_pr_merge_event(
            pr_number=3500,
            pr_title="feat: add grounding verifier",
            merge_sha="abc123def456",
            merged_at="2026-05-20T12:00:00Z",
            author="delta",
        )
        assert event.event_id.startswith("pr-merge-")
        assert event.event_type == "metadata.update"
        assert event.state_kind == "research_observation"
        assert event.rights_class == "operator_original"
        assert event.privacy_class == "public_safe"

    def test_event_id_deterministic(self):
        kwargs = dict(
            pr_number=100,
            pr_title="test",
            merge_sha="aaa",
            merged_at="2026-01-01T00:00:00Z",
            author="x",
        )
        e1 = build_pr_merge_event(**kwargs)
        e2 = build_pr_merge_event(**kwargs)
        assert e1.event_id == e2.event_id

    def test_event_id_differs_for_different_prs(self):
        base = dict(
            pr_title="test",
            merge_sha="aaa",
            merged_at="2026-01-01T00:00:00Z",
            author="x",
        )
        e1 = build_pr_merge_event(pr_number=1, **base)
        e2 = build_pr_merge_event(pr_number=2, **base)
        assert e1.event_id != e2.event_id

    def test_provenance_contains_pr_ref(self):
        event = build_pr_merge_event(
            pr_number=42,
            pr_title="fix: something",
            merge_sha="deadbeef",
            merged_at="2026-05-20T12:00:00Z",
            author="alpha",
        )
        assert "42" in event.provenance.citation_refs[0]
        assert "deadbeef" in event.provenance.evidence_refs[0]

    def test_technical_note_content(self):
        event = build_pr_merge_event(
            pr_number=99,
            pr_title="feat: new feature",
            merge_sha="abc",
            merged_at="2026-05-20T12:00:00Z",
            author="delta",
            changed_files=5,
            additions=100,
            deletions=20,
        )
        assert any("99" in ref for ref in event.provenance.citation_refs)
        assert event.provenance.rights_basis == "operator_original"

    def test_surface_policy(self):
        event = build_pr_merge_event(
            pr_number=1,
            pr_title="test",
            merge_sha="a",
            merged_at="2026-01-01T00:00:00Z",
            author="x",
        )
        assert "github_profile" in event.surface_policy.allowed_surfaces
        assert event.surface_policy.requires_provenance


class TestSalience:
    def test_large_pr_high_salience(self):
        event = build_pr_merge_event(
            pr_number=1,
            pr_title="big refactor",
            merge_sha="a",
            merged_at="2026-01-01T00:00:00Z",
            author="x",
            changed_files=25,
            additions=600,
            deletions=200,
        )
        assert event.salience >= 0.7

    def test_small_pr_low_salience(self):
        event = build_pr_merge_event(
            pr_number=1,
            pr_title="typo fix",
            merge_sha="a",
            merged_at="2026-01-01T00:00:00Z",
            author="x",
            changed_files=1,
            additions=2,
            deletions=1,
        )
        assert event.salience <= 0.4


class TestEmit:
    def test_emits_to_file(self, tmp_path):
        event = build_pr_merge_event(
            pr_number=3500,
            pr_title="test emit",
            merge_sha="abc123",
            merged_at="2026-05-20T12:00:00Z",
            author="delta",
        )
        output = tmp_path / "events.jsonl"
        emit_pr_merge_event(event, output_path=output)
        assert output.exists()
        lines = output.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["event_id"] == event.event_id

    def test_appends_multiple(self, tmp_path):
        output = tmp_path / "events.jsonl"
        for i in range(3):
            event = build_pr_merge_event(
                pr_number=i,
                pr_title=f"pr {i}",
                merge_sha=f"sha{i}",
                merged_at="2026-05-20T12:00:00Z",
                author="delta",
            )
            emit_pr_merge_event(event, output_path=output)
        lines = output.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_serialization_roundtrip(self, tmp_path):
        event = build_pr_merge_event(
            pr_number=42,
            pr_title="roundtrip test",
            merge_sha="beef",
            merged_at="2026-05-20T12:00:00Z",
            author="delta",
            changed_files=10,
            additions=200,
            deletions=50,
        )
        output = tmp_path / "events.jsonl"
        emit_pr_merge_event(event, output_path=output)
        parsed = json.loads(output.read_text().strip())
        assert parsed["event_type"] == "metadata.update"
        assert any("PR #42" in ref for ref in parsed["provenance"]["citation_refs"])
