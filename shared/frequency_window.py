"""Time-windowed event frequency tracker for distribution shift detection.

WS4: Maintains a sliding window of recent events and compares current rates
against the long-term baseline (monotonic counters). A high shift_score means
recent event patterns differ significantly from the historical baseline.
"""

from __future__ import annotations

import time
from collections import deque


class FrequencyWindow:
    """Time-windowed event frequency tracker.

    Maintains a sliding window (default 1 hour) and compares current
    rates against a baseline for distribution shift detection.
    """

    def __init__(self, window_s: float = 3600.0) -> None:
        self._window_s = window_s
        self._events: deque[tuple[float, str]] = deque()  # (timestamp, pattern_key)

    def record(self, pattern_key: str) -> None:
        """Record an event occurrence."""
        self._events.append((time.monotonic(), pattern_key))
        self._prune()

    def _prune(self) -> None:
        """Remove events outside the window."""
        cutoff = time.monotonic() - self._window_s
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def window_counts(self) -> dict[str, int]:
        """Get event counts within the current window."""
        self._prune()
        counts: dict[str, int] = {}
        for _, key in self._events:
            counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def total_in_window(self) -> int:
        self._prune()
        return len(self._events)

    def shift_score(self, baseline: dict[str, int]) -> float:
        """Compare windowed distribution against baseline counters.

        Returns 0.0 when window matches baseline proportions.
        Returns up to 1.0 when window is maximally different.

        For each pattern in the window, compare its windowed share vs
        baseline share. Patterns present in window but rare in baseline
        contribute high shift.
        """
        window = self.window_counts()
        if not window or not baseline:
            return 0.0

        total_window = sum(window.values())
        total_baseline = sum(baseline.values())
        if total_window == 0 or total_baseline == 0:
            return 0.0

        divergence = 0.0
        for key, w_count in window.items():
            w_share = w_count / total_window
            b_count = baseline.get(key, 0)
            b_share = (b_count / total_baseline) if b_count > 0 else (1 / (total_baseline + 1))
            ratio = w_share / b_share
            divergence += w_share * abs(min(ratio, 10.0) - 1.0)  # cap ratio at 10x

        return round(min(1.0, divergence), 3)
