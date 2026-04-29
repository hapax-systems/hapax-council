"""Schema and seed contract tests for the World Capability Surface registry."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "world-capability-registry.schema.json"
REGISTRY = REPO_ROOT / "config" / "world-capability-registry.json"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_world_capability_schema_validates_seed_registry() -> None:
    schema = _json(SCHEMA)
    registry = _json(REGISTRY)

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(registry)

    assert schema["title"] == "WorldCapabilitySurfaceRegistry"
    assert registry["schema_version"] == 1


def test_schema_pins_required_wcs_record_fields_and_enums() -> None:
    schema = _json(SCHEMA)
    record = schema["$defs"]["world_capability_record"]
    required = set(record["required"])

    for field in (
        "capability_id",
        "grounding_role",
        "authority_ceiling",
        "grounding_status",
        "evidence_envelope_requirements",
        "witness_requirements",
        "public_claim_policy",
        "public_private_posture",
        "blocked_reasons",
        "fallback",
    ):
        assert field in required

    assert set(record["properties"]["domain"]["enum"]) >= {
        "audio",
        "camera",
        "archive",
        "public_aperture",
        "file_obsidian",
        "browser_mcp",
        "music_midi",
        "mobile_watch",
    }
    assert set(record["properties"]["direction"]["enum"]) >= {
        "observe",
        "express",
        "act",
        "route",
        "recall",
        "communicate",
        "regulate",
    }


def test_schema_and_seed_prevent_public_live_or_monetizable_defaults() -> None:
    schema = _json(SCHEMA)
    registry = _json(REGISTRY)
    policy = schema["$defs"]["public_claim_policy"]["properties"]

    assert policy["claim_public_live"]["const"] is False
    assert policy["claim_monetizable"]["const"] is False

    for record in registry["records"]:
        assert record["availability_state"] != "public_live"
        assert record["public_claim_policy"]["claim_public_live"] is False
        assert record["public_claim_policy"]["claim_monetizable"] is False
        assert record["blocked_reasons"]


def test_seed_registry_names_no_multi_operator_abstractions() -> None:
    registry_text = REGISTRY.read_text(encoding="utf-8")

    forbidden = ("multi_user", "collaboration", "auth_provider", "user_role")
    for token in forbidden:
        assert token not in registry_text


def test_seed_registry_avoids_local_absolute_source_paths() -> None:
    registry_text = REGISTRY.read_text(encoding="utf-8")

    assert "/home/hapax/" not in registry_text
