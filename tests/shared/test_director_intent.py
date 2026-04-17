"""Schema tests for shared/director_intent.py."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shared.director_intent import (
    CompositionalImpingement,
    DirectorIntent,
)
from shared.stimmung import Stance


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


class TestDirectorIntent:
    def test_minimal_valid_intent(self):
        intent = DirectorIntent(
            activity="silence",
            stance=Stance.NOMINAL,
            narrative_text="",
        )
        assert intent.activity == "silence"
        assert intent.stance == Stance.NOMINAL
        assert intent.narrative_text == ""
        assert intent.grounding_provenance == []
        assert intent.compositional_impingements == []

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
            DirectorIntent(activity=activity, stance=Stance.NOMINAL, narrative_text="")

    def test_empty_grounding_provenance_allowed_but_noted(self):
        """Empty provenance is allowed — the pipeline accepts ungrounded
        fallback — but the research log should flag it."""
        intent = DirectorIntent(
            activity="silence",
            stance=Stance.NOMINAL,
            narrative_text="",
            grounding_provenance=[],
        )
        assert intent.grounding_provenance == []
