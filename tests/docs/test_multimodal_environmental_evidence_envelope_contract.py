"""Schema contract tests for multimodal environmental evidence fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.multimodal_environmental_evidence_envelope import (
    FAIL_CLOSED_POLICY,
    MULTIMODAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS,
    REQUIRED_FIXTURE_CASES,
    REQUIRED_SOURCE_CLASSES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "multimodal-environmental-evidence-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "multimodal-environmental-evidence-envelope-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _envelopes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", payload["envelopes"])


def test_multimodal_environmental_evidence_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "MultimodalEnvironmentalEvidenceEnvelopeFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == (
        "schemas/multimodal-environmental-evidence-envelope.schema.json"
    )


def test_schema_pins_source_classes_fixture_cases_required_fields_and_policy() -> None:
    schema = _json(SCHEMA)
    defs = cast("dict[str, Any]", schema["$defs"])
    envelope = cast("dict[str, Any]", defs["multimodal_evidence_envelope"])

    assert set(schema["x-required_source_classes"]) == REQUIRED_SOURCE_CLASSES
    assert set(schema["x-required_fixture_cases"]) == REQUIRED_FIXTURE_CASES
    assert schema["x-fail_closed_policy"] == FAIL_CLOSED_POLICY
    assert set(schema["x-evidence_envelope_required_fields"]) == set(
        MULTIMODAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS
    )
    assert set(envelope["required"]) == set(MULTIMODAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS)
    assert envelope["properties"]["source_family"]["$ref"] == "#/$defs/source_family"
    assert envelope["properties"]["source_class"]["$ref"] == "#/$defs/source_class"
    assert envelope["properties"]["witness_kind"]["$ref"] == "#/$defs/witness_kind"
    assert envelope["properties"]["claim_authority_ceiling"]["$ref"] == (
        "#/$defs/claim_authority_ceiling"
    )


def test_fixture_catalog_covers_required_source_classes_and_fixture_cases() -> None:
    fixtures = _json(FIXTURES)
    envelopes = _envelopes(fixtures)

    assert set(fixtures["required_source_classes"]) == REQUIRED_SOURCE_CLASSES
    assert set(fixtures["required_fixture_cases"]) == REQUIRED_FIXTURE_CASES
    assert {row["source_class"] for row in envelopes} >= REQUIRED_SOURCE_CLASSES
    assert {row["fixture_case"] for row in envelopes} >= REQUIRED_FIXTURE_CASES


def test_schema_rejects_public_gate_without_public_event_or_witness_refs() -> None:
    bad = deepcopy(_json(FIXTURES))
    row = next(
        envelope
        for envelope in _envelopes(bad)
        if envelope["envelope_id"] == "multimodal-evidence:public.reembed.clip"
    )
    row["public_event_refs"] = []
    row["witness_refs"] = []

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_classifier_fallback_mutated_to_claim_authority() -> None:
    bad = deepcopy(_json(FIXTURES))
    row = next(
        envelope
        for envelope in _envelopes(bad)
        if envelope["envelope_id"] == "multimodal-evidence:classifier.scene.fallback-zero"
    )
    row["claim_authority_ceiling"] = "public_gate_required"
    row["privacy_state"] = "public_safe"
    row["rights_state"] = "public_clear"
    row["public_event_refs"] = ["public-event:bad"]

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_undertrained_ir_negative_absence() -> None:
    bad = deepcopy(_json(FIXTURES))
    row = next(
        envelope
        for envelope in _envelopes(bad)
        if envelope["envelope_id"] == "multimodal-evidence:ir.desk.no-detection-undertrained"
    )
    row["observation_polarity"] = "negative"

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_render_state_mutated_to_public_gate() -> None:
    bad = deepcopy(_json(FIXTURES))
    row = next(
        envelope
        for envelope in _envelopes(bad)
        if envelope["envelope_id"] == "multimodal-evidence:ward.decorative.render-state"
    )
    row["claim_authority_ceiling"] = "public_gate_required"
    row["privacy_state"] = "public_safe"
    row["rights_state"] = "public_clear"
    row["public_event_refs"] = ["public-event:bad"]

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_multimodal_fixture_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
