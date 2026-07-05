"""Tests for capability-agnostic availability receipts."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

import shared.capability_availability_guarantor as guarantor
from shared.capability_availability_guarantor import (
    CodexOAuthRefreshStrategy,
    RefreshCommandResult,
    RefreshOutcome,
    RefreshStatus,
    RefreshStrategyRegistry,
    availability_dispatch_reason_codes,
    default_refresh_strategy_registry,
    evaluate_registry_availability,
    evaluate_route_availability,
)
from shared.dispatcher_policy import _capability_state
from shared.platform_capability_registry import (
    AuthSurface,
    PlatformCapabilityRegistry,
    RouteFreshnessCheck,
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


class _FakeRefreshRunner:
    def __init__(self, result: RefreshCommandResult) -> None:
        self.result = result
        self.commands: list[tuple[str, ...]] = []
        self.timeout_s: float | None = None

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        timeout_s: float,
    ) -> RefreshCommandResult:
        self.commands.append(command)
        self.timeout_s = timeout_s
        return self.result


def _payload() -> dict:
    return load_platform_capability_registry().model_dump(mode="json")


def _route_payload(payload: dict, route_id: str) -> dict:
    return next(route for route in payload["routes"] if route["route_id"] == route_id)


def _degraded_codex_route_and_freshness():
    registry = load_platform_capability_registry()
    route = registry.require("codex.headless.full")
    freshness = check_registry_freshness(registry, route_ids=[route.route_id], now=NOW).routes[0]
    return route, freshness


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


def _mark_account_live_quota_observed(route: dict) -> None:
    route["freshness"]["evidence"]["quota"]["evidence_refs"].append(
        "test:codex:account-live-quota:observed"
    )


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
    _mark_account_live_quota_observed(route_payload)
    registry = PlatformCapabilityRegistry.model_validate(payload)
    route = registry.require("codex.headless.full")
    freshness = check_registry_freshness(registry, route_ids=[route.route_id], now=NOW).routes[0]

    receipt = evaluate_route_availability(route, freshness, now=NOW)

    assert receipt.available is True
    assert receipt.status.value == "available"
    assert receipt.refresh_status is RefreshStatus.NOT_REQUIRED
    assert receipt.reason_codes == ()


def test_oauth_subscription_route_degrades_when_account_live_quota_is_unobservable() -> None:
    payload = _payload()
    route_payload = _route_payload(payload, "codex.headless.full")
    _mark_fresh(route_payload)
    route_payload["freshness"]["evidence"]["quota"]["evidence_refs"] = [
        "local:codex:quota-probe:unobservable",
        "platform-capability-receipt:codex:test-codex-receipt",
    ]
    registry = PlatformCapabilityRegistry.model_validate(payload)
    route = registry.require("codex.headless.full")
    freshness = check_registry_freshness(registry, route_ids=[route.route_id], now=NOW).routes[0]

    assert freshness.ok is True

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry(()),
        now=NOW,
    )

    assert receipt.available is False
    assert receipt.status.value == "degraded"
    assert receipt.predicate.account_live_quota_attested is False
    assert "account_live_quota_evidence_absent" in receipt.reason_codes
    assert "auth_surface_not_fresh" in receipt.reason_codes
    assert "capacity_pool_headroom_not_fresh" in receipt.reason_codes


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


def test_default_codex_oauth_strategy_is_pure_deferred_action() -> None:
    route, freshness = _degraded_codex_route_and_freshness()

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=default_refresh_strategy_registry(),
        now=NOW,
    )

    assert receipt.refresh_strategy_id == "codex-oauth-supported-refresh"
    assert receipt.refresh_status is RefreshStatus.DEFERRED
    assert "refresh_execution_not_requested" in receipt.refresh_reason_codes
    reasons = availability_dispatch_reason_codes(receipt)
    assert (
        "refresh_remediation:scripts/hapax-platform-capability-receipts --platform codex --json"
        in reasons
    )


def test_executable_codex_oauth_strategy_runs_receipt_refresher_without_bearer_daemon() -> None:
    route, freshness = _degraded_codex_route_and_freshness()
    runner = _FakeRefreshRunner(
        RefreshCommandResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "receipts": [
                        {
                            "platform": "codex",
                            "receipt_id": "codex-20260509T210000Z",
                            "path": "/tmp/codex.json",
                            "cli_available": True,
                            "wrapper_exists": True,
                            "quota_status": "observed",
                            "quota_reason_codes": [],
                        }
                    ]
                }
            ),
        )
    )

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry(
            (CodexOAuthRefreshStrategy(runner=runner, timeout_s=3.0),)
        ),
        now=NOW,
    )

    assert runner.commands
    assert runner.commands[0][1:] == (
        "--platform",
        "codex",
        "--json",
        "--now",
        "2026-05-09T21:00:00Z",
    )
    assert runner.commands[0][-1] == "2026-05-09T21:00:00Z"
    assert runner.timeout_s == 3.0
    assert receipt.refresh_strategy_id == "codex-oauth-supported-refresh"
    assert receipt.refresh_status is RefreshStatus.REFRESHED
    assert "refresh_receipt_written" in receipt.refresh_reason_codes
    assert "platform-capability-receipt:codex:codex-20260509T210000Z" in (
        receipt.refresh_evidence_refs
    )
    assert "policy:not_codex_access_token_daemon" in receipt.refresh_evidence_refs
    serialized = " ".join(
        [
            *receipt.refresh_reason_codes,
            *receipt.refresh_evidence_refs,
            *receipt.refresh_remediation_commands,
        ]
    )
    assert "CODEX_ACCESS_TOKEN" not in serialized


def test_executable_codex_oauth_strategy_defers_when_account_live_quota_unverified() -> None:
    route, freshness = _degraded_codex_route_and_freshness()
    runner = _FakeRefreshRunner(
        RefreshCommandResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "receipts": [
                        {
                            "platform": "codex",
                            "receipt_id": "codex-unverified",
                            "path": "/tmp/codex.json",
                            "cli_available": True,
                            "wrapper_exists": True,
                            "quota_status": "unobservable",
                            "quota_reason_codes": ["account_live_quota_receipt_absent"],
                        }
                    ]
                }
            ),
        )
    )

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry((CodexOAuthRefreshStrategy(runner=runner),)),
        now=NOW,
    )

    assert receipt.refresh_status is RefreshStatus.DEFERRED
    assert "refresh_receipt_account_live_unverified" in receipt.refresh_reason_codes
    assert "refresh_receipt_quota_status:unobservable" in receipt.refresh_reason_codes
    assert (
        "refresh_receipt_quota_reason:account_live_quota_receipt_absent"
        in receipt.refresh_reason_codes
    )
    assert "refresh_receipt_written" not in receipt.refresh_reason_codes


def test_executable_codex_oauth_strategy_reports_command_failure() -> None:
    route, freshness = _degraded_codex_route_and_freshness()
    runner = _FakeRefreshRunner(RefreshCommandResult(returncode=2, stderr="boom"))

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry((CodexOAuthRefreshStrategy(runner=runner),)),
        now=NOW,
    )

    assert receipt.refresh_status is RefreshStatus.FAILED
    assert "refresh_command_failed:2" in receipt.refresh_reason_codes
    assert (
        "scripts/hapax-platform-capability-receipts --platform codex --json"
        in receipt.refresh_remediation_commands
    )


def test_executable_codex_oauth_strategy_reports_missing_receipt_output() -> None:
    route, freshness = _degraded_codex_route_and_freshness()
    runner = _FakeRefreshRunner(RefreshCommandResult(returncode=0, stdout="not-json"))

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry((CodexOAuthRefreshStrategy(runner=runner),)),
        now=NOW,
    )

    assert receipt.refresh_status is RefreshStatus.FAILED
    assert "refresh_receipt_missing_from_command_output" in receipt.refresh_reason_codes


def test_executable_codex_oauth_strategy_reports_unavailable_receipt() -> None:
    route, freshness = _degraded_codex_route_and_freshness()
    runner = _FakeRefreshRunner(
        RefreshCommandResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "receipts": [
                        {
                            "platform": "codex",
                            "receipt_id": "codex-unavailable",
                            "path": "/tmp/codex.json",
                            "cli_available": False,
                            "wrapper_exists": True,
                        }
                    ]
                }
            ),
        )
    )

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry((CodexOAuthRefreshStrategy(runner=runner),)),
        now=NOW,
    )

    assert receipt.refresh_status is RefreshStatus.FAILED
    assert "refresh_receipt_observed_codex_unavailable" in receipt.refresh_reason_codes


def test_executable_codex_oauth_strategy_reports_timeout(monkeypatch) -> None:  # noqa: ANN001
    route, freshness = _degraded_codex_route_and_freshness()

    def _timeout(*args, **kwargs):  # noqa: ANN002, ANN003
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(guarantor.subprocess, "run", _timeout)

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry((CodexOAuthRefreshStrategy(execute=True),)),
        now=NOW,
    )

    assert receipt.refresh_status is RefreshStatus.FAILED
    assert "refresh_command_failed:124" in receipt.refresh_reason_codes


def test_executable_codex_oauth_strategy_reports_os_error(monkeypatch) -> None:  # noqa: ANN001
    route, freshness = _degraded_codex_route_and_freshness()

    def _os_error(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("missing executable")

    monkeypatch.setattr(guarantor.subprocess, "run", _os_error)

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry((CodexOAuthRefreshStrategy(execute=True),)),
        now=NOW,
    )

    assert receipt.refresh_status is RefreshStatus.FAILED
    assert "refresh_command_failed:127" in receipt.refresh_reason_codes


def test_registry_availability_fails_closed_for_unsupported_route_filter() -> None:
    registry = load_platform_capability_registry()

    result = evaluate_registry_availability(
        registry,
        route_ids=["codex/headless/nope"],
        now=NOW,
    )

    assert result.ok is False
    assert result.receipts == ()
    assert len(result.unsupported_routes) == 1
    assert result.unsupported_routes[0].route_id == "codex.headless.nope"
    assert result.to_dict()["unsupported_routes"][0]["errors"] == [
        "unsupported route: codex.headless.nope"
    ]


def test_registry_availability_mixed_filter_keeps_supported_receipt_but_fails_overall() -> None:
    payload = _payload()
    route_payload = _route_payload(payload, "codex.headless.full")
    _mark_fresh(route_payload)
    _mark_account_live_quota_observed(route_payload)
    registry = PlatformCapabilityRegistry.model_validate(payload)

    result = evaluate_registry_availability(
        registry,
        route_ids=["codex.headless.full", "codex.headless.nope"],
        now=NOW,
    )

    assert result.ok is False
    assert [receipt.route_id for receipt in result.receipts] == ["codex.headless.full"]
    assert result.receipts[0].available is True
    assert [route.route_id for route in result.unsupported_routes] == ["codex.headless.nope"]


def test_no_strategy_refresh_outcome_carries_remediation() -> None:
    registry = load_platform_capability_registry()
    route = registry.require("api.headless.api_frontier")
    freshness = check_registry_freshness(registry, route_ids=[route.route_id], now=NOW).routes[0]

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry(()),
        now=NOW,
    )

    assert receipt.refresh_status is RefreshStatus.NO_STRATEGY
    reasons = availability_dispatch_reason_codes(receipt)
    assert "refresh_strategy_absent:api_key" in reasons
    assert "refresh_remediation:register refresh strategy for auth_surface=api_key" in reasons


def test_capability_staleness_does_not_masquerade_as_auth_staleness() -> None:
    payload = _payload()
    route_payload = _route_payload(payload, "codex.headless.full")
    _mark_fresh(route_payload)
    _mark_account_live_quota_observed(route_payload)
    route_payload["freshness"]["capability_checked_at"] = "2026-05-01T00:00:00Z"
    registry = PlatformCapabilityRegistry.model_validate(payload)
    route = registry.require("codex.headless.full")
    freshness = check_registry_freshness(registry, route_ids=[route.route_id], now=NOW).routes[0]

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry(()),
        now=NOW,
    )

    assert receipt.available is False
    assert "capability_degraded" in receipt.reason_codes
    assert "auth_surface_not_fresh" not in receipt.reason_codes


def test_reason_token_matching_does_not_overmatch_authority_or_quotable_text() -> None:
    payload = _payload()
    route_payload = _route_payload(payload, "codex.headless.full")
    _mark_fresh(route_payload)
    registry = PlatformCapabilityRegistry.model_validate(payload)
    route = registry.require("codex.headless.full")
    freshness = RouteFreshnessCheck(
        route_id=route.route_id,
        ok=False,
        supported=True,
        errors=(
            "authority metadata stale",
            "quotable docs stale",
        ),
        evidence_refs=("test:codex:account-live-quota:observed",),
    )

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry(()),
        now=NOW,
    )

    assert "auth_surface_not_fresh" not in receipt.reason_codes
    assert "capacity_pool_headroom_not_fresh" not in receipt.reason_codes


def test_reason_token_matching_counts_snake_case_auth_and_quota_tokens() -> None:
    payload = _payload()
    route_payload = _route_payload(payload, "codex.headless.full")
    _mark_fresh(route_payload)
    registry = PlatformCapabilityRegistry.model_validate(payload)
    route = registry.require("codex.headless.full")
    freshness = RouteFreshnessCheck(
        route_id=route.route_id,
        ok=False,
        supported=True,
        errors=(
            "auth_failed",
            "quota_exceeded",
        ),
        evidence_refs=("test:codex:account-live-quota:observed",),
    )

    receipt = evaluate_route_availability(
        route,
        freshness,
        refresh_strategies=RefreshStrategyRegistry(()),
        now=NOW,
    )

    assert "auth_surface_not_fresh" in receipt.reason_codes
    assert "capacity_pool_headroom_not_fresh" in receipt.reason_codes


def test_dispatcher_capability_state_carries_availability_receipt_ref_without_refresh_side_effect(
    monkeypatch,
) -> None:
    registry = load_platform_capability_registry()
    calls: list[tuple[str, ...]] = []

    def _forbidden_runner(
        command: tuple[str, ...],
        *,
        timeout_s: float,
    ) -> RefreshCommandResult:
        calls.append(command)
        raise AssertionError("dispatcher capability evaluation must not execute refresh")

    monkeypatch.setattr(guarantor, "_run_refresh_command", _forbidden_runner)

    capability = _capability_state(
        registry,
        "codex.headless.full",
        None,
        now=NOW,
    )

    assert capability is not None
    assert capability.availability_status == "degraded"
    assert capability.availability_receipt_ref is not None
    assert capability.availability_refresh_status == "deferred"
    assert capability.availability_recomposition_required is True
    assert any(reason.startswith("availability_receipt:") for reason in capability.freshness_errors)
    assert (
        "refresh_remediation:scripts/hapax-platform-capability-receipts --platform codex --json"
        in capability.freshness_errors
    )
    assert calls == []
