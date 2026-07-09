"""Tests for the platform capability registry freshness gate."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from copy import deepcopy
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
    _quota_receipt_removable_reasons,
    _route_specific_quota_admission_fresh,
    build_supply_vector,
    check_registry_freshness,
    load_platform_capability_registry,
)
from shared.quota_spend_ledger import QUOTA_SPEND_LEDGER_FIXTURES

REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"
FRESH_NOW = datetime(2026, 5, 9, 21, 0, tzinfo=UTC)
ROUTE_EVIDENCE_NOW = datetime(2026, 5, 17, 8, 14, tzinfo=UTC)
GLMCP_PAYG_ADMISSION_EVIDENCE_REF = (
    "relay-receipt:glmcp-quota-admission-payg.yaml:"
    "witness:glmcp-payg-spend-20260517t075900z-test.yaml:"
    "supported_tool:hapax-glmcp-reviewer:"
    "endpoint:https://api.z.ai/api/paas/v4:"
    "model:glm-5.2:"
    "primary_error_class:quota_exhausted:"
    "quota_wall_evidence_ref:cx-glmcp-quota-wall.yaml:"
    "observed_at:2026-05-17T07:59:00Z:"
    "fresh_until:2026-05-17T08:05:00Z"
)
GLMCP_PAYG_BUDGET_ID = "tb-20260517-zai-glmcp-payg-review"
AGY_ADMISSION_EVIDENCE_REF = (
    "relay-receipt:agy-quota-admission.yaml:"
    "witness:agy-gemini31pro-smoke-witness:"
    "supported_tool:hapax-agy-reviewer:"
    "model:gemini-3.1-pro-preview:"
    "observed_at:2026-05-17T07:59:00Z:"
    "fresh_until:2026-05-17T08:05:00Z"
)


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
        "agy",
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


def test_review_seats_registered_as_fail_closed_read_only_routes() -> None:
    # Review seats (live in cc-pr-review-dispatch) are visible in DESCRIBE as
    # non-launchable, read-only ReviewSeatAdapter routes. Coding workhorses are
    # separate, promotion-gated routes — not these review seats.
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
    assert "agy.review.direct" in ROUTE_SPECIFIC_SUBSCRIPTION_QUOTA_REQUIRED
    assert "agy.review.direct" in RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES
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

    agy = registry.require("agy.review.direct")
    assert agy.platform.value == "agy"
    assert agy.authority_ceiling.value == "read_only"
    assert agy.route_state is RouteState.BLOCKED
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
    expected_scores = {
        "grounding": 4,
        "governance_reasoning": 4,
        "source_editing": 4,
        "architecture": 4,
        "ambiguity_resolution": 4,
        "long_context": 5,
        "current_docs_grounding": 4,
        "multimodal_verification": 2,
        "runtime_debugging": 3,
        "test_authoring": 4,
        "coordination_reliability": 2,
        "privacy_safety": 2,
        "public_claim_safety": 3,
        "local_calibration": 1,
    }
    score_payload = route.capability_scores.model_dump(mode="json")
    assert {name: score_payload[name]["score"] for name in expected_scores} == expected_scores
    assert all(score_payload[name]["confidence"] == 2 for name in expected_scores)
    assert route.tool_access.filesystem.value == "read_write"
    assert route.tool_access.shell.value == "full"
    assert "capabilityio_measurement_absent" in route.blocked_reasons
    assert "capability_scores_asserted_not_measured" in route.blocked_reasons
    assert "openrouter_key_credit_witness_absent" in route.blocked_reasons
    assert "capabilityio_adapter_wiring_absent" in route.blocked_reasons
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


def test_vibe_route_uses_explicit_bounded_exclusions_without_quality_equivalence() -> None:
    registry = load_platform_capability_registry()
    vibe = registry.require("vibe.headless.full")

    assert vibe.worker_tier.value == "bounded_worker"
    assert [floor.value for floor in vibe.quality_envelope.eligible_quality_floors] == [
        "deterministic_ok"
    ]
    assert vibe.quality_envelope.explicit_equivalence_records == []
    assert "frontier_review_required_without_equivalence_record" in (
        vibe.quality_envelope.excluded_task_classes
    )
    assert "quality_equivalence_record_absent" not in vibe.blocked_reasons
    assert "quality_equivalence_record_absent" not in (
        vibe.freshness.evidence.capability.blocked_reasons
    )
    assert "fresh_capability_evidence_absent" in vibe.blocked_reasons


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


def _make_vibe_receipt(
    *, observed_at: datetime, stale_after: str = "24h"
) -> PlatformCapabilityReceipt:
    return PlatformCapabilityReceipt(
        receipt_id="test-vibe-receipt",
        platform="vibe",
        routes=["vibe.headless.full"],
        observed_at=observed_at,
        stale_after=stale_after,
        cli=CliEvidence(binary="vibe", available=True, version="0.0-test"),
        wrapper=WrapperEvidence(path="scripts/hapax-vibe", exists=True, executable=True),
        capability=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=["test:vibe:cap"],
        ),
        resource=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=["test:vibe:res"],
        ),
        quota=SurfaceEvidence(
            status=EvidenceStatus.UNOBSERVABLE,
            source="test",
            observed_at=observed_at,
            stale_after="15m",
            evidence_refs=["test:vibe:quota"],
            reason_codes=["account_live_quota_receipt_absent"],
        ),
        provider_docs=ProviderDocsEvidence(
            refs=["test:vibe:docs"],
            fetched_at=observed_at,
            stale_after="30d",
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


def _make_agy_receipt(
    *,
    observed_at: datetime,
    quota_status: EvidenceStatus = EvidenceStatus.UNOBSERVABLE,
    quota_refs: list[str] | None = None,
    quota_reason_codes: list[str] | None = None,
) -> PlatformCapabilityReceipt:
    if quota_status is EvidenceStatus.OBSERVED:
        quota_refs = quota_refs or ["test:agy:route-specific-quota"]
        quota_reason_codes = quota_reason_codes or []
    else:
        quota_refs = quota_refs or ["test:agy:quota-unobservable"]
        quota_reason_codes = quota_reason_codes or ["account_live_quota_receipt_absent"]
    return PlatformCapabilityReceipt(
        receipt_id="test-agy-receipt",
        platform="agy",
        routes=["agy.review.direct"],
        observed_at=observed_at,
        stale_after="24h",
        cli=CliEvidence(binary="agy", available=True, version="1.0.10"),
        wrapper=WrapperEvidence(
            path="scripts/hapax-agy-reviewer",
            exists=True,
            executable=True,
            sha256="abc123",
        ),
        capability=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=["test:agy:capability"],
        ),
        resource=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=["test:agy:resource"],
        ),
        quota=SurfaceEvidence(
            status=quota_status,
            source="test",
            observed_at=observed_at,
            stale_after="15m",
            evidence_refs=quota_refs,
            reason_codes=quota_reason_codes,
        ),
        provider_docs=ProviderDocsEvidence(
            refs=["test:agy:docs"],
            fetched_at=observed_at,
            stale_after="30d",
        ),
    )


def _make_glmcp_receipt(
    *, observed_at: datetime, stale_after: str = "24h"
) -> PlatformCapabilityReceipt:
    return PlatformCapabilityReceipt(
        receipt_id="test-glmcp-receipt",
        platform="glmcp",
        routes=["glmcp.review.direct"],
        observed_at=observed_at,
        stale_after=stale_after,
        cli=CliEvidence(
            binary="scripts/hapax-glmcp-reviewer",
            available=True,
            version=(
                "hapax-glmcp-reviewer: ok model=glm-5.2 "
                "payg_fallback=enabled payg_base_url=https://api.z.ai/api/paas/v4"
            ),
        ),
        wrapper=WrapperEvidence(
            path="scripts/hapax-glmcp-reviewer",
            exists=True,
            executable=True,
            sha256="abc123",
        ),
        capability=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=["test:glmcp:capability:glm-5.2"],
        ),
        resource=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=["test:glmcp:resource:pass-backed-key"],
        ),
        quota=SurfaceEvidence(
            status=EvidenceStatus.UNOBSERVABLE,
            source="test",
            observed_at=observed_at,
            stale_after="15m",
            evidence_refs=["test:glmcp:quota:local-probe-unobservable"],
            reason_codes=["account_live_quota_receipt_absent", "quota_telemetry_unknown"],
        ),
        provider_docs=ProviderDocsEvidence(
            refs=["test:glmcp:provider-docs"],
            fetched_at=observed_at,
            stale_after="30d",
        ),
    )


CLAUDE_ADMISSION_EVIDENCE_REF = (
    "relay-receipt:claude-subscription-quota-admission-20260708t140000z.yaml:"
    "witness:claude-subscription-headroom-observed-20260708t1400z:"
    "observation:subscription_quota_headroom_observed:"
    "observed_at:2026-07-08T14:00:00Z:"
    "fresh_until:2026-07-08T14:15:00Z:"
    "account-live-quota:observed"
)
CLAUDE_NOW = datetime(2026, 7, 8, 14, 5, tzinfo=UTC)


def _write_claude_live_quota_ledger(path: Path) -> None:
    payload = deepcopy(json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8")))
    payload["ledger_id"] = "quota-spend-ledger-test-claude-live"
    payload["captured_at"] = "2026-07-08T13:59:30Z"
    payload["generated_from"] = list(
        dict.fromkeys([*payload["generated_from"], "scripts/hapax-quota-telemetry-writer"])
    )
    # Drop the base EXHAUSTED operator dry-run claude snapshot so the fresh admission is isolated.
    payload["quota_snapshots"] = [
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot.get("route_id") != "claude.headless.full"
    ]
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-claude-headless-full-fresh",
            "captured_at": "2026-07-08T13:59:00Z",
            "fresh_until": "2026-07-08T14:15:00Z",
            "route_id": "claude.headless.full",
            "provider": "anthropic-claude-subscription",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [CLAUDE_ADMISSION_EVIDENCE_REF],
            "operator_visible_reason": "fixture claude admission receipt",
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_stale_claude_live_quota_ledger(
    path: Path,
    *,
    evidence_ref: str = CLAUDE_ADMISSION_EVIDENCE_REF,
) -> None:
    _write_claude_live_quota_ledger(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for snapshot in payload["quota_snapshots"]:
        if snapshot.get("route_id") == "claude.headless.full":
            snapshot["fresh_until"] = "2026-07-08T14:01:00Z"
            snapshot["evidence_refs"] = [evidence_ref]
            break
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_agy_live_quota_ledger(path: Path) -> None:
    payload = deepcopy(json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8")))
    payload["ledger_id"] = "quota-spend-ledger-test-agy-live"
    payload["captured_at"] = "2026-05-17T07:59:30Z"
    payload["generated_from"] = list(
        dict.fromkeys([*payload["generated_from"], "scripts/hapax-quota-telemetry-writer"])
    )
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-agy-review-direct-fresh",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "agy.review.direct",
            "provider": "google-antigravity-cli-agy",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [AGY_ADMISSION_EVIDENCE_REF],
            "operator_visible_reason": "fixture agy admission receipt",
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_glmcp_live_quota_ledger(path: Path) -> None:
    payload = deepcopy(json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8")))
    payload["ledger_id"] = "quota-spend-ledger-test-glmcp-payg-live"
    payload["captured_at"] = "2026-05-17T07:59:30Z"
    payload["generated_from"] = list(
        dict.fromkeys([*payload["generated_from"], "scripts/hapax-quota-telemetry-writer"])
    )
    payload["transition_budgets"].append(
        {
            "budget_schema": 1,
            "budget_id": GLMCP_PAYG_BUDGET_ID,
            "authority_case": "CASE-CAPACITY-ROUTING-GLMCP-PAYG-TEST",
            "approved_by": "operator",
            "created_at": "2026-05-17T07:00:00Z",
            "expires_at": "2026-05-17T09:00:00Z",
            "capacity_pool": "api_paid_spend",
            "providers_allowed": ["z_ai"],
            "profiles_allowed": ["glmcp-review-direct"],
            "task_classes_allowed": ["independent-review"],
            "quality_floors_allowed": ["frontier_review_required"],
            "total_cap_usd": "100.00",
            "per_task_cap_usd": "2.00",
            "daily_cap_usd": "20.00",
            "auto_top_up_allowed": False,
            "subscription_path_checked_at": "2026-05-17T07:00:00Z",
            "reason_subscription_path_not_used": (
                "fixture Coding Plan quota exhausted; PAYG spend gate under test"
            ),
            "steady_state_replacement": {
                "target_route_id": None,
                "blocker_to_remove": None,
                "exit_criterion": None,
            },
            "ledger_owner": "test",
            "dashboard_visibility": "required",
            "lifecycle_state": "active",
        }
    )
    payload["spend_receipts"].append(
        {
            "spend_receipt_schema": 1,
            "spend_id": "spend-20260517T075900Z-glmcp-payg-review-test",
            "task_id": "glmcp-review-direct",
            "authority_case": "CASE-CAPACITY-ROUTING-GLMCP-PAYG-TEST",
            "route_id": "glmcp.review.direct",
            "capacity_pool": "api_paid_spend",
            "budget_id": GLMCP_PAYG_BUDGET_ID,
            "provider": "z_ai",
            "model_or_engine": "glm-5.2",
            "model_id": "z_ai-glm-5.2",
            "effort": "none",
            "quantization": "not_applicable",
            "auth_surface": "api_key",
            "quality_floor": "frontier_review_required",
            "quality_preservation_reason": (
                "receipt-bounded GLMCP review fallback after Coding Plan quota wall"
            ),
            "spend_reason": "quota_exhaustion",
            "estimated_cost_usd": "0.05",
            "created_at": "2026-05-17T07:59:00Z",
            "reconcile_by": "2026-05-18T07:59:00Z",
            "reconciliation_state": "pending",
            "support_artifact_authority": "none",
        }
    )
    payload["quota_snapshots"] = [
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-payg-live",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [
                GLMCP_PAYG_ADMISSION_EVIDENCE_REF,
                "spend-gate:glmcp.review.direct:eligible_active_budget",
                f"spend-gate-budget:{GLMCP_PAYG_BUDGET_ID}",
            ],
            "operator_visible_reason": "fixture GLMCP PAYG admission receipt",
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_subscription_quota_nonblocking_uses_receipt_stale_after_without_clearing_admission() -> (
    None
):
    """Regression: unobservable subscription quota extends freshness but does not admit Claude."""
    payload = _payload()
    route = _route_payload(payload, "claude.headless.full")
    assert route["capacity_pool"] == "subscription_quota"
    route["blocked_reasons"] = [
        "account_live_quota_receipt_absent",
        "quota_telemetry_unknown",
    ]
    route["freshness"]["evidence"]["quota"]["blocked_reasons"] = [
        "account_live_quota_receipt_absent",
        "quota_telemetry_unknown",
    ]

    receipt_time = datetime(2026, 5, 9, 20, 0, tzinfo=UTC)
    receipt = _make_receipt(observed_at=receipt_time, stale_after="24h")
    _apply_receipt_to_route_payload(route, receipt)

    assert route["freshness"]["quota_stale_after"] == "24h"
    assert route["route_state"] == "blocked"
    assert route["blocked_reasons"] == ["account_live_quota_receipt_absent"]
    assert route["freshness"]["evidence"]["quota"]["blocked_reasons"] == [
        "account_live_quota_receipt_absent"
    ]

    check_at = datetime(2026, 5, 9, 21, 0, tzinfo=UTC)
    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(registry, route_ids=["claude.headless.full"], now=check_at)

    quota_stale_errors = [e for e in result.routes[0].errors if "quota" in e and "stale" in e]
    assert not quota_stale_errors, f"quota should not be stale after 1h: {quota_stale_errors}"
    assert result.ok is False
    assert "account_live_quota_receipt_absent" in result.routes[0].blocked_reasons


def test_claude_observed_platform_quota_receipt_does_not_clear_live_admission_blocker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _payload()
    route = _route_payload(payload, "claude.headless.full")
    route["blocked_reasons"] = [
        "account_live_quota_receipt_absent",
        "quota_telemetry_unknown",
    ]
    route["freshness"]["evidence"]["quota"]["blocked_reasons"] = [
        "account_live_quota_receipt_absent",
        "quota_telemetry_unknown",
    ]
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(tmp_path / "missing-live.json"))

    observed_at = datetime(2026, 5, 9, 20, 0, tzinfo=UTC)
    receipt = _make_receipt(observed_at=observed_at).model_copy(
        update={
            "quota": SurfaceEvidence(
                status=EvidenceStatus.OBSERVED,
                source="test",
                observed_at=observed_at,
                stale_after="15m",
                evidence_refs=["test:claude:observed-platform-quota"],
                reason_codes=[],
            )
        }
    )

    _apply_receipt_to_route_payload(route, receipt, now=datetime(2026, 5, 9, 20, 1, tzinfo=UTC))

    assert route["route_state"] == "blocked"
    assert route["blocked_reasons"] == ["account_live_quota_receipt_absent"]
    assert route["freshness"]["evidence"]["quota"]["blocked_reasons"] == [
        "account_live_quota_receipt_absent"
    ]
    assert (
        "test:claude:observed-platform-quota"
        in route["freshness"]["evidence"]["quota"]["evidence_refs"]
    )


def test_loader_applies_route_authority_receipts_after_platform_receipts(tmp_path: Path) -> None:
    """Platform freshness projections must mirror dispatch route authority."""

    from shared.dispatcher_policy import (
        build_route_authority_receipt,
        write_route_authority_receipt,
    )

    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    observed_at = datetime(2026, 5, 9, 20, 0, tzinfo=UTC)
    platform_receipt = _make_receipt(observed_at=observed_at).model_copy(
        update={
            "receipt_id": "test-claude-opus",
            "routes": ["claude.headless.opus"],
        }
    )
    (receipt_dir / "claude.json").write_text(
        json.dumps(platform_receipt.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_route_authority_receipt(
        build_route_authority_receipt(
            receipt_type="opus_model_entitlement",
            route_id="claude.headless.opus",
            evidence_refs=["operator-signed:test-opus"],
            receipt_id="test-opus-entitlement",
            issued_at=observed_at,
        ),
        receipt_dir=receipt_dir,
    )

    check_at = datetime(2026, 5, 9, 20, 1, tzinfo=UTC)
    registry = load_platform_capability_registry(receipt_dir=receipt_dir, now=check_at)
    route = registry.require("claude.headless.opus")
    result = check_registry_freshness(registry, route_ids=["claude.headless.opus"], now=check_at)

    assert route.route_state is RouteState.ACTIVE
    assert result.ok is True
    assert "opus_model_entitlement_receipt_absent" not in route.blocked_reasons
    assert "fresh_capability_evidence_absent" not in route.blocked_reasons
    assert "account_live_quota_receipt_absent" not in route.blocked_reasons
    assert any(
        ref.startswith("route-authority-receipt:opus_model_entitlement")
        for ref in result.routes[0].evidence_refs
    )


def test_vibe_receipt_backfills_capability_checked_at_from_observed_at() -> None:
    payload = _payload()
    route = _route_payload(payload, "vibe.headless.full")
    assert route["freshness"]["capability_checked_at"] is None
    assert "fresh_capability_evidence_absent" in route["blocked_reasons"]

    receipt_time = datetime(2026, 6, 19, 15, 30, tzinfo=UTC)
    _apply_receipt_to_route_payload(route, _make_vibe_receipt(observed_at=receipt_time))

    assert route["freshness"]["capability_checked_at"] == "2026-06-19T15:30:00Z"
    assert route["freshness"]["resource_checked_at"] == "2026-06-19T15:30:00Z"
    assert route["freshness"]["quota_checked_at"] == "2026-06-19T15:30:00Z"
    assert route["freshness"]["quota_stale_after"] == "24h"
    assert route["route_state"] == "active"
    assert route["blocked_reasons"] == []
    assert (
        "fresh_capability_evidence_absent"
        not in (route["freshness"]["evidence"]["capability"]["blocked_reasons"])
    )
    assert any(
        ref.startswith("platform-capability-receipt:vibe:")
        for ref in route["freshness"]["evidence"]["capability"]["evidence_refs"]
    )

    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(
        registry,
        route_ids=["vibe.headless.full"],
        now=datetime(2026, 6, 19, 15, 31, tzinfo=UTC),
    )

    assert result.ok is True


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


def test_agy_local_receipt_clears_review_seat_but_not_route_quota(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(tmp_path / "missing-live.json"))
    payload = _payload()
    route = _route_payload(payload, "agy.review.direct")

    receipt_time = datetime(2026, 7, 5, 14, 51, tzinfo=UTC)
    _apply_receipt_to_route_payload(route, _make_agy_receipt(observed_at=receipt_time))

    assert route["route_state"] == "blocked"
    assert "agy_review_seat_receipt_admission_required" not in route["blocked_reasons"]
    assert "route_specific_quota_receipt_absent" in route["blocked_reasons"]
    assert (
        "route_specific_quota_receipt_absent"
        in route["freshness"]["evidence"]["quota"]["blocked_reasons"]
    )


def test_agy_observed_route_quota_receipt_does_not_admit_review_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(tmp_path / "missing-live.json"))
    payload = _payload()
    route = _route_payload(payload, "agy.review.direct")

    receipt_time = datetime(2026, 7, 5, 14, 51, tzinfo=UTC)
    _apply_receipt_to_route_payload(
        route,
        _make_agy_receipt(
            observed_at=receipt_time,
            quota_status=EvidenceStatus.OBSERVED,
            quota_refs=["test:agy:route-quota-observed"],
        ),
    )

    assert route["route_state"] == "blocked"
    assert route["blocked_reasons"] == ["route_specific_quota_receipt_absent"]
    assert route["freshness"]["evidence"]["quota"]["blocked_reasons"] == [
        "route_specific_quota_receipt_absent"
    ]
    assert (
        "test:agy:route-quota-observed" in route["freshness"]["evidence"]["quota"]["evidence_refs"]
    )

    registry = PlatformCapabilityRegistry.model_validate(payload)
    result = check_registry_freshness(
        registry,
        route_ids=["agy.review.direct"],
        now=datetime(2026, 7, 5, 14, 52, tzinfo=UTC),
    )
    assert result.ok is False
    assert "route_specific_quota_receipt_absent" in result.routes[0].blocked_reasons


def test_forged_agy_observed_quota_receipt_cannot_clear_route_specific_blocker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(tmp_path / "missing-live.json"))
    payload = _payload()
    route = _route_payload(payload, "agy.review.direct")
    quota_blockers = [
        "account_live_quota_receipt_absent",
        "quota_telemetry_unknown",
        "route_specific_quota_receipt_absent",
    ]
    route["blocked_reasons"] = [*quota_blockers]
    route["freshness"]["evidence"]["quota"]["blocked_reasons"] = [*quota_blockers]

    _apply_receipt_to_route_payload(
        route,
        _make_agy_receipt(
            observed_at=datetime(2026, 7, 5, 14, 51, tzinfo=UTC),
            quota_status=EvidenceStatus.OBSERVED,
            quota_refs=["test:forged-agy:observed-quota"],
        ),
    )

    assert route["route_state"] == "blocked"
    assert route["blocked_reasons"] == quota_blockers
    assert route["freshness"]["evidence"]["quota"]["blocked_reasons"] == quota_blockers


def test_agy_quota_receipt_removable_reasons_preserve_route_specific_blocker() -> None:
    payload = _payload()
    route = _route_payload(payload, "agy.review.direct")

    removable = _quota_receipt_removable_reasons(route)

    assert removable == set()
    assert "account_live_quota_receipt_absent" not in removable
    assert "quota_telemetry_unknown" not in removable
    assert "route_specific_quota_receipt_absent" not in removable
    assert "agy_review_seat_receipt_admission_required" not in removable


def test_agy_has_no_route_specific_quota_admission_without_live_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _payload()
    route = _route_payload(payload, "agy.review.direct")
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(tmp_path / "missing-live.json"))

    admitted, refs = _route_specific_quota_admission_fresh(
        route,
        now=datetime(2026, 7, 5, 14, 52, tzinfo=UTC),
    )

    assert admitted is False
    assert refs == ()


def test_quota_spend_live_env_disable_sentinel_skips_default_live_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    route = _route_payload(payload, "agy.review.direct")
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", "none")

    admitted, refs = _route_specific_quota_admission_fresh(
        route,
        now=datetime(2026, 7, 5, 14, 52, tzinfo=UTC),
    )

    assert admitted is False
    assert refs == ()


def test_agy_receipt_with_fresh_live_admission_clears_route_quota(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    live_ledger = tmp_path / "quota-spend-ledger-live.json"
    _write_agy_live_quota_ledger(live_ledger)
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(live_ledger))

    receipt_time = datetime(2026, 5, 17, 8, 0, tzinfo=UTC)
    (receipt_dir / "agy.json").write_text(
        _make_agy_receipt(observed_at=receipt_time).model_dump_json(),
        encoding="utf-8",
    )
    registry = load_platform_capability_registry(
        receipt_dir=receipt_dir,
        now=datetime(2026, 5, 17, 8, 1, tzinfo=UTC),
    )
    route = registry.require("agy.review.direct")
    result = check_registry_freshness(
        registry,
        route_ids=["agy.review.direct"],
        now=datetime(2026, 5, 17, 8, 1, tzinfo=UTC),
    )

    assert route.route_state is RouteState.ACTIVE
    assert route.blocked_reasons == []
    assert AGY_ADMISSION_EVIDENCE_REF in route.freshness.evidence.quota.evidence_refs
    assert result.ok is True


def test_claude_receipt_with_fresh_live_admission_injects_account_live_quota_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # A fresh live ledger admission for claude.headless.full makes _route_specific_quota_admission_fresh
    # return the account-live-quota:observed evidence ref, which the caller injects into quota
    # freshness so the availability guarantor attests (proven AVAILABLE in the guarantor test).
    live_ledger = tmp_path / "quota-spend-ledger-live.json"
    _write_claude_live_quota_ledger(live_ledger)
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(live_ledger))
    route = _route_payload(_payload(), "claude.headless.full")

    admitted, refs = _route_specific_quota_admission_fresh(route, now=CLAUDE_NOW)

    assert admitted is True
    assert CLAUDE_ADMISSION_EVIDENCE_REF in refs
    assert any(ref.endswith(":account-live-quota:observed") for ref in refs)


def test_claude_receipt_with_fresh_live_admission_clears_account_live_quota_blocker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live_ledger = tmp_path / "quota-spend-ledger-live.json"
    _write_claude_live_quota_ledger(live_ledger)
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(live_ledger))
    route = _route_payload(_payload(), "claude.headless.full")

    _apply_receipt_to_route_payload(
        route,
        _make_receipt(observed_at=datetime(2026, 7, 8, 14, 1, tzinfo=UTC)),
        now=CLAUDE_NOW,
    )

    assert route["route_state"] == "active"
    assert route["blocked_reasons"] == []
    assert route["freshness"]["evidence"]["quota"]["blocked_reasons"] == []
    assert CLAUDE_ADMISSION_EVIDENCE_REF in route["freshness"]["evidence"]["quota"]["evidence_refs"]


def test_claude_stale_live_admission_does_not_inject_account_live_quota_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live_ledger = tmp_path / "quota-spend-ledger-live.json"
    _write_stale_claude_live_quota_ledger(live_ledger)
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(live_ledger))
    route = _route_payload(_payload(), "claude.headless.full")

    _apply_receipt_to_route_payload(
        route,
        _make_receipt(observed_at=datetime(2026, 7, 8, 14, 2, tzinfo=UTC)),
        now=CLAUDE_NOW,
    )

    assert route["route_state"] == "blocked"
    assert route["blocked_reasons"] == ["account_live_quota_receipt_absent"]
    assert (
        CLAUDE_ADMISSION_EVIDENCE_REF
        not in route["freshness"]["evidence"]["quota"]["evidence_refs"]
    )


def test_claude_stale_live_admission_strips_tokenized_account_live_quota_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live_ledger = tmp_path / "quota-spend-ledger-live.json"
    stale_ref = "probe:account_live_quota_observed"
    _write_stale_claude_live_quota_ledger(live_ledger, evidence_ref=stale_ref)
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(live_ledger))
    route = _route_payload(_payload(), "claude.headless.full")

    _apply_receipt_to_route_payload(
        route,
        _make_receipt(observed_at=datetime(2026, 7, 8, 14, 2, tzinfo=UTC)),
        now=CLAUDE_NOW,
    )

    refs = route["freshness"]["evidence"]["quota"]["evidence_refs"]
    assert route["route_state"] == "blocked"
    assert route["blocked_reasons"] == ["account_live_quota_receipt_absent"]
    assert stale_ref not in refs


def test_claude_has_no_route_specific_quota_admission_without_live_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Fail-closed: absent a live ledger, claude gets no route-specific admission — lane/session
    # presence never clears the account-live quota gate.
    route = _route_payload(_payload(), "claude.headless.full")
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(tmp_path / "missing-live.json"))

    admitted, refs = _route_specific_quota_admission_fresh(route, now=CLAUDE_NOW)

    assert admitted is False
    assert refs == ()


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


def test_glmcp_receipt_does_not_clear_admission_without_live_quota_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    receipt_time = datetime(2026, 5, 17, 8, 0, tzinfo=UTC)
    (receipt_dir / "glmcp.json").write_text(
        _make_glmcp_receipt(observed_at=receipt_time).model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(tmp_path / "missing-live.json"))

    registry = load_platform_capability_registry(
        receipt_dir=receipt_dir,
        now=datetime(2026, 5, 17, 8, 1, tzinfo=UTC),
    )
    route = registry.require("glmcp.review.direct")

    assert route.route_state is RouteState.BLOCKED
    assert "glmcp_review_seat_receipt_admission_required" in route.blocked_reasons
    assert "fresh_capability_evidence_absent" not in route.blocked_reasons
    assert "quota_telemetry_unknown" not in route.blocked_reasons


def test_glmcp_receipt_with_fresh_live_payg_admission_clears_review_latch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    live_ledger = tmp_path / "quota-spend-ledger-live.json"
    _write_glmcp_live_quota_ledger(live_ledger)
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(live_ledger))

    receipt_time = datetime(2026, 5, 17, 8, 0, tzinfo=UTC)
    (receipt_dir / "glmcp.json").write_text(
        _make_glmcp_receipt(observed_at=receipt_time).model_dump_json(),
        encoding="utf-8",
    )
    registry = load_platform_capability_registry(
        receipt_dir=receipt_dir,
        now=datetime(2026, 5, 17, 8, 1, tzinfo=UTC),
    )
    route = registry.require("glmcp.review.direct")
    result = check_registry_freshness(
        registry,
        route_ids=["glmcp.review.direct"],
        now=datetime(2026, 5, 17, 8, 1, tzinfo=UTC),
    )

    assert route.route_state is RouteState.ACTIVE
    assert route.blocked_reasons == []
    assert GLMCP_PAYG_ADMISSION_EVIDENCE_REF in route.freshness.evidence.quota.evidence_refs
    assert result.ok is True


def test_glmcp_receipt_surfaces_invalid_live_quota_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    live_ledger = tmp_path / "quota-spend-ledger-live.json"
    live_ledger.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(live_ledger))

    receipt_time = datetime(2026, 5, 17, 8, 0, tzinfo=UTC)
    (receipt_dir / "glmcp.json").write_text(
        _make_glmcp_receipt(observed_at=receipt_time).model_dump_json(),
        encoding="utf-8",
    )
    registry = load_platform_capability_registry(
        receipt_dir=receipt_dir,
        now=datetime(2026, 5, 17, 8, 1, tzinfo=UTC),
    )
    route = registry.require("glmcp.review.direct")

    assert route.route_state is RouteState.BLOCKED
    assert "glmcp_review_seat_receipt_admission_required" in route.blocked_reasons
    assert (
        "quota-spend-ledger:glmcp.review.direct:live-ledger-invalid"
        in route.freshness.evidence.quota.evidence_refs
    )


def test_api_receipt_score_suppression_honors_top_level_unmeasured_blocker() -> None:
    payload = _payload()
    route = _route_payload(payload, "api.headless.openrouter")
    route["freshness"]["evidence"]["capability"]["blocked_reasons"] = []
    route["blocked_reasons"] = [
        reason for reason in route["blocked_reasons"] if reason != "capabilityio_measurement_absent"
    ]

    receipt_time = datetime(2026, 7, 5, 16, 0, tzinfo=UTC)
    _apply_receipt_to_route_payload(route, _make_api_receipt(observed_at=receipt_time))

    assert "capability_scores_asserted_not_measured" in route["blocked_reasons"]
    assert route["capability_scores"]["source_editing"]["observed_at"] is None
    assert not any(
        ref.startswith("platform-capability-receipt:api:")
        for ref in route["capability_scores"]["source_editing"]["evidence_refs"]
    )


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
