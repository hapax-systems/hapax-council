"""Tests for audio_processor archive sidecar functionality (Batch 3)."""

from __future__ import annotations

from unittest.mock import patch


def test_compute_value_score_sample_sessions():
    """Sample sessions contribute the most to value score."""
    from agents.audio_processor import ProcessedFileInfo, _compute_value_score

    info = ProcessedFileInfo(
        filename="test.flac",
        processed_at=1000.0,
        sample_sessions=3,
        vocal_notes=0,
        conversations=0,
        listening_logs=0,
    )
    score = _compute_value_score(info)
    assert score > 0.5  # Sample sessions are high value


def test_compute_value_score_empty():
    """Empty file gets zero score."""
    from agents.audio_processor import ProcessedFileInfo, _compute_value_score

    info = ProcessedFileInfo(filename="test.flac", processed_at=1000.0)
    score = _compute_value_score(info)
    assert score == 0.0


def test_compute_value_score_clamped():
    """Value score is clamped to 1.0."""
    from agents.audio_processor import ProcessedFileInfo, _compute_value_score

    info = ProcessedFileInfo(
        filename="test.flac",
        processed_at=1000.0,
        sample_sessions=10,
        vocal_notes=5,
        conversations=3,
        listening_logs=4,
        music_seconds=120.0,
    )
    score = _compute_value_score(info)
    assert score == 1.0


def test_write_sidecar(tmp_path):
    """Sidecar is written with correct YAML frontmatter."""
    from agents.audio_processor import ProcessedFileInfo, _write_sidecar

    archive_path = tmp_path / "rec-20260308-143000.flac"
    archive_path.touch()

    info = ProcessedFileInfo(
        filename="rec-20260308-143000.flac",
        processed_at=1741400000.0,
        speech_seconds=120.0,
        music_seconds=300.0,
        silence_seconds=80.0,
        segment_count=5,
        speaker_count=1,
        sample_sessions=2,
        vocal_notes=1,
        conversations=0,
        listening_logs=2,
    )

    sidecar = _write_sidecar(archive_path, info)
    assert sidecar.suffix == ".md"
    assert sidecar.exists()

    content = sidecar.read_text()
    assert "disposition: archive" in content
    assert "value_score:" in content
    assert "dominant_classification: sample-session" in content
    assert "speech_seconds: 120.0" in content
    assert "music_seconds: 300.0" in content


def test_write_sidecar_silence_dominant(tmp_path):
    """Sidecar with no segments classifies as silence."""
    from agents.audio_processor import ProcessedFileInfo, _write_sidecar

    archive_path = tmp_path / "rec-20260308-143000.flac"
    archive_path.touch()

    info = ProcessedFileInfo(
        filename="rec-20260308-143000.flac",
        processed_at=1741400000.0,
        silence_seconds=500.0,
    )

    sidecar = _write_sidecar(archive_path, info)
    content = sidecar.read_text()
    assert "dominant_classification: silence" in content


def test_archive_file_moves_and_writes_sidecar(tmp_path):
    """archive_file moves FLAC and writes sidecar."""
    from agents.audio_processor import ProcessedFileInfo, _archive_file

    raw = tmp_path / "raw"
    raw.mkdir()
    archive = tmp_path / "archive"

    flac = raw / "rec-20260308-143000.flac"
    flac.write_bytes(b"fake audio data")

    info = ProcessedFileInfo(
        filename="rec-20260308-143000.flac",
        processed_at=1741400000.0,
        speech_seconds=60.0,
        music_seconds=200.0,
        sample_sessions=1,
    )

    with patch("agents.audio_processor.ARCHIVE_DIR", archive):
        result = _archive_file(flac, info)

    assert result is not None
    assert result.exists()
    assert not flac.exists()  # Original moved
    assert (archive / "rec-20260308-143000.md").exists()  # Sidecar written
