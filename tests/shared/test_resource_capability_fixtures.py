"""Fixture/schema tests for private resource-capability projections."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.resource_capability import (
    FORBIDDEN_PROVIDER_WRITE_SCOPES,
    REQUIRED_MODELS,
    RESOURCE_CAPABILITY_SCHEMA_REF,
    ResourceCapabilityError,
    load_resource_capability_fixtures,
)

FIXTURE_PATH = Path("config/resource-capability-fixtures.json")
SCHEMA_PATH = Path("schemas/resource-capability.schema.json")


def test_fixture_loader_covers_required_models_and_scopes() -> None:
    fixtures = load_resource_capability_fixtures()

    assert set(fixtures.required_models) == REQUIRED_MODELS
    assert {scope.value for scope in fixtures.forbidden_provider_write_scopes} == (
        FORBIDDEN_PROVIDER_WRITE_SCOPES
    )
    assert fixtures.schema_ref == RESOURCE_CAPABILITY_SCHEMA_REF
    assert fixtures.fail_closed_policy.model_dump() == {
        "technical_rail_readiness_as_public_offer": False,
        "high_value_upgrades_truth_or_claims": False,
        "nominal_value_substitutes_cash_equivalent": False,
        "revenue_value_substitutes_operational_capability_value": False,
        "public_claim_without_envelope": False,
        "stale_surface_conflict_activates_capability": False,
        "semantic_transaction_trace_public_by_default": False,
        "expected_mail_candidate_allows_body_or_thread": False,
        "calendar_write_allows_attendees_or_notifications_by_default": False,
        "provider_write_unknown_scope_allowed": False,
    }


def test_schema_metadata_matches_typed_contract() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["$id"] == "https://hapax.council/schemas/resource-capability.schema.json"
    assert set(schema["x-required_models"]) == REQUIRED_MODELS
    assert set(schema["x-forbidden_provider_write_scopes"]) == FORBIDDEN_PROVIDER_WRITE_SCOPES
    assert schema["properties"]["schema_ref"]["const"] == RESOURCE_CAPABILITY_SCHEMA_REF


def test_fixture_file_points_to_schema_and_loads_as_json_object() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert isinstance(payload, dict)
    assert payload["schema_ref"] == RESOURCE_CAPABILITY_SCHEMA_REF
    assert "semantic_transaction_traces" in payload
    assert "transaction_pressure_ledgers" in payload
    assert payload["semantic_transaction_traces"][0]["public_projection_allowed"] is False
    assert payload["transaction_pressure_ledgers"][0]["external_effect_authorized"] is False


def test_fixture_mutation_missing_required_model_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["required_models"] = [
        model for model in payload["required_models"] if model != "SemanticTransactionTrace"
    ]
    path = tmp_path / "bad-resource-capability-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ResourceCapabilityError, match="required_models mismatch"):
        load_resource_capability_fixtures(path)


def test_fixture_mutation_public_trace_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["semantic_transaction_traces"][0]["privacy_scope"] = "public"
    path = tmp_path / "bad-resource-capability-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ResourceCapabilityError, match="privacy_scope"):
        load_resource_capability_fixtures(path)


def test_fixture_mutation_authorized_external_effect_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["transaction_pressure_ledgers"][0]["external_effect_authorized"] = True
    path = tmp_path / "bad-resource-capability-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ResourceCapabilityError, match="False"):
        load_resource_capability_fixtures(path)
