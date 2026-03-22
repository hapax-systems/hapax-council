"""Tests for logos/data/studio.py — studio ingestion data collector."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import yaml


def _write_sidecar(path, **overrides):
    defaults = {
        "source_file": path.with_suffix(".flac").name,
        "processed_at": datetime.now(tz=UTC).isoformat(),
        "disposition": "archive",
        "value_score": 0.5,
        "dominant_classification": "listening-log",
        "speech_seconds": 30.0,
        "music_seconds": 120.0,
        "segment_count": 3,
        "sample_sessions": 1,
        "listening_logs": 2,
    }
    defaults.update(overrides)
    content = f"---\n{yaml.dump(defaults, default_flow_style=False)}---\n\nSidecar.\n"
    path.write_text(content, encoding="utf-8")


def test_collect_processor_stats_no_state(tmp_path):
    from logos.data.studio import _collect_processor_stats

    with patch("logos.data.studio.AUDIO_PROCESSOR_CACHE_DIR", tmp_path):
        stats = _collect_processor_stats()
    assert stats.total_processed == 0


def test_collect_processor_stats_with_data(tmp_path):
    from logos.data.studio import _collect_processor_stats

    state = {
        "processed_files": {
            "f1": {
                "filename": "rec-1.flac",
                "processed_at": 1741400000.0,
                "speech_seconds": 3600.0,
                "music_seconds": 1800.0,
                "sample_sessions": 5,
                "vocal_notes": 2,
                "conversations": 1,
                "listening_logs": 3,
            },
            "f2": {
                "filename": "rec-2.flac",
                "processed_at": 1741500000.0,
                "speech_seconds": 1200.0,
                "music_seconds": 600.0,
                "sample_sessions": 1,
                "error": "GPU OOM",
            },
        },
        "last_run": 1741500000.0,
    }
    (tmp_path / "state.json").write_text(json.dumps(state))

    with patch("logos.data.studio.AUDIO_PROCESSOR_CACHE_DIR", tmp_path):
        stats = _collect_processor_stats()

    assert stats.total_processed == 2
    assert stats.total_speech_hours > 0
    assert stats.total_sample_sessions == 6
    assert stats.errors == 1


def test_collect_archive_stats(tmp_path):
    from logos.data.studio import _collect_archive_stats

    # Create 3 FLAC + sidecar pairs
    for i in range(3):
        flac = tmp_path / f"rec-{i}.flac"
        flac.write_bytes(b"x" * 1000)
        sidecar = tmp_path / f"rec-{i}.md"
        score = 0.1 * (i + 1)  # 0.1, 0.2, 0.3
        _write_sidecar(sidecar, value_score=score)

    with patch("logos.data.studio.AUDIO_ARCHIVE_DIR", tmp_path):
        with patch("logos.data.studio.AUDIO_RAW_DIR", tmp_path / "raw"):
            with patch("logos.data.studio.AUDIO_RAG_DIR", tmp_path / "rag"):
                stats, values, recent = _collect_archive_stats()

    assert stats.total_files == 3
    assert values.low == 2  # 0.1, 0.2 are below 0.3; 0.3 is medium
    assert len(recent) == 3


def test_collect_archive_value_distribution(tmp_path):
    from logos.data.studio import _collect_archive_stats

    scores = [0.1, 0.2, 0.5, 0.6, 0.8, 0.9]
    for i, score in enumerate(scores):
        flac = tmp_path / f"rec-{i}.flac"
        flac.write_bytes(b"x" * 100)
        _write_sidecar(tmp_path / f"rec-{i}.md", value_score=score)

    with (
        patch("logos.data.studio.AUDIO_ARCHIVE_DIR", tmp_path),
        patch("logos.data.studio.AUDIO_RAW_DIR", tmp_path / "raw"),
        patch("logos.data.studio.AUDIO_RAG_DIR", tmp_path / "rag"),
    ):
        _, values, _ = _collect_archive_stats()

    assert values.low == 2  # 0.1, 0.2
    assert values.medium == 2  # 0.5, 0.6
    assert values.high == 2  # 0.8, 0.9


def test_collect_arbiter_summary(tmp_path):
    from logos.data.studio import _collect_arbiter_summary

    report = """---
timestamp: "2026-03-15T05:00:00+00:00"
total_files: 50
total_size_mb: 2500.0
files_protected: 45
files_eligible_for_reap: 3
---

# Storage Arbiter Report
"""
    (tmp_path / "storage-arbiter-report.md").write_text(report)

    with patch("logos.data.studio.PROFILES_DIR", tmp_path):
        summary = _collect_arbiter_summary()

    assert summary.total_files == 50
    assert summary.files_protected == 45
    assert summary.files_eligible_for_reap == 3


def test_collect_arbiter_no_report(tmp_path):
    from logos.data.studio import _collect_arbiter_summary

    with patch("logos.data.studio.PROFILES_DIR", tmp_path):
        summary = _collect_arbiter_summary()

    assert summary.total_files == 0


def test_collect_capture_status():
    from logos.data.studio import _collect_capture_status

    mock_result = MagicMock()
    mock_result.stdout = "active\n"

    with patch("subprocess.run", return_value=mock_result):
        status = _collect_capture_status()

    assert status.audio_recorder_active is True


def test_collect_studio_snapshot(tmp_path):
    from logos.data.studio import collect_studio

    with (
        patch("logos.data.studio.AUDIO_PROCESSOR_CACHE_DIR", tmp_path),
        patch("logos.data.studio.AUDIO_ARCHIVE_DIR", tmp_path / "archive"),
        patch("logos.data.studio.AUDIO_RAW_DIR", tmp_path / "raw"),
        patch("logos.data.studio.AUDIO_RAG_DIR", tmp_path / "rag"),
        patch("logos.data.studio.PROFILES_DIR", tmp_path),
        patch("subprocess.run", side_effect=FileNotFoundError),
    ):
        snapshot = collect_studio()

    assert snapshot.processor.total_processed == 0
    assert snapshot.archive.total_files == 0
    assert snapshot.capture.audio_recorder_active is False
