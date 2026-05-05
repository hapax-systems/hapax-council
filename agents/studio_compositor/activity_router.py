"""ActivityRouter — coordination layer over ActivityRevealMixin wards.

P0 (cc-task ``activity-reveal-ward-p0-base-class``) shipped a stub
router that classifies claims into mandatory-invisible / want-visible /
nominal. P3-phase-3a (cc-task ``activity-reveal-ward-p3-governance``,
PR #2259) added a hardcoded family-ceiling table + per-ward eviction
priorities. **That table was a static expert-system rule and violated
``feedback_no_expert_system_rules`` per the 2026-05-02 24h
independent-auditor batch (Auditor B finding #8).**

Per cc-task ``p3-governance-recruitment-bias-replacement``
(this ship): the table + ceiling decisions + eviction priorities are
**deleted**. The router still records visible-windows into the shared
:class:`WardVisibilityWindowTracker`, but **the decision** about
which ward gets to be visible is moved into the recruitment cascade
inside :func:`shared.affordance_pipeline.AffordancePipeline.select`,
where a soft-prior bias multiplier (proportional to consumed
visible-time) competes with all other affordance scoring inputs.
Constraint emerges from the same pipeline that selects everything
else — no fixed ceilings.

What this module still does:

  * Snapshots ward claims per tick.
  * Classifies into ``mandatory_invisible_ids`` / ``want_visible_ids``
    (no ceiling-eviction reclassification).
  * Projects ``SUPPRESS_WHEN_ACTIVE`` from currently-visible wards
    into ``ward_properties.json`` per tick (closes audit-flagged
    "DURF suppression at render time only" gap).
  * Writes a WCS row to ``/dev/shm/hapax-compositor/routing-state.json``
    per tick.
  * Updates Prometheus metrics.

What this module no longer does (per governance correction):

  * No family-pool ceiling consultation.
  * No per-ward sub-ceiling table or registration.
  * No priority-based eviction order.
  * No ``ceiling_decisions`` map in ``RouterState``.

The visible-window data the router writes feeds the recruitment-bias
read in ``AffordancePipeline.select`` via the shared
:func:`get_default_tracker` singleton. The router is a writer; the
pipeline is a reader; both share one tracker instance per process.

Spec reference (updated):
``hapax-research/specs/2026-05-01-activity-reveal-ward-family-spec.md``
§1.5 (Shared concerns) + §2.6 (Observability) — family-pool ceiling
table is removed; recruitment-bias governance is described in its
place. Supersession doc: see commit log of this PR.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from agents.studio_compositor.activity_family_ceiling import (
    DEFAULT_VISIBILITY_WINDOW_S,
    WardVisibilityWindowTracker,
    get_default_tracker,
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

#: Operator override for the P4 router policy. Invalid values are
#: deliberately fail-open to ``UNCONSTRAINED`` so a typo cannot make a
#: ward disappear from broadcast.
ACTIVITY_ROUTER_POLICY_ENV: str = "HAPAX_ACTIVITY_ROUTER_POLICY"


# ── Prometheus metrics (registry-bound per memory project_compositor_metrics_registry) ──

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
    """Construct the P3 metrics with the splat. Returns ``{}`` if
    prometheus_client is missing.

    Per cc-task ``p3-governance-recruitment-bias-replacement``: the
    ``ceiling_enforced_total`` and ``family_pool_consumed_fraction``
    metrics from the prior phase 3a are removed (no longer applicable
    under recruitment-bias governance). Everything else stays for
    observability of router-tick behavior.
    """
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
        "active_wards": Gauge(
            "activity_reveal_router_active_wards",
            "Wards with want_visible=True and not mandatory_invisible at last tick.",
            **_metric_kwargs,
        ),
        "ward_visible_time_bias": Gauge(
            "activity_reveal_ward_visible_time_bias",
            "Per-ward recruitment-bias multiplier from visible-time tracker [BIAS_FLOOR, BIAS_CEILING].",
            ["ward_id"],
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
            "Forced exits per ward per reason (mandatory_invisible only — no ceiling-eviction).",
            ["ward_id", "reason"],
            **_metric_kwargs,
        ),
    }


_METRICS: dict[str, Any] = _build_metrics()


class RouterPolicy(StrEnum):
    """Activity-reveal ward visibility policy.

    ``UNCONSTRAINED`` is the historical P0/P3 behavior: every ward that
    wants visibility remains eligible. ``FIRST_WINS`` and
    ``PRIORITY_SCORED`` are opt-in mutex policies for later family
    growth when multiple activity wards can compete for the same visual
    plane.
    """

    UNCONSTRAINED = "unconstrained"
    FIRST_WINS = "first_wins"
    PRIORITY_SCORED = "priority_scored"

    @classmethod
    def coerce(cls, value: str | RouterPolicy | None) -> RouterPolicy:
        if isinstance(value, cls):
            return value
        raw = (value or cls.UNCONSTRAINED.value).strip().lower().replace("-", "_")
        try:
            return cls(raw)
        except ValueError:
            log.warning(
                "invalid %s=%r; falling back to %s",
                ACTIVITY_ROUTER_POLICY_ENV,
                value,
                cls.UNCONSTRAINED.value,
            )
            return cls.UNCONSTRAINED

    @classmethod
    def from_env(cls) -> RouterPolicy:
        return cls.coerce(os.environ.get(ACTIVITY_ROUTER_POLICY_ENV))


@dataclass
class RouterConfig:
    """Router policy.

    P0 honored ``tick_hz`` only. P3-phase-3a added family-pool ceiling
    fields; cc-task ``p3-governance-recruitment-bias-replacement``
    removed them (no static thresholds; bias emerges from recruitment).
    P4 wires the rest.
    """

    tick_hz: float = 2.0
    visibility_ceiling_pct: float = 0.15
    rolling_window_s: float = DEFAULT_VISIBILITY_WINDOW_S
    mutex: bool = True
    entry_debounce_s: float = 5.0
    mandatory_exit_transition: str = "zero-cut-out"
    normal_exit_transition: str = "ticker-scroll-out"
    normal_entry_transition: str = "ticker-scroll-in"

    # P3 observability — write the WCS row each tick.
    routing_state_path: Path = ROUTING_STATE_PATH
    policy: RouterPolicy = field(default_factory=RouterPolicy.from_env)

    def __post_init__(self) -> None:
        self.policy = RouterPolicy.coerce(self.policy)


@dataclass
class RouterState:
    """One-tick snapshot of router-side observability state.

    Per cc-task ``p3-governance-recruitment-bias-replacement``: the
    ``ceiling_decisions`` field and ``family_pool_consumed_fraction``
    field from the prior phase 3a are removed. The new
    ``ward_visible_time_bias`` map is informational only — it mirrors
    the bias values the affordance pipeline reads via
    :func:`get_default_tracker`.
    """

    tick_ts: float
    claims: dict[str, VisibilityClaim] = field(default_factory=dict)
    mandatory_invisible_ids: tuple[str, ...] = ()
    want_visible_ids: tuple[str, ...] = ()
    suppressed_by_other_ward: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """Map of suppressed ward_id -> tuple of suppressor ward IDs that
    forced this ward to invisible this tick."""
    policy_blocked_ids: tuple[str, ...] = ()
    """Ward IDs that wanted visibility but were filtered by the active
    ``RouterPolicy`` mutex."""
    ward_visible_time_bias: dict[str, float] = field(default_factory=dict)
    """Per-ward recruitment-bias multiplier from the shared
    visibility-window tracker. Informational mirror of what the
    affordance pipeline reads; not a decision input on the router side."""


class ActivityRouter:
    """Coordination layer over a set of ``ActivityRevealMixin`` wards.

    P0 surface:

      - ``__init__``: register wards.
      - ``tick``: snapshot every ward's claim, classify into
        mandatory-invisible / want-visible / nominal. Never raises.
      - ``start`` / ``stop``: lifecycle.
      - ``last_state``: thread-safe snapshot of the most recent tick.

    P4 adds opt-in mutex/priority policy while preserving the default
    unconstrained behavior.
    """

    def __init__(
        self,
        wards: Sequence[ActivityRevealMixin],
        config: RouterConfig | None = None,
        *,
        visibility_tracker: WardVisibilityWindowTracker | None = None,
    ) -> None:
        self._wards: tuple[ActivityRevealMixin, ...] = tuple(wards)
        self._config = config if config is not None else RouterConfig()
        self._state_lock = threading.Lock()
        self._state = RouterState(tick_ts=time.monotonic())
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stopped = False
        # Per cc-task p3-governance-recruitment-bias-replacement:
        # use the process-shared tracker by default. Tests inject a
        # private tracker to isolate state.
        self._tracker = (
            visibility_tracker if visibility_tracker is not None else get_default_tracker()
        )
        # Track per-ward visible-window cursor so each tick can close
        # the elapsed interval into the shared tracker. This feeds the
        # P3 recruitment-bias surface and avoids waiting for a final
        # "exit" tick before visible-time becomes observable.
        self._open_windows: dict[str, float] = {}
        self._active_policy_winner: str | None = None

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
        self._record_visibility_intervals((), time.monotonic())

    # ── Public surface ───────────────────────────────────────────────

    @property
    def wards(self) -> tuple[ActivityRevealMixin, ...]:
        return self._wards

    @property
    def policy(self) -> RouterPolicy:
        return self._config.policy

    def last_state(self) -> RouterState:
        """Thread-safe snapshot of the latest tick state."""
        with self._state_lock:
            return self._state

    def describe(self) -> dict[str, Any]:
        return {
            "tick_hz": self._config.tick_hz,
            "policy": self.policy.value,
            "ward_count": len(self._wards),
            "ward_ids": [type(w).WARD_ID for w in self._wards],
        }

    def tick(self, *, now: float | None = None) -> RouterState:
        """One tick of the router. Snapshots claims, projects suppression,
        records visibility windows for the bias tracker, writes WCS row.

        Per cc-task ``p3-governance-recruitment-bias-replacement``:
        the router does NOT make ceiling decisions or evict wards. It
        only writes to the shared visibility-window tracker and emits
        observability state. The decision about which ward gets
        visible time is made downstream by AffordancePipeline.select
        applying the bias.
        """
        ts = time.monotonic() if now is None else now
        claims: dict[str, VisibilityClaim] = {}
        for ward in self._wards:
            ward_id = type(ward).WARD_ID
            try:
                ward.poll_once(now=ts)
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
        candidate_list: list[str] = []
        seen_candidates: set[str] = set()
        for ward in self._wards:
            ward_id = type(ward).WARD_ID
            if ward_id in seen_candidates:
                continue
            claim = claims.get(ward_id)
            if claim is None or not claim.want_visible or claim.mandatory_invisible:
                continue
            candidate_list.append(ward_id)
            seen_candidates.add(ward_id)
        candidate_ids = tuple(candidate_list)
        want_visible_ids, policy_blocked_ids = self._apply_policy(candidate_ids, claims)

        # ── Project SUPPRESS_WHEN_ACTIVE ───────────────────────────
        # Every ward that is currently want_visible projects its
        # SUPPRESS_WHEN_ACTIVE set onto the suppression map. Multiple
        # suppressors compose: a ward can be suppressed by several at once.
        suppressed_by_other_ward: dict[str, list[str]] = {}
        ward_classes = {type(w).WARD_ID: type(w) for w in self._wards}
        for ward_id in want_visible_ids:
            cls = ward_classes.get(ward_id)
            if cls is None:
                continue
            for suppressed_id in cls.SUPPRESS_WHEN_ACTIVE:
                suppressed_by_other_ward.setdefault(suppressed_id, []).append(ward_id)
        suppressed_by_other_ward_tuples = {
            wid: tuple(sorted(suppressors)) for wid, suppressors in suppressed_by_other_ward.items()
        }

        # ── Write suppression / policy blocks to ward_properties on every tick ─────
        invisible_wards = set(suppressed_by_other_ward_tuples)
        invisible_wards.update(policy_blocked_ids)
        if invisible_wards:
            self._project_invisible_to_ward_properties(invisible_wards)

        self._record_visibility_intervals(want_visible_ids, ts)

        # ── Compute visibility-time bias per ward (informational mirror) ──
        ward_visible_time_bias: dict[str, float] = {
            ward_id: self._tracker.bias_score(ward_id, now=ts) for ward_id in claims
        }

        state = RouterState(
            tick_ts=ts,
            claims=claims,
            mandatory_invisible_ids=mandatory_invisible_ids,
            want_visible_ids=want_visible_ids,
            suppressed_by_other_ward=suppressed_by_other_ward_tuples,
            policy_blocked_ids=policy_blocked_ids,
            ward_visible_time_bias=ward_visible_time_bias,
        )
        with self._state_lock:
            self._state = state

        self._update_metrics(state)
        self._write_routing_state(state)

        return state

    # ── Internal helpers ─────────────────────────────────────────────

    def _apply_policy(
        self,
        candidate_ids: tuple[str, ...],
        claims: dict[str, VisibilityClaim],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return ``(visible_ids, policy_blocked_ids)`` for this tick."""
        if not candidate_ids:
            self._active_policy_winner = None
            return (), ()
        if self.policy is RouterPolicy.UNCONSTRAINED:
            return tuple(sorted(candidate_ids)), ()

        candidate_set = set(candidate_ids)
        if self.policy is RouterPolicy.FIRST_WINS:
            current = getattr(self, "_active_policy_winner", None)
            winner = current if current in candidate_set else candidate_ids[0]
        else:
            winner = min(
                candidate_ids,
                key=lambda ward_id: (
                    -int(getattr(self._ward_classes_by_id().get(ward_id), "priority", 0)),
                    ward_id,
                ),
            )
        self._active_policy_winner = winner
        visible = (winner,)
        blocked = tuple(sorted(ward_id for ward_id in candidate_set if ward_id != winner))
        # Keep ``claims`` referenced in the signature so future policy
        # scoring can include claim.score without changing the helper API.
        del claims
        return visible, blocked

    def _ward_classes_by_id(self) -> dict[str, type[ActivityRevealMixin]]:
        return {type(ward).WARD_ID: type(ward) for ward in self._wards}

    def _record_visibility_intervals(self, visible_ids: tuple[str, ...], ts: float) -> None:
        """Close per-tick visible intervals into the shared tracker and
        each ward's local ceiling counter."""
        visible = set(visible_ids)
        wards_by_id = {type(ward).WARD_ID: ward for ward in self._wards}
        for ward_id in tuple(self._open_windows):
            start = self._open_windows[ward_id]
            if ts > start:
                self._tracker.mark_visible_window(ward_id, start, ts)
                ward = wards_by_id.get(ward_id)
                if ward is not None:
                    ward.mark_visible_window(start, ts)
                if _METRICS:
                    try:
                        _METRICS["visible_seconds_total"].labels(ward_id=ward_id).inc(ts - start)
                    except Exception:
                        log.debug("visible_seconds_total metric update failed", exc_info=True)
            if ward_id in visible:
                self._open_windows[ward_id] = ts
            else:
                del self._open_windows[ward_id]
        for ward_id in visible:
            self._open_windows.setdefault(ward_id, ts)

    def _project_invisible_to_ward_properties(self, ward_ids: set[str]) -> None:
        """Write ``visible=False`` to ward_properties.json for every
        suppressed or policy-blocked ward.

        Defensive: ward_properties depends on an SHM dir that may not
        exist in unit tests. On any failure, log WARNING and continue —
        suppression is best-effort observability glue.
        """
        try:
            from agents.studio_compositor.ward_properties import (
                WardProperties,
                set_many_ward_properties,
            )

            props_by_ward = {ward_id: WardProperties(visible=False) for ward_id in ward_ids}
            set_many_ward_properties(props_by_ward, ttl_s=SUPPRESSION_TTL_S)
        except Exception as exc:
            log.warning(
                "activity-router: invisible projection failed (%s wards): %s",
                len(ward_ids),
                exc,
                exc_info=True,
            )

    def _update_metrics(self, state: RouterState) -> None:
        """Publish the P3 metrics for this tick."""
        if not _METRICS:
            return
        try:
            _METRICS["active_wards"].set(len(state.want_visible_ids))
            if not state.want_visible_ids:
                _METRICS["idle_ticks_total"].inc()
            for ward_id in state.mandatory_invisible_ids:
                _METRICS["forced_exits_total"].labels(
                    ward_id=ward_id, reason="mandatory_invisible"
                ).inc()
            for ward_id, bias in state.ward_visible_time_bias.items():
                _METRICS["ward_visible_time_bias"].labels(ward_id=ward_id).set(bias)
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
                "policy": self.policy.value,
                "policy_blocked_ids": list(state.policy_blocked_ids),
                "ward_visible_time_bias": dict(state.ward_visible_time_bias),
                "rolling_window_s": self._tracker.window_s,
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
    "ACTIVITY_ROUTER_POLICY_ENV",
    "ActivityRouter",
    "RouterConfig",
    "RouterPolicy",
    "RouterState",
]
