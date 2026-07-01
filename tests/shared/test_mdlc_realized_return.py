"""Tests for the MonDLC realized-return rail boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import shared.durable_jsonl_sink as sink_mod
from shared.capdlc_lifecycle import GateStatus
from shared.mdlc_measure import MonDLCLadder, MonDLCVerdict, score
from shared.mdlc_realized_return import (
    AMBIGUOUS_BANK_TRANSACTION_EVENT_KINDS,
    DIRECTION_FILTERED_EVENT_KINDS,
    MEMBERSHIP_LIFECYCLE_EVENT_KINDS,
    NON_SETTLED_INBOUND_EVENT_KINDS,
    OUTBOUND_EVENT_KINDS,
    REALIZED_INBOUND_EVENT_KINDS,
    REFUND_REVERSAL_EVENT_KINDS,
    RealizedReturnRefusalReason,
    RealizedReturnStatus,
    realized_return_from_durable_payment_event,
    realized_return_from_rail,
    realized_returns_from_durable_payment_events,
)
from shared.modern_treasury_receive_only_rail import (
    IncomingPaymentEvent,
    IncomingPaymentEventKind,
    PaymentMethod,
)
from shared.stripe_payment_link_receive_only_rail import (
    PaymentEvent as StripePaymentEvent,
)
from shared.stripe_payment_link_receive_only_rail import (
    PaymentEventKind as StripePaymentEventKind,
)

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
    }
    if event_kind in DIRECTION_FILTERED_EVENT_KINDS:
        event["direction"] = "credit"
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


def _receipt(event_kind: str) -> str:
    return f"receipt://payment/test/{event_kind.replace('/', '_')}"


def _trusted_sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sink_mod.DurableJsonlSink:
    root = tmp_path / "durable"
    root.mkdir()
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "btrfs")
    return sink_mod.DurableJsonlSink(root)


def test_event_kind_contract_is_explicit_and_disjoint() -> None:
    refused = (
        MEMBERSHIP_LIFECYCLE_EVENT_KINDS
        | NON_SETTLED_INBOUND_EVENT_KINDS
        | OUTBOUND_EVENT_KINDS
        | REFUND_REVERSAL_EVENT_KINDS
        | AMBIGUOUS_BANK_TRANSACTION_EVENT_KINDS
    )

    assert REALIZED_INBOUND_EVENT_KINDS
    assert REALIZED_INBOUND_EVENT_KINDS.isdisjoint(refused)
    assert "customer_subscription_created" in MEMBERSHIP_LIFECYCLE_EVENT_KINDS
    assert "incoming_payment_detail.created" in NON_SETTLED_INBOUND_EVENT_KINDS
    assert "payment_refunded" in REFUND_REVERSAL_EVENT_KINDS
    assert "transaction.updated" in AMBIGUOUS_BANK_TRANSACTION_EVENT_KINDS


@pytest.mark.parametrize("event_kind", sorted(REALIZED_INBOUND_EVENT_KINDS))
def test_all_enumerated_realized_inbound_event_kinds_become_measurements(
    event_kind: str,
) -> None:
    result = realized_return_from_rail(
        _accepted_event(event_kind), source_receipt_ref=_receipt(event_kind)
    )

    assert result.status is RealizedReturnStatus.ACCEPTED
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
    event = StripePaymentEvent(
        customer_handle="cus_TestRail01",
        amount_currency_cents=2500,
        currency="USD",
        event_kind=StripePaymentEventKind.PAYMENT_INTENT_SUCCEEDED,
        occurred_at=NOW,
        raw_payload_sha256=RAW_SHA,
    )

    rail_result = realized_return_from_rail(
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

    result = realized_return_from_rail(event, source_receipt_ref="receipt://payment/mt/created")

    assert result.status is RealizedReturnStatus.REFUSED
    assert result.refusal_reason is RealizedReturnRefusalReason.NON_SETTLED_INBOUND_EVENT
    assert result.measurement is None


@pytest.mark.parametrize(
    ("event", "reason"),
    (
        (
            _accepted_event("payment_refunded"),
            RealizedReturnRefusalReason.REFUND_OR_REVERSAL_EVENT,
        ),
        (
            _accepted_event("processor_fee_charged"),
            RealizedReturnRefusalReason.FEE_EVENT,
        ),
        (
            _accepted_event("transaction.created", direction="debit"),
            RealizedReturnRefusalReason.OUTBOUND_EVENT,
        ),
        (
            _directionless_event("transaction.created"),
            RealizedReturnRefusalReason.MISSING_INBOUND_DIRECTION,
        ),
        (
            _accepted_event("transaction.updated", direction="incoming"),
            RealizedReturnRefusalReason.AMBIGUOUS_BANK_TRANSACTION_EVENT,
        ),
        (
            _accepted_event("payment_intent_succeeded", provenance="projected"),
            RealizedReturnRefusalReason.PROJECTED_VALUE,
        ),
        (
            _accepted_event("customer_subscription_created"),
            RealizedReturnRefusalReason.MEMBERSHIP_LIFECYCLE_EVENT,
        ),
        (
            _accepted_event("unknown_payment_kind"),
            RealizedReturnRefusalReason.UNSUPPORTED_EVENT_KIND,
        ),
    ),
)
def test_refusal_events_do_not_produce_measurements(
    event: dict[str, object],
    reason: RealizedReturnRefusalReason,
) -> None:
    result = realized_return_from_rail(event, source_receipt_ref="receipt://payment/test/refusal")

    assert result.status is RealizedReturnStatus.REFUSED
    assert result.refusal_reason is reason
    assert result.measurement is None


def test_missing_evidence_refuses_otherwise_valid_realized_kind() -> None:
    event = _accepted_event("payment_intent_succeeded")
    event.pop("raw_payload_sha256")

    result = realized_return_from_rail(event)

    assert result.status is RealizedReturnStatus.REFUSED
    assert result.refusal_reason is RealizedReturnRefusalReason.MISSING_RAIL_EVIDENCE
    assert result.measurement is None


def test_malformed_timestamp_returns_invalid_shape_refusal() -> None:
    result = realized_return_from_rail(
        _accepted_event("payment_intent_succeeded", occurred_at="not-a-date"),
        source_receipt_ref="receipt://payment/test/bad-clock",
    )

    assert result.status is RealizedReturnStatus.REFUSED
    assert result.refusal_reason is RealizedReturnRefusalReason.INVALID_EVENT_SHAPE
    assert result.measurement is None
    assert result.to_dict()["detail"] == "event timestamp is malformed"


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
    result = realized_return_from_rail(
        event,
        source_receipt_ref="receipt://payment/test/bad-amount",
    )

    assert result.status is RealizedReturnStatus.REFUSED
    assert result.refusal_reason is RealizedReturnRefusalReason.INVALID_EVENT_SHAPE
    assert result.measurement is None


def test_refusal_result_carries_cctv_and_ratchet_context() -> None:
    result = realized_return_from_rail(
        _accepted_event("payment_refunded"),
        source_receipt_ref="receipt://payment/test/refund",
    )

    payload = result.to_dict()

    assert payload["status"] == "refused"
    assert payload["refusal_reason"] == "refund_or_reversal_event"
    assert payload["event_kind"] == "payment_refunded"
    assert payload["source_class"] == "payment_event"
    assert "receipt://payment/test/refund" in payload["evidence_refs"]
    with pytest.raises(TypeError, match="truthiness is undefined"):
        bool(result)


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

    results = realized_returns_from_durable_payment_events(sink.path_for_stream("payment-event"))

    assert [result.status for result in results] == [
        RealizedReturnStatus.ACCEPTED,
        RealizedReturnStatus.REFUSED,
    ]
    assert results[0].measurement is not None
    assert f"durable:payment-event:{accepted.row_hash}" in results[0].evidence_refs
    assert accepted.source_receipt_ref in results[0].evidence_refs
    assert results[1].refusal_reason is RealizedReturnRefusalReason.REFUND_OR_REVERSAL_EVENT
    assert f"durable:payment-event:{refused.row_hash}" in results[1].evidence_refs


def test_missing_durable_payment_event_file_returns_empty_tuple(tmp_path: Path) -> None:
    assert realized_returns_from_durable_payment_events(tmp_path / "missing.jsonl") == ()


def test_durable_row_wrapper_refuses_non_payment_event_rows() -> None:
    result = realized_return_from_durable_payment_event(
        {
            "stream_id": "chronicle",
            "data_class": "financial_receipt",
            "source_receipt_ref": "receipt://payment/wrong-stream",
            "row_hash": "b" * 64,
            "payload": _durable_event("payment_intent_succeeded"),
        }
    )

    assert result.status is RealizedReturnStatus.REFUSED
    assert result.refusal_reason is RealizedReturnRefusalReason.NOT_STAGE0_PAYMENT_EVENT
    assert result.measurement is None


def test_durable_row_wrapper_refuses_non_mapping_payload() -> None:
    result = realized_return_from_durable_payment_event(
        {
            "stream_id": "payment-event",
            "data_class": "financial_receipt",
            "source_receipt_ref": "receipt://payment/bad-payload",
            "row_hash": "c" * 64,
            "payload": ["not", "a", "mapping"],
        }
    )

    assert result.status is RealizedReturnStatus.REFUSED
    assert result.refusal_reason is RealizedReturnRefusalReason.INVALID_EVENT_SHAPE
    assert result.measurement is None
