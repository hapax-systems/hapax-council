"""Tests for provenance_gate module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.auto_clip.provenance_gate import check_clip


def test_gate_passes_with_valid_inputs(tmp_path: Path):
    clip = tmp_path / "test.mp4"
    clip.write_bytes(b"fake video data")

    with (
        patch("agents.auto_clip.provenance_gate.is_feature_active", return_value=True),
        patch(
            "agents.auto_clip.provenance_gate.resolve_policy",
            return_value="always_obscure",
        ),
    ):
        result = check_clip(
            clip_path=clip,
            title="Test Short",
            description="A test clip",
            source_segments=["seg001"],
        )
    assert result.passed
    assert result.reasons == []


def test_gate_fails_on_missing_clip():
    result = check_clip(
        clip_path=Path("/nonexistent/clip.mp4"),
        title="Test",
        description="Test",
        source_segments=["seg001"],
    )
    assert not result.passed
    assert "clip_file_missing" in result.reasons


def test_gate_fails_on_empty_source_segments(tmp_path: Path):
    clip = tmp_path / "test.mp4"
    clip.write_bytes(b"fake")

    with (
        patch("agents.auto_clip.provenance_gate.is_feature_active", return_value=True),
        patch(
            "agents.auto_clip.provenance_gate.resolve_policy",
            return_value="always_obscure",
        ),
    ):
        result = check_clip(
            clip_path=clip,
            title="Test",
            description="Test",
            source_segments=[],
        )
    assert not result.passed
    assert "no_source_segments" in result.reasons


def test_gate_fails_when_face_obscure_disabled(tmp_path: Path):
    clip = tmp_path / "test.mp4"
    clip.write_bytes(b"fake")

    with (
        patch("agents.auto_clip.provenance_gate.is_feature_active", return_value=False),
        patch(
            "agents.auto_clip.provenance_gate.resolve_policy",
            return_value="disabled",
        ),
    ):
        result = check_clip(
            clip_path=clip,
            title="Test",
            description="Test",
            source_segments=["seg001"],
        )
    assert not result.passed
    assert "face_obscure_feature_disabled" in result.reasons
