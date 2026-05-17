"""Tests for shared.audio_performance_context."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from shared.audio_performance_context import (
    build_performance_context,
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
