"""Tests for DirectorControlMove to scrim gesture adapter fixtures."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.director_scrim_gesture_adapter import (
    FAIL_CLOSED_POLICY,
    REQUIRED_AUDIT_OUTCOMES,
    REQUIRED_DIRECTOR_VERBS,
    DirectorScrimGestureAdapterError,
    DirectorScrimGestureFixtureSet,
    ScrimGestureRecord,
    load_director_scrim_gesture_fixtures,
    project_director_scrim_gesture_input,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "director-scrim-gesture-adapter.schema.json"
SCRIM_STATE_SCHEMA = REPO_ROOT / "schemas" / "scrim-state-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "director-scrim-gesture-adapter-fixtures.json"


def _payload() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(FIXTURES.read_text(encoding="utf-8")))


def _fixtures() -> DirectorScrimGestureFixtureSet:
    return load_director_scrim_gesture_fixtures()


def _projections_by_fixture_id() -> dict[str, ScrimGestureRecord]:
    return {projection.fixture_id: projection.gesture for projection in _fixtures().projections()}


def test_schema_validates_director_scrim_fixture_file() -> None:
    schema = cast("dict[str, Any]", json.loads(SCHEMA.read_text(encoding="utf-8")))
    payload = _payload()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert set(schema["x-required_director_verbs"]) == REQUIRED_DIRECTOR_VERBS
    assert set(schema["x-required_audit_outcomes"]) == REQUIRED_AUDIT_OUTCOMES
    assert schema["x-fail_closed_policy"] == FAIL_CLOSED_POLICY


def test_loader_covers_all_director_verbs_and_audit_outcomes() -> None:
    fixtures = _fixtures()
    projections = fixtures.projections()

    assert {fixture.director_move.verb for fixture in fixtures.fixtures} == REQUIRED_DIRECTOR_VERBS
    assert {
        projection.audit_record.outcome for projection in projections
    } >= REQUIRED_AUDIT_OUTCOMES
    assert set(fixtures.audit_records_by_outcome()) >= REQUIRED_AUDIT_OUTCOMES


def test_every_gesture_cites_director_move_wcs_freshness_fallback_and_policy() -> None:
    scrim_schema = cast(
        "dict[str, Any]", json.loads(SCRIM_STATE_SCHEMA.read_text(encoding="utf-8"))
    )
    scrim_gesture_schema = {
        "$defs": scrim_schema["$defs"],
        **cast("dict[str, Any]", scrim_schema["$defs"]["scrim_gesture"]),
    }

    for projection in _fixtures().projections():
        fixture = next(
            row for row in _fixtures().fixtures if row.fixture_id == projection.fixture_id
        )
        gesture = projection.gesture

        assert fixture.director_move.decision_id in gesture.source_move_refs
        assert fixture.director_move.audit_event.payload_ref in gesture.source_move_refs
        assert set(fixture.wcs.source_refs) <= set(gesture.wcs_source_refs)
        assert gesture.freshness_state
        assert gesture.fallback_mode == fixture.wcs.fallback_mode
        assert gesture.public_claim_policy.scrim_grants_truth is False
        assert gesture.public_claim_policy.scrim_grants_public_status is False
        assert gesture.public_claim_policy.scrim_grants_live_control is False
        jsonschema.Draft202012Validator(scrim_gesture_schema).validate(
            gesture.scrim_state_gesture()
        )


def test_blocked_targets_cannot_be_foregrounded_intensified_or_made_public() -> None:
    projections = _projections_by_fixture_id()
    blocked_foreground = projections["foreground_blocked_rejected"]
    blocked_intensify = projections["intensify_blocked_rejected"]

    for gesture in (blocked_foreground, blocked_intensify):
        assert gesture.execution == "no_op"
        assert gesture.gesture_type == "neutral_hold"
        assert gesture.gesture_effect == "neutral_hold"
        assert gesture.intensity == 0.0
        assert gesture.public_claim_policy.scrim_public_claim_allowed is False
        assert "blocked_target_cannot_be_prominent" in gesture.blocked_reasons


def test_silence_stillness_hold_is_valid_only_with_target_lane_and_reason() -> None:
    fixture = next(row for row in _fixtures().fixtures if row.fixture_id == "hold_silence_valid")
    projection = project_director_scrim_gesture_input(fixture)

    assert projection.audit_record.outcome == "accepted"
    assert projection.gesture.target_lane_ref == "lane:listening.quiet"
    assert projection.gesture.reason

    payload = fixture.model_dump(mode="json")
    payload["target_lane_ref"] = None
    payload["reason"] = None
    payload["expected"] = None
    mutated = fixture.model_validate(payload)
    muted_projection = project_director_scrim_gesture_input(mutated)

    assert muted_projection.audit_record.outcome == "rejected"
    assert muted_projection.audit_record.reason_code == "hold_requires_target_lane_and_reason"
    assert muted_projection.gesture.execution == "no_op"
    assert muted_projection.gesture.public_claim_policy.scrim_public_claim_allowed is False


def test_ttl_and_caps_bound_density_refraction_focus_boundary_and_pierce() -> None:
    for gesture in _projections_by_fixture_id().values():
        assert gesture.ttl_s <= 30
        assert -0.35 <= gesture.caps.density_delta <= 0.35
        assert -0.25 <= gesture.caps.refraction_delta <= 0.25
        assert 0.0 <= gesture.caps.focus_strength <= 0.7
        assert gesture.caps.boundary_pulse_count <= 3

    pierce = _projections_by_fixture_id()["mark_boundary_pierce_accepted"]
    assert pierce.gesture_type == "mark_boundary"
    assert pierce.gesture_effect == "scrim.pierce"
    assert pierce.caps.pierce_allowed is True
    assert pierce.caps.pierce_ttl_s is not None
    assert pierce.caps.pierce_ttl_s <= 5
    assert pierce.ttl_s <= 8
    assert pierce.intensity <= 0.45


def test_private_dry_run_stale_and_fallback_do_not_expand_public_claims() -> None:
    projections = {projection.fixture_id: projection for projection in _fixtures().projections()}

    for fixture_id in (
        "route_attention_private_only",
        "mark_boundary_dry_run",
        "transition_stale_hold",
        "crossfade_degraded_fallback",
        "suppress_blocked_fallback",
    ):
        projection = projections[fixture_id]
        assert projection.audit_record.public_claim_allowed is False
        assert projection.gesture.public_claim_policy.scrim_public_claim_allowed is False
        assert (
            projection.gesture.execution != "gesture" or fixture_id == "suppress_blocked_fallback"
        )

    public = projections["foreground_public_accepted"]
    assert public.audit_record.public_claim_allowed is True
    assert public.gesture.public_claim_policy.inherited_public_claim_allowed is True
    assert public.gesture.public_claim_policy.scope_expansion_allowed is False


def test_malformed_fixture_packet_fails_closed_on_policy_and_event_mismatch(
    tmp_path: Path,
) -> None:
    payload = copy.deepcopy(_payload())
    payload["fail_closed_policy"]["scrim_grants_truth"] = True
    bad_policy_path = tmp_path / "bad-policy.json"
    bad_policy_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DirectorScrimGestureAdapterError, match="fail_closed_policy"):
        load_director_scrim_gesture_fixtures(bad_policy_path)

    payload = copy.deepcopy(_payload())
    payload["fixtures"][0]["director_move"]["audit_event"]["event_type"] = (
        "director.move.background"
    )
    with pytest.raises(ValueError, match="event_type"):
        DirectorScrimGestureFixtureSet.model_validate(payload)
