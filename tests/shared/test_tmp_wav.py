"""Tests for shared.tmp_wav.

84-LOC managed temporary WAV file creation with leak prevention.
Untested before this commit. Tests monkeypatch
``HAPAX_TMP_WAV_DIR`` so the operator's real
~/.cache/hapax/tmp-wav directory is never read or mutated.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from shared import tmp_wav


@pytest.fixture
def fake_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    target = tmp_path / "tmp-wav"
    monkeypatch.setattr(tmp_wav, "HAPAX_TMP_WAV_DIR", target)
    return target


# ── tmp_wav_path ───────────────────────────────────────────────────


class TestTmpWavPath:
    def test_creates_directory_if_missing(self, fake_dir: Path) -> None:
        assert not fake_dir.exists()
        tmp_wav.tmp_wav_path()
        assert fake_dir.is_dir()

    def test_returns_path_in_managed_dir(self, fake_dir: Path) -> None:
        path = tmp_wav.tmp_wav_path()
        assert path.parent == fake_dir
        assert path.suffix == ".wav"

    def test_each_call_returns_unique_path(self, fake_dir: Path) -> None:
        a = tmp_wav.tmp_wav_path()
        b = tmp_wav.tmp_wav_path()
        c = tmp_wav.tmp_wav_path()
        assert {a, b, c} == {a, b, c}  # all distinct
        assert len({a, b, c}) == 3

    def test_path_exists_after_call(self, fake_dir: Path) -> None:
        """mkstemp creates the file — caller is responsible for unlinking."""
        path = tmp_wav.tmp_wav_path()
        assert path.exists()
        assert path.is_file()


# ── cleanup_stale_wavs ─────────────────────────────────────────────


class TestCleanupStaleWavs:
    def test_no_files_returns_zero(self, fake_dir: Path) -> None:
        fake_dir.mkdir(parents=True)
        assert tmp_wav.cleanup_stale_wavs() == 0

    def test_fresh_files_kept(self, fake_dir: Path) -> None:
        fake_dir.mkdir(parents=True)
        fresh = fake_dir / "fresh.wav"
        fresh.write_bytes(b"")
        # Just-now mtime → not stale
        assert tmp_wav.cleanup_stale_wavs(max_age_s=120) == 0
        assert fresh.exists()

    def test_old_files_removed(self, fake_dir: Path) -> None:
        fake_dir.mkdir(parents=True)
        old = fake_dir / "old.wav"
        old.write_bytes(b"")
        # Backdate 5 minutes
        old_ts = time.time() - 300
        os.utime(old, (old_ts, old_ts))
        removed = tmp_wav.cleanup_stale_wavs(max_age_s=120)
        assert removed == 1
        assert not old.exists()

    def test_only_wav_files_swept(self, fake_dir: Path) -> None:
        """Non-.wav files in the directory are not touched."""
        fake_dir.mkdir(parents=True)
        wav = fake_dir / "x.wav"
        other = fake_dir / "y.txt"
        wav.write_bytes(b"")
        other.write_bytes(b"")
        old_ts = time.time() - 1000
        os.utime(wav, (old_ts, old_ts))
        os.utime(other, (old_ts, old_ts))
        tmp_wav.cleanup_stale_wavs(max_age_s=120)
        assert not wav.exists()
        assert other.exists()

    def test_default_max_age(self, fake_dir: Path) -> None:
        """Default _MAX_AGE_S is 120 seconds per docstring."""
        fake_dir.mkdir(parents=True)
        f = fake_dir / "borderline.wav"
        f.write_bytes(b"")
        old_ts = time.time() - 60  # 60s old, well under 120
        os.utime(f, (old_ts, old_ts))
        # Default invocation should NOT remove it
        assert tmp_wav.cleanup_stale_wavs() == 0


# ── cleanup_all_wavs ──────────────────────────────────────────────


class TestCleanupAllWavs:
    def test_empty_dir_returns_zero(self, fake_dir: Path) -> None:
        fake_dir.mkdir(parents=True)
        assert tmp_wav.cleanup_all_wavs() == 0

    def test_removes_every_wav_regardless_of_age(self, fake_dir: Path) -> None:
        fake_dir.mkdir(parents=True)
        # Mix of fresh and aged files
        for name in ["a.wav", "b.wav", "c.wav"]:
            (fake_dir / name).write_bytes(b"")
        # Make one fresh, one aged, one in-between
        os.utime(fake_dir / "b.wav", (time.time() - 1000, time.time() - 1000))
        removed = tmp_wav.cleanup_all_wavs()
        assert removed == 3
        assert list(fake_dir.glob("*.wav")) == []

    def test_non_wav_files_kept(self, fake_dir: Path) -> None:
        """Only .wav files are removed; sibling files survive."""
        fake_dir.mkdir(parents=True)
        (fake_dir / "x.wav").write_bytes(b"")
        (fake_dir / "y.txt").write_bytes(b"")
        tmp_wav.cleanup_all_wavs()
        assert not (fake_dir / "x.wav").exists()
        assert (fake_dir / "y.txt").exists()
