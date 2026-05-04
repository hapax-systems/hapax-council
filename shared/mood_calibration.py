"""Rolling-quantile helper for mood bridge signal calibration.

Provides a thread-safe rolling-window quantile tracker that mood bridge
accessors use to determine whether a raw backend value is "high" relative
to the operator's recent baseline.

Usage::

    tracker = RollingQuantile(window_s=1800.0, quantile=0.8)
    tracker.observe(0.42)
    tracker.observe(0.55)
    is_high = tracker.is_above_quantile(0.60)  # True if 0.60 > q80

Thread-safe: the internal deque is protected by a lock. Multiple
backends can observe concurrently without corruption.

Staleness: if no observations have been recorded within ``stale_s``
(default 120s), ``is_above_quantile()`` returns ``None`` (skip-signal
semantics per ClaimEngine contract).
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RollingQuantile:
    """Thread-safe rolling-window quantile tracker.

    Args:
        window_s: Rolling window duration in seconds.
        quantile: Quantile to compute (0.0-1.0). E.g. 0.8 = 80th percentile.
        min_samples: Minimum number of observations before quantile is valid.
            Returns ``None`` from ``is_above_quantile()`` until this many
            observations have been recorded.
        stale_s: Maximum age (seconds) of the most recent observation before
            the tracker is considered stale (returns ``None``).
    """

    def __init__(
        self,
        *,
        window_s: float = 1800.0,
        quantile: float = 0.8,
        min_samples: int = 10,
        stale_s: float = 120.0,
    ) -> None:
        self._window_s = window_s
        self._quantile = quantile
        self._min_samples = min_samples
        self._stale_s = stale_s
        self._lock = threading.Lock()
        self._data: deque[tuple[float, float]] = deque()  # (timestamp, value)

    def observe(self, value: float, *, now: float | None = None) -> None:
        """Record a new observation.

        Args:
            value: The raw value to record.
            now: Override timestamp (for testing). Defaults to time.monotonic().
        """
        if now is None:
            now = time.monotonic()
        with self._lock:
            self._data.append((now, value))
            self._prune(now)

    def is_above_quantile(self, value: float, *, now: float | None = None) -> bool | None:
        """Return True if value exceeds the rolling quantile threshold.

        Returns ``None`` when:
        - Fewer than ``min_samples`` observations in the window.
        - Most recent observation is older than ``stale_s``.

        ``None`` signals "skip this signal" to the Bayesian engine.
        """
        if now is None:
            now = time.monotonic()
        with self._lock:
            self._prune(now)
            if len(self._data) < self._min_samples:
                return None
            # Staleness check: most recent observation age
            if now - self._data[-1][0] > self._stale_s:
                return None
            q = self._compute_quantile()
        return value > q

    def current_quantile(self, *, now: float | None = None) -> float | None:
        """Return the current quantile value, or None if insufficient data."""
        if now is None:
            now = time.monotonic()
        with self._lock:
            self._prune(now)
            if len(self._data) < self._min_samples:
                return None
            return self._compute_quantile()

    def _prune(self, now: float) -> None:
        """Remove observations older than the window. Caller holds lock."""
        cutoff = now - self._window_s
        while self._data and self._data[0][0] < cutoff:
            self._data.popleft()

    def _compute_quantile(self) -> float:
        """Compute the quantile from current observations. Caller holds lock."""
        values = sorted(v for _, v in self._data)
        n = len(values)
        if n == 0:
            return 0.0
        idx = self._quantile * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return values[lo] * (1 - frac) + values[hi] * frac
