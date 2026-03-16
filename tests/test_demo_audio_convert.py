"""Tests for WAV-to-MP3 audio conversion."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

try:
    import imageio_ffmpeg

    _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    import subprocess as _sp

    _r = _sp.run([_ffmpeg_exe, "-encoders"], capture_output=True, text=True)
    _HAS_FFMPEG = bool(_ffmpeg_exe) and "libmp3lame" in _r.stdout
except (ModuleNotFoundError, RuntimeError):
    _HAS_FFMPEG = False
pytestmark = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg with MP3 encoding not available")

from agents.demo_pipeline.audio_convert import (  # noqa: E402
    convert_all_wav_to_mp3,
    get_ffmpeg_path,
    wav_to_mp3,
)


def _create_test_wav(path: Path, duration_s: float = 0.5, sample_rate: int = 44100) -> None:
    """Create a minimal WAV file with a sine-ish tone."""
    n_frames = int(sample_rate * duration_s)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # Simple ascending ramp as audio data (not silence, so MP3 encoder has something to work with)
        frames = b"".join(struct.pack("<h", (i * 37) % 32768 - 16384) for i in range(n_frames))
        wf.writeframes(frames)


def test_get_ffmpeg_path():
    """get_ffmpeg_path returns a valid file path."""
    ffmpeg = get_ffmpeg_path()
    assert ffmpeg
    assert Path(ffmpeg).exists()


def test_wav_to_mp3(tmp_path: Path):
    """wav_to_mp3 converts a WAV file and produces a smaller MP3."""
    wav_file = tmp_path / "test.wav"
    _create_test_wav(wav_file)

    mp3_file = wav_to_mp3(wav_file)

    assert mp3_file.exists()
    assert mp3_file.suffix == ".mp3"
    assert mp3_file.stat().st_size > 0
    assert mp3_file.stat().st_size < wav_file.stat().st_size


def test_wav_to_mp3_explicit_path(tmp_path: Path):
    """wav_to_mp3 writes to an explicitly provided mp3_path."""
    wav_file = tmp_path / "input.wav"
    _create_test_wav(wav_file)
    mp3_file = tmp_path / "subdir" / "output.mp3"
    mp3_file.parent.mkdir()

    result = wav_to_mp3(wav_file, mp3_path=mp3_file)

    assert result == mp3_file
    assert mp3_file.exists()


def test_convert_all_wav_to_mp3(tmp_path: Path):
    """convert_all_wav_to_mp3 batch-converts all WAV files in a directory."""
    names = ["clip_a", "clip_b", "clip_c"]
    for name in names:
        _create_test_wav(tmp_path / f"{name}.wav")

    results = convert_all_wav_to_mp3(tmp_path)

    assert set(results.keys()) == set(names)
    for stem, mp3_path in results.items():
        assert mp3_path.exists()
        assert mp3_path.suffix == ".mp3"
        assert mp3_path.stem == stem
