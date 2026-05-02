"""ActivityRouter — coordination layer over ActivityRevealMixin wards.

Per cc-task ``activity-reveal-ward-p0-base-class`` (WSJF 7.5). P0 ships
a **stub** router whose ``tick()`` iterates registered wards and
produces a router-state snapshot. The full mutex/priority/hysteresis
algorithm is P4 work — the spec lists 10 regression pins to ship
alongside it; P0 just establishes the registration + tick surface so
P1/P2 ward migrations can use the contract from day one.

Spec reference:
``hapax-research/specs/2026-05-01-activity-reveal-ward-family-spec.md``
§2 (ActivityRouter Contract).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from agents.studio_compositor.activity_reveal_ward import (
    ActivityRevealMixin,
    VisibilityClaim,
)

log = logging.getLogger(__name__)


@dataclass
class RouterConfig:
    """Router policy. P0 honors ``tick_hz`` only; P4 wires the rest."""

    tick_hz: float = 2.0
    visibility_ceiling_pct: float = 0.15
    rolling_window_s: float = 3600.0
    ceiling_cooldown_s: float = 600.0
    mutex: bool = True
    entry_debounce_s: float = 5.0
    mandatory_exit_transition: str = "zero-cut-out"
    normal_exit_transition: str = "ticker-scroll-out"
    normal_entry_transition: str = "ticker-scroll-in"


@dataclass
class RouterState:
    """One-tick snapshot of router-side observability state."""

    tick_ts: float
    claims: dict[str, VisibilityClaim] = field(default_factory=dict)
    mandatory_invisible_ids: tuple[str, ...] = ()
    want_visible_ids: tuple[str, ...] = ()


class ActivityRouter:
    """Coordination layer over a set of ``ActivityRevealMixin`` wards.

    P0 surface:

      - ``__init__``: register wards.
      - ``tick``: snapshot every ward's claim, classify into
        mandatory-invisible / want-visible / nominal. Never raises.
      - ``start`` / ``stop``: lifecycle. ``start`` spawns a daemon
        tick thread at ``tick_hz``; ``stop`` is idempotent.
      - ``last_state``: thread-safe snapshot of the most recent tick.

    P4 will replace the trivial classify-only logic with the
    mutex/priority/hysteresis algorithm in spec §2.
    """

    def __init__(
        self,
        wards: Sequence[ActivityRevealMixin],
        config: RouterConfig | None = None,
    ) -> None:
        self._wards: tuple[ActivityRevealMixin, ...] = tuple(wards)
        self._config = config if config is not None else RouterConfig()
        self._state_lock = threading.Lock()
        self._state = RouterState(tick_ts=time.monotonic())
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stopped = False

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the daemon tick thread. Idempotent at the
        already-started level: a second call is a no-op."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopped = False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._tick_loop,
            name="activity-router-tick",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Idempotent shutdown."""
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # ── Public surface ───────────────────────────────────────────────

    @property
    def wards(self) -> tuple[ActivityRevealMixin, ...]:
        return self._wards

    def last_state(self) -> RouterState:
        """Thread-safe snapshot of the latest tick state."""
        with self._state_lock:
            return self._state

    def describe(self) -> dict[str, Any]:
        """Return a JSON-friendly snapshot of registered wards.

        Diagnostic-only — used by ad-hoc operator scripts and the
        upcoming router observability dashboard. Tests pin the shape so
        the contract is stable for those callers.
        """
        return {
            "tick_hz": self._config.tick_hz,
            "ward_count": len(self._wards),
            "ward_ids": [type(w).WARD_ID for w in self._wards],
        }

    def tick(self, *, now: float | None = None) -> RouterState:
        """One tick of the router. Snapshots claims and classifies.

        Per the spec's failure-mode invariants: a tick that raises is
        caught, logged WARNING, and the next tick continues. The state
        we return is always self-consistent — partial claim sets
        (caused by an exception mid-iteration) never escape this method.
        """
        ts = time.monotonic() if now is None else now
        claims: dict[str, VisibilityClaim] = {}
        for ward in self._wards:
            ward_id = type(ward).WARD_ID
            try:
                claim = ward.current_claim()
            except Exception as exc:  # pragma: no cover — defensive
                log.warning(
                    "activity-router: claim snapshot raised on %s: %s",
                    ward_id,
                    exc,
                    exc_info=True,
                )
                continue
            claims[ward_id] = claim

        mandatory_invisible_ids = tuple(
            sorted(wid for wid, c in claims.items() if c.mandatory_invisible)
        )
        want_visible_ids = tuple(
            sorted(wid for wid, c in claims.items() if c.want_visible and not c.mandatory_invisible)
        )
        state = RouterState(
            tick_ts=ts,
            claims=claims,
            mandatory_invisible_ids=mandatory_invisible_ids,
            want_visible_ids=want_visible_ids,
        )
        with self._state_lock:
            self._state = state
        return state

    # ── Internal tick loop ───────────────────────────────────────────

    def _tick_loop(self) -> None:
        interval = 1.0 / max(0.1, self._config.tick_hz)
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:  # pragma: no cover — defensive
                log.warning(
                    "activity-router: tick raised, continuing: %s",
                    exc,
                    exc_info=True,
                )
            self._stop_event.wait(interval)


__all__ = [
    "ActivityRouter",
    "RouterConfig",
    "RouterState",
]
