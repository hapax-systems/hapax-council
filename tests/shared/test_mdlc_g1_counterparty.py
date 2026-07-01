"""Tests for the MonDLC G1 counterparty eligibility gate."""

from __future__ import annotations

import pytest

from shared.capdlc_lifecycle import GateResult, GateStatus
from shared.mdlc_g1_counterparty import (
    ELIGIBLE_COUNTERPARTY_CLASSES,
    ArbitrageRefusal,
    G1CounterpartyRefusalReason,
    G1CounterpartyVerification,
    MonDLCCounterparty,
    MonDLCCounterpartyClass,
    require_g1_counterparty,
    verify_g1_counterparty,
)

EXPECTED_ELIGIBLE_CLASSES = {
    "institution",
    "market",
    "corporation",
    "sophisticated_party",
    "the_wealthy",
}


def _counterparty(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "counterparty_id": "counterparty:test-market-maker",
        "counterparty_class": "institution",
        "evidence_refs": ("counterparty-registry:test-market-maker",),
    }
    data.update(overrides)
    return data


def test_eligible_counterparty_class_contract_is_exact() -> None:
    assert ELIGIBLE_COUNTERPARTY_CLASSES == EXPECTED_ELIGIBLE_CLASSES
    assert {item.value for item in MonDLCCounterpartyClass} == EXPECTED_ELIGIBLE_CLASSES


@pytest.mark.parametrize("counterparty_class", sorted(ELIGIBLE_COUNTERPARTY_CLASSES))
def test_allowed_counterparty_classes_are_lit(counterparty_class: str) -> None:
    result = verify_g1_counterparty(_counterparty(counterparty_class=counterparty_class))

    assert result.status is GateStatus.LIT
    assert result.ok is True
    assert result.gate_result.verdict is True
    assert result.reason == "counterparty_class_eligible"
    assert result.refusal_reason is None
    assert result.counterparty_class == counterparty_class
    assert f"counterparty-class:{counterparty_class}" in result.evidence_refs
    assert "counterparty:test-market-maker" in result.evidence_refs


def test_lit_result_to_dict_preserves_gate_contract() -> None:
    result = verify_g1_counterparty(_counterparty(counterparty_class="market"))

    data = result.to_dict()

    assert data["validator"] == "mdlc_g1_counterparty"
    assert data["status"] == "lit"
    assert data["ok"] is True
    assert data["reason"] == "counterparty_class_eligible"
    assert data["refusal_reason"] is None
    assert data["counterparty_class"] == "market"
    assert data["counterparty_id"] == "counterparty:test-market-maker"
    assert data["gate_result"] == {
        "status": "lit",
        "verdict": True,
        "reason": "counterparty_class_eligible",
        "evidence_refs": list(result.evidence_refs),
    }


def test_counterparty_to_dict_preserves_normalized_fields() -> None:
    counterparty = require_g1_counterparty(
        _counterparty(counterparty_class=" Institution ", counterparty_id=" counterparty:abc ")
    )

    assert counterparty.to_dict() == {
        "counterparty_class": "institution",
        "counterparty_id": "counterparty:abc",
        "evidence_refs": ["counterparty-registry:test-market-maker"],
    }


def test_native_counterparty_constructor_coerces_string_class() -> None:
    counterparty = MonDLCCounterparty(
        counterparty_class=" Market ",  # type: ignore[arg-type]
        counterparty_id="market-maker-1",
    )

    assert counterparty.counterparty_class is MonDLCCounterpartyClass.MARKET
    result = verify_g1_counterparty(counterparty)
    assert "counterparty:market-maker-1" in result.evidence_refs


def test_native_counterparty_class_is_accepted() -> None:
    result = verify_g1_counterparty(
        MonDLCCounterparty(
            counterparty_class=MonDLCCounterpartyClass.SOPHISTICATED_PARTY,
            counterparty_id="counterparty:sophisticated",
        )
    )

    assert result.status is GateStatus.LIT
    assert result.counterparty_class == "sophisticated_party"


def test_counterparty_verification_truthiness_is_not_allowed() -> None:
    result = verify_g1_counterparty(_counterparty())

    with pytest.raises(TypeError, match="truthiness is undefined"):
        bool(result)


def test_require_success_returns_counterparty() -> None:
    counterparty = require_g1_counterparty(_counterparty(counterparty_class="market"))

    assert counterparty.counterparty_class is MonDLCCounterpartyClass.MARKET
    assert counterparty.counterparty_id == "counterparty:test-market-maker"


def test_missing_counterparty_refuses_before_m2_commit() -> None:
    result = verify_g1_counterparty(None)

    assert result.status is GateStatus.DARK
    assert result.ok is False
    assert result.gate_result.verdict is None
    assert result.refusal_reason is G1CounterpartyRefusalReason.MISSING_COUNTERPARTY
    assert result.next_action == "attach a counterparty record before M2 commit"


@pytest.mark.parametrize("missing_value", (None, "", "   "))
def test_missing_counterparty_class_refuses(missing_value: object) -> None:
    result = verify_g1_counterparty(_counterparty(counterparty_class=missing_value))

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G1CounterpartyRefusalReason.MISSING_COUNTERPARTY_CLASS
    assert "record one eligible counterparty class" in result.next_action


@pytest.mark.parametrize("counterparty_class", ("retail", "general_public", "operator"))
def test_ineligible_counterparty_class_refuses_and_require_raises(
    counterparty_class: str,
) -> None:
    result = verify_g1_counterparty(_counterparty(counterparty_class=counterparty_class))

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G1CounterpartyRefusalReason.INELIGIBLE_COUNTERPARTY_CLASS
    assert result.gate_result.evidence_refs == ()

    with pytest.raises(ArbitrageRefusal) as exc:
        require_g1_counterparty(_counterparty(counterparty_class=counterparty_class))
    assert (
        exc.value.verification.refusal_reason
        is G1CounterpartyRefusalReason.INELIGIBLE_COUNTERPARTY_CLASS
    )


def test_invalid_counterparty_shape_refuses() -> None:
    result = verify_g1_counterparty(object())

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G1CounterpartyRefusalReason.INVALID_COUNTERPARTY


def test_invalid_optional_counterparty_id_refuses_with_counterparty_reason() -> None:
    result = verify_g1_counterparty(_counterparty(counterparty_id=123))

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G1CounterpartyRefusalReason.INVALID_COUNTERPARTY


def test_invalid_evidence_refs_has_specific_refusal_reason() -> None:
    result = verify_g1_counterparty(_counterparty(evidence_refs="not-a-sequence"))

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G1CounterpartyRefusalReason.INVALID_EVIDENCE_REFS


def test_invalid_evidence_ref_item_has_specific_refusal_reason() -> None:
    result = verify_g1_counterparty(_counterparty(evidence_refs=("valid-ref", 123)))

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G1CounterpartyRefusalReason.INVALID_EVIDENCE_REFS


def test_missing_evidence_refs_are_optional() -> None:
    payload = {
        "counterparty_id": "counterparty:no-refs",
        "counterparty_class": "institution",
    }

    result = verify_g1_counterparty(payload)

    assert result.status is GateStatus.LIT
    assert result.evidence_refs == (
        "counterparty-class:institution",
        "counterparty:no-refs",
    )


def test_dark_result_to_dict_preserves_refusal_contract() -> None:
    result = verify_g1_counterparty(_counterparty(counterparty_class="retail"))

    data = result.to_dict()

    assert data["status"] == "dark"
    assert data["ok"] is False
    assert data["refusal_reason"] == "ineligible_counterparty_class"
    assert data["counterparty_class"] is None
    assert data["counterparty_id"] is None
    assert data["evidence_refs"] == []
    assert data["gate_result"]["status"] == "dark"
    assert data["gate_result"]["verdict"] is None


def test_verification_constructor_rejects_invalid_status_type() -> None:
    with pytest.raises(TypeError, match="status"):
        G1CounterpartyVerification(
            validator="mdlc_g1_counterparty",
            validator_version=1,
            status="lit",  # type: ignore[arg-type]
            gate_result=GateResult(status=GateStatus.LIT, verdict=True, reason="ok"),
            reason="ok",
            refusal_reason=None,
        )


def test_verification_constructor_rejects_invalid_gate_result_type() -> None:
    with pytest.raises(TypeError, match="gate_result"):
        G1CounterpartyVerification(
            validator="mdlc_g1_counterparty",
            validator_version=1,
            status=GateStatus.LIT,
            gate_result=object(),  # type: ignore[arg-type]
            reason="ok",
            refusal_reason=None,
        )


def test_verification_constructor_rejects_invalid_refusal_reason_type() -> None:
    with pytest.raises(TypeError, match="refusal_reason"):
        G1CounterpartyVerification(
            validator="mdlc_g1_counterparty",
            validator_version=1,
            status=GateStatus.DARK,
            gate_result=GateResult(status=GateStatus.DARK, verdict=None, reason="blocked"),
            reason="blocked",
            refusal_reason="blocked",  # type: ignore[arg-type]
        )


def test_g1_does_not_decide_g2_venue_or_instrument_legality() -> None:
    result = verify_g1_counterparty(
        _counterparty(
            counterparty_class="corporation",
            venue="minnesota",
            instrument="prediction_market",
            legal_posture="DARK",
        )
    )

    assert result.status is GateStatus.LIT
    assert result.counterparty_class == "corporation"


def test_g1_refusal_is_class_based_not_g2_surface_based() -> None:
    result = verify_g1_counterparty(
        _counterparty(
            counterparty_class="individual",
            venue="ndcvb-feed",
            instrument="receipt-feed",
            legal_posture="LIT",
        )
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G1CounterpartyRefusalReason.INELIGIBLE_COUNTERPARTY_CLASS


def test_g1_does_not_score_m_value_measurement_fields() -> None:
    result = verify_g1_counterparty(
        _counterparty(
            counterparty_class="the_wealthy",
            measurement=-1_000_000.0,
            observed_at=None,
            provenance="projected",
        )
    )

    assert result.status is GateStatus.LIT
    assert result.counterparty_class == "the_wealthy"
