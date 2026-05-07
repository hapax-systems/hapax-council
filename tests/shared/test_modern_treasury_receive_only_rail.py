"""Tests for the Modern Treasury receive-only rail.

cc-task: modern-treasury-receive-only-rail (Phase 0).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from shared.modern_treasury_receive_only_rail import (
    MODERN_TREASURY_WEBHOOK_SECRET_ENV,
    IncomingPaymentEvent,
    IncomingPaymentEventKind,
    ModernTreasuryRailReceiver,
    PaymentMethod,
    ReceiveOnlyRailError,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_VALID_SECRET = "modern-treasury-webhook-secret-aBcDeFgHiJkLmN"


def _sign(payload_bytes: bytes, secret: str = _VALID_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _ach_payload(
    *,
    event: str = "incoming_payment_detail.created",
    originating_party_name: str = "Foundation Trust",
    amount: object = 10000,
    currency: str = "USD",
    payment_type: str = "ach",
    created_at: str = "2026-05-02T12:00:00Z",
) -> dict:
    """Realistic Modern Treasury delivery for an incoming ACH payment.

    Includes banking PII fields that the receiver MUST NOT extract.
    """
    return {
        "event": event,
        "data": {
            "id": "ipd-uuid-1111-2222",
            "object": "incoming_payment_detail",
            "amount": amount,
            "currency": currency,
            "type": payment_type,
            "status": "completed",
            "as_of_date": "2026-05-02",
            "originating_party_name": originating_party_name,
            "originating_account_number": "999111888777",  # banking PII
            "originating_routing_number": "021000089",  # banking PII
            "description": "thank you for the work — Q2 retainer",  # PII
            "vendor_id": "mt-vendor-001",  # internal cross-correlation PII
            "internal_account_id": "ia-uuid-3333",
            "ledger_transaction_id": "lt-uuid-4444",
            "created_at": created_at,
            "updated_at": created_at,
        },
    }


def _wire_payload(**overrides: object) -> dict:
    overrides.setdefault("payment_type", "wire")
    overrides.setdefault("originating_party_name", "Acme Corp")
    overrides.setdefault("amount", 500000)
    return _ach_payload(**overrides)  # type: ignore[arg-type]


def _outgoing_payload() -> dict:
    return _ach_payload(event="payment_order.created")


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_ingest_ach_created_returns_normalized_event() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.event_kind is IncomingPaymentEventKind.CREATED
    assert event.payment_method is PaymentMethod.ACH
    assert event.originating_party_handle == "Foundation Trust"
    assert event.amount_currency_cents == 10000
    assert event.currency == "USD"


def test_ingest_completed_event() -> None:
    payload = _ach_payload(event="incoming_payment_detail.completed")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.event_kind is IncomingPaymentEventKind.COMPLETED


@pytest.mark.parametrize(
    "method",
    ["ach", "wire", "check", "book", "rtp", "sepa", "signet", "interac"],
)
def test_all_payment_methods_pass(method: str) -> None:
    payload = _ach_payload(payment_type=method)
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.payment_method.value == method


# ---------------------------------------------------------------------------
# Direction filter via event-kind taxonomy
# ---------------------------------------------------------------------------


def test_payment_order_event_rejected_as_outgoing() -> None:
    payload = _outgoing_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"refusing outgoing"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_expected_payment_event_rejected_as_outgoing() -> None:
    payload = _ach_payload(event="expected_payment.created")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"refusing outgoing"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_unknown_event_rejected() -> None:
    payload = _ach_payload(event="ledger_transaction.created")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"unaccepted webhook event type"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_legacy_type_field_accepted_when_event_absent() -> None:
    """Some Modern Treasury historical deliveries used `type` instead of `event`."""
    payload = _ach_payload()
    payload["type"] = payload.pop("event")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None


def test_event_takes_precedence_over_legacy_type() -> None:
    payload = _ach_payload()
    payload["type"] = "payment_order.created"  # outgoing — would refuse if read
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.event_kind is IncomingPaymentEventKind.CREATED


# ---------------------------------------------------------------------------
# HMAC SHA-256 verification
# ---------------------------------------------------------------------------


def test_signature_mismatch_fails_closed() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    bad_sig = "0" * 64
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"signature mismatch"):
            receiver.ingest_webhook(payload, bad_sig, raw_body=raw)


def test_signature_with_sha256_prefix_accepted() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    sig = "sha256=" + _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None


def test_signature_provided_but_secret_unset_fails() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ReceiveOnlyRailError, match=r"is not set"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_signature_none_skips_verification() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    receiver = ModernTreasuryRailReceiver()
    event = receiver.ingest_webhook(payload, None, raw_body=raw)
    assert event is not None


# ---------------------------------------------------------------------------
# Banking-PII guard — the receive-only invariant
# ---------------------------------------------------------------------------


def test_normalized_event_carries_no_banking_pii() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    field_names = set(IncomingPaymentEvent.model_fields.keys())
    forbidden = {
        "originating_account_number",
        "originating_routing_number",
        "description",
        "vendor_id",
        "internal_account_id",
        "ledger_transaction_id",
        "status",
    }
    assert field_names.isdisjoint(forbidden)
    serialized = event.model_dump_json()
    assert "021000089" not in serialized
    assert "999111888777" not in serialized
    assert "Q2 retainer" not in serialized
    assert "mt-vendor-001" not in serialized
    assert "ia-uuid-3333" not in serialized
    assert "lt-uuid-4444" not in serialized


def test_event_refuses_extras_at_construction() -> None:
    base = {
        "originating_party_handle": "Acme",
        "amount_currency_cents": 10000,
        "currency": "USD",
        "event_kind": IncomingPaymentEventKind.CREATED,
        "payment_method": PaymentMethod.ACH,
        "occurred_at": datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        "raw_payload_sha256": "0" * 64,
    }
    for forbidden in ("description", "vendor_id", "routing_number"):
        with pytest.raises(Exception, match=r"forbid|extra"):
            IncomingPaymentEvent(**{**base, forbidden: "x"})  # type: ignore[arg-type]


def test_handle_with_at_sign_is_rejected() -> None:
    payload = _ach_payload(originating_party_name="leak@example.com")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"validation"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Multi-currency + amount normalization
# ---------------------------------------------------------------------------


def test_integer_amount_treated_as_cents_already() -> None:
    payload = _ach_payload(amount=12345)
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 12345


def test_decimal_string_with_dot_is_major_units() -> None:
    """Decimal-string '100.00' → 10000 cents (× 100 normalization)."""
    payload = _ach_payload(amount="100.00")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 10000


def test_decimal_string_without_dot_is_already_cents() -> None:
    """Decimal-string '10000' → 10000 cents (already minor units)."""
    payload = _ach_payload(amount="10000")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 10000


def test_negative_integer_amount_is_absolute_value() -> None:
    payload = _ach_payload(amount=-5000)
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 5000


def test_eur_wire_normalizes() -> None:
    payload = _wire_payload(currency="EUR", amount=1234567)
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 1234567
    assert event.currency == "EUR"


def test_lowercase_currency_is_normalized_to_upper() -> None:
    payload = _ach_payload(currency="usd")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.currency == "USD"


def test_invalid_currency_format_fails() -> None:
    payload = _ach_payload(currency="DOLLAR")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"validation"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_amount_as_bool_fails() -> None:
    payload = _ach_payload(amount=True)
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"numeric string or number"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_invalid_decimal_string_fails() -> None:
    payload = _ach_payload(amount="not-a-number")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"invalid 'amount'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Schema rejection
# ---------------------------------------------------------------------------


def test_non_dict_payload_fails() -> None:
    receiver = ModernTreasuryRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match=r"must be a dict"):
        receiver.ingest_webhook("not-a-dict", None)  # type: ignore[arg-type]


def test_missing_data_fails() -> None:
    payload: dict = {"event": "incoming_payment_detail.created"}
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'data'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_originating_party_name_fails() -> None:
    payload = _ach_payload()
    del payload["data"]["originating_party_name"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'originating_party_name'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_amount_fails() -> None:
    payload = _ach_payload()
    del payload["data"]["amount"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'amount'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_currency_fails() -> None:
    payload = _ach_payload()
    del payload["data"]["currency"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'currency'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_payment_method_fails() -> None:
    payload = _ach_payload()
    del payload["data"]["type"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'type'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_unknown_payment_method_fails() -> None:
    payload = _ach_payload(payment_type="quantum_teleport")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"unknown payment method"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_timestamp_fails() -> None:
    payload = _ach_payload()
    del payload["data"]["created_at"]
    del payload["data"]["updated_at"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'updated_at'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_invalid_timestamp_fails() -> None:
    payload = _ach_payload(created_at="yesterday-noon")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"invalid ISO 8601"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_non_string_event_fails() -> None:
    payload = _ach_payload()
    payload["event"] = 42  # type: ignore[assignment]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = ModernTreasuryRailReceiver()
    with mock.patch.dict("os.environ", {MODERN_TREASURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"must be a string"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Heartbeat / no-op
# ---------------------------------------------------------------------------


def test_empty_payload_with_no_signature_returns_none() -> None:
    receiver = ModernTreasuryRailReceiver()
    assert receiver.ingest_webhook({}, None) is None


# ---------------------------------------------------------------------------
# Module-level static checks
# ---------------------------------------------------------------------------


def test_module_carries_no_outbound_calls() -> None:
    import inspect

    import shared.modern_treasury_receive_only_rail as mod

    src = inspect.getsource(mod)
    forbidden = (
        "requests.",
        "httpx.",
        "urllib.request",
        "aiohttp",
        "modern_treasury",
    )
    for token in forbidden:
        if token == "modern_treasury" and ("modern_treasury_receive_only_rail" in src):
            # The module itself is named modern_treasury_receive_only_rail; skip the
            # full-module-name check (forbidden refers to importing the SDK).
            continue
        assert token not in src, f"unexpected I/O reference: {token!r}"


def test_module_carries_no_send_path() -> None:
    import inspect

    import shared.modern_treasury_receive_only_rail as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer_out",
        "def origination",
        "def create_payment_order",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


def test_secret_env_var_constant_is_canonical() -> None:
    assert MODERN_TREASURY_WEBHOOK_SECRET_ENV == "MODERN_TREASURY_WEBHOOK_SECRET"


def test_receive_only_error_subclasses_exception() -> None:
    assert issubclass(ReceiveOnlyRailError, Exception)


def test_payment_method_enum_has_expected_members() -> None:
    expected = {"ach", "wire", "check", "book", "rtp", "sepa", "signet", "interac"}
    assert {m.value for m in PaymentMethod} == expected


def test_event_kind_enum_only_accepts_two_incoming_events() -> None:
    assert {k.value for k in IncomingPaymentEventKind} == {
        "incoming_payment_detail.created",
        "incoming_payment_detail.completed",
    }


# ---------------------------------------------------------------------------
# jr-modern-treasury-rail-idempotency-pin regression pins
# ---------------------------------------------------------------------------


def test_idempotency_store_rejects_duplicate_payment_id(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "mt-idem.db")
    receiver = ModernTreasuryRailReceiver(idempotency_store=store)
    payload = _ach_payload()
    payload["data"]["id"] = "ipd-test-001"

    first = receiver.ingest_webhook(payload, signature=None)
    second = receiver.ingest_webhook(payload, signature=None)

    assert first is not None
    assert second is None


def test_idempotency_store_distinct_payment_ids_both_processed(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "mt-idem.db")
    receiver = ModernTreasuryRailReceiver(idempotency_store=store)
    payload_a = _ach_payload()
    payload_a["data"]["id"] = "ipd-a"
    payload_b = _ach_payload()
    payload_b["data"]["id"] = "ipd-b"

    first = receiver.ingest_webhook(payload_a, signature=None)
    second = receiver.ingest_webhook(payload_b, signature=None)

    assert first is not None
    assert second is not None


def test_idempotency_store_allows_lifecycle_events_for_same_payment_id(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "mt-idem.db")
    receiver = ModernTreasuryRailReceiver(idempotency_store=store)
    created = _ach_payload(event="incoming_payment_detail.created")
    completed = _ach_payload(event="incoming_payment_detail.completed")
    created["data"]["id"] = "ipd-lifecycle-001"
    completed["data"]["id"] = "ipd-lifecycle-001"

    first = receiver.ingest_webhook(created, signature=None)
    second = receiver.ingest_webhook(completed, signature=None)
    replay_completed = receiver.ingest_webhook(completed, signature=None)

    assert first is not None
    assert first.event_kind is IncomingPaymentEventKind.CREATED
    assert second is not None
    assert second.event_kind is IncomingPaymentEventKind.COMPLETED
    assert replay_completed is None


def test_idempotency_store_provided_but_data_id_missing_raises(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "mt-idem.db")
    receiver = ModernTreasuryRailReceiver(idempotency_store=store)
    payload = _ach_payload()
    del payload["data"]["id"]

    with pytest.raises(ReceiveOnlyRailError, match="data.id"):
        receiver.ingest_webhook(payload, signature=None)


def test_no_idempotency_store_means_no_idempotency_check():
    receiver = ModernTreasuryRailReceiver()
    payload = _ach_payload()
    a = receiver.ingest_webhook(payload, signature=None)
    b = receiver.ingest_webhook(payload, signature=None)
    assert a is not None
    assert b is not None


def test_idempotency_store_persists_across_receivers(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    db = tmp_path / "mt-idem.db"
    payload = _ach_payload()
    payload["data"]["id"] = "ipd-persist"

    a = ModernTreasuryRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    first = a.ingest_webhook(payload, signature=None)
    b = ModernTreasuryRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    second = b.ingest_webhook(payload, signature=None)

    assert first is not None
    assert second is None
