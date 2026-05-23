"""Tests for shared.prosody — prosodic feature extraction."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from shared.prosody import (
    ProsodyFeatures,
    extract_prosody,
    read_prosody_block,
    write_prosody,
)


def _make_tone(freq: float = 200.0, duration: float = 2.0, sr: int = 16000) -> np.ndarray:
    """Generate a sine tone for testing pitch extraction."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    return (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _make_word_timestamps(count: int = 10, gap: float = 0.15) -> list[dict]:
    words = []
    t = 0.0
    for i in range(count):
        start = t
        end = t + 0.2
        words.append({"word": f"word{i}", "start": start, "end": end})
        t = end + gap
    return words


class TestExtractProsody:
    def test_basic_extraction(self) -> None:
        audio = _make_tone(200.0, 2.0)
        words = _make_word_timestamps(10)
        features = extract_prosody(audio, 16000, words)
        assert features.word_count == 10
        assert features.duration_s > 0
        assert features.rms_db is not None
        assert features.timestamp > 0

    def test_speaking_rate(self) -> None:
        words = _make_word_timestamps(10)
        audio = np.zeros(16000 * 4, dtype=np.float32)
        features = extract_prosody(audio, 16000, words)
        assert features.speaking_rate_wpm is not None
        assert features.speaking_rate_wpm > 0

    def test_pause_detection(self) -> None:
        words = _make_word_timestamps(5, gap=0.1)
        words.insert(
            3, {"word": "pause", "start": words[2]["end"] + 0.5, "end": words[2]["end"] + 0.7}
        )
        audio = np.zeros(16000 * 3, dtype=np.float32)
        features = extract_prosody(audio, 16000, words)
        assert features.pause_count >= 1
        assert features.pause_total_s > 0

    def test_no_word_timestamps(self) -> None:
        audio = _make_tone(200.0, 1.0)
        features = extract_prosody(audio, 16000, None)
        assert features.speaking_rate_wpm is None
        assert features.word_count == 0
        assert features.rms_db is not None

    def test_pitch_extraction(self) -> None:
        audio = _make_tone(200.0, 2.0)
        features = extract_prosody(audio, 16000)
        if features.f0_mean_hz is not None:
            assert 150 < features.f0_mean_hz < 250

    def test_empty_audio(self) -> None:
        audio = np.zeros(1600, dtype=np.float32)
        features = extract_prosody(audio, 16000)
        assert features.duration_s > 0


class TestWriteAndRead:
    def test_write_read_roundtrip(self, tmp_path: Path) -> None:
        features = ProsodyFeatures(
            f0_mean_hz=180.0,
            f0_std_hz=25.0,
            speaking_rate_wpm=130.0,
            pause_count=2,
            pause_total_s=0.8,
            rms_db=-20.0,
            hnr_db=15.0,
            duration_s=3.5,
            word_count=8,
            timestamp=time.time(),
        )
        out = tmp_path / "prosody.json"
        write_prosody(features, out)
        block = read_prosody_block(out)
        assert "pace:" in block
        assert "pitch:" in block
        assert "energy:" in block
        assert "pauses:" in block
        assert "voice quality:" in block

    def test_stale_returns_empty(self, tmp_path: Path) -> None:
        out = tmp_path / "prosody.json"
        data = {"timestamp": time.time() - 60, "speaking_rate_wpm": 120}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data))
        assert read_prosody_block(out) == ""

    def test_missing_returns_empty(self, tmp_path: Path) -> None:
        assert read_prosody_block(tmp_path / "nope.json") == ""

    def test_pace_labels(self, tmp_path: Path) -> None:
        for wpm, expected in [(80, "slow"), (130, "measured"), (180, "brisk"), (220, "rapid")]:
            out = tmp_path / f"prosody_{wpm}.json"
            data = {"timestamp": time.time(), "speaking_rate_wpm": wpm}
            out.write_text(json.dumps(data))
            block = read_prosody_block(out)
            assert expected in block
