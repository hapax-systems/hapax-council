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

from shared.platform_capability_receipts import (
    CliEvidence,
    EvidenceStatus,
    PlatformCapabilityReceipt,
    ProviderDocsEvidence,
    SurfaceEvidence,
    WrapperEvidence,
)
from shared.platform_capability_registry import (
    REQUIRED_ROUTE_IDS,
    AuthorityCeiling,
    PlatformCapabilityRegistry,
    PlatformCapabilityRoute,
    RouteState,
    _apply_receipt_to_route_payload,
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
        "claude",
        "codex",
        "vibe",
    }
    assert "antigrav" not in {route.platform.value for route in registry.routes}
    assert all(not route_id.startswith("gemini.") for route_id in registry.route_map())


def test_registry_route_ids_match_dispatcher_platform_paths() -> None:
    registry = load_platform_capability_registry()
    dispatcher = _dispatcher_module()
    dispatcher_routes = {
        f"{route.platform}.{route.mode}.{route.profile}"
        for route in dispatcher.PLATFORM_PATHS.values()
    }

    # Review-seat routes (mode=review, e.g. glmcp.review.direct) are non-launchable
    # capability rows — admitted/observed but never spawned through a PLATFORM_PATHS
    # launcher — so they are registry-only, not dispatcher launchers.
    launchable_routes = {
        route_id for route_id, route in registry.route_map().items() if route.mode != "review"
    }
    assert launchable_routes == dispatcher_routes


def test_glmcp_review_seat_registered_as_fail_closed_read_only_route() -> None:
    # The GLM Coding-Plan review seat (live in cc-pr-review-dispatch) is now visible
    # in DESCRIBE as a non-launchable, read-only ReviewSeatAdapter route. The coding
    # workhorse is a separate, bakeoff-gated route — NOT this one.
    from shared.dispatcher_policy import ROUTE_SPECIFIC_SUBSCRIPTION_QUOTA_REQUIRED
    from shared.quota_spend_ledger import RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES

    assert "glmcp.review.direct" in REQUIRED_ROUTE_IDS
    route = load_platform_capability_registry().require("glmcp.review.direct")
    assert (route.platform.value, route.mode.value, route.profile.value) == (
        "glmcp",
        "review",
        "direct",
    )
    assert route.authority_ceiling == AuthorityCeiling.READ_ONLY
    assert route.worker_tier.value == "read_only_sidecar"
    assert route.route_state == RouteState.BLOCKED  # receipt-bounded admission, fail-closed
    assert not route.mutability.any_mutation()
    # the receipt-bounded subscription-quota machinery already keys this route id
    assert "glmcp.review.direct" in ROUTE_SPECIFIC_SUBSCRIPTION_QUOTA_REQUIRED
    assert "glmcp.review.direct" in RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES


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
    route = registry.require("codex.headless.full")
    payload = route.model_dump(mode="json")
    payload["route_id"] = "local_tool.local.deterministic"
    payload["platform"] = "local_tool"
    payload["mode"] = "local"
    payload["profile"] = "deterministic"
    payload["authority_ceiling"] = AuthorityCeiling.READ_ONLY.value
    payload["approval_posture"] = "plan_mode_read_only"
    payload["worker_tier"] = "read_only_sidecar"
    payload["mutability"] = {
        "vault_docs": False,
        "source": False,
        "runtime": False,
        "public": False,
        "provider_spend": False,
    }
    payload["tool_access"] = {
        "filesystem": "read_only",
        "shell": "read_only",
        "browser": False,
        "mcp": [],
    }
    PlatformCapabilityRoute.model_validate(payload)
    payload["mutability"]["source"] = True
    with pytest.raises(ValidationError, match="read-only routes cannot declare mutation"):
        PlatformCapabilityRoute.model_validate(payload)


def test_gemini_routes_are_not_seeded_as_dispatchable_platform_paths() -> None:
    registry = load_platform_capability_registry()

    assert all(not route_id.startswith("gemini.") for route_id in registry.route_map())
    with pytest.raises(KeyError):
        registry.require("gemini.headless.full")


def test_cloud_burst_api_route_is_blocked_dry_run_paid_surface() -> None:
    registry = load_platform_capability_registry()
    route = registry.require("api.headless.api_frontier")

    assert route.route_state is RouteState.BLOCKED
    assert route.capacity_pool.value == "api_paid_spend"
    assert route.auth_surface.value == "api_key"
    assert route.mutability.source is True
    assert "provider_budget_receipt_absent" in route.blocked_reasons
    assert "cloud_burst_release_gate_absent" in route.blocked_reasons


def test_openrouter_frontier_route_is_blocked_until_measurement_budget_and_key() -> None:
    registry = load_platform_capability_registry()
    route = registry.require("api.headless.openrouter")

    assert route.route_state is RouteState.BLOCKED
    assert route.model_or_engine == "openrouter/openai/gpt-5.5"
    assert route.execution_descriptor.model_id.value == "gpt-5.5"
    assert route.paid_provider == "openrouter"
    assert route.paid_profile == "frontier-gpt-5.5"
    assert route.authority_ceiling is AuthorityCeiling.FRONTIER_REVIEW_REQUIRED
    assert route.capacity_pool.value == "api_paid_spend"
    assert route.mutability.source is True
    assert route.mutability.provider_spend is False
    assert route.privacy_posture.value == "provider_training_unknown"
    assert route.capability_tier.value == "frontier_full"
    assert route.worker_tier.value == "fallback_worker"
    assert route.capability_scores.source_editing.observed_at is None
    assert route.capability_scores.source_editing.confidence == 2
    assert route.capability_scores.local_calibration.score == 1
    assert route.tool_access.filesystem.value == "read_write"
    assert route.tool_access.shell.value == "full"
    assert "capabilityio_measurement_absent" in route.blocked_reasons
    assert "capability_scores_asserted_not_measured" in route.blocked_reasons
    assert "openrouter_paid_budget_receipt_absent" in route.blocked_reasons
    assert "openrouter_served_model_witness_absent" in route.blocked_reasons


def test_provider_gateway_route_is_explicit_fail_closed_paid_runtime_surface() -> None:
    registry = load_platform_capability_registry()
    route = registry.require("api.headless.provider_gateway")

    assert route.route_state is RouteState.BLOCKED
    assert route.capacity_pool.value == "api_paid_spend"
    assert route.paid_provider == "google"
    assert route.paid_profile == "frontier-fast"
    assert route.mutability.source is False
    assert route.mutability.runtime is True
    assert route.mutability.provider_spend is True
    assert route.tool_access.filesystem.value == "read_write"
    assert route.tool_access.shell.value == "full"
    assert "provider_gateway_evidence_absent" in route.blocked_reasons
    assert "provider_budget_receipt_absent" in route.blocked_reasons

    ordinary_routes = [
        candidate
        for candidate in registry.routes
        if candidate.route_id != "api.headless.provider_gateway"
    ]
    assert all(candidate.mutability.provider_spend is False for candidate in ordinary_routes)


def test_provider_spend_mutability_requires_paid_capacity_pool() -> None:
    registry = load_platform_capability_registry()
    codex = registry.require("codex.headless.full")

    payload = codex.model_dump(mode="json")
    payload["mutability"]["provider_spend"] = True
    with pytest.raises(ValidationError, match="provider-spend mutation requires"):
        PlatformCapabilityRoute.model_validate(payload)


def test_risky_auto_approval_routes_cannot_be_unrestricted_authoritative() -> None:
    registry = load_platform_capability_registry()
    vibe = registry.require("vibe.headless.full")

    assert vibe.approval_posture.value == "programmatic_auto_approve_task_scoped"
    assert vibe.worker_tier.value == "bounded_worker"

    payload = vibe.model_dump(mode="json")
    payload["authority_ceiling"] = "authoritative"
    with pytest.raises(ValidationError, match="auto-approval posture cannot"):
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
    assert supply.route.approval_posture.value == "no_ask_hooks_enforced"
    assert supply.route.worker_tier.value == "full_worker"
    assert supply.route.sanctioned_wrapper == "scripts/hapax-codex"
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


def _make_receipt(*, observed_at: datetime, stale_after: str = "24h") -> PlatformCapabilityReceipt:
    return PlatformCapabilityReceipt(
        receipt_id="test-receipt",
        platform="claude",
        routes=["claude.headless.full"],
        observed_at=observed_at,
        stale_after=stale_after,
        cli=CliEvidence(binary="claude", available=True, version="2.1.0"),
        wrapper=WrapperEvidence(path="/dev/null", exists=True, executable=True, sha256="abc123"),
        capability=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=["test:cap"],
        ),
        resource=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=["test:res"],
        ),
        quota=SurfaceEvidence(
            status=EvidenceStatus.UNOBSERVABLE,
            source="test",
            observed_at=observed_at,
            stale_after="15m",
            evidence_refs=["test:quota"],
            reason_codes=["account_live_quota_receipt_absent"],
        ),
        provider_docs=ProviderDocsEvidence(
            refs=["test:docs"],
            fetched_at=observed_at,
            stale_after="168h",
        ),
    )


def _make_api_receipt(
    *, observed_at: datetime, stale_after: str = "24h"
) -> PlatformCapabilityReceipt:
    return PlatformCapabilityReceipt(
        receipt_id="test-api-receipt",
        platform="api",
        routes=[
            "api.headless.api_frontier",
            "api.headless.openrouter",
            "api.headless.provider_gateway",
        ],
        observed_at=observed_at,
        stale_after=stale_after,
        cli=CliEvidence(binary="python3", available=True, version="Python 3.12.3"),
        wrapper=WrapperEvidence(
            path="scripts/hapax-methodology-dispatch",
            exists=True,
            executable=True,
            sha256="abc123",
        ),
        capability=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=["test:api:cap"],
        ),
        resource=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="5m",
            evidence_refs=["test:api:res"],
        ),
        quota=SurfaceEvidence(
            status=EvidenceStatus.UNOBSERVABLE,
            source="test",
            observed_at=observed_at,
            stale_after="15m",
            evidence_refs=["test:api:quota"],
            reason_codes=["account_live_quota_receipt_absent"],
        ),
        provider_docs=ProviderDocsEvidence(
            refs=["test:api:docs"],
            fetched_at=observed_at,
            stale_after="30d",
        ),
    )


def test_subscription_quota_nonblocking_uses_receipt_stale_after() -> None:
    """Regression: unobservable subscription quota must not go stale at 15m."""
    payload = _payload()
    route = _route_payload(payload, "claude.headless.full")
    assert route["capacity_pool"] == "subscription_quota"
    _mark_fresh(route)

    receipt_time = datetime(2026, 5, 9, 20, 0, tzinfo=UTC)
    receipt = _make_receipt(observed_at=receipt_time, stale_after="24h")
    _apply_receipt_to_route_payload(route, receipt)

    assert route["freshness"]["quota_stale_after"] == "24h"
    assert route["route_state"] == "active"
    assert "account_live_quota_receipt_absent" not in route.get("blocked_reasons", [])

    check_at = datetime(2026, 5, 9, 21, 0, tzinfo=UTC)
    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(registry, route_ids=["claude.headless.full"], now=check_at)

    quota_errors = [e for e in result.routes[0].errors if "quota" in e]
    assert not quota_errors, f"quota should not be stale after 1h: {quota_errors}"


def test_provider_gateway_receipt_clears_gateway_evidence_blockers() -> None:
    payload = _payload()
    route = _route_payload(payload, "api.headless.provider_gateway")

    receipt_time = datetime(2026, 6, 4, 16, 0, tzinfo=UTC)
    _apply_receipt_to_route_payload(route, _make_api_receipt(observed_at=receipt_time))

    assert route["route_state"] == "active"
    assert "provider_gateway_evidence_absent" not in route["blocked_reasons"]
    assert "provider_budget_receipt_absent" not in route["blocked_reasons"]
    assert (
        "gateway_resource_receipt_absent"
        not in route["freshness"]["evidence"]["resource"]["blocked_reasons"]
    )
    assert route["freshness"]["quota_stale_after"] == "24h"
    assert route["capability_scores"]["source_editing"]["observed_at"] == "2026-06-04T16:00:00Z"
    assert any(
        ref.startswith("platform-capability-receipt:api:")
        for ref in route["capability_scores"]["source_editing"]["evidence_refs"]
    )

    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(
        registry,
        route_ids=["api.headless.provider_gateway"],
        now=datetime(2026, 6, 4, 16, 1, tzinfo=UTC),
    )

    assert result.ok is True


def test_api_receipt_does_not_open_cloud_burst_release_gate() -> None:
    payload = _payload()
    route = _route_payload(payload, "api.headless.api_frontier")

    receipt_time = datetime(2026, 6, 4, 16, 0, tzinfo=UTC)
    _apply_receipt_to_route_payload(route, _make_api_receipt(observed_at=receipt_time))

    assert route["route_state"] == "blocked"
    assert "cloud_burst_release_gate_absent" in route["blocked_reasons"]
    assert "no_secret_egress_receipt_absent" in route["blocked_reasons"]
    assert (
        "cloud_runner_resource_receipt_absent"
        in route["freshness"]["evidence"]["resource"]["blocked_reasons"]
    )


def test_api_receipt_does_not_admit_openrouter_without_measurement_budget_or_key() -> None:
    payload = _payload()
    route = _route_payload(payload, "api.headless.openrouter")

    receipt_time = datetime(2026, 7, 5, 16, 0, tzinfo=UTC)
    receipt = _make_api_receipt(observed_at=receipt_time)
    _apply_receipt_to_route_payload(route, receipt)

    assert route["route_state"] == "blocked"
    assert "capabilityio_measurement_absent" in route["blocked_reasons"]
    assert "openrouter_key_secret_receipt_absent" in route["blocked_reasons"]
    assert "openrouter_paid_budget_receipt_absent" in route["blocked_reasons"]
    assert "openrouter_served_model_witness_absent" in route["blocked_reasons"]
    assert (
        "capabilityio_measurement_absent"
        in route["freshness"]["evidence"]["capability"]["blocked_reasons"]
    )
    assert (
        "openrouter_key_secret_receipt_absent"
        in route["freshness"]["evidence"]["resource"]["blocked_reasons"]
    )
    assert route["capability_scores"]["source_editing"]["observed_at"] is None
    assert route["capability_scores"]["local_calibration"]["observed_at"] is None
    assert not any(
        ref.startswith("platform-capability-receipt:api:")
        for ref in route["capability_scores"]["source_editing"]["evidence_refs"]
    )

    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(
        registry,
        route_ids=["api.headless.openrouter"],
        now=datetime(2026, 7, 5, 16, 1, tzinfo=UTC),
    )

    assert result.ok is False
    assert any("blocked:" in error for error in result.routes[0].errors)


# --------------------------------------------------------------------------------------
# SupplyDescriptor — the execution-axis supply the dispatcher scores satisfiability against
# --------------------------------------------------------------------------------------
def test_supply_vector_carries_supply_descriptor_with_reachable_variants() -> None:
    """build_supply_vector exposes the route's reachable execution axes: base + every non-blocked
    variant, with maps pointing each reachable value at the providing variant (None = base)."""
    registry = load_platform_capability_registry()
    descriptor = build_supply_vector(registry.require("claude.headless.opus")).supply_descriptor
    assert descriptor is not None
    assert descriptor.base_context_mode == "standard"
    assert "extended_1m" in descriptor.reachable_context_modes
    assert descriptor.context_mode_to_variant["extended_1m"] == "opus@extended_1m"
    assert descriptor.context_mode_to_variant["standard"] is None  # base provides standard


def test_supply_descriptor_excludes_blocked_variants_fail_closed() -> None:
    """A descriptor variant carrying blocked_reasons cannot make its route reachable for the
    blocked axis nor be resolved as a leaf — fail-closed."""
    registry = load_platform_capability_registry()
    payload = registry.require("claude.headless.opus").model_dump(mode="json")
    for variant in payload["descriptor_variants"]:
        if variant["variant_id"] == "opus@extended_1m":
            variant["blocked_reasons"] = ["entitlement_absent"]
    route = PlatformCapabilityRoute.model_validate(payload)
    descriptor = build_supply_vector(route).supply_descriptor
    assert descriptor is not None
    assert "extended_1m" not in descriptor.reachable_context_modes
    assert "extended_1m" not in descriptor.context_mode_to_variant


# --------------------------------------------------------------------------------------
# haiku + local_tool routes (capability-haiku-localtool-routes slice) — closing the
# enum-without-route holes: claude-haiku-4-5 routable, Platform.LOCAL_TOOL/Mode.LOCAL materialized.
# --------------------------------------------------------------------------------------
def test_haiku_and_local_tool_routes_are_required_and_routable() -> None:
    from shared.platform_capability_registry import (
        Mode,
        ModelId,
        Platform,
        materialize_descriptor_leaves,
    )

    registry = load_platform_capability_registry()
    assert {"claude.headless.haiku", "local_tool.local.worker"} <= REQUIRED_ROUTE_IDS
    assert {"claude.headless.haiku", "local_tool.local.worker"} <= set(registry.route_map())

    haiku = registry.require("claude.headless.haiku")
    assert (
        haiku.execution_descriptor.model_id is ModelId.CLAUDE_HAIKU_4_5
    )  # claude-haiku now routable
    assert haiku.route_state is RouteState.BLOCKED  # materialized but honestly not yet live

    local = registry.require("local_tool.local.worker")
    assert (
        local.platform is Platform.LOCAL_TOOL
    )  # the verified-unused enum members now have a route
    assert local.mode is Mode.LOCAL
    assert local.execution_descriptor.model_id is ModelId.COMMAND_R_08_2024
    assert local.execution_descriptor.quantization.value == "exl3_4_0bpw"

    # the podium 5.0bpw tier is a materialized descriptor leaf
    leaves = materialize_descriptor_leaves(registry)
    variant_leaf = leaves["local_tool.local.worker#worker@quantization_exl3_5_0bpw"]
    assert variant_leaf.quantization.value == "exl3_5_0bpw"
