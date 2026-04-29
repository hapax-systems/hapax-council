"""Schema contract tests for WCS witness probe runtime fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.wcs_witness_probe_runtime import REQUIRED_PROBE_STATES, REQUIRED_WITNESS_CLASSES

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "wcs-witness-probe-runtime.schema.json"
FIXTURES = REPO_ROOT / "config" / "wcs-witness-probe-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_wcs_witness_probe_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "WCSWitnessProbeRuntime"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/wcs-witness-probe-runtime.schema.json"


def test_schema_pins_required_witness_classes_and_probe_states() -> None:
    schema = _json(SCHEMA)
    defs = schema["$defs"]

    assert set(schema["x-required_witness_classes"]) == REQUIRED_WITNESS_CLASSES
    assert set(schema["x-required_probe_states"]) == REQUIRED_PROBE_STATES
    assert set(defs["witness_class_id"]["enum"]) == REQUIRED_WITNESS_CLASSES
    assert set(defs["probe_state"]["enum"]) == REQUIRED_PROBE_STATES


def test_fixture_catalog_covers_required_classes_and_states() -> None:
    fixtures = _json(FIXTURES)
    interfaces = cast("list[dict[str, Any]]", fixtures["witness_class_interfaces"])
    probes = cast("list[dict[str, Any]]", fixtures["probes"])

    assert {interface["witness_class"] for interface in interfaces} == REQUIRED_WITNESS_CLASSES
    assert set(fixtures["states"]) == REQUIRED_PROBE_STATES
    assert {probe["state"] for probe in probes} == REQUIRED_PROBE_STATES
    assert {
        "audio.broadcast_voice.commanded_no_egress_witness",
        "audio.broadcast_voice.public_egress_witnessed",
    } <= {probe["probe_id"] for probe in probes}


def test_schema_rejects_expert_oracle_and_missing_public_witness_policy() -> None:
    schema = _json(SCHEMA)
    interface = schema["$defs"]["witness_class_interface"]["properties"]
    policy = schema["properties"]["fail_closed_policy"]["properties"]
    probe = schema["$defs"]["probe_record"]["properties"]

    assert interface["is_truth_oracle"]["const"] is False
    assert interface["source_ref_required"]["const"] is True
    assert probe["certifies_declared_obligation_only"]["const"] is True
    assert policy["selected_or_commanded_is_public_truth"]["const"] is False
    assert policy["missing_witness_allows_public_claim"]["const"] is False
    assert policy["stale_witness_allows_public_claim"]["const"] is False
    assert policy["probes_are_expert_truth_oracle"]["const"] is False

    fixtures = _json(FIXTURES)
    bad = json.loads(json.dumps(fixtures))
    bad["witness_class_interfaces"][0]["is_truth_oracle"] = True
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_requires_blocked_reason_for_stale_or_failed_probe() -> None:
    fixtures = _json(FIXTURES)
    bad = json.loads(json.dumps(fixtures))
    for probe in bad["probes"]:
        if probe["probe_id"] == "audio.broadcast_voice.stale_public_egress":
            probe["blocked_reasons"] = []

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_fixture_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
