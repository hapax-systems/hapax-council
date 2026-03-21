"""System-wide GPU semaphore using flock-based counting slots.

Prevents concurrent embedding calls from saturating GPU VRAM. Uses N slot
files in /run/hapax-gpu-sem/; the kernel guarantees automatic release on
process crash or exit. Overhead: <5 microseconds per acquire/release.

Slot files live on tmpfs (/run), so they survive no reboot and are cleaned
on boot. The directory is created lazily on first use.
"""

from __future__ import annotations

import fcntl
import logging
import os
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

_SLOT_DIR = Path(os.environ.get("GPU_SEM_DIR", "/run/hapax-gpu-sem"))
_NUM_SLOTS = int(os.environ.get("GPU_SEM_SLOTS", "2"))


def _ensure_slot_dir() -> bool:
    """Create slot directory if it doesn't exist. Returns False if unavailable."""
    try:
        if not _SLOT_DIR.exists():
            _SLOT_DIR.mkdir(parents=True, exist_ok=True)
            for i in range(_NUM_SLOTS):
                (_SLOT_DIR / f"slot.{i}").touch()
        return True
    except PermissionError:
        return False


@contextmanager
def gpu_slot():
    """Acquire a GPU embedding slot, yield, then release.

    Tries each slot with non-blocking flock. If all slots are taken,
    blocks on slot 0 until it becomes available. The kernel releases
    the lock automatically if the process crashes.

    Usage::

        with gpu_slot():
            result = ollama_client.embed(model=model, input=text)
    """
    if not _ensure_slot_dir():
        log.debug("gpu_slot: slot dir unavailable, running without GPU semaphore")
        yield
        return
    fd = -1
    try:
        # Try non-blocking acquisition across all slots
        for i in range(_NUM_SLOTS):
            slot_path = _SLOT_DIR / f"slot.{i}"
            fd = os.open(str(slot_path), os.O_CREAT | os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                log.debug("gpu_slot: acquired slot %d (non-blocking)", i)
                yield
                return
            except BlockingIOError:
                os.close(fd)
                fd = -1

        # All slots taken — block on slot 0
        slot_path = _SLOT_DIR / "slot.0"
        fd = os.open(str(slot_path), os.O_CREAT | os.O_RDWR)
        log.debug("gpu_slot: all %d slots taken, blocking on slot 0", _NUM_SLOTS)
        fcntl.flock(fd, fcntl.LOCK_EX)
        log.debug("gpu_slot: acquired slot 0 (after blocking)")
        yield
    finally:
        if fd >= 0:
            os.close(fd)
