"""Semantic pins for content programme run-envelope fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "config" / "content-programme-run-envelope-fixtures.json"

REQUIRED_CASES = {
    "private_run",
    "dry_run",
    "public_archive_run",
    "public_live_run",
    "monetization_blocked_run",
    "refusal_run",
    "correction_run",
    "conversion_held_run",
}
PUBLIC_EFFECTIVE_MODES = {"public_archive", "public_live", "public_monetizable"}


def _fixtures() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(FIXTURES.read_text(encoding="utf-8")))


def _runs() -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", _fixtures()["runs"])


def _run(fixture_case: str) -> dict[str, Any]:
    return next(run for run in _runs() if run["fixture_case"] == fixture_case)


def test_fixtures_cover_required_run_cases() -> None:
    fixture_payload = _fixtures()
    fixture_cases = {run["fixture_case"] for run in _runs()}

    assert set(fixture_payload["required_fixture_cases"]) == REQUIRED_CASES
    assert fixture_cases >= REQUIRED_CASES


def test_public_live_success_and_public_live_negative_are_distinct() -> None:
    live = _run("public_live_run")
    negative = _run("public_live_negative_missing_public_event")

    assert live["requested_mode"] == "public_live"
    assert live["effective_mode"] == "public_live"
    assert live["blockers"] == []
    assert live["outcomes"]["public_event_refs"]

    assert negative["requested_mode"] == "public_live"
    assert negative["effective_mode"] == "dry_run"
    assert negative["final_status"] == "refused"
    assert "public_event_readiness_missing" in negative["blockers"]
    assert negative["outcomes"]["public_event_refs"] == []


def test_public_modes_are_evidence_bound_and_blocker_free() -> None:
    for run in _runs():
        if run["effective_mode"] not in PUBLIC_EFFECTIVE_MODES:
            continue

        evidence = run["evidence_obligations"]
        assert run["grounding_question"]["state"] == "present"
        assert run["claim_shape"]["authority_ceiling"] == "evidence_bound"
        assert run["claim_shape"]["public_claim_allowed"] is True
        assert run["wcs_snapshot"]["public_event_ready"] is True
        assert run["wcs_snapshot"]["privacy_state"] == "public_safe"
        assert run["blockers"] == []
        assert evidence["evidence_envelope_refs"]
        assert evidence["witness_refs"]
        assert evidence["rights_refs"]
        assert evidence["grounding_gate_refs"]
        assert evidence["public_event_readiness_refs"]


def test_missing_grounding_question_forces_refusal_dry_run() -> None:
    refusal = _run("refusal_run")

    assert refusal["grounding_question"]["state"] == "missing"
    assert refusal["effective_mode"] == "dry_run"
    assert refusal["final_status"] == "refused"
    assert "missing_grounding_question" in refusal["blockers"]
    assert refusal["claim_shape"]["public_claim_allowed"] is False


def test_monetization_blocker_does_not_override_public_grounding() -> None:
    blocked = _run("monetization_blocked_run")

    assert blocked["requested_mode"] == "public_monetizable"
    assert blocked["effective_mode"] == "public_archive"
    assert blocked["conversion_posture"]["monetization_state"] == "blocked"
    assert blocked["conversion_posture"]["monetization_evidence_refs"] == []
    assert "monetization" in blocked["conversion_posture"]["blocked_routes"]
    assert blocked["conversion_posture"]["revenue_can_override_grounding"] is False


def test_correction_and_conversion_held_postures_are_explicit() -> None:
    correction = _run("correction_run")
    held = _run("conversion_held_run")

    assert correction["final_status"] == "corrected"
    assert correction["outcomes"]["refusal_or_correction_refs"]
    assert "correction_artifact" in correction["conversion_posture"]["allowed_routes"]

    assert held["final_status"] == "conversion_held"
    assert held["conversion_posture"]["conversion_state"] == "held"
    assert held["conversion_posture"]["held_routes"] == ["shorts"]


def test_operator_labor_policy_prevents_recurring_manual_programming() -> None:
    for run in _runs():
        policy = run["operator_labor_policy"]

        assert policy["single_operator_only"] is True
        assert policy["recurring_operator_nomination_required"] is False
        assert policy["manual_calendar_required"] is False
        assert policy["supporter_request_queue_allowed"] is False
