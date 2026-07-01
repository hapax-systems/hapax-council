"""Tests for the MonDLC G1 counterparty eligibility gate."""

from __future__ import annotations

import pytest

from shared.capdlc_lifecycle import GateStatus
from shared.mdlc_g1_counterparty import (
    ELIGIBLE_COUNTERPARTY_CLASSES,
    ArbitrageRefusal,
    G1CounterpartyRefusalReason,
    MonDLCCounterparty,
    MonDLCCounterpartyClass,
    require_g1_counterparty,
    verify_g1_counterparty,
)


def _counterparty(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "counterparty_id": "counterparty:test-market-maker",
        "counterparty_class": "institution",
        "evidence_refs": ("counterparty-registry:test-market-maker",),
    }
    data.update(overrides)
    return data


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
    assert "counterparty:counterparty:test-market-maker" in result.evidence_refs


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


def test_invalid_evidence_refs_has_specific_refusal_reason() -> None:
    result = verify_g1_counterparty(_counterparty(evidence_refs="not-a-sequence"))

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G1CounterpartyRefusalReason.INVALID_EVIDENCE_REFS


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
