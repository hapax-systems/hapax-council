"""Tests for camera/archive/public-aperture WCS media fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.wcs_camera_archive_public_aperture import (
    REQUIRED_FAIL_CLOSED_POLICY,
    REQUIRED_VISIBILITY_STATES,
    EvidenceState,
    MediaApertureFixtureSet,
    VisibilityState,
    WCSMediaApertureError,
    load_media_aperture_fixtures,
)


def test_fixture_loader_covers_visibility_states_and_fail_closed_policy() -> None:
    fixtures = load_media_aperture_fixtures()

    assert {state.value for state in fixtures.visibility_states} == REQUIRED_VISIBILITY_STATES
    assert {record.visibility_state.value for record in fixtures.records} >= (
        REQUIRED_VISIBILITY_STATES
    )
    assert fixtures.fail_closed_policy == REQUIRED_FAIL_CLOSED_POLICY
    assert all(not record.claim_posture.monetization_allowed for record in fixtures.records)


def test_camera_and_archive_existence_do_not_imply_public_safe() -> None:
    fixtures = load_media_aperture_fixtures()
    camera = fixtures.require_record("media_aperture:camera_rgb.internal_visible")
    archive = fixtures.require_record("media_aperture:archive_hls_sidecar.archived")

    assert camera.camera_refs
    assert camera.claim_posture.internally_visible is True
    assert camera.claim_posture.public_safe is False
    assert camera.claim_posture.public_live_claim_allowed is False
    assert "public_event_evidence_missing" in camera.public_claim_blockers()
    assert "egress_evidence_missing" in camera.public_claim_blockers()

    assert archive.archive_refs
    assert archive.claim_posture.archived is True
    assert archive.claim_posture.public_safe is False
    assert archive.claim_posture.public_archive_claim_allowed is False
    assert "public_event_evidence_missing" in archive.public_claim_blockers()


def test_public_live_and_archive_claims_require_explicit_evidence_refs() -> None:
    fixtures = load_media_aperture_fixtures()
    youtube = fixtures.require_record("media_aperture:youtube_live.public")
    replay = fixtures.require_record("media_aperture:archive_replay_url.public_archive")

    for record in (youtube, replay):
        assert record.claim_posture.public_safe is True
        assert record.egress_state is EvidenceState.PASS
        assert record.public_event_state is EvidenceState.PASS
        assert record.rights_state is EvidenceState.PASS
        assert record.privacy_state is EvidenceState.PASS
        assert record.evidence.face_privacy_refs
        assert record.evidence.consent_refs
        assert record.evidence.audio_refs
        assert record.evidence.egress_refs
        assert record.evidence.public_event_refs
        assert record.evidence.rights_refs
        assert record.evidence.privacy_refs
        assert record.public_claim_blockers() == ()

    assert youtube.claim_posture.public_live_claim_allowed is True
    assert youtube.claim_posture.public_archive_claim_allowed is False

    assert replay.claim_posture.public_live_claim_allowed is False
    assert replay.claim_posture.public_archive_claim_allowed is True
    assert replay.evidence.archive_refs
    assert replay.archive_replay_decision_refs
    assert replay.research_vehicle_public_event_refs
    assert replay.temporal_span_refs


@pytest.mark.parametrize(
    ("record_id", "reason"),
    [
        ("media_aperture:camera_rgb.missing", "camera_missing"),
        ("media_aperture:archive_hls_sidecar.missing", "archive_missing"),
        ("media_aperture:youtube_live.stale", "public_surface_stale"),
        ("media_aperture:public_egress.unknown_blocked", "egress_unknown"),
        ("media_aperture:archive_replay.privacy_rights_hold", "privacy_rights_hold"),
    ],
)
def test_missing_stale_and_blocked_records_name_blockers(record_id: str, reason: str) -> None:
    record = load_media_aperture_fixtures().require_record(record_id)

    assert record.visibility_state in {
        VisibilityState.MISSING,
        VisibilityState.STALE,
        VisibilityState.BLOCKED,
    }
    assert reason in record.blocking_reasons
    assert record.claim_posture.public_safe is False
    assert record.claim_posture.public_live_claim_allowed is False
    assert record.claim_posture.public_archive_claim_allowed is False


def test_public_safe_mutation_without_public_event_is_rejected(tmp_path: Path) -> None:
    fixtures = load_media_aperture_fixtures()
    payload = fixtures.model_dump(mode="json")
    for record in payload["records"]:
        if record["record_id"] == "media_aperture:camera_rgb.internal_visible":
            record["claim_posture"]["public_safe"] = True

    path = tmp_path / "bad-media-apertures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WCSMediaApertureError, match="public_safe cannot pass"):
        load_media_aperture_fixtures(path)


def test_fixture_set_rejects_missing_visibility_state() -> None:
    fixtures = load_media_aperture_fixtures()
    payload = fixtures.model_dump(mode="json")
    payload["visibility_states"] = [
        state for state in payload["visibility_states"] if state != "internal_visible"
    ]

    with pytest.raises(ValueError, match="internal_visible"):
        MediaApertureFixtureSet.model_validate(payload)
