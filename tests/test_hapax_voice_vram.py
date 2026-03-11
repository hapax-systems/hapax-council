"""Tests for hapax_voice VRAM coordinator."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from agents.hapax_voice.vram import VRAMLock


def _temp_lock_path() -> Path:
    return Path(tempfile.mktemp(suffix=".lock"))


def test_acquire_and_release() -> None:
    path = _temp_lock_path()
    lock = VRAMLock(path=path)
    assert lock.acquire() is True
    assert path.exists()
    lock.release()
    assert not path.exists()


def test_lock_is_exclusive() -> None:
    path = _temp_lock_path()
    lock1 = VRAMLock(path=path)
    lock2 = VRAMLock(path=path)
    assert lock1.acquire() is True
    # Same PID, but the lock file holds our PID so os.kill(pid, 0) succeeds
    assert lock2.acquire() is False
    lock1.release()


def test_context_manager() -> None:
    path = _temp_lock_path()
    with VRAMLock(path=path) as lock:
        assert path.exists()
        assert int(path.read_text().strip()) == os.getpid()
    assert not path.exists()


def test_stale_lock_broken() -> None:
    path = _temp_lock_path()
    # Write a fake PID that doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("999999999")
    lock = VRAMLock(path=path)
    assert lock.acquire() is True
    lock.release()
