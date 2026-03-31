"""Perception ring buffer — temporal depth for ambient perception.

Replaces flat snapshots with a rolling window of perception state,
enabling retention (fading past), impression (present), and protention
(anticipated future). Core data structure for WS1 temporal thickness.

Used by: _perception_state_writer (push), visual_layer_aggregator (read),
temporal_bands (format for LLM context).
"""

from __future__ import annotations

import time
from collections import deque


class PerceptionRing:
    """Rolling buffer of perception snapshots with time-windowed accessors.

    ~50s of history at 2.5s ticks (maxlen=20). Thread-safe for single-writer
    single-reader (perception daemon writes, aggregator reads).
    """

    def __init__(self, maxlen: int = 20) -> None:
        self._buffer: deque[dict[str, object]] = deque(maxlen=maxlen)

    def push(self, snapshot: dict[str, object]) -> None:
        """Add a timestamped snapshot. Normalizes timestamp to 'ts' key."""
        if "ts" not in snapshot:
            # Accept "timestamp" (from perception state writer) or generate
            ts = snapshot.get("timestamp", time.time())
            snapshot = {**snapshot, "ts": ts}
        self._buffer.append(snapshot)

    def current(self) -> dict[str, object] | None:
        """Most recent snapshot, or None if empty."""
        return self._buffer[-1] if self._buffer else None

    def window(self, seconds: float) -> list[dict[str, object]]:
        """All snapshots within the last `seconds` from the most recent."""
        if not self._buffer:
            return []
        cutoff = float(self._buffer[-1]["ts"]) - seconds
        return [s for s in self._buffer if float(s["ts"]) >= cutoff]

    def delta(self, key: str) -> float:
        """Change in `key` between the two most recent snapshots. 0.0 if unavailable."""
        if len(self._buffer) < 2:
            return 0.0
        curr = self._buffer[-1].get(key)
        prev = self._buffer[-2].get(key)
        if curr is None or prev is None:
            return 0.0
        try:
            return float(curr) - float(prev)
        except (TypeError, ValueError):
            return 0.0

    def trend(self, key: str, window_s: float = 15.0) -> float:
        """Linear trend of `key` over window. Positive = rising, negative = falling.

        Returns slope per second. 0.0 if insufficient data.
        """
        snapshots = self.window(window_s)
        if len(snapshots) < 2:
            return 0.0

        values: list[tuple[float, float]] = []
        for s in snapshots:
            v = s.get(key)
            if v is not None:
                try:
                    values.append((s["ts"], float(v)))
                except (TypeError, ValueError):
                    continue

        if len(values) < 2:
            return 0.0

        # Linear regression with centered timestamps to avoid
        # catastrophic cancellation with large POSIX values.
        n = len(values)
        ts = [t for t, _ in values]
        vs = [v for _, v in values]
        t_mean = sum(ts) / n

        centered = [t - t_mean for t in ts]
        sum_ct = sum(centered)
        sum_cv = sum(c * v for c, v in zip(centered, vs, strict=True))
        sum_cc = sum(c * c for c in centered)

        denom = n * sum_cc - sum_ct * sum_ct
        if abs(denom) < 1e-12:
            return 0.0

        return (n * sum_cv - sum_ct * sum(vs)) / denom

    def __len__(self) -> int:
        return len(self._buffer)

    @property
    def snapshots(self) -> list[dict[str, object]]:
        """All snapshots oldest-first (copy)."""
        return list(self._buffer)
