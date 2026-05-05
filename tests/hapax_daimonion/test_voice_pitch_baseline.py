"""Tests for operator voice pitch baseline publishing and reading."""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from agents.hapax_daimonion.voice_pitch_baseline import (
    STALE_S,
    operator_voice_pitch_is_elevated,
    publish_operator_voice_pitch_sample,
)


def _sine_pcm(freq_hz: float, *, sample_rate_hz: int = 16000, duration_s: float = 0.2) -> bytes:
    frames = int(sample_rate_hz * duration_s)
    out = bytearray()
    for i in range(frames):
        sample = int(0.5 * 32767.0 * math.sin(2.0 * math.pi * freq_hz * i / sample_rate_hz))
        out.extend(struct.pack("<h", sample))
    return bytes(out)


def test_missing_pitch_state_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "operator-voice-pitch.json"
    assert operator_voice_pitch_is_elevated(path=path, now=1000.0) is None


def test_non_operator_speech_does_not_publish(tmp_path: Path) -> None:
    path = tmp_path / "operator-voice-pitch.json"
    written = publish_operator_voice_pitch_sample(
        _sine_pcm(220.0),
        path=path,
        now=1000.0,
        operator_speech=False,
    )
    assert written is False
    assert not path.exists()


def test_quiet_frame_does_not_publish(tmp_path: Path) -> None:
    path = tmp_path / "operator-voice-pitch.json"
    written = publish_operator_voice_pitch_sample(
        b"\x00\x00" * 3200,
        path=path,
        now=1000.0,
        min_interval_s=0.0,
    )
    assert written is False
    assert not path.exists()


def test_pitch_baseline_returns_false_then_true(tmp_path: Path) -> None:
    path = tmp_path / "operator-voice-pitch.json"

    for i in range(5):
        assert publish_operator_voice_pitch_sample(
            _sine_pcm(220.0),
            path=path,
            now=1000.0 + i,
            min_interval_s=0.0,
        )

    assert operator_voice_pitch_is_elevated(path=path, now=1005.0) is False

    assert publish_operator_voice_pitch_sample(
        _sine_pcm(300.0),
        path=path,
        now=1006.0,
        min_interval_s=0.0,
    )
    assert operator_voice_pitch_is_elevated(path=path, now=1006.0) is True


def test_stale_pitch_state_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "operator-voice-pitch.json"
    for i in range(5):
        publish_operator_voice_pitch_sample(
            _sine_pcm(220.0),
            path=path,
            now=1000.0 + i,
            min_interval_s=0.0,
        )

    assert operator_voice_pitch_is_elevated(path=path, now=1004.0 + STALE_S + 1.0) is None


def test_pitch_state_contains_numeric_features_only(tmp_path: Path) -> None:
    path = tmp_path / "operator-voice-pitch.json"
    publish_operator_voice_pitch_sample(
        _sine_pcm(220.0),
        path=path,
        now=1000.0,
        min_interval_s=0.0,
    )

    payload = json.loads(path.read_text())
    assert payload["current"]["pitch_hz"] > 0
    serialized = json.dumps(payload)
    assert "transcript" not in serialized
    assert "pcm" not in serialized
    assert "audio" not in serialized
