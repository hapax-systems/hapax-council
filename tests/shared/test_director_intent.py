"""Schema tests for shared/director_intent.py."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shared.director_intent import (
    CompositionalImpingement,
    DirectorIntent,
    is_synthetic_grounding_marker,
    split_grounding_provenance,
)
from shared.stimmung import Stance


def _silence_hold_imp() -> CompositionalImpingement:
    """Stock impingement for tests that only exercise fields other than
    compositional_impingements. Operator invariant (2026-04-18) requires
    at least one impingement per DirectorIntent."""
    return CompositionalImpingement(
        narrative="silence hold: maintain surface",
        intent_family="overlay.emphasis",
    )


class TestCompositionalImpingement:
    def test_minimal_valid_impingement(self):
        imp = CompositionalImpingement(
            narrative="the turntable is active",
            intent_family="camera.hero",
        )
        assert imp.narrative == "the turntable is active"
        assert imp.intent_family == "camera.hero"
        assert imp.material == "water"
        assert imp.salience == 0.5
        assert imp.dimensions == {}

    def test_narrative_stripped(self):
        imp = CompositionalImpingement(
            narrative="  leading whitespace  ",
            intent_family="preset.bias",
        )
        assert imp.narrative == "leading whitespace"

    def test_empty_narrative_rejected(self):
        with pytest.raises(ValidationError):
            CompositionalImpingement(narrative="   ", intent_family="camera.hero")

    def test_unknown_intent_family_rejected(self):
        with pytest.raises(ValidationError):
            CompositionalImpingement(narrative="valid", intent_family="not.a.family")

    def test_salience_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            CompositionalImpingement(narrative="valid", intent_family="camera.hero", salience=1.2)

    def test_unknown_material_rejected(self):
        with pytest.raises(ValidationError):
            CompositionalImpingement(
                narrative="valid", intent_family="camera.hero", material="plasma"
            )

    def test_full_impingement_with_dimensions(self):
        imp = CompositionalImpingement(
            narrative="hardware workspace claims attention",
            dimensions={"intensity": 0.7, "tension": 0.3},
            material="earth",
            salience=0.82,
            intent_family="camera.hero",
        )
        assert imp.dimensions["intensity"] == 0.7
        assert imp.material == "earth"

    def test_synthetic_grounding_markers_are_migrated_out_of_real_provenance(self):
        imp = CompositionalImpingement(
            narrative="fallback move",
            intent_family="overlay.emphasis",
            grounding_provenance=[
                "fallback.parser_non_dict",
                "audio.contact_mic.desk_activity",
                "inferred.nominal.overlay.emphasis",
            ],
        )
        assert imp.grounding_provenance == ["audio.contact_mic.desk_activity"]
        assert imp.synthetic_grounding_markers == [
            "fallback.parser_non_dict",
            "inferred.nominal.overlay.emphasis",
        ]


class TestDirectorIntent:
    def test_minimal_valid_intent(self):
        # Operator invariant (2026-04-18): every DirectorIntent must carry
        # at least one compositional_impingement. Silence-hold counts.
        intent = DirectorIntent(
            activity="silence",
            stance=Stance.NOMINAL,
            narrative_text="",
            compositional_impingements=[
                CompositionalImpingement(
                    narrative="silence hold: maintain surface",
                    intent_family="overlay.emphasis",
                )
            ],
        )
        assert intent.activity == "silence"
        assert intent.stance == Stance.NOMINAL
        assert intent.narrative_text == ""
        assert intent.grounding_provenance == []
        assert len(intent.compositional_impingements) == 1

    def test_full_intent(self):
        intent = DirectorIntent(
            grounding_provenance=[
                "audio.contact_mic.fused_activity.scratching",
                "visual.overhead_hand_zones.turntable",
                "album.artist",
            ],
            activity="vinyl",
            stance=Stance.NOMINAL,
            narrative_text="the record keeps going",
            compositional_impingements=[
                CompositionalImpingement(
                    narrative="shows the hardware workspace while vinyl plays",
                    intent_family="camera.hero",
                    salience=0.9,
                ),
                CompositionalImpingement(
                    narrative="sound-following visuals for a music-led moment",
                    intent_family="preset.bias",
                    salience=0.7,
                ),
            ],
        )
        assert len(intent.grounding_provenance) == 3
        assert len(intent.compositional_impingements) == 2

    def test_unknown_activity_rejected(self):
        with pytest.raises(ValidationError):
            DirectorIntent(
                activity="nap",  # not in the 13-label vocabulary
                stance=Stance.NOMINAL,
                narrative_text="",
            )

    def test_stance_accepts_string_enum_value(self):
        intent = DirectorIntent(
            activity="silence",
            stance="seeking",  # StrEnum accepts string
            narrative_text="",
            compositional_impingements=[_silence_hold_imp()],
        )
        assert intent.stance == Stance.SEEKING

    def test_unknown_stance_rejected(self):
        with pytest.raises(ValidationError):
            DirectorIntent(
                activity="silence",
                stance="euphoric",
                narrative_text="",
            )

    def test_model_dump_for_jsonl_serializes_stance_as_string(self):
        intent = DirectorIntent(
            activity="react",
            stance=Stance.SEEKING,
            narrative_text="what caught me",
            compositional_impingements=[_silence_hold_imp()],
        )
        dumped = intent.model_dump_for_jsonl()
        assert dumped["stance"] == "seeking"
        # Round-trip via JSON
        restored = DirectorIntent.model_validate(json.loads(json.dumps(dumped)))
        assert restored.stance == Stance.SEEKING
        assert restored.activity == "react"

    def test_jsonl_roundtrip_preserves_impingements(self):
        intent = DirectorIntent(
            activity="vinyl",
            stance=Stance.NOMINAL,
            narrative_text="",
            compositional_impingements=[
                CompositionalImpingement(
                    narrative="turntable focus",
                    intent_family="camera.hero",
                    dimensions={"intensity": 0.6},
                    salience=0.8,
                    material="earth",
                ),
            ],
        )
        serialized = json.dumps(intent.model_dump_for_jsonl())
        restored = DirectorIntent.model_validate_json(serialized)
        assert restored.compositional_impingements[0].narrative == "turntable focus"
        assert restored.compositional_impingements[0].dimensions == {"intensity": 0.6}
        assert restored.compositional_impingements[0].material == "earth"

    def test_all_13_activities_accepted(self):
        for activity in (
            "react",
            "chat",
            "vinyl",
            "study",
            "observe",
            "silence",
            "draft",
            "reflect",
            "critique",
            "patch",
            "compose_drop",
            "synthesize",
            "exemplar_review",
        ):
            DirectorIntent(
                activity=activity,
                stance=Stance.NOMINAL,
                narrative_text="",
                compositional_impingements=[_silence_hold_imp()],
            )

    def test_empty_grounding_provenance_allowed_but_noted(self):
        """Empty provenance is allowed — the pipeline accepts ungrounded
        fallback — but the research log should flag it."""
        intent = DirectorIntent(
            activity="silence",
            stance=Stance.NOMINAL,
            narrative_text="",
            grounding_provenance=[],
            compositional_impingements=[_silence_hold_imp()],
        )
        assert intent.grounding_provenance == []

    def test_synthetic_grounding_markers_do_not_satisfy_real_intent_provenance(self):
        intent = DirectorIntent(
            activity="silence",
            stance=Stance.NOMINAL,
            narrative_text="",
            grounding_provenance=["fallback.parser_json_decode"],
            compositional_impingements=[_silence_hold_imp()],
        )
        assert intent.grounding_provenance == []
        assert intent.synthetic_grounding_markers == ["fallback.parser_json_decode"]
        assert intent.has_real_grounding_provenance is False


def test_synthetic_grounding_marker_classifier():
    assert is_synthetic_grounding_marker("inferred.nominal.camera.hero")
    assert is_synthetic_grounding_marker("fallback.parser_non_dict")
    assert is_synthetic_grounding_marker("parser-error")
    assert is_synthetic_grounding_marker("silence_hold")
    assert not is_synthetic_grounding_marker("audio.contact_mic.desk_activity")


def test_split_grounding_provenance_keeps_real_wcs_and_capability_keys():
    real, synthetic = split_grounding_provenance(
        [
            "fallback.micromove.llm_empty",
            "audio.contact_mic.desk_activity",
            "wcs.capability.audio.broadcast_voice",
            "capability_outcome.route.broadcast_public",
            "inferred.seeking.preset.bias",
        ]
    )
    assert real == [
        "audio.contact_mic.desk_activity",
        "wcs.capability.audio.broadcast_voice",
        "capability_outcome.route.broadcast_public",
    ]
    assert synthetic == ["fallback.micromove.llm_empty", "inferred.seeking.preset.bias"]


class TestDiagnosticFlag:
    """The ``diagnostic`` flag marks an impingement whose narrative is
    internal routing text that must never reach viewer-facing surfaces.
    Added 2026-04-21 after operator saw silence-hold narrative rendered
    in the ActivityHeader gloss slot on broadcast.
    """

    def test_diagnostic_defaults_false(self):
        imp = CompositionalImpingement(
            narrative="turntable focus",
            intent_family="camera.hero",
        )
        assert imp.diagnostic is False

    def test_diagnostic_true_roundtrip(self):
        imp = CompositionalImpingement(
            narrative="Silence hold: maintain the current surface",
            intent_family="overlay.emphasis",
            diagnostic=True,
        )
        assert imp.diagnostic is True
        payload = imp.model_dump()
        assert payload["diagnostic"] is True
        restored = CompositionalImpingement.model_validate(payload)
        assert restored.diagnostic is True

    def test_diagnostic_does_not_affect_other_fields(self):
        """Diagnostic is purely a legibility fence — pipeline recruitment
        score, narrative, salience, etc. unchanged."""
        a = CompositionalImpingement(
            narrative="the turntable is active",
            intent_family="camera.hero",
            salience=0.8,
        )
        b = CompositionalImpingement(
            narrative="the turntable is active",
            intent_family="camera.hero",
            salience=0.8,
            diagnostic=True,
        )
        assert a.narrative == b.narrative
        assert a.intent_family == b.intent_family
        assert a.salience == b.salience
