"""Tests for the support-copy readiness gate."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.conversion_target_readiness import REQUIRED_GATE_DIMENSIONS, GateDimension
from shared.monetization_readiness_ledger import (
    GateDimensionEvidence,
    MonetizationReadinessLedger,
    MonetizationReadinessSnapshot,
    evaluate_default_monetization_readiness,
)
from shared.support_copy_readiness import (
    PROHIBITED_SUPPORT_COPY_SHAPES,
    PUBLIC_TRUTH_DIMENSIONS,
    SupportCopyConsumerReadiness,
    evaluate_support_copy_readiness,
)
from shared.support_surface_registry import SupportSurfaceRegistry, load_support_surface_registry

NOW = datetime(2026, 5, 2, 11, 50, tzinfo=UTC)
ALL_DIMS: frozenset[GateDimension] = frozenset(REQUIRED_GATE_DIMENSIONS)


def _snapshot(satisfied: frozenset[GateDimension]) -> MonetizationReadinessSnapshot:
    return MonetizationReadinessSnapshot(
        captured_at=NOW,
        snapshot_source="test",
        evidence={
            dim: GateDimensionEvidence(
                dimension=dim,
                satisfied=dim in satisfied,
                evidence_refs=(f"evidence:{dim}",) if dim in satisfied else (),
                operator_visible_reason=(
                    f"{dim} satisfied" if dim in satisfied else f"{dim} missing"
                ),
            )
            for dim in REQUIRED_GATE_DIMENSIONS
        },
    )


def _ledger(satisfied: frozenset[GateDimension]) -> MonetizationReadinessLedger:
    return evaluate_default_monetization_readiness(_snapshot(satisfied))


def _registry() -> SupportSurfaceRegistry:
    return load_support_surface_registry()


def _refs(*, money: bool = True, no_perk: bool = True) -> dict[str, bool]:
    return {
        "support_surface_registry.no_perk_copy_valid": no_perk,
        "MonetizationReadiness.safe_to_publish_offer": money,
    }


def test_missing_registry_is_unavailable_and_fails_closed() -> None:
    decision = evaluate_support_copy_readiness(None, _ledger(ALL_DIMS), readiness_refs=_refs())

    assert decision.state == "unavailable"
    assert decision.public_copy_allowed is False
    assert "support_surface_registry_missing" in decision.blockers
    assert all(not state.public_copy_allowed for state in decision.consumer_states)


def test_missing_no_perk_registry_ref_requires_bootstrap() -> None:
    decision = evaluate_support_copy_readiness(
        _registry(),
        _ledger(ALL_DIMS),
        readiness_refs=_refs(no_perk=False),
    )

    assert decision.state == "bootstrap-needed"
    assert decision.public_copy_allowed is False
    assert decision.missing_readiness_refs == ("support_surface_registry.no_perk_copy_valid",)


def test_public_truth_missing_is_registry_ready_but_not_public_safe() -> None:
    decision = evaluate_support_copy_readiness(
        _registry(), _ledger(frozenset()), readiness_refs=_refs()
    )

    assert decision.state == "registry-ready"
    assert decision.public_copy_allowed is False
    assert "public_event" in decision.missing_gate_dimensions
    assert decision.consumer_state("public_offer_page").support_invitation_allowed is False


def test_public_truth_without_monetization_is_held() -> None:
    satisfied = PUBLIC_TRUTH_DIMENSIONS
    decision = evaluate_support_copy_readiness(
        _registry(),
        _ledger(satisfied),
        readiness_refs=_refs(money=False),
    )

    assert decision.state == "monetization-held"
    assert decision.public_copy_allowed is False
    assert "monetization_readiness_missing" in decision.blockers
    assert "MonetizationReadiness.safe_to_publish_offer" in decision.missing_readiness_refs


def test_refused_generic_surface_emits_conversion_explanation() -> None:
    decision = evaluate_support_copy_readiness(
        _registry(),
        _ledger(ALL_DIMS),
        readiness_refs=_refs(),
        surface_id="patreon",
    )

    assert decision.state == "refused"
    assert decision.public_copy_allowed is False
    assert decision.refusal_brief_refs
    assert decision.buildable_conversion
    assert decision.allowed_public_copy == ()


def test_full_evidence_and_refs_returns_public_safe_machine_state() -> None:
    decision = evaluate_support_copy_readiness(
        _registry(), _ledger(ALL_DIMS), readiness_refs=_refs()
    )

    assert decision.state == "public-safe"
    assert decision.public_copy_allowed is True
    assert decision.allowed_public_copy
    assert "No access" in " ".join(decision.allowed_public_copy)
    assert set(PROHIBITED_SUPPORT_COPY_SHAPES) <= set(decision.prohibited_copy_shapes)

    for consumer in (
        "public_offer_page",
        "youtube_copy",
        "cross_surface_legibility_pack",
        "public_package_surface",
        "github_readme",
    ):
        state = decision.consumer_state(consumer)
        assert state.readiness_state == "public-safe"
        assert state.public_copy_allowed is True
        assert state.support_invitation_allowed is True
        assert state.issue_invitation_allowed is False
        assert state.licensing_negotiation_allowed is False
        assert state.customer_service_expectation_allowed is False


def test_readme_and_package_cannot_invite_support_before_public_safe() -> None:
    decision = evaluate_support_copy_readiness(
        _registry(), _ledger(frozenset()), readiness_refs=_refs()
    )

    for consumer in ("github_readme", "public_package_surface"):
        state = decision.consumer_state(consumer)
        assert state.public_copy_allowed is False
        assert state.support_invitation_allowed is False
        assert state.issue_invitation_allowed is False
        assert state.licensing_negotiation_allowed is False
        assert state.customer_service_expectation_allowed is False


def test_consumer_state_rejects_public_flags_before_public_safe() -> None:
    with pytest.raises(ValidationError, match="before public-safe"):
        SupportCopyConsumerReadiness(
            consumer="github_readme",
            readiness_state="registry-ready",
            public_copy_allowed=False,
            support_invitation_allowed=True,
        )
