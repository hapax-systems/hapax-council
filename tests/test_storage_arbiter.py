"""Tests for storage_arbiter.py — audio archive value assessment."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from agents.storage_arbiter import (
    ArbiterReport,
    ArchivedFile,
    compute_composite_score,
    is_protected,
    run_assessment,
    scan_archive,
    write_report,
)


def _make_sidecar(path: Path, **overrides):
    """Write a sidecar markdown file with YAML frontmatter."""
    defaults = {
        "source_file": path.with_suffix(".flac").name,
        "processed_at": datetime.now(tz=UTC).isoformat(),
        "disposition": "archive",
        "value_score": 0.5,
        "dominant_classification": "listening-log",
        "speech_seconds": 30.0,
        "music_seconds": 120.0,
        "silence_seconds": 50.0,
        "segment_count": 3,
        "speaker_count": 1,
        "sample_sessions": 1,
        "vocal_notes": 0,
        "conversations": 0,
        "listening_logs": 2,
    }
    defaults.update(overrides)
    content = f"---\n{yaml.dump(defaults, default_flow_style=False)}---\n\nSidecar.\n"
    path.write_text(content, encoding="utf-8")


def test_scan_archive_empty(tmp_path):
    assert scan_archive(tmp_path) == []


def test_scan_archive_with_files(tmp_path):
    # Create a FLAC + sidecar pair
    flac = tmp_path / "rec-20260308.flac"
    flac.write_bytes(b"fake audio")
    sidecar = tmp_path / "rec-20260308.md"
    _make_sidecar(sidecar)

    files = scan_archive(tmp_path)
    assert len(files) == 1
    assert files[0].filename == "rec-20260308.flac"
    assert files[0].value_score == 0.5


def test_scan_archive_orphaned_sidecar(tmp_path):
    """Sidecar without matching FLAC is ignored."""
    sidecar = tmp_path / "orphan.md"
    _make_sidecar(sidecar)
    assert scan_archive(tmp_path) == []


def test_composite_score_rich_file(tmp_path):
    f = ArchivedFile(
        filename="test.flac",
        archive_path=tmp_path / "test.flac",
        sidecar_path=tmp_path / "test.md",
        value_score=0.8,
        sample_sessions=3,
        listening_logs=2,
        speech_seconds=60,
        music_seconds=120,
        segment_count=5,
        processed_at=datetime.now(tz=UTC).isoformat(),
    )
    score = compute_composite_score(f, [f])
    assert score > 0.5


def test_composite_score_empty_file(tmp_path):
    f = ArchivedFile(
        filename="test.flac",
        archive_path=tmp_path / "test.flac",
        sidecar_path=tmp_path / "test.md",
        processed_at=datetime.now(tz=UTC).isoformat(),
    )
    score = compute_composite_score(f, [f])
    assert score < 0.5


def test_is_protected_with_segments(tmp_path):
    f = ArchivedFile(
        filename="test.flac",
        archive_path=tmp_path / "test.flac",
        sidecar_path=tmp_path / "test.md",
        segment_count=1,
    )
    assert is_protected(f) is True


def test_is_protected_recent_file(tmp_path):
    f = ArchivedFile(
        filename="test.flac",
        archive_path=tmp_path / "test.flac",
        sidecar_path=tmp_path / "test.md",
        segment_count=0,
        processed_at=datetime.now(tz=UTC).isoformat(),
    )
    assert is_protected(f) is True


def test_is_protected_old_empty_file(tmp_path):
    f = ArchivedFile(
        filename="test.flac",
        archive_path=tmp_path / "test.flac",
        sidecar_path=tmp_path / "test.md",
        segment_count=0,
        processed_at="2025-01-01T00:00:00+00:00",
    )
    assert is_protected(f) is False


def test_run_assessment_empty(tmp_path):
    report = run_assessment(tmp_path)
    assert report.total_files == 0


def test_run_assessment_with_files(tmp_path):
    for i in range(3):
        flac = tmp_path / f"rec-{i}.flac"
        flac.write_bytes(b"x" * 1000)
        _make_sidecar(
            tmp_path / f"rec-{i}.md",
            segment_count=i,
            sample_sessions=i,
        )

    report = run_assessment(tmp_path)
    assert report.total_files == 3
    assert report.files_assessed == 3
    assert len(report.top_value_files) <= 5


def test_write_report(tmp_path):
    report = ArbiterReport(
        timestamp=datetime.now(tz=UTC).isoformat(),
        total_files=10,
        total_size_mb=500.0,
        files_assessed=10,
        files_below_threshold=2,
        files_protected=8,
        files_eligible_for_reap=1,
    )

    out = tmp_path / "report.md"
    write_report(report, out)
    assert out.exists()
    content = out.read_text()
    assert "Storage Arbiter Report" in content
    assert "500.0 MB" in content
