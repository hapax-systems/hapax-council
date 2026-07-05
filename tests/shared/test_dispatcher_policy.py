"""Tests for the S5-4 fail-closed dispatcher policy evaluator."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import shared.dispatcher_policy as dispatcher_policy
from shared.dispatcher_policy import (
    LOCAL_DEV_PLATFORMS,
    ClogRouteState,
    DispatchAction,
    DispatchRequest,
    QuotaSpendState,
    RouteCapabilityState,
    build_dispatch_request,
    build_route_authority_receipt,
    evaluate_dispatch_policy,
    load_dispatch_policy_sources,
    write_route_authority_receipt,
    write_route_decision_receipt,
)
from shared.platform_capability_registry import (
    CapacityPool,
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
from shared.route_metadata_schema import DemandVector, RouteEnvelope, build_demand_vector


@pytest.fixture(autouse=True)
def _enforce_route_envelope_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin these policy units to the route-envelope gate's ENFORCE behaviour.

    The gate ships in SHADOW mode by default (``HAPAX_ROUTE_ENVELOPE_GATE`` unset); these
    units exercise its full fail-closed (enforce) logic. The SHADOW rollout default is
    covered end-to-end in tests/scripts/test_hapax_methodology_dispatch.py.
    """
    monkeypatch.setenv("HAPAX_ROUTE_ENVELOPE_GATE", "enforce")


NOW = datetime(2026, 5, 9, 22, 30, tzinfo=UTC)
GLMCP_ADMISSION_EVIDENCE_REF = (
    "relay-receipt:glmcp-quota-admission.yaml:"
    "witness:supported-tool-usage-witness:"
    "supported_tool:hapax-glmcp-reviewer:"
    "endpoint:https://api.z.ai/api/coding/paas/v4:"
    "model:glm-5:"
    "observed_at:2026-05-09T22:00:00Z:"
    "fresh_until:2026-05-09T23:00:00Z"
)


def test_antigrav_is_not_a_local_dev_platform() -> None:
    assert "antigrav" not in LOCAL_DEV_PLATFORMS


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
    if "demand_vector" not in overrides and payload.get("route_metadata_status") == "explicit":
        payload["demand_vector"] = _demand()
    return DispatchRequest.model_validate(payload)


def _route_envelope(*, admission_action: str = "route") -> dict[str, object]:
    return {
        "classification_envelope": {
            "label": "source_python",
            "classifier": "test.deterministic",
            "source_kind": "deterministic",
            "confidence": 0.92,
            "evidence_refs": ["test:classification-evidence"],
            "freshness": "fresh",
            "authority_ceiling": "authoritative",
            "validity_mask": {
                "label": True,
                "source": True,
                "confidence": True,
                "freshness": True,
                "authority_ceiling": True,
            },
            "deterministic_facts_used": ["mutation_surface:source"],
            "consumer_floor": "frontier_required",
        },
        "eligibility": {
            "authority_allowed": True,
            "privacy_allowed": True,
            "freshness_ok": True,
            "quality_floor_satisfied": True,
            "required_tools_available": True,
            "budget_allowed": True,
            "reason_codes": ["eligibility_witnessed"],
        },
        "admission": {
            "admission_action": admission_action,
            "reason_codes": [f"route_envelope_{admission_action}"],
        },
    }


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
        "route_envelope": _route_envelope(),
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


def _ledger_with_route_subscription_state(
    route_id: str,
    state: str,
    *,
    fresh_until: str | None = None,
    ledger_captured_at: str | None = None,
) -> QuotaSpendLedger:
    payload = json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8"))
    if ledger_captured_at is not None:
        payload["captured_at"] = ledger_captured_at
    evidence_refs = [f"relay-receipt:{route_id}:quota:{state}"]
    if route_id == "glmcp.review.direct" and state == "fresh":
        evidence_refs = [GLMCP_ADMISSION_EVIDENCE_REF]
        payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    snapshot = {
        "quota_snapshot_schema": 1,
        "snapshot_id": f"quota-{route_id.replace('.', '-')}-{state}",
        "captured_at": "2026-05-09T22:00:00Z",
        "route_id": route_id,
        "provider": "test-subscription",
        "capacity_pool": "subscription_quota",
        "subscription_quota_state": state,
        "evidence_refs": evidence_refs,
        "operator_visible_reason": f"test route quota {state}",
    }
    if route_id == "glmcp.review.direct" and state == "fresh":
        snapshot["provider"] = "z_ai-glm-coding-plan"
    if fresh_until is not None:
        snapshot["fresh_until"] = fresh_until
    payload["quota_snapshots"].append(snapshot)
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


def _move_route_metadata_under_nested_key(task_fields: dict[str, object]) -> None:
    route_metadata_keys = (
        "route_metadata_schema",
        "route_envelope",
        "quality_floor",
        "authority_level",
        "mutation_surface",
        "mutation_scope_refs",
        "risk_flags",
        "context_shape",
        "verification_surface",
        "route_constraints",
        "review_requirement",
        "cloud_burst",
    )
    task_fields["route_metadata"] = {
        key: task_fields.pop(key) for key in route_metadata_keys if key in task_fields
    }


def _review_task_fields() -> dict[str, object]:
    # A review-seat task: non-mutating, support-non-authoritative — the work a
    # read-only ReviewSeatAdapter (glmcp.review.direct) actually does. Used to
    # exercise the receipt-bounded subscription-quota gate on the review seat; the
    # authoritative coding-workhorse quota path is a separate, bakeoff-gated route.
    payload = _task_fields()
    payload.update(
        {
            "quality_floor": "frontier_review_required",
            "authority_level": "support_non_authoritative",
            "mutation_surface": "none",
            "mutation_scope_refs": [],
            "review_requirement": {
                "support_artifact_allowed": True,
                "independent_review_required": True,
                "authoritative_acceptor_profile": "operator",
            },
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


def test_route_envelope_hold_blocks_dispatch_launch() -> None:
    demand = _demand().model_copy(
        update={
            "route_envelope": RouteEnvelope.model_validate(
                {
                    "admission": {
                        "admission_action": "hold",
                        "reason_codes": ["route_envelope_missing"],
                    }
                }
            )
        }
    )
    request = _request(
        demand_vector=demand,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.launch_allowed is False
    assert "route_envelope_admission_hold" in decision.reason_codes
    assert "route_envelope_missing" in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


def test_missing_demand_vector_blocks_dispatch_launch() -> None:
    request = _request(demand_vector=None)

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.launch_allowed is False
    assert "missing_demand_vector" in decision.reason_codes
    assert "route_envelope_missing" in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


def test_build_dispatch_request_missing_route_envelope_holds_before_launch() -> None:
    task_fields = _task_fields()
    task_fields.pop("route_envelope", None)
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=_registry_with_fresh_route("codex.headless.full"),
        now=NOW,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert request.demand_vector is None
    assert decision.action is DispatchAction.HOLD
    assert "missing_demand_vector" in decision.reason_codes
    assert "route_envelope_missing" in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


def test_build_dispatch_request_preserves_explicit_route_envelope_hold_reasons() -> None:
    task_fields = _task_fields()
    task_fields["route_envelope"] = _route_envelope(admission_action="hold")
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=_registry_with_fresh_route("codex.headless.full"),
        now=NOW,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert request.demand_vector is not None
    assert decision.action is DispatchAction.HOLD
    assert decision.launch_allowed is False
    assert "route_envelope_admission_hold" in decision.reason_codes
    assert "route_envelope_hold" in decision.reason_codes
    assert "missing_demand_vector" not in decision.reason_codes
    assert "route_envelope_missing" not in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


def test_build_dispatch_request_preserves_nested_route_envelope_hold_reasons() -> None:
    task_fields = _task_fields()
    task_fields["route_envelope"] = _route_envelope(admission_action="hold")
    _move_route_metadata_under_nested_key(task_fields)
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=_registry_with_fresh_route("codex.headless.full"),
        now=NOW,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert request.demand_vector is not None
    assert decision.action is DispatchAction.HOLD
    assert decision.launch_allowed is False
    assert "route_envelope_admission_hold" in decision.reason_codes
    assert "route_envelope_hold" in decision.reason_codes
    assert "missing_demand_vector" not in decision.reason_codes
    assert "route_envelope_missing" not in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


def test_build_dispatch_request_invalid_demand_vector_holds_before_launch() -> None:
    task_fields = _task_fields()
    task_demand = dict(task_fields["task_demand"])  # type: ignore[index]
    task_demand["fixed_route_overhead_sensitivity"] = 999
    task_fields["task_demand"] = task_demand
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=_registry_with_fresh_route("codex.headless.full"),
        now=NOW,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert request.demand_vector is None
    assert decision.action is DispatchAction.HOLD
    assert "missing_demand_vector" in decision.reason_codes
    assert "route_envelope_missing" in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


def test_operator_coupled_headless_refuses_before_capability_lookup() -> None:
    request = _request(
        operator_coupled=True,
        operator_coupled_evidence_refs=("operator_coupled:frontmatter",),
        capability=None,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert decision.launch_allowed is False
    assert "operator_coupled_interactive_only" in decision.reason_codes
    assert "interactive_path:hapax-claude --terminal tmux" in decision.reason_codes
    assert "operator_coupled:frontmatter" in decision.reason_codes
    assert "capability_registry_unavailable" not in decision.reason_codes


def test_build_dispatch_request_refuses_path_derived_operator_coupled_headless() -> None:
    task_fields = _task_fields()
    task_fields["__operator_coupled_path_matches"] = [
        "agents/studio_compositor/programme.py#operator-coupled-broadcast-visual"
    ]
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=_registry_with_fresh_route("codex.headless.full"),
        now=NOW,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert request.operator_coupled is True
    assert request.operator_coupled_evidence_refs == (
        "operator_coupled:path:agents/studio_compositor/programme.py"
        "#operator-coupled-broadcast-visual",
    )
    assert decision.action is DispatchAction.REFUSE
    assert "operator_coupled_interactive_only" in decision.reason_codes


def test_build_dispatch_request_refuses_dispatch_mode_interactive_only_headless() -> None:
    task_fields = _task_fields()
    task_fields["dispatch_mode"] = "interactive_only"
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=_registry_with_fresh_route("codex.headless.full"),
        now=NOW,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert request.operator_coupled is True
    assert request.operator_coupled_evidence_refs == ("operator_coupled:dispatch_mode",)
    assert decision.action is DispatchAction.REFUSE
    assert "operator_coupled_interactive_only" in decision.reason_codes
    assert "operator_coupled:dispatch_mode" in decision.reason_codes


def test_build_dispatch_request_without_operator_evidence_is_not_operator_coupled() -> None:
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=_registry_with_fresh_route("codex.headless.full"),
        now=NOW,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert request.operator_coupled is False
    assert request.operator_coupled_evidence_refs == ()
    assert "operator_coupled_interactive_only" not in decision.reason_codes
    assert all(not reason.startswith("operator_coupled:path:") for reason in decision.reason_codes)


def test_candidate_set_cannot_bypass_primary_missing_route_envelope() -> None:
    task_fields = _task_fields()
    task_fields.pop("route_envelope", None)
    primary = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=_registry_with_fresh_route("codex.headless.full"),
        now=NOW,
    )
    same_route_candidate = _dimensional_request("codex.headless.full", score=5)

    decision = evaluate_dispatch_policy(
        primary,
        candidate_requests=(same_route_candidate,),
        now=NOW,
    )

    assert primary.demand_vector is None
    assert same_route_candidate.demand_vector is not None
    assert decision.action is DispatchAction.HOLD
    assert decision.launch_allowed is False
    assert "missing_demand_vector" in decision.reason_codes
    assert "route_envelope_missing" in decision.reason_codes
    assert "dimensional_unique_dominant_route" not in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


def test_candidate_set_cannot_bypass_primary_route_envelope_hold() -> None:
    # Regression guard: candidate-set evaluation used to run before the primary
    # route-envelope hold, allowing an alternate route to bypass admission.
    task_fields = _task_fields()
    task_fields["route_envelope"] = _route_envelope(admission_action="hold")
    primary = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=_registry_with_fresh_route("codex.headless.full"),
        now=NOW,
    )
    alternative = _dimensional_request("claude.headless.full", score=5)

    decision = evaluate_dispatch_policy(
        primary,
        candidate_requests=(alternative,),
        now=NOW,
    )

    assert primary.demand_vector is not None
    assert alternative.demand_vector is not None
    assert decision.action is DispatchAction.HOLD
    assert decision.launch_allowed is False
    assert "route_envelope_admission_hold" in decision.reason_codes
    assert "route_envelope_hold" in decision.reason_codes
    assert "dimensional_unique_dominant_route" not in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes
    assert decision.dimensional_receipt is not None
    assert [candidate.route_id for candidate in decision.dimensional_receipt.candidates] == [
        "codex.headless.full"
    ]


def test_candidate_set_keeps_primary_for_same_route_candidate() -> None:
    # Regression guard: same-route candidates used to overwrite the primary
    # request in candidate-set deduplication.
    primary = _dimensional_request("codex.headless.full", score=3)
    same_route_candidate = _dimensional_request("codex.headless.full", score=5)
    primary_only = evaluate_dispatch_policy(primary, candidate_requests=(), now=NOW)

    decision = evaluate_dispatch_policy(
        primary,
        candidate_requests=(same_route_candidate,),
        now=NOW,
    )

    assert decision.action is DispatchAction.LAUNCH
    assert "dimensional_unique_dominant_route" in decision.reason_codes
    assert decision.dimensional_receipt is not None
    assert decision.dimensional_receipt.selected_route_id == "codex.headless.full"
    assert len(decision.dimensional_receipt.candidates) == 1
    receipt = decision.dimensional_receipt.candidates[0]
    assert receipt.route_id == "codex.headless.full"
    assert receipt.aggregate_score is not None
    assert primary_only.dimensional_receipt is not None
    assert receipt.aggregate_score == primary_only.dimensional_receipt.candidates[0].aggregate_score


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


def test_pending_capability_surface_delta_holds_even_with_fresh_legacy_telemetry() -> None:
    blocker = "capability_surface_delta:delta_pending:route.codex.headless.full"
    request = _request(
        route_id="codex.headless.full",
        capability=_capability(
            route_id="codex.headless.full",
            freshness_ok=True,
            freshness_errors=(),
            surface_delta_refs=("cap-surface-delta:20260701T030000Z",),
            surface_delta_blockers=(blocker,),
        ),
        quota=_quota(route_subscription_quota_state="fresh"),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.registry_freshness_green is False
    assert decision.quota_freshness_green is False
    assert decision.resource_freshness_green is False
    assert "capability_surface_delta_pending" in decision.reason_codes
    assert blocker in decision.reason_codes


def test_build_dispatch_request_populates_surface_delta_blockers_from_policy_sources(
    tmp_path: Path,
) -> None:
    surface_delta_path = tmp_path / "capability-surface-deltas.json"
    surface_delta_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixture_set_id": "policy-source-delta-test",
                "schema_ref": "schemas/capability-surface-delta.schema.json",
                "generated_from": ["unit-test"],
                "declared_at": "2026-05-09T22:00:00Z",
                "descriptors": [
                    {
                        "descriptor_schema": 1,
                        "surface_id": "route.codex.headless.full",
                        "descriptor_ref": "platform-capability-registry:codex.headless.full",
                        "surface_kind": "review_seat",
                        "authority_ceiling": "read_only",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "stale_after": "1h",
                        "evidence_refs": ["test:descriptor"],
                        "route_id": "codex.headless.full",
                        "resource_pools": ["subscription_quota"],
                    }
                ],
                "deltas": [
                    {
                        "delta_schema": 1,
                        "delta_id": "test:pending-codex-delta",
                        "source": "unit-test",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "detected_by": "unit-test",
                        "surface_id": "route.codex.headless.full",
                        "delta_kind": "stale_determination",
                        "prior_descriptor_ref": "platform-capability-registry:codex.headless.full",
                        "observed_descriptor_ref": "platform-capability-receipt:codex:current-expired",
                        "evidence_refs": ["test:expired-codex-receipt"],
                        "authority_ceiling": "read_only",
                        "affected_resource_pools": ["subscription_quota"],
                        "privacy_sensitive": True,
                        "public_egress": False,
                        "money_rail": False,
                        "freshness_state": "stale",
                        "required_intake_action": "refresh_receipt",
                        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
                        "summary": "test stale codex determination",
                    },
                    {
                        "delta_schema": 1,
                        "delta_id": "test:new-openrouter",
                        "source": "unit-test",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "detected_by": "unit-test",
                        "surface_id": "route.openrouter.test",
                        "delta_kind": "new_capability",
                        "prior_descriptor_ref": None,
                        "observed_descriptor_ref": "provider-catalog:openrouter:test",
                        "evidence_refs": ["test:openrouter"],
                        "authority_ceiling": "frontier_review_required",
                        "affected_resource_pools": ["api_paid_spend"],
                        "privacy_sensitive": True,
                        "public_egress": False,
                        "money_rail": True,
                        "freshness_state": "delta_pending",
                        "required_intake_action": "mint_intake_item",
                        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
                        "summary": "test new capability",
                    },
                    {
                        "delta_schema": 1,
                        "delta_id": "test:authority-change-publication",
                        "source": "unit-test",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "detected_by": "unit-test",
                        "surface_id": "surface.publication_bus.weblog",
                        "delta_kind": "authority_changed",
                        "prior_descriptor_ref": "publication-bus:weblog:read-only",
                        "observed_descriptor_ref": "publication-bus:weblog:publish-capable",
                        "evidence_refs": ["test:publication"],
                        "authority_ceiling": "frontier_review_required",
                        "affected_resource_pools": ["public_egress"],
                        "privacy_sensitive": True,
                        "public_egress": True,
                        "money_rail": False,
                        "freshness_state": "delta_pending",
                        "required_intake_action": "update_descriptor",
                        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
                        "summary": "test authority change",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    sources = load_dispatch_policy_sources(
        registry_path=None,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        surface_delta_path=surface_delta_path,
        now=NOW,
    )

    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=_registry_with_fresh_route("codex.headless.full"),
        quota_ledger=sources.quota_ledger,
        surface_delta_refs_by_route=sources.surface_delta_refs_by_route,
        surface_delta_blockers_by_route=sources.surface_delta_blockers_by_route,
        now=NOW,
    )

    assert request.capability is not None
    assert request.capability.surface_delta_refs
    assert request.capability.surface_delta_blockers
    decision = evaluate_dispatch_policy(request, now=NOW)
    assert decision.action is DispatchAction.HOLD
    assert "capability_surface_delta_pending" in decision.reason_codes
    assert any("test:pending-codex-delta" in reason for reason in decision.reason_codes)


def test_malformed_surface_delta_policy_source_fails_closed_for_routes(
    tmp_path: Path,
) -> None:
    surface_delta_path = tmp_path / "malformed-surface-deltas.json"
    surface_delta_path.write_text("{not json", encoding="utf-8")

    sources = load_dispatch_policy_sources(
        registry_path=None,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        surface_delta_path=surface_delta_path,
        now=NOW,
    )
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=_registry_with_fresh_route("codex.headless.full"),
        quota_ledger=sources.quota_ledger,
        surface_delta_refs_by_route=sources.surface_delta_refs_by_route,
        surface_delta_blockers_by_route=sources.surface_delta_blockers_by_route,
        now=NOW,
    )

    assert request.capability is not None
    assert request.capability.surface_delta_blockers
    decision = evaluate_dispatch_policy(request, now=NOW)
    assert decision.action is DispatchAction.HOLD
    assert "capability_surface_delta_pending" in decision.reason_codes
    assert any("producer_file" in reason for reason in decision.reason_codes)


def test_surface_delta_policy_source_indexes_descriptor_route_ids(
    tmp_path: Path,
) -> None:
    surface_delta_path = tmp_path / "capability-surface-deltas.json"
    surface_delta_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "schema_ref": "schemas/capability-surface-delta.schema.json",
                "generated_from": ["unit-test"],
                "declared_at": "2026-05-09T22:00:00Z",
                "descriptors": [
                    {
                        "descriptor_schema": 1,
                        "surface_id": "surface.codex.cluster",
                        "descriptor_ref": "platform-capability-registry:codex.headless.full",
                        "surface_kind": "model_route",
                        "authority_ceiling": "authoritative",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "stale_after": "1h",
                        "evidence_refs": ["platform-capability-receipt:codex:expired"],
                        "route_id": "codex.headless.full",
                        "resource_pools": ["subscription_quota"],
                    }
                ],
                "deltas": [
                    {
                        "delta_schema": 1,
                        "delta_id": "test:descriptor-route-id-stale",
                        "source": "unit-test",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "detected_by": "unit-test",
                        "surface_id": "surface.codex.receipt-check",
                        "delta_kind": "stale_determination",
                        "prior_descriptor_ref": "legacy-descriptor:codex-cluster",
                        "observed_descriptor_ref": "platform-capability-receipt:codex:expired",
                        "evidence_refs": ["test:expired-codex-receipt"],
                        "authority_ceiling": "authoritative",
                        "affected_resource_pools": ["subscription_quota"],
                        "privacy_sensitive": True,
                        "public_egress": False,
                        "money_rail": False,
                        "freshness_state": "stale",
                        "required_intake_action": "refresh_receipt",
                        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
                        "summary": "descriptor carries the dispatch route id",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sources = load_dispatch_policy_sources(
        registry_path=None,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        surface_delta_path=surface_delta_path,
        now=NOW,
    )
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=_registry_with_fresh_route("codex.headless.full"),
        quota_ledger=sources.quota_ledger,
        surface_delta_refs_by_route=sources.surface_delta_refs_by_route,
        surface_delta_blockers_by_route=sources.surface_delta_blockers_by_route,
        now=NOW,
    )

    assert request.capability is not None
    assert any(
        "test:descriptor-route-id-stale" in blocker
        for blocker in request.capability.surface_delta_blockers
    )
    decision = evaluate_dispatch_policy(request, now=NOW)
    assert decision.action is DispatchAction.HOLD
    assert "capability_surface_delta_pending" in decision.reason_codes


def test_unjoined_blocking_surface_delta_fails_closed_globally(
    tmp_path: Path,
) -> None:
    surface_delta_path = tmp_path / "capability-surface-deltas.json"
    surface_delta_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "schema_ref": "schemas/capability-surface-delta.schema.json",
                "generated_from": ["unit-test"],
                "declared_at": "2026-05-09T22:00:00Z",
                "descriptors": [
                    {
                        "descriptor_schema": 1,
                        "surface_id": "surface.unrelated.cluster",
                        "descriptor_ref": "platform-capability-registry:unrelated",
                        "surface_kind": "model_route",
                        "authority_ceiling": "authoritative",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "stale_after": "1h",
                        "evidence_refs": ["test:unrelated-descriptor"],
                        "route_id": "unrelated.headless.full",
                        "resource_pools": ["subscription_quota"],
                    }
                ],
                "deltas": [
                    {
                        "delta_schema": 1,
                        "delta_id": "test:unjoined-stale-surface",
                        "source": "unit-test",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "detected_by": "unit-test",
                        "surface_id": "surface.dark.receipt-check",
                        "delta_kind": "stale_determination",
                        "prior_descriptor_ref": "receipt:dark:previous",
                        "observed_descriptor_ref": "receipt:dark:expired",
                        "evidence_refs": ["receipt:dark:expired"],
                        "authority_ceiling": "authoritative",
                        "affected_resource_pools": ["subscription_quota"],
                        "privacy_sensitive": True,
                        "public_egress": False,
                        "money_rail": False,
                        "freshness_state": "stale",
                        "required_intake_action": "refresh_receipt",
                        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
                        "summary": "blocking delta cannot be joined to a route",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sources = load_dispatch_policy_sources(
        registry_path=None,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        surface_delta_path=surface_delta_path,
        now=NOW,
    )
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=_registry_with_fresh_route("codex.headless.full"),
        quota_ledger=sources.quota_ledger,
        surface_delta_refs_by_route=sources.surface_delta_refs_by_route,
        surface_delta_blockers_by_route=sources.surface_delta_blockers_by_route,
        now=NOW,
    )

    assert request.capability is not None
    assert any(
        "test:unjoined-stale-surface" in blocker
        for blocker in request.capability.surface_delta_blockers
    )
    decision = evaluate_dispatch_policy(request, now=NOW)
    assert decision.action is DispatchAction.HOLD
    assert "capability_surface_delta_pending" in decision.reason_codes


def test_plain_descriptor_ref_without_route_id_fails_closed_globally(
    tmp_path: Path,
) -> None:
    surface_delta_path = tmp_path / "capability-surface-deltas.json"
    surface_delta_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "schema_ref": "schemas/capability-surface-delta.schema.json",
                "generated_from": ["unit-test"],
                "declared_at": "2026-05-09T22:00:00Z",
                "descriptors": [
                    {
                        "descriptor_schema": 1,
                        "surface_id": "surface.publication_bus.weblog",
                        "descriptor_ref": "publication-bus-weblog",
                        "surface_kind": "publication_bus",
                        "authority_ceiling": "frontier_review_required",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "stale_after": "1h",
                        "evidence_refs": ["publication-bus-weblog-receipt"],
                        "route_id": None,
                        "resource_pools": ["public_egress"],
                    }
                ],
                "deltas": [
                    {
                        "delta_schema": 1,
                        "delta_id": "test:plain-ref-publication-stale",
                        "source": "unit-test",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "detected_by": "unit-test",
                        "surface_id": "surface.publication_bus.weblog",
                        "delta_kind": "stale_determination",
                        "prior_descriptor_ref": "publication-bus-weblog",
                        "observed_descriptor_ref": "publication-bus-weblog-receipt",
                        "evidence_refs": ["publication-bus-weblog-receipt"],
                        "authority_ceiling": "frontier_review_required",
                        "affected_resource_pools": ["public_egress"],
                        "privacy_sensitive": True,
                        "public_egress": True,
                        "money_rail": False,
                        "freshness_state": "stale",
                        "required_intake_action": "refresh_receipt",
                        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
                        "summary": "plain non-route descriptor ref cannot satisfy dispatch routing",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sources = load_dispatch_policy_sources(
        registry_path=None,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        surface_delta_path=surface_delta_path,
        now=NOW,
    )
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=_registry_with_fresh_route("codex.headless.full"),
        quota_ledger=sources.quota_ledger,
        surface_delta_refs_by_route=sources.surface_delta_refs_by_route,
        surface_delta_blockers_by_route=sources.surface_delta_blockers_by_route,
        now=NOW,
    )

    assert request.capability is not None
    assert any(
        "test:plain-ref-publication-stale" in blocker
        for blocker in request.capability.surface_delta_blockers
    )
    decision = evaluate_dispatch_policy(request, now=NOW)
    assert decision.action is DispatchAction.HOLD
    assert "capability_surface_delta_pending" in decision.reason_codes


def test_unknown_producer_route_id_fails_closed_globally(
    tmp_path: Path,
) -> None:
    surface_delta_path = tmp_path / "capability-surface-deltas.json"
    surface_delta_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "schema_ref": "schemas/capability-surface-delta.schema.json",
                "generated_from": ["unit-test"],
                "declared_at": "2026-05-09T22:00:00Z",
                "descriptors": [
                    {
                        "descriptor_schema": 1,
                        "surface_id": "surface.codex.cluster",
                        "descriptor_ref": "platform-capability-registry:codex.headless.typo",
                        "surface_kind": "model_route",
                        "authority_ceiling": "authoritative",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "stale_after": "1h",
                        "evidence_refs": ["receipt:codex-typo"],
                        "route_id": "codex.headless.ful",
                        "resource_pools": ["subscription_quota"],
                    }
                ],
                "deltas": [
                    {
                        "delta_schema": 1,
                        "delta_id": "test:unknown-route-stale",
                        "source": "unit-test",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "detected_by": "unit-test",
                        "surface_id": "surface.codex.receipt-check",
                        "delta_kind": "stale_determination",
                        "prior_descriptor_ref": "receipt:codex-typo:previous",
                        "observed_descriptor_ref": "receipt:codex-typo:expired",
                        "evidence_refs": ["receipt:codex-typo"],
                        "authority_ceiling": "authoritative",
                        "affected_resource_pools": ["subscription_quota"],
                        "privacy_sensitive": True,
                        "public_egress": False,
                        "money_rail": False,
                        "freshness_state": "stale",
                        "required_intake_action": "refresh_receipt",
                        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
                        "summary": "producer descriptor names an unknown dispatch route",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sources = load_dispatch_policy_sources(
        registry_path=None,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        surface_delta_path=surface_delta_path,
        now=NOW,
    )
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=_registry_with_fresh_route("codex.headless.full"),
        quota_ledger=sources.quota_ledger,
        surface_delta_refs_by_route=sources.surface_delta_refs_by_route,
        surface_delta_blockers_by_route=sources.surface_delta_blockers_by_route,
        now=NOW,
    )

    assert request.capability is not None
    assert any(
        "test:unknown-route-stale" in blocker
        for blocker in request.capability.surface_delta_blockers
    )
    decision = evaluate_dispatch_policy(request, now=NOW)
    assert decision.action is DispatchAction.HOLD
    assert "capability_surface_delta_pending" in decision.reason_codes


def test_unknown_producer_route_id_with_route_shaped_raw_ref_fails_closed_globally(
    tmp_path: Path,
) -> None:
    surface_delta_path = tmp_path / "capability-surface-deltas.json"
    surface_delta_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "schema_ref": "schemas/capability-surface-delta.schema.json",
                "generated_from": ["unit-test"],
                "declared_at": "2026-05-09T22:00:00Z",
                "descriptors": [
                    {
                        "descriptor_schema": 1,
                        "surface_id": "surface.codex.cluster",
                        "descriptor_ref": "platform-capability-registry:codex.headless.typo",
                        "surface_kind": "model_route",
                        "authority_ceiling": "authoritative",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "stale_after": "1h",
                        "evidence_refs": ["receipt:codex-typo"],
                        "route_id": "codex.headless.ful",
                        "resource_pools": ["subscription_quota"],
                    }
                ],
                "deltas": [
                    {
                        "delta_schema": 1,
                        "delta_id": "test:unknown-route-raw-known-ref-stale",
                        "source": "unit-test",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "detected_by": "unit-test",
                        "surface_id": "surface.codex.receipt-check",
                        "delta_kind": "stale_determination",
                        "prior_descriptor_ref": "codex.headless.full",
                        "observed_descriptor_ref": "receipt:codex-typo:expired",
                        "evidence_refs": ["codex.headless.full"],
                        "authority_ceiling": "authoritative",
                        "affected_resource_pools": ["subscription_quota"],
                        "privacy_sensitive": True,
                        "public_egress": False,
                        "money_rail": False,
                        "freshness_state": "stale",
                        "required_intake_action": "refresh_receipt",
                        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
                        "summary": "raw known-route refs must not validate unknown producer route",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sources = load_dispatch_policy_sources(
        registry_path=None,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        surface_delta_path=surface_delta_path,
        now=NOW,
    )
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=_registry_with_fresh_route("codex.headless.full"),
        quota_ledger=sources.quota_ledger,
        surface_delta_refs_by_route=sources.surface_delta_refs_by_route,
        surface_delta_blockers_by_route=sources.surface_delta_blockers_by_route,
        now=NOW,
    )

    assert request.capability is not None
    assert any(
        "test:unknown-route-raw-known-ref-stale" in blocker
        for blocker in request.capability.surface_delta_blockers
    )
    decision = evaluate_dispatch_policy(request, now=NOW)
    assert decision.action is DispatchAction.HOLD
    assert "capability_surface_delta_pending" in decision.reason_codes


def test_shared_descriptor_evidence_ref_blocks_all_joined_routes(
    tmp_path: Path,
) -> None:
    surface_delta_path = tmp_path / "capability-surface-deltas.json"
    surface_delta_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "schema_ref": "schemas/capability-surface-delta.schema.json",
                "generated_from": ["unit-test"],
                "declared_at": "2026-05-09T22:00:00Z",
                "descriptors": [
                    {
                        "descriptor_schema": 1,
                        "surface_id": "surface.codex.cluster",
                        "descriptor_ref": "platform-capability-registry:codex.headless.full",
                        "surface_kind": "model_route",
                        "authority_ceiling": "authoritative",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "stale_after": "1h",
                        "evidence_refs": ["receipt:shared-provider"],
                        "route_id": "codex.headless.full",
                        "resource_pools": ["subscription_quota"],
                    },
                    {
                        "descriptor_schema": 1,
                        "surface_id": "surface.glmcp.cluster",
                        "descriptor_ref": "platform-capability-registry:glmcp.review.direct",
                        "surface_kind": "model_route",
                        "authority_ceiling": "authoritative",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "stale_after": "1h",
                        "evidence_refs": ["receipt:shared-provider"],
                        "route_id": "glmcp.review.direct",
                        "resource_pools": ["subscription_quota"],
                    },
                ],
                "deltas": [
                    {
                        "delta_schema": 1,
                        "delta_id": "test:shared-provider-stale",
                        "source": "unit-test",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "detected_by": "unit-test",
                        "surface_id": "surface.provider.receipt-check",
                        "delta_kind": "stale_determination",
                        "prior_descriptor_ref": "receipt:shared-provider:previous",
                        "observed_descriptor_ref": "receipt:shared-provider:current-expired",
                        "evidence_refs": ["receipt:shared-provider"],
                        "authority_ceiling": "authoritative",
                        "affected_resource_pools": ["subscription_quota"],
                        "privacy_sensitive": True,
                        "public_egress": False,
                        "money_rail": False,
                        "freshness_state": "stale",
                        "required_intake_action": "refresh_receipt",
                        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
                        "summary": "shared provider receipt is stale",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sources = load_dispatch_policy_sources(
        registry_path=None,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        surface_delta_path=surface_delta_path,
        now=NOW,
    )

    for route_id in ("codex.headless.full", "glmcp.review.direct"):
        assert any(
            "test:shared-provider-stale" in blocker
            for blocker in sources.surface_delta_blockers_by_route[route_id]
        )

    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=_registry_with_fresh_route("codex.headless.full"),
        quota_ledger=sources.quota_ledger,
        surface_delta_refs_by_route=sources.surface_delta_refs_by_route,
        surface_delta_blockers_by_route=sources.surface_delta_blockers_by_route,
        now=NOW,
    )

    assert request.capability is not None
    assert any(
        "test:shared-provider-stale" in blocker
        for blocker in request.capability.surface_delta_blockers
    )
    decision = evaluate_dispatch_policy(request, now=NOW)
    assert decision.action is DispatchAction.HOLD
    assert "capability_surface_delta_pending" in decision.reason_codes


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


def test_glmcp_subscription_route_missing_quota_is_not_fresh_green() -> None:
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=_capability(route_id="glmcp.review.direct"),
        quota=None,
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.route_policy_green is False
    assert decision.quota_freshness_green is False
    assert "subscription_route_quota_unavailable" in decision.reason_codes


def test_glmcp_subscription_route_holds_when_live_quota_ledger_stale() -> None:
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=_capability(route_id="glmcp.review.direct"),
        quota=_quota(
            budget_ledger_stale=True,
            subscription_quota_state="fresh",
            route_subscription_quota_state="fresh",
            route_quota_evidence_refs=("relay-receipt:glmcp-quota-admission.yaml",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.route_policy_green is False
    assert decision.quota_freshness_green is False
    assert "subscription_quota_ledger_stale" in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


def test_glmcp_subscription_route_holds_when_live_quota_ledger_unknown() -> None:
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=_capability(route_id="glmcp.review.direct"),
        quota=_quota(
            budget_ledger_stale=None,
            subscription_quota_state="fresh",
            route_subscription_quota_state="fresh",
            route_quota_evidence_refs=("relay-receipt:glmcp-quota-admission.yaml",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.route_policy_green is False
    assert decision.quota_freshness_green is False
    assert "subscription_quota_ledger_unknown" in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


def test_glmcp_subscription_route_launches_with_fresh_route_quota() -> None:
    quota_ref = "relay-receipt:glmcp-quota-admission.yaml:fresh_until:2026-05-09T23:00:00Z"
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=_capability(route_id="glmcp.review.direct"),
        quota=_quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state="fresh",
            route_quota_evidence_refs=(quota_ref,),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert decision.quota_freshness_green is True
    assert decision.quota_evidence_refs == (quota_ref,)
    assert "policy_launch" in decision.reason_codes


def test_glmcp_route_specific_quota_holds_on_capacity_pool_mismatch() -> None:
    quota_ref = "relay-receipt:glmcp-quota-admission.yaml:fresh_until:2026-05-09T23:00:00Z"
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=_capability(
            route_id="glmcp.review.direct",
            capacity_pool="local_compute",
        ),
        quota=_quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state="fresh",
            route_quota_evidence_refs=(quota_ref,),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.route_policy_green is False
    assert decision.quota_freshness_green is False
    assert "subscription_route_capacity_pool_mismatch" in decision.reason_codes
    assert "capacity_pool:local_compute" in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


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
        task_fields=_review_task_fields(),
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

    unbounded_request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="glmcp",
        mode="review",
        profile="direct",
        task_fields=_review_task_fields(),
        registry=registry,
        quota_ledger=_ledger_with_route_subscription_state(route_id, "fresh"),
        now=freshness_now,
    )
    assert unbounded_request.quota is not None
    assert unbounded_request.quota.route_subscription_quota_state == "unknown"
    assert (
        "quota-snapshot:quota-glmcp-review-direct-fresh:fresh_until_missing"
        in unbounded_request.quota.route_quota_evidence_refs
    )

    unbounded_decision = evaluate_dispatch_policy(unbounded_request, now=freshness_now)

    assert unbounded_decision.action is DispatchAction.HOLD
    assert "subscription_route_quota_not_fresh" in unbounded_decision.reason_codes
    assert "route_subscription_quota_state:unknown" in unbounded_decision.reason_codes

    fresh_request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="glmcp",
        mode="review",
        profile="direct",
        task_fields=_review_task_fields(),
        registry=registry,
        quota_ledger=_ledger_with_route_subscription_state(
            route_id,
            "fresh",
            fresh_until="2026-05-09T23:00:00Z",
        ),
        now=freshness_now,
    )
    assert fresh_request.quota is not None
    assert fresh_request.quota.route_subscription_quota_state == "fresh"

    fresh_decision = evaluate_dispatch_policy(fresh_request, now=freshness_now)

    assert fresh_decision.action is DispatchAction.LAUNCH
    assert fresh_decision.quota_freshness_green is True
    assert "policy_launch" in fresh_decision.reason_codes


def test_build_dispatch_request_holds_glmcp_capacity_pool_mismatch() -> None:
    route_id = "glmcp.review.direct"
    registry = _registry_with_fresh_route(route_id)
    route = registry.require(route_id).model_copy(
        update={"capacity_pool": CapacityPool.LOCAL_COMPUTE}
    )
    registry = registry.model_copy(
        update={
            "routes": [
                route if existing.route_id == route_id else existing for existing in registry.routes
            ]
        }
    )
    freshness_now = datetime(2026, 5, 9, 22, 10, tzinfo=UTC)

    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="glmcp",
        mode="review",
        profile="direct",
        task_fields=_review_task_fields(),
        registry=registry,
        quota_ledger=_ledger_with_route_subscription_state(
            route_id,
            "fresh",
            fresh_until="2026-05-09T23:00:00Z",
        ),
        now=freshness_now,
    )
    assert request.capability is not None
    assert request.capability.capacity_pool == "local_compute"
    assert request.quota is not None
    assert request.quota.route_subscription_quota_state == "fresh"

    decision = evaluate_dispatch_policy(request, now=freshness_now)

    assert decision.action is DispatchAction.HOLD
    assert decision.quota_freshness_green is False
    assert "subscription_route_capacity_pool_mismatch" in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


def test_glmcp_expired_admission_snapshot_holds_even_when_ledger_fresh() -> None:
    route_id = "glmcp.review.direct"
    registry = _registry_with_fresh_route(route_id)
    freshness_now = datetime(2026, 5, 9, 22, 10, tzinfo=UTC)

    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="glmcp",
        mode="review",
        profile="direct",
        task_fields=_review_task_fields(),
        registry=registry,
        quota_ledger=_ledger_with_route_subscription_state(
            route_id,
            "fresh",
            fresh_until="2026-05-09T22:05:00Z",
            ledger_captured_at="2026-05-09T22:00:00Z",
        ),
        now=freshness_now,
    )

    assert request.quota is not None
    assert request.quota.budget_ledger_stale is False
    assert request.quota.route_subscription_quota_state == "stale"
    assert any(
        ref.startswith("quota-snapshot:quota-glmcp-review-direct-fresh:fresh_until_expired")
        for ref in request.quota.route_quota_evidence_refs
    )

    decision = evaluate_dispatch_policy(request, now=freshness_now)

    assert decision.action is DispatchAction.HOLD
    assert "subscription_route_quota_not_fresh" in decision.reason_codes
    assert "route_subscription_quota_state:stale" in decision.reason_codes


def test_glmcp_missing_capability_still_surfaces_route_quota_requirement() -> None:
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=None,
        quota=_quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state="unknown",
            route_quota_evidence_refs=("quota-snapshot:glmcp.review.direct:missing",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert "capability_registry_unavailable" in decision.reason_codes
    assert "subscription_route_quota_not_fresh" in decision.reason_codes
    assert "route_subscription_quota_state:unknown" in decision.reason_codes
    assert "subscription_route_capability_missing" in decision.reason_codes


def test_glmcp_unsupported_route_never_reports_quota_green() -> None:
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=RouteCapabilityState(
            route_id="glmcp.review.direct",
            supported=False,
            freshness_errors=("unsupported route: glmcp.review.direct",),
        ),
        quota=_quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state="unknown",
            route_quota_evidence_refs=("quota-snapshot:glmcp.review.direct:missing",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert decision.quota_freshness_green is False
    assert "unsupported_route" in decision.reason_codes
    assert "subscription_route_quota_not_fresh" in decision.reason_codes
    assert "route_subscription_quota_state:unknown" in decision.reason_codes
    assert "subscription_route_capability_missing" in decision.reason_codes


def test_glmcp_mismatched_capability_route_fails_closed() -> None:
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=_capability(route_id="codex.headless.full"),
        quota=_quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state="unknown",
            route_quota_evidence_refs=("quota-snapshot:glmcp.review.direct:missing",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.REFUSE
    assert decision.quota_freshness_green is False
    assert "capability_route_mismatch" in decision.reason_codes
    assert "request_route_id:glmcp.review.direct" in decision.reason_codes
    assert "capability_route_id:codex.headless.full" in decision.reason_codes
    assert "subscription_route_quota_not_fresh" in decision.reason_codes
    assert "policy_launch" not in decision.reason_codes


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


def test_glmcp_launch_receipt_persists_quota_evidence(tmp_path: Path) -> None:
    quota_ref = "relay-receipt:glmcp-quota-admission.yaml:fresh_until:2026-05-09T23:00:00Z"
    request = _request(
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        capability=_capability(route_id="glmcp.review.direct"),
        quota=_quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state="fresh",
            route_quota_evidence_refs=(quota_ref,),
        ),
    )
    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.LAUNCH

    path = write_route_decision_receipt(decision, ledger_dir=tmp_path)
    line = path.read_text(encoding="utf-8").splitlines()[-1]

    assert '"quota_evidence_refs": [' in line
    assert quota_ref in line


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


def test_dimensional_policy_scores_fixed_route_overhead_through_dispatch() -> None:
    demand = _demand(tags=["fixed-overhead-sensitive"])
    route_payload = _route_with_scores("codex.headless.full", score=5).model_dump(mode="json")
    route_payload["historical_performance"]["fixed_route_overhead"] = {
        "fixed_cost_score": 4,
        "setup_seconds": 90,
        "context_tokens": 3000,
        "coordination_steps": 2,
        "evidence_refs": ["overhead:test:codex-headless-full"],
        "projection_ref": "overhead:test:projection",
    }
    supply = build_supply_vector(PlatformCapabilityRoute.model_validate(route_payload), now=NOW)
    request = _request(demand_vector=demand, supply_vector=supply)

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.dimensional_receipt is not None
    [candidate] = decision.dimensional_receipt.candidates
    overhead_score = next(
        score for score in candidate.dimensional_scores if score.dimension == "fixed_route_overhead"
    )
    assert overhead_score.demand == 5
    assert overhead_score.supply == 4
    assert overhead_score.score == 1.0
    assert overhead_score.confidence == 3.0
    assert overhead_score.evidence_refs == ("overhead:test:codex-headless-full",)


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


def test_policy_sources_fail_soft_when_quota_fixture_resolution_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_fixture_resolution(*, live_path: Path | None = None) -> object:
        raise RuntimeError(
            "hapax-spine: cannot load 'quota-spend-ledger-fixtures.json' "
            "-- set HAPAX_SPINE_CONFIG_DIR"
        )

    monkeypatch.setattr(
        dispatcher_policy,
        "load_quota_spend_ledger_resolved",
        fail_fixture_resolution,
    )
    receipt = build_route_authority_receipt(
        receipt_type="runtime_actuation",
        route_id="codex.headless.full",
        evidence_refs=["route-authority-receipt:test-feed-1e"],
        task_ids=["cc-task-quota-fixture-failsoft-capability-plane-20260705"],
        mutation_surfaces=["runtime"],
        receipt_id="test-feed-1e-runtime-actuation",
        issued_at=NOW,
    )
    write_route_authority_receipt(receipt, receipt_dir=tmp_path)

    sources = load_dispatch_policy_sources(receipt_dir=tmp_path, now=NOW)

    assert sources.registry is not None
    assert sources.registry.routes
    assert sources.registry_error is None
    assert sources.route_authority_receipts == (receipt,)
    assert sources.quota_ledger is None
    assert sources.quota_ledger_source is None
    assert sources.quota_error is not None
    assert "quota-spend-ledger-fixtures.json" in sources.quota_error


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
