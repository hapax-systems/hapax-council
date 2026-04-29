"""Regression pins for the programme-to-scrim-profile policy packet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "programme-scrim-profile-policy.schema.json"
POLICY = REPO_ROOT / "config" / "programme-scrim-profile-policy.json"
SCRIM_SCHEMA = REPO_ROOT / "schemas" / "scrim-state-envelope.schema.json"
FORMAT_SCHEMA = REPO_ROOT / "schemas" / "content-programme-format.schema.json"

EXPECTED_TARGETS = {
    "tier_list",
    "ranking",
    "bracket",
    "react_commentary",
    "watch_along",
    "review",
    "explainer",
    "rundown",
    "what_is_this",
    "refusal_breakdown",
    "evidence_audit",
    "failure_autopsy",
    "listening",
    "hothouse",
    "ritual_boundary",
}
EXPECTED_FOCUS_REGIONS = {
    "criteria_table",
    "source_metadata",
    "rank_trace",
    "object_focus",
    "refusal_reason",
    "correction_boundary",
    "conversion_held_state",
}
EXPECTED_POSTURES = {"failure_autopsy", "listening", "hothouse", "ritual_boundary"}


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _policy() -> dict[str, Any]:
    return _json(POLICY)


def _targets() -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", _policy()["targets"])


def test_policy_schema_validates_fixture_packet() -> None:
    schema = _json(SCHEMA)
    policy = _policy()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(policy)


def test_policy_covers_required_formats_and_programme_postures() -> None:
    targets = {target["target_id"]: target for target in _targets()}

    assert set(targets) == EXPECTED_TARGETS

    for target_id in EXPECTED_TARGETS - EXPECTED_POSTURES:
        assert targets[target_id]["target_kind"] == "format"
        assert targets[target_id]["covered_format_ids"], target_id
        assert targets[target_id]["covered_postures"] == []

    for posture_id in EXPECTED_POSTURES:
        assert targets[posture_id]["target_kind"] == "programme_posture"
        assert targets[posture_id]["covered_format_ids"] == []
        assert targets[posture_id]["covered_postures"] == [posture_id]


def test_policy_references_existing_scrim_and_format_enums() -> None:
    policy_targets = _targets()
    scrim_defs = _json(SCRIM_SCHEMA)["$defs"]
    format_defs = _json(FORMAT_SCHEMA)["$defs"]
    scrim_profiles = set(scrim_defs["scrim_profile"]["enum"])
    permeability_modes = set(scrim_defs["permeability_mode"]["enum"])
    format_ids = set(format_defs["format_id"]["enum"])

    for target in policy_targets:
        for format_id in target["covered_format_ids"]:
            assert format_id in format_ids
        for prior in target["profile_priors"]:
            assert prior["profile_id"] in scrim_profiles
            assert prior["permeability_mode"] in permeability_modes


def test_policy_is_soft_prior_and_cannot_override_wcs_blockers() -> None:
    policy = _policy()

    assert policy["soft_prior_only"] == {
        "policy_grants_public_claim_authority": False,
        "policy_grants_live_control": False,
        "policy_can_override_wcs_blockers": False,
        "wcs_decision_required": True,
        "director_decision_required": True,
        "scheduler_hint_only": True,
    }
    assert policy["wcs_blocker_policy"]["blocked_context_returns_profile"] is False
    assert policy["wcs_blocker_policy"]["blocked_reasons_exposed"] is True
    assert policy["wcs_blocker_policy"]["unavailable_profile_reasons_required"] is True
    assert policy["wcs_blocker_policy"]["blocked_fallback_mode"] in {
        "neutral_hold",
        "minimum_density",
    }

    blocker_states = set(policy["wcs_blocker_policy"]["blocker_states"])
    assert blocker_states >= {
        "missing_evidence_ref",
        "missing_grounding_gate",
        "grounding_gate_failed",
        "source_stale",
        "rights_blocked",
        "privacy_blocked",
        "public_event_missing",
        "world_surface_blocked",
        "health_failed",
        "monetization_blocked",
        "monetization_readiness_missing",
        "conversion_held",
    }


def test_focus_regions_cover_programme_specific_surfaces() -> None:
    focus_regions = {
        focus
        for target in _targets()
        for prior in target["profile_priors"]
        for focus in prior["focus_region_kinds"]
    }

    assert focus_regions >= EXPECTED_FOCUS_REGIONS


def test_oq02_legibility_and_anti_visualizer_constraints_are_pinned() -> None:
    for target in _targets():
        for prior in target["profile_priors"]:
            constraints = prior["legibility_constraints"]
            assert constraints["oq02_minimum_translucency"] >= 0.54
            assert constraints["oq02_label_required"] is True
            assert constraints["anti_visualizer_required"] is True
            assert constraints["audio_reactive_visualizer_allowed"] is False
            assert constraints["preserve_operator_foreground"] is True
            assert prior["motion_rate"] <= constraints["max_motion_rate"]
