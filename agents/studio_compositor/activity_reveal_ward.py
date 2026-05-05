"""ActivityRevealMixin — base mixin for activity-reveal wards.

Per cc-task ``activity-reveal-ward-p0-base-class`` (WSJF 7.5). Wards that
broadcast operator activity (DURF coding sessions, M8 instrument reveal,
Polyend instrument reveal, Steam Deck reveal, future variants) inherit
visibility-ceiling enforcement, co-existence suppression, HARDM hooks,
and a uniform claim contract from this single source of truth.

Per the audit / spec:

* This is a **mixin**, NOT a ``CairoSource`` subclass. M8 reads RGBA
  from ``/dev/shm`` and never paints Cairo; mixing Cairo machinery
  into the family base would force M8 to inherit dead code.
* The family enforces *coordination* (visibility, ceiling, consent),
  not *appearance*. DURF stays Px437 IBM VGA + mIRC-16; M8 stays
  NEAREST 4× pixel art. The mixin does not touch palette / typography.
* P0 ships per-ward ceiling. Family-pool ceiling per the R3 governance
  doc lands in P3 (this module's contract is forward-compatible).

Migration sequence:

  P0 (this file): mixin + router stub.
  P1: ``CodingActivityReveal(HomageTransitionalSource, ActivityRevealMixin)``.
  P2: ``M8InstrumentReveal(ActivityRevealMixin)`` — non-Cairo lifecycle.
  P3: governance (router-side ceiling + suppression + HARDM detector).
  P4: router policy + full tick integration.
  P5/P6: Polyend / Steam Deck variants.

Spec reference:
``hapax-research/specs/2026-05-01-activity-reveal-ward-family-spec.md``
§1 (Mixin Contract).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

log = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────

#: When set to ``"1"``, ``_ceiling_enforced()`` returns False
#: unconditionally. Used by operator inspection / triage and by tests
#: that exercise the unconstrained code path.
ACTIVITY_CEILING_DISABLED_ENV: str = "HAPAX_ACTIVITY_CEILING_DISABLED"

#: Rolling-window length for the per-ward visibility ceiling counter.
#: 60 minutes per the DURF design §6 spec; the family base inherits it.
DEFAULT_ROLLING_WINDOW_S: float = 3600.0

#: Default poll cadence for the mixin's daemon thread. Each subclass
#: can override at construction.
DEFAULT_POLL_INTERVAL_S: float = 0.5

_VALID_SOURCE_KINDS: frozenset[str] = frozenset({"cairo", "external_rgba"})


# ── VisibilityClaim ──────────────────────────────────────────────────


@dataclass(frozen=True)
class VisibilityClaim:
    """A single ward's visibility request, snapshotted at one tick.

    The router consumes claims and decides which ward (if any) is
    visible this tick. Claims are immutable so they can be safely
    handed off across threads.
    """

    ward_id: str
    want_visible: bool
    score: float
    """Recruitment score in [0.0, 1.0]. The router uses this to break
    ties when multiple wards want_visible=True simultaneously."""
    hysteresis_floor_s: float = 30.0
    """Minimum visible-seconds before the ward can be exited via the
    normal exit transition. Prevents rapid claim flap."""
    mandatory_invisible: bool = False
    """When True, the router must force-exit immediately (consent-safe,
    HARDM violation, or hardware absence). Overrides hysteresis."""
    source_refs: tuple[str, ...] = ()
    """Free-form provenance pointers — e.g., the impingement event IDs
    or the M8 SHM file path that drove the claim."""
    reason: str = "no reason provided"


# ── ActivityRevealMixin ──────────────────────────────────────────────


class ActivityRevealMixin(ABC):
    """Base mixin for activity-reveal wards. NOT a ``CairoSource``."""

    # ── Required class variables (validated at __init_subclass__) ──

    WARD_ID: ClassVar[str] = ""
    """Stable ID; matches the layout JSON ``source.id`` field."""

    SOURCE_KIND: ClassVar[Literal["cairo", "external_rgba"]] = "cairo"
    """``"cairo"`` for Cairo-painting wards (DURF, Polyend),
    ``"external_rgba"`` for SHM-driven wards (M8, Steam Deck)."""

    DEFAULT_HYSTERESIS_S: ClassVar[float] = 30.0
    """Default hysteresis floor; subclasses may override per ward."""

    VISIBILITY_CEILING_PCT: ClassVar[float] = 0.15
    """Per-ward ceiling: max fraction of a 60-minute rolling window the
    ward is allowed to be visible. P3 retrofits a family-pool variant."""

    SUPPRESS_WHEN_ACTIVE: ClassVar[frozenset[str]] = frozenset()
    """Other ward IDs the router must suppress when this ward is in
    HOLD. P3 wires the router-side enforcement; P0 just defines the
    declarative slot."""

    priority: ClassVar[int] = 0
    """Router-policy priority. P4 ``PRIORITY_SCORED`` uses this as the
    first ordering key, with lexicographic ``WARD_ID`` as the tie-break.
    Default 0 preserves existing family behavior unless a ward opts in."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Allow abstract-but-not-yet-concrete subclasses (used in test
        # bases that intermediate the contract): require fields only on
        # subclasses that are not themselves abstract.
        if getattr(cls, "__abstractmethods__", None):
            return
        if not getattr(cls, "WARD_ID", ""):
            raise TypeError(
                f"{cls.__name__}: WARD_ID is required (non-empty string) "
                "on every concrete ActivityRevealMixin subclass"
            )
        kind = getattr(cls, "SOURCE_KIND", None)
        if kind not in _VALID_SOURCE_KINDS:
            raise TypeError(
                f"{cls.__name__}: SOURCE_KIND must be one of "
                f"{sorted(_VALID_SOURCE_KINDS)}, got {kind!r}"
            )

    # ── Construction / lifecycle ─────────────────────────────────────

    def __init__(
        self,
        *,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        rolling_window_s: float = DEFAULT_ROLLING_WINDOW_S,
        start_poll_thread: bool = True,
    ) -> None:
        self._poll_interval_s = poll_interval_s
        self._rolling_window_s = rolling_window_s
        self._claim_lock = threading.Lock()
        self._claim = VisibilityClaim(
            ward_id=type(self).WARD_ID,
            want_visible=False,
            score=0.0,
            hysteresis_floor_s=type(self).DEFAULT_HYSTERESIS_S,
            mandatory_invisible=False,
            reason="not yet polled",
        )
        # Visibility-ceiling counter: list of (start_ts, end_ts) for
        # each visible interval inside the rolling window. The mixin
        # is told about visibility via ``mark_visible_window`` (the
        # router calls it). P0 trusts the router; P3 verifies via
        # router-side state.
        self._visible_intervals: deque[tuple[float, float]] = deque()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._stopped = False
        if start_poll_thread:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name=f"activity-reveal-poll[{type(self).WARD_ID}]",
                daemon=True,
            )
            self._poll_thread.start()

    def stop(self) -> None:
        """Idempotent shutdown. Joins the poll thread within 2s."""
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=2.0)

    # ── Subclass contract ────────────────────────────────────────────

    @abstractmethod
    def _compute_claim_score(self) -> float:
        """Return recruitment score in [0.0, 1.0] for this tick."""

    @abstractmethod
    def _want_visible(self) -> bool:
        """Return whether the ward wants to be visible this tick."""

    @abstractmethod
    def _mandatory_invisible(self) -> bool:
        """Return whether the ward MUST be invisible regardless of
        ``_want_visible`` (consent-safe, HARDM violation, etc)."""

    @abstractmethod
    def _claim_source_refs(self) -> tuple[str, ...]:
        """Provenance pointers for this tick's claim."""

    @abstractmethod
    def _describe_source_registration(self) -> dict[str, Any]:
        """Layout JSON registration descriptor.

        Used by ``ActivityRouter`` to look up the ward in the source
        registry without forcing an import cycle. The dict shape is
        ``{"id": str, "class_name": str, "kind": str, ...}``.
        """

    # ── Optional override ────────────────────────────────────────────

    def _hardm_check(self) -> None:
        """Pre-render HARDM enforcement hook.

        P0 default is ``pass``. Subclasses override per ward when the
        ward has render output that could violate the HARDM grammar
        (chrome text labels, marketing copy, etc). P3 wires a runtime
        detector that escalates HARDM violations into
        ``_mandatory_invisible``.
        """
        return None

    # ── Public surface ───────────────────────────────────────────────

    def current_claim(self) -> VisibilityClaim:
        """Thread-safe snapshot of the latest claim."""
        with self._claim_lock:
            return self._claim

    def state(self) -> dict[str, Any]:
        """Render-ready state dict.

        Mirrors the existing ``DURFCairoSource.state()`` shape so
        ``ActivityRouter`` and downstream consumers can read either
        kind of ward through one contract.
        """
        with self._claim_lock:
            claim = self._claim
        return {
            "ward_id": claim.ward_id,
            "want_visible": claim.want_visible,
            "score": claim.score,
            "mandatory_invisible": claim.mandatory_invisible,
            "hysteresis_floor_s": claim.hysteresis_floor_s,
            "source_refs": list(claim.source_refs),
            "reason": claim.reason,
        }

    def mark_visible_window(self, start_ts: float, end_ts: float) -> None:
        """Record a closed visibility interval; the router calls this
        after a HOLD → exit transition completes so the ceiling counter
        can decay older intervals out of the rolling window."""
        if end_ts < start_ts:
            return
        with self._claim_lock:
            self._visible_intervals.append((start_ts, end_ts))
            self._evict_expired_locked(now=end_ts)

    def _evict_expired_locked(self, *, now: float) -> None:
        """Drop intervals whose ``end_ts`` is older than the rolling
        window. Caller must hold ``_claim_lock``."""
        cutoff = now - self._rolling_window_s
        while self._visible_intervals and self._visible_intervals[0][1] < cutoff:
            self._visible_intervals.popleft()

    # ── Visibility ceiling ───────────────────────────────────────────

    @property
    def _visibility_ceiling_s(self) -> float:
        return type(self).VISIBILITY_CEILING_PCT * self._rolling_window_s

    def _consumed_visible_seconds(self, *, now: float) -> float:
        """Total visible-seconds inside the rolling window ending at
        ``now``. Counted with proper trimming of intervals that
        partially overlap the window edge."""
        with self._claim_lock:
            self._evict_expired_locked(now=now)
            cutoff = now - self._rolling_window_s
            total = 0.0
            for start_ts, end_ts in self._visible_intervals:
                trimmed_start = max(start_ts, cutoff)
                trimmed_end = min(end_ts, now)
                if trimmed_end > trimmed_start:
                    total += trimmed_end - trimmed_start
        return total

    def _ceiling_enforced(self, now: float) -> bool:
        """Return True when the rolling-window ceiling would be exceeded.

        Returns False unconditionally when
        ``HAPAX_ACTIVITY_CEILING_DISABLED=1`` is set in the environment.
        """
        if os.environ.get(ACTIVITY_CEILING_DISABLED_ENV) == "1":
            return False
        consumed = self._consumed_visible_seconds(now=now)
        return consumed >= self._visibility_ceiling_s

    # ── Internal poll ────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # pragma: no cover — defensive
                log.warning(
                    "activity-reveal[%s]: poll cycle failed: %s",
                    type(self).WARD_ID,
                    exc,
                    exc_info=True,
                )
            self._stop_event.wait(self._poll_interval_s)

    def poll_once(self, *, now: float | None = None) -> VisibilityClaim:
        """One claim-assembly cycle. Public so tests drive it.

        Wraps the subclass ``_compute_claim_score`` /
        ``_want_visible`` / ``_mandatory_invisible`` /
        ``_claim_source_refs`` calls in a fail-CLOSED guard: if the
        subclass raises, the claim degrades to
        ``(want_visible=False, mandatory_invisible=True, score=0.0)``
        and the exception is logged WARNING.
        """
        ts = time.monotonic() if now is None else now
        cls = type(self)
        try:
            score = float(self._compute_claim_score())
            want = bool(self._want_visible())
            mand = bool(self._mandatory_invisible())
            refs = tuple(self._claim_source_refs())
            reason = "ok"
        except Exception as exc:
            log.warning(
                "activity-reveal[%s]: claim assembly raised, fail-closed: %s",
                cls.WARD_ID,
                exc,
                exc_info=True,
            )
            score = 0.0
            want = False
            mand = True
            refs = ()
            reason = f"compute_exception: {type(exc).__name__}"
        score = max(0.0, min(1.0, score))
        claim = VisibilityClaim(
            ward_id=cls.WARD_ID,
            want_visible=want,
            score=score,
            hysteresis_floor_s=cls.DEFAULT_HYSTERESIS_S,
            mandatory_invisible=mand,
            source_refs=refs,
            reason=reason,
        )
        with self._claim_lock:
            self._claim = claim
        # Don't touch the wall-clock; the router knows when "now" is.
        del ts
        return claim


__all__ = [
    "ACTIVITY_CEILING_DISABLED_ENV",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_ROLLING_WINDOW_S",
    "ActivityRevealMixin",
    "VisibilityClaim",
]
