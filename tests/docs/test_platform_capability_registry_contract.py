"""Schema and seed contract tests for the platform capability registry."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "platform-capability-registry.schema.json"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_platform_capability_schema_validates_seed_registry() -> None:
    schema = _json(SCHEMA)
    registry = _json(REGISTRY)

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(registry)

    assert schema["title"] == "PlatformCapabilityRegistry"
    assert registry["registry_schema"] == 1


def test_schema_pins_r2_route_fields_and_enums() -> None:
    schema = _json(SCHEMA)
    route = schema["$defs"]["platform_capability_route"]
    required = set(route["required"])

    for field in (
        "route_id",
        "platform",
        "mode",
        "profile",
        "model_or_engine",
        "auth_surface",
        "capacity_pool",
        "mutability",
        "authority_ceiling",
        "tool_access",
        "privacy_posture",
        "quality_envelope",
        "capability_scores",
        "tool_state",
        "context_limits",
        "telemetry",
        "freshness",
        "known_unknowns",
    ):
        assert field in required

    assert set(schema["$defs"]["platform"]["enum"]) >= {
        "claude",
        "codex",
        "gemini",
        "vibe",
        "antigrav",
        "local_tool",
        "api",
    }
    assert set(schema["$defs"]["authority_ceiling"]["enum"]) == {
        "authoritative",
        "frontier_review_required",
        "support_only",
        "read_only",
    }
    assert "evidence" in schema["$defs"]["freshness"]["required"]


def test_seed_registry_keeps_absent_evidence_blocked_unless_explicitly_seeded() -> None:
    registry = _json(REGISTRY)

    for route in registry["routes"]:
        freshness = route["freshness"]
        assert route["route_state"] == "blocked"
        assert route["blocked_reasons"]
        for surface in ("capability", "quota", "resource", "provider_docs"):
            surface_evidence = freshness["evidence"][surface]
            assert surface_evidence["evidence_refs"] or surface_evidence["blocked_reasons"]
            if freshness[f"{surface}_checked_at"] is None:
                assert surface_evidence["blocked_reasons"]
            else:
                assert surface_evidence["evidence_refs"]


def test_seed_registry_names_no_dispatcher_policy_integration() -> None:
    registry_text = REGISTRY.read_text(encoding="utf-8")

    forbidden = ("route_choice_enabled", "auto_dispatch_policy", "paid_spend_authorized")
    for token in forbidden:
        assert token not in registry_text


def test_seed_registry_records_dimensional_scores_with_evidence() -> None:
    registry = _json(REGISTRY)

    for route in registry["routes"]:
        scores = route["capability_scores"]
        assert set(scores) >= {"grounding", "source_editing", "test_authoring"}
        for score in scores.values():
            assert 0 <= score["score"] <= 5
            assert 0 <= score["confidence"] <= 5
            assert score["evidence_refs"]
            assert score["stale_after"]
        assert route["tool_state"]
