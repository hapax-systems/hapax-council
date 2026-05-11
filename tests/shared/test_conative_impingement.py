from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from shared.conative_impingement import (
    ActionTendencyImpingement,
    action_tendency_impulse_from_impingement,
    compulsion_band,
    execution_inhibition_reasons,
    narrative_drive_content_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "config" / "conative-impingement-fixtures.json"


def _fixture_cases() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["fixtures"]


def test_fixture_compulsion_ranges_and_execution_blockers() -> None:
    for case in _fixture_cases():
        impulse = ActionTendencyImpingement.model_validate(case["envelope"])
        assert impulse.compulsion_band == case["expected_compulsion_band"]
        assert (
            list(execution_inhibition_reasons(impulse))
            == case["expected_execution_inhibition_reasons"]
        )


def test_narrative_drive_payload_carries_required_conative_fields() -> None:
    payload = narrative_drive_content_payload(
        impingement_id="abc123",
        narrative="Internal drive to narrate the live shift.",
        drive_name="narration",
        strength_posterior=0.43,
        chronicle_event_count=7,
        stimmung_stance="reflective",
        programme_role="listening",
    )

    impulse = ActionTendencyImpingement.model_validate(
        {k: payload[k] for k in ActionTendencyImpingement.model_fields}
    )

    assert impulse.impulse_id == "narration-abc123"
    assert impulse.action_tendency == "speak"
    assert impulse.speech_act_candidate == "autonomous_narrative"
    assert impulse.strength_posterior == 0.43
    assert impulse.speech_destination == "public_live"
    assert impulse.claim_posture == "public_live"
    assert impulse.raw_drive_text_spoken is False
    assert "source:endogenous.narrative_drive" in impulse.evidence_refs
    assert payload["narrative"] == "Internal drive to narrate the live shift."


def test_build_from_legacy_impingement_preserves_existing_impulse_id_and_refs() -> None:
    imp = SimpleNamespace(
        id="imp-1",
        source="endogenous.narrative_drive",
        strength=0.57,
        content={
            "impulse_id": "impulse-explicit",
            "drive": "narration",
            "content_summary": "A bounded narration impulse.",
            "evidence_refs": ["wcs:audio.broadcast_voice"],
            "strength_posterior": 0.57,
            "action_tendency": "speak",
            "role_state_ref": "livestream-role-state:test",
            "speech_destination": "public_live",
            "claim_posture": "public_live",
        },
    )

    impulse = action_tendency_impulse_from_impingement(imp)

    assert impulse.impulse_id == "impulse-explicit"
    assert impulse.content_summary == "A bounded narration impulse."
    assert impulse.role_state_ref == "livestream-role-state:test"
    assert impulse.speech_destination == "public_live"
    assert "wcs:audio.broadcast_voice" in impulse.evidence_refs
    assert impulse.route_evidence_ref == "route:audio.broadcast_voice:health_witness_required"


def test_compulsion_band_is_not_binary_route_permission() -> None:
    assert compulsion_band(0.01) == "too_low"
    assert compulsion_band(0.50) == "healthy"
    assert compulsion_band(0.95) == "too_high"
