"""Tests for scheduler stimmung awareness (WS2 Phase 4)."""

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
        moments=["jazz piano"],
        nudge_titles=["Review PR"],
        camera_roles=["brio-operator"],
        camera_filters=["sepia(0.8)"],
    )


def _ctx(**overrides) -> SchedulerContext:
    defaults = {
        "activity": "present",
        "flow_score": 0.0,
        "audio_energy": 0.0,
        "stress_elevated": False,
        "heart_rate": 70,
        "sleep_quality": 1.0,
        "voice_active": False,
        "display_state": "ambient",
        "hour": 14,
        "signal_count": 0,
    }
    defaults.update(overrides)
    return SchedulerContext(**defaults)


class TestStimmungDensity:
    def test_nominal_no_effect(self):
        s = ContentScheduler()
        ctx = _ctx(stimmung_stance="nominal")
        density = s._compute_density(ctx)
        assert density == DisplayDensity.RECEPTIVE  # present + idle = receptive

    def test_degraded_forces_presenting(self):
        s = ContentScheduler()
        ctx = _ctx(stimmung_stance="degraded")
        density = s._compute_density(ctx)
        assert density == DisplayDensity.PRESENTING

    def test_critical_forces_presenting(self):
        s = ContentScheduler()
        ctx = _ctx(stimmung_stance="critical")
        density = s._compute_density(ctx)
        assert density == DisplayDensity.PRESENTING

    def test_cautious_does_not_force_presenting(self):
        s = ContentScheduler()
        ctx = _ctx(stimmung_stance="cautious")
        density = s._compute_density(ctx)
        assert density != DisplayDensity.PRESENTING


class TestStimmungScoring:
    def test_cautious_boosts_calming_sources(self):
        s = ContentScheduler()
        ctx_nominal = _ctx(stimmung_stance="nominal")
        ctx_cautious = _ctx(stimmung_stance="cautious")
        now = 1000.0

        score_nom = s._score_source(ContentSource.SHADER_VARIATION, ctx_nominal, now)
        score_caut = s._score_source(ContentSource.SHADER_VARIATION, ctx_cautious, now)
        assert score_caut > score_nom

    def test_cautious_boosts_time_of_day(self):
        s = ContentScheduler()
        ctx_nominal = _ctx(stimmung_stance="nominal")
        ctx_cautious = _ctx(stimmung_stance="cautious")
        now = 1000.0

        score_nom = s._score_source(ContentSource.TIME_OF_DAY, ctx_nominal, now)
        score_caut = s._score_source(ContentSource.TIME_OF_DAY, ctx_cautious, now)
        assert score_caut > score_nom

    def test_cautious_no_boost_for_non_calming(self):
        s = ContentScheduler()
        ctx_nominal = _ctx(stimmung_stance="nominal")
        ctx_cautious = _ctx(stimmung_stance="cautious")
        now = 1000.0

        score_nom = s._score_source(ContentSource.CAMERA_FEED, ctx_nominal, now)
        score_caut = s._score_source(ContentSource.CAMERA_FEED, ctx_cautious, now)
        assert score_nom == score_caut


class TestSchedulerContextField:
    def test_stimmung_stance_default(self):
        ctx = SchedulerContext()
        assert ctx.stimmung_stance == "nominal"

    def test_stimmung_stance_set(self):
        ctx = _ctx(stimmung_stance="critical")
        assert ctx.stimmung_stance == "critical"
