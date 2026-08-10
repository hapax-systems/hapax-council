"""Tests for the S5-4 fail-closed dispatcher policy evaluator."""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest

from shared import dispatcher_policy
from shared.dispatcher_policy import (
    LOCAL_DEV_PLATFORMS,
    CandidateStatus,
    ClogRouteState,
    DispatchAction,
    DispatchRequest,
    QuotaSpendState,
    RouteCapabilityState,
    _resource_state_refs,
    _surface_delta_route_index,
    build_dispatch_request,
    build_route_authority_receipt,
    evaluate_dispatch_policy,
    load_dispatch_policy_sources,
    write_route_authority_receipt,
    write_route_decision_receipt,
)
from shared.jsonl_append import append_jsonl, lock_path_for
from shared.mcp_connector_policy import _latest_route_decision
from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
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
    "model:glm-5.2:"
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


def test_resource_state_refs_skip_availability_receipt_for_non_resource_degradation() -> None:
    capability = _capability(
        freshness_ok=False,
        freshness_errors=(
            "capability_availability_degraded",
            "auth_surface_not_fresh",
            "capacity_pool_headroom_not_fresh",
        ),
        availability_receipt_ref="capability-availability-receipt:codex.headless.full:test",
    )

    refs = _resource_state_refs(capability, None)

    assert "capability-availability-receipt:codex.headless.full:test" not in refs
    assert "capability.resource_source:local_probe" in refs


def test_resource_state_refs_include_availability_receipt_for_resource_degradation() -> None:
    capability = _capability(
        freshness_ok=False,
        freshness_errors=(
            "capability_availability_degraded",
            "codex.headless.full: resource stale",
        ),
        availability_receipt_ref="capability-availability-receipt:codex.headless.full:test",
    )

    refs = _resource_state_refs(capability, None)

    assert "capability-availability-receipt:codex.headless.full:test" in refs
    assert "codex.headless.full: resource stale" in refs


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


@pytest.mark.parametrize(
    "marker",
    ("AgenticTrustEvidenceReceiptV1", "agentic-trust-evidence-receipt-v1"),
)
def test_observation_receipt_cannot_be_a_quality_selector(marker: str) -> None:
    with pytest.raises(ValueError, match="cannot establish route capability"):
        _capability(eligible_quality_floors=(marker,))
    with pytest.raises(ValueError, match="cannot define a dispatch quality floor"):
        _request(quality_floor=marker)


def test_observation_receipt_child_remains_an_ordinary_quality_identity() -> None:
    child = "AgenticTrustEvidenceReceiptV1Child"
    assert _capability(eligible_quality_floors=(child,)).eligible_quality_floors == (child,)
    assert _request(quality_floor=child).quality_floor == child


def test_route_capability_privacy_posture_is_closed_vocabulary() -> None:
    with pytest.raises(ValueError):
        _capability(privacy_posture="AgenticTrustEvidenceReceiptV1")


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
    quota_evidence_refs = [f"test:{route_id}:quota"]
    if payload.get("capacity_pool") == "subscription_quota":
        quota_evidence_refs.append(f"test:{route_id}:account-live-quota:observed")
    payload["freshness"]["evidence"] = {
        "capability": {
            "evidence_refs": [f"test:{route_id}:capability"],
            "blocked_reasons": [],
        },
        "quota": {
            "evidence_refs": quota_evidence_refs,
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
    quota = _quota()
    if route_id == "claude.headless.full":
        quota = _quota(
            route_subscription_quota_state="fresh",
            route_quota_evidence_refs=("test:claude-headless-full:account-live-quota:observed",),
        )
    return _request(
        route_id=route_id,
        platform=platform or parts[0],
        mode=parts[1],
        profile=profile or parts[2],
        capability=_capability(**capability_payload),
        quota=quota,
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


@pytest.mark.parametrize(
    "surface_id",
    (
        "surface.local_compute.agentic_trust_evaluator_surface",
        "SURFACE.LOCAL_COMPUTE.AGENTIC_TRUST_EVALUATOR_SURFACE",
    ),
)
def test_registered_evidence_only_surface_delta_is_dispatch_inert(
    tmp_path: Path,
    surface_id: str,
) -> None:
    surface_delta_path = tmp_path / "agentic-trust-evidence-only-delta.json"
    surface_delta_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "schema_ref": "schemas/capability-surface-delta.schema.json",
                "generated_from": ["unit-test-adversarial-wrong-channel"],
                "declared_at": "2026-05-09T22:00:00Z",
                "descriptors": [
                    {
                        "descriptor_schema": 1,
                        "surface_id": surface_id,
                        "descriptor_ref": "inventory:local_compute.agentic_trust_evaluator_surface",
                        "surface_kind": "local_tool",
                        "authority_ceiling": "read_only",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "stale_after": "1h",
                        "evidence_refs": ["test:evidence-only-observation"],
                        "route_id": "codex.headless.full",
                        "resource_pools": ["local_compute"],
                    }
                ],
                "deltas": [
                    {
                        "delta_schema": 1,
                        "delta_id": "test:evidence-only-wrong-channel",
                        "source": "unit-test",
                        "observed_at": "2026-05-09T22:00:00Z",
                        "detected_by": "unit-test",
                        "surface_id": surface_id,
                        "delta_kind": "stale_determination",
                        "prior_descriptor_ref": "agentic-trust-receipt:previous",
                        "observed_descriptor_ref": "agentic-trust-receipt:expired",
                        "evidence_refs": ["agentic-trust-receipt:expired"],
                        "authority_ceiling": "read_only",
                        "affected_resource_pools": ["local_compute"],
                        "privacy_sensitive": False,
                        "public_egress": False,
                        "money_rail": False,
                        "freshness_state": "stale",
                        "required_intake_action": "refresh_receipt",
                        "remediation_ref": "cc-task-agentic-trust-evidence-only-onboarding-20260804",
                        "summary": "adversarial evidence-only observation in the rich delta channel",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sources = load_dispatch_policy_sources(
        registry_path=None,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        receipt_dir=tmp_path / "empty-receipts",
        surface_delta_path=surface_delta_path,
        now=NOW,
    )

    assert sources.surface_delta_refs_by_route == {}
    assert sources.surface_delta_blockers_by_route == {}
    registry = _registry_with_fresh_route("codex.headless.full")
    with_observation = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=registry,
        quota_ledger=sources.quota_ledger,
        surface_delta_refs_by_route=sources.surface_delta_refs_by_route,
        surface_delta_blockers_by_route=sources.surface_delta_blockers_by_route,
        now=NOW,
    )
    without_observation = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=registry,
        quota_ledger=sources.quota_ledger,
        now=NOW,
    )

    observed_decision = evaluate_dispatch_policy(with_observation, now=NOW)
    baseline_decision = evaluate_dispatch_policy(without_observation, now=NOW)
    assert with_observation.capability is not None
    assert with_observation.capability.surface_delta_refs == ()
    assert with_observation.capability.surface_delta_blockers == ()
    assert observed_decision.model_dump(mode="json") == baseline_decision.model_dump(mode="json")

    child_payload = json.loads(surface_delta_path.read_text(encoding="utf-8"))
    child_payload["descriptors"][0]["surface_id"] += ".child"
    child_payload["deltas"][0]["surface_id"] += ".child"
    surface_delta_path.write_text(json.dumps(child_payload), encoding="utf-8")
    child_sources = load_dispatch_policy_sources(
        registry_path=None,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        receipt_dir=tmp_path / "empty-receipts",
        surface_delta_path=surface_delta_path,
        now=NOW,
    )

    assert child_sources.surface_delta_blockers_by_route["codex.headless.full"]

    route_alias_payload = json.loads(surface_delta_path.read_text(encoding="utf-8"))
    route_alias_payload["descriptors"][0]["surface_id"] = "route.codex.headless.full"
    route_alias_payload["deltas"][0]["surface_id"] = "route.codex.headless.full"
    surface_delta_path.write_text(json.dumps(route_alias_payload), encoding="utf-8")
    route_alias_refs, route_alias_blockers = _surface_delta_route_index(
        surface_delta_path,
        known_route_ids=("codex.headless.full",),
        evidence_only_surface_ids=("route.codex.headless.full",),
    )

    # Even a malicious evidence-only list cannot suppress a known admitted route.
    assert route_alias_refs["codex.headless.full"]
    assert route_alias_blockers["codex.headless.full"]


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


def test_claude_subscription_route_holds_when_route_quota_unknown() -> None:
    request = _request(
        platform="claude",
        mode="headless",
        profile="full",
        route_id="claude.headless.full",
        capability=_capability(route_id="claude.headless.full"),
        quota=_quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state="unknown",
            route_quota_evidence_refs=("relay-receipt:claude:quota-admission:absent",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.HOLD
    assert decision.route_policy_green is False
    assert decision.quota_freshness_green is False
    assert "subscription_route_quota_not_fresh" in decision.reason_codes
    assert "route_subscription_quota_state:unknown" in decision.reason_codes


def test_claude_subscription_route_launches_with_fresh_route_quota() -> None:
    request = _request(
        platform="claude",
        mode="headless",
        profile="full",
        route_id="claude.headless.full",
        capability=_capability(route_id="claude.headless.full"),
        quota=_quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state="fresh",
            route_quota_evidence_refs=("test:claude-headless-full:account-live-quota:observed",),
        ),
    )

    decision = evaluate_dispatch_policy(request, now=NOW)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert decision.quota_freshness_green is True
    assert "policy_launch" in decision.reason_codes
    assert "subscription_route_quota_not_fresh" not in decision.reason_codes


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


def test_rotation_is_a_noop_below_the_cap(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text("a\nb\nc\n", encoding="utf-8")

    assert (
        dispatcher_policy._rotate_locked(
            ledger, max_bytes=dispatcher_policy.ROUTE_DECISION_LEDGER_MAX_BYTES
        )
        is False
    )
    assert ledger.read_text(encoding="utf-8") == "a\nb\nc\n"
    assert not (tmp_path / "route-decisions.jsonl.1").exists()


def test_rotation_carries_the_newest_rows_forward(tmp_path: Path) -> None:
    """The trap this guards: a rotation that truncated would hard-block every MCP call.

    ``_latest_route_decision`` refuses when it finds no recent row for the task,
    so the rows at the tail must survive rotation.
    """
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text(
        "".join(f'{{"n": {i}, "pad": "{"x" * 200}"}}\n' for i in range(5_000)),
        encoding="utf-8",
    )
    original_size = ledger.stat().st_size

    assert dispatcher_policy._rotate_locked(ledger, max_bytes=1024) is True

    kept = [json.loads(line)["n"] for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert kept, "rotation must never leave an empty ledger"
    assert kept[-1] == 4_999, "the newest row must survive"
    assert kept == list(range(kept[0], 5_000)), "carried rows must stay contiguous and ordered"
    assert ledger.stat().st_size < original_size

    archive = tmp_path / "route-decisions.jsonl.1"
    assert archive.exists(), "one generation is retained for audit"
    assert archive.stat().st_size == original_size


def test_rotation_keeps_the_newest_row_findable_by_the_connector_gate(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    now = datetime.now(UTC)
    rows = [
        {"task_id": "old-task", "lane": "beta", "created_at": now.isoformat(), "pad": "y" * 300}
        for _ in range(4_000)
    ]
    rows.append({"task_id": "live-task", "lane": "beta", "created_at": now.isoformat()})
    ledger.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    assert dispatcher_policy._rotate_locked(ledger, max_bytes=1024) is True

    found = _latest_route_decision(task_id="live-task", role="beta", ledger_path=ledger)
    assert found is not None, "rotation stripped the row the connector gate needs"
    assert found["task_id"] == "live-task"


def test_rotation_failure_leaves_the_ledger_intact_and_says_so(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Degrading back to an uncapped ledger must never be silent.

    The failure this module exists to stop stayed invisible for weeks and reached
    2.5 GB. A rotation that quietly returns False restores exactly that condition,
    so the operator has to be told, with a next action.
    """
    ledger = tmp_path / "route-decisions.jsonl"
    payload = "".join(f'{{"n": {i}}}\n' for i in range(100))
    ledger.write_text(payload, encoding="utf-8")
    # Occupy the staging name with a directory so replace() cannot succeed.
    (tmp_path / "route-decisions.jsonl.rotating").mkdir()

    with caplog.at_level(logging.WARNING, logger="shared.dispatcher_policy"):
        assert dispatcher_policy._rotate_locked(ledger, max_bytes=1) is False

    assert ledger.read_text(encoding="utf-8") == payload
    assert caplog.records, "a failed rotation must not be silent"
    assert "UNCAPPED" in caplog.text
    assert "Next:" in caplog.text, "the warning must carry an operator next action"


def test_a_failed_archive_promotion_never_aliases_the_live_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`.1` must never end up as a hardlink of the ledger that is still being appended to.

    Promoting the archive BEFORE committing the rotation used to allow exactly that: the
    staging hardlink was renamed onto `.1`, and if the ledger replace then failed, `.1` and
    the live ledger shared one inode. Every later append grew both, `.1` stopped representing
    a rotated generation, disk use doubled per row, and the previous generation was already
    destroyed — while the warning said only "intact but UNCAPPED".

    Committing the rotation first makes that state unreachable, which is what this pins.
    """
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text("".join(f'{{"n": {i}}}\n' for i in range(300)), encoding="utf-8")

    real_replace = os.replace

    def fail_archive_promotion(src: object, dst: object) -> None:
        if str(dst).endswith(".1"):
            raise OSError(errno.EIO, "archive promotion failed")
        real_replace(src, dst)

    monkeypatch.setattr(dispatcher_policy.os, "replace", fail_archive_promotion)

    with caplog.at_level(logging.WARNING, logger="shared.dispatcher_policy"):
        rotated = dispatcher_policy._rotate_locked(ledger, max_bytes=1)

    # The rotation itself succeeded, so it must not be reported as a rotation failure.
    assert rotated is True
    assert "UNCAPPED" not in caplog.text, "a capped ledger must not be called UNCAPPED"
    assert "Next:" in caplog.text, "the warning must carry an operator next action"

    archive = tmp_path / "route-decisions.jsonl.1"
    if archive.exists():
        assert archive.stat().st_ino != ledger.stat().st_ino, (
            "the archive must never share an inode with the live ledger"
        )
    assert not (tmp_path / "route-decisions.jsonl.1.staging").exists(), (
        "the staging hardlink must not be left behind holding the old inode"
    )


def test_a_lock_file_left_by_a_dead_process_does_not_wedge_rotation(
    tmp_path: Path,
) -> None:
    """The kernel drops flock when the holder exits, so no reclamation is needed.

    The previous mtime-staleness scheme was itself a loss vector: the lock mtime
    was fixed at creation and never refreshed, so a live holder that ran past the
    window had its lock stolen and two rotations interleaved.
    """
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text("".join(f'{{"n": {i}}}\n' for i in range(100)), encoding="utf-8")
    # A stale sidecar with an ancient mtime — the old code's "dead process" shape.
    lock = tmp_path / "route-decisions.jsonl.lock"
    lock.write_text("", encoding="utf-8")
    ancient = time.time() - 86_400
    os.utime(lock, (ancient, ancient))

    assert dispatcher_policy._rotate_locked(ledger, max_bytes=1) is True
    assert ledger.read_text(encoding="utf-8").strip(), "ledger must not be emptied"


def test_an_unopenable_lock_refuses_the_write_instead_of_risking_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lock we cannot take is a receipt we cannot guarantee, so say so.

    Three attempts to make an unserialised fallback safe were all unsound for the
    same reason: without mutual exclusion a rotation elsewhere can replace the
    inode around the write, and every mitigation short of the lock is a
    check-then-act with a gap after the check. Raising is deliberate and loud;
    the alternative is a receipt that vanishes and fails the connector gate
    closed with no explanation.

    Rotation is still skipped rather than exploding, and the ledger is untouched.
    """
    ledger = tmp_path / "route-decisions.jsonl"
    payload = "".join(f'{{"n": {i}}}\n' for i in range(200))
    ledger.write_text(payload, encoding="utf-8")

    real_open = os.open

    def refuse_lock(path, flags, *args):  # type: ignore[no-untyped-def]
        if str(path).endswith(".jsonl.lock"):
            raise PermissionError(13, "Permission denied")
        return real_open(path, flags, *args)

    monkeypatch.setattr(dispatcher_policy, "ROUTE_DECISION_LEDGER_MAX_BYTES", 1)
    monkeypatch.setattr(dispatcher_policy.os, "open", refuse_lock)

    decision = evaluate_dispatch_policy(_request(), now=NOW)
    with pytest.raises(RuntimeError) as exc:
        write_route_decision_receipt(decision, ledger_dir=tmp_path)

    assert "cannot be written safely" in str(exc.value)
    assert "Next:" in str(exc.value), "the refusal must name its own remedy"
    assert ledger.read_text(encoding="utf-8") == payload, "the ledger must be untouched"
    assert not (tmp_path / "route-decisions.jsonl.1").exists(), "no rotation may have happened"


def test_the_receipt_write_appends_inside_one_lock_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rotate and append must share ONE lock acquisition, with the append inside it.

    Two acquisitions left a gap where another writer could rotate between this
    process's rotate-release and its append-acquire, and the unlocked-fallback
    escape hatch that briefly existed reintroduced the original race outright —
    an append landing mid-rotation goes to the inode about to be replaced.

    This asserts the STRUCTURE, because the behavioural version does not
    discriminate: a competing ``append_jsonl`` takes the same sidecar, so it
    blocks on rotation's own lock and its row survives either way. Ordering the
    observed events is what actually distinguishes one critical section from two.
    """
    monkeypatch.setattr(dispatcher_policy, "ROUTE_DECISION_LEDGER_MAX_BYTES", 1)
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text("".join(f'{{"n": {i}}}\n' for i in range(400)), encoding="utf-8")

    events: list[str] = []
    real_lock = dispatcher_policy._ledger_lock
    real_write = os.write

    @contextmanager
    def recording_lock(path: Path):  # type: ignore[no-untyped-def]
        events.append("lock-enter")
        with real_lock(path) as held:
            yield held
        events.append("lock-exit")

    def recording_write(fd: int, data: bytes) -> int:
        if data == blob:
            events.append("append")
        return real_write(fd, data)

    decision = evaluate_dispatch_policy(_request(), now=NOW)
    payload = decision.model_dump(mode="json")
    if decision.dimensional_receipt is not None:
        payload.update(decision.dimensional_receipt.model_dump(mode="json"))
    blob = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")

    monkeypatch.setattr(dispatcher_policy, "_ledger_lock", recording_lock)
    monkeypatch.setattr(dispatcher_policy.os, "write", recording_write)
    write_route_decision_receipt(decision, ledger_dir=tmp_path)

    assert events == ["lock-enter", "append", "lock-exit"], (
        f"the append must happen inside a single lock acquisition; saw {events}"
    )
    assert decision.decision_id in ledger.read_text(encoding="utf-8")


def test_no_row_is_written_when_a_rotation_could_race_the_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The scenario no fallback could cover, now excluded by construction.

    This process cannot lock while a rotation completes underneath what would
    have been its append. Successive fallbacks tried to survive this: arguing
    other processes must also be failing (unsound for transient errors), then
    verifying the inode afterwards (a check-then-act that still lost the row on a
    final attempt). Both families ultimately called it unresolved, and they were
    right — the window cannot be closed without the lock.

    So nothing is written at all, and the caller is told why.
    """
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text("".join(f'{{"n": {i}}}\n' for i in range(200)), encoding="utf-8")

    real_flock = fcntl.flock

    def always_fail(fd: int, op: int) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(dispatcher_policy.fcntl, "flock", always_fail)
    monkeypatch.setattr(dispatcher_policy, "_LEDGER_LOCK_RETRY_S", 0)

    real_open = os.open
    rotated = {"done": False}

    def rotate_under_the_append(path, flags, *args):  # type: ignore[no-untyped-def]
        fd = real_open(path, flags, *args)
        # After this process opens the ledger for append but before it writes,
        # simulate another process completing a rotation: replace the inode.
        if str(path).endswith("route-decisions.jsonl") and not rotated["done"]:
            rotated["done"] = True
            replacement = tmp_path / "route-decisions.jsonl.new"
            replacement.write_text('{"carried": true}\n', encoding="utf-8")
            os.replace(replacement, ledger)
        return fd

    monkeypatch.setattr(dispatcher_policy.os, "open", rotate_under_the_append)

    decision = evaluate_dispatch_policy(_request(), now=NOW)
    with caplog.at_level(logging.WARNING, logger="shared.dispatcher_policy"):
        with pytest.raises(RuntimeError):
            write_route_decision_receipt(decision, ledger_dir=tmp_path)

    monkeypatch.setattr(dispatcher_policy.fcntl, "flock", real_flock)
    assert decision.decision_id not in ledger.read_text(encoding="utf-8"), (
        "no row may be written into a ledger this process cannot lock"
    )
    assert not rotated["done"], "the append must not even be attempted"


def test_a_transient_flock_failure_is_retried_into_a_held_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient failure must NOT degrade to an unserialised append.

    Giving up is only safe when every other writer is failing too — true for a
    filesystem without flock, false for a per-call EINTR. If a transient failure
    here dropped straight to an unserialised append while another process locked
    successfully, that process could rotate under our append and the receipt
    would land in the inode being replaced.

    The earlier test made EVERY flock call fail, which validated the assumption
    instead of challenging it. This one fails once and then succeeds.
    """
    monkeypatch.setattr(dispatcher_policy, "ROUTE_DECISION_LEDGER_MAX_BYTES", 1)
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text("".join(f'{{"n": {i}}}\n' for i in range(300)), encoding="utf-8")

    real_flock = fcntl.flock
    calls = {"n": 0}

    def flaky_flock(fd: int, op: int) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise InterruptedError(4, "Interrupted system call")
        real_flock(fd, op)

    monkeypatch.setattr(dispatcher_policy.fcntl, "flock", flaky_flock)

    decision = evaluate_dispatch_policy(_request(), now=NOW)
    write_route_decision_receipt(decision, ledger_dir=tmp_path)

    assert calls["n"] >= 2, "a transient flock failure must be retried, not surrendered to"
    assert (tmp_path / "route-decisions.jsonl.1").exists(), (
        "the retry must yield a held lock, so rotation proceeds normally"
    )
    assert decision.decision_id in ledger.read_text(encoding="utf-8")


def test_a_short_write_still_produces_a_complete_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.write may write fewer bytes than asked; ignoring the count truncates the row.

    A truncated JSONL row is worse than a missing one: the connector reader meets
    malformed data and fails closed, which is the outcome this module exists to
    prevent.
    """
    ledger = tmp_path / "route-decisions.jsonl"
    real_write = os.write

    def short_write(fd: int, data: bytes) -> int:
        return real_write(fd, data[:1])  # one byte at a time

    monkeypatch.setattr(dispatcher_policy.os, "write", short_write)

    decision = evaluate_dispatch_policy(_request(), now=NOW)
    write_route_decision_receipt(decision, ledger_dir=tmp_path)

    line = ledger.read_text(encoding="utf-8").splitlines()[-1]
    parsed = json.loads(line)  # must not raise: a truncated row is unparseable
    assert decision.decision_id in line, "the row must be complete despite short writes"
    assert isinstance(parsed, dict) and parsed, "the row must round-trip as an object"


def test_a_filesystem_without_flock_still_writes_the_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """EOPNOTSUPP means flock is NOT IMPLEMENTED here, so nobody can rotate — the append is safe.

    ENOLCK is deliberately NOT in this class and must not be added to it. It is
    lock-record exhaustion, which means other writers CAN still hold locks and
    rotate; `test_lock_failures_that_are_not_capability_facts_refuse_the_write`
    requires it to refuse. Reading this docstring as being about ENOLCK is the
    exact reasoning error the excluded-errno comment in `shared/dispatcher_policy.py`
    warns against, and acting on it would license an unserialised append while
    another writer rotates the inode out from under it.

    Refusing this case as well would be its own defect: on a locking-less
    filesystem every MCP mutation becomes impossible, including the ones that
    would repair the estate. The distinguishing fact is not "did we get the lock"
    but "can anyone else be rotating", and errno answers it.

    Rotation is still skipped, because rotation replaces the inode and must never
    happen unserialised.
    """

    def unsupported_flock(fd: int, op: int) -> None:
        raise OSError(errno.EOPNOTSUPP, "Operation not supported")

    monkeypatch.setattr(dispatcher_policy, "ROUTE_DECISION_LEDGER_MAX_BYTES", 1)
    monkeypatch.setattr(dispatcher_policy.fcntl, "flock", unsupported_flock)
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text("".join(f'{{"n": {i}}}\n' for i in range(300)), encoding="utf-8")

    decision = evaluate_dispatch_policy(_request(), now=NOW)
    with caplog.at_level(logging.WARNING, logger="shared.dispatcher_policy"):
        path = write_route_decision_receipt(decision, ledger_dir=tmp_path)

    assert decision.decision_id in path.read_text(encoding="utf-8"), (
        "a locking-less filesystem must not make every MCP mutation impossible"
    )
    assert not (tmp_path / "route-decisions.jsonl.1").exists(), (
        "rotation replaces the inode and must never run unserialised"
    )
    assert "unsupported" in caplog.text


@pytest.mark.parametrize(
    ("code", "name"),
    [
        (errno.ENOLCK, "ENOLCK"),
        (errno.EINVAL, "EINVAL"),
        (errno.EACCES, "EACCES"),
        (errno.EIO, "EIO"),
    ],
)
def test_lock_failures_that_are_not_capability_facts_refuse_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, name: str
) -> None:
    """Only "this operation does not exist here" licenses an unserialised append.

    ENOLCK is the trap, and an earlier revision of this module got it wrong:
    flock(2) returns it when the kernel runs out of lock RECORDS — resource
    exhaustion, which usually means locks are in heavy use. Reading that as
    "nobody can lock" would license an unlocked append at exactly the moment
    other writers are locking and rotating. EINVAL is a malformed call, and
    EACCES/EIO plainly mean locking works and we did not get it.

    All of these must refuse rather than append.
    """

    def failing_flock(fd: int, op: int) -> None:
        raise OSError(code, name)

    monkeypatch.setattr(dispatcher_policy, "ROUTE_DECISION_LEDGER_MAX_BYTES", 1)
    monkeypatch.setattr(dispatcher_policy, "_LEDGER_LOCK_RETRY_S", 0)
    monkeypatch.setattr(dispatcher_policy.fcntl, "flock", failing_flock)
    ledger = tmp_path / "route-decisions.jsonl"
    original = "".join(f'{{"n": {i}}}\n' for i in range(120))
    ledger.write_text(original, encoding="utf-8")

    decision = evaluate_dispatch_policy(_request(), now=NOW)
    with pytest.raises(RuntimeError):
        write_route_decision_receipt(decision, ledger_dir=tmp_path)

    assert ledger.read_text(encoding="utf-8") == original, (
        f"{name} must not license an unserialised append"
    )


def test_a_persistent_flock_failure_warns_and_refuses_without_exploding_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """flock itself can fail — EINTR, or a filesystem that does not implement it.

    Two properties, and they are different. _ledger_lock must SWALLOW the OSError
    and warn rather than let it escape rotation as an unexplained crash — that was
    a review finding in its own right. And the caller must then refuse the write,
    because an unserialised append can be discarded by a concurrent rotation.

    The refusal names its remedy; the raw OSError did not.
    """

    def refuse_flock(fd: int, op: int) -> None:
        raise OSError(9, "Bad file descriptor")

    monkeypatch.setattr(dispatcher_policy, "ROUTE_DECISION_LEDGER_MAX_BYTES", 1)
    monkeypatch.setattr(dispatcher_policy, "_LEDGER_LOCK_RETRY_S", 0)
    monkeypatch.setattr(dispatcher_policy.fcntl, "flock", refuse_flock)
    ledger = tmp_path / "route-decisions.jsonl"
    original = "".join(f'{{"n": {i}}}\n' for i in range(300))
    ledger.write_text(original, encoding="utf-8")

    decision = evaluate_dispatch_policy(_request(), now=NOW)
    with caplog.at_level(logging.WARNING, logger="shared.dispatcher_policy"):
        with pytest.raises(RuntimeError) as exc:
            write_route_decision_receipt(decision, ledger_dir=tmp_path)

    assert "Bad file descriptor" not in str(exc.value), (
        "the raw OSError must be swallowed and translated, not propagated"
    )
    assert "Next:" in str(exc.value)
    assert "classified failed" in caplog.text, (
        "the lock failure must still be logged, and classified as failed rather "
        "than unsupported — EBADF means locking works here and we did not get it"
    )
    assert ledger.read_text(encoding="utf-8") == original, "the ledger must be untouched"
    assert not (tmp_path / "route-decisions.jsonl.1").exists(), "rotation must be skipped"


def test_a_failed_archive_link_preserves_the_previous_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retained .1 must survive a rotation that fails while creating its replacement.

    The archive used to be unlinked before os.link created the new one, so a
    link failure destroyed the prior audit generation outright — and the warning
    then reported only that the ledger was uncapped, understating a loss that
    had already happened.
    """
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text("".join(f'{{"n": {i}}}\n' for i in range(300)), encoding="utf-8")
    archive = tmp_path / "route-decisions.jsonl.1"
    archive.write_text('{"generation": "previous"}\n', encoding="utf-8")

    def refuse_link(src: object, dst: object) -> None:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(dispatcher_policy.os, "link", refuse_link)

    assert dispatcher_policy._rotate_locked(ledger, max_bytes=1) is False
    assert archive.read_text(encoding="utf-8") == '{"generation": "previous"}\n', (
        "a failed rotation must not destroy the retained archive"
    )
    assert not (tmp_path / "route-decisions.jsonl.1.staging").exists(), "staging must be cleaned up"


def test_rotation_and_append_share_one_lock(tmp_path: Path) -> None:
    """Rotation must take the SAME sidecar append_jsonl takes.

    A separately-derived lock path looks like mutual exclusion and provides none.
    """
    ledger = tmp_path / "route-decisions.jsonl"
    assert lock_path_for(ledger) == tmp_path / "route-decisions.jsonl.lock"


def test_rotation_does_not_discard_a_concurrently_appended_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported critical: an append landing mid-rotation was lost.

    Rotation reads the tail, then links the ledger to ``.1`` and replaces the
    path. An appender that slipped into that gap wrote to the old inode, so its
    row survived only in the archive and was invisible to the connector gate —
    which then failed closed on a receipt that had been written successfully.

    The appender runs on a thread and blocks on the shared flock; a separate
    ``open`` is a separate open-file-description, so the kernel denies it even
    within one process. The barrier makes it deterministic: rotation does not
    proceed past the tail read until the appender is committed to writing.
    """
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text("".join(f'{{"n": {i}}}\n' for i in range(500)), encoding="utf-8")

    appender_started = threading.Event()
    appended = {"row": '{"receipt": "written-during-rotation"}'}

    def _append() -> None:
        appender_started.set()
        append_jsonl(ledger, json.loads(appended["row"]), sort_keys=True)

    thread = threading.Thread(target=_append, daemon=True)
    real_tail = dispatcher_policy.read_tail_lines

    def _tail_then_race(*args: object, **kwargs: object) -> list[str]:
        carried = real_tail(*args, **kwargs)
        thread.start()
        appender_started.wait(timeout=5)
        time.sleep(0.2)  # let the appender reach and block on the flock
        return carried

    # Drive the PRODUCTION path: _rotate_locked assumes the lock is already
    # held, so calling it bare would leave the competing appender unexcluded and
    # test nothing. write_route_decision_receipt is what takes the lock.
    monkeypatch.setattr(dispatcher_policy, "ROUTE_DECISION_LEDGER_MAX_BYTES", 1)
    decision = evaluate_dispatch_policy(_request(), now=NOW)
    with mock.patch.object(dispatcher_policy, "read_tail_lines", _tail_then_race):
        write_route_decision_receipt(decision, ledger_dir=tmp_path)
    thread.join(timeout=5)
    assert not thread.is_alive(), "the appender must not still be blocked"

    active = ledger.read_text(encoding="utf-8")
    assert "written-during-rotation" in active, (
        "a receipt appended during rotation was lost from the active ledger"
    )
    assert decision.decision_id in active, "the receipt itself was lost"


def test_write_receipt_rotates_an_over_cap_ledger_and_still_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The only production call site of rotation, and it had no test.

    Every rotation test called the function directly, so a regression that
    rotated *after* the append — dropping the row just written — or removed the
    call entirely would have passed the whole suite.
    """
    monkeypatch.setattr(dispatcher_policy, "ROUTE_DECISION_LEDGER_MAX_BYTES", 1)
    ledger = tmp_path / "route-decisions.jsonl"
    ledger.write_text("".join(f'{{"n": {i}}}\n' for i in range(500)), encoding="utf-8")

    decision = evaluate_dispatch_policy(_request(), now=NOW)
    path = write_route_decision_receipt(decision, ledger_dir=tmp_path)

    assert path == ledger
    assert (tmp_path / "route-decisions.jsonl.1").exists(), "rotation must have run"
    assert decision.decision_id in ledger.read_text(encoding="utf-8"), (
        "the receipt written after rotation must survive in the ledger the gate reads"
    )
    assert (
        _latest_route_decision(task_id=decision.task_id, role=None, ledger_path=ledger) is not None
    ), "the connector gate must still find the row it needs"


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


def test_dimensional_policy_launches_substitute_for_degraded_recomposition() -> None:
    primary = _dimensional_request(
        "codex.headless.full",
        score=5,
        capability_overrides={
            "freshness_ok": False,
            "freshness_errors": (
                "capability_availability_degraded",
                "availability_receipt:availability-codex-headless-full-test",
                "auth_surface_not_fresh",
                "capacity_pool_headroom_not_fresh",
            ),
            "availability_status": "degraded",
            "availability_receipt_ref": (
                "capability-availability-receipt:"
                "codex.headless.full:availability-codex-headless-full-test"
            ),
            "availability_reason_codes": (
                "capability_availability_degraded",
                "availability_receipt:availability-codex-headless-full-test",
                "auth_surface:oauth",
                "capacity_pool:subscription_quota",
                "auth_surface_not_fresh",
                "capacity_pool_headroom_not_fresh",
                "refresh_status:deferred",
            ),
            "availability_refresh_status": "deferred",
            "availability_recomposition_required": True,
        },
    )
    substitute = _dimensional_request("claude.headless.full", score=4)

    decision = evaluate_dispatch_policy(
        primary,
        candidate_requests=(substitute,),
        now=NOW,
    )

    assert decision.action is DispatchAction.LAUNCH
    assert decision.launch_allowed is True
    assert decision.route_id == "claude.headless.full"
    assert "policy_launch" in decision.reason_codes
    assert "availability_recomposition_required" in decision.reason_codes
    assert "availability_recomposed_from:codex.headless.full" in decision.reason_codes
    assert "availability_recomposed_to:claude.headless.full" in decision.reason_codes
    assert (
        "capability-availability-receipt:codex.headless.full:availability-codex-headless-full-test"
    ) in decision.reason_codes
    assert decision.dimensional_receipt is not None
    assert decision.dimensional_receipt.selected_route_id == "claude.headless.full"
    candidates = {
        candidate.route_id: candidate for candidate in decision.dimensional_receipt.candidates
    }
    assert candidates["codex.headless.full"].status is CandidateStatus.VETOED
    assert candidates["claude.headless.full"].status is CandidateStatus.SELECTED


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


def test_non_supply_observation_metadata_fails_local_to_dispatch(
    tmp_path: Path,
) -> None:
    payload = json.loads(PLATFORM_CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    target = next(
        shape
        for shape in payload["omitted_capability_shapes"]
        if shape["shape_id"] == "local_compute.agentic_trust_evaluator_surface"
    )
    target["stale_after"] = "not-a-duration"
    poisoned_registry = tmp_path / "platform-capability-registry.json"
    poisoned_registry.write_text(json.dumps(payload), encoding="utf-8")
    empty_receipts = tmp_path / "empty-receipts"

    baseline = load_dispatch_policy_sources(
        registry_path=PLATFORM_CAPABILITY_REGISTRY,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        receipt_dir=empty_receipts,
        now=NOW,
    )
    observed = load_dispatch_policy_sources(
        registry_path=poisoned_registry,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        receipt_dir=empty_receipts,
        now=NOW,
    )

    assert baseline.registry is not None
    assert observed.registry is not None
    assert observed.registry_error is None
    assert observed.non_supply_observation_errors
    assert "not-a-duration" in observed.non_supply_observation_errors[0]
    assert observed.surface_delta_refs_by_route == baseline.surface_delta_refs_by_route
    assert observed.surface_delta_blockers_by_route == baseline.surface_delta_blockers_by_route
    assert [route.model_dump(mode="json") for route in observed.registry.routes] == [
        route.model_dump(mode="json") for route in baseline.registry.routes
    ]

    baseline_request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=baseline.registry,
        quota_ledger=baseline.quota_ledger,
        now=NOW,
    )
    observed_request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=_task_fields(),
        registry=observed.registry,
        quota_ledger=observed.quota_ledger,
        now=NOW,
    )

    observed_decision = evaluate_dispatch_policy(observed_request, now=NOW)
    baseline_decision = evaluate_dispatch_policy(baseline_request, now=NOW)
    assert observed_decision.model_dump(mode="json") == baseline_decision.model_dump(mode="json")
    serialized_decision = json.dumps(observed_decision.model_dump(mode="json"), sort_keys=True)
    assert "observation_metadata_invalid_fail_local" not in serialized_decision
    assert "not-a-duration" not in serialized_decision


def test_non_supply_dispatch_identity_violation_still_fails_registry_closed(
    tmp_path: Path,
) -> None:
    payload = json.loads(PLATFORM_CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    target = next(
        shape
        for shape in payload["omitted_capability_shapes"]
        if shape["shape_id"] == "local_compute.agentic_trust_evaluator_surface"
    )
    target["demand_eligible"] = True
    poisoned_registry = tmp_path / "platform-capability-registry.json"
    poisoned_registry.write_text(json.dumps(payload), encoding="utf-8")

    sources = load_dispatch_policy_sources(
        registry_path=poisoned_registry,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        receipt_dir=tmp_path / "empty-receipts",
        now=NOW,
    )

    assert sources.registry is None
    assert sources.registry_error is not None
    assert "cannot become demand eligible" in sources.registry_error


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
        "shared.dispatcher_policy.load_quota_spend_ledger_resolved",
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


def test_policy_sources_do_not_mask_unexpected_quota_runtime_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_unexpectedly(*, live_path: Path | None = None) -> object:
        raise RuntimeError("unexpected quota resolver bug")

    monkeypatch.setattr(
        "shared.dispatcher_policy.load_quota_spend_ledger_resolved",
        fail_unexpectedly,
    )

    with pytest.raises(RuntimeError, match="unexpected quota resolver bug"):
        load_dispatch_policy_sources()


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
