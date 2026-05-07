"""Tests for ``shared.tmp_wav``.

Three small public functions (``tmp_wav_path``, ``cleanup_stale_wavs``,
``cleanup_all_wavs``) form the leak-prevention contract for temporary
WAV files. The module enforces:

  * Files are created under ``HAPAX_TMP_WAV_DIR`` (not ``/tmp``) so a
    single directory can be swept on startup / periodically.
  * ``cleanup_stale_wavs`` removes files older than ``max_age_s`` and
    returns the count.
  * ``cleanup_all_wavs`` removes every ``*.wav`` in the directory and
    returns the count — used at process startup to clean orphans from
    prior SIGKILL / OOM.
  * Both cleanup helpers are tolerant of OSError (file vanished, etc.)
    so a transient FS hiccup doesn't take down the caller.

These tests pin those invariants in isolation so the module can be
trusted by every transcribe / play_pcm / TTS path that currently
relies on it.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from shared.tmp_wav import cleanup_all_wavs, cleanup_stale_wavs, tmp_wav_path


@pytest.fixture
def isolated_tmp_wav_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``HAPAX_TMP_WAV_DIR`` to a tmp dir for the test."""
    import shared.tmp_wav as mod

    override = tmp_path / "tmp-wav"
    monkeypatch.setattr(mod, "HAPAX_TMP_WAV_DIR", override)
    return override


def test_tmp_wav_path_creates_file_in_managed_dir(isolated_tmp_wav_dir: Path) -> None:
    path = tmp_wav_path()
    try:
        assert path.parent == isolated_tmp_wav_dir
        assert path.exists()
        assert path.suffix == ".wav"
    finally:
        path.unlink(missing_ok=True)


def test_tmp_wav_path_creates_dir_if_missing(isolated_tmp_wav_dir: Path) -> None:
    """``HAPAX_TMP_WAV_DIR`` is created lazily on first call."""
    assert not isolated_tmp_wav_dir.exists()
    path = tmp_wav_path()
    try:
        assert isolated_tmp_wav_dir.exists()
    finally:
        path.unlink(missing_ok=True)


def test_tmp_wav_path_each_call_returns_unique_path(isolated_tmp_wav_dir: Path) -> None:
    paths = [tmp_wav_path() for _ in range(3)]
    try:
        assert len(set(paths)) == 3, f"paths collided: {paths}"
    finally:
        for p in paths:
            p.unlink(missing_ok=True)


def test_cleanup_stale_wavs_removes_old_files_only(isolated_tmp_wav_dir: Path) -> None:
    """A file older than ``max_age_s`` is removed; a fresh file survives."""
    isolated_tmp_wav_dir.mkdir(parents=True, exist_ok=True)
    fresh = isolated_tmp_wav_dir / "fresh.wav"
    stale = isolated_tmp_wav_dir / "stale.wav"
    fresh.write_bytes(b"")
    stale.write_bytes(b"")
    # Backdate the stale file 200s into the past.
    long_ago = time.time() - 200.0
    os.utime(stale, (long_ago, long_ago))

    removed = cleanup_stale_wavs(max_age_s=120.0)

    assert removed == 1
    assert fresh.exists()
    assert not stale.exists()


def test_cleanup_stale_wavs_returns_zero_when_dir_empty(isolated_tmp_wav_dir: Path) -> None:
    assert cleanup_stale_wavs() == 0


def test_cleanup_stale_wavs_ignores_non_wav_files(isolated_tmp_wav_dir: Path) -> None:
    """Files that aren't ``*.wav`` are left alone — the directory is
    private to the wav workflow but a stray ``.tmp`` from another tool
    shouldn't be silently deleted by this module."""
    isolated_tmp_wav_dir.mkdir(parents=True, exist_ok=True)
    foreign = isolated_tmp_wav_dir / "stray.tmp"
    foreign.write_bytes(b"")
    long_ago = time.time() - 600.0
    os.utime(foreign, (long_ago, long_ago))

    removed = cleanup_stale_wavs(max_age_s=60.0)

    assert removed == 0
    assert foreign.exists()


def test_cleanup_all_wavs_removes_every_wav(isolated_tmp_wav_dir: Path) -> None:
    """Used at startup to wipe orphans from prior SIGKILL/OOM."""
    isolated_tmp_wav_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (isolated_tmp_wav_dir / f"f{i}.wav").write_bytes(b"")

    removed = cleanup_all_wavs()

    assert removed == 3
    assert list(isolated_tmp_wav_dir.glob("*.wav")) == []


def test_cleanup_all_wavs_returns_zero_when_dir_empty(isolated_tmp_wav_dir: Path) -> None:
    assert cleanup_all_wavs() == 0


def test_cleanup_all_wavs_ignores_non_wav_files(isolated_tmp_wav_dir: Path) -> None:
    isolated_tmp_wav_dir.mkdir(parents=True, exist_ok=True)
    foreign = isolated_tmp_wav_dir / "stray.tmp"
    foreign.write_bytes(b"")

    removed = cleanup_all_wavs()

    assert removed == 0
    assert foreign.exists()
