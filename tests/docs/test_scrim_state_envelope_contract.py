"""Regression pins for the ScrimStateEnvelope contract packet."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-04-29-scrim-state-envelope-design.md"
SCHEMA = REPO_ROOT / "schemas" / "scrim-state-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "scrim-state-envelope-fixtures.json"

EXPECTED_PROFILES = {
    "gauzy_quiet",
    "warm_haze",
    "moire_crackle",
    "clarity_peak",
    "dissolving",
    "ritual_open",
    "rain_streak",
}
EXPECTED_PERMEABILITY = {
    "semipermeable_membrane",
    "solute_suspension",
    "ionised_glow",
}
EXPECTED_CLAIM_POSTURES = {
    "fresh",
    "uncertain",
    "blocked",
    "private_only",
    "dry_run",
    "refusal",
    "correction",
    "conversion_ready",
    "conversion_held",
}
EXPECTED_FIXTURE_FAMILIES = {
    "fresh_public_safe",
    "stale",
    "private_only",
    "dry_run",
    "rights_blocked",
    "consent_privacy_blocked",
    "monetization_held",
    "refusal",
    "correction",
    "conversion_ready",
    "health_failed",
    "expired",
}
FAIL_CLOSED_FALLBACKS = {"neutral_hold", "minimum_density"}
PUBLIC_ALLOWED_FAMILIES = {"fresh_public_safe", "conversion_ready"}


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(SCHEMA.read_text(encoding="utf-8")))


def _fixture_set() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(FIXTURES.read_text(encoding="utf-8")))


def _fixtures_by_family() -> dict[str, dict[str, Any]]:
    fixtures = cast("list[dict[str, Any]]", _fixture_set()["fixtures"])
    return {
        cast("str", fixture["family"]): cast("dict[str, Any]", fixture["envelope"])
        for fixture in fixtures
    }


def _validator() -> jsonschema.Draft202012Validator:
    schema = _schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Envelope Contract",
        "## Canonical Enums",
        "## Gesture Queue",
        "## Fail-Closed Rules",
        "## Public Claim Scope",
        "## Fixture Catalog",
        "## Downstream Contract",
    ):
        assert heading in body

    for phrase in (
        "The envelope is not a source of truth",
        "`public_claim_allowed=true` is only valid when the WCS/public-event path already allows it",
        "must not infer truth, public safety, rights clearance, monetization readiness",
    ):
        assert phrase in body


def test_schema_pins_required_fields_and_exact_enums() -> None:
    schema = _schema()
    required = set(schema["required"])
    defs = cast("dict[str, dict[str, Any]]", schema["$defs"])

    for field in (
        "programme_id",
        "run_id",
        "format_id",
        "condition_id",
        "wcs_snapshot_ref",
        "director_move_refs",
        "boundary_event_refs",
        "health_ref",
        "source_refs",
        "public_private_mode",
        "blocked_reasons",
        "fallback_mode",
        "public_claim_allowed",
        "public_claim_basis_refs",
        "separation_policy",
    ):
        assert field in required
        assert field in schema["properties"]

    assert set(defs["scrim_profile"]["enum"]) == EXPECTED_PROFILES
    assert set(defs["permeability_mode"]["enum"]) == EXPECTED_PERMEABILITY
    assert set(defs["claim_posture"]["enum"]) == EXPECTED_CLAIM_POSTURES


def test_schema_defines_bounded_gesture_queue_without_imperative_control() -> None:
    schema = _schema()
    gesture_queue = schema["properties"]["gesture_queue"]
    gesture = schema["$defs"]["scrim_gesture"]
    gesture_required = set(gesture["required"])
    gesture_props = gesture["properties"]

    assert gesture_queue["maxItems"] == 8
    assert "not imperative calls" in gesture_queue["description"]
    assert gesture_required == {
        "gesture_id",
        "gesture_type",
        "created_at",
        "ttl_s",
        "intensity",
        "target_region_refs",
        "source_move_refs",
        "fallback_behavior",
    }
    assert gesture_props["ttl_s"]["maximum"] == 30
    assert gesture_props["source_move_refs"]["minItems"] == 1
    assert set(gesture_props["fallback_behavior"]["enum"]) == {
        "no_op",
        "neutral_hold",
        "minimum_density",
        "suppress_public_cue",
        "dry_run_badge",
    }


def test_schema_pins_fail_closed_and_no_claim_expansion_policy() -> None:
    schema = _schema()
    separation = schema["$defs"]["separation_policy"]["properties"]
    claim_policy = schema["x-public_claim_policy"]

    assert set(schema["x-fail_closed_fallback_modes"]) == FAIL_CLOSED_FALLBACKS
    assert claim_policy == {
        "scrim_grants_public_claim_authority": False,
        "public_claim_allowed_is_inherited_from_wcs": True,
        "public_claim_scope_expansion_allowed": False,
        "missing_or_stale_state_fails_closed": True,
    }
    assert separation["single_operator_only"]["const"] is True
    assert separation["scrim_grants_public_claim_authority"]["const"] is False
    assert separation["scrim_grants_live_control"]["const"] is False
    assert separation["public_claim_allowed_inherited_from_wcs"]["const"] is True
    assert separation["public_claim_scope_expansion_allowed"]["const"] is False
    assert separation["missing_or_stale_state_fails_closed"]["const"] is True


def test_fixture_catalog_covers_required_families_and_validates_against_schema() -> None:
    schema = _schema()
    fixture_set = _fixture_set()
    fixtures = _fixtures_by_family()
    validator = _validator()

    assert set(schema["x-fixture_families"]) == EXPECTED_FIXTURE_FAMILIES
    assert set(fixture_set["families"]) == EXPECTED_FIXTURE_FAMILIES
    assert set(fixtures) == EXPECTED_FIXTURE_FAMILIES

    for family, envelope in fixtures.items():
        try:
            validator.validate(envelope)
        except jsonschema.ValidationError as exc:
            pytest.fail(f"{family} fixture failed schema validation: {exc.message}")


def test_non_public_fixtures_do_not_expand_public_claim_scope() -> None:
    fixtures = _fixtures_by_family()

    for family, envelope in fixtures.items():
        policy = envelope["separation_policy"]

        assert policy["single_operator_only"] is True
        assert policy["scrim_grants_public_claim_authority"] is False
        assert policy["scrim_grants_live_control"] is False
        assert policy["public_claim_allowed_inherited_from_wcs"] is True
        assert policy["public_claim_scope_expansion_allowed"] is False

        if family in PUBLIC_ALLOWED_FAMILIES:
            assert envelope["public_claim_allowed"] is True
            assert envelope["evidence_status"] == "fresh"
            assert envelope["health_state"] == "healthy"
            assert envelope["fallback_mode"] == "none"
            assert envelope["blocked_reasons"] == []
            assert any(
                ref.startswith("wcs-snapshot:") for ref in envelope["public_claim_basis_refs"]
            )
        else:
            assert envelope["public_claim_allowed"] is False
            assert envelope["public_claim_basis_refs"] == []


def test_stale_missing_and_expired_state_fail_closed_to_quiet_fallbacks() -> None:
    fixtures = _fixtures_by_family()
    validator = _validator()

    for family in ("stale", "expired"):
        envelope = fixtures[family]
        assert envelope["evidence_status"] == "stale"
        assert envelope["health_state"] == "stale"
        assert envelope["fallback_mode"] in FAIL_CLOSED_FALLBACKS
        assert envelope["public_claim_allowed"] is False

    missing = copy.deepcopy(fixtures["stale"])
    missing["state_id"] = "scrim_state:missing:test"
    missing["evidence_status"] = "missing"
    missing["health_state"] = "missing"
    missing["fallback_mode"] = "neutral_hold"
    missing["blocked_reasons"] = ["missing_wcs_snapshot"]
    validator.validate(missing)

    stale_bad = copy.deepcopy(fixtures["stale"])
    stale_bad["fallback_mode"] = "none"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(stale_bad)

    missing_bad = copy.deepcopy(missing)
    missing_bad["public_claim_allowed"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(missing_bad)


def test_blocked_and_held_fixtures_carry_auditable_reasons() -> None:
    fixtures = _fixtures_by_family()

    expected_reasons = {
        "rights_blocked": {"rights_blocked"},
        "consent_privacy_blocked": {"privacy_blocked", "consent_blocked"},
        "monetization_held": {"monetization_readiness_missing", "conversion_held"},
        "refusal": {"refusal_boundary", "missing_evidence_ref"},
        "correction": {"correction_boundary"},
        "health_failed": {"health_failed", "world_surface_blocked"},
    }

    for family, reasons in expected_reasons.items():
        envelope = fixtures[family]
        assert set(envelope["blocked_reasons"]) == reasons
        assert envelope["public_claim_allowed"] is False
        assert envelope["fallback_mode"] != "none"


def test_example_envelope_is_parseable_and_schema_valid() -> None:
    body = _body()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example ScrimStateEnvelope JSON block missing"

    envelope = json.loads(match.group("payload"))
    _validator().validate(envelope)

    assert envelope["schema_version"] == 1
    assert envelope["profile_id"] == "gauzy_quiet"
    assert envelope["permeability_mode"] == "semipermeable_membrane"
    assert envelope["claim_posture"] == "fresh"
    assert envelope["public_claim_allowed"] is True
    assert envelope["separation_policy"]["scrim_grants_public_claim_authority"] is False
