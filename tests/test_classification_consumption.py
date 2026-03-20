"""Tests for classification consumption layer — Batch 1.

Tests gaze/emotion/posture gating in content scheduler and interruptibility.
"""

from __future__ import annotations

from agents.content_scheduler import (
    ContentPools,
    ContentScheduler,
    ContentSource,
    SchedulerContext,
)
from agents.hapax_voice.perception import compute_interruptibility


def _default_pools() -> ContentPools:
    return ContentPools(
        facts=["Fact one", "Fact two", "Fact three"],
        moments=["ambient drone pad"],
        nudge_titles=["Check drift"],
        camera_roles=["brio-operator", "c920-room"],
        camera_filters=["sepia(0.8)"],
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


class TestSchedulerGazeGating:
    """Gaze=screen suppresses CAMERA_FEED injection."""

    def test_gaze_screen_suppresses_camera_feed(self):
        s = ContentScheduler()
        ctx_screen = _default_context(gaze_direction="screen")
        ctx_away = _default_context(gaze_direction="away")

        score_screen = s._score_source(ContentSource.CAMERA_FEED, ctx_screen, now=0.0)
        score_away = s._score_source(ContentSource.CAMERA_FEED, ctx_away, now=0.0)

        # Screen gaze should heavily suppress camera feed (×0.1)
        assert score_screen < score_away * 0.2

    def test_gaze_screen_does_not_affect_other_sources(self):
        s = ContentScheduler()
        ctx_screen = _default_context(gaze_direction="screen")
        ctx_unknown = _default_context(gaze_direction="unknown")

        for source in (ContentSource.PROFILE_FACT, ContentSource.SHADER_VARIATION):
            score_screen = s._score_source(source, ctx_screen, now=0.0)
            score_unknown = s._score_source(source, ctx_unknown, now=0.0)
            assert score_screen == score_unknown


class TestSchedulerEmotionGating:
    """Negative emotion suppresses PROFILE_FACT content."""

    def test_angry_suppresses_profile_fact(self):
        s = ContentScheduler()
        ctx_angry = _default_context(emotion="angry")
        ctx_neutral = _default_context(emotion="neutral")

        score_angry = s._score_source(ContentSource.PROFILE_FACT, ctx_angry, now=0.0)
        score_neutral = s._score_source(ContentSource.PROFILE_FACT, ctx_neutral, now=0.0)

        # Angry should suppress profile facts (×0.3)
        assert score_angry < score_neutral * 0.5

    def test_sad_suppresses_profile_fact(self):
        s = ContentScheduler()
        ctx_sad = _default_context(emotion="sad")
        ctx_neutral = _default_context(emotion="neutral")

        score_sad = s._score_source(ContentSource.PROFILE_FACT, ctx_sad, now=0.0)
        score_neutral = s._score_source(ContentSource.PROFILE_FACT, ctx_neutral, now=0.0)

        assert score_sad < score_neutral * 0.5

    def test_fear_suppresses_profile_fact(self):
        s = ContentScheduler()
        ctx = _default_context(emotion="fear")
        ctx_neutral = _default_context(emotion="neutral")

        score_fear = s._score_source(ContentSource.PROFILE_FACT, ctx, now=0.0)
        score_neutral = s._score_source(ContentSource.PROFILE_FACT, ctx_neutral, now=0.0)

        assert score_fear < score_neutral * 0.5

    def test_happy_does_not_suppress_profile_fact(self):
        s = ContentScheduler()
        ctx_happy = _default_context(emotion="happy")
        ctx_neutral = _default_context(emotion="neutral")

        score_happy = s._score_source(ContentSource.PROFILE_FACT, ctx_happy, now=0.0)
        score_neutral = s._score_source(ContentSource.PROFILE_FACT, ctx_neutral, now=0.0)

        assert score_happy == score_neutral


class TestSchedulerPostureGating:
    """Slouching boosts STUDIO_MOMENT for breaks."""

    def test_slouching_boosts_studio_moment(self):
        s = ContentScheduler()
        ctx_slouch = _default_context(posture="slouching")
        ctx_upright = _default_context(posture="upright")

        score_slouch = s._score_source(ContentSource.STUDIO_MOMENT, ctx_slouch, now=0.0)
        score_upright = s._score_source(ContentSource.STUDIO_MOMENT, ctx_upright, now=0.0)

        assert score_slouch > score_upright


class TestInterruptibilityEnrichment:
    """Gaze/emotion/posture reduce interruptibility score."""

    def _base_kwargs(self) -> dict:
        return {
            "vad_confidence": 0.0,
            "activity_mode": "",
            "in_voice_session": False,
            "operator_present": True,
        }

    def test_gaze_away_reduces_interruptibility(self):
        base = compute_interruptibility(**self._base_kwargs())
        away = compute_interruptibility(**self._base_kwargs(), gaze_direction="away")
        assert away < base
        assert base - away >= 0.2  # at least -0.25

    def test_emotion_angry_reduces_interruptibility(self):
        base = compute_interruptibility(**self._base_kwargs())
        angry = compute_interruptibility(**self._base_kwargs(), emotion="angry")
        assert angry < base
        assert base - angry >= 0.15  # at least -0.2

    def test_posture_slouching_reduces_interruptibility(self):
        base = compute_interruptibility(**self._base_kwargs())
        slouch = compute_interruptibility(**self._base_kwargs(), posture="slouching")
        assert slouch < base
        assert base - slouch >= 0.08  # at least -0.1

    def test_combined_penalties_stack(self):
        base = compute_interruptibility(**self._base_kwargs())
        combined = compute_interruptibility(
            **self._base_kwargs(),
            gaze_direction="away",
            emotion="angry",
            posture="slouching",
        )
        assert combined < base - 0.4  # all three stack

    def test_neutral_values_no_change(self):
        base = compute_interruptibility(**self._base_kwargs())
        neutral = compute_interruptibility(
            **self._base_kwargs(),
            gaze_direction="unknown",
            emotion="neutral",
            posture="unknown",
        )
        assert base == neutral

    def test_result_still_clamped(self):
        """Even with all penalties, result stays in [0, 1]."""
        result = compute_interruptibility(
            vad_confidence=0.9,
            activity_mode="production",
            in_voice_session=False,
            operator_present=True,
            physiological_load=0.8,
            gaze_direction="away",
            emotion="angry",
            posture="slouching",
        )
        assert 0.0 <= result <= 1.0
