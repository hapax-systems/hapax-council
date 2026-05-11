"""Tests for pipeline orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents.auto_clip.pipeline import (
    is_paused,
    process_candidate,
    run_pipeline,
)
from agents.auto_clip.segment_detection import (
    DecoderChannel,
    LlmSegmentDetector,
    RollingContext,
    SegmentCandidate,
)


def _candidate(resonance: float = 0.8) -> SegmentCandidate:
    return SegmentCandidate(
        start_offset_seconds=10.0,
        end_offset_seconds=40.0,
        resonance=resonance,
        decoder_channels=[DecoderChannel.VISUAL],
        rationale="Test candidate",
        hook_text="watch this",
        suggested_title="Test Short",
    )


def test_is_paused_false_by_default():
    assert not is_paused()


def test_is_paused_true_when_file_exists(tmp_path: Path):
    pause = tmp_path / "pause.md"
    pause.write_text("paused")
    with patch("agents.auto_clip.pipeline.PAUSE_FILE", pause):
        assert is_paused()


def test_process_candidate_fails_gracefully_on_no_segments():
    now = datetime.now(UTC)
    result = process_candidate(
        _candidate(),
        now - timedelta(minutes=10),
        output_dir=Path("/tmp/auto-clip-test"),
        archive_path=Path("/nonexistent/archive"),
        dry_run=True,
    )
    assert result.stage_failed == "extract"
    assert result.extracted is None


def test_run_pipeline_skips_when_paused(tmp_path: Path):
    pause = tmp_path / "pause.md"
    pause.write_text("paused by operator")
    with patch("agents.auto_clip.pipeline.PAUSE_FILE", pause):
        results = run_pipeline(dry_run=True)
    assert results == []


def test_run_pipeline_filters_by_resonance_threshold():
    low_candidates = [_candidate(resonance=0.2), _candidate(resonance=0.3)]

    class _FakeAgent:
        def run_sync(self, prompt: str) -> object:
            return SimpleNamespace(output=low_candidates)

    detector = LlmSegmentDetector(agent=_FakeAgent())
    now = datetime.now(UTC)
    ctx = RollingContext(window_start=now - timedelta(minutes=10), window_end=now)

    with patch("agents.auto_clip.pipeline.LlmSegmentDetector", return_value=detector):
        results = run_pipeline(
            dry_run=True,
            context=ctx,
            archive_path=Path("/nonexistent"),
        )
    assert results == []
