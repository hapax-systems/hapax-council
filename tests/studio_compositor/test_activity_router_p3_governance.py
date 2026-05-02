"""P3 governance regression pins for ActivityRouter (cc-task
``activity-reveal-ward-p3-governance``).

The 3 cc-task acceptance pins:

1. ``test_activity_router_ceiling_window_is_60_minutes`` — family-pool
   ceiling window matches the per-ward mixin's rolling window
   (60 min default per
   ``activity_reveal_ward.DEFAULT_ROLLING_WINDOW_S``).
2. ``test_activity_router_metrics_use_metric_kwargs_splat`` — the 7
   P3 metrics register against the compositor's REGISTRY (or no-op
   when the compositor module isn't importable), per memory
   ``project_compositor_metrics_registry``.
3. ``test_activity_router_suppression_is_ward_specific`` — when ward A
   has ``SUPPRESS_WHEN_ACTIVE = {"a-target"}``, ONLY ``a-target`` is
   suppressed; unrelated wards are not collateral damage.

Plus 6 supporting pins on the family-pool ceiling tracker, the WCS
row writer, and the suppression-on-tick wiring.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agents.studio_compositor.activity_family_ceiling import (
    DEFAULT_FAMILY_WINDOW_S,
    FamilyCeilingTracker,
)
from agents.studio_compositor.activity_reveal_ward import (
    DEFAULT_ROLLING_WINDOW_S,
    ActivityRevealMixin,
)
from agents.studio_compositor.activity_router import (
    _METRICS,
    ActivityRouter,
    RouterConfig,
    _metric_kwargs,
)

# ── Test fixture wards ───────────────────────────────────────────────


class _SuppressorWard(ActivityRevealMixin):
    """Ward that wants to be visible AND suppresses ``a-target``."""

    WARD_ID = "fixture-suppressor"
    SOURCE_KIND = "cairo"
    DEFAULT_HYSTERESIS_S = 1.5
    SUPPRESS_WHEN_ACTIVE = frozenset({"a-target"})

    def __init__(self) -> None:
        super().__init__(start_poll_thread=False)

    def _compute_claim_score(self) -> float:
        return 0.9

    def _want_visible(self) -> bool:
        return True

    def _mandatory_invisible(self) -> bool:
        return False

    def _claim_source_refs(self) -> tuple[str, ...]:
        return ("fixture-suppressor-src",)

    def _describe_source_registration(self) -> dict[str, Any]:
        return {"id": self.WARD_ID, "kind": self.SOURCE_KIND}


class _TargetWard(ActivityRevealMixin):
    """Ward that should be suppressed by ``_SuppressorWard``."""

    WARD_ID = "a-target"
    SOURCE_KIND = "cairo"
    DEFAULT_HYSTERESIS_S = 1.5

    def __init__(self) -> None:
        super().__init__(start_poll_thread=False)

    def _compute_claim_score(self) -> float:
        return 0.5

    def _want_visible(self) -> bool:
        return True

    def _mandatory_invisible(self) -> bool:
        return False

    def _claim_source_refs(self) -> tuple[str, ...]:
        return ("a-target-src",)

    def _describe_source_registration(self) -> dict[str, Any]:
        return {"id": self.WARD_ID, "kind": self.SOURCE_KIND}


class _UnrelatedWard(ActivityRevealMixin):
    """Ward that the suppressor does NOT mention — must NOT be
    suppressed (test pin against collateral damage)."""

    WARD_ID = "unrelated"
    SOURCE_KIND = "cairo"
    DEFAULT_HYSTERESIS_S = 1.5

    def __init__(self) -> None:
        super().__init__(start_poll_thread=False)

    def _compute_claim_score(self) -> float:
        return 0.4

    def _want_visible(self) -> bool:
        return True

    def _mandatory_invisible(self) -> bool:
        return False

    def _claim_source_refs(self) -> tuple[str, ...]:
        return ()

    def _describe_source_registration(self) -> dict[str, Any]:
        return {"id": self.WARD_ID, "kind": self.SOURCE_KIND}


# ── 3 P3 cc-task acceptance pins ─────────────────────────────────────


class TestP3CcTaskAcceptancePins(unittest.TestCase):
    def test_activity_router_ceiling_window_is_60_minutes(self) -> None:
        """Family-pool ceiling rolling window = 60 min, matching the
        per-ward mixin's DEFAULT_ROLLING_WINDOW_S. If these drift apart,
        the per-ward ceiling and the family-pool ceiling will be using
        different epochs and the governance contract is incoherent."""
        self.assertEqual(DEFAULT_FAMILY_WINDOW_S, 3600.0)
        self.assertEqual(DEFAULT_ROLLING_WINDOW_S, 3600.0)
        self.assertEqual(DEFAULT_FAMILY_WINDOW_S, DEFAULT_ROLLING_WINDOW_S)
        # Default RouterConfig must use the same window.
        cfg = RouterConfig()
        self.assertEqual(cfg.rolling_window_s, DEFAULT_FAMILY_WINDOW_S)
        # And a tracker built from defaults reports 25% of 60min = 15min ceiling.
        tracker = FamilyCeilingTracker()
        self.assertAlmostEqual(tracker.window_s, 3600.0)
        self.assertAlmostEqual(tracker.family_ceiling_s, 0.25 * 3600.0)

    def test_activity_router_metrics_use_metric_kwargs_splat(self) -> None:
        """All P3 metrics MUST register via the **_metric_kwargs splat
        pattern per memory project_compositor_metrics_registry. When
        the compositor module is importable, _metric_kwargs MUST carry
        the compositor REGISTRY so /metrics on :9482 sees these. When
        not importable (officium / tests without studio deps), the
        kwargs MUST be empty so registration falls back to the default
        registry without crashing."""
        # _metric_kwargs is either {} or {"registry": <CollectorRegistry>}.
        self.assertIsInstance(_metric_kwargs, dict)
        if _metric_kwargs:
            self.assertIn("registry", _metric_kwargs)
            # When carrying a registry, every metric we built must
            # have been registered against it (verified indirectly by
            # _METRICS being non-empty).
            self.assertTrue(_METRICS, "metrics should be registered when registry is available")
        # The 7 metrics must all be present whenever prometheus_client
        # is importable (which it always is in CI per pyproject.toml).
        if _METRICS:
            expected = {
                "visible_seconds_total",
                "ceiling_enforced_total",
                "active_wards",
                "family_pool_consumed_fraction",
                "transitions_total",
                "idle_ticks_total",
                "forced_exits_total",
            }
            self.assertEqual(set(_METRICS.keys()), expected)

    def test_activity_router_suppression_is_ward_specific(self) -> None:
        """When ward A's SUPPRESS_WHEN_ACTIVE = {'a-target'}, ONLY
        'a-target' is suppressed. 'unrelated' (also visible, also
        unmentioned by the suppressor) MUST NOT appear in the
        suppression map. Catches over-broad suppression bugs that would
        cascade into unrelated ward families."""
        suppressor = _SuppressorWard()
        target = _TargetWard()
        unrelated = _UnrelatedWard()
        try:
            for w in (suppressor, target, unrelated):
                w.poll_once()
            router = ActivityRouter(wards=[suppressor, target, unrelated])
            try:
                state = router.tick(now=100.0)
            finally:
                router.stop()
        finally:
            for w in (suppressor, target, unrelated):
                w.stop()
        # Exact ward-specificity:
        self.assertIn("a-target", state.suppressed_by_other_ward)
        self.assertNotIn("unrelated", state.suppressed_by_other_ward)
        self.assertEqual(
            state.suppressed_by_other_ward["a-target"],
            ("fixture-suppressor",),
            "suppressor identity must be recorded so observability can attribute the suppression",
        )


# ── Family-pool ceiling tracker ──────────────────────────────────────


class TestFamilyCeilingTracker(unittest.TestCase):
    def test_register_ward_sets_policy(self) -> None:
        tracker = FamilyCeilingTracker()
        tracker.register_ward("durf", ceiling_pct=0.15, eviction_priority=4)
        policy = tracker.policy("durf")
        self.assertIsNotNone(policy)
        assert policy is not None  # mypy
        self.assertEqual(policy.ceiling_pct, 0.15)
        self.assertEqual(policy.eviction_priority, 4)

    def test_consult_within_ceiling_does_not_enforce(self) -> None:
        tracker = FamilyCeilingTracker()
        tracker.register_ward("durf", ceiling_pct=0.15, eviction_priority=4)
        # No prior visibility — both ceilings open.
        decision = tracker.consult("durf", now=100.0)
        self.assertFalse(decision.would_exceed_self)
        self.assertFalse(decision.would_exceed_family)
        self.assertFalse(decision.enforced)

    def test_consult_self_ceiling_exceeded(self) -> None:
        tracker = FamilyCeilingTracker(window_s=3600.0)
        tracker.register_ward("durf", ceiling_pct=0.15, eviction_priority=4)
        # 0.15 * 3600 = 540s. Mark 600s of visibility ending at 600s.
        tracker.mark_visible_window("durf", start_ts=0.0, end_ts=600.0)
        decision = tracker.consult("durf", now=600.0)
        self.assertTrue(decision.would_exceed_self)
        self.assertTrue(decision.enforced)
        self.assertIn("self", decision.reason)

    def test_consult_family_ceiling_exceeded(self) -> None:
        tracker = FamilyCeilingTracker(window_s=3600.0, family_ceiling_pct=0.25)
        # Family ceiling = 0.25 * 3600 = 900s.
        tracker.register_ward("durf", ceiling_pct=0.15, eviction_priority=4)
        tracker.register_ward("m8", ceiling_pct=0.12, eviction_priority=3)
        # DURF + M8 together = 1000s, exceeding family pool (900s).
        tracker.mark_visible_window("durf", start_ts=0.0, end_ts=500.0)
        tracker.mark_visible_window("m8", start_ts=500.0, end_ts=1000.0)
        decision = tracker.consult("durf", now=1000.0)
        self.assertTrue(decision.would_exceed_family)
        self.assertTrue(decision.enforced)

    def test_evictable_order_lowest_priority_first(self) -> None:
        tracker = FamilyCeilingTracker()
        tracker.register_ward("durf", 0.15, 4)
        tracker.register_ward("m8", 0.12, 3)
        tracker.register_ward("polyend", 0.10, 2)
        tracker.register_ward("steam_deck", 0.08, 1)
        order = tracker.evictable_order(now=0.0)
        self.assertEqual([p.ward_id for p in order], ["steam_deck", "polyend", "m8", "durf"])

    def test_intervals_outside_window_evicted(self) -> None:
        # Use a wider family ceiling so we can register a ward with
        # ceiling_pct=0.25 inside it.
        tracker = FamilyCeilingTracker(window_s=100.0, family_ceiling_pct=0.5)
        tracker.register_ward("durf", 0.25, 4)
        # Old interval (>100s ago) is evicted; recent interval counts.
        tracker.mark_visible_window("durf", start_ts=0.0, end_ts=10.0)
        # At now=200, the old interval is fully out of the window.
        self.assertEqual(tracker.consumed_seconds("durf", now=200.0), 0.0)


# ── WCS row writer ────────────────────────────────────────────────────


class TestRoutingStateRowWriter(unittest.TestCase):
    def test_routing_state_written_on_tick(self) -> None:
        """The router writes routing-state.json atomically on every tick.
        Pinned because the family observability dashboard depends on
        this surface refreshing per tick."""
        suppressor = _SuppressorWard()
        target = _TargetWard()
        try:
            for w in (suppressor, target):
                w.poll_once()
            tmp_dir = Path("/tmp/test-activity-router-routing-state")
            tmp_dir.mkdir(parents=True, exist_ok=True)
            target_path = tmp_dir / "routing-state.json"
            if target_path.exists():
                target_path.unlink()
            cfg = RouterConfig(routing_state_path=target_path)
            router = ActivityRouter(wards=[suppressor, target], config=cfg)
            try:
                router.tick(now=42.0)
            finally:
                router.stop()
            self.assertTrue(target_path.exists())
            payload = json.loads(target_path.read_text(encoding="utf-8"))
            # Pin the shape expected by the dashboard.
            for key in (
                "tick_ts",
                "wall_ts",
                "want_visible_ids",
                "mandatory_invisible_ids",
                "suppressed_by_other_ward",
                "ceiling_decisions",
                "family_pool_consumed_fraction",
                "family_pool_ceiling_s",
            ):
                self.assertIn(key, payload, f"routing-state.json missing key: {key}")
            self.assertEqual(payload["tick_ts"], 42.0)
            self.assertIn("a-target", payload["suppressed_by_other_ward"])
        finally:
            for w in (suppressor, target):
                w.stop()


# ── Suppression projection to ward_properties ─────────────────────────


class TestSuppressionProjectionPerTick(unittest.TestCase):
    def test_suppression_calls_set_many_ward_properties_per_tick(self) -> None:
        """The router projects suppression to ward_properties on every
        tick, not at render time. Pinned with a mock so the test
        doesn't depend on /dev/shm being writable."""
        suppressor = _SuppressorWard()
        target = _TargetWard()
        try:
            for w in (suppressor, target):
                w.poll_once()
            router = ActivityRouter(wards=[suppressor, target])
            try:
                with patch(
                    "agents.studio_compositor.ward_properties.set_many_ward_properties"
                ) as mock_set:
                    router.tick(now=10.0)
            finally:
                router.stop()
        finally:
            for w in (suppressor, target):
                w.stop()
        # set_many_ward_properties was called with at least 'a-target'.
        self.assertTrue(mock_set.called, "router did not project suppression to ward_properties")
        kwargs_props = mock_set.call_args.args[0]
        self.assertIn("a-target", kwargs_props)
        # And the projected WardProperties has visible=False (the
        # suppression marker that gates render).
        self.assertFalse(kwargs_props["a-target"].visible)
