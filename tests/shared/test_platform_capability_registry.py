"""Tests for the platform capability registry freshness gate."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from shared.platform_capability_registry import (
    REQUIRED_ROUTE_IDS,
    AuthorityCeiling,
    PlatformCapabilityRegistry,
    PlatformCapabilityRoute,
    RouteState,
    build_supply_vector,
    check_registry_freshness,
    load_platform_capability_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"
FRESH_NOW = datetime(2026, 5, 9, 21, 0, tzinfo=UTC)
ROUTE_EVIDENCE_NOW = datetime(2026, 5, 17, 8, 14, tzinfo=UTC)


def _dispatcher_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_methodology_dispatch", str(DISPATCHER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _payload() -> dict:
    return load_platform_capability_registry().model_dump(mode="json")


def _route_payload(payload: dict, route_id: str) -> dict:
    return next(route for route in payload["routes"] if route["route_id"] == route_id)


def _mark_fresh(route: dict) -> None:
    route["route_state"] = RouteState.ACTIVE.value
    route["blocked_reasons"] = []
    route["freshness"]["capability_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["quota_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["resource_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["provider_docs_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["evidence"] = {
        "capability": {
            "evidence_refs": ["test:fresh-capability"],
            "blocked_reasons": [],
        },
        "quota": {
            "evidence_refs": ["test:fresh-quota"],
            "blocked_reasons": [],
        },
        "resource": {
            "evidence_refs": ["test:fresh-resource"],
            "blocked_reasons": [],
        },
        "provider_docs": {
            "evidence_refs": ["test:fresh-provider-docs"],
            "blocked_reasons": [],
        },
    }
    for score in route["capability_scores"].values():
        score["observed_at"] = "2026-05-09T20:55:00Z"
    for tool in route["tool_state"]:
        tool["observed_at"] = "2026-05-09T20:55:00Z"


def test_seed_registry_loads_sanctioned_platform_routes() -> None:
    registry = load_platform_capability_registry()

    assert set(registry.route_map()) == REQUIRED_ROUTE_IDS
    assert {route.platform.value for route in registry.routes} >= {
        "antigrav",
        "claude",
        "codex",
        "gemini",
        "vibe",
    }


def test_registry_route_ids_match_dispatcher_platform_paths() -> None:
    registry = load_platform_capability_registry()
    dispatcher = _dispatcher_module()
    dispatcher_routes = {
        f"{route.platform}.{route.mode}.{route.profile}"
        for route in dispatcher.PLATFORM_PATHS.values()
    }

    assert set(registry.route_map()) == dispatcher_routes


def test_seed_registry_uses_explicit_surface_blockers_and_fails_closed() -> None:
    registry = load_platform_capability_registry()

    assert any(route.freshness.capability_checked_at is None for route in registry.routes)
    result = check_registry_freshness(
        registry,
        route_ids=["codex.headless.full"],
        now=ROUTE_EVIDENCE_NOW,
    )

    assert result.ok is False
    errors = "\n".join(result.routes[0].errors)
    assert "blocked:" in errors
    assert "quota blocked: account_live_quota_receipt_absent" in errors
    assert "freshness is unknown" not in errors
    assert "account_live_quota_receipt_absent" in result.routes[0].blocked_reasons
    assert result.routes[0].evidence_refs


def test_fresh_row_passes_when_evidence_is_present() -> None:
    payload = _payload()
    route = _route_payload(payload, "codex.headless.full")
    _mark_fresh(route)

    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(registry, route_ids=["codex/headless/full"], now=FRESH_NOW)

    assert result.ok is True
    assert result.routes[0].errors == ()


def test_claude_headless_full_route_is_blocked_with_exact_reasons() -> None:
    registry = load_platform_capability_registry()

    result = check_registry_freshness(
        registry,
        route_ids=["claude.headless.full"],
        now=ROUTE_EVIDENCE_NOW,
    )

    assert result.ok is False
    route = registry.require("claude.headless.full")
    assert route.route_state is RouteState.BLOCKED
    assert "account_live_quota_receipt_absent" in route.blocked_reasons
    assert "freshness is unknown" not in "\n".join(result.routes[0].errors)


def test_stale_capability_quota_and_resource_state_fail_closed() -> None:
    payload = _payload()
    route = _route_payload(payload, "codex.headless.full")
    _mark_fresh(route)
    route["freshness"]["capability_checked_at"] = "2026-05-01T00:00:00Z"
    route["freshness"]["quota_checked_at"] = "2026-05-01T00:00:00Z"
    route["freshness"]["resource_checked_at"] = "2026-05-01T00:00:00Z"

    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(registry, route_ids=["codex/headless/full"], now=FRESH_NOW)

    assert result.ok is False
    errors = "\n".join(result.routes[0].errors)
    assert "capability stale" in errors
    assert "quota stale" in errors
    assert "resource stale" in errors


def test_unsupported_routes_fail_closed() -> None:
    registry = load_platform_capability_registry()

    result = check_registry_freshness(registry, route_ids=["codex.headless.unknown"], now=FRESH_NOW)

    assert result.ok is False
    assert result.routes[0].supported is False
    assert result.routes[0].errors == ("unsupported route: codex.headless.unknown",)


def test_read_only_routes_cannot_declare_mutation_access() -> None:
    registry = load_platform_capability_registry()
    gemini = registry.require("gemini/headless/full")

    assert gemini.authority_ceiling is AuthorityCeiling.READ_ONLY
    assert gemini.mutability.source is False
    assert gemini.tool_access.filesystem.value == "read_only"

    payload = gemini.model_dump(mode="json")
    payload["mutability"]["source"] = True
    with pytest.raises(ValidationError, match="read-only routes cannot declare mutation"):
        PlatformCapabilityRoute.model_validate(payload)


def test_unknown_privacy_posture_is_visible_and_non_permissive() -> None:
    payload = _payload()
    route = _route_payload(payload, "vibe.headless.full")
    _mark_fresh(route)
    route["privacy_posture"] = "unknown"

    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(registry, route_ids=["vibe.headless.full"], now=FRESH_NOW)

    assert result.ok is False
    assert result.routes[0].errors == ("vibe.headless.full: privacy posture is unknown",)


def test_provider_doc_expiry_blocks_route() -> None:
    payload = _payload()
    route = _route_payload(payload, "claude.headless.opus")
    _mark_fresh(route)
    route["freshness"]["provider_docs_checked_at"] = "2026-03-01T00:00:00Z"

    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(registry, route_ids=["claude.headless.opus"], now=FRESH_NOW)

    assert result.ok is False
    assert result.routes[0].errors
    assert "provider_docs stale" in result.routes[0].errors[0]


def test_null_freshness_without_surface_blocker_is_invalid() -> None:
    payload = _payload()
    route = _route_payload(payload, "codex.headless.full")
    route["freshness"]["capability_checked_at"] = None
    route["freshness"]["evidence"]["capability"] = {
        "evidence_refs": [],
        "blocked_reasons": [],
    }

    with pytest.raises(ValidationError, match="freshness surface requires"):
        PlatformCapabilityRegistry.model_validate(payload)


def test_active_route_cannot_carry_surface_blocker() -> None:
    payload = _payload()
    route = _route_payload(payload, "codex.headless.full")
    _mark_fresh(route)
    route["freshness"]["evidence"]["quota"]["blocked_reasons"] = ["quota_blocker"]

    with pytest.raises(ValidationError, match="active routes cannot carry freshness"):
        PlatformCapabilityRegistry.model_validate(payload)


def test_supply_vector_projects_dimensional_scores_and_tool_state() -> None:
    registry = load_platform_capability_registry()
    route = registry.require("codex.headless.full")

    supply = build_supply_vector(route, lane_id="cx-green", now=FRESH_NOW)

    assert supply.supply_vector_schema == 1
    assert supply.route.route_id == "codex.headless.full"
    assert supply.route.lane_id == "cx-green"
    assert supply.capability_scores.source_editing.score == 5
    assert any(tool.tool_id == "local_shell" for tool in supply.tool_state)
    assert "source" in supply.authority.supported_mutation_surfaces


def test_stale_capability_score_field_fails_closed() -> None:
    payload = _payload()
    route = _route_payload(payload, "codex.headless.full")
    _mark_fresh(route)
    route["capability_scores"]["source_editing"]["observed_at"] = "2026-05-01T00:00:00Z"

    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(registry, route_ids=["codex.headless.full"], now=FRESH_NOW)

    assert result.ok is False
    assert any(
        "capability_scores.source_editing stale" in error for error in result.routes[0].errors
    )
