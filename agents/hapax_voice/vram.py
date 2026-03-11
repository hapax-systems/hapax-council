"""VRAM lockfile coordination with audio processor."""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_LOCK_PATH = Path.home() / ".cache" / "hapax-voice" / "vram.lock"


class VRAMLock:
    """File-based VRAM lock to coordinate GPU access.

    Stale locks (from dead processes) are automatically broken.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else DEFAULT_LOCK_PATH

    def acquire(self) -> bool:
        """Acquire the VRAM lock. Returns True on success, False if held."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            log.debug("Acquired VRAM lock (PID %d)", os.getpid())
            return True
        except FileExistsError:
            # Lock file exists — check if holder is alive
            try:
                pid = int(self.path.read_text().strip())
                os.kill(pid, 0)
                log.debug("Lock held by PID %d (alive)", pid)
                return False
            except PermissionError:
                # Process exists but owned by different user — treat as held
                log.debug("Lock held by PID %d (alive, different user)", pid)
                return False
            except (ValueError, ProcessLookupError, OSError):
                log.info("Breaking stale lock at %s", self.path)
                self.path.unlink(missing_ok=True)
                # Retry once after breaking stale lock
                return self._try_create_lock()

    def _try_create_lock(self) -> bool:
        """Attempt atomic lock file creation."""
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            log.debug("Acquired VRAM lock after breaking stale (PID %d)", os.getpid())
            return True
        except FileExistsError:
            log.debug("Lock acquired by another process during stale break")
            return False

    def release(self) -> None:
        """Release the VRAM lock."""
        if self.path.exists():
            self.path.unlink()
            log.debug("Released VRAM lock")

    def __enter__(self) -> VRAMLock:
        if not self.acquire():
            raise RuntimeError("Could not acquire VRAM lock")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        self.release()
