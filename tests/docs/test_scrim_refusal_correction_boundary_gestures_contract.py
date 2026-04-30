"""Contract tests for the scrim refusal/correction boundary gesture surface."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "scrim-refusal-correction-boundary-gestures.schema.json"
FIXTURES = REPO_ROOT / "config" / "scrim-refusal-correction-boundary-gestures-fixtures.json"


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _fixtures() -> dict[str, object]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def test_schema_names_required_contract_fields() -> None:
    schema = _schema()
    fixture_required = set(schema["$defs"]["fixture"]["required"])
    boundary_required = set(schema["$defs"]["boundary_event"]["required"])

    for field in (
        "boundary_event",
        "wcs_source_refs",
        "run_store_ref",
        "audit_log_ref",
        "health_ref",
        "expected",
    ):
        assert field in fixture_required

    for field in (
        "boundary_id",
        "boundary_type",
        "public_private_mode",
        "evidence_refs",
        "no_expert_system_gate",
        "claim_shape",
        "public_event_mapping",
        "dry_run_unavailable_reasons",
    ):
        assert field in boundary_required


def test_schema_pins_posture_vocabulary_and_no_grant_policy() -> None:
    schema = _schema()

    assert set(schema["$defs"]["boundary_posture"]["enum"]) == {
        "refusal",
        "correction",
        "uncertainty",
        "stale_source",
        "rights_blocked",
        "privacy_blocked",
        "monetization_held",
        "public_event_held",
    }
    assert schema["x-fail_closed_policy"] == {
        "scrim_grants_truth": False,
        "scrim_grants_rights": False,
        "scrim_grants_safety": False,
        "scrim_grants_public_status": False,
        "scrim_grants_monetization_status": False,
        "scrim_implies_public_fanout": False,
        "aesthetic_emphasis_validates_blocked_claim": False,
        "private_blocked_details_can_be_foregrounded": False,
    }


def test_fixture_families_cover_acceptance_criteria() -> None:
    payload = _fixtures()
    families = {fixture["family"] for fixture in payload["fixtures"]}

    assert families == set(payload["boundary_postures"])
    assert {
        "refusal",
        "correction",
        "uncertainty",
        "stale_source",
        "rights_blocked",
        "privacy_blocked",
        "monetization_held",
        "public_event_held",
    } <= families


def test_task_acceptance_remains_machine_checked() -> None:
    payload = _fixtures()
    fixtures = {fixture["fixture_id"]: fixture for fixture in payload["fixtures"]}

    refusal = fixtures["public_safe_refusal_success"]["expected"]
    assert refusal["programme_output_success"] is True
    assert refusal["public_safe_artifact"] is True
    assert refusal["artifact_visibility"] == "foreground_public_safe"

    blocked = fixtures["rights_blocked_metadata_first"]["expected"]
    assert blocked["programme_output_success"] is False
    assert blocked["artifact_visibility"] == "metadata_only"

    for fixture in fixtures.values():
        assert fixture["run_store_ref"]
        assert fixture["audit_log_ref"]
        assert fixture["health_ref"]
