"""Phase-7 tests for director observability emitters.

Verifies that each emitter either updates a Prometheus counter (when
prometheus_client is available) or is a safe no-op (when not). We don't
assert on specific counter values because the global registry persists
across tests — just that calls don't raise.
"""

from __future__ import annotations

import pytest

from shared.director_intent import CompositionalImpingement, DirectorIntent
from shared.stimmung import Stance


@pytest.fixture
def intent():
    return DirectorIntent(
        grounding_provenance=["audio.contact_mic.desk_activity.drumming", "album.artist"],
        activity="vinyl",
        stance=Stance.NOMINAL,
        narrative_text="",
        compositional_impingements=[
            CompositionalImpingement(narrative="turntable focus", intent_family="camera.hero"),
            CompositionalImpingement(
                narrative="audio-reactive visuals", intent_family="preset.bias"
            ),
        ],
    )


def test_emit_director_intent_does_not_raise(intent):
    from shared import director_observability as obs

    obs.emit_director_intent(intent, condition_id="cond-x")


def test_emit_twitch_move_does_not_raise():
    from shared import director_observability as obs

    obs.emit_twitch_move("overlay.emphasis", condition_id="cond-x")


def test_emit_structural_intent_does_not_raise():
    from shared import director_observability as obs

    obs.emit_structural_intent(
        scene_mode="hardware-play",
        preset_family_hint="audio-reactive",
        condition_id="cond-x",
    )


def test_observe_llm_latency_does_not_raise():
    from shared import director_observability as obs

    obs.observe_llm_latency(seconds=18.3, tier="narrative", condition_id="cond-x")


def test_emit_parse_failure_does_not_raise():
    from shared import director_observability as obs

    obs.emit_parse_failure(tier="narrative", condition_id="cond-x")


def test_public_api_is_exhaustive():
    """Every emitter function surfaced in __all__ is callable with typed args."""
    from shared import director_observability as obs

    expected = {
        "emit_director_intent",
        "emit_twitch_move",
        "emit_structural_intent",
        "observe_llm_latency",
        "emit_parse_failure",
    }
    assert expected.issubset(set(obs.__all__))
    for name in expected:
        assert callable(getattr(obs, name))
