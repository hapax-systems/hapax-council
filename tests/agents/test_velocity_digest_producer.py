"""Tests for the daily velocity digest public event producer."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.velocity_digest_public_event_producer import (
    GitStats,
    _event_already_written,
    _fallback_summary,
    build_velocity_digest_event,
    gather_git_stats,
)


@pytest.fixture
def sample_stats() -> GitStats:
    return GitStats(
        total_commits=12,
        prs_merged=4,
        reverts=1,
        subjects=[
            "feat(compositor): add new layout mode (#2900)",
            "fix(audio): resolve L-12 routing race",
            "Merge pull request #2901 from ryanklee/beta/pub-hardening",
            "revert: undo broken migration",
        ],
        files_changed=37,
        areas=["agents/studio_compositor", "shared", "systemd/units"],
    )


class TestGatherGitStats:
    def test_parses_git_log_output(self, tmp_path: Path) -> None:
        log_output = (
            "abc1234 feat(audio): new routing (#100)\n"
            "def5678 Merge pull request #101 from ryanklee/fix\n"
            "ghi9012 revert: undo broken change\n"
            "jkl3456 chore: update deps\n"
        )
        diff_output = "agents/foo.py\nshared/bar.py\nsystemd/units/baz.service\n"

        with patch("agents.velocity_digest_public_event_producer.subprocess.run") as mock_run:
            mock_log = MagicMock()
            mock_log.stdout = log_output
            mock_diff = MagicMock()
            mock_diff.stdout = diff_output
            mock_run.side_effect = [mock_log, mock_diff]

            stats = gather_git_stats(tmp_path, date(2026, 5, 10))

        assert stats.total_commits == 4
        assert stats.prs_merged == 2
        assert stats.reverts == 1
        assert stats.files_changed == 3
        assert "agents/foo.py" in [a for a in stats.areas if "agents" in a]

    def test_empty_log(self, tmp_path: Path) -> None:
        with patch("agents.velocity_digest_public_event_producer.subprocess.run") as mock_run:
            mock_empty = MagicMock()
            mock_empty.stdout = ""
            mock_run.return_value = mock_empty

            stats = gather_git_stats(tmp_path, date(2026, 5, 10))

        assert stats.total_commits == 0
        assert stats.prs_merged == 0
        assert stats.reverts == 0


class TestBuildEvent:
    def test_event_structure(self, sample_stats: GitStats) -> None:
        now = datetime(2026, 5, 10, 4, 0, 0, tzinfo=UTC)
        event = build_velocity_digest_event(
            "12 commits, 4 PRs merged across compositor and audio.",
            sample_stats,
            date(2026, 5, 10),
            now,
        )

        assert event.event_type == "velocity.digest"
        assert event.event_id == "rvpe:velocity_digest:2026-05-10"
        assert event.state_kind == "research_observation"
        assert event.rights_class == "operator_original"
        assert event.privacy_class == "public_safe"
        assert event.salience == pytest.approx(0.45)
        assert event.source.producer == "agents.velocity_digest_public_event_producer"
        assert event.source.substrate_id == "git_log"

    def test_surface_policy(self, sample_stats: GitStats) -> None:
        now = datetime(2026, 5, 10, 4, 0, 0, tzinfo=UTC)
        event = build_velocity_digest_event("test", sample_stats, date(2026, 5, 10), now)

        assert "omg_statuslog" in event.surface_policy.allowed_surfaces
        assert "discord" in event.surface_policy.allowed_surfaces
        assert event.surface_policy.claim_live is False
        assert event.surface_policy.claim_archive is True
        assert event.surface_policy.requires_egress_public_claim is False

    def test_serializes_to_valid_jsonl(self, sample_stats: GitStats) -> None:
        now = datetime(2026, 5, 10, 4, 0, 0, tzinfo=UTC)
        event = build_velocity_digest_event("test summary", sample_stats, date(2026, 5, 10), now)
        line = event.to_json_line()

        assert line.endswith("\n")
        parsed = json.loads(line)
        assert parsed["event_type"] == "velocity.digest"
        assert parsed["event_id"] == "rvpe:velocity_digest:2026-05-10"

    def test_provenance_evidence_refs(self, sample_stats: GitStats) -> None:
        now = datetime(2026, 5, 10, 4, 0, 0, tzinfo=UTC)
        event = build_velocity_digest_event("test", sample_stats, date(2026, 5, 10), now)

        assert "git.log.main.daily" in event.provenance.evidence_refs
        assert "commits:12" in event.provenance.evidence_refs
        assert "prs:4" in event.provenance.evidence_refs


class TestFallbackSummary:
    def test_includes_all_stats(self, sample_stats: GitStats) -> None:
        summary = _fallback_summary(sample_stats)
        assert "12 commits" in summary
        assert "4 PRs merged" in summary
        assert "1 revert" in summary
        assert "37 files changed" in summary

    def test_no_reverts_omits_revert_text(self) -> None:
        stats = GitStats(
            total_commits=5,
            prs_merged=2,
            reverts=0,
            subjects=[],
            files_changed=10,
            areas=["agents"],
        )
        summary = _fallback_summary(stats)
        assert "revert" not in summary

    def test_under_280_chars(self, sample_stats: GitStats) -> None:
        summary = _fallback_summary(sample_stats)
        assert len(summary) <= 280


class TestIdempotency:
    def test_detects_existing_event(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        path.write_text(
            '{"event_id":"rvpe:velocity_digest:2026-05-10","event_type":"velocity.digest"}\n',
            encoding="utf-8",
        )
        assert _event_already_written("rvpe:velocity_digest:2026-05-10", path) is True

    def test_returns_false_when_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        path.write_text(
            '{"event_id":"rvpe:velocity_digest:2026-05-09","event_type":"velocity.digest"}\n',
            encoding="utf-8",
        )
        assert _event_already_written("rvpe:velocity_digest:2026-05-10", path) is False

    def test_returns_false_when_file_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.jsonl"
        assert _event_already_written("rvpe:velocity_digest:2026-05-10", path) is False

    def test_handles_malformed_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        path.write_text(
            'not json\n{"event_id":"rvpe:velocity_digest:2026-05-10"}\n',
            encoding="utf-8",
        )
        assert _event_already_written("rvpe:velocity_digest:2026-05-10", path) is True
