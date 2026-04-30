"""Schema contract tests for TemporalEvidenceEnvelope fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.temporal_band_evidence import (
    FAIL_CLOSED_POLICY,
    REQUIRED_SHM_FIXTURE_CASES,
    REQUIRED_TEMPORAL_BANDS,
    TEMPORAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "temporal-band-evidence-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "temporal-band-evidence-envelope-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _envelopes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", payload["envelopes"])


def _claim_fixtures(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", payload["claim_support_fixtures"])


def test_temporal_band_evidence_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "TemporalBandEvidenceEnvelopeFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/temporal-band-evidence-envelope.schema.json"


def test_schema_pins_temporal_band_shm_and_required_field_contracts() -> None:
    schema = _json(SCHEMA)
    defs = cast("dict[str, Any]", schema["$defs"])
    envelope = cast("dict[str, Any]", defs["temporal_evidence_envelope"])

    assert set(schema["x-required_temporal_bands"]) == REQUIRED_TEMPORAL_BANDS
    assert set(schema["x-required_shm_fixture_cases"]) == REQUIRED_SHM_FIXTURE_CASES
    assert schema["x-fail_closed_policy"] == FAIL_CLOSED_POLICY
    assert set(schema["x-evidence_envelope_required_fields"]) == set(
        TEMPORAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS
    )
    assert set(envelope["required"]) == set(TEMPORAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS) | {
        "fixture_case"
    }
    assert envelope["properties"]["temporal_band"]["$ref"] == "#/$defs/temporal_band"
    assert envelope["properties"]["evidence_role"]["$ref"] == "#/$defs/evidence_role"
    assert envelope["properties"]["authority_ceiling"]["$ref"] == "#/$defs/authority_ceiling"


def test_fixture_catalog_covers_temporal_bands_and_shm_read_states() -> None:
    fixtures = _json(FIXTURES)
    envelopes = _envelopes(fixtures)
    shm_rows = cast("list[dict[str, Any]]", fixtures["shm_payload_fixtures"])

    assert set(fixtures["temporal_bands"]) == REQUIRED_TEMPORAL_BANDS
    assert set(fixtures["shm_fixture_cases"]) == REQUIRED_SHM_FIXTURE_CASES
    assert {envelope["temporal_band"] for envelope in envelopes} >= REQUIRED_TEMPORAL_BANDS
    assert {row["fixture_case"] for row in shm_rows} == REQUIRED_SHM_FIXTURE_CASES
    assert {
        row["fixture_case"]
        for row in shm_rows
        if row["producer_failure"]
        and row["source_payload_state"] in {"missing", "malformed", "empty"}
    } == {"missing", "malformed", "empty"}


@pytest.mark.parametrize(
    "fixture_case",
    [
        "raw_xml_public_director_claim",
        "protention_current_claim",
        "retention_current_claim",
        "stale_retention_without_age_window",
        "producer_failure_positive_claim",
        "expired_high_posterior_current_claim",
    ],
)
def test_schema_rejects_negative_claim_fixtures_mutated_to_allowed(fixture_case: str) -> None:
    bad = deepcopy(_json(FIXTURES))
    row = next(row for row in _claim_fixtures(bad) if row["fixture_case"] == fixture_case)
    row["expected"]["allowed"] = True
    row["expected"]["status"] = "allowed"
    row["expected"]["rendered_claim_mode"] = "public_live"

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_public_fresh_impression_without_witness_and_span_refs() -> None:
    bad = deepcopy(_json(FIXTURES))
    row = next(
        envelope
        for envelope in _envelopes(bad)
        if envelope["fixture_case"] == "fresh_impression_public"
    )
    row["witness_refs"] = []
    row["span_refs"] = []

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_producer_failure_with_positive_witness_refs() -> None:
    bad = deepcopy(_json(FIXTURES))
    row = next(
        envelope
        for envelope in _envelopes(bad)
        if envelope["fixture_case"] == "producer_failure_missing"
    )
    row["witness_refs"] = ["witness:fake-positive-world-state"]

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_fail_closed_policy_constants_are_non_permissive() -> None:
    schema = _json(SCHEMA)
    policy = schema["$defs"]["fail_closed_policy"]["properties"]
    fixtures = _json(FIXTURES)

    for key, value in fixtures["fail_closed_policy"].items():
        assert value is False
        assert policy[key]["const"] is False


def test_temporal_band_fixture_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
