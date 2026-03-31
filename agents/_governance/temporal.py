"""Temporal bounds: time-limited consent decisions.

Implements deferred formalism #6. Adds interval logic to consent
contracts — a contract is active iff created_at <= t < expires_at.

Current ConsentContract has created_at and revoked_at but no expiry.
This module adds:
- ConsentInterval: half-open time interval [start, end)
- Temporal validity check for contracts
- Renewal and extension operations
- Grace period for near-expiry warnings

Reference: Allen's interval algebra for temporal reasoning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ConsentInterval:
    """Half-open time interval [start, end) for consent validity.

    start: epoch seconds when consent begins
    end: epoch seconds when consent expires (None = indefinite)
    """

    start: float
    end: float | None = None

    def active_at(self, t: float | None = None) -> bool:
        """Check if interval is active at time t (defaults to now)."""
        t = t if t is not None else time.time()
        if t < self.start:
            return False
        return not (self.end is not None and t >= self.end)

    def expired_at(self, t: float | None = None) -> bool:
        """Check if interval has expired by time t."""
        if self.end is None:
            return False
        t = t if t is not None else time.time()
        return t >= self.end

    def remaining_at(self, t: float | None = None) -> float | None:
        """Seconds remaining until expiry. None if indefinite."""
        if self.end is None:
            return None
        t = t if t is not None else time.time()
        return max(0.0, self.end - t)

    def near_expiry(self, grace_s: float = 3600.0, t: float | None = None) -> bool:
        """Check if within grace period of expiry (default: 1 hour)."""
        remaining = self.remaining_at(t)
        if remaining is None:
            return False
        return remaining <= grace_s

    # ── Interval operations ──────────────────────────────────────────

    def extend(self, additional_s: float) -> ConsentInterval:
        """Extend the interval by additional seconds.

        If indefinite, returns self unchanged.
        """
        if self.end is None:
            return self
        return ConsentInterval(start=self.start, end=self.end + additional_s)

    def renew(self, duration_s: float, from_time: float | None = None) -> ConsentInterval:
        """Create a new interval starting from now (or given time) with given duration."""
        t = from_time if from_time is not None else time.time()
        return ConsentInterval(start=t, end=t + duration_s)

    def intersect(self, other: ConsentInterval) -> ConsentInterval | None:
        """Compute intersection of two intervals. Returns None if disjoint."""
        new_start = max(self.start, other.start)

        if self.end is None and other.end is None:
            new_end = None
        elif self.end is None:
            new_end = other.end
        elif other.end is None:
            new_end = self.end
        else:
            new_end = min(self.end, other.end)

        if new_end is not None and new_start >= new_end:
            return None
        return ConsentInterval(start=new_start, end=new_end)

    def contains(self, other: ConsentInterval) -> bool:
        """Check if this interval fully contains another."""
        if other.start < self.start:
            return False
        if self.end is None:
            return True
        if other.end is None:
            return False
        return other.end <= self.end

    # ── Allen's interval relations (subset) ──────────────────────────

    def before(self, other: ConsentInterval) -> bool:
        """This interval ends before other starts."""
        if self.end is None:
            return False
        return self.end <= other.start

    def overlaps(self, other: ConsentInterval) -> bool:
        """This interval overlaps with other (non-empty intersection)."""
        return self.intersect(other) is not None

    @staticmethod
    def indefinite(start: float | None = None) -> ConsentInterval:
        """Create an indefinite interval starting from now."""
        return ConsentInterval(start=start or time.time(), end=None)

    @staticmethod
    def fixed(duration_s: float, start: float | None = None) -> ConsentInterval:
        """Create a fixed-duration interval starting from now."""
        t = start or time.time()
        return ConsentInterval(start=t, end=t + duration_s)


@dataclass(frozen=True)
class TemporalConsent:
    """Consent decision with temporal bounds.

    Wraps a contract ID with its validity interval. Used by the gate
    to check not just WHETHER consent exists but WHETHER it's temporally valid.
    """

    contract_id: str
    interval: ConsentInterval
    person_id: str = ""

    def valid_at(self, t: float | None = None) -> bool:
        """Check if this consent is valid at time t."""
        return self.interval.active_at(t)

    def needs_renewal(self, grace_s: float = 3600.0, t: float | None = None) -> bool:
        """Check if this consent needs renewal soon."""
        return self.interval.near_expiry(grace_s, t)
