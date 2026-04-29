from __future__ import annotations

import time
from unittest import mock

from shared.affordance import SelectionCandidate
from shared.affordance_pipeline import AffordancePipeline
from shared.impingement import Impingement, ImpingementType, render_impingement_text


def _conative_impingement() -> Impingement:
    return Impingement(
        timestamp=time.time(),
        source="endogenous.narrative_drive",
        type=ImpingementType.ENDOGENOUS,
        strength=0.5,
        content={
            "narrative": "Internal pressure to narrate the live shift.",
            "content_summary": "A bounded public narration wants to be selected.",
            "drive": "narration",
            "action_tendency": "speak",
            "speech_act_candidate": "autonomous_narrative",
            "strength_posterior": 0.5,
            "role_context": "programme_role:listening",
            "inhibition_policy": "wcs_route_role_claim_gates",
            "wcs_snapshot_ref": "wcs:audio.broadcast_voice:voice-output-witness",
            "route_evidence_ref": "route:audio.broadcast_voice:health_witness_required",
            "public_claim_evidence_ref": "claim_posture:bounded_nonassertive_narration",
            "learning_policy": "separate_drive_selection_execution_world_claim",
            "evidence_refs": ["source:endogenous.narrative_drive", "drive:narration"],
        },
    )


def test_render_impingement_text_includes_conative_retrieval_fields() -> None:
    text = render_impingement_text(_conative_impingement())

    assert "action tendency: speak" in text
    assert "speech act candidate: autonomous_narrative" in text
    assert "posterior pressure: 0.5" in text
    assert "wcs evidence: wcs:audio.broadcast_voice:voice-output-witness" in text
    assert "route evidence: route:audio.broadcast_voice:health_witness_required" in text


def test_action_tendency_is_soft_scoring_prior_not_family_filter(monkeypatch) -> None:
    monkeypatch.setattr("shared.affordance_pipeline.THRESHOLD", 0.0)
    monkeypatch.setattr("shared.affordance.ActivationState.thompson_sample", lambda _self: 0.5)
    pipeline = AffordancePipeline()
    narration = SelectionCandidate(
        capability_name="narration.autonomous_first_system",
        similarity=0.5,
        payload={"medium": "auditory"},
    )
    visual = SelectionCandidate(
        capability_name="visual.marker",
        similarity=0.5,
        payload={"medium": "visual"},
    )

    with (
        mock.patch.object(pipeline, "_get_embedding", return_value=[0.0] * 384),
        mock.patch.object(pipeline, "_retrieve", return_value=[visual, narration]),
        mock.patch.object(pipeline, "_consent_allows", return_value=True),
    ):
        survivors = pipeline.select(_conative_impingement())

    names = [candidate.capability_name for candidate in survivors]
    assert names[0] == "narration.autonomous_first_system"
    assert "visual.marker" in names
    visual_score = next(c.combined for c in survivors if c.capability_name == "visual.marker")
    assert survivors[0].combined > visual_score
