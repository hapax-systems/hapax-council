"""Schema contract tests for content programme run-envelope fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "content-programme-run-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "content-programme-run-envelope-fixtures.json"

EXPECTED_REQUIRED_CASES = {
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


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _runs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", payload["runs"])


def _run(payload: dict[str, Any], fixture_case: str) -> dict[str, Any]:
    return next(run for run in _runs(payload) if run["fixture_case"] == fixture_case)


def test_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "ContentProgrammeRunEnvelopeFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/content-programme-run-envelope.schema.json"


def test_schema_pins_fixture_cases_modes_and_required_fields() -> None:
    schema = _json(SCHEMA)
    run_envelope = schema["$defs"]["content_programme_run_envelope"]

    assert set(schema["x-required_fixture_cases"]) == EXPECTED_REQUIRED_CASES
    assert schema["x-public_live_negative_fixture_cases"] == [
        "public_live_negative_missing_public_event"
    ]
    assert set(schema["x-run_envelope_required_fields"]) == set(run_envelope["required"])
    assert set(schema["$defs"]["public_private_mode"]["enum"]) == {
        "private",
        "dry_run",
        "public_archive",
        "public_live",
        "public_monetizable",
    }


def test_fixture_catalog_covers_required_modes_and_negative_live_case() -> None:
    fixtures = _json(FIXTURES)
    fixture_cases = {run["fixture_case"] for run in _runs(fixtures)}

    assert set(fixtures["required_fixture_cases"]) == EXPECTED_REQUIRED_CASES
    assert fixture_cases >= EXPECTED_REQUIRED_CASES
    assert "public_live_negative_missing_public_event" in fixture_cases

    modes = {run["effective_mode"] for run in _runs(fixtures)}
    assert {"private", "dry_run", "public_archive", "public_live"} <= modes


def test_public_effective_modes_have_grounding_witnesses_rights_and_public_event_refs() -> None:
    fixtures = _json(FIXTURES)

    for run in _runs(fixtures):
        if run["effective_mode"] not in PUBLIC_EFFECTIVE_MODES:
            continue

        evidence = run["evidence_obligations"]
        wcs = run["wcs_snapshot"]
        outcomes = run["outcomes"]

        assert run["grounding_question"]["state"] == "present"
        assert evidence["source_refs"]
        assert evidence["evidence_envelope_refs"]
        assert evidence["witness_refs"]
        assert evidence["rights_refs"]
        assert evidence["public_event_readiness_refs"]
        assert evidence["grounding_gate_refs"]
        assert evidence["missing_obligations"] == []
        assert wcs["health_state"] == "healthy"
        assert wcs["public_event_ready"] is True
        assert wcs["rights_state"] in {"operator_original", "cleared"}
        assert wcs["privacy_state"] == "public_safe"
        assert run["claim_shape"]["authority_ceiling"] == "evidence_bound"
        assert run["claim_shape"]["public_claim_allowed"] is True
        assert run["blockers"] == []
        assert outcomes["public_event_refs"]
        assert outcomes["boundary_event_refs"]
        assert outcomes["outcome_envelope_refs"]


@pytest.mark.parametrize(
    ("mutation_path", "value"),
    [
        (("evidence_obligations", "witness_refs"), []),
        (("evidence_obligations", "public_event_readiness_refs"), []),
        (("evidence_obligations", "rights_refs"), []),
        (("evidence_obligations", "source_refs"), []),
        (("evidence_obligations", "grounding_gate_refs"), []),
        (("wcs_snapshot", "public_event_ready"), False),
        (("wcs_snapshot", "rights_state"), "unknown"),
        (("claim_shape", "public_claim_allowed"), False),
    ],
)
def test_public_live_fixture_fails_closed_on_missing_grounding_inputs(
    mutation_path: tuple[str, str],
    value: object,
) -> None:
    bad = deepcopy(_json(FIXTURES))
    row = _run(bad, "public_live_run")
    row[mutation_path[0]][mutation_path[1]] = value

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_public_live_without_grounding_question() -> None:
    bad = deepcopy(_json(FIXTURES))
    row = _run(bad, "public_live_run")
    row["grounding_question"] = {"state": "missing", "text": None, "source_ref": None}

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_monetizable_mode_without_monetization_evidence() -> None:
    bad = deepcopy(_json(FIXTURES))
    row = _run(bad, "monetization_blocked_run")
    row["effective_mode"] = "public_monetizable"
    row["conversion_posture"]["monetization_state"] = "ready"

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_public_live_negative_fixture_is_refused_dry_run() -> None:
    fixtures = _json(FIXTURES)
    row = _run(fixtures, "public_live_negative_missing_public_event")

    assert row["requested_mode"] == "public_live"
    assert row["effective_mode"] == "dry_run"
    assert row["final_status"] == "refused"
    assert "public_event_readiness_missing" in row["blockers"]
    assert row["evidence_obligations"]["public_event_readiness_refs"] == []
    assert "public_event_readiness" in row["evidence_obligations"]["missing_obligations"]


def test_fail_closed_policy_constants_are_non_permissive() -> None:
    schema = _json(SCHEMA)
    policy = schema["properties"]["fail_closed_policy"]["properties"]
    fixtures = _json(FIXTURES)

    for key, value in fixtures["fail_closed_policy"].items():
        assert value is False
        assert policy[key]["const"] is False


def test_schema_and_fixtures_avoid_local_absolute_paths() -> None:
    assert "/home/hapax/" not in SCHEMA.read_text(encoding="utf-8")
    assert "/home/hapax/" not in FIXTURES.read_text(encoding="utf-8")
