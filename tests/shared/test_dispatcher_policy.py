"""Tests for the S5-4 fail-closed dispatcher policy evaluator."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from shared.dispatcher_policy import (
    ClogRouteState,
    DispatchAction,
    DispatchRequest,
    QuotaSpendState,
    RouteCapabilityState,
    build_dispatch_request,
    evaluate_dispatch_policy,
    load_dispatch_policy_sources,
    write_route_decision_receipt,
)
from shared.platform_capability_registry import (
    PlatformCapabilityRegistry,
    PlatformCapabilityRoute,
    build_supply_vector,
    load_platform_capability_registry,
)
from shared.quota_spend_ledger import (
    QUOTA_SPEND_LEDGER_FIXTURES,
    QUOTA_SPEND_LEDGER_LIVE_ENV,
    QuotaSpendLedger,
)
from shared.route_metadata_schema import DemandVector, build_demand_vector

if TYPE_CHECKING:
    import pytest

NOW = datetime(2026, 5, 9, 22, 30, tzinfo=UTC)


def _capability(**overrides: object) -> RouteCapabilityState:
    payload = {
        "route_id": "codex.headless.full",
        "supported": True,
        "route_state": "active",
        "blocked_reasons": (),
        "capacity_pool": "subscription_quota",
        "authority_ceiling": "authoritative",
        "privacy_posture": "provider_private",
        "eligible_quality_floors": (
            "frontier_required",
            "frontier_review_required",
            "deterministic_ok",
        ),
        "explicit_equivalence_records": (),
        "excluded_task_classes": (),
        "mutability": {
            "vault_docs": True,
            "source": True,
            "runtime": False,
            "public": False,
            "provider_spend": False,
        },
        "freshness_ok": True,
        "freshness_errors": (),
        "telemetry_quota_source": "manual",
        "telemetry_resource_source": "local_probe",
    }
    payload.update(overrides)
    return RouteCapabilityState.model_validate(payload)


def _quota(**overrides: object) -> QuotaSpendState:
    payload = {
        "available": True,
        "budget_ledger_stale": False,
        "paid_api_budget_state": None,
        "local_resource_state": "green",
        "paid_api_route_eligible": None,
        "paid_api_blocking_reasons": (),
        "paid_route_eligibility_state": None,
        "paid_route_eligibility_reasons": (),
        "evidence_refs": (),
    }
    payload.update(overrides)
    return QuotaSpendState.model_validate(payload)


def _request(**overrides: object) -> DispatchRequest:
    payload = {
        "task_id": "policy-test",
        "lane": "cx-green",
        "platform": "codex",
        "mode": "headless",
        "profile": "full",
        "route_id": "codex.headless.full",
        "task_status": "claimed",
        "assigned_to": "cx-green",
        "authority_case": "CASE-TEST-001",
        "route_metadata_status": "explicit",
        "route_metadata_hold_reasons": (),
        "route_metadata_missing_fields": (),
        "route_metadata_validation_errors": (),
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ("shared/dispatcher_policy.py",),
        "risk_flags": {
            "governance_sensitive": False,
            "privacy_or_secret_sensitive": False,
            "public_claim_sensitive": False,
            "aesthetic_theory_sensitive": False,
            "audio_or_live_egress_sensitive": False,
            "provider_billing_sensitive": False,
        },
        "context_shape": {},
        "route_constraints": {},
        "review_requirement": {},
        "capability": _capability(),
        "quota": _quota(),
        "resource_state_refs": (),
        "rollback_mode": False,
        "legacy_route_supported": True,
        "legacy_route_mutable": True,
    }
    payload.update(overrides)
    return DispatchRequest.model_validate(payload)


def _demand(**overrides: object) -> DemandVector:
    payload = {
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/dispatcher_policy.py"],
        "risk_flags": {
            "governance_sensitive": True,
            "privacy_or_secret_sensitive": False,
            "public_claim_sensitive": False,
            "aesthetic_theory_sensitive": False,
            "audio_or_live_egress_sensitive": False,
            "provider_billing_sensitive": False,
        },
        "context_shape": {
            "codebase_locality": "cross_module",
            "vault_context_required": True,
            "external_docs_required": False,
            "currentness_required": False,
        },
        "verification_surface": {
            "deterministic_tests": ["uv run pytest tests/shared/test_dispatcher_policy.py"],
            "static_checks": ["uv run ruff check shared/dispatcher_policy.py"],
            "runtime_observation": [],
            "operator_only": False,
        },
        "route_constraints": {},
        "review_requirement": {},
        "task_id": "policy-test",
        "authority_case": "CASE-TEST-001",
    }
    payload.update(overrides)
    return build_demand_vector(payload, observed_at=NOW)


def _route_with_scores(
    route_id: str, *, score: int, confidence: int = 4
) -> PlatformCapabilityRoute:
    registry = load_platform_capability_registry()
    payload = registry.require(route_id).model_dump(mode="json")
    payload["route_state"] = "active"
    payload["blocked_reasons"] = []
    payload["freshness"]["capability_checked_at"] = "2026-05-09T22:00:00Z"
    payload["freshness"]["quota_checked_at"] = "2026-05-09T22:00:00Z"
    payload["freshness"]["resource_checked_at"] = "2026-05-09T22:00:00Z"
    payload["freshness"]["provider_docs_checked_at"] = "2026-05-09T22:00:00Z"
    payload["freshness"]["evidence"] = {
        "capability": {
            "evidence_refs": [f"test:{route_id}:capability"],
            "blocked_reasons": [],
        },
        "quota": {
            "evidence_refs": [f"test:{route_id}:quota"],
            "blocked_reasons": [],
        },
        "resource": {
            "evidence_refs": [f"test:{route_id}:resource"],
            "blocked_reasons": [],
        },
        "provider_docs": {
            "evidence_refs": [f"test:{route_id}:provider_docs"],
            "blocked_reasons": [],
        },
    }
    for item in payload["capability_scores"].values():
        item["score"] = score
        item["confidence"] = confidence
        item["observed_at"] = "2026-05-09T22:00:00Z"
    for tool in payload["tool_state"]:
        tool["observed_at"] = "2026-05-09T22:00:00Z"
    return PlatformCapabilityRoute.model_validate(payload)


def _registry_with_fresh_route(route_id: str) -> PlatformCapabilityRegistry:
    registry = load_platform_capability_registry()
    if route_id in registry.route_map():
        payload = registry.model_dump(mode="json")
        route_payload = _route_with_scores(route_id, score=5).model_dump(mode="json")
        payload["routes"] = [
            route_payload if route["route_id"] == route_id else route for route in payload["routes"]
        ]
        return PlatformCapabilityRegistry.model_validate(payload)

    route = _route_with_scores("codex.headless.full", score=5).model_copy(
        update={
            "route_id": route_id,
            "launcher": f"test-only synthetic route for {route_id}",
            "summary": f"Test-only synthetic route for {route_id}",
            "notes": "Synthetic test route; production registration is covered by a later slice.",
        }
    )
    return registry.model_copy(update={"routes": [*registry.routes, route]})


def _ledger_with_route_subscription_state(route_id: str, state: str) -> QuotaSpendLedger:
    payload = json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8"))
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": f"quota-{route_id.replace('.', '-')}-{state}",
            "captured_at": "2026-05-09T22:00:00Z",
            "route_id": route_id,
            "provider": "test-subscription",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": state,
            "evidence_refs": [f"relay-receipt:{route_id}:quota:{state}"],
            "operator_visible_reason": f"test route quota {state}",
        }
    )
    return QuotaSpendLedger.model_validate(payload)


def _task_fields() -> dict[str, object]:
    payload = _demand().model_dump(mode="json")
    payload.update(
        {
            "status": "claimed",
            "assigned_to": "cx-green",
            "authority_case": "CASE-TEST-001",
        }
    )
    return payload


def _dimensional_request(
    route_id: str,
    *,
    score: int,
    confidence: int = 4,
    demand: DemandVector | None = None,
    platform: str | None = None,
    profile: str | None = None,
    capability_overrides: dict[str, object] | None = None,
) -> DispatchRequest:
    parts = route_id.split(".")
    capability_payload = {
        "route_id": route_id,
        "authority_ceiling": "authoritative",
        "eligible_quality_floors": (
            "frontier_required",
            "frontier_review_required",
            "deterministic_ok",
        ),
    }
    if capability_overrides:
        capability_payload.update(capability_overrides)
    return _request(
        route_id=route_id,
        platform=platform or parts[0],
        mode=parts[1],
        profile=profile or parts[2],
        capability=_capability(**capability_payload),
        demand_vector=demand or _demand(),
        supply_vector=build_supply_vector(
            _route_with_scores(route_id, score=score, confidence=confidence), now=NOW
        ),
    )


def test_missing_route_metadata_holds_before_launch() -> None:
    request = _request(
        route_metadata_status="hold",
        route_metadata_hold_reasons=("missing_quality_floor",),
        quality_floor=None,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.launch_allowed is False
    assert "route_metadata_missing_or_incomplete" in decision.reason_codes


def test_malformed_route_metadata_holds_before_launch() -> None:
    request = _request(
        route_metadata_status="malformed",
        route_metadata_validation_errors=("quality_floor: invalid",),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert "route_metadata_malformed" in decision.reason_codes


def test_stale_capability_data_holds() -> None:
    request = _request(
        capability=_capability(
            freshness_ok=False,
            freshness_errors=("codex.headless.full: capability stale",),
        )
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert "capability_data_stale_or_unknown" in decision.reason_codes


def test_unsupported_routes_refuse() -> None:
    request = _request(
        route_id="codex.headless.unknown",
        capability=_capability(
            route_id="codex.headless.unknown",
            supported=False,
            freshness_ok=False,
            freshness_errors=("unsupported route: codex.headless.unknown",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "unsupported_route" in decision.reason_codes


def test_read_only_mutation_route_refuses() -> None:
    request = _request(
        capability=_capability(
            authority_ceiling="read_only",
            mutability={
                "vault_docs": False,
                "source": False,
                "runtime": False,
                "public": False,
                "provider_spend": False,
            },
        )
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "read_only_mutation_route" in decision.reason_codes


def test_privacy_unknown_sensitive_route_refuses() -> None:
    risk_flags = dict(_request().risk_flags)
    risk_flags["privacy_or_secret_sensitive"] = True
    request = _request(
        risk_flags=risk_flags,
        capability=_capability(privacy_posture="unknown"),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "privacy_unknown_sensitive_route" in decision.reason_codes


def test_stale_paid_budget_ledger_refuses_paid_route() -> None:
    request = _request(
        capability=_capability(capacity_pool="bootstrap_budget"),
        quota=_quota(budget_ledger_stale=True, paid_api_budget_state="active"),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "paid_route_ledger_stale" in decision.reason_codes


def test_paid_route_without_active_budget_refuses() -> None:
    request = _request(
        capability=_capability(capacity_pool="bootstrap_budget"),
        quota=_quota(
            paid_api_budget_state="expired",
            paid_api_route_eligible=False,
            paid_route_eligibility_state="refused_expired_budget",
            paid_route_eligibility_reasons=("matching TransitionBudget expired",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "paid_route_without_active_budget" in decision.reason_codes
    assert "refused_expired_budget" in decision.reason_codes


def test_ordinary_subscription_route_still_refuses_provider_spend_mutation() -> None:
    request = _request(mutation_surface="provider_spend")

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "route_not_mutable_for_provider_spend" in decision.reason_codes


def test_ordinary_subscription_route_refuses_runtime_without_task_authority() -> None:
    request = _request(mutation_surface="runtime")

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_receipt_absent" in decision.reason_codes


def test_provider_gateway_route_requires_active_paid_budget() -> None:
    request = _request(
        platform="api",
        profile="provider_gateway",
        route_id="api.headless.provider_gateway",
        mutation_surface="provider_spend",
        capability=_capability(
            route_id="api.headless.provider_gateway",
            capacity_pool="api_paid_spend",
            paid_provider="google",
            paid_profile="frontier-fast",
            mutability={
                "vault_docs": False,
                "source": False,
                "runtime": True,
                "public": False,
                "provider_spend": True,
            },
        ),
        quota=_quota(
            paid_api_budget_state="expired",
            paid_route_eligibility_state="refused_expired_budget",
            paid_route_eligibility_reasons=("matching TransitionBudget expired",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "paid_route_without_active_budget" in decision.reason_codes
    assert "refused_expired_budget" in decision.reason_codes


def test_provider_gateway_route_launches_with_paid_budget_and_mutability() -> None:
    request = _request(
        platform="api",
        profile="provider_gateway",
        route_id="api.headless.provider_gateway",
        mutation_surface="provider_spend",
        capability=_capability(
            route_id="api.headless.provider_gateway",
            capacity_pool="api_paid_spend",
            paid_provider="google",
            paid_profile="frontier-fast",
            mutability={
                "vault_docs": False,
                "source": False,
                "runtime": True,
                "public": False,
                "provider_spend": True,
            },
        ),
        quota=_quota(
            paid_api_budget_state="active",
            paid_route_eligibility_state="eligible_active_budget",
            evidence_refs=("tb-20260510-anthropic-api-steady-state",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert "policy_launch" in decision.reason_codes


def test_provider_gateway_route_ignores_subscription_quota_when_paid_api_is_eligible() -> None:
    request = _request(
        platform="api",
        profile="provider_gateway",
        route_id="api.headless.provider_gateway",
        mutation_surface="provider_spend",
        capability=_capability(
            route_id="api.headless.provider_gateway",
            capacity_pool="api_paid_spend",
            paid_provider="anthropic",
            paid_profile="frontier-full",
            mutability={
                "vault_docs": False,
                "source": False,
                "runtime": True,
                "public": False,
                "provider_spend": True,
            },
        ),
        quota=_quota(
            paid_api_budget_state="active",
            paid_api_route_eligible=True,
            paid_api_blocking_reasons=("subscription_quota_state:exhausted",),
            paid_route_eligibility_state="eligible_active_budget",
            evidence_refs=("tb-20260510-anthropic-api-steady-state",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert "policy_launch" in decision.reason_codes
    assert "paid_route_without_active_budget" not in decision.reason_codes


def test_glmcp_subscription_route_holds_when_route_quota_unknown() -> None:
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=_capability(route_id="glmcp.review.direct"),
        quota=_quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state="unknown",
            route_quota_evidence_refs=("relay-receipt:glmcp:quota-admission:absent",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.route_policy_green is False
    assert decision.quota_freshness_green is False
    assert "subscription_route_quota_not_fresh" in decision.reason_codes
    assert "route_subscription_quota_state:unknown" in decision.reason_codes


def test_glmcp_subscription_route_launches_with_fresh_route_quota() -> None:
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=_capability(route_id="glmcp.review.direct"),
        quota=_quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state="fresh",
            route_quota_evidence_refs=("relay-receipt:glmcp-quota-admission.yaml",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert decision.quota_freshness_green is True
    assert "policy_launch" in decision.reason_codes


def test_build_dispatch_request_enforces_exact_route_subscription_quota() -> None:
    route_id = "glmcp.review.direct"
    registry = _registry_with_fresh_route(route_id)
    freshness_now = datetime(2026, 5, 9, 22, 10, tzinfo=UTC)

    missing_request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="glmcp",
        mode="review",
        profile="direct",
        task_fields=_task_fields(),
        registry=registry,
        quota_ledger=_ledger_with_route_subscription_state("codex.headless.full", "fresh"),
        now=freshness_now,
    )
    assert missing_request.quota is not None
    assert missing_request.quota.subscription_quota_state == "fresh"
    assert missing_request.quota.route_subscription_quota_state == "unknown"
    assert missing_request.quota.route_quota_evidence_refs == (
        "quota-snapshot:glmcp.review.direct:missing",
    )

    missing_decision = evaluate_dispatch_policy(missing_request, now=freshness_now)

    assert missing_decision.action is DispatchAction.HOLD
    assert "subscription_route_quota_not_fresh" in missing_decision.reason_codes
    assert "route_subscription_quota_state:unknown" in missing_decision.reason_codes

    fresh_request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="glmcp",
        mode="review",
        profile="direct",
        task_fields=_task_fields(),
        registry=registry,
        quota_ledger=_ledger_with_route_subscription_state(route_id, "fresh"),
        now=freshness_now,
    )
    assert fresh_request.quota is not None
    assert fresh_request.quota.route_subscription_quota_state == "fresh"

    fresh_decision = evaluate_dispatch_policy(fresh_request, now=freshness_now)

    assert fresh_decision.action is DispatchAction.LAUNCH
    assert fresh_decision.quota_freshness_green is True
    assert "policy_launch" in fresh_decision.reason_codes


def test_spike_workload_refuses_local_fleet_and_points_to_cloud_burst() -> None:
    request = _request(
        cloud_burst={
            "eligible": True,
            "spike_reasons": ["high_parallelism:12", "multi_agent_fanout:5"],
            "parallelism": 12,
            "agent_fanout": 5,
            "public_repo_only": True,
            "read_mostly": True,
            "no_secret_egress": True,
            "provider_budget_ref": "tb-test-cloud-burst",
        }
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "cloud_burst_spike_excludes_local_fleet" in decision.reason_codes
    assert "cloud_burst_target:api.headless.api_frontier" in decision.reason_codes
    assert decision.cloud_burst_eligible is True
    assert decision.cloud_burst_guard_state == "excluded_local"
    assert decision.local_execution_target == "appendix"


def test_non_spike_workload_launch_receipt_records_appendix_default() -> None:
    decision = evaluate_dispatch_policy(_request(), now=NOW)

    assert decision.action is DispatchAction.LAUNCH
    assert "cloud_burst_not_eligible_appendix_default" in decision.reason_codes
    assert decision.cloud_burst_guard_state == "appendix_default"
    assert decision.local_execution_target == "appendix"


def test_cloud_burst_route_requires_secret_public_read_and_budget_guards() -> None:
    request = _request(
        platform="api",
        profile="api_frontier",
        route_id="api.headless.api_frontier",
        capability=_capability(
            route_id="api.headless.api_frontier",
            capacity_pool="api_paid_spend",
        ),
        quota=_quota(
            paid_api_budget_state="active",
            paid_route_eligibility_state="eligible_active_budget",
            evidence_refs=("tb-test-cloud-burst",),
        ),
        cloud_burst={
            "eligible": True,
            "spike_reasons": ["ci_matrix"],
            "ci_matrix": True,
            "public_repo_only": False,
            "read_mostly": False,
            "no_secret_egress": True,
            "provider_budget_ref": "tb-test-cloud-burst",
        },
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "cloud_burst_public_repo_guard_failed" in decision.reason_codes
    assert "cloud_burst_read_mostly_guard_failed" in decision.reason_codes
    assert decision.cloud_burst_guard_state == "blocked"


def test_cloud_burst_route_ineligible_receipt_points_back_to_appendix() -> None:
    request = _request(
        platform="api",
        profile="api_frontier",
        route_id="api.headless.api_frontier",
        capability=_capability(
            route_id="api.headless.api_frontier",
            capacity_pool="api_paid_spend",
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "cloud_burst_not_eligible_appendix_default" in decision.reason_codes
    assert decision.cloud_burst_guard_state == "ineligible"
    assert decision.local_execution_target == "appendix"


def test_cloud_burst_route_launches_only_after_all_guards_and_budget_match() -> None:
    request = _request(
        platform="api",
        profile="api_frontier",
        route_id="api.headless.api_frontier",
        capability=_capability(
            route_id="api.headless.api_frontier",
            capacity_pool="api_paid_spend",
        ),
        quota=_quota(
            paid_api_budget_state="active",
            paid_route_eligibility_state="eligible_active_budget",
            evidence_refs=("tb-test-cloud-burst",),
        ),
        cloud_burst={
            "eligible": True,
            "spike_reasons": ["high_parallelism:12", "ci_matrix"],
            "parallelism": 12,
            "ci_matrix": True,
            "public_repo_only": True,
            "read_mostly": True,
            "no_secret_egress": True,
            "provider_budget_ref": "tb-test-cloud-burst",
        },
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.LAUNCH
    assert "cloud_burst_guard_passed" in decision.reason_codes
    assert decision.cloud_burst_guard_state == "eligible"
    assert decision.cloud_burst_spike_reasons == ("high_parallelism:12", "ci_matrix")


def test_support_artifact_without_eligible_review_refuses() -> None:
    request = _request(
        capability=_capability(authority_ceiling="frontier_review_required"),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "support_artifact_review_missing" in decision.reason_codes


def test_stale_resource_telemetry_holds() -> None:
    request = _request(
        capability=_capability(
            freshness_ok=False,
            freshness_errors=("codex.headless.full: resource stale",),
        ),
        resource_state_refs=("codex.headless.full: resource stale",),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert "resource_telemetry_stale_or_unknown" in decision.reason_codes
    assert "codex.headless.full: resource stale" in decision.resource_state_refs


def test_fallback_profile_refuses_before_quality_equivalence() -> None:
    request = _request(
        platform="codex",
        profile="spark",
        route_id="codex.headless.spark",
        capability=_capability(
            route_id="codex.headless.spark",
            authority_ceiling="authoritative",
            eligible_quality_floors=("frontier_required",),
            explicit_equivalence_records=(),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert "fallback_profile_without_equivalence_record" in decision.reason_codes


def test_review_eligible_support_route_returns_support_only() -> None:
    request = _request(
        capability=_capability(authority_ceiling="frontier_review_required"),
        review_requirement={
            "support_artifact_allowed": True,
            "independent_review_required": True,
            "authoritative_acceptor_profile": "frontier_full",
        },
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.SUPPORT_ONLY
    assert decision.launch_allowed is False
    assert "support_artifact_requires_independent_review" in decision.reason_codes


def test_writes_route_decision_jsonl_receipt(tmp_path: Path) -> None:
    decision = evaluate_dispatch_policy(_request(), now=NOW)

    assert decision.route_policy_green is True
    assert decision.clog_state is ClogRouteState.POLICY_GREEN
    assert decision.compatibility_mode == "none"

    path = write_route_decision_receipt(decision, ledger_dir=tmp_path)

    line = path.read_text(encoding="utf-8").splitlines()[-1]
    assert '"action": "launch"' in line
    assert '"dimensional_route_receipt_schema": 1' in line
    assert '"route_policy_green": true' in line
    assert '"clog_state": "policy_green"' in line
    assert decision.decision_id in line


def test_dimensional_policy_holds_lower_scoring_requested_route() -> None:
    primary = _dimensional_request("codex.headless.full", score=3)
    better = _dimensional_request("claude.headless.full", score=5)

    decision = evaluate_dispatch_policy(
        primary,
        candidate_requests=(primary, better),
        now=NOW,
    )

    assert decision.action is DispatchAction.HOLD
    assert "requested_route_dominated_by_higher_scoring_candidate" in decision.reason_codes
    assert decision.dimensional_receipt is not None
    assert decision.dimensional_receipt.selected_route_id == "claude.headless.full"


def test_dimensional_policy_holds_ties_without_degraded_authority() -> None:
    primary = _dimensional_request("codex.headless.full", score=4)
    tied = _dimensional_request("claude.headless.full", score=4)

    decision = evaluate_dispatch_policy(primary, candidate_requests=(primary, tied), now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert "dimensional_candidate_tie_hold" in decision.reason_codes


def test_dimensional_policy_allows_degraded_authority_tie_break() -> None:
    primary = _dimensional_request("codex.headless.full", score=4).model_copy(
        update={"degraded_mode_authority_ref": "operator:explicit-tie-break"}
    )
    tied = _dimensional_request("claude.headless.full", score=4)

    decision = evaluate_dispatch_policy(primary, candidate_requests=(primary, tied), now=NOW)

    assert decision.action is DispatchAction.LAUNCH
    assert "degraded_mode_authorized_dimensional_tie_break" in decision.reason_codes
    assert decision.dimensional_receipt is not None
    assert decision.dimensional_receipt.degraded_mode is True


def test_dimensional_policy_holds_incomparable_low_confidence_candidate() -> None:
    primary = _dimensional_request("codex.headless.full", score=5, confidence=1)

    decision = evaluate_dispatch_policy(primary, candidate_requests=(primary,), now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert "dimensional_candidates_incomparable_hold" in decision.reason_codes


def test_dimensional_policy_vetoes_missing_required_tool() -> None:
    demand = _demand(
        required_tools=[{"tool_id": "android_device", "required": True, "authority_use": "execute"}]
    )
    primary = _dimensional_request("codex.headless.full", score=5, demand=demand)

    decision = evaluate_dispatch_policy(primary, candidate_requests=(primary,), now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.dimensional_receipt is not None
    [candidate] = decision.dimensional_receipt.candidates
    assert any(veto.code == "required_tool_unavailable" for veto in candidate.vetoes)


def test_policy_rollback_is_retired_and_requires_signed_route_receipts() -> None:
    request = _request(rollback_mode=True)

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.launch_allowed is False
    assert decision.route_policy_green is False
    assert decision.clog_state is ClogRouteState.HELD
    assert decision.compatibility_mode == "none"
    assert decision.degraded_state is None
    assert decision.route_selection_authority is False
    assert "policy_rollback_retired" in decision.reason_codes
    assert "signed_route_authority_receipt_required" in decision.reason_codes


def test_policy_rollback_retirement_does_not_fall_back_to_legacy_route_checks() -> None:
    request = _request(
        rollback_mode=True,
        legacy_route_supported=False,
        legacy_route_mutable=False,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.route_policy_green is False
    assert decision.clog_state is ClogRouteState.HELD
    assert decision.reason_codes == (
        "policy_rollback_retired",
        "signed_route_authority_receipt_required",
    )


def test_policy_sources_prefer_live_quota_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "quota-spend-ledger-live.json"
    payload = json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8"))
    payload["ledger_id"] = "quota-spend-ledger-live-policy-test"
    payload["captured_at"] = "2026-06-10T00:00:00Z"
    live.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv(QUOTA_SPEND_LEDGER_LIVE_ENV, str(live))

    sources = load_dispatch_policy_sources()

    assert sources.quota_ledger is not None
    assert sources.quota_ledger.ledger_id == "quota-spend-ledger-live-policy-test"
    assert sources.quota_ledger_source == "live"
    assert sources.quota_live_error is None


def test_policy_sources_fall_back_to_fixtures_without_live_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(QUOTA_SPEND_LEDGER_LIVE_ENV, str(tmp_path / "absent.json"))

    sources = load_dispatch_policy_sources()

    assert sources.quota_ledger is not None
    assert sources.quota_ledger_source == "fixtures"
    assert sources.quota_live_error is None


def test_policy_sources_flag_invalid_live_ledger_on_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "quota-spend-ledger-live.json"
    live.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(QUOTA_SPEND_LEDGER_LIVE_ENV, str(live))

    sources = load_dispatch_policy_sources()

    assert sources.quota_ledger is not None
    assert sources.quota_ledger_source == "fixtures"
    assert sources.quota_live_error is not None
    assert "invalid quota/spend ledger" in sources.quota_live_error


def test_policy_sources_explicit_path_bypasses_live_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "quota-spend-ledger-live.json"
    payload = json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8"))
    payload["ledger_id"] = "quota-spend-ledger-live-ignored"
    live.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv(QUOTA_SPEND_LEDGER_LIVE_ENV, str(live))

    sources = load_dispatch_policy_sources(quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES)

    assert sources.quota_ledger is not None
    assert sources.quota_ledger.ledger_id != "quota-spend-ledger-live-ignored"
    assert sources.quota_ledger_source == "explicit"
