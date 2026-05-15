"""Schema contract tests for capability classification inventory fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "capability-classification-inventory.schema.json"
FIXTURES = REPO_ROOT / "config" / "capability-classification-inventory.json"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_capability_classification_schema_validates_inventory_fixtures() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(fixtures)

    assert schema["title"] == "CapabilityClassificationInventory"
    assert fixtures["schema_version"] == 1


def test_schema_pins_inventory_row_fields_and_semantic_ontology() -> None:
    schema = _json(SCHEMA)
    row = schema["$defs"]["CapabilityClassificationRow"]
    required = set(row["required"])

    for field in (
        "classification_id",
        "surface_id",
        "surface_family",
        "realm",
        "direction",
        "gibson_verb",
        "semantic_description",
        "producer",
        "concrete_interface",
        "availability_probe",
        "freshness_ttl_s",
        "evidence_ref",
        "privacy_class",
        "rights_class",
        "content_risk",
        "monetization_risk",
        "consent_policy",
        "claim_authority_ceiling",
        "public_claim_policy",
        "kill_switch_behavior",
        "fallback_policy",
        "witness_requirements",
        "recruitment_family",
        "missing_record_action",
        "kind",
        "relations",
        "projection",
    ):
        assert field in required


def test_schema_pins_requested_surface_families() -> None:
    schema = _json(SCHEMA)
    families = set(schema["$defs"]["SurfaceFamily"]["enum"])

    assert families >= {
        "affordance_record",
        "tool_schema",
        "mcp_tool",
        "runtime_service",
        "state_file",
        "device",
        "audio_route",
        "video_surface",
        "midi_surface",
        "companion_device",
        "local_api",
        "docker_container",
        "model_provider",
        "search_provider",
        "publication_endpoint",
        "archive_processor",
        "storage_sync",
        "public_event",
        "governance_surface",
        "infrastructure",
    }


def test_schema_pins_projection_consent_scope_fields() -> None:
    schema = _json(SCHEMA)
    projection_fields = set(schema["$defs"]["CapabilityProjection"]["properties"])

    assert "consent_person_id" in projection_fields
    assert "consent_data_category" in projection_fields


def test_fixture_contract_avoids_absolute_local_paths_and_user_abstractions() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "multi_user" not in fixture_text
    assert "auth_provider" not in fixture_text
