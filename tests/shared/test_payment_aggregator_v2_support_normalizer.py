"""Tests for the payment-aggregator v2 support normalizer.

cc-task: payment-aggregator-v2-support-normalizer.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

import shared.payment_aggregator_v2_support_normalizer as normalizer_module
from shared.payment_aggregator_v2_support_normalizer import (
    CurrencyUnit,
    EventType,
    MonetizationReadinessGate,
    NormalizedSupportReceipt,
    NormalizerVerdict,
    PublicEmitDecision,
    Rail,
    SupportSurfaceApproval,
    Visibility,
    evaluate_public_emit,
    render_public_aggregate_text,
)


def _receipt(
    *,
    rail: Rail = Rail.LIBERAPAY,
    visibility: Visibility = Visibility.AGGREGATE_PUBLIC,
    receipt_id_suffix: str = "001",
    amount: float = 5.0,
    currency: CurrencyUnit | None = None,
) -> NormalizedSupportReceipt:
    if currency is None:
        currency = {
            Rail.LIGHTNING: CurrencyUnit.SATS,
            Rail.NOSTR_ZAP: CurrencyUnit.SATS,
            Rail.LIBERAPAY: CurrencyUnit.EUR,
            Rail.KOFI_GUARDED: CurrencyUnit.USD,
            Rail.YOUTUBE_FAN_FUNDING: CurrencyUnit.USD,
        }[rail]
    return NormalizedSupportReceipt(
        receipt_id=f"r-{rail.value}-{receipt_id_suffix}".lower(),
        rail=rail,
        amount=amount,
        currency_unit=currency,
        timestamp=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        event_type=EventType.SUPPORT_RECEIVED,
        visibility=visibility,
    )


def _approval(rail: Rail, *, approved: bool = True) -> SupportSurfaceApproval:
    return SupportSurfaceApproval(rail=rail, approved=approved, decision_ref="ssr:test")


def _readiness(safe: bool = True) -> MonetizationReadinessGate:
    return MonetizationReadinessGate(
        safe_to_monetize=safe,
        captured_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        snapshot_source="test-fixture",
    )


def test_normalized_receipt_constructs_for_each_rail():
    for rail in Rail:
        r = _receipt(rail=rail)
        assert r.rail is rail


def test_normalized_receipt_required_fields_match_acceptance():
    expected = {
        "receipt_id",
        "rail",
        "amount",
        "currency_unit",
        "timestamp",
        "event_type",
        "visibility",
    }
    assert expected.issubset(NormalizedSupportReceipt.model_fields.keys())


def test_normalized_receipt_refuses_payer_identity_fields():
    """Receipt schema has no PII fields and refuses extras at construction."""
    base = {
        "receipt_id": "r-test-001",
        "rail": Rail.LIBERAPAY,
        "amount": 5.0,
        "currency_unit": CurrencyUnit.EUR,
        "timestamp": datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        "event_type": EventType.SUPPORT_RECEIVED,
        "visibility": Visibility.AGGREGATE_PUBLIC,
    }
    for forbidden in (
        "name",
        "email",
        "handle",
        "payer_id",
        "message",
        "comment",
        "sender_excerpt",
    ):
        with pytest.raises(Exception):
            NormalizedSupportReceipt(**base, **{forbidden: "operator-only-data"})


def test_rail_currency_mismatch_rejected():
    with pytest.raises(Exception, match="currency_unit"):
        NormalizedSupportReceipt(
            receipt_id="r-test-001",
            rail=Rail.LIBERAPAY,
            amount=5.0,
            currency_unit=CurrencyUnit.SATS,
            timestamp=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            event_type=EventType.SUPPORT_RECEIVED,
            visibility=Visibility.AGGREGATE_PUBLIC,
        )


def test_amount_must_be_positive():
    with pytest.raises(Exception):
        _receipt(amount=0)


def test_module_exposes_no_send_or_payout_functions():
    """Acceptance §5: receive-only — block send/payout/transfer behavior."""
    forbidden_substrings = ("send", "payout", "transfer", "refund", "withdraw", "initiate")
    for name, member in inspect.getmembers(normalizer_module):
        if name.startswith("_"):
            continue
        if not (inspect.isfunction(member) or inspect.isclass(member)):
            continue
        lower = name.lower()
        for s in forbidden_substrings:
            assert s not in lower, f"forbidden substring {s!r} in public name {name!r}"


def test_public_emit_succeeds_for_approved_safe_window():
    rail = Rail.LIBERAPAY
    receipts = (
        _receipt(rail=rail, receipt_id_suffix="001"),
        _receipt(rail=rail, receipt_id_suffix="002"),
    )
    decision = evaluate_public_emit(
        rail,
        receipts,
        surface_approval=_approval(rail),
        readiness=_readiness(safe=True),
        window_start=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
        window_end=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
        captured_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
    )
    assert decision.verdict is NormalizerVerdict.EMITTED
    assert decision.emission is not None
    assert decision.emission.receipt_count == 2
    assert decision.emission.total_amount == 10.0


def test_public_emit_refused_when_surface_not_approved():
    rail = Rail.KOFI_GUARDED
    decision = evaluate_public_emit(
        rail,
        (_receipt(rail=rail),),
        surface_approval=_approval(rail, approved=False),
        readiness=_readiness(safe=True),
        window_start=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
        window_end=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
        captured_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
    )
    assert decision.verdict is NormalizerVerdict.REFUSED_NOT_APPROVED
    assert decision.emission is None


def test_public_emit_refused_when_not_safe_to_monetize():
    rail = Rail.LIBERAPAY
    decision = evaluate_public_emit(
        rail,
        (_receipt(rail=rail),),
        surface_approval=_approval(rail),
        readiness=_readiness(safe=False),
        window_start=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
        window_end=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
        captured_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
    )
    assert decision.verdict is NormalizerVerdict.REFUSED_NOT_SAFE_TO_MONETIZE


def test_public_emit_refused_when_all_receipts_private_only():
    rail = Rail.LIBERAPAY
    decision = evaluate_public_emit(
        rail,
        (_receipt(rail=rail, visibility=Visibility.PRIVATE_ONLY),),
        surface_approval=_approval(rail),
        readiness=_readiness(safe=True),
        window_start=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
        window_end=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
        captured_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
    )
    assert decision.verdict is NormalizerVerdict.REFUSED_PRIVATE_ONLY


def test_public_emit_refused_when_no_receipts():
    rail = Rail.YOUTUBE_FAN_FUNDING
    decision = evaluate_public_emit(
        rail,
        (),
        surface_approval=_approval(rail),
        readiness=_readiness(safe=True),
        window_start=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
        window_end=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
        captured_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
    )
    assert decision.verdict is NormalizerVerdict.REFUSED_NO_RECEIPTS


def test_public_emit_filters_to_target_rail_only():
    rail = Rail.LIBERAPAY
    other = _receipt(rail=Rail.LIGHTNING, amount=1000)
    target = _receipt(rail=rail, amount=5)
    decision = evaluate_public_emit(
        rail,
        (other, target),
        surface_approval=_approval(rail),
        readiness=_readiness(safe=True),
        window_start=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
        window_end=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
        captured_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
    )
    assert decision.emission is not None
    assert decision.emission.receipt_count == 1
    assert decision.emission.total_amount == 5.0


def test_evaluate_public_emit_rejects_mismatched_approval_rail():
    with pytest.raises(ValueError, match="surface_approval rail"):
        evaluate_public_emit(
            Rail.LIBERAPAY,
            (),
            surface_approval=_approval(Rail.LIGHTNING),
            readiness=_readiness(safe=True),
            window_start=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
            window_end=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
            captured_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
        )


def test_render_public_aggregate_text_contains_no_pii_fields():
    rail = Rail.LIBERAPAY
    receipts = (_receipt(rail=rail, receipt_id_suffix="aa", amount=3.0),)
    decision = evaluate_public_emit(
        rail,
        receipts,
        surface_approval=_approval(rail),
        readiness=_readiness(safe=True),
        window_start=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
        window_end=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
        captured_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
    )
    text = render_public_aggregate_text(decision.emission)
    assert "1 aggregate receipts" in text
    assert "3.0 eur" in text.lower() or "3 eur" in text.lower()
    for forbidden in ("name", "email", "@", "message", "comment", "handle", "payer"):
        assert forbidden not in text.lower(), f"public emission leaked {forbidden!r}"


def test_window_end_must_be_at_or_after_window_start():
    rail = Rail.LIBERAPAY
    with pytest.raises(Exception, match="window_end"):
        evaluate_public_emit(
            rail,
            (_receipt(rail=rail),),
            surface_approval=_approval(rail),
            readiness=_readiness(safe=True),
            window_start=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
            window_end=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
            captured_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
        )


def test_public_emit_decision_requires_emission_when_emitted():
    with pytest.raises(Exception, match="EMITTED verdict requires"):
        PublicEmitDecision(
            rail=Rail.LIBERAPAY,
            verdict=NormalizerVerdict.EMITTED,
            reason="missing emission",
        )


def test_public_emit_decision_rejects_emission_when_refused():
    rail = Rail.LIBERAPAY
    receipts = (_receipt(rail=rail),)
    decision_ok = evaluate_public_emit(
        rail,
        receipts,
        surface_approval=_approval(rail),
        readiness=_readiness(safe=True),
        window_start=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
        window_end=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
        captured_at=datetime(2026, 5, 2, 13, 0, tzinfo=UTC),
    )
    with pytest.raises(Exception, match="cannot carry an emission"):
        PublicEmitDecision(
            rail=rail,
            verdict=NormalizerVerdict.REFUSED_NOT_APPROVED,
            emission=decision_ok.emission,
            reason="contradictory",
        )


def test_currency_unit_per_rail_invariants():
    expected = {
        Rail.LIGHTNING: CurrencyUnit.SATS,
        Rail.NOSTR_ZAP: CurrencyUnit.SATS,
        Rail.LIBERAPAY: CurrencyUnit.EUR,
        Rail.KOFI_GUARDED: CurrencyUnit.USD,
        Rail.YOUTUBE_FAN_FUNDING: CurrencyUnit.USD,
    }
    for rail, currency in expected.items():
        receipt = _receipt(rail=rail, currency=currency)
        assert receipt.currency_unit is currency
