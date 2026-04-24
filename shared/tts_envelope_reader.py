"""Read-side of the TTS envelope SHM ring (GEAL Phase 2, spec §5.1).

The producer lives at
``agents.hapax_daimonion.tts_envelope_publisher.TtsEnvelopePublisher`` —
a lock-free mmap of 256 × 5 f32 slots plus a 4-byte head index. This
reader lets GEAL (and any future consumer) pull the most-recent
window of samples without importing daimonion-side code.

The ring is optional — GEAL must render even when daimonion isn't
running. Methods return empty lists when the file doesn't exist,
is mis-sized, or hasn't been written yet.
"""

from __future__ import annotations

import logging
import mmap
import struct
from pathlib import Path

__all__ = [
    "DEFAULT_ENVELOPE_PATH",
    "FIELDS_PER_SLOT",
    "RING_SLOTS",
    "TtsEnvelopeReader",
]

log = logging.getLogger(__name__)

DEFAULT_ENVELOPE_PATH = Path("/dev/shm/hapax-daimonion/tts-envelope.f32")

RING_SLOTS = 256
FIELDS_PER_SLOT = 5  # rms, centroid, zcr, f0, voicing_prob
_HEADER_SIZE = 4
_F32_BYTES = 4
_SLOT_SIZE = FIELDS_PER_SLOT * _F32_BYTES
_PAYLOAD_SIZE = RING_SLOTS * _SLOT_SIZE
_FILE_SIZE = _HEADER_SIZE + _PAYLOAD_SIZE


class TtsEnvelopeReader:
    """Lazy mmap reader with automatic re-open if the producer restarts.

    The reader opens the file on first :meth:`latest` call, re-opens on
    size changes (daemon restart → file truncate), and never blocks
    the render tick on I/O. If the file is missing, :meth:`latest`
    returns an empty list — callers should treat that as silence.
    """

    def __init__(self, *, path: Path | str = DEFAULT_ENVELOPE_PATH) -> None:
        self._path = Path(path)
        self._mmap: mmap.mmap | None = None
        self._file = None
        self._last_inode: int | None = None

    def latest(self, n: int = 8) -> list[tuple[float, float, float, float, float]]:
        """Return the ``n`` most-recent ring entries (oldest-first).

        Best-effort: silently returns ``[]`` on any I/O failure. ``n``
        is capped at :data:`RING_SLOTS`.
        """
        if n <= 0:
            return []
        n = min(int(n), RING_SLOTS)

        if not self._ensure_open():
            return []
        assert self._mmap is not None

        try:
            head = struct.unpack_from("<I", self._mmap, 0)[0]
        except (struct.error, ValueError):
            return []

        available = min(n, head, RING_SLOTS)
        if available == 0:
            return []

        out: list[tuple[float, float, float, float, float]] = []
        for i in range(available, 0, -1):
            slot = (head - i) % RING_SLOTS
            offset = _HEADER_SIZE + slot * _SLOT_SIZE
            try:
                out.append(struct.unpack_from("<fffff", self._mmap, offset))
            except (struct.error, ValueError):
                break
        return out

    def close(self) -> None:
        if self._mmap is not None:
            try:
                self._mmap.close()
            except (ValueError, OSError):
                pass
            self._mmap = None
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None

    # -- Internals ----------------------------------------------------------

    def _ensure_open(self) -> bool:
        """Open / reopen the mmap as needed. Returns True on success."""
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            # Producer not running — render without envelope.
            self.close()
            return False
        except OSError:
            log.debug("tts envelope stat failed", exc_info=True)
            return False

        if stat.st_size < _FILE_SIZE:
            # File too small (daemon may be mid-truncate). Try again
            # next tick.
            return False

        if self._mmap is None or self._last_inode != stat.st_ino:
            # First open, or the producer restarted and rewrote the
            # file. Close the old mapping and reopen against the new
            # inode.
            self.close()
            try:
                self._file = open(self._path, "rb")
                self._mmap = mmap.mmap(self._file.fileno(), _FILE_SIZE, prot=mmap.PROT_READ)
                self._last_inode = stat.st_ino
            except OSError:
                log.debug("tts envelope mmap open failed", exc_info=True)
                self.close()
                return False
        return True
