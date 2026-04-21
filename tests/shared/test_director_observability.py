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
        "emit_ungrounded_audit",  # FINDING-X (2026-04-21 wiring audit)
    }
    assert expected.issubset(set(obs.__all__))
    for name in expected:
        assert callable(getattr(obs, name))


# ── FINDING-X: emit_ungrounded_audit (2026-04-21 wiring audit) ──────────


def test_emit_ungrounded_audit_does_not_raise(intent):
    """Fully-grounded intent → audit completes without raising."""
    from shared import director_observability as obs

    obs.emit_ungrounded_audit(intent, condition_id="cond-x")


def test_emit_ungrounded_audit_warns_when_intent_empty(caplog):
    """Top-level grounding_provenance empty → WARNING logged."""
    import logging as _logging

    from shared import director_observability as obs

    empty_intent = DirectorIntent(
        grounding_provenance=[],
        activity="vinyl",
        stance=Stance.NOMINAL,
        narrative_text="",
        compositional_impingements=[
            CompositionalImpingement(
                narrative="any",
                intent_family="camera.hero",
                grounding_provenance=["audio.contact_mic"],  # impingement is grounded
            ),
        ],
    )

    with caplog.at_level(_logging.WARNING, logger="shared.director_observability"):
        obs.emit_ungrounded_audit(empty_intent, condition_id="cond-x")

    matched = [r for r in caplog.records if "UNGROUNDED intent" in r.message]
    assert matched, "expected an UNGROUNDED intent warning"


def test_emit_ungrounded_audit_warns_per_empty_impingement(caplog):
    """Every impingement with empty grounding_provenance → its own WARNING."""
    import logging as _logging

    from shared import director_observability as obs

    intent_with_two_ungrounded = DirectorIntent(
        grounding_provenance=["audio.contact_mic.desk_activity"],
        activity="observe",
        stance=Stance.NOMINAL,
        narrative_text="",
        compositional_impingements=[
            CompositionalImpingement(
                narrative="ungrounded one",
                intent_family="camera.hero",
                grounding_provenance=[],
            ),
            CompositionalImpingement(
                narrative="grounded one",
                intent_family="preset.bias",
                grounding_provenance=["audio.midi.beat_position"],
            ),
            CompositionalImpingement(
                narrative="ungrounded two",
                intent_family="overlay.emphasis",
                grounding_provenance=[],
            ),
        ],
    )

    with caplog.at_level(_logging.WARNING, logger="shared.director_observability"):
        obs.emit_ungrounded_audit(intent_with_two_ungrounded, condition_id="cond-x")

    impingement_warnings = [r for r in caplog.records if "UNGROUNDED impingement" in r.message]
    assert len(impingement_warnings) == 2
    intent_warnings = [r for r in caplog.records if "UNGROUNDED intent" in r.message]
    # Top-level was grounded → no intent-level warning
    assert intent_warnings == []


def test_emit_ungrounded_audit_silent_when_fully_grounded(caplog):
    """No warnings when both top-level and every impingement are grounded."""
    import logging as _logging

    from shared import director_observability as obs

    fully_grounded = DirectorIntent(
        grounding_provenance=["audio.contact_mic.desk_activity"],
        activity="observe",
        stance=Stance.NOMINAL,
        narrative_text="",
        compositional_impingements=[
            CompositionalImpingement(
                narrative="grounded",
                intent_family="camera.hero",
                grounding_provenance=["ir.ir_hand_zone.turntable"],
            ),
        ],
    )

    with caplog.at_level(_logging.WARNING, logger="shared.director_observability"):
        obs.emit_ungrounded_audit(fully_grounded, condition_id="cond-x")

    ungrounded_warnings = [r for r in caplog.records if "UNGROUNDED" in r.message]
    assert ungrounded_warnings == []
