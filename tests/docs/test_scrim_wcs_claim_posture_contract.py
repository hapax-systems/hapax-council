"""Contract tests for the scrim WCS claim-posture gate fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "scrim-wcs-claim-posture.schema.json"
FIXTURES = REPO_ROOT / "config" / "scrim-wcs-claim-posture-fixtures.json"
SCRIM_STATE_FIXTURES = REPO_ROOT / "config" / "scrim-state-envelope-fixtures.json"
WCS_HEALTH_FIXTURES = REPO_ROOT / "config" / "world-surface-health-fixtures.json"

EXPECTED_FAMILIES = {
    "fresh_public_safe",
    "stale",
    "missing_witness",
    "private_only",
    "blocked_media",
    "audio_blocked",
    "refusal",
    "correction",
    "conversion_ready",
    "conversion_held",
}
EXPECTED_POSTURES = {
    "local_clarity",
    "hold",
    "dry_run",
    "suppress_public_cue",
    "neutralize_blocked_media",
    "operator_reason",
    "refusal_artifact",
    "correction_boundary",
    "conversion_cue",
    "conversion_held",
}
EXPECTED_BLOCKER_FAMILIES = {
    "rights",
    "privacy_consent",
    "monetization",
    "egress",
    "audio",
    "public_event",
}


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _schema() -> dict[str, Any]:
    return _json(SCHEMA)


def _fixtures() -> dict[str, Any]:
    return _json(FIXTURES)


def test_schema_validates_scrim_wcs_claim_posture_fixtures() -> None:
    schema = _schema()
    fixtures = _fixtures()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(fixtures)


def test_schema_pins_posture_blocker_and_no_grant_vocabulary() -> None:
    schema = _schema()
    defs = schema["$defs"]

    assert set(schema["x-required_fixture_families"]) == EXPECTED_FAMILIES
    assert set(schema["x-required_blocker_families"]) == EXPECTED_BLOCKER_FAMILIES
    assert set(defs["bounded_posture"]["enum"]) == EXPECTED_POSTURES
    assert schema["x-no_grant_policy"] == {
        "scrim_grants_truth": False,
        "scrim_grants_rights": False,
        "scrim_grants_safety": False,
        "scrim_grants_public_status": False,
        "scrim_grants_monetization_status": False,
        "scrim_grants_live_control": False,
        "conversion_cue_is_truth_signal": False,
        "engagement_trend_revenue_spectacle_are_truth_signals": False,
        "blocked_media_hidden_under_spectacle": False,
    }


def test_fixture_refs_resolve_to_existing_scrim_and_wcs_health_packets() -> None:
    fixtures = _fixtures()["fixtures"]
    scrim_families = {fixture["family"] for fixture in _json(SCRIM_STATE_FIXTURES)["fixtures"]}
    health_surface_ids = {
        record["surface_id"]
        for envelope in _json(WCS_HEALTH_FIXTURES)["envelopes"]
        for record in envelope["records"]
    }

    assert {fixture["family"] for fixture in fixtures} == EXPECTED_FAMILIES
    for fixture in fixtures:
        assert fixture["scrim_fixture_family"] in scrim_families
        assert fixture["health_surface_id"] in health_surface_ids


def test_fixture_catalog_covers_required_public_safe_and_blocked_cases() -> None:
    fixtures = _fixtures()["fixtures"]
    expected_by_family = {fixture["family"]: fixture["expected"] for fixture in fixtures}

    assert expected_by_family["fresh_public_safe"]["public_claim_allowed"] is True
    assert expected_by_family["fresh_public_safe"]["posture"] == "local_clarity"
    assert expected_by_family["blocked_media"]["posture"] == "neutralize_blocked_media"
    assert expected_by_family["blocked_media"]["media_visibility"] == ("neutralized_metadata_first")
    assert expected_by_family["conversion_ready"]["posture"] == "conversion_cue"
    assert expected_by_family["conversion_held"]["posture"] == "conversion_held"

    observed_blockers = {
        blocker
        for expected in expected_by_family.values()
        for blocker in expected["blocker_families"]
    }
    assert observed_blockers >= EXPECTED_BLOCKER_FAMILIES
