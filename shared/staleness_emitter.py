"""Rate-limited staleness impingement emitter.

Backends call maybe_emit(source) when they detect stale input data.
The emitter returns an Impingement on the first call per source, then
returns None for subsequent calls within the cooldown period.
"""

from __future__ import annotations

import time

from shared.impingement import Impingement, ImpingementType


class StalenessEmitter:
    """Rate-limited staleness impingement emitter."""

    def __init__(self, cooldown_s: float = 60.0) -> None:
        self._cooldown_s = cooldown_s
        self._last_emit: dict[str, float] = {}

    def maybe_emit(self, source: str) -> Impingement | None:
        """Emit a staleness impingement if cooldown has elapsed for this source."""
        now = time.time()
        last = self._last_emit.get(source, 0)
        if now - last < self._cooldown_s:
            return None

        self._last_emit[source] = now
        return Impingement(
            timestamp=now,
            source=f"staleness.{source}",
            type=ImpingementType.ABSOLUTE_THRESHOLD,
            strength=0.4,
            content={"metric": f"{source}_staleness", "value": "stale"},
        )
