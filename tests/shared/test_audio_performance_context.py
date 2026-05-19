"""Tests for shared.audio_performance_context."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from shared.audio_performance_context import (
    AudioPerformanceContext,
    build_performance_context,
    build_performance_context_full,
    read_audio_performance_mode,
)


def test_idle_when_no_impingements(tmp_path: Path) -> None:
    with patch("shared.audio_performance_context.IMPINGEMENTS_PATH", tmp_path / "missing.jsonl"):
        assert read_audio_performance_mode() == "idle"


def test_active_performance_on_vinyl(tmp_path: Path) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    imp = {
        "id": "test",
        "timestamp": time.time(),
        "source": "audio.vinyl_spinning",
        "content": {"to_state": "ASSERTED"},
    }
    imp_file.write_text(json.dumps(imp) + "\n")
    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context._read_voice_active", return_value=False),
    ):
        assert read_audio_performance_mode() == "active_performance"


def test_passive_music_on_yamnet(tmp_path: Path) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    imp = {
        "id": "test",
        "timestamp": time.time(),
        "source": "audio.music_playing",
        "content": {"to_state": "ASSERTED"},
    }
    imp_file.write_text(json.dumps(imp) + "\n")
    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context._read_voice_active", return_value=False),
    ):
        assert read_audio_performance_mode() == "passive_music"


def test_speaking_overrides_performance(tmp_path: Path) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    imp = {
        "id": "test",
        "timestamp": time.time(),
        "source": "audio.vinyl_spinning",
        "content": {"to_state": "ASSERTED"},
    }
    imp_file.write_text(json.dumps(imp) + "\n")
    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context._read_voice_active", return_value=True),
    ):
        assert read_audio_performance_mode() == "speaking"


def test_build_performance_context_returns_dict() -> None:
    with patch("shared.audio_performance_context.read_audio_performance_mode", return_value="idle"):
        ctx = build_performance_context()
        assert ctx == {"audio_performance_mode": "idle"}


def test_pydantic_model_defaults() -> None:
    ctx = AudioPerformanceContext()
    assert ctx.mode == "idle"
    assert ctx.confidence == 0.5
    assert ctx.recruitment_scale == 1.0


def test_pydantic_model_active_performance() -> None:
    ctx = AudioPerformanceContext(
        mode="active_performance",
        confidence=0.9,
        recruitment_scale=1.3,
    )
    assert ctx.mode == "active_performance"
    assert ctx.confidence == 0.9
    assert ctx.recruitment_scale == 1.3


def test_build_full_context_from_impingements() -> None:
    with (
        patch("shared.audio_performance_context._try_read_shm_snapshot", return_value=None),
        patch(
            "shared.audio_performance_context.read_audio_performance_mode",
            return_value="active_performance",
        ),
    ):
        ctx = build_performance_context_full()
        assert isinstance(ctx, AudioPerformanceContext)
        assert ctx.mode == "active_performance"
        assert ctx.confidence == 0.6
        assert ctx.recruitment_scale == 1.3


def test_build_full_context_from_shm_snapshot() -> None:
    snapshot = AudioPerformanceContext(
        mode="speaking",
        confidence=0.95,
        recruitment_scale=0.8,
    )
    with patch("shared.audio_performance_context._try_read_shm_snapshot", return_value=snapshot):
        ctx = build_performance_context_full()
        assert ctx.mode == "speaking"
        assert ctx.confidence == 0.95
        assert ctx.recruitment_scale == 0.8


def test_shm_snapshot_fast_path(tmp_path: Path) -> None:
    snapshot_file = tmp_path / "performance-context.json"
    data = {
        "mode": "passive_music",
        "confidence": 0.85,
        "recruitment_scale": 1.1,
        "timestamp": time.time(),
    }
    snapshot_file.write_text(json.dumps(data))
    with patch("shared.audio_performance_context.PERFORMANCE_CONTEXT_PATH", snapshot_file):
        ctx = build_performance_context()
        assert ctx == {"audio_performance_mode": "passive_music"}


def test_stale_shm_snapshot_falls_back(tmp_path: Path) -> None:
    snapshot_file = tmp_path / "performance-context.json"
    data = {
        "mode": "active_performance",
        "confidence": 0.9,
        "recruitment_scale": 1.3,
        "timestamp": time.time() - 120.0,  # stale
    }
    snapshot_file.write_text(json.dumps(data))
    with (
        patch("shared.audio_performance_context.PERFORMANCE_CONTEXT_PATH", snapshot_file),
        patch("shared.audio_performance_context.read_audio_performance_mode", return_value="idle"),
    ):
        ctx = build_performance_context()
        assert ctx == {"audio_performance_mode": "idle"}


def test_mixer_active_is_active_performance(tmp_path: Path) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    imp = {
        "id": "test",
        "timestamp": time.time(),
        "source": "audio.mixer_input",
        "content": {"to_state": "ACTIVE"},
    }
    imp_file.write_text(json.dumps(imp) + "\n")
    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context._read_voice_active", return_value=False),
    ):
        assert read_audio_performance_mode() == "active_performance"
