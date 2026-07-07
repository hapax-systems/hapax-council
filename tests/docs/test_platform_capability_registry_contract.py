"""Schema and seed contract tests for the platform capability registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_type_hints

import jsonschema
import pytest
from pydantic import ValidationError

from shared.capability_surface_delta import (
    AuthorityCeiling as DeltaAuthorityCeiling,
)
from shared.capability_surface_delta import (
    CapabilitySurfaceDelta,
    DeltaKind,
    FreshnessState,
    RequiredIntakeAction,
    load_capability_surface_delta_fixtures,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "platform-capability-registry.schema.json"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _surface_delta(surface_id: str) -> CapabilitySurfaceDelta:
    return CapabilitySurfaceDelta(
        delta_id=f"test:{surface_id}",
        source="pytest",
        observed_at="2026-07-04T01:50:00Z",
        detected_by="test-platform-capability-registry-contract",
        surface_id=surface_id,
        delta_kind=DeltaKind.NEW_CAPABILITY,
        prior_descriptor_ref=None,
        observed_descriptor_ref=f"test-observed:{surface_id}",
        evidence_refs=["test:surface-delta"],
        authority_ceiling=DeltaAuthorityCeiling.FRONTIER_REVIEW_REQUIRED,
        affected_resource_pools=["test_resource_pool"],
        privacy_sensitive=False,
        public_egress=False,
        money_rail=False,
        freshness_state=FreshnessState.DELTA_PENDING,
        required_intake_action=RequiredIntakeAction.MINT_INTAKE_ITEM,
        remediation_ref="cc-task:test-capability-surface-delta",
        summary=f"test surface delta for {surface_id}",
    )


def test_platform_capability_schema_validates_seed_registry() -> None:
    schema = _json(SCHEMA)
    registry = _json(REGISTRY)

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(registry)

    assert schema["title"] == "PlatformCapabilityRegistry"
    assert registry["registry_schema"] == 1


def test_platform_capability_schema_rejects_antigrav_route_platform() -> None:
    schema = _json(SCHEMA)
    registry = _json(REGISTRY)
    poisoned = {
        **registry,
        "routes": [{**registry["routes"][0], "platform": "antigrav"}, *registry["routes"][1:]],
    }

    with pytest.raises(jsonschema.ValidationError, match="antigrav"):
        jsonschema.Draft202012Validator(schema).validate(poisoned)


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

    assert "historical_performance" in route["properties"]
    history = schema["$defs"]["historical_performance"]
    assert history["properties"]["class_posteriors"]["additionalProperties"] == {
        "$ref": "#/$defs/score_confidence"
    }
    assert history["properties"]["fixed_route_overhead"] == {"$ref": "#/$defs/fixed_route_overhead"}

    assert set(schema["$defs"]["platform"]["enum"]) >= {
        "agy",
        "claude",
        "codex",
        "gemini",
        "vibe",
        "local_tool",
        "api",
    }
    assert "antigrav" not in schema["$defs"]["platform"]["enum"]
    assert "paid_provider" in route["properties"]
    assert "paid_profile" in route["properties"]
    assert "omitted_capability_shapes" in schema["required"]
    assert schema["properties"]["omitted_capability_shapes"]["minItems"] == 1
    assert schema["properties"]["omitted_capability_shapes"]["items"] == {
        "$ref": "#/$defs/capability_shape_descriptor"
    }
    assert set(schema["$defs"]["authority_ceiling"]["enum"]) == {
        "authoritative",
        "frontier_review_required",
        "support_only",
        "read_only",
    }
    assert "worker" in set(schema["$defs"]["profile"]["enum"])
    assert "openrouter" in set(schema["$defs"]["profile"]["enum"])
    assert "provider_gateway" in set(schema["$defs"]["profile"]["enum"])
    assert "plan_mode_read_only" in set(schema["$defs"]["approval_posture"]["enum"])
    assert "programmatic_auto_approve_task_scoped" in set(
        schema["$defs"]["approval_posture"]["enum"]
    )
    assert "read_only_sidecar" in set(schema["$defs"]["worker_tier"]["enum"])
    assert "oauth" in set(schema["$defs"]["auth_surface"]["enum"])
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


def test_seed_registry_records_omitted_shapes_as_evidence_only_non_supply() -> None:
    from shared.platform_capability_registry import load_platform_capability_registry

    registry = _json(REGISTRY)
    shapes = {shape["shape_id"]: shape for shape in registry["omitted_capability_shapes"]}
    typed_registry = load_platform_capability_registry()
    typed_shapes = {shape.shape_id: shape for shape in typed_registry.omitted_capability_shapes}

    required_classes = {
        "model_provider",
        "local_compute",
        "publication_bus",
        "money_rail",
        "mcp_connector",
        "orchestrator",
        "subagent",
        "cockpit_command",
        "cctv_runner",
        "self_inline",
    }
    assert required_classes <= {shape["shape_class"] for shape in shapes.values()}
    assert set(typed_shapes) == set(shapes)

    for shape in shapes.values():
        assert shape["demand_eligible"] is False
        assert shape["route_ids"] == []
        assert shape["measurement_plan_refs"]
        assert shape["remediation_refs"]
        assert shape["surface_delta_signal"].startswith("capability_surface_delta:")
        assert shape["observed_at"] or shape["blocked_reasons"]

    publication = shapes["publication_bus.public_event_surface"]
    assert "public_claim_disposition_required" in publication["blocked_reasons"]
    assert any("rdlc" in ref for ref in publication["remediation_refs"])

    antigrav = shapes["antigrav.interactive.full"]
    assert antigrav["shape_state"] == "deprecated"
    assert antigrav["route_ids"] == []
    assert any(ref == "refuse:antigrav-live-route" for ref in antigrav["remediation_refs"])


def test_seed_registry_excises_antigrav_live_route_but_records_deprecated_shape() -> None:
    registry = _json(REGISTRY)
    routes = {route["route_id"]: route for route in registry["routes"]}
    shapes = {shape["shape_id"]: shape for shape in registry["omitted_capability_shapes"]}

    assert "agy.review.direct" in registry["required_route_ids"]
    assert routes["agy.review.direct"]["platform"] == "agy"
    assert routes["agy.review.direct"]["mode"] == "review"
    assert routes["agy.review.direct"]["authority_ceiling"] == "read_only"
    assert "antigrav.interactive.full" not in registry["required_route_ids"]
    assert "antigrav.interactive.full" not in routes
    assert shapes["antigrav.interactive.full"]["shape_state"] == "deprecated"


def test_seed_registry_records_agy_review_route_as_blocked_review_supply() -> None:
    registry = _json(REGISTRY)
    route = {route["route_id"]: route for route in registry["routes"]}["agy.review.direct"]

    assert route["sanctioned_wrapper"] == "scripts/hapax-agy-reviewer"
    assert (REPO_ROOT / route["sanctioned_wrapper"]).is_file()
    assert route["route_state"] == "blocked"
    assert route["blocked_reasons"] == [
        "agy_review_seat_receipt_admission_required",
        "route_specific_quota_receipt_absent",
    ]
    assert route["mutability"] == {
        "vault_docs": False,
        "source": False,
        "runtime": False,
        "public": False,
        "provider_spend": False,
    }
    assert route["tool_access"] == {
        "filesystem": "read_only",
        "shell": "none",
        "browser": False,
        "mcp": [],
    }
    assert route["freshness"]["capability_checked_at"] == "2026-07-05T14:51:11Z"
    assert (
        "route_specific_quota_receipt_absent"
        in route["freshness"]["evidence"]["quota"]["blocked_reasons"]
    )
    assert {variant["variant_id"] for variant in route["descriptor_variants"]} >= {
        "agy@gemini-3.5-flash-low",
        "agy@claude-sonnet-4.6-thinking",
        "agy@gpt-oss-120b-medium",
    }
    variants = {variant["variant_id"]: variant for variant in route["descriptor_variants"]}
    assert variants["agy@gemini-3.5-flash-low"]["blocked_reasons"] == [
        "engine_exact_token_smoke_failed"
    ]
    assert variants["agy@gemini-3.5-flash-medium"]["blocked_reasons"] == [
        "engine_exact_token_smoke_failed"
    ]
    assert variants["agy@gemini-3.5-flash-high"]["blocked_reasons"] == [
        "engine_exact_token_smoke_failed"
    ]


def test_surface_delta_for_omitted_shape_holds_until_measurement() -> None:
    from shared.platform_capability_registry import (
        CapabilitySurfaceDeltaAction,
        disposition_for_capability_surface_delta,
        load_platform_capability_registry,
    )

    registry = load_platform_capability_registry()
    disposition = disposition_for_capability_surface_delta(
        registry,
        _surface_delta("publication_bus.public_event_surface.omg_weblog"),
    )

    assert disposition.action is CapabilitySurfaceDeltaAction.KNOWN_HOLD_FOR_MEASUREMENT
    assert disposition.demand_eligible is False
    assert disposition.descriptor_id == "publication_bus.public_event_surface"
    assert "evidence_only_not_dispatch_supply" in disposition.reason_codes


def test_canonical_fixture_surface_delta_holds_registered_omitted_shape() -> None:
    from shared.platform_capability_registry import (
        CapabilitySurfaceDeltaAction,
        disposition_for_capability_surface_delta,
        load_platform_capability_registry,
    )

    registry = load_platform_capability_registry()
    fixtures = load_capability_surface_delta_fixtures()
    delta = next(
        delta for delta in fixtures.deltas if delta.surface_id == "surface.publication_bus.weblog"
    )

    disposition = disposition_for_capability_surface_delta(registry, delta)

    assert disposition.action is CapabilitySurfaceDeltaAction.KNOWN_HOLD_FOR_MEASUREMENT
    assert disposition.demand_eligible is False
    assert disposition.descriptor_id == "publication_bus.public_event_surface"
    assert "known_omitted_capability_shape" in disposition.reason_codes


def test_same_carrier_unknown_surface_delta_mints_intake_not_hold() -> None:
    from shared.platform_capability_registry import (
        CapabilitySurfaceDeltaAction,
        disposition_for_capability_surface_delta,
        load_platform_capability_registry,
    )

    registry = load_platform_capability_registry()
    disposition = disposition_for_capability_surface_delta(
        registry,
        _surface_delta("openrouter.unregistered_new_surface"),
    )

    assert disposition.action is CapabilitySurfaceDeltaAction.MINT_INTAKE
    assert disposition.descriptor_id is None


def test_unknown_surface_delta_mints_intake_not_supply() -> None:
    from shared.platform_capability_registry import (
        CapabilitySurfaceDeltaAction,
        disposition_for_capability_surface_delta,
        load_platform_capability_registry,
    )

    registry = load_platform_capability_registry()
    disposition = disposition_for_capability_surface_delta(
        registry,
        _surface_delta("new_provider.experimental_leaf"),
    )

    assert disposition.action is CapabilitySurfaceDeltaAction.MINT_INTAKE
    assert disposition.demand_eligible is False
    assert disposition.descriptor_id is None
    assert "capability_surface_delta_unknown_shape" in disposition.reason_codes


def test_deprecated_surface_delta_refuses_live_supply() -> None:
    from shared.platform_capability_registry import (
        CapabilitySurfaceDeltaAction,
        disposition_for_capability_surface_delta,
        load_platform_capability_registry,
    )

    registry = load_platform_capability_registry()
    disposition = disposition_for_capability_surface_delta(
        registry,
        _surface_delta("antigrav.interactive.full"),
    )

    assert disposition.action is CapabilitySurfaceDeltaAction.DEPRECATED_REFUSE
    assert disposition.demand_eligible is False
    assert disposition.descriptor_id == "antigrav.interactive.full"
    assert "capability_shape_deprecated" in disposition.reason_codes


def test_surface_delta_disposition_consumes_canonical_sdlc_signal() -> None:
    from shared.platform_capability_registry import disposition_for_capability_surface_delta

    hints = get_type_hints(disposition_for_capability_surface_delta)

    assert hints["delta"] is CapabilitySurfaceDelta


def test_omitted_shape_cannot_be_marked_demand_eligible() -> None:
    from shared.platform_capability_registry import CapabilityShapeDescriptor

    shape = _json(REGISTRY)["omitted_capability_shapes"][0]
    poisoned = {**shape, "demand_eligible": True}

    with pytest.raises(ValidationError, match="cannot be demand_eligible"):
        CapabilityShapeDescriptor.model_validate(poisoned)


def test_omitted_shape_cannot_carry_route_ids() -> None:
    from shared.platform_capability_registry import CapabilityShapeDescriptor

    shape = _json(REGISTRY)["omitted_capability_shapes"][0]
    poisoned = {**shape, "route_ids": ["codex.headless.full"]}

    with pytest.raises(ValidationError, match="cannot carry route_ids"):
        CapabilityShapeDescriptor.model_validate(poisoned)


def test_deprecated_omitted_shape_requires_retired_blocker() -> None:
    from shared.platform_capability_registry import CapabilityShapeDescriptor

    shape = next(
        shape
        for shape in _json(REGISTRY)["omitted_capability_shapes"]
        if shape["shape_id"] == "antigrav.interactive.full"
    )
    poisoned = {**shape, "blocked_reasons": ["measured_supply_leaf_absent"]}

    with pytest.raises(ValidationError, match="deprecated/retired blocker"):
        CapabilityShapeDescriptor.model_validate(poisoned)


def test_unobserved_omitted_shape_requires_blocker() -> None:
    from shared.platform_capability_registry import CapabilityShapeDescriptor

    shape = _json(REGISTRY)["omitted_capability_shapes"][0]
    poisoned = {**shape, "observed_at": None, "blocked_reasons": []}

    with pytest.raises(ValidationError, match="unobserved capability shapes require"):
        CapabilityShapeDescriptor.model_validate(poisoned)


def test_observed_omitted_shape_requires_evidence_refs() -> None:
    from shared.platform_capability_registry import CapabilityShapeDescriptor

    shape = _json(REGISTRY)["omitted_capability_shapes"][0]
    poisoned = {**shape, "evidence_refs": []}

    with pytest.raises(ValidationError, match="observed capability shapes require"):
        CapabilityShapeDescriptor.model_validate(poisoned)


def test_runtime_registry_requires_omitted_shapes() -> None:
    from shared.platform_capability_registry import PlatformCapabilityRegistry

    payload = _json(REGISTRY)
    del payload["omitted_capability_shapes"]

    with pytest.raises(ValidationError, match="Field required"):
        PlatformCapabilityRegistry.model_validate(payload)


def test_runtime_registry_rejects_extra_route_rows_not_declared() -> None:
    from shared.platform_capability_registry import PlatformCapabilityRegistry

    payload = _json(REGISTRY)
    extra_route = {**payload["routes"][0], "route_id": "api.headless.full", "profile": "full"}
    payload["routes"] = [*payload["routes"], extra_route]

    with pytest.raises(ValidationError, match="not declared in required_route_ids"):
        PlatformCapabilityRegistry.model_validate(payload)


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
