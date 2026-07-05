"""Tests for capability-agnostic availability receipts."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.capability_availability_guarantor import (
    RefreshOutcome,
    RefreshStatus,
    RefreshStrategyRegistry,
    availability_dispatch_reason_codes,
    default_refresh_strategy_registry,
    evaluate_route_availability,
)
from shared.dispatcher_policy import _capability_state
from shared.platform_capability_registry import (
    AuthSurface,
    PlatformCapabilityRegistry,
    RouteState,
    check_registry_freshness,
    load_platform_capability_registry,
)

NOW = datetime(2026, 5, 9, 21, 0, tzinfo=UTC)


class _FakeOAuthStrategy:
    auth_surface = AuthSurface.OAUTH
    strategy_id = "test-oauth"

    def refresh(self, route, freshness, *, now):  # noqa: ANN001
        return RefreshOutcome(
            status=RefreshStatus.REFRESHED,
            strategy_id=self.strategy_id,
            reason_codes=("test_oauth_refresh_invoked",),
            evidence_refs=(f"test:oauth:{route.route_id}",),
        )


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
        "capability": {"evidence_refs": ["test:fresh-capability"], "blocked_reasons": []},
        "quota": {"evidence_refs": ["test:fresh-quota"], "blocked_reasons": []},
        "resource": {"evidence_refs": ["test:fresh-resource"], "blocked_reasons": []},
        "provider_docs": {"evidence_refs": ["test:fresh-provider-docs"], "blocked_reasons": []},
    }
    for score in route["capability_scores"].values():
        score["observed_at"] = "2026-05-09T20:55:00Z"
        score["evidence_refs"] = ["test:fresh-score"]
    for tool in route["tool_state"]:
        tool["observed_at"] = "2026-05-09T20:55:00Z"
        tool["evidence_ref"] = "test:fresh-tool"


def test_codex_routes_are_oauth_auth_surface_with_subscription_capacity() -> None:
    registry = load_platform_capability_registry()

    for route_id in ("codex.headless.full", "codex.headless.spark"):
        route = registry.require(route_id)
        assert route.auth_surface is AuthSurface.OAUTH
        assert route.capacity_pool.value == "subscription_quota"


def test_fresh_route_emits_available_receipt_without_refresh() -> None:
    payload = _payload()
    route_payload = _route_payload(payload, "codex.headless.full")
    _mark_fresh(route_payload)
    registry = PlatformCapabilityRegistry.model_validate(payload)
    route = registry.require("codex.headless.full")
    freshness = check_registry_freshness(registry, route_ids=[route.route_id], now=NOW).routes[0]

    receipt = evaluate_route_availability(route, freshness, now=NOW)

    assert receipt.available is True
    assert receipt.status.value == "available"
    assert receipt.refresh_status is RefreshStatus.NOT_REQUIRED
    assert receipt.reason_codes == ()


def test_degraded_oauth_route_uses_auth_surface_strategy_registry() -> None:
    registry = load_platform_capability_registry()
    route = registry.require("codex.headless.full")
    freshness = check_registry_freshness(registry, route_ids=[route.route_id], now=NOW).routes[0]
    strategies = RefreshStrategyRegistry((_FakeOAuthStrategy(),))

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=strategies,
        now=NOW,
    )

    assert receipt.available is False
    assert receipt.auth_surface == "oauth"
    assert receipt.refresh_status is RefreshStatus.REFRESHED
    assert receipt.refresh_strategy_id == "test-oauth"
    assert "capability_availability_degraded" in availability_dispatch_reason_codes(receipt)


def test_default_codex_oauth_strategy_avoids_bearer_token_daemon() -> None:
    registry = load_platform_capability_registry()
    route = registry.require("codex.headless.full")
    freshness = check_registry_freshness(registry, route_ids=[route.route_id], now=NOW).routes[0]

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=default_refresh_strategy_registry(),
        now=NOW,
    )

    assert receipt.refresh_strategy_id == "codex-oauth-supported-refresh"
    assert "policy:not_codex_access_token_daemon" in receipt.refresh_evidence_refs
    serialized = " ".join(
        [
            *receipt.refresh_reason_codes,
            *receipt.refresh_evidence_refs,
            *receipt.refresh_remediation_commands,
        ]
    )
    assert "CODEX_ACCESS_TOKEN" not in serialized


def test_dispatcher_capability_state_carries_availability_receipt_ref() -> None:
    registry = load_platform_capability_registry()

    capability = _capability_state(
        registry,
        "codex.headless.full",
        None,
        now=NOW,
    )

    assert capability is not None
    assert capability.availability_status == "degraded"
    assert capability.availability_receipt_ref is not None
    assert capability.availability_recomposition_required is True
    assert any(reason.startswith("availability_receipt:") for reason in capability.freshness_errors)
