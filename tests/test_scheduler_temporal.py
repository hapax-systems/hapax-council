"""Tests for temporal context in scheduler (Phase 6)."""

from __future__ import annotations

from agents.content_scheduler import (
    ContentPools,
    ContentScheduler,
    ContentSource,
    DisplayDensity,
    SchedulerContext,
)


def _default_pools() -> ContentPools:
    return ContentPools(
        facts=["Fact one", "Fact two"],
        moments=["moment one"],
        nudge_titles=["nudge one"],
        camera_roles=["brio-operator"],
        camera_filters=["sepia(0.8)"],
    )


class TestTemporalDensity:
    def test_rising_flow_preemptive_focused(self):
        s = ContentScheduler()
        ctx = SchedulerContext(
            activity="writing",
            flow_score=0.4,
            trend_flow=0.02,  # rising
        )
        assert s._compute_density(ctx) == DisplayDensity.FOCUSED

    def test_falling_flow_becomes_receptive(self):
        s = ContentScheduler()
        ctx = SchedulerContext(
            activity="writing",
            flow_score=0.35,
            trend_flow=-0.03,  # falling
        )
        assert s._compute_density(ctx) == DisplayDensity.RECEPTIVE

    def test_flat_trend_no_change(self):
        s = ContentScheduler()
        ctx = SchedulerContext(
            activity="writing",
            flow_score=0.4,
            trend_flow=0.0,
        )
        # Default behavior: 0.4 flow, "writing" → AMBIENT
        assert s._compute_density(ctx) == DisplayDensity.AMBIENT

    def test_meeting_overrides_trend(self):
        s = ContentScheduler()
        ctx = SchedulerContext(
            activity="in a meeting",
            flow_score=0.4,
            trend_flow=0.05,  # rising but meeting overrides
        )
        assert s._compute_density(ctx) == DisplayDensity.PRESENTING


class TestStalenessScoring:
    def test_stale_perception_reduces_score(self):
        s = ContentScheduler()
        fresh = SchedulerContext(perception_age_s=0.0)
        stale = SchedulerContext(perception_age_s=30.0)
        score_fresh = s._score_source(ContentSource.PROFILE_FACT, fresh, now=1000.0)
        score_stale = s._score_source(ContentSource.PROFILE_FACT, stale, now=1000.0)
        assert score_stale < score_fresh

    def test_very_stale_still_positive(self):
        s = ContentScheduler()
        ctx = SchedulerContext(perception_age_s=120.0)
        score = s._score_source(ContentSource.PROFILE_FACT, ctx, now=1000.0)
        assert score > 0

    def test_slightly_stale_no_penalty(self):
        s = ContentScheduler()
        ctx5 = SchedulerContext(perception_age_s=5.0)
        ctx0 = SchedulerContext(perception_age_s=0.0)
        score5 = s._score_source(ContentSource.PROFILE_FACT, ctx5, now=1000.0)
        score0 = s._score_source(ContentSource.PROFILE_FACT, ctx0, now=1000.0)
        # Under 10s threshold, no penalty
        assert score5 == score0


class TestTemporalContextBackwardCompat:
    def test_default_temporal_fields(self):
        ctx = SchedulerContext()
        assert ctx.trend_flow == 0.0
        assert ctx.trend_audio == 0.0
        assert ctx.perception_age_s == 0.0

    def test_tick_with_temporal_context(self):
        s = ContentScheduler()
        s._rng.seed(42)
        ctx = SchedulerContext(
            activity="present",
            trend_flow=0.01,
            perception_age_s=2.0,
        )
        pools = _default_pools()
        # Should not crash
        result = s.tick(ctx, pools, now=1000.0)
        assert result is None or result.source in ContentSource

    def test_old_code_still_works(self):
        """SchedulerContext without temporal fields still works."""
        s = ContentScheduler()
        ctx = SchedulerContext(activity="present", flow_score=0.0)
        pools = _default_pools()
        for i in range(20):
            result = s.tick(ctx, pools, now=100.0 + i * 20.0)
            assert result is None or result.source in ContentSource
