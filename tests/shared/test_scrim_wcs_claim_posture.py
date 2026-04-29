"""Tests for bounded scrim posture projected from WCS claim state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.scrim_wcs_claim_posture import (
    REQUIRED_BLOCKER_FAMILIES,
    REQUIRED_FIXTURE_FAMILIES,
    ScrimWCSClaimPostureError,
    ScrimWCSClaimPostureProjection,
    load_scrim_wcs_claim_posture_fixtures,
    project_scrim_claim_posture_input,
    resolve_fixture,
)


def _fixtures():
    return load_scrim_wcs_claim_posture_fixtures()


def _projections_by_family() -> dict[str, ScrimWCSClaimPostureProjection]:
    return {
        fixture.family: project_scrim_claim_posture_input(resolve_fixture(fixture))
        for fixture in _fixtures().fixtures
    }


def test_loader_covers_required_families_and_expected_projection_contract() -> None:
    fixtures = _fixtures()

    assert set(fixtures.families) == REQUIRED_FIXTURE_FAMILIES
    assert {fixture.family for fixture in fixtures.fixtures} == REQUIRED_FIXTURE_FAMILIES

    observed_blockers = {
        blocker for fixture in fixtures.fixtures for blocker in fixture.expected.blocker_families
    }
    assert observed_blockers >= REQUIRED_BLOCKER_FAMILIES

    for fixture in fixtures.fixtures:
        projection = project_scrim_claim_posture_input(resolve_fixture(fixture))
        assert projection.posture == fixture.expected.posture
        assert projection.visibility_treatment == fixture.expected.visibility_treatment
        assert projection.public_claim_allowed is fixture.expected.public_claim_allowed
        assert projection.blocker_families == fixture.expected.blocker_families
        assert projection.media_visibility == fixture.expected.media_visibility


def test_fresh_public_safe_maps_to_bounded_local_clarity_not_certainty() -> None:
    projection = _projections_by_family()["fresh_public_safe"]

    assert projection.posture == "local_clarity"
    assert projection.public_claim_allowed is True
    assert projection.inherited_public_claim_allowed is True
    assert projection.max_visual_confidence == 0.65
    assert projection.visual_confidence == 0.65
    assert projection.local_clarity <= 0.62
    assert projection.no_grant_policy.scrim_grants_truth is False
    assert projection.no_grant_policy.scrim_grants_public_status is False


def test_visual_confidence_cannot_outrun_authority_or_freshness() -> None:
    stale_projection = _projections_by_family()["stale"]

    assert stale_projection.public_claim_allowed is False
    assert stale_projection.evidence_freshness.value == "stale"
    assert stale_projection.max_visual_confidence == 0.15
    assert stale_projection.visual_confidence <= stale_projection.max_visual_confidence
    assert "freshness" in stale_projection.blocker_families

    fixture = next(row for row in _fixtures().fixtures if row.family == "stale")
    stale_input = resolve_fixture(fixture)
    high_pressure = stale_input.model_copy(
        update={
            "engagement_pressure": 1.0,
            "trend_pressure": 1.0,
            "revenue_pressure": 1.0,
            "spectacle_intensity_requested": 1.0,
        }
    )
    mutated_projection = project_scrim_claim_posture_input(high_pressure)

    assert mutated_projection.visual_confidence == stale_projection.visual_confidence
    assert mutated_projection.spectacle_intensity <= 0.2
    assert all(
        not ref.startswith(("engagement:", "trend:", "revenue:", "spectacle:"))
        for ref in mutated_projection.truth_signal_refs
    )


def test_blocked_media_is_neutralized_not_hidden_under_spectacle() -> None:
    projection = _projections_by_family()["blocked_media"]

    assert projection.posture == "neutralize_blocked_media"
    assert projection.media_visibility == "neutralized_metadata_first"
    assert projection.blocked_media_neutralized is True
    assert projection.public_claim_allowed is False
    assert "rights" in projection.blocker_families
    assert projection.spectacle_intensity <= 0.2
    assert projection.visual_confidence <= 0.1
    assert projection.visible_blocker_refs


def test_private_missing_audio_and_public_event_blockers_stay_distinct() -> None:
    projections = _projections_by_family()

    private = projections["private_only"]
    assert private.posture == "suppress_public_cue"
    assert private.blocker_families == ("health", "privacy_consent")

    missing = projections["missing_witness"]
    assert missing.posture == "dry_run"
    assert {"evidence", "missing_witness", "rights", "privacy_consent"} <= set(
        missing.blocker_families
    )

    audio = projections["audio_blocked"]
    assert audio.posture == "operator_reason"
    assert {"audio", "egress", "public_event", "privacy_consent"} <= set(audio.blocker_families)


def test_refusal_and_correction_are_successful_programme_postures() -> None:
    projections = _projections_by_family()

    refusal = projections["refusal"]
    correction = projections["correction"]

    assert refusal.posture == "refusal_artifact"
    assert refusal.visibility_treatment == "refusal_artifact_visible"
    assert refusal.public_claim_allowed is False
    assert refusal.no_grant_policy.scrim_grants_truth is False

    assert correction.posture == "correction_boundary"
    assert correction.visibility_treatment == "correction_boundary_visible"
    assert correction.public_claim_allowed is False
    assert correction.no_grant_policy.scrim_grants_truth is False


def test_conversion_cues_are_not_truth_or_confidence_cues() -> None:
    projections = _projections_by_family()
    ready = projections["conversion_ready"]
    held = projections["conversion_held"]

    assert ready.posture == "conversion_cue"
    assert ready.conversion_cue == "ready"
    assert "conversion:ready" in ready.non_truth_signal_refs
    assert ready.no_grant_policy.conversion_cue_is_truth_signal is False
    assert all(not ref.startswith("conversion:") for ref in ready.truth_signal_refs)
    assert ready.visual_confidence <= ready.max_visual_confidence

    assert held.posture == "conversion_held"
    assert held.public_claim_allowed is False
    assert "monetization" in held.blocker_families
    assert "conversion:held" in held.non_truth_signal_refs
    assert held.no_grant_policy.scrim_grants_monetization_status is False


def test_malformed_fixture_packet_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(
        Path("config/scrim-wcs-claim-posture-fixtures.json").read_text(encoding="utf-8")
    )
    payload["fail_closed_policy"]["scrim_grants_truth"] = True
    bad_path = tmp_path / "bad-scrim-wcs-claim-posture-fixtures.json"
    bad_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScrimWCSClaimPostureError, match="fail_closed_policy"):
        load_scrim_wcs_claim_posture_fixtures(bad_path)
