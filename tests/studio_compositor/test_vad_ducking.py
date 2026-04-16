"""Tests for VAD-driven auto-ducking."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agents.studio_compositor import vad_ducking
from agents.studio_compositor.vad_ducking import (
    DuckController,
    _read_vad_state,
    publish_vad_state,
)


class TestPublishVadState:
    def test_writes_atomic_snapshot(self, tmp_path):
        target = tmp_path / "voice-state.json"
        with patch.object(vad_ducking, "VOICE_STATE_FILE", target):
            publish_vad_state(True)
        assert target.exists()
        state = json.loads(target.read_text())
        assert state["operator_speech_active"] is True

    def test_overwrites_on_state_change(self, tmp_path):
        target = tmp_path / "voice-state.json"
        with patch.object(vad_ducking, "VOICE_STATE_FILE", target):
            publish_vad_state(True)
            publish_vad_state(False)
        state = json.loads(target.read_text())
        assert state["operator_speech_active"] is False


class TestReadVadState:
    def test_returns_none_when_missing(self, tmp_path):
        target = tmp_path / "voice-state.json"
        with patch.object(vad_ducking, "VOICE_STATE_FILE", target):
            assert _read_vad_state() is None

    def test_returns_none_on_malformed(self, tmp_path):
        target = tmp_path / "voice-state.json"
        target.write_text("not json")
        with patch.object(vad_ducking, "VOICE_STATE_FILE", target):
            assert _read_vad_state() is None

    def test_reads_true_and_false(self, tmp_path):
        target = tmp_path / "voice-state.json"
        with patch.object(vad_ducking, "VOICE_STATE_FILE", target):
            publish_vad_state(True)
            assert _read_vad_state() is True
            publish_vad_state(False)
            assert _read_vad_state() is False


class TestDuckController:
    def _tick_once(self, controller: DuckController) -> None:
        """Invoke one iteration of the controller's loop body."""
        new = _read_vad_state()
        if new is not None and new != controller._last_state:
            if new:
                controller._audio_control.duck()
            else:
                controller._audio_control.restore()
            controller._last_state = new

    def test_ducks_on_first_speech(self, tmp_path):
        target = tmp_path / "voice-state.json"
        audio = MagicMock()
        with patch.object(vad_ducking, "VOICE_STATE_FILE", target):
            publish_vad_state(True)
            controller = DuckController(audio)
            self._tick_once(controller)
        audio.duck.assert_called_once()
        audio.restore.assert_not_called()

    def test_restores_on_silence_after_speech(self, tmp_path):
        target = tmp_path / "voice-state.json"
        audio = MagicMock()
        with patch.object(vad_ducking, "VOICE_STATE_FILE", target):
            publish_vad_state(True)
            controller = DuckController(audio)
            self._tick_once(controller)
            publish_vad_state(False)
            self._tick_once(controller)
        audio.duck.assert_called_once()
        audio.restore.assert_called_once()

    def test_no_duplicate_calls_when_state_unchanged(self, tmp_path):
        target = tmp_path / "voice-state.json"
        audio = MagicMock()
        with patch.object(vad_ducking, "VOICE_STATE_FILE", target):
            publish_vad_state(True)
            controller = DuckController(audio)
            self._tick_once(controller)
            self._tick_once(controller)  # state hasn't changed
            self._tick_once(controller)
        audio.duck.assert_called_once()
