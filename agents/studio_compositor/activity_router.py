"""ActivityRouter — coordination layer over ActivityRevealMixin wards.

Per cc-task ``activity-reveal-ward-p0-base-class`` (WSJF 7.5). P0 shipped
a **stub** router whose ``tick()`` iterates registered wards and
produces a router-state snapshot. P3 (cc-task
``activity-reveal-ward-p3-governance``, WSJF 7.5) layers in:

  * **Family-pool ceiling** (R3 §1) — 25% family budget shared across
    all members + per-ward sub-ceilings (DURF 15%, M8 12%, Polyend 10%,
    Steam Deck 8%) with priority-based eviction.
  * **Suppression wiring** — per-tick projection of every visible ward's
    ``SUPPRESS_WHEN_ACTIVE`` set into the ward-properties SHM file so
    suppression no longer waits for render time.
  * **WCS row writer** — per-tick atomic write to
    ``/dev/shm/hapax-compositor/routing-state.json`` for the family
    observability dashboard.
  * **7 Prometheus metrics** registered with the compositor's REGISTRY
    via the ``**_metric_kwargs`` splat per
    ``project_compositor_metrics_registry`` memory.

Three concerns from the cc-task scope are deferred to follow-ups:
HARDM static commit-time hook, HARDM runtime 4-axis detector, and
consent-SHM canonicalization (operator decision per audit OQ-6).

The full mutex/priority/hysteresis algorithm is still P4 work — this
P3 lift is observability + governance scaffolding around the existing
classify-only logic.

Spec reference:
``hapax-research/specs/2026-05-01-activity-reveal-ward-family-spec.md``
§2 (ActivityRouter Contract).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.studio_compositor.activity_family_ceiling import (
    DEFAULT_FAMILY_CEILING_PCT,
    DEFAULT_FAMILY_WINDOW_S,
    DEFAULT_WARD_SUB_CEILINGS,
    FamilyCeilingDecision,
    FamilyCeilingTracker,
)
from agents.studio_compositor.activity_reveal_ward import (
    ActivityRevealMixin,
    VisibilityClaim,
)

log = logging.getLogger(__name__)

#: WCS row destination per cc-task ``activity-reveal-ward-p3-governance``
#: § Verification. The compositor's family observability dashboard reads
#: this file; the router writes it atomically every tick.
ROUTING_STATE_PATH: Path = Path("/dev/shm/hapax-compositor/routing-state.json")

#: Default TTL applied to suppression entries written to the
#: ward-properties surface. 5s is comfortably longer than the router's
#: default 0.5s tick interval (2 Hz) so a missed write never lets a
#: suppressed ward leak visible.
SUPPRESSION_TTL_S: float = 5.0


# ── Prometheus metrics (registry-bound per memory project_compositor_metrics_registry) ──
#
# The compositor's :mod:`agents.studio_compositor.metrics` module owns
# its own ``CollectorRegistry`` exported on :9482. Metrics on the default
# registry are silently invisible to that scrape surface. We use the
# splat pattern: ``_metric_kwargs`` resolves to ``{"registry": REGISTRY}``
# when the compositor module is importable, else ``{}`` (so officium /
# tests don't crash on missing optional dependency).

try:
    from agents.studio_compositor import metrics as _compositor_metrics

    _metric_kwargs: dict[str, Any] = (
        {"registry": _compositor_metrics.REGISTRY}
        if getattr(_compositor_metrics, "REGISTRY", None) is not None
        else {}
    )
except Exception:  # pragma: no cover — defensive
    _metric_kwargs = {}


def _build_metrics() -> dict[str, Any]:
    """Construct the 7 P3 metrics with the splat. Returns ``{}`` if
    prometheus_client is missing."""
    try:
        from prometheus_client import Counter, Gauge
    except ImportError:  # pragma: no cover — prometheus_client always installed
        return {}
    return {
        "visible_seconds_total": Counter(
            "activity_reveal_ward_visible_seconds_total",
            "Cumulative visible-seconds per ward inside the rolling window.",
            ["ward_id"],
            **_metric_kwargs,
        ),
        "ceiling_enforced_total": Counter(
            "activity_reveal_ward_ceiling_enforced_total",
            "Times the per-ward sub-ceiling or family-pool ceiling denied a visible request.",
            ["ward_id"],
            **_metric_kwargs,
        ),
        "active_wards": Gauge(
            "activity_reveal_router_active_wards",
            "Wards with want_visible=True and not mandatory_invisible at last tick.",
            **_metric_kwargs,
        ),
        "family_pool_consumed_fraction": Gauge(
            "activity_reveal_family_pool_consumed_fraction",
            "Fraction of the family pool consumed inside the rolling window (0.0-1.0+).",
            **_metric_kwargs,
        ),
        "transitions_total": Counter(
            "activity_reveal_router_transitions_total",
            "Router transitions per ward per transition kind.",
            ["ward_id", "transition"],
            **_metric_kwargs,
        ),
        "idle_ticks_total": Counter(
            "activity_reveal_router_idle_ticks_total",
            "Ticks where no ward wanted to be visible.",
            **_metric_kwargs,
        ),
        "forced_exits_total": Counter(
            "activity_reveal_router_forced_exits_total",
            "Forced exits (mandatory_invisible or ceiling-eviction) per ward per reason.",
            ["ward_id", "reason"],
            **_metric_kwargs,
        ),
    }


_METRICS: dict[str, Any] = _build_metrics()


@dataclass
class RouterConfig:
    """Router policy. P0 honored ``tick_hz`` only; P3 adds family-pool
    ceiling fields (``family_ceiling_pct``, ``rolling_window_s``,
    ``sub_ceilings``); P4 wires the rest."""

    tick_hz: float = 2.0
    visibility_ceiling_pct: float = 0.15
    rolling_window_s: float = DEFAULT_FAMILY_WINDOW_S
    ceiling_cooldown_s: float = 600.0
    mutex: bool = True
    entry_debounce_s: float = 5.0
    mandatory_exit_transition: str = "zero-cut-out"
    normal_exit_transition: str = "ticker-scroll-out"
    normal_entry_transition: str = "ticker-scroll-in"

    # P3 family-pool ceiling fields.
    family_ceiling_pct: float = DEFAULT_FAMILY_CEILING_PCT
    sub_ceilings: dict[str, tuple[float, int]] = field(
        default_factory=lambda: dict(DEFAULT_WARD_SUB_CEILINGS)
    )

    # P3 observability — write the WCS row each tick.
    routing_state_path: Path = ROUTING_STATE_PATH


@dataclass
class RouterState:
    """One-tick snapshot of router-side observability state."""

    tick_ts: float
    claims: dict[str, VisibilityClaim] = field(default_factory=dict)
    mandatory_invisible_ids: tuple[str, ...] = ()
    want_visible_ids: tuple[str, ...] = ()
    # P3 additions.
    suppressed_by_other_ward: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """Map of suppressed ward_id -> tuple of suppressor ward IDs that
    forced this ward to invisible this tick."""
    ceiling_decisions: dict[str, FamilyCeilingDecision] = field(default_factory=dict)
    """Per-ward ceiling consultation result for this tick."""
    family_pool_consumed_fraction: float = 0.0
    """Family pool consumption as a fraction of the pool ceiling (0.0-1.0+)."""


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
        *,
        ceiling_tracker: FamilyCeilingTracker | None = None,
    ) -> None:
        self._wards: tuple[ActivityRevealMixin, ...] = tuple(wards)
        self._config = config if config is not None else RouterConfig()
        self._state_lock = threading.Lock()
        self._state = RouterState(tick_ts=time.monotonic())
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stopped = False
        # P3: family-pool ceiling tracker. Inject for tests; otherwise
        # construct from config + register every ward whose WARD_ID is
        # in ``sub_ceilings``.
        self._ceiling = (
            ceiling_tracker
            if ceiling_tracker is not None
            else FamilyCeilingTracker(
                window_s=self._config.rolling_window_s,
                family_ceiling_pct=self._config.family_ceiling_pct,
            )
        )
        if ceiling_tracker is None:
            for ward_id, (ceiling_pct, priority) in self._config.sub_ceilings.items():
                self._ceiling.register_ward(
                    ward_id=ward_id,
                    ceiling_pct=ceiling_pct,
                    eviction_priority=priority,
                )
        # Track per-ward visible-window starts so we can mark intervals
        # closed when the ward exits (or this router stops).
        self._open_windows: dict[str, float] = {}

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

        P3 layers in family-pool ceiling consultation, suppression
        wiring (per-tick projection of ``SUPPRESS_WHEN_ACTIVE``),
        Prometheus metric updates, and the WCS row write.

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

        # ── P3: family-pool ceiling consultation ───────────────────
        ceiling_decisions: dict[str, FamilyCeilingDecision] = {}
        for ward_id in claims:
            decision = self._ceiling.consult(ward_id, now=ts)
            ceiling_decisions[ward_id] = decision

        # ── P3: project SUPPRESS_WHEN_ACTIVE ───────────────────────
        # Every ward that is currently want_visible (and not
        # mandatory_invisible, and not ceiling-enforced) projects its
        # SUPPRESS_WHEN_ACTIVE set onto the suppression map. Multiple
        # suppressors compose: a ward can be suppressed by several at
        # once.
        suppressed_by_other_ward: dict[str, list[str]] = {}
        ward_classes = {type(w).WARD_ID: type(w) for w in self._wards}
        for ward_id in want_visible_ids:
            decision = ceiling_decisions.get(ward_id)
            if decision is not None and decision.enforced:
                continue
            cls = ward_classes.get(ward_id)
            if cls is None:
                continue
            for suppressed_id in cls.SUPPRESS_WHEN_ACTIVE:
                suppressed_by_other_ward.setdefault(suppressed_id, []).append(ward_id)
        suppressed_by_other_ward_tuples = {
            wid: tuple(sorted(suppressors)) for wid, suppressors in suppressed_by_other_ward.items()
        }

        # ── P3: write suppression to ward_properties on every tick ──
        if suppressed_by_other_ward_tuples:
            self._project_suppression_to_ward_properties(suppressed_by_other_ward_tuples)

        # ── P3: WCS row + metrics ──────────────────────────────────
        family_consumed_s = (
            ceiling_decisions[want_visible_ids[0]].family_consumed_s
            if want_visible_ids
            else self._ceiling.family_consumed_seconds(now=ts)
        )
        family_pool_consumed_fraction = (
            family_consumed_s / self._ceiling.family_ceiling_s
            if self._ceiling.family_ceiling_s > 0
            else 0.0
        )

        state = RouterState(
            tick_ts=ts,
            claims=claims,
            mandatory_invisible_ids=mandatory_invisible_ids,
            want_visible_ids=want_visible_ids,
            suppressed_by_other_ward=suppressed_by_other_ward_tuples,
            ceiling_decisions=ceiling_decisions,
            family_pool_consumed_fraction=family_pool_consumed_fraction,
        )
        with self._state_lock:
            self._state = state

        self._update_metrics(state)
        self._write_routing_state(state)

        return state

    # ── P3 internal helpers ──────────────────────────────────────────

    def _project_suppression_to_ward_properties(
        self, suppressed: dict[str, tuple[str, ...]]
    ) -> None:
        """Write ``visible=False`` to ward_properties.json for every
        suppressed ward.

        Per cc-task acceptance criterion: "DURF's
        ``SUPPRESS_WHEN_ACTIVE = frozenset({'album', 'gem', 'grounding_provenance_ticker'})``
        emits to ``ward_properties`` on every router tick, not just at
        render time."

        Defensive: ward_properties depends on an SHM dir that may not
        exist in unit tests. On any failure, log WARNING and continue —
        suppression is best-effort observability glue.
        """
        try:
            from agents.studio_compositor.ward_properties import (
                WardProperties,
                set_many_ward_properties,
            )

            props_by_ward = {ward_id: WardProperties(visible=False) for ward_id in suppressed}
            set_many_ward_properties(props_by_ward, ttl_s=SUPPRESSION_TTL_S)
        except Exception as exc:
            log.warning(
                "activity-router: suppression projection failed (%s suppressed wards): %s",
                len(suppressed),
                exc,
                exc_info=True,
            )

    def _update_metrics(self, state: RouterState) -> None:
        """Publish the 7 P3 metrics for this tick."""
        if not _METRICS:
            return
        try:
            _METRICS["active_wards"].set(len(state.want_visible_ids))
            _METRICS["family_pool_consumed_fraction"].set(state.family_pool_consumed_fraction)
            if not state.want_visible_ids:
                _METRICS["idle_ticks_total"].inc()
            for ward_id, decision in state.ceiling_decisions.items():
                if decision.enforced and ward_id in state.want_visible_ids:
                    _METRICS["ceiling_enforced_total"].labels(ward_id=ward_id).inc()
            for ward_id in state.mandatory_invisible_ids:
                _METRICS["forced_exits_total"].labels(
                    ward_id=ward_id, reason="mandatory_invisible"
                ).inc()
            for ward_id, decision in state.ceiling_decisions.items():
                if decision.enforced and ward_id in state.want_visible_ids:
                    _METRICS["forced_exits_total"].labels(
                        ward_id=ward_id, reason="ceiling_eviction"
                    ).inc()
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("activity-router: metric update failed: %s", exc, exc_info=True)

    def _write_routing_state(self, state: RouterState) -> None:
        """Atomic tmp+rename write of the WCS row to
        ``/dev/shm/hapax-compositor/routing-state.json``.

        Defensive: if the SHM dir is missing (unit tests, container
        misconfig), log DEBUG and continue. The router never raises
        because the writer failed.
        """
        target = self._config.routing_state_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "tick_ts": state.tick_ts,
                "wall_ts": time.time(),
                "want_visible_ids": list(state.want_visible_ids),
                "mandatory_invisible_ids": list(state.mandatory_invisible_ids),
                "suppressed_by_other_ward": {
                    wid: list(suppressors)
                    for wid, suppressors in state.suppressed_by_other_ward.items()
                },
                "ceiling_decisions": {
                    wid: {
                        "consumed_s": d.consumed_s,
                        "ceiling_s": d.ceiling_s,
                        "would_exceed_self": d.would_exceed_self,
                        "would_exceed_family": d.would_exceed_family,
                        "reason": d.reason,
                    }
                    for wid, d in state.ceiling_decisions.items()
                },
                "family_pool_consumed_fraction": state.family_pool_consumed_fraction,
                "family_pool_consumed_s": (
                    state.family_pool_consumed_fraction * self._ceiling.family_ceiling_s
                ),
                "family_pool_ceiling_s": self._ceiling.family_ceiling_s,
            }
            tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
            tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            tmp.replace(target)
        except Exception as exc:
            log.debug(
                "activity-router: routing-state write failed (target=%s): %s",
                target,
                exc,
                exc_info=True,
            )

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
