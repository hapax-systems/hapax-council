"""Tests for hapax_daimonion VRAM coordinator."""

from __future__ import annotations

import os
from pathlib import Path

from agents.hapax_daimonion.vram import VRAMLock


def _temp_lock_path(tmp_path: Path) -> Path:
    return tmp_path / "vram.lock"


def test_acquire_and_release(tmp_path: Path) -> None:
    path = _temp_lock_path(tmp_path)
    lock = VRAMLock(path=path)
    assert lock.acquire() is True
    assert path.exists()
    lock.release()
    assert not path.exists()


def test_lock_is_exclusive(tmp_path: Path) -> None:
    path = _temp_lock_path(tmp_path)
    lock1 = VRAMLock(path=path)
    lock2 = VRAMLock(path=path)
    assert lock1.acquire() is True
    # Same PID, but the lock file holds our PID so os.kill(pid, 0) succeeds
    assert lock2.acquire() is False
    lock1.release()


def test_context_manager(tmp_path: Path) -> None:
    path = _temp_lock_path(tmp_path)
    with VRAMLock(path=path):
        assert path.exists()
        assert int(path.read_text().strip()) == os.getpid()
    assert not path.exists()


def test_stale_lock_broken(tmp_path: Path) -> None:
    path = _temp_lock_path(tmp_path)
    # Write a fake PID that doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("999999999")
    lock = VRAMLock(path=path)
    assert lock.acquire() is True
    lock.release()
