"""Tests for the flock-based GPU semaphore."""

import os
import fcntl
import tempfile
from unittest.mock import patch

import pytest

from shared.gpu_semaphore import gpu_slot, _NUM_SLOTS


@pytest.fixture
def tmp_slot_dir(tmp_path):
    """Use a temp directory for slot files instead of /run."""
    slot_dir = tmp_path / "gpu-sem"
    with patch("shared.gpu_semaphore._SLOT_DIR", slot_dir):
        yield slot_dir


class TestGpuSlot:
    def test_acquires_and_releases(self, tmp_slot_dir):
        with gpu_slot():
            # Slot file should exist and be locked
            assert (tmp_slot_dir / "slot.0").exists()

    def test_creates_slot_dir(self, tmp_slot_dir):
        assert not tmp_slot_dir.exists()
        with gpu_slot():
            assert tmp_slot_dir.exists()

    def test_creates_slot_files(self, tmp_slot_dir):
        with gpu_slot():
            for i in range(_NUM_SLOTS):
                assert (tmp_slot_dir / f"slot.{i}").exists()

    def test_multiple_sequential_acquires(self, tmp_slot_dir):
        for _ in range(5):
            with gpu_slot():
                pass

    def test_concurrent_slots_up_to_limit(self, tmp_slot_dir):
        """Two concurrent acquisitions should succeed with 2 slots."""
        import threading

        results = []
        barrier = threading.Barrier(2)

        def worker():
            with gpu_slot():
                barrier.wait(timeout=2)
                results.append("ok")

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(results) == 2

    def test_slot_released_on_exception(self, tmp_slot_dir):
        """Slot should be released even if the body raises."""
        with pytest.raises(ValueError, match="test"):
            with gpu_slot():
                raise ValueError("test")

        # Should be able to acquire again
        with gpu_slot():
            pass

    def test_flock_auto_releases_on_fd_close(self, tmp_slot_dir):
        """Verify the kernel releases flock when fd is closed."""
        # Manually acquire a lock
        with gpu_slot():
            pass  # ensure dir exists

        slot_path = str(tmp_slot_dir / "slot.0")
        fd = os.open(slot_path, os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Lock is held — non-blocking acquire should fail
        fd2 = os.open(slot_path, os.O_CREAT | os.O_RDWR)
        with pytest.raises(BlockingIOError):
            fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.close(fd2)

        # Close original fd — lock should release
        os.close(fd)

        # Now non-blocking acquire should succeed
        fd3 = os.open(slot_path, os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd3, fcntl.LOCK_EX | fcntl.LOCK_NB)  # should not raise
        os.close(fd3)

    def test_env_override_slot_count(self, tmp_slot_dir):
        """GPU_SEM_SLOTS env var should be respected."""
        with patch("shared.gpu_semaphore._NUM_SLOTS", 4):
            with gpu_slot():
                for i in range(4):
                    assert (tmp_slot_dir / f"slot.{i}").exists()
