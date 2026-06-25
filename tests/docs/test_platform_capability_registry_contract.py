"""Schema and seed contract tests for the platform capability registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "platform-capability-registry.schema.json"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"


def _json(path: Path) -> dict[str, Any]:
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
        "sanctioned_wrapper",
        "approval_posture",
        "capability_tier",
        "worker_tier",
        "model_or_engine",
        "execution_descriptor",
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
    assert "paid_provider" in route["properties"]
    assert "paid_profile" in route["properties"]
    assert set(schema["$defs"]["authority_ceiling"]["enum"]) == {
        "authoritative",
        "frontier_review_required",
        "support_only",
        "read_only",
    }
    assert "worker" in set(schema["$defs"]["profile"]["enum"])
    assert "provider_gateway" in set(schema["$defs"]["profile"]["enum"])
    assert "plan_mode_read_only" in set(schema["$defs"]["approval_posture"]["enum"])
    assert "programmatic_auto_approve_task_scoped" in set(
        schema["$defs"]["approval_posture"]["enum"]
    )
    assert "read_only_sidecar" in set(schema["$defs"]["worker_tier"]["enum"])
    assert "evidence" in schema["$defs"]["freshness"]["required"]


def test_schema_pins_execution_descriptor_axes_and_model_catalog() -> None:
    """The execution_descriptor sub-object is a required route field carrying the five
    operator-steered axes, and model_id is a STRUCTURED dated catalog that splits the
    gpt-5.5-xhigh smuggle (gpt-5.5 distinct from the codex spark)."""
    schema = _json(SCHEMA)
    desc = schema["$defs"]["execution_descriptor"]
    assert set(desc["required"]) == {
        "model_id",
        "effort",
        "context_mode",
        "fast_mode",
        "quantization",
    }
    assert desc["additionalProperties"] is False
    assert set(schema["$defs"]["effort"]["enum"]) == {
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }
    assert "extended_1m" in set(schema["$defs"]["context_mode"]["enum"])
    model_ids = set(schema["$defs"]["model_id"]["enum"])
    assert {"gpt-5.5", "gpt-5.3-codex-spark", "claude-opus-4-8"} <= model_ids
    # the retired placeholder must NOT be a structured model identity
    assert "claude-code-default" not in model_ids


def test_seed_registry_retires_claude_code_default_and_splits_the_smuggle() -> None:
    """No route keeps the free-text 'claude-code-default' placeholder, and the smuggled
    'gpt-5.5-xhigh' is split into structured model_id + effort on codex.headless.full."""
    registry = _json(REGISTRY)
    routes = {r["route_id"]: r for r in registry["routes"]}

    for route in routes.values():
        assert route["model_or_engine"] != "claude-code-default", (
            f"{route['route_id']} still carries the retired placeholder"
        )

    codex = routes["codex.headless.full"]["execution_descriptor"]
    assert codex["model_id"] == "gpt-5.5"
    assert codex["effort"] == "xhigh"


def test_seed_registry_keeps_absent_evidence_blocked_unless_explicitly_seeded() -> None:
    registry = _json(REGISTRY)

    assert all(not route["route_id"].startswith("gemini.") for route in registry["routes"])
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


def test_supply_history_contract_projects_benchmark_overhead_and_calibration_fields() -> None:
    from shared.platform_capability_registry import (
        build_supply_vector,
        load_platform_capability_registry,
    )

    registry = load_platform_capability_registry()
    supply = build_supply_vector(registry.require("codex.headless.full"))
    history = supply.historical_performance
    history_fields = type(history).model_fields

    assert "benchmark_coverage" in history_fields
    assert "fixed_route_overhead" in history_fields
    assert "local_calibration_provenance" in history_fields
    assert history.fixed_route_overhead.fixed_cost_score == 0
