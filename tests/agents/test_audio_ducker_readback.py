"""Focused regression tests for the audio ducker readback contract."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from agents.audio_ducker.__main__ import (
    SOURCE_MAX_STALE_MS,
    DuckState,
    EnvelopeState,
    MixerGainReadback,
    MixerGainWriteResult,
    _parse_mixer_gain_readback,
    _read_aligned,
    fail_open_ducks,
    publish_state,
    refresh_gain_readback,
    source_blockers,
)


class ChunkedStream:
    def __init__(self, data: bytes, *, max_chunk: int) -> None:
        self._data = bytearray(data)
        self._max_chunk = max_chunk
        self.requests: list[int] = []

    def read(self, size: int) -> bytes:
        self.requests.append(size)
        if not self._data:
            return b""
        take = min(size, self._max_chunk, len(self._data))
        chunk = bytes(self._data[:take])
        del self._data[:take]
        return chunk


def test_read_aligned_reads_exact_window_without_rotating_next_frame() -> None:
    stream = ChunkedStream(b"abcdefghijkl", max_chunk=5)

    result = _read_aligned(stream, want_bytes=8, frame_bytes=4)

    assert result == b"abcdefgh"
    assert stream.requests == [8, 3]
    assert stream.read(4) == b"ijkl"


def test_read_aligned_rejects_non_frame_aligned_window() -> None:
    stream = ChunkedStream(b"abcdefghijkl", max_chunk=12)

    with pytest.raises(ValueError, match="multiple of frame_bytes"):
        _read_aligned(stream, want_bytes=10, frame_bytes=4)


def test_parse_mixer_gain_readback_extracts_pipewire_props() -> None:
    output = """
    Object: size 376, type Spa:Pod:Object:Param:Props
      PropInfo 2
        id 2
        type Object
          String "duck_l:Gain 1"
          Float 0.398100
      PropInfo 3
        id 3
        type Object
          String "duck_r:Gain 1"
          Float 0.400000
    """

    readback = _parse_mixer_gain_readback(output)

    assert readback.ok is True
    assert readback.left == 0.3981
    assert readback.right == 0.4
    assert readback.gain == pytest.approx(0.39905)


def test_refresh_gain_readback_flags_command_actual_mismatch() -> None:
    duck = DuckState(node="hapax-music-duck", commanded_gain=0.5, current_gain=0.5)

    error = refresh_gain_readback(
        duck,
        now_s=123.0,
        reader=lambda _node: MixerGainReadback(ok=True, left=1.0, right=1.0),
    )

    assert error is not None
    assert "readback_mismatch" in error
    assert duck.actual_gain == 1.0
    assert duck.last_readback_ts == 123.0


def test_source_blockers_require_fresh_capture_samples() -> None:
    rode = EnvelopeState(name="rode")
    tts = EnvelopeState(name="tts")
    now_ms = 10_000.0

    assert source_blockers(rode, tts, now_ms) == [
        "rode_capture_missing",
        "tts_capture_missing",
    ]

    rode.update(np.zeros(4, dtype=np.float32), now_ms)
    tts.update(np.zeros(4, dtype=np.float32), now_ms)
    assert source_blockers(rode, tts, now_ms + SOURCE_MAX_STALE_MS) == []

    blockers = source_blockers(rode, tts, now_ms + SOURCE_MAX_STALE_MS + 1.0)
    assert blockers == ["rode_capture_stale:501ms", "tts_capture_stale:501ms"]


def test_fail_open_ducks_commands_unity_and_records_reason() -> None:
    music = DuckState(node="hapax-music-duck", current_gain=0.4, commanded_gain=0.4)
    tts = DuckState(node="hapax-tts-duck", current_gain=0.7, commanded_gain=0.7)
    writes: list[tuple[str, float]] = []

    def writer(node: str, gain: float) -> MixerGainWriteResult:
        writes.append((node, gain))
        return MixerGainWriteResult(ok=True)

    fail_open_ducks(
        music,
        tts,
        "rode_capture_stale:700ms",
        now_s=456.0,
        writer=writer,
        reader=lambda _node: MixerGainReadback(ok=True, left=1.0, right=1.0),
    )

    assert writes == [("hapax-music-duck", 1.0), ("hapax-tts-duck", 1.0)]
    assert music.commanded_gain == 1.0
    assert tts.commanded_gain == 1.0
    assert music.actual_gain == 1.0
    assert tts.fail_open_reason == "rode_capture_stale:700ms"


def test_publish_state_distinguishes_commanded_actual_and_freshness(tmp_path: Path) -> None:
    rode = EnvelopeState(name="rode")
    tts = EnvelopeState(name="tts")
    rode.update(np.zeros(4, dtype=np.float32), 1_000.0)
    tts.update(np.zeros(4, dtype=np.float32), 1_000.0)
    music = DuckState(
        node="hapax-music-duck",
        current_gain=0.5,
        target_gain=0.5,
        commanded_gain=0.5,
        actual_gain=1.0,
        actual_left_gain=1.0,
        actual_right_gain=1.0,
    )
    tts_duck = DuckState(node="hapax-tts-duck")
    path = tmp_path / "state.json"

    publish_state(
        rode,
        tts,
        music,
        tts_duck,
        trigger_cause="operator_voice",
        blockers=["music_readback_error:readback_mismatch"],
        now_s=1_800_000_000.0,
        now_ms=1_020.0,
        path=path,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["trigger_cause"] == "operator_voice"
    assert payload["fail_open"] is True
    assert payload["commanded_music_duck_gain"] == 0.5
    assert payload["actual_music_duck_gain"] == 1.0
    assert payload["music_duck_gain"] == 1.0
    assert payload["rode"]["fresh"] is True
    assert payload["rode"]["sample_age_ms"] == 20.0
