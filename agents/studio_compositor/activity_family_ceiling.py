"""Family-pool ceiling tracker for ActivityRevealMixin members.

P3 governance per cc-task ``activity-reveal-ward-p3-governance`` (audit
``hapax-research/audits/2026-05-01-activity-reveal-ward-family-unification.md``
§R3 §1). The per-ward ``VISIBILITY_CEILING_PCT`` (15% default in the P0
mixin) is insufficient at the family scale: with N members each at 15%,
the family could consume up to ``N * 15% = 60%+`` of the rolling window.
The R3 governance design caps the family pool at 25% and assigns
per-ward sub-ceilings inside that pool with priority-based eviction.

Sub-ceilings (R3 §1.3):

| Ward         | Sub-ceiling (60-min window) | Priority (lower = more evictable) |
|--------------|-----------------------------|-----------------------------------|
| DURF         | 15%                         | 4 (least evictable)               |
| M8           | 12%                         | 3                                 |
| Polyend      | 10%                         | 2                                 |
| Steam Deck   |  8%                         | 1 (most evictable)                |

The tracker is a pure logic module — no I/O, no threading. It records
visibility intervals via :func:`mark_visible_window` and answers
:func:`would_exceed_ceiling` queries deterministically. The
:class:`ActivityRouter` wires the tracker into its tick loop.

Spec reference:
``hapax-research/specs/2026-05-01-activity-reveal-ward-family-spec.md``
§1.5 (Shared concerns) + §2.6 (Observability).
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

#: Rolling window the tracker observes. Matches
#: :data:`agents.studio_compositor.activity_reveal_ward.DEFAULT_ROLLING_WINDOW_S`
#: so per-ward ceilings and family-pool ceiling agree on the same epoch.
DEFAULT_FAMILY_WINDOW_S: float = 3600.0

#: Family-pool ceiling as a fraction of the rolling window. 25% per
#: R3 §1.2 — chosen so the family of four wards collectively cannot
#: occupy more than 15min/hour of broadcast surface.
DEFAULT_FAMILY_CEILING_PCT: float = 0.25

#: Default per-ward sub-ceilings (fraction of the rolling window) and
#: eviction priority. Lower priority = more evictable when the family
#: pool is exhausted. These are R3 §1.3 starting values; subclasses
#: that need different ceilings register via
#: :meth:`FamilyCeilingTracker.register_ward`.
DEFAULT_WARD_SUB_CEILINGS: dict[str, tuple[float, int]] = {
    "durf": (0.15, 4),
    "m8": (0.12, 3),
    "polyend": (0.10, 2),
    "steam_deck": (0.08, 1),
}


@dataclass(frozen=True)
class WardCeilingPolicy:
    """Per-ward ceiling + eviction priority within the family pool."""

    ward_id: str
    ceiling_pct: float
    eviction_priority: int
    """Lower priority is more evictable. The router picks the
    lowest-priority ward to deny when the family pool is exhausted."""


@dataclass
class FamilyCeilingDecision:
    """Result of a ceiling consultation for one ward at one tick."""

    ward_id: str
    consumed_s: float
    """Visible-seconds this ward has consumed inside the rolling window."""
    family_consumed_s: float
    """Total visible-seconds across the family inside the rolling window."""
    ceiling_s: float
    """This ward's per-ward sub-ceiling in seconds."""
    family_ceiling_s: float
    """Family-pool ceiling in seconds."""
    would_exceed_self: bool
    """True iff visible NOW would push this ward past its sub-ceiling."""
    would_exceed_family: bool
    """True iff visible NOW would push the family past the pool ceiling."""

    @property
    def enforced(self) -> bool:
        return self.would_exceed_self or self.would_exceed_family

    @property
    def reason(self) -> str:
        if self.would_exceed_self and self.would_exceed_family:
            return "self+family ceiling exceeded"
        if self.would_exceed_self:
            return "self ceiling exceeded"
        if self.would_exceed_family:
            return "family ceiling exceeded"
        return "within ceilings"


class FamilyCeilingTracker:
    """Rolling-window family-pool ceiling tracker.

    Records closed visibility intervals per ward and answers
    "would visible-now exceed the ward's sub-ceiling or the family
    pool?" The tracker stores intervals as ``(start_ts, end_ts)``
    tuples in per-ward deques and evicts entries whose ``end_ts`` is
    older than the rolling window.

    Thread safety: not thread-safe by itself. The router is single-
    threaded inside its tick loop, so the tracker doesn't need locking.
    Callers that want concurrent updates must serialize externally.
    """

    def __init__(
        self,
        *,
        window_s: float = DEFAULT_FAMILY_WINDOW_S,
        family_ceiling_pct: float = DEFAULT_FAMILY_CEILING_PCT,
    ) -> None:
        if window_s <= 0:
            raise ValueError(f"window_s must be > 0, got {window_s}")
        if not 0.0 < family_ceiling_pct <= 1.0:
            raise ValueError(f"family_ceiling_pct must be in (0.0, 1.0], got {family_ceiling_pct}")
        self._window_s = window_s
        self._family_ceiling_pct = family_ceiling_pct
        self._intervals: dict[str, deque[tuple[float, float]]] = defaultdict(deque)
        self._policies: dict[str, WardCeilingPolicy] = {}

    @property
    def window_s(self) -> float:
        return self._window_s

    @property
    def family_ceiling_s(self) -> float:
        return self._family_ceiling_pct * self._window_s

    def register_ward(self, ward_id: str, ceiling_pct: float, eviction_priority: int) -> None:
        """Register a ward's sub-ceiling and eviction priority.

        Idempotent: calling with the same ``ward_id`` overwrites the
        prior policy. ``ceiling_pct`` is a fraction of the rolling
        window; ``eviction_priority`` is the priority within the
        family pool (lower = more evictable).
        """
        if not 0.0 <= ceiling_pct <= self._family_ceiling_pct:
            raise ValueError(
                f"ward {ward_id}: ceiling_pct must be in [0.0, family_ceiling_pct={self._family_ceiling_pct}], "
                f"got {ceiling_pct}"
            )
        self._policies[ward_id] = WardCeilingPolicy(
            ward_id=ward_id,
            ceiling_pct=ceiling_pct,
            eviction_priority=eviction_priority,
        )

    def policy(self, ward_id: str) -> WardCeilingPolicy | None:
        return self._policies.get(ward_id)

    def mark_visible_window(self, ward_id: str, start_ts: float, end_ts: float) -> None:
        """Record a closed visibility interval for ``ward_id``.

        No-op if ``end_ts < start_ts`` (defensive — clock-skew /
        out-of-order callers don't poison the tracker).
        """
        if end_ts < start_ts:
            return
        self._intervals[ward_id].append((start_ts, end_ts))
        self._evict_expired(ward_id, now=end_ts)

    def consumed_seconds(self, ward_id: str, *, now: float) -> float:
        """Visible-seconds for ``ward_id`` inside the rolling window
        ending at ``now``."""
        self._evict_expired(ward_id, now=now)
        cutoff = now - self._window_s
        total = 0.0
        for start_ts, end_ts in self._intervals[ward_id]:
            trimmed_start = max(start_ts, cutoff)
            trimmed_end = min(end_ts, now)
            if trimmed_end > trimmed_start:
                total += trimmed_end - trimmed_start
        return total

    def family_consumed_seconds(self, *, now: float) -> float:
        """Total visible-seconds across all wards inside the rolling
        window ending at ``now``."""
        return sum(
            self.consumed_seconds(ward_id, now=now) for ward_id in list(self._intervals.keys())
        )

    def consult(self, ward_id: str, *, now: float) -> FamilyCeilingDecision:
        """Compute the ceiling decision for ``ward_id`` at ``now``.

        The decision returns ``would_exceed_self`` / ``would_exceed_family``
        as advisory flags. The router decides what to do (deny entry,
        evict another ward, etc) based on the decision.

        For wards without a registered policy, ``ceiling_s`` falls
        back to the family ceiling — i.e., an unregistered ward is
        only blocked by family-pool exhaustion.
        """
        policy = self._policies.get(ward_id)
        ceiling_s = (policy.ceiling_pct * self._window_s) if policy else self.family_ceiling_s
        consumed = self.consumed_seconds(ward_id, now=now)
        family_consumed = self.family_consumed_seconds(now=now)
        return FamilyCeilingDecision(
            ward_id=ward_id,
            consumed_s=consumed,
            family_consumed_s=family_consumed,
            ceiling_s=ceiling_s,
            family_ceiling_s=self.family_ceiling_s,
            would_exceed_self=consumed >= ceiling_s,
            would_exceed_family=family_consumed >= self.family_ceiling_s,
        )

    def evictable_order(self, *, now: float) -> list[WardCeilingPolicy]:
        """Wards eligible for eviction, sorted from most-evictable
        (lowest priority) to least-evictable. Used by the router when
        the family pool is exhausted and a higher-priority ward wants
        to enter."""
        del now  # priority is policy-based, not consumption-based
        return sorted(self._policies.values(), key=lambda p: p.eviction_priority)

    def _evict_expired(self, ward_id: str, *, now: float) -> None:
        cutoff = now - self._window_s
        intervals = self._intervals[ward_id]
        while intervals and intervals[0][1] < cutoff:
            intervals.popleft()


__all__ = [
    "DEFAULT_FAMILY_CEILING_PCT",
    "DEFAULT_FAMILY_WINDOW_S",
    "DEFAULT_WARD_SUB_CEILINGS",
    "FamilyCeilingDecision",
    "FamilyCeilingTracker",
    "WardCeilingPolicy",
]
