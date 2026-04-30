"""Schema contract tests for audio marker probe harness fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.audio_marker_probe_harness import (
    FAIL_CLOSED_POLICY,
    REQUIRED_AUDIO_MARKER_FIXTURE_CASES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "audio-marker-probe-harness.schema.json"
FIXTURES = REPO_ROOT / "config" / "audio-marker-probe-fixtures.json"
LOCAL_HOME_PREFIX = "/".join(("", "home", "hapax", ""))


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_audio_marker_probe_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "AudioMarkerProbeHarness"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/audio-marker-probe-harness.schema.json"


def test_schema_pins_required_cases_modes_states_and_fail_closed_policy() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    assert set(schema["x-required_fixture_cases"]) == REQUIRED_AUDIO_MARKER_FIXTURE_CASES
    assert set(fixtures["required_fixture_cases"]) == REQUIRED_AUDIO_MARKER_FIXTURE_CASES
    assert set(schema["x-marker_probe_kinds"]) == {"public", "private", "no_leak"}
    assert set(schema["x-modes"]) == {"dry_run", "fixture", "live"}
    assert set(schema["x-states"]) == {"dry_run_planned", "witnessed", "blocked", "failed"}
    assert fixtures["fail_closed_policy"] == FAIL_CLOSED_POLICY


def test_fixture_catalog_covers_public_private_no_leak_and_negative_leak_cases() -> None:
    fixtures = _json(FIXTURES)
    probes = cast("list[dict[str, Any]]", fixtures["probes"])
    by_case = {probe["fixture_case"]: probe for probe in probes}

    assert set(by_case) >= REQUIRED_AUDIO_MARKER_FIXTURE_CASES
    assert by_case["public_marker_witnessed"]["witness_class"] == "public_audio_witness"
    assert by_case["private_marker_witnessed_no_leak"]["witness_class"] == ("private_audio_witness")
    assert by_case["no_leak_clean"]["witness_class"] == "no_leak_audio_witness"
    assert by_case["private_marker_leaked_public_negative"]["expected_health_state"] == "unsafe"
    assert by_case["private_marker_leaked_public_negative"]["expected_failure_class"] == (
        "private_marker_leaked_public"
    )
    assert by_case["live_execution_blocked_without_authorization"]["mode"] == "live"
    assert (
        by_case["live_execution_blocked_without_authorization"]["live_execution_requested"] is True
    )


def test_schema_rejects_truthy_fail_closed_policy_and_wrong_witness_class() -> None:
    fixtures = _json(FIXTURES)
    bad_policy = json.loads(json.dumps(fixtures))
    bad_policy["fail_closed_policy"]["live_execution_without_authorization"] = True

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad_policy)

    bad_witness = json.loads(json.dumps(fixtures))
    bad_witness["probes"][0]["witness_class"] = "private_audio_witness"

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad_witness)


def test_fixture_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert LOCAL_HOME_PREFIX not in fixture_text
    assert LOCAL_HOME_PREFIX not in schema_text
