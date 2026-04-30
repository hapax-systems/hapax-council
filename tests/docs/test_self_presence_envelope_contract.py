"""Schema contract tests for the Hapax Unified self-presence ontology."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.self_presence import (
    PROMPT_ONLY_NON_WITNESS_STATES,
    REQUIRED_FIXTURE_CASES,
    REQUIRED_MAPPING_TARGETS,
    REQUIRED_ONTOLOGY_TERMS,
    ROLES_ARE_OFFICES_STATEMENT,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "self-presence-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "self-presence-envelope-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _envelopes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", payload["envelopes"])


def test_self_presence_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "SelfPresenceEnvelopeFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/self-presence-envelope.schema.json"


def test_schema_pins_ontology_terms_fixture_cases_and_mapping_targets() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    assert set(schema["x-required_ontology_terms"]) == REQUIRED_ONTOLOGY_TERMS
    assert set(schema["x-required_fixture_cases"]) == REQUIRED_FIXTURE_CASES
    assert set(schema["x-required_mapping_targets"]) == REQUIRED_MAPPING_TARGETS
    assert set(schema["x-prompt_only_non_witness_states"]) == PROMPT_ONLY_NON_WITNESS_STATES

    assert {row["term"] for row in fixtures["ontology_term_mappings"]} == REQUIRED_ONTOLOGY_TERMS
    assert {row["fixture_case"] for row in fixtures["envelopes"]} == REQUIRED_FIXTURE_CASES
    for row in fixtures["ontology_term_mappings"]:
        assert set(row["maps_to"]) == REQUIRED_MAPPING_TARGETS
        assert all(row["maps_to"][target] for target in REQUIRED_MAPPING_TARGETS)


def test_roles_are_offices_not_masks_or_activities() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    assert schema["properties"]["roles_are_offices_statement"]["const"] == (
        ROLES_ARE_OFFICES_STATEMENT
    )
    assert fixtures["roles_are_offices_statement"] == ROLES_ARE_OFFICES_STATEMENT
    for envelope in _envelopes(fixtures):
        role_state = envelope["role_state"]
        assert role_state["roles_are_offices_not_masks"] is True
        assert role_state["office"] not in {"mask", "persona", "activity"}


@pytest.mark.parametrize(
    ("fixture_case", "bad_outcome"),
    [
        ("public_speech_candidate", "public_speech_allowed"),
        ("archive_only_referent", "public_speech_allowed"),
        ("synthetic_only_provenance", "public_speech_allowed"),
        ("blocked_route", "public_speech_allowed"),
    ],
)
def test_schema_rejects_public_speech_allowed_without_required_witnesses(
    fixture_case: str, bad_outcome: str
) -> None:
    bad = deepcopy(_json(FIXTURES))
    row = next(envelope for envelope in _envelopes(bad) if envelope["fixture_case"] == fixture_case)
    row["allowed_outcomes"] = [bad_outcome]

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_public_live_claim_without_witness_refs() -> None:
    bad = deepcopy(_json(FIXTURES))
    row = next(
        envelope
        for envelope in _envelopes(bad)
        if envelope["fixture_case"] == "livestream_referent"
    )
    row["claim_bindings"][0]["witness_refs"] = []

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_prompt_only_states_are_cataloged_as_non_witness_support() -> None:
    fixtures = _json(FIXTURES)

    assert set(fixtures["prompt_only_non_witness_states"]) == PROMPT_ONLY_NON_WITNESS_STATES
    prompt_only_cases = {
        row["fixture_case"]
        for row in _envelopes(fixtures)
        for event in row["aperture_events"]
        if PROMPT_ONLY_NON_WITNESS_STATES & set(event["support_states"])
    }
    assert prompt_only_cases >= {
        "public_speech_candidate",
        "synthetic_only_provenance",
        "blocked_route",
    }


def test_fixture_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
