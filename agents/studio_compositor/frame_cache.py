"""Per-camera last-good-frame cache for freeze-frame fallback (A+ Stage 3).

When a camera drops (USB bus-kick, FSM → DEGRADED → OFFLINE), the
fallback pipeline plays a "no signal" card. ATEM / vMix / pro broadcast
switchers instead freeze the last-good frame. This module is the
shared buffer store that makes that work:

- Each camera's producer pipeline installs a pad probe at its
  interpipesink that snapshots one frame every N ticks into this
  cache (``update``), keyed by camera role.
- The fallback pipeline's ``appsrc`` (replacing the previous
  ``videotestsrc``) reads this cache via ``get`` on its timer tick
  and emits the stored NV12 buffer. If no frame has been captured
  yet, ``get`` returns ``None`` and the fallback emits its pre-baked
  black frame instead.

The cache deliberately stores a SINGLE frame per role (no ring
buffer): fallback is a stop-gap, not a replay system. Memory cost:
1280x720 NV12 = 1.4 MiB × 6 cameras = 8.4 MiB total.
"""

from __future__ import annotations

import threading
from typing import NamedTuple


class CachedFrame(NamedTuple):
    data: bytes
    width: int
    height: int
    format: str  # "NV12" | "BGRA"
    sequence: int


_cache: dict[str, CachedFrame] = {}
_sequence_by_role: dict[str, int] = {}
_lock = threading.Lock()


def update(role: str, data: bytes, width: int, height: int, fmt: str = "NV12") -> None:
    """Store the latest good frame for ``role``. Overwrites any prior cache.

    Called from a GStreamer pad-probe on the camera producer's
    interpipesink — every N frames (controlled by the caller's probe
    sampling rate). ``data`` is a raw pixel byte copy; this cache does
    not hold references to GstBuffer memory so the buffer pool is
    free to recycle.
    """
    with _lock:
        sequence = _sequence_by_role.get(role, 0) + 1
        _sequence_by_role[role] = sequence
        _cache[role] = CachedFrame(
            data=bytes(data),
            width=width,
            height=height,
            format=fmt,
            sequence=sequence,
        )


def get(role: str) -> CachedFrame | None:
    """Return the last cached frame for ``role``, or None if never populated."""
    with _lock:
        return _cache.get(role)


def clear(role: str | None = None) -> None:
    """Drop one role's cache (or all if ``role`` is None)."""
    with _lock:
        if role is None:
            _cache.clear()
            _sequence_by_role.clear()
        else:
            _cache.pop(role, None)
            _sequence_by_role.pop(role, None)


def roles() -> list[str]:
    """Return the list of roles with cached frames (snapshot; non-blocking after acquire)."""
    with _lock:
        return list(_cache.keys())


__all__ = ["CachedFrame", "update", "get", "clear", "roles"]
