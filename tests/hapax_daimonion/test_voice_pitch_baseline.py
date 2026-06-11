"""Tests for operator voice pitch baseline publishing and reading."""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import TYPE_CHECKING

from agents.hapax_daimonion import voice_pitch_baseline

if TYPE_CHECKING:
    import pytest
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


def _count_state_reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Wrap _read_state with a counter; returns a single-element list."""
    reads = [0]
    orig = voice_pitch_baseline._read_state

    def counting(path: Path) -> dict[str, object] | None:
        reads[0] += 1
        return orig(path)

    monkeypatch.setattr(voice_pitch_baseline, "_read_state", counting)
    return reads


def test_throttled_call_does_no_file_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hot path (one call per 32ms VAD chunk) must interval-gate
    BEFORE any state-file read — per-chunk JSON parse of the SHM file
    is what starved the audio loop below real-time."""
    path = tmp_path / "operator-voice-pitch.json"
    assert publish_operator_voice_pitch_sample(_sine_pcm(220.0), path=path, now=1000.0)

    reads = _count_state_reads(monkeypatch)
    written = publish_operator_voice_pitch_sample(
        _sine_pcm(220.0), path=path, now=1000.2
    )
    assert written is False  # inside MIN_INTERVAL_S
    assert reads[0] == 0


def test_warm_cache_publishes_without_rereading_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "operator-voice-pitch.json"
    assert publish_operator_voice_pitch_sample(_sine_pcm(220.0), path=path, now=1000.0)

    reads = _count_state_reads(monkeypatch)
    assert publish_operator_voice_pitch_sample(_sine_pcm(220.0), path=path, now=1001.0)
    assert reads[0] == 0

    payload = json.loads(path.read_text())
    assert payload["window_30m"]["readings"] == 2


def test_cold_cache_warms_from_existing_state_file(tmp_path: Path) -> None:
    """Restart continuity: a fresh process merges with samples persisted
    by the previous run instead of restarting the baseline."""
    path = tmp_path / "operator-voice-pitch.json"
    for i in range(5):
        publish_operator_voice_pitch_sample(
            _sine_pcm(220.0), path=path, now=1000.0 + i, min_interval_s=0.0
        )

    voice_pitch_baseline._reset_state_cache()

    assert publish_operator_voice_pitch_sample(_sine_pcm(300.0), path=path, now=1006.0)
    # 6 readings only if the 5 persisted samples survived the cache reset
    payload = json.loads(path.read_text())
    assert payload["window_30m"]["readings"] == 6
    assert operator_voice_pitch_is_elevated(path=path, now=1006.0) is True


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
