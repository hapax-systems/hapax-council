"""Tests for the S5-4 fail-closed dispatcher policy evaluator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shared.dispatcher_policy import (
    ClogRouteState,
    DispatchAction,
    DispatchRequest,
    QuotaSpendState,
    RouteCapabilityState,
    evaluate_dispatch_policy,
    write_route_decision_receipt,
)
from shared.platform_capability_registry import (
    PlatformCapabilityRoute,
    build_supply_vector,
    load_platform_capability_registry,
)
from shared.route_metadata_schema import DemandVector, build_demand_vector

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
    for item in payload["capability_scores"].values():
        item["score"] = score
        item["confidence"] = confidence
        item["observed_at"] = "2026-05-09T22:00:00Z"
    for tool in payload["tool_state"]:
        tool["observed_at"] = "2026-05-09T22:00:00Z"
    return PlatformCapabilityRoute.model_validate(payload)


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


def test_policy_rollback_launch_is_compatibility_degraded_not_green() -> None:
    request = _request(rollback_mode=True)

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.launch_allowed is True
    assert decision.route_policy_green is False
    assert decision.clog_state is ClogRouteState.COMPATIBILITY_DEGRADED
    assert decision.compatibility_mode == "rollback_full_profile"
    assert decision.degraded_state == "compatibility_rollback"
    assert decision.registry_freshness_green is False
    assert decision.quota_freshness_green is False
    assert decision.resource_freshness_green is False
    assert decision.route_selection_authority is False
    assert "rollback_full_profile_launch" in decision.reason_codes


def test_policy_rollback_refuses_unsupported_routes() -> None:
    request = _request(
        rollback_mode=True,
        legacy_route_supported=False,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert decision.route_policy_green is False
    assert decision.clog_state is ClogRouteState.REFUSED
    assert "rollback_unsupported_route_refused" in decision.reason_codes


def test_policy_rollback_refuses_read_only_mutation_route() -> None:
    request = _request(
        rollback_mode=True,
        legacy_route_mutable=False,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert decision.route_policy_green is False
    assert decision.clog_state is ClogRouteState.REFUSED
    assert "rollback_read_only_mutation_refused" in decision.reason_codes
