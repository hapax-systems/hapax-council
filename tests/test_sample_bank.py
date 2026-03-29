"""Tests for SampleBank — WAV loading, energy tag mapping, cycling."""

from __future__ import annotations

import struct
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.hapax_daimonion.sample_bank import SampleBank


def _write_wav(path: Path, rate: int = 44100, channels: int = 1, n_frames: int = 100) -> None:
    """Write a minimal valid WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(struct.pack(f"<{n_frames}h", *([1000] * n_frames)))


class TestSampleBank(unittest.TestCase):
    def test_load_from_directory(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _write_wav(base / "vocal_throw" / "high_001.wav")
            _write_wav(base / "vocal_throw" / "medium_001.wav")
            _write_wav(base / "ad_lib" / "low_001.wav")

            bank = SampleBank(base)
            count = bank.load()
            self.assertEqual(count, 3)
            self.assertEqual(bank.sample_count, 3)

    def test_energy_tag_mapping(self):
        self.assertEqual(SampleBank._energy_tag(0.8), "high")
        self.assertEqual(SampleBank._energy_tag(0.5), "medium")
        self.assertEqual(SampleBank._energy_tag(0.1), "low")

    def test_select_by_action_and_energy(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _write_wav(base / "vocal_throw" / "high_001.wav")
            bank = SampleBank(base)
            bank.load()

            entry = bank.select("vocal_throw", 0.8)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.action, "vocal_throw")
            self.assertEqual(entry.energy_tag, "high")

    def test_select_cycling(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _write_wav(base / "ad_lib" / "medium_001.wav")
            _write_wav(base / "ad_lib" / "medium_002.wav")
            bank = SampleBank(base)
            bank.load()

            names = [bank.select("ad_lib", 0.5).name for _ in range(4)]
            # Should cycle: 001, 002, 001, 002
            self.assertEqual(names[0], "medium_001")
            self.assertEqual(names[1], "medium_002")
            self.assertEqual(names[2], "medium_001")

    def test_select_fallback_tag(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _write_wav(base / "vocal_throw" / "low_001.wav")
            bank = SampleBank(base)
            bank.load()

            # Requesting high energy but only low available → falls back
            entry = bank.select("vocal_throw", 0.9)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.energy_tag, "low")

    def test_select_unknown_action_returns_none(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _write_wav(base / "vocal_throw" / "high_001.wav")
            bank = SampleBank(base)
            bank.load()
            self.assertIsNone(bank.select("nonexistent", 0.5))

    def test_missing_dir_returns_zero(self):
        bank = SampleBank(Path("/nonexistent/path"))
        self.assertEqual(bank.load(), 0)
        self.assertEqual(bank.sample_count, 0)


if __name__ == "__main__":
    unittest.main()
