"""Shared loop helpers for audio-health daemons."""

from __future__ import annotations

import time
from collections.abc import Callable

DEFAULT_SLEEP_CHUNK_S = 0.5


def interruptible_sleep(
    seconds: float,
    should_shutdown: Callable[[], bool],
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_chunk_s: float = DEFAULT_SLEEP_CHUNK_S,
) -> None:
    """Sleep in bounded chunks so signal handlers can stop daemon loops promptly."""
    remaining = max(0.0, seconds)
    chunk_limit = max(0.001, max_chunk_s)

    while remaining > 0.0 and not should_shutdown():
        chunk = min(chunk_limit, remaining)
        sleep_fn(chunk)
        remaining -= chunk
