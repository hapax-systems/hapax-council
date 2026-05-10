"""Tests for the S5-4 fail-closed dispatcher policy evaluator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shared.dispatcher_policy import (
    DispatchAction,
    DispatchRequest,
    QuotaSpendState,
    RouteCapabilityState,
    evaluate_dispatch_policy,
    write_route_decision_receipt,
)

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

    path = write_route_decision_receipt(decision, ledger_dir=tmp_path)

    line = path.read_text(encoding="utf-8").splitlines()[-1]
    assert '"action": "launch"' in line
    assert decision.decision_id in line
