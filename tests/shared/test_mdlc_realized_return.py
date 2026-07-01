"""Tests for the MonDLC realized-return rail boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import shared.durable_jsonl_sink as sink_mod
import shared.mdlc_realized_return as realized_return_mod
from shared.capdlc_lifecycle import GateStatus
from shared.mdlc_measure import MonDLCLadder, MonDLCVerdict, score
from shared.modern_treasury_receive_only_rail import (
    IncomingPaymentEvent,
    IncomingPaymentEventKind,
    PaymentMethod,
)
from shared.open_collective_receive_only_rail import OpenCollectiveRailReceiver
from shared.stripe_payment_link_receive_only_rail import (
    StripePaymentLinkRailReceiver,
)
from shared.treasury_prime_receive_only_rail import TreasuryPrimeRailReceiver

NOW = datetime(2026, 7, 1, 6, 0, tzinfo=UTC)
RAW_SHA = "a" * 64
HASH = "ruler-hash-fixture"


def _accepted_event(event_kind: str, **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_kind": event_kind,
        "amount_currency_cents": 1200,
        "currency": "USD",
        "occurred_at": NOW,
        "raw_payload_sha256": RAW_SHA,
        "source_amount_sign": "positive",
    }
    if event_kind in realized_return_mod.DIRECTION_FILTERED_EVENT_KINDS:
        event["direction"] = "credit"
    if event_kind == "checkout_session_completed":
        event.update(
            {
                "mode": "payment",
                "payment_status": "paid",
                "payment_intent": "pi_test_checkout",
            }
        )
    event.update(overrides)
    return event


def _durable_event(event_kind: str, **overrides: object) -> dict[str, object]:
    event = _accepted_event(event_kind, occurred_at=NOW.isoformat().replace("+00:00", "Z"))
    event.update(overrides)
    return event


def _directionless_event(event_kind: str) -> dict[str, object]:
    event = _accepted_event(event_kind)
    event.pop("direction", None)
    return event


def _open_collective_transaction_payload(
    *,
    value: float | int | str = 5.0,
    currency: str = "USD",
) -> dict[str, object]:
    return {
        "type": "collective_transaction_created",
        "createdAt": NOW.isoformat().replace("+00:00", "Z"),
        "data": {
            "fromCollective": {"slug": "alice"},
            "transaction": {"amount": {"value": value, "currency": currency}},
        },
    }


def _stripe_checkout_session_payload(
    *,
    mode: str | None = None,
    payment_status: str | None = None,
    payment_intent: str | None = None,
    subscription: str | None = None,
) -> dict[str, object]:
    session: dict[str, object] = {
        "id": "cs_test_mondlc",
        "object": "checkout.session",
        "customer": "cus_TestCheckout",
        "amount_total": 5000,
        "amount_subtotal": 5000,
        "currency": "usd",
    }
    if mode is not None:
        session["mode"] = mode
    if payment_status is not None:
        session["payment_status"] = payment_status
    if payment_intent is not None:
        session["payment_intent"] = payment_intent
    if subscription is not None:
        session["subscription"] = subscription
    return {
        "id": "evt_test_checkout",
        "type": "checkout.session.completed",
        "created": 1_745_000_010,
        "data": {"object": session},
    }


def _stripe_payment_intent_payload(
    *,
    amount: int = 2500,
    currency: str = "usd",
) -> dict[str, object]:
    return {
        "id": "evt_test_payment_intent_mondlc",
        "type": "payment_intent.succeeded",
        "created": 1_745_000_000,
        "data": {
            "object": {
                "id": "pi_test_mondlc",
                "object": "payment_intent",
                "customer": "cus_TestRail01",
                "amount": amount,
                "amount_received": amount,
                "currency": currency,
            }
        },
    }


def _treasury_prime_ach_payload(
    *,
    amount: object = 10000,
    currency: str = "USD",
) -> dict[str, object]:
    return {
        "event": "incoming_ach.create",
        "data": {
            "id": "tp-incoming-ach-mondlc",
            "amount": amount,
            "currency": currency,
            "originating_party_name": "Acme Foundation",
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
        },
    }


def _receipt(event_kind: str) -> str:
    return f"receipt://payment/test/{event_kind.replace('/', '_')}"


def _trusted_sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sink_mod.DurableJsonlSink:
    root = tmp_path / "durable"
    root.mkdir()
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "btrfs")
    return sink_mod.DurableJsonlSink(root)


def test_event_kind_contract_is_explicit_and_disjoint() -> None:
    refused = (
        realized_return_mod.MEMBERSHIP_LIFECYCLE_EVENT_KINDS
        | realized_return_mod.NON_SETTLED_INBOUND_EVENT_KINDS
        | realized_return_mod.OUTBOUND_EVENT_KINDS
        | realized_return_mod.REFUND_REVERSAL_EVENT_KINDS
        | realized_return_mod.AMBIGUOUS_BANK_TRANSACTION_EVENT_KINDS
    )

    assert realized_return_mod.REALIZED_INBOUND_EVENT_KINDS
    assert realized_return_mod.REALIZED_INBOUND_EVENT_KINDS.isdisjoint(refused)
    assert "customer_subscription_created" in realized_return_mod.MEMBERSHIP_LIFECYCLE_EVENT_KINDS
    assert "incoming_payment_detail.created" in realized_return_mod.NON_SETTLED_INBOUND_EVENT_KINDS
    assert "payment_refunded" in realized_return_mod.REFUND_REVERSAL_EVENT_KINDS
    assert "collective_transaction_created" in realized_return_mod.DIRECTION_FILTERED_EVENT_KINDS
    assert "incoming_ach.create" in realized_return_mod.DIRECTION_FILTERED_EVENT_KINDS
    assert "transaction.updated" in realized_return_mod.AMBIGUOUS_BANK_TRANSACTION_EVENT_KINDS


@pytest.mark.parametrize("event_kind", sorted(realized_return_mod.REALIZED_INBOUND_EVENT_KINDS))
def test_all_enumerated_realized_inbound_event_kinds_become_measurements(
    event_kind: str,
) -> None:
    result = realized_return_mod.realized_return_from_rail(
        _accepted_event(event_kind), source_receipt_ref=_receipt(event_kind)
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.ACCEPTED
    assert result.refusal_reason is None
    assert result.event_kind == event_kind
    assert result.amount_minor_units == 1200
    assert result.currency == "USD"
    assert result.measurement is not None
    assert result.measurement.provenance == "inbound_rail"
    assert result.measurement.value == 1200.0
    assert _receipt(event_kind) in result.evidence_refs
    assert f"payload_sha256:{RAW_SHA}" in result.evidence_refs


def test_stripe_payment_intent_measurement_scores_lit_with_two_witness_refs() -> None:
    event = _accepted_event(
        "payment_intent_succeeded",
        amount_currency_cents=2500,
        event_id="pi_test_rail_01",
    )

    rail_result = realized_return_mod.realized_return_from_rail(
        event,
        source_receipt_ref="receipt://payment/stripe/rail-test/payment_intent_succeeded",
    )
    assert rail_result.measurement is not None
    measurement = rail_result.measurement

    scored = score(
        measurement,
        MonDLCLadder(
            ruler_hash=HASH,
            min_corroboration_count=2,
            freshness_ttl_seconds=3600,
            as_of=NOW,
        ),
        ruler_hash_commit=HASH,
    )

    assert rail_result.amount_minor_units == 2500
    assert rail_result.currency == "USD"
    assert scored.status is GateStatus.LIT
    assert scored.verdict is MonDLCVerdict.CORROBORATED


def test_stripe_payment_intent_from_receiver_refuses_without_source_sign_witness() -> None:
    event = StripePaymentLinkRailReceiver().ingest_webhook(
        _stripe_payment_intent_payload(amount=-2500),
        signature=None,
    )

    result = realized_return_mod.realized_return_from_rail(
        event,
        source_receipt_ref="receipt://payment/stripe/payment-intent-succeeded",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.MISSING_SOURCE_AMOUNT_SIGN
    )
    assert result.measurement is None


def test_stripe_checkout_session_from_receiver_refuses_without_paid_one_time_witness() -> None:
    event = StripePaymentLinkRailReceiver().ingest_webhook(
        _stripe_checkout_session_payload(),
        signature=None,
    )

    result = realized_return_mod.realized_return_from_rail(
        event,
        source_receipt_ref="receipt://payment/stripe/checkout-session-completed",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.NON_SETTLED_INBOUND_EVENT
    )
    assert result.measurement is None


def test_stripe_checkout_session_paid_one_time_witness_can_measure() -> None:
    result = realized_return_mod.realized_return_from_rail(
        _accepted_event(
            "checkout_session_completed",
            mode="payment",
            payment_status="paid",
            payment_intent="pi_test_checkout",
        ),
        source_receipt_ref="receipt://payment/stripe/checkout-session-paid",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.ACCEPTED
    assert result.measurement is not None


@pytest.mark.parametrize(
    "overrides",
    (
        {"mode": "setup", "payment_status": "paid", "payment_intent": "pi_test_checkout"},
        {"mode": "subscription", "payment_status": "paid", "subscription": "sub_test"},
        {"mode": "payment", "payment_status": "unpaid", "payment_intent": "pi_test_checkout"},
        {"mode": "payment", "payment_status": "paid", "payment_intent": None},
    ),
)
def test_stripe_checkout_session_non_receipt_modes_refuse(
    overrides: dict[str, object],
) -> None:
    result = realized_return_mod.realized_return_from_rail(
        _accepted_event("checkout_session_completed", **overrides),
        source_receipt_ref="receipt://payment/stripe/checkout-session-refusal",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.NON_SETTLED_INBOUND_EVENT
    )
    assert result.measurement is None


def test_modern_treasury_created_refuses_as_non_settled_before_score_folding() -> None:
    event = IncomingPaymentEvent(
        originating_party_handle="Acme",
        amount_currency_cents=10000,
        currency="USD",
        event_kind=IncomingPaymentEventKind.CREATED,
        payment_method=PaymentMethod.ACH,
        occurred_at=NOW,
        raw_payload_sha256=RAW_SHA,
    )

    result = realized_return_mod.realized_return_from_rail(
        event, source_receipt_ref="receipt://payment/mt/created"
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.NON_SETTLED_INBOUND_EVENT
    )
    assert result.measurement is None


def test_treasury_prime_incoming_ach_requires_direction_witness() -> None:
    event = TreasuryPrimeRailReceiver().ingest_webhook(
        _treasury_prime_ach_payload(amount=-5000),
        signature=None,
    )

    result = realized_return_mod.realized_return_from_rail(
        event,
        source_receipt_ref="receipt://payment/treasury-prime/incoming-ach",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.MISSING_INBOUND_DIRECTION
    )
    assert result.measurement is None


def test_treasury_prime_incoming_ach_credit_direction_can_measure() -> None:
    result = realized_return_mod.realized_return_from_rail(
        _accepted_event("incoming_ach.create", direction="credit"),
        source_receipt_ref="receipt://payment/treasury-prime/incoming-ach-credit",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.ACCEPTED
    assert result.measurement is not None


def test_treasury_prime_incoming_ach_debit_direction_refuses_outbound() -> None:
    result = realized_return_mod.realized_return_from_rail(
        _accepted_event("incoming_ach.create", direction="debit"),
        source_receipt_ref="receipt://payment/treasury-prime/incoming-ach-debit",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert result.refusal_reason is realized_return_mod.RealizedReturnRefusalReason.OUTBOUND_EVENT
    assert result.measurement is None


def test_open_collective_transaction_created_requires_direction_witness() -> None:
    event = OpenCollectiveRailReceiver().ingest_webhook(
        _open_collective_transaction_payload(value=-7.0),
        signature=None,
    )

    result = realized_return_mod.realized_return_from_rail(
        event,
        source_receipt_ref="receipt://payment/open-collective/transaction-created",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.MISSING_INBOUND_DIRECTION
    )
    assert result.measurement is None


def test_open_collective_transaction_credit_direction_can_measure() -> None:
    result = realized_return_mod.realized_return_from_rail(
        _accepted_event("collective_transaction_created", direction="credit"),
        source_receipt_ref="receipt://payment/open-collective/credit",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.ACCEPTED
    assert result.measurement is not None


def test_open_collective_transaction_debit_direction_refuses_outbound() -> None:
    result = realized_return_mod.realized_return_from_rail(
        _accepted_event("collective_transaction_created", direction="debit"),
        source_receipt_ref="receipt://payment/open-collective/debit",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert result.refusal_reason is realized_return_mod.RealizedReturnRefusalReason.OUTBOUND_EVENT
    assert result.measurement is None


@pytest.mark.parametrize(
    ("event", "reason"),
    (
        (
            _accepted_event("payment_refunded"),
            realized_return_mod.RealizedReturnRefusalReason.REFUND_OR_REVERSAL_EVENT,
        ),
        (
            _accepted_event("processor_fee_charged"),
            realized_return_mod.RealizedReturnRefusalReason.FEE_EVENT,
        ),
        (
            _accepted_event("transaction.created", direction="debit"),
            realized_return_mod.RealizedReturnRefusalReason.OUTBOUND_EVENT,
        ),
        (
            _directionless_event("transaction.created"),
            realized_return_mod.RealizedReturnRefusalReason.MISSING_INBOUND_DIRECTION,
        ),
        (
            _accepted_event("transaction.updated", direction="incoming"),
            realized_return_mod.RealizedReturnRefusalReason.AMBIGUOUS_BANK_TRANSACTION_EVENT,
        ),
        (
            _accepted_event("payment_intent_succeeded", provenance="projected"),
            realized_return_mod.RealizedReturnRefusalReason.PROJECTED_VALUE,
        ),
        (
            _accepted_event("customer_subscription_created"),
            realized_return_mod.RealizedReturnRefusalReason.MEMBERSHIP_LIFECYCLE_EVENT,
        ),
        (
            _accepted_event("unknown_payment_kind"),
            realized_return_mod.RealizedReturnRefusalReason.UNSUPPORTED_EVENT_KIND,
        ),
        (
            _accepted_event("payment_intent_succeeded", source_amount_sign=None),
            realized_return_mod.RealizedReturnRefusalReason.MISSING_SOURCE_AMOUNT_SIGN,
        ),
        (
            _accepted_event("payment_intent_succeeded", source_amount_sign="negative"),
            realized_return_mod.RealizedReturnRefusalReason.REFUND_OR_REVERSAL_EVENT,
        ),
        (
            _accepted_event(
                "incoming_ach.create",
                direction="credit",
                source_amount_sign="negative",
            ),
            realized_return_mod.RealizedReturnRefusalReason.REFUND_OR_REVERSAL_EVENT,
        ),
        (
            _accepted_event(
                "payment_intent_succeeded",
                source_amount_sign=None,
                signed_amount=-2500,
            ),
            realized_return_mod.RealizedReturnRefusalReason.REFUND_OR_REVERSAL_EVENT,
        ),
        (
            _accepted_event(
                "incoming_ach.create",
                direction="credit",
                source_amount_sign=None,
                signed_amount=-2500,
            ),
            realized_return_mod.RealizedReturnRefusalReason.REFUND_OR_REVERSAL_EVENT,
        ),
        (
            {
                key: value
                for key, value in _accepted_event("payment_intent_succeeded").items()
                if key != "event_kind"
            },
            realized_return_mod.RealizedReturnRefusalReason.MISSING_EVENT_KIND,
        ),
        (
            {
                key: value
                for key, value in _accepted_event("payment_intent_succeeded").items()
                if key not in {"amount_currency_cents", "amount_usd_cents", "amount_sats"}
            },
            realized_return_mod.RealizedReturnRefusalReason.MISSING_AMOUNT,
        ),
        (
            _accepted_event("payment_intent_succeeded", amount_currency_cents=0),
            realized_return_mod.RealizedReturnRefusalReason.NON_POSITIVE_AMOUNT,
        ),
        (
            {
                key: value
                for key, value in _accepted_event("payment_intent_succeeded").items()
                if key not in {"occurred_at", "timestamp", "observed_at", "realized_at"}
            },
            realized_return_mod.RealizedReturnRefusalReason.MISSING_OBSERVED_AT,
        ),
    ),
)
def test_refusal_events_do_not_produce_measurements(
    event: dict[str, object],
    reason: realized_return_mod.RealizedReturnRefusalReason,
) -> None:
    result = realized_return_mod.realized_return_from_rail(
        event, source_receipt_ref="receipt://payment/test/refusal"
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert result.refusal_reason is reason
    assert result.measurement is None


def test_missing_evidence_refuses_otherwise_valid_realized_kind() -> None:
    event = _accepted_event("payment_intent_succeeded")
    event.pop("raw_payload_sha256")

    result = realized_return_mod.realized_return_from_rail(event)

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.MISSING_RAIL_EVIDENCE
    )
    assert result.measurement is None


def test_malformed_timestamp_returns_invalid_shape_refusal() -> None:
    result = realized_return_mod.realized_return_from_rail(
        _accepted_event("payment_intent_succeeded", occurred_at="not-a-date"),
        source_receipt_ref="receipt://payment/test/bad-clock",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason is realized_return_mod.RealizedReturnRefusalReason.INVALID_EVENT_SHAPE
    )
    assert result.measurement is None
    assert result.to_dict()["detail"].startswith("event timestamp is malformed")
    assert "next action:" in result.to_dict()["detail"]


@pytest.mark.parametrize(
    "event",
    (
        _accepted_event("payment_intent_succeeded", amount_currency_cents="1200"),
        {
            "event_kind": "payment_intent_succeeded",
            "amount_usd": "Infinity",
            "occurred_at": NOW,
            "raw_payload_sha256": RAW_SHA,
        },
        {
            "event_kind": "payment_intent_succeeded",
            "amount_usd": "1.234",
            "occurred_at": NOW,
            "raw_payload_sha256": RAW_SHA,
        },
    ),
)
def test_malformed_amounts_return_invalid_shape_refusal(event: dict[str, object]) -> None:
    result = realized_return_mod.realized_return_from_rail(
        event,
        source_receipt_ref="receipt://payment/test/bad-amount",
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason is realized_return_mod.RealizedReturnRefusalReason.INVALID_EVENT_SHAPE
    )
    assert result.measurement is None


def test_refusal_result_carries_cctv_and_ratchet_context() -> None:
    result = realized_return_mod.realized_return_from_rail(
        _accepted_event("payment_refunded"),
        source_receipt_ref="receipt://payment/test/refund",
    )

    payload = result.to_dict()

    assert payload["status"] == "refused"
    assert payload["refusal_reason"] == "refund_or_reversal_event"
    assert payload["event_kind"] == "payment_refunded"
    assert payload["source_class"] == "payment_event"
    assert "next action:" in payload["detail"]
    assert "receipt://payment/test/refund" in payload["evidence_refs"]
    with pytest.raises(TypeError, match="truthiness is undefined"):
        bool(result)


@pytest.mark.parametrize(
    ("event", "reason"),
    (
        (
            _accepted_event("processor_fee_charged"),
            realized_return_mod.RealizedReturnRefusalReason.FEE_EVENT,
        ),
        (
            _accepted_event("customer_subscription_created"),
            realized_return_mod.RealizedReturnRefusalReason.MEMBERSHIP_LIFECYCLE_EVENT,
        ),
        (
            _accepted_event("transaction.updated", direction="incoming"),
            realized_return_mod.RealizedReturnRefusalReason.AMBIGUOUS_BANK_TRANSACTION_EVENT,
        ),
        (
            _accepted_event("payment_intent_succeeded", amount_currency_cents="bad"),
            realized_return_mod.RealizedReturnRefusalReason.INVALID_EVENT_SHAPE,
        ),
    ),
)
def test_refusal_to_dict_shape_is_stable_across_reason_classes(
    event: dict[str, object],
    reason: realized_return_mod.RealizedReturnRefusalReason,
) -> None:
    result = realized_return_mod.realized_return_from_rail(
        event,
        source_receipt_ref="receipt://payment/test/refusal-context",
    )

    payload = result.to_dict()

    assert payload["status"] == "refused"
    assert payload["refusal_reason"] == reason.value
    assert payload["source_class"] == "payment_event"
    assert payload["measurement"] is None
    assert "receipt://payment/test/refusal-context" in payload["evidence_refs"]
    assert "next action:" in payload["detail"]


def test_reader_consumes_durable_stage0_payment_event_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    accepted = sink.append(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref="receipt://payment/stripe/accepted/payment_intent_succeeded",
        payload=_durable_event("payment_intent_succeeded"),
        timestamp=NOW.isoformat().replace("+00:00", "Z"),
    )
    refused = sink.append(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref="receipt://payment/stripe/refund/payment_refunded",
        payload=_durable_event("payment_refunded"),
        timestamp=NOW.isoformat().replace("+00:00", "Z"),
    )

    results = realized_return_mod.realized_returns_from_durable_payment_events(
        sink.path_for_stream("payment-event")
    )

    assert [result.status for result in results] == [
        realized_return_mod.RealizedReturnStatus.ACCEPTED,
        realized_return_mod.RealizedReturnStatus.REFUSED,
    ]
    assert results[0].measurement is not None
    assert f"durable:payment-event:{accepted.row_hash}" in results[0].evidence_refs
    assert accepted.source_receipt_ref in results[0].evidence_refs
    assert (
        results[1].refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.REFUND_OR_REVERSAL_EVENT
    )
    assert f"durable:payment-event:{refused.row_hash}" in results[1].evidence_refs


def test_durable_row_wrapper_refuses_direct_sink_row_without_stream_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    row = sink.append(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref="receipt://payment/stripe/accepted/payment_intent_succeeded",
        payload=_durable_event("payment_intent_succeeded"),
        timestamp=NOW.isoformat().replace("+00:00", "Z"),
    )

    result = realized_return_mod.realized_return_from_durable_payment_event(row)

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.NOT_STAGE0_PAYMENT_EVENT
    )
    assert result.measurement is None
    assert "durable rows must be read through" in result.detail


def test_missing_durable_payment_event_file_returns_empty_tuple(tmp_path: Path) -> None:
    assert (
        realized_return_mod.realized_returns_from_durable_payment_events(tmp_path / "missing.jsonl")
        == ()
    )


def test_durable_row_wrapper_refuses_unvalidated_non_payment_event_rows() -> None:
    result = realized_return_mod.realized_return_from_durable_payment_event(
        sink_mod.DurableSinkRow(
            schema_version=sink_mod.SCHEMA_VERSION,
            timestamp=NOW.isoformat().replace("+00:00", "Z"),
            stream_id="chronicle",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/wrong-stream",
            prior_hash=sink_mod.GENESIS_HASH,
            row_hash="b" * 64,
            payload=_durable_event("payment_intent_succeeded"),
        )
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.NOT_STAGE0_PAYMENT_EVENT
    )
    assert result.measurement is None


def test_durable_row_wrapper_refuses_unvalidated_non_mapping_payload() -> None:
    result = realized_return_mod.realized_return_from_durable_payment_event(
        sink_mod.DurableSinkRow(
            schema_version=sink_mod.SCHEMA_VERSION,
            timestamp=NOW.isoformat().replace("+00:00", "Z"),
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/bad-payload",
            prior_hash=sink_mod.GENESIS_HASH,
            row_hash="c" * 64,
            payload=["not", "a", "mapping"],  # type: ignore[arg-type]
        )
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.NOT_STAGE0_PAYMENT_EVENT
    )
    assert result.measurement is None


def test_durable_stream_reader_refuses_non_mapping_payload_with_durable_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoIssues:
        def raise_for_issues(self) -> None:
            return None

    row_hash = "c" * 64
    path = tmp_path / "payment-event.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": sink_mod.SCHEMA_VERSION,
                "timestamp": NOW.isoformat().replace("+00:00", "Z"),
                "stream_id": "payment-event",
                "data_class": "financial_receipt",
                "source_receipt_ref": "receipt://payment/bad-payload",
                "prior_hash": sink_mod.GENESIS_HASH,
                "row_hash": row_hash,
                "payload": ["not", "a", "mapping"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        realized_return_mod,
        "validate_chain",
        lambda *_args, **_kwargs: _NoIssues(),
    )

    results = realized_return_mod.realized_returns_from_durable_payment_events(path)

    assert len(results) == 1
    assert results[0].status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        results[0].refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.INVALID_EVENT_SHAPE
    )
    assert "receipt://payment/bad-payload" in results[0].evidence_refs
    assert f"durable:payment-event:{row_hash}" in results[0].evidence_refs


def test_durable_stream_reader_refuses_wrong_stage0_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoIssues:
        def raise_for_issues(self) -> None:
            return None

    path = tmp_path / "payment-event.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": sink_mod.SCHEMA_VERSION,
                "timestamp": NOW.isoformat().replace("+00:00", "Z"),
                "stream_id": "chronicle",
                "data_class": "financial_receipt",
                "source_receipt_ref": "receipt://payment/wrong-stream",
                "prior_hash": sink_mod.GENESIS_HASH,
                "row_hash": "e" * 64,
                "payload": _durable_event("payment_intent_succeeded"),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        realized_return_mod,
        "validate_chain",
        lambda *_args, **_kwargs: _NoIssues(),
    )

    results = realized_return_mod.realized_returns_from_durable_payment_events(path)

    assert len(results) == 1
    assert results[0].status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        results[0].refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.NOT_STAGE0_PAYMENT_EVENT
    )
    assert "durable row must be payment-event/financial_receipt" in results[0].detail


def test_durable_row_wrapper_refuses_unvalidated_mapping_even_with_valid_payload() -> None:
    result = realized_return_mod.realized_return_from_durable_payment_event(
        {
            "stream_id": "payment-event",
            "data_class": "financial_receipt",
            "source_receipt_ref": "receipt://payment/self-declared",
            "row_hash": "d" * 64,
            "payload": _durable_event("payment_intent_succeeded"),
        }
    )

    assert result.status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        result.refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.NOT_STAGE0_PAYMENT_EVENT
    )
    assert result.measurement is None


def test_durable_stream_reader_refuses_non_mapping_jsonl_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoIssues:
        def raise_for_issues(self) -> None:
            return None

    path = tmp_path / "payment-event.jsonl"
    path.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(
        realized_return_mod,
        "validate_chain",
        lambda *_args, **_kwargs: _NoIssues(),
    )

    results = realized_return_mod.realized_returns_from_durable_payment_events(path)

    assert len(results) == 1
    assert results[0].status is realized_return_mod.RealizedReturnStatus.REFUSED
    assert (
        results[0].refusal_reason
        is realized_return_mod.RealizedReturnRefusalReason.INVALID_EVENT_SHAPE
    )


def test_durable_stream_reader_raises_when_chain_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenChain:
        def raise_for_issues(self) -> None:
            raise RuntimeError("chain validation failed")

    path = tmp_path / "payment-event.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        realized_return_mod,
        "validate_chain",
        lambda *_args, **_kwargs: _BrokenChain(),
    )

    with pytest.raises(RuntimeError, match="chain validation failed"):
        realized_return_mod.realized_returns_from_durable_payment_events(path)
