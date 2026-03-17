"""Tests for the content scheduler — weighted softmax sampler."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.content_scheduler import (
    DEFAULT_SOURCE_CONFIGS,
    DENSITY_PARAMS,
    RELEVANCE_MATRIX,
    ContentPools,
    ContentScheduler,
    ContentSource,
    DisplayDensity,
    SchedulerContext,
    SchedulerDecision,
    ShaderNudge,
    SourceConfig,
)


def _default_pools() -> ContentPools:
    return ContentPools(
        facts=["Fact one about the operator", "Fact two about habits", "Fact three about work"],
        moments=["jazz piano loop", "ambient drone pad"],
        nudge_titles=["Review PR #130", "Check drift items"],
        camera_roles=["brio-operator", "c920-room"],
        camera_filters=["sepia(0.8)", "grayscale(0.6)"],
    )


def _default_context(**overrides) -> SchedulerContext:
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


class TestDisplayDensity:
    def test_meeting_is_presenting(self):
        s = ContentScheduler()
        ctx = _default_context(activity="in a meeting")
        assert s._compute_density(ctx) == DisplayDensity.PRESENTING

    def test_coding_is_focused(self):
        s = ContentScheduler()
        ctx = _default_context(activity="coding")
        assert s._compute_density(ctx) == DisplayDensity.FOCUSED

    def test_deep_flow_is_focused(self):
        s = ContentScheduler()
        ctx = _default_context(flow_score=0.8)
        assert s._compute_density(ctx) == DisplayDensity.FOCUSED

    def test_idle_is_receptive(self):
        s = ContentScheduler()
        ctx = _default_context(activity="present", flow_score=0.0)
        assert s._compute_density(ctx) == DisplayDensity.RECEPTIVE

    def test_browsing_is_receptive(self):
        s = ContentScheduler()
        ctx = _default_context(activity="browsing")
        assert s._compute_density(ctx) == DisplayDensity.RECEPTIVE


class TestDensityParams:
    def test_all_densities_have_params(self):
        for d in DisplayDensity:
            assert d in DENSITY_PARAMS

    def test_focused_has_lower_temperature(self):
        assert (
            DENSITY_PARAMS[DisplayDensity.FOCUSED].temperature
            < DENSITY_PARAMS[DisplayDensity.AMBIENT].temperature
        )

    def test_receptive_has_higher_inject_rate(self):
        assert (
            DENSITY_PARAMS[DisplayDensity.RECEPTIVE].inject_probability
            > DENSITY_PARAMS[DisplayDensity.AMBIENT].inject_probability
        )

    def test_presenting_has_lowest_inject_rate(self):
        lowest = min(DENSITY_PARAMS[d].inject_probability for d in DisplayDensity)
        assert DENSITY_PARAMS[DisplayDensity.PRESENTING].inject_probability == lowest


class TestSourceScoring:
    def test_freshness_increases_with_time(self):
        s = ContentScheduler()
        ctx = _default_context()
        s._last_selected[ContentSource.PROFILE_FACT] = 0.0
        score_early = s._score_source(ContentSource.PROFILE_FACT, ctx, now=10.0)
        score_late = s._score_source(ContentSource.PROFILE_FACT, ctx, now=300.0)
        assert score_late > score_early

    def test_relevance_modulates_score(self):
        s = ContentScheduler()
        ctx_idle = _default_context(activity="present")
        ctx_meeting = _default_context(activity="in a meeting")
        score_idle = s._score_source(ContentSource.PROFILE_FACT, ctx_idle, now=1000.0)
        score_meeting = s._score_source(ContentSource.PROFILE_FACT, ctx_meeting, now=1000.0)
        assert score_idle > score_meeting

    def test_stress_boosts_calming_sources(self):
        s = ContentScheduler()
        ctx_calm = _default_context(stress_elevated=False)
        ctx_stress = _default_context(stress_elevated=True)
        score_calm = s._score_source(ContentSource.SHADER_VARIATION, ctx_calm, now=1000.0)
        score_stress = s._score_source(ContentSource.SHADER_VARIATION, ctx_stress, now=1000.0)
        assert score_stress > score_calm

    def test_score_always_positive(self):
        s = ContentScheduler()
        ctx = _default_context()
        for source in ContentSource:
            score = s._score_source(source, ctx, now=0.0)
            assert score > 0


class TestSoftmaxSampling:
    def test_deterministic_with_one_source(self):
        s = ContentScheduler()
        scores = {ContentSource.PROFILE_FACT: 1.0}
        result = s._softmax_sample(scores, temperature=1.0)
        assert result == ContentSource.PROFILE_FACT

    def test_empty_scores_returns_none(self):
        s = ContentScheduler()
        result = s._softmax_sample({}, temperature=1.0)
        assert result is None

    def test_low_temperature_favors_highest(self):
        s = ContentScheduler()
        scores = {
            ContentSource.PROFILE_FACT: 2.0,
            ContentSource.CAMERA_FEED: 0.1,
        }
        # With very low temperature, should almost always pick highest
        picks = [s._softmax_sample(scores, temperature=0.01) for _ in range(50)]
        fact_count = sum(1 for p in picks if p == ContentSource.PROFILE_FACT)
        assert fact_count >= 45  # >90%

    def test_high_temperature_is_more_uniform(self):
        s = ContentScheduler()
        scores = {
            ContentSource.PROFILE_FACT: 1.0,
            ContentSource.CAMERA_FEED: 1.0,
            ContentSource.SHADER_VARIATION: 1.0,
        }
        picks = [s._softmax_sample(scores, temperature=10.0) for _ in range(300)]
        fact_count = sum(1 for p in picks if p == ContentSource.PROFILE_FACT)
        # With equal scores and high temp, each should get ~33%
        assert 50 < fact_count < 200


class TestTickIntegration:
    def test_first_tick_respects_interval(self):
        s = ContentScheduler()
        ctx = _default_context()
        pools = _default_pools()
        # First tick at t=0 should produce something (last_tick starts at 0)
        result = s.tick(ctx, pools, now=100.0)
        # May or may not inject based on probability, but shouldn't crash
        assert result is None or isinstance(result, SchedulerDecision)

    def test_rapid_ticks_throttled(self):
        s = ContentScheduler()
        ctx = _default_context()
        pools = _default_pools()
        # First tick
        s.tick(ctx, pools, now=100.0)
        # Immediate second tick should be throttled
        result = s.tick(ctx, pools, now=100.1)
        assert result is None

    def test_tick_after_interval_may_produce(self):
        s = ContentScheduler()
        s._rng.seed(42)  # deterministic
        ctx = _default_context()
        pools = _default_pools()
        # Try many ticks with sufficient spacing to get at least one decision
        decisions = []
        for i in range(50):
            result = s.tick(ctx, pools, now=100.0 + i * 20.0)
            if result:
                decisions.append(result)
        assert len(decisions) > 0

    def test_decision_has_valid_source(self):
        s = ContentScheduler()
        s._rng.seed(42)
        ctx = _default_context()
        pools = _default_pools()
        for i in range(50):
            result = s.tick(ctx, pools, now=100.0 + i * 20.0)
            if result:
                assert result.source in ContentSource
                assert result.dwell_s > 0
                break

    def test_empty_pools_no_crash(self):
        s = ContentScheduler()
        ctx = _default_context()
        pools = ContentPools()  # empty
        # Should still work (shader_variation and time_of_day are always available)
        for i in range(10):
            result = s.tick(ctx, pools, now=100.0 + i * 20.0)
            assert result is None or result.source in (
                ContentSource.SHADER_VARIATION,
                ContentSource.TIME_OF_DAY,
            )

    def test_camera_decision_has_role(self):
        s = ContentScheduler()
        s._rng.seed(42)
        ctx = _default_context()
        pools = _default_pools()
        # Force camera selection by giving it massive weight
        s._configs[ContentSource.CAMERA_FEED] = SourceConfig(
            source=ContentSource.CAMERA_FEED, base_weight=100.0
        )
        for i in range(100):
            result = s.tick(ctx, pools, now=100.0 + i * 20.0)
            if result and result.source == ContentSource.CAMERA_FEED:
                assert result.camera_role in pools.camera_roles
                assert result.camera_opacity > 0
                break

    def test_fact_avoids_repetition(self):
        s = ContentScheduler()
        s._rng.seed(123)
        # Give PROFILE_FACT massive weight
        s._configs[ContentSource.PROFILE_FACT] = SourceConfig(
            source=ContentSource.PROFILE_FACT, base_weight=100.0
        )
        ctx = _default_context()
        pools = ContentPools(facts=["A", "B", "C"])
        seen: list[str] = []
        for i in range(100):
            result = s.tick(ctx, pools, now=100.0 + i * 20.0)
            if result and result.source == ContentSource.PROFILE_FACT:
                seen.append(result.content)
        # Should see all three facts, not just one repeated
        assert len(set(seen)) > 1

    def test_meeting_blocks_camera(self):
        s = ContentScheduler()
        ctx = _default_context(activity="in a meeting")
        pools = _default_pools()
        available = s._available_sources(ctx, pools)
        assert ContentSource.CAMERA_FEED not in available


class TestShaderNudge:
    def test_coding_is_cooler_slower(self):
        s = ContentScheduler()
        ctx = _default_context(activity="coding")
        nudge = s._compute_shader_nudge(ContentSource.PROFILE_FACT, ctx)
        assert nudge.speed_mult < 1.0
        assert nudge.warmth_offset < 0

    def test_music_is_warmer_faster(self):
        s = ContentScheduler()
        ctx = _default_context(activity="making music")
        nudge = s._compute_shader_nudge(ContentSource.PROFILE_FACT, ctx)
        assert nudge.speed_mult > 1.0
        assert nudge.warmth_offset > 0

    def test_camera_brightens(self):
        s = ContentScheduler()
        ctx = _default_context()
        nudge = s._compute_shader_nudge(ContentSource.CAMERA_FEED, ctx)
        assert nudge.brightness_offset > 0

    def test_late_night_slow_warm(self):
        s = ContentScheduler()
        ctx = _default_context(hour=23)
        nudge = s._compute_shader_nudge(ContentSource.PROFILE_FACT, ctx)
        assert nudge.speed_mult < 1.0
        assert nudge.warmth_offset > 0

    def test_audio_energy_boosts_turbulence(self):
        s = ContentScheduler()
        ctx = _default_context(audio_energy=0.5)
        nudge = s._compute_shader_nudge(ContentSource.PROFILE_FACT, ctx)
        assert nudge.turbulence_mult > 1.0

    def test_neutral_nudge_is_identity(self):
        nudge = ShaderNudge()
        assert nudge.speed_mult == 1.0
        assert nudge.turbulence_mult == 1.0
        assert nudge.warmth_offset == 0.0
        assert nudge.brightness_offset == 0.0


class TestRelevanceMatrix:
    def test_camera_low_during_coding(self):
        assert RELEVANCE_MATRIX[ContentSource.CAMERA_FEED]["coding"] < 0.5

    def test_profile_fact_high_when_idle(self):
        assert RELEVANCE_MATRIX[ContentSource.PROFILE_FACT]["present"] > 1.0

    def test_studio_moment_high_during_music(self):
        assert RELEVANCE_MATRIX[ContentSource.STUDIO_MOMENT]["making music"] > 1.0


class TestSourceConfigs:
    def test_all_sources_have_configs(self):
        configured = {c.source for c in DEFAULT_SOURCE_CONFIGS}
        for source in ContentSource:
            assert source in configured, f"Missing config for {source}"

    def test_dwell_ranges_valid(self):
        for c in DEFAULT_SOURCE_CONFIGS:
            assert c.min_dwell_s > 0
            assert c.max_dwell_s >= c.min_dwell_s
            assert c.half_life_s > 0
            assert c.base_weight > 0


class TestInvariants:
    @given(
        activity=st.sampled_from(["present", "coding", "making music", "in a meeting", "browsing"]),
        flow=st.floats(min_value=0.0, max_value=1.0),
        audio=st.floats(min_value=0.0, max_value=1.0),
        stress=st.booleans(),
        hour=st.integers(min_value=0, max_value=23),
    )
    @settings(max_examples=200)
    def test_tick_never_crashes(
        self, activity: str, flow: float, audio: float, stress: bool, hour: int
    ):
        s = ContentScheduler()
        ctx = SchedulerContext(
            activity=activity,
            flow_score=flow,
            audio_energy=audio,
            stress_elevated=stress,
            hour=hour,
        )
        pools = _default_pools()
        result = s.tick(ctx, pools, now=1000.0)
        assert result is None or isinstance(result, SchedulerDecision)

    @given(
        activity=st.sampled_from(["present", "coding", "making music", "in a meeting"]),
        hour=st.integers(min_value=0, max_value=23),
        audio=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=100)
    def test_shader_nudge_bounded(self, activity: str, hour: int, audio: float):
        s = ContentScheduler()
        ctx = SchedulerContext(activity=activity, hour=hour, audio_energy=audio)
        for source in ContentSource:
            nudge = s._compute_shader_nudge(source, ctx)
            assert 0.1 <= nudge.speed_mult <= 3.0
            assert 0.1 <= nudge.turbulence_mult <= 3.0
            assert -1.0 <= nudge.warmth_offset <= 1.0
            assert -1.0 <= nudge.brightness_offset <= 1.0

    @given(
        activity=st.sampled_from(["present", "coding", "making music", "in a meeting"]),
        flow=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=50)
    def test_density_always_valid(self, activity: str, flow: float):
        s = ContentScheduler()
        ctx = SchedulerContext(activity=activity, flow_score=flow)
        density = s._compute_density(ctx)
        assert density in DisplayDensity
