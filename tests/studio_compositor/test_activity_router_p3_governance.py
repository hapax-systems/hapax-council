"""P3 governance regression pins for ActivityRouter under the
recruitment-bias replacement (cc-task
``p3-governance-recruitment-bias-replacement``).

The prior P3-phase-3a (#2259) shipped a hardcoded family-ceiling
table + per-ward eviction priorities. The 2026-05-02 24h
independent-auditor batch (Auditor B finding #8) flagged the table as
a static expert-system rule violating
``feedback_no_expert_system_rules``. This test file validates the
**replacement** governance: visibility-window tracking + multiplicative
bias score read by the affordance pipeline. No static thresholds, no
eviction priorities.

Pins:

1. ``test_no_static_ceiling_table_in_module`` — the module no longer
   exports any of the deleted symbols (``DEFAULT_WARD_SUB_CEILINGS``,
   ``WardCeilingPolicy``, ``FamilyCeilingDecision``,
   ``FamilyCeilingTracker``).
2. ``test_visible_time_bias_score_linear_ramp`` — the bias formula
   maps consumed-seconds linearly from BIAS_CEILING (no consumption)
   to BIAS_FLOOR (full-window saturation).
3. ``test_dominant_ward_loses_to_competitor_after_bias`` —
   regression pin for the cc-task acceptance criterion: with one ward
   dominating visible-time, the recruitment cycle's biased score for
   that ward is reduced enough that a competitor wins.
4. ``test_router_no_longer_consults_ceiling`` — RouterState no longer
   carries ``ceiling_decisions`` or ``family_pool_consumed_fraction``.
5. ``test_router_writes_visibility_bias_to_routing_state`` — the WCS
   row now carries ``ward_visible_time_bias`` instead of
   ``ceiling_decisions``.
6. ``test_suppression_still_ward_specific`` — suppression contract
   from #2259 is preserved (regression).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from agents.studio_compositor.activity_family_ceiling import (
    BIAS_CEILING,
    BIAS_FLOOR,
    DEFAULT_VISIBILITY_WINDOW_S,
    WardVisibilityWindowTracker,
    visible_time_bias_score,
)
from agents.studio_compositor.activity_reveal_ward import ActivityRevealMixin
from agents.studio_compositor.activity_router import (
    ActivityRouter,
    RouterConfig,
    RouterState,
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


# ── 6 cc-task acceptance / regression pins ──────────────────────────


class TestRecruitmentBiasReplacementPins(unittest.TestCase):
    def test_no_static_ceiling_table_in_module(self) -> None:
        """The module no longer exports any of the deleted symbols
        from the prior phase 3a (PR #2259) static-table API."""
        from agents.studio_compositor import activity_family_ceiling as mod

        for deleted in (
            "DEFAULT_WARD_SUB_CEILINGS",
            "DEFAULT_FAMILY_CEILING_PCT",
            "DEFAULT_FAMILY_WINDOW_S",
            "WardCeilingPolicy",
            "FamilyCeilingDecision",
            "FamilyCeilingTracker",
        ):
            self.assertFalse(
                hasattr(mod, deleted),
                f"{deleted} must NOT exist in activity_family_ceiling — "
                "violates feedback_no_expert_system_rules per Auditor B finding #8",
            )

    def test_visible_time_bias_score_linear_ramp(self) -> None:
        """Bias formula: linear from BIAS_CEILING (consumed=0) to
        BIAS_FLOOR (consumed >= window_s). Pin the formula so a future
        change to either bound forces a deliberate test update."""
        # Zero consumption → identity (no penalty).
        self.assertAlmostEqual(visible_time_bias_score(0.0, window_s=3600.0), BIAS_CEILING)
        # Full saturation → floor.
        self.assertAlmostEqual(visible_time_bias_score(3600.0, window_s=3600.0), BIAS_FLOOR)
        # Half consumption → midpoint.
        self.assertAlmostEqual(
            visible_time_bias_score(1800.0, window_s=3600.0),
            (BIAS_CEILING + BIAS_FLOOR) / 2.0,
        )
        # Over-saturation clamps to floor (never below).
        self.assertAlmostEqual(visible_time_bias_score(7200.0, window_s=3600.0), BIAS_FLOOR)

    def test_dominant_ward_loses_to_competitor_after_bias(self) -> None:
        """cc-task acceptance: with one ward dominating visible-time,
        the next recruitment cycle's biased score for that ward is
        reduced enough that a competitor wins.

        Setup: ward "dominant" has consumed full-window visible time
        (bias = 0.5); ward "competitor" has consumed nothing
        (bias = 1.0). At equal pre-bias scores, competitor wins after
        the multiplicative bias is applied. Without the bias, ties
        would resolve arbitrarily."""
        tracker = WardVisibilityWindowTracker(window_s=3600.0)
        # Dominant ward: visible the entire trailing window.
        tracker.mark_visible_window("dominant", start_ts=0.0, end_ts=3600.0)
        # Competitor: no visible window recorded.
        now = 3600.0
        dominant_bias = tracker.bias_score("dominant", now=now)
        competitor_bias = tracker.bias_score("competitor", now=now)
        self.assertAlmostEqual(dominant_bias, BIAS_FLOOR)
        self.assertAlmostEqual(competitor_bias, BIAS_CEILING)
        # Equal pre-bias scores → competitor wins after bias.
        pre_bias_score = 0.7
        dominant_post = pre_bias_score * dominant_bias
        competitor_post = pre_bias_score * competitor_bias
        self.assertGreater(
            competitor_post,
            dominant_post,
            "Competitor must out-score dominant ward after visible-time bias is applied "
            "(this is the cc-task's load-bearing acceptance criterion)",
        )

    def test_router_no_longer_consults_ceiling(self) -> None:
        """RouterState no longer carries ceiling_decisions or
        family_pool_consumed_fraction. The ward_visible_time_bias map
        is the new informational surface."""
        state = RouterState(tick_ts=0.0)
        for deleted in ("ceiling_decisions", "family_pool_consumed_fraction"):
            self.assertFalse(
                hasattr(state, deleted),
                f"RouterState.{deleted} must NOT exist — violates "
                "feedback_no_expert_system_rules per Auditor B finding #8",
            )
        self.assertTrue(hasattr(state, "ward_visible_time_bias"))
        self.assertIsInstance(state.ward_visible_time_bias, dict)

    def test_router_writes_visibility_bias_to_routing_state(self) -> None:
        """The WCS row now carries ward_visible_time_bias + rolling_window_s
        instead of the deleted ceiling_decisions / family_pool_*."""
        suppressor = _SuppressorWard()
        target = _TargetWard()
        try:
            for w in (suppressor, target):
                w.poll_once()
            tmp_dir = Path("/tmp/test-activity-router-bias-routing-state")
            tmp_dir.mkdir(parents=True, exist_ok=True)
            target_path = tmp_dir / "routing-state.json"
            if target_path.exists():
                target_path.unlink()
            cfg = RouterConfig(routing_state_path=target_path)
            tracker = WardVisibilityWindowTracker(window_s=3600.0)
            router = ActivityRouter(
                wards=[suppressor, target], config=cfg, visibility_tracker=tracker
            )
            try:
                router.tick(now=42.0)
            finally:
                router.stop()
            self.assertTrue(target_path.exists())
            payload = json.loads(target_path.read_text(encoding="utf-8"))
            for required in (
                "tick_ts",
                "want_visible_ids",
                "mandatory_invisible_ids",
                "suppressed_by_other_ward",
                "ward_visible_time_bias",
                "rolling_window_s",
            ):
                self.assertIn(required, payload, f"routing-state.json missing key: {required}")
            for deleted in (
                "ceiling_decisions",
                "family_pool_consumed_fraction",
                "family_pool_ceiling_s",
            ):
                self.assertNotIn(
                    deleted,
                    payload,
                    f"routing-state.json must NOT carry deleted key {deleted!r}",
                )
        finally:
            for w in (suppressor, target):
                w.stop()

    def test_suppression_still_ward_specific(self) -> None:
        """Regression pin from #2259: ward A's
        ``SUPPRESS_WHEN_ACTIVE = {'a-target'}`` suppresses ONLY
        a-target; unrelated wards stay un-suppressed."""
        suppressor = _SuppressorWard()
        target = _TargetWard()
        unrelated = _UnrelatedWard()
        try:
            for w in (suppressor, target, unrelated):
                w.poll_once()
            tracker = WardVisibilityWindowTracker(window_s=3600.0)
            router = ActivityRouter(
                wards=[suppressor, target, unrelated],
                visibility_tracker=tracker,
            )
            try:
                state = router.tick(now=100.0)
            finally:
                router.stop()
        finally:
            for w in (suppressor, target, unrelated):
                w.stop()
        self.assertIn("a-target", state.suppressed_by_other_ward)
        self.assertNotIn("unrelated", state.suppressed_by_other_ward)
        self.assertEqual(
            state.suppressed_by_other_ward["a-target"],
            ("fixture-suppressor",),
        )


# ── WardVisibilityWindowTracker (replaces FamilyCeilingTracker tests) ──


class TestWardVisibilityWindowTracker(unittest.TestCase):
    def test_consumed_seconds_within_window(self) -> None:
        tracker = WardVisibilityWindowTracker(window_s=100.0)
        tracker.mark_visible_window("w1", 0.0, 30.0)
        self.assertAlmostEqual(tracker.consumed_seconds("w1", now=50.0), 30.0)

    def test_consumed_seconds_trims_at_window_edge(self) -> None:
        tracker = WardVisibilityWindowTracker(window_s=100.0)
        tracker.mark_visible_window("w1", 0.0, 50.0)
        # At now=120, cutoff is 20; the (0, 50) interval is trimmed to (20, 50) = 30s.
        self.assertAlmostEqual(tracker.consumed_seconds("w1", now=120.0), 30.0)

    def test_intervals_outside_window_evicted(self) -> None:
        tracker = WardVisibilityWindowTracker(window_s=100.0)
        tracker.mark_visible_window("w1", 0.0, 10.0)
        # At now=200, the (0, 10) interval is fully out of the window.
        self.assertEqual(tracker.consumed_seconds("w1", now=200.0), 0.0)

    def test_unknown_ward_returns_zero(self) -> None:
        tracker = WardVisibilityWindowTracker()
        self.assertEqual(tracker.consumed_seconds("never-seen", now=100.0), 0.0)

    def test_default_window_matches_mixin_constant(self) -> None:
        """The tracker's default window must equal the mixin's
        DEFAULT_ROLLING_WINDOW_S so per-ward + tracker share an epoch."""
        from agents.studio_compositor.activity_reveal_ward import DEFAULT_ROLLING_WINDOW_S

        self.assertEqual(DEFAULT_VISIBILITY_WINDOW_S, DEFAULT_ROLLING_WINDOW_S)

    def test_tracker_singleton_lazy_init(self) -> None:
        from agents.studio_compositor.activity_family_ceiling import (
            get_default_tracker,
            set_default_tracker,
        )

        # Reset singleton so this test is self-contained.
        set_default_tracker(None)
        t1 = get_default_tracker()
        t2 = get_default_tracker()
        self.assertIs(t1, t2, "singleton must return the same instance")
        # Cleanup so other tests get a fresh singleton.
        set_default_tracker(None)
