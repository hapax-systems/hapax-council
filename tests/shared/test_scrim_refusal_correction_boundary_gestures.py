"""Tests for programme boundary events projected as bounded scrim gestures."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.scrim_refusal_correction_boundary_gestures import (
    FAIL_CLOSED_POLICY,
    REQUIRED_BOUNDARY_POSTURES,
    BoundaryGestureCaps,
    BoundaryGesturePublicClaimPolicy,
    BoundaryGestureRefs,
    ScrimBoundaryGestureError,
    ScrimBoundaryGestureFixtureSet,
    ScrimBoundaryGestureRecord,
    load_scrim_boundary_gesture_fixtures,
    project_scrim_boundary_gesture_input,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "scrim-refusal-correction-boundary-gestures.schema.json"
SCRIM_STATE_SCHEMA = REPO_ROOT / "schemas" / "scrim-state-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "scrim-refusal-correction-boundary-gestures-fixtures.json"


def _payload() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(FIXTURES.read_text(encoding="utf-8")))


def _fixtures() -> ScrimBoundaryGestureFixtureSet:
    return load_scrim_boundary_gesture_fixtures()


def test_schema_validates_fixture_file_and_pins_fail_closed_policy() -> None:
    schema = cast("dict[str, Any]", json.loads(SCHEMA.read_text(encoding="utf-8")))
    payload = _payload()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert set(schema["x-required_boundary_postures"]) == REQUIRED_BOUNDARY_POSTURES
    assert schema["x-fail_closed_policy"] == FAIL_CLOSED_POLICY


def test_loader_covers_required_refusal_correction_and_blocker_postures() -> None:
    fixtures = _fixtures()
    projections = fixtures.projections()

    assert {fixture.family for fixture in fixtures.fixtures} == REQUIRED_BOUNDARY_POSTURES
    assert {projection.gesture.posture for projection in projections} == REQUIRED_BOUNDARY_POSTURES


def test_public_safe_refusal_is_successful_programme_output_without_claim_authority() -> None:
    fixture = next(
        row for row in _fixtures().fixtures if row.fixture_id == "public_safe_refusal_success"
    )
    projection = project_scrim_boundary_gesture_input(fixture)
    gesture = projection.gesture

    assert gesture.posture == "refusal"
    assert gesture.visual_treatment == "foreground_public_safe_artifact"
    assert gesture.artifact_visibility == "foreground_public_safe"
    assert gesture.programme_output_success is True
    assert gesture.public_safe_artifact is True
    assert gesture.public_claim_policy.scrim_public_claim_allowed is False
    assert gesture.public_claim_policy.scrim_grants_truth is False
    assert gesture.public_fanout_implied is False
    assert projection.audit_record.outcome == "accepted"


def test_public_safe_correction_foregrounds_artifact_without_scope_expansion() -> None:
    projection = next(
        item
        for item in _fixtures().projections()
        if item.fixture_id == "public_safe_correction_success"
    )

    assert projection.gesture.posture == "correction"
    assert projection.gesture.scrim_state_gesture_type == "correction_glint"
    assert projection.gesture.programme_output_success is True
    assert projection.gesture.public_claim_policy.scope_expansion_allowed is False
    assert projection.gesture.claim_validation_by_aesthetic is False


def test_blocked_claims_cannot_be_validated_by_aesthetic_emphasis() -> None:
    blocked_ids = {
        "stale_source_holds_last_safe",
        "rights_blocked_metadata_first",
        "privacy_blocked_detail_suppressed",
        "monetization_held_boundary",
        "public_event_held_boundary_pulse",
    }
    projections = {projection.fixture_id: projection for projection in _fixtures().projections()}

    for fixture_id in blocked_ids:
        gesture = projections[fixture_id].gesture
        assert gesture.programme_output_success is False
        assert gesture.public_safe_artifact is False
        assert gesture.public_claim_policy.scrim_public_claim_allowed is False
        assert gesture.artifact_visibility != "foreground_public_safe"
        assert gesture.visual_treatment != "foreground_public_safe_artifact"
        assert gesture.intensity <= 0.3
        assert gesture.claim_validation_by_aesthetic is False
        assert gesture.blocked_reasons


def test_private_and_unsafe_blocked_details_are_suppressed() -> None:
    projections = {projection.fixture_id: projection for projection in _fixtures().projections()}

    privacy = projections["privacy_blocked_detail_suppressed"].gesture
    assert privacy.visual_treatment == "suppress_private_detail"
    assert privacy.artifact_visibility == "suppressed_private"
    assert privacy.suppressed_detail_refs

    rights = projections["rights_blocked_metadata_first"].gesture
    assert rights.visual_treatment == "neutralize_blocked_claim"
    assert rights.artifact_visibility == "metadata_only"
    assert rights.suppressed_detail_refs


def test_boundary_pulses_do_not_imply_public_fanout() -> None:
    projection = next(
        item
        for item in _fixtures().projections()
        if item.fixture_id == "public_event_held_boundary_pulse"
    )
    gesture = projection.gesture

    assert gesture.visual_treatment == "boundary_breath_pulse"
    assert gesture.scrim_state_gesture_type == "mark_boundary"
    assert gesture.caps.breath_pulse_count > 0
    assert gesture.caps.boundary_pulse_count > 0
    assert gesture.public_fanout_implied is False
    assert "research_vehicle_public_event_missing" in gesture.blocked_reasons


def test_gestures_emit_run_store_audit_health_and_scrim_state_refs() -> None:
    scrim_schema = cast(
        "dict[str, Any]", json.loads(SCRIM_STATE_SCHEMA.read_text(encoding="utf-8"))
    )
    scrim_gesture_schema = {
        "$defs": scrim_schema["$defs"],
        **cast("dict[str, Any]", scrim_schema["$defs"]["scrim_gesture"]),
    }

    for projection in _fixtures().projections():
        gesture = projection.gesture
        assert gesture.refs.run_store_refs
        assert gesture.refs.audit_refs
        assert gesture.refs.health_refs
        assert gesture.boundary_event_ref in gesture.refs.boundary_event_refs
        assert gesture.refs.wcs_source_refs
        jsonschema.Draft202012Validator(scrim_gesture_schema).validate(
            gesture.scrim_state_gesture()
        )


def test_invalid_blocked_foreground_record_fails_closed() -> None:
    good = next(
        item
        for item in _fixtures().projections()
        if item.fixture_id == "rights_blocked_metadata_first"
    ).gesture
    payload = good.model_dump(mode="json")
    payload["visual_treatment"] = "foreground_public_safe_artifact"
    payload["artifact_visibility"] = "foreground_public_safe"
    payload["public_safe_artifact"] = True
    payload["programme_output_success"] = True

    with pytest.raises(ValueError, match="blocked boundary claims cannot be foregrounded"):
        ScrimBoundaryGestureRecord.model_validate(payload)


def test_malformed_fixture_policy_or_expected_projection_fails_closed(tmp_path: Path) -> None:
    payload = copy.deepcopy(_payload())
    payload["fail_closed_policy"]["scrim_grants_truth"] = True
    bad_policy = tmp_path / "bad-policy.json"
    bad_policy.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScrimBoundaryGestureError, match="fail_closed_policy"):
        load_scrim_boundary_gesture_fixtures(bad_policy)

    payload = copy.deepcopy(_payload())
    payload["fixtures"][0]["expected"]["posture"] = "correction"
    with pytest.raises(ValueError, match="expected projection mismatch"):
        ScrimBoundaryGestureFixtureSet.model_validate(payload)


def test_boundary_gesture_caps_and_policy_literals_are_fail_closed() -> None:
    refs = BoundaryGestureRefs(
        run_store_refs=("run-store:example",),
        audit_refs=("audit:example",),
        health_refs=("health:example",),
        boundary_event_refs=("pbe:example",),
        wcs_source_refs=("wcs:example",),
    )
    assert refs.run_store_refs

    caps = BoundaryGestureCaps(
        ttl_s=12,
        density_delta=0.0,
        refraction_delta=0.0,
        focus_strength=0.2,
        breath_pulse_count=2,
    )
    assert caps.ttl_s == 12

    policy = BoundaryGesturePublicClaimPolicy(
        inherited_boundary_public_claim_allowed=True,
        basis_refs=("gate:example",),
    )
    assert policy.scrim_public_claim_allowed is False
