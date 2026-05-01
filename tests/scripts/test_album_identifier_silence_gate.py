"""Tests for the album-identifier audio-silence gate.

Operator-reported regression 2026-05-01: while no music was playing,
the album-identifier was logging "Identified: track=Saffron
(confidence=0.95)" and writing album-state.json with `playing=true`.
Root cause: the multimodal LLM call asks "what track is playing?" and
the LLM plausibly guesses a track name from the album-cover image
even when the audio clip it received was silent.

Fix (this PR): `_wav_is_silent` checks RMS energy of the captured
WAV; `_capture_audio_mp3` returns None on silence so the LLM call
falls back to vision-only album identification with track=None.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import wave
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "album-identifier.py"


def _load_module() -> ModuleType:
    name = "album_identifier_under_test_silence"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_wav(path: Path, *, sample_value: int, n_samples: int = 44100) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(struct.pack(f"{n_samples}h", *([sample_value] * n_samples)))


def test_silence_gate_flags_pure_zero_wav(tmp_path: Path) -> None:
    """A WAV of all-zero samples is the canonical silence case."""

    mod = _load_module()
    wav = tmp_path / "zero.wav"
    _write_wav(wav, sample_value=0, n_samples=44100)
    assert mod._wav_is_silent(str(wav)) is True


def test_silence_gate_flags_low_amplitude_noise(tmp_path: Path) -> None:
    """RMS below the conservative 50 threshold counts as silent
    (catches sub-quiet ambient pickup that wouldn't fingerprint)."""

    mod = _load_module()
    wav = tmp_path / "very-quiet.wav"
    # Small constant value: RMS = |sample_value|. 30 < 50 threshold.
    _write_wav(wav, sample_value=30, n_samples=44100)
    assert mod._wav_is_silent(str(wav)) is True


def test_silence_gate_passes_typical_ambient_room_noise(tmp_path: Path) -> None:
    """Ambient room noise typically reads RMS 100-500 — the gate must
    pass it through (it's potentially fingerprintable)."""

    mod = _load_module()
    wav = tmp_path / "ambient.wav"
    _write_wav(wav, sample_value=200, n_samples=44100)
    assert mod._wav_is_silent(str(wav)) is False


def test_silence_gate_passes_music_amplitude(tmp_path: Path) -> None:
    """A WAV at music-loudness amplitude (RMS > 1000) must pass through."""

    mod = _load_module()
    wav = tmp_path / "music.wav"
    _write_wav(wav, sample_value=5000, n_samples=44100)
    assert mod._wav_is_silent(str(wav)) is False


def test_silence_gate_fails_closed_on_corrupt_or_missing_wav(tmp_path: Path) -> None:
    """An unreadable / corrupt path must return True (silent) so the
    pipeline doesn't proceed to ask the LLM about a track when the
    audio is suspect."""

    mod = _load_module()
    bogus = tmp_path / "does-not-exist.wav"
    assert mod._wav_is_silent(str(bogus)) is True


def test_silence_gate_handles_empty_wav(tmp_path: Path) -> None:
    """A 0-frame WAV is degenerate; treat as silent."""

    mod = _load_module()
    wav = tmp_path / "empty.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"")
    assert mod._wav_is_silent(str(wav)) is True


def test_silence_gate_threshold_is_tunable(tmp_path: Path) -> None:
    """``rms_threshold`` is exposed as a kwarg so callers can tighten
    or loosen the gate per operator's reported environment."""

    mod = _load_module()
    wav = tmp_path / "borderline.wav"
    _write_wav(wav, sample_value=100, n_samples=44100)
    # Default 50 — passes
    assert mod._wav_is_silent(str(wav)) is False
    # Tightened to 200 — flagged as silent
    assert mod._wav_is_silent(str(wav), rms_threshold=200) is True
