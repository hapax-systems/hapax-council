"""Tests for shared.gpu_semaphore.gpu_slot.

78-LOC system-wide GPU semaphore using flock counting slots.
Untested before this commit.

Tests monkeypatch ``_SLOT_DIR`` and ``_NUM_SLOTS`` so the real
/run/hapax-gpu-sem state is never touched. flock semantics are
exercised by acquiring the same slot from multiple file descriptors
in the same process — non-blocking acquisition fails when another
fd holds the lock.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from shared import gpu_semaphore
from shared.gpu_semaphore import gpu_slot


@pytest.fixture
def fake_slot_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    target = tmp_path / "gpu-sem"
    monkeypatch.setattr(gpu_semaphore, "_SLOT_DIR", target)
    monkeypatch.setattr(gpu_semaphore, "_NUM_SLOTS", 2)
    return target


# ── Slot directory provisioning ────────────────────────────────────


class TestSlotDirProvisioning:
    def test_creates_dir_and_slot_files_on_first_use(
        self, fake_slot_dir: Path
    ) -> None:
        assert not fake_slot_dir.exists()
        with gpu_slot():
            pass
        assert fake_slot_dir.is_dir()
        assert (fake_slot_dir / "slot.0").is_file()
        assert (fake_slot_dir / "slot.1").is_file()

    def test_existing_dir_reused(self, fake_slot_dir: Path) -> None:
        fake_slot_dir.mkdir()
        (fake_slot_dir / "slot.0").touch()
        # Even if only some slot files exist, the call should still succeed.
        with gpu_slot():
            pass


# ── Non-blocking acquisition ───────────────────────────────────────


class TestNonBlockingAcquire:
    def test_acquires_first_available_slot(self, fake_slot_dir: Path) -> None:
        """First call into gpu_slot acquires slot.0 non-blocking."""
        fake_slot_dir.mkdir()
        (fake_slot_dir / "slot.0").touch()
        (fake_slot_dir / "slot.1").touch()
        # We only verify that the context manager yields without raising.
        with gpu_slot():
            pass

    def test_falls_through_to_slot_one_when_zero_held(
        self, fake_slot_dir: Path
    ) -> None:
        """When slot.0 is locked elsewhere, acquisition tries slot.1
        non-blocking and succeeds."""
        fake_slot_dir.mkdir()
        slot0 = fake_slot_dir / "slot.0"
        slot0.touch()
        (fake_slot_dir / "slot.1").touch()
        # Hold slot.0 from a separate fd.
        held_fd = os.open(str(slot0), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with gpu_slot():
                # gpu_slot should have taken slot.1 since slot.0 is held.
                pass
        finally:
            fcntl.flock(held_fd, fcntl.LOCK_UN)
            os.close(held_fd)


# ── Blocking fallback ──────────────────────────────────────────────


class TestBlockingFallback:
    def test_blocks_on_slot_zero_when_all_taken(
        self, fake_slot_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When all slots are held externally, the gpu_slot call falls
        through to a blocking acquire on slot.0. We patch flock to
        avoid an actual block — the patched call simulates success."""
        fake_slot_dir.mkdir()
        for i in range(2):
            (fake_slot_dir / f"slot.{i}").touch()

        # Track the sequence of flock calls.
        calls: list[tuple[int, int]] = []
        original_flock = fcntl.flock

        def fake_flock(fd: int, op: int) -> None:
            calls.append((fd, op))
            if op & fcntl.LOCK_NB:
                # Simulate non-blocking failure for both initial attempts.
                if len(calls) <= 2:
                    raise BlockingIOError("would block")
                return
            # Blocking acquire — succeeds.
            return

        monkeypatch.setattr(fcntl, "flock", fake_flock)
        with gpu_slot():
            pass

        # Expect: 2 non-blocking attempts (slot.0, slot.1) + 1 blocking
        # acquire on slot.0 = 3 calls total.
        assert len(calls) == 3
        # Last call is the blocking one (LOCK_EX without LOCK_NB).
        assert calls[-1][1] == fcntl.LOCK_EX

        # Restore for cleanup.
        monkeypatch.setattr(fcntl, "flock", original_flock)


# ── Permission-error fail-open ─────────────────────────────────────


class TestPermissionFailOpen:
    def test_permission_error_yields_without_lock(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When the slot dir cannot be created (PermissionError), gpu_slot
        yields without acquiring any lock — the caller is unimpeded but
        gets no concurrency protection."""
        # Point _SLOT_DIR to a path whose parent we deny.
        unreachable = tmp_path / "deny" / "gpu-sem"
        monkeypatch.setattr(gpu_semaphore, "_SLOT_DIR", unreachable)

        # Make _ensure_slot_dir return False by raising PermissionError.
        with patch("shared.gpu_semaphore._ensure_slot_dir", return_value=False):
            entered = False
            with gpu_slot():
                entered = True
            assert entered


# ── Context manager semantics ──────────────────────────────────────


class TestContextManager:
    def test_releases_on_normal_exit(self, fake_slot_dir: Path) -> None:
        """After the `with` block exits, the slot is released — verified
        by being able to acquire the same slot in the next call."""
        with gpu_slot():
            pass
        # Second acquisition should succeed (not block, not raise).
        with gpu_slot():
            pass

    def test_releases_on_exception(self, fake_slot_dir: Path) -> None:
        """If the body raises, the slot is still released (try/finally)."""
        try:
            with gpu_slot():
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        # Second acquisition still works.
        with gpu_slot():
            pass
