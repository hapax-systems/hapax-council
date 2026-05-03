"""Hysteresis / transition tests for the H1 detector.

Pins the two operator-loaded failure modes from the source research:

1. The OBS clipping noise must fire only after the configured 2s
   sustain window — no single-tick alert.
2. Absolute silence at OBS must NOT fire when livestream is off,
   and MUST fire when livestream is on AFTER the 5s sustain window.
3. Brief gaps during legitimate restarts (sub-sustain blips) must
   NOT fire — false-positive auto-mute would be as bad as silence.
"""

from __future__ import annotations

import pytest

from agents.audio_signal_assertion.classifier import Classification
from agents.audio_signal_assertion.transitions import (
    DEFAULT_CLIPPING_SUSTAIN_S,
    DEFAULT_NOISE_SUSTAIN_S,
    DEFAULT_RECOVERY_SUSTAIN_S,
    DEFAULT_SILENCE_SUSTAIN_S,
    StageObservation,
    TransitionDetector,
)


def _detector(stages=("a", "b", "c"), **kwargs) -> TransitionDetector:
    return TransitionDetector(stage_names=stages, **kwargs)


# ---------------------------------------------------------------------------
# Sustain-window edges
# ---------------------------------------------------------------------------


def test_clipping_below_sustain_does_not_fire():
    det = _detector()
    events = det.record_probe("a", Classification.CLIPPING, captured_at=0.0)
    assert events == []
    # Same tick + 1s — still under 2s sustain default.
    events = det.record_probe("a", Classification.CLIPPING, captured_at=1.0)
    assert events == []


def test_clipping_at_sustain_fires_once():
    det = _detector()
    det.record_probe("a", Classification.CLIPPING, captured_at=0.0)
    events = det.record_probe("a", Classification.CLIPPING, captured_at=DEFAULT_CLIPPING_SUSTAIN_S)
    assert len(events) == 1
    assert events[0].new_state == Classification.CLIPPING
    assert events[0].sustained_for_s >= DEFAULT_CLIPPING_SUSTAIN_S


def test_clipping_re_arms_after_recovery():
    det = _detector(recovery_sustain_s=4.0)
    det.record_probe("a", Classification.CLIPPING, captured_at=0.0)
    fired_now = det.record_probe(
        "a", Classification.CLIPPING, captured_at=DEFAULT_CLIPPING_SUSTAIN_S
    )
    assert len(fired_now) == 1

    # Recovery: feed clean for >= recovery_sustain_s.
    for t in [3.0, 4.0, 5.0, 6.0, 7.0, 8.0]:
        det.record_probe("a", Classification.MUSIC_VOICE, captured_at=t)

    # After recovery, a NEW clipping run must fire again — not be
    # suppressed because the prior event still sits in history.
    det.record_probe("a", Classification.CLIPPING, captured_at=20.0)
    re_events = det.record_probe(
        "a", Classification.CLIPPING, captured_at=20.0 + DEFAULT_CLIPPING_SUSTAIN_S
    )
    assert len(re_events) == 1


def test_silence_off_air_does_not_fire():
    det = _detector(silence_sustain_s=DEFAULT_SILENCE_SUSTAIN_S)
    for t in range(20):
        events = det.record_probe(
            "a",
            Classification.SILENT,
            captured_at=float(t),
            livestream_active=False,
        )
        assert events == []


def test_silence_on_air_fires_after_sustain():
    det = _detector()
    # Sub-sustain duration: must not fire.
    events = det.record_probe(
        "a",
        Classification.SILENT,
        captured_at=0.0,
        livestream_active=True,
    )
    assert events == []
    # >= sustain duration: must fire exactly once.
    events = det.record_probe(
        "a",
        Classification.SILENT,
        captured_at=DEFAULT_SILENCE_SUSTAIN_S,
        livestream_active=True,
    )
    assert len(events) == 1
    assert events[0].new_state == Classification.SILENT
    assert events[0].sustained_for_s >= DEFAULT_SILENCE_SUSTAIN_S


def test_brief_silence_blip_during_restart_no_event():
    """One-tick silence followed by recovery must NOT page.

    This pins the operator's "brief gaps during legitimate restarts
    are not failure modes" constraint.
    """
    det = _detector()
    det.record_probe(
        "a",
        Classification.MUSIC_VOICE,
        captured_at=0.0,
        livestream_active=True,
    )
    # Single-tick silence shorter than sustain.
    det.record_probe(
        "a",
        Classification.SILENT,
        captured_at=1.0,
        livestream_active=True,
    )
    # Recovery before sustain elapses.
    events = det.record_probe(
        "a",
        Classification.MUSIC_VOICE,
        captured_at=2.0,
        livestream_active=True,
    )
    assert events == []


# ---------------------------------------------------------------------------
# Cross-class behavior + upstream context
# ---------------------------------------------------------------------------


def test_noise_then_clipping_emits_distinct_events():
    det = _detector()
    det.record_probe("a", Classification.NOISE, captured_at=0.0)
    fired = det.record_probe(
        "a",
        Classification.NOISE,
        captured_at=DEFAULT_NOISE_SUSTAIN_S,
    )
    assert len(fired) == 1
    assert fired[0].new_state == Classification.NOISE

    # Now the chain transitions noise→clipping. The detector must
    # close the noise state and open a fresh clipping window: no
    # event until the new sustain elapses.
    det.record_probe("a", Classification.CLIPPING, captured_at=10.0)
    fired = det.record_probe(
        "a",
        Classification.CLIPPING,
        captured_at=10.0 + DEFAULT_CLIPPING_SUSTAIN_S,
    )
    assert len(fired) == 1
    assert fired[0].new_state == Classification.CLIPPING
    assert fired[0].previous_state == Classification.NOISE


def test_upstream_context_captures_other_stages():
    det = _detector(stages=("master", "normalized", "obs"))
    det.record_probe("master", Classification.MUSIC_VOICE, captured_at=0.0)
    det.record_probe("normalized", Classification.NOISE, captured_at=0.0)
    det.record_probe("obs", Classification.CLIPPING, captured_at=0.0)
    fired = det.record_probe(
        "obs",
        Classification.CLIPPING,
        captured_at=DEFAULT_CLIPPING_SUSTAIN_S,
    )
    assert len(fired) == 1
    upstream = dict(fired[0].upstream_context)
    assert upstream["master"] == Classification.MUSIC_VOICE
    assert upstream["normalized"] == Classification.NOISE
    # The focal stage is excluded from its own upstream context.
    assert "obs" not in upstream


def test_unknown_stage_registers_on_first_record():
    det = _detector(stages=())
    fired = det.record_probe("freshly-discovered", Classification.MUSIC_VOICE, captured_at=0.0)
    assert fired == []
    assert "freshly-discovered" in {s.name for s in det.stages}


@pytest.mark.parametrize(
    "states",
    [
        [Classification.MUSIC_VOICE, Classification.MUSIC_VOICE, Classification.MUSIC_VOICE],
        [Classification.TONE, Classification.MUSIC_VOICE, Classification.TONE],
    ],
)
def test_clean_states_never_fire(states):
    det = _detector()
    for i, s in enumerate(states):
        events = det.record_probe("a", s, captured_at=float(i))
        assert events == []


def test_recovery_event_is_silent():
    """Once a bad state recovers, no recovery TransitionEvent fires.

    The operator-loaded preference is "notification spam is worse
    than silent recovery"; the metric flipping back is the recovery
    signal.
    """
    det = _detector(recovery_sustain_s=2.0)
    det.record_probe("a", Classification.CLIPPING, captured_at=0.0)
    fired = det.record_probe("a", Classification.CLIPPING, captured_at=DEFAULT_CLIPPING_SUSTAIN_S)
    assert len(fired) == 1
    # Sustained recovery: no event.
    for t in (3.0, 4.0, 5.0, 6.0):
        events = det.record_probe("a", Classification.MUSIC_VOICE, captured_at=t)
        assert events == []


def test_observation_history_bounded():
    det = _detector(stages=("a",))
    for t in range(200):
        det.record_probe("a", Classification.MUSIC_VOICE, captured_at=float(t))
    state = det.stage("a")
    # History deque maxlen guards memory.
    assert len(state.history) <= 64


def test_observation_dataclass_carries_class_and_timestamp():
    obs = StageObservation(
        classification=Classification.NOISE,
        captured_at=12.5,
        duration_s=2.0,
    )
    assert obs.classification == Classification.NOISE
    assert obs.captured_at == 12.5


def test_default_recovery_sustain_constant_is_used():
    det = _detector()
    # Borrow the API to assert the constant is in play.
    assert det._recovery_sustain_s == DEFAULT_RECOVERY_SUSTAIN_S
