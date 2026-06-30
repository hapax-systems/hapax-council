"""Tests for the MonDLC g2 legal-posture registry gate."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from shared.capdlc_lifecycle import CAPDLC_DARK_STUB, CapDLCLifecycleState
from shared.legal_posture_registry import (
    G2GateInput,
    G2Reason,
    LegalPostureRefusal,
    LegalPostureRegistry,
    evaluate_g2_commit_gate,
    require_g2_commit_admitted,
)

TODAY = date(2026, 6, 30)
TARGET = G2GateInput(
    surface="bug_bounty",
    venue="hackerone",
    instrument="universal_jailbreak_bounty",
)


def _row(
    *,
    surface: str = TARGET.surface,
    venue: str = TARGET.venue,
    instrument: str = TARGET.instrument,
    verdict: str = "DARK",
    review_date: str = "2026-06-30",
    ttl: int = 180,
    operator_signed: bool = False,
    open_questions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "surface": surface,
        "venue": venue,
        "instrument": instrument,
        "g2_verdict": verdict,
        "citation": "test fixture citation",
        "authority_basis": "legal_opinion" if verdict != "DARK" else "no_research",
        "review_date": review_date,
        "freshness_ttl_days": ttl,
        "operator_signed": operator_signed,
        "operator_sign_date": "2026-06-30" if operator_signed else None,
        "notes": "fixture",
        "open_questions": open_questions or [],
        "blocks_surfaces": [surface],
        "source_task": "20260628-registry-phase7-mdlc-g2-gate-wire",
    }


def _registry(*rows: dict[str, Any]) -> LegalPostureRegistry:
    return LegalPostureRegistry.from_mapping(
        {
            "schema_version": "1.0.0",
            "schema_doc": "docs/monetization/legal-posture-registry-schema.md",
            "rows": list(rows),
        }
    )


def test_legal_registry_g2_missing_row_blocks_committed_disposition() -> None:
    decision = evaluate_g2_commit_gate(TARGET, registry=_registry(), today=TODAY)

    assert decision.blocked is True
    assert decision.reason is G2Reason.NO_EXACT_ROW
    assert decision.row is None


def test_legal_registry_g2_dark_row_blocks_committed_disposition() -> None:
    decision = evaluate_g2_commit_gate(TARGET, registry=_registry(_row()), today=TODAY)

    assert decision.blocked is True
    assert decision.reason is G2Reason.DARK_ROW
    assert decision.row is not None
    assert decision.row.verdict == "DARK"


def test_legal_registry_g2_partial_row_blocks_committed_disposition() -> None:
    decision = evaluate_g2_commit_gate(
        TARGET,
        registry=_registry(_row(verdict="PARTIAL", operator_signed=True)),
        today=TODAY,
    )

    assert decision.blocked is True
    assert decision.reason is G2Reason.PARTIAL_NOT_COMMITTABLE


def test_legal_registry_g2_stale_lit_row_blocks_committed_disposition() -> None:
    decision = evaluate_g2_commit_gate(
        TARGET,
        registry=_registry(
            _row(verdict="LIT", review_date="2026-01-01", ttl=90, operator_signed=True)
        ),
        today=TODAY,
    )

    assert decision.blocked is True
    assert decision.reason is G2Reason.STALE_NON_DARK
    assert decision.stale is True


def test_legal_registry_g2_unsigned_lit_row_blocks_committed_disposition() -> None:
    decision = evaluate_g2_commit_gate(
        TARGET,
        registry=_registry(_row(verdict="LIT", operator_signed=False)),
        today=TODAY,
    )

    assert decision.blocked is True
    assert decision.reason is G2Reason.UNSIGNED_NON_DARK


def test_legal_registry_g2_fresh_lit_row_admits_only_named_tuple() -> None:
    registry = _registry(_row(verdict="LIT", operator_signed=True))

    exact = evaluate_g2_commit_gate(TARGET, registry=registry, today=TODAY)
    other_surface = evaluate_g2_commit_gate(
        G2GateInput("prediction_market", TARGET.venue, TARGET.instrument),
        registry=registry,
        today=TODAY,
    )
    other_venue = evaluate_g2_commit_gate(
        G2GateInput(TARGET.surface, "anthropic", TARGET.instrument),
        registry=registry,
        today=TODAY,
    )
    other_instrument = evaluate_g2_commit_gate(
        G2GateInput(TARGET.surface, TARGET.venue, "paid_private_exploit_brokerage"),
        registry=registry,
        today=TODAY,
    )

    assert exact.admitted is True
    assert exact.reason is G2Reason.FRESH_LIT
    assert other_surface.blocked is True
    assert other_venue.blocked is True
    assert other_instrument.blocked is True
    assert {other_surface.reason, other_venue.reason, other_instrument.reason} == {
        G2Reason.NO_EXACT_ROW
    }


def test_legal_registry_g2_wildcard_lit_is_not_commit_authority() -> None:
    decision = evaluate_g2_commit_gate(
        TARGET,
        registry=_registry(_row(venue="*", instrument="*", verdict="LIT", operator_signed=True)),
        today=TODAY,
    )

    assert decision.blocked is True
    assert decision.reason is G2Reason.NO_EXACT_ROW
    assert decision.advisory_row is not None
    assert decision.advisory_row.venue == "*"


def test_legal_registry_g2_missing_registry_file_fails_closed(tmp_path: Path) -> None:
    decision = evaluate_g2_commit_gate(
        TARGET,
        registry_path=tmp_path / "missing-registry.yaml",
        today=TODAY,
    )

    assert decision.blocked is True
    assert decision.reason is G2Reason.REGISTRY_UNREADABLE


def test_legal_registry_g2_refusal_carries_decision() -> None:
    with pytest.raises(LegalPostureRefusal) as exc_info:
        require_g2_commit_admitted(TARGET, registry=_registry(_row()), today=TODAY)

    assert exc_info.value.decision.reason is G2Reason.DARK_ROW


def test_mondlc_g2_is_separate_from_g1_counterparty_and_capdlc_m_measurement() -> None:
    assert set(G2GateInput.__dataclass_fields__) == {"surface", "venue", "instrument"}
    assert "counterparty_class" not in G2GateInput.__dataclass_fields__
    assert "measured_value" not in G2GateInput.__dataclass_fields__
    assert CAPDLC_DARK_STUB.lifecycle_state is CapDLCLifecycleState.DARK_SPECIFIED
    assert CAPDLC_DARK_STUB.is_measured is False

    decision = evaluate_g2_commit_gate(
        TARGET,
        registry=_registry(_row(verdict="LIT", operator_signed=True)),
        today=TODAY,
    )

    assert decision.admitted is True
    assert bool(CAPDLC_DARK_STUB) is False
