"""Tests for the Mercury receive-only rail.

cc-task: mercury-receive-only-rail (Phase 0).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from shared.mercury_receive_only_rail import (
    MERCURY_WEBHOOK_SECRET_ENV,
    MercuryEventKind,
    MercuryRailReceiver,
    MercuryTransactionDirection,
    MercuryTransactionEvent,
    ReceiveOnlyRailError,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_VALID_SECRET = "mercury-webhook-secret-aBcDeFgHiJkLmN"


def _sign(payload_bytes: bytes, secret: str = _VALID_SECRET) -> str:
    """Compute the X-Mercury-Signature hex digest Mercury would ship."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def _canonical(payload: dict) -> bytes:
    """Round-trip canonical bytes used by tests as the 'raw' body."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _ach_incoming_payload(
    *,
    counterparty_name: str = "Acme Foundation",
    amount: str = "100.00",
    currency: str = "USD",
    kind: str = "ach_incoming",
    created_at: str = "2026-05-02T12:00:00Z",
    event_type: str = "transaction.created",
) -> dict:
    """Realistic Mercury delivery for an incoming ACH transfer.

    Includes fields that constitute banking PII (account_number,
    routing_number, counterparty_email, memo, address) that the
    receiver must NOT extract — pinning the receive-only invariant.
    """
    return {
        "type": event_type,
        "data": {
            "id": "txn-mercury-incoming-1",
            "amount": amount,
            "currency": currency,
            "kind": kind,
            "counterparty_name": counterparty_name,
            "counterparty_email": "treasury@example.com",  # PII; rail MUST NOT extract
            "counterparty_address": "1 Main St, Anytown, USA",  # PII
            "counterparty_routing_number": "021000089",  # banking PII
            "counterparty_account_number": "999111888777",  # banking PII
            "memo": "thank you for the work — Q2 retainer",  # free text PII
            "status": "settled",
            "created_at": created_at,
            "posted_at": created_at,
        },
    }


def _wire_incoming_payload(**overrides: object) -> dict:
    overrides.setdefault("kind", "wire_incoming")
    overrides.setdefault("counterparty_name", "Foundation Trust")
    overrides.setdefault("amount", "5000.00")
    overrides.setdefault("currency", "EUR")
    return _ach_incoming_payload(**overrides)  # type: ignore[arg-type]


def _check_deposit_payload(**overrides: object) -> dict:
    overrides.setdefault("kind", "check_deposit")
    overrides.setdefault("counterparty_name", "Cash Deposit")
    overrides.setdefault("amount", "250.00")
    return _ach_incoming_payload(**overrides)  # type: ignore[arg-type]


def _outgoing_payload(*, kind: str = "ach_outgoing") -> dict:
    return _ach_incoming_payload(kind=kind, counterparty_name="Vendor Co")


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_ingest_ach_incoming_returns_normalized_event() -> None:
    payload = _ach_incoming_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.event_kind is MercuryEventKind.TRANSACTION_CREATED
    assert event.direction is MercuryTransactionDirection.INCOMING
    assert event.counterparty_handle == "Acme Foundation"
    assert event.amount_currency_cents == 10000
    assert event.currency == "USD"


def test_ingest_transaction_updated_returns_normalized_event() -> None:
    payload = _ach_incoming_payload(event_type="transaction.updated")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.event_kind is MercuryEventKind.TRANSACTION_UPDATED


@pytest.mark.parametrize(
    "kind",
    [
        "ach_incoming",
        "wire_incoming",
        "check_deposit",
        "incoming_credit",
        "credit_returned",
        "interest",
        "refund_received",
    ],
)
def test_all_incoming_kinds_pass_direction_filter(kind: str) -> None:
    payload = _ach_incoming_payload(kind=kind)
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.direction is MercuryTransactionDirection.INCOMING


# ---------------------------------------------------------------------------
# Direction filter: outgoing rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "ach_outgoing",
        "wire_outgoing",
        "check_outgoing",
        "card_purchase",
        "ach_origination",
        "platform_payment",
        "fee",
        "interest_paid",
    ],
)
def test_outgoing_kinds_are_rejected(kind: str) -> None:
    payload = _outgoing_payload(kind=kind)
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"refusing outgoing"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_unknown_kind_is_rejected() -> None:
    payload = _ach_incoming_payload(kind="quantum_teleport")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"unknown transaction kind"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_kind_is_rejected() -> None:
    payload = _ach_incoming_payload()
    del payload["data"]["kind"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'kind'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# HMAC SHA-256 verification
# ---------------------------------------------------------------------------


def test_signature_mismatch_fails_closed() -> None:
    payload = _ach_incoming_payload()
    raw = _canonical(payload)
    bad_sig = "0" * 64
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"signature mismatch"):
            receiver.ingest_webhook(payload, bad_sig, raw_body=raw)


def test_signature_with_sha256_prefix_accepted() -> None:
    payload = _ach_incoming_payload()
    raw = _canonical(payload)
    sig = "sha256=" + _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None


def test_signature_provided_but_secret_unset_fails() -> None:
    payload = _ach_incoming_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ReceiveOnlyRailError, match=r"is not set"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_signature_none_skips_verification() -> None:
    payload = _ach_incoming_payload()
    raw = _canonical(payload)
    receiver = MercuryRailReceiver()
    event = receiver.ingest_webhook(payload, None, raw_body=raw)
    assert event is not None
    assert event.counterparty_handle == "Acme Foundation"


def test_signature_uses_raw_body_not_reencoded_payload() -> None:
    """Live deliveries sign the original wire bytes; receiver must use raw_body."""
    payload = _ach_incoming_payload()
    wire_bytes = b'{"type":"transaction.created","data":{"id":"x"}}'
    sig = _sign(wire_bytes)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"signature mismatch"):
            receiver.ingest_webhook(payload, sig, raw_body=_canonical(payload))


# ---------------------------------------------------------------------------
# Banking-PII guard — the receive-only invariant
# ---------------------------------------------------------------------------


def test_normalized_event_carries_no_banking_pii() -> None:
    payload = _ach_incoming_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    field_names = set(MercuryTransactionEvent.model_fields.keys())
    forbidden = {
        "counterparty_email",
        "counterparty_address",
        "counterparty_routing_number",
        "counterparty_account_number",
        "memo",
        "status",
        "transaction_id",
    }
    assert field_names.isdisjoint(forbidden)
    serialized = event.model_dump_json()
    assert "021000089" not in serialized
    assert "999111888777" not in serialized
    assert "treasury@example.com" not in serialized
    assert "1 Main St" not in serialized
    assert "Q2 retainer" not in serialized


def test_event_refuses_extras_at_construction() -> None:
    """Schema is frozen + extra='forbid'."""
    base = {
        "counterparty_handle": "Acme",
        "amount_currency_cents": 10000,
        "currency": "USD",
        "event_kind": MercuryEventKind.TRANSACTION_CREATED,
        "direction": MercuryTransactionDirection.INCOMING,
        "occurred_at": datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        "raw_payload_sha256": "0" * 64,
    }
    for forbidden in ("counterparty_email", "memo", "routing_number"):
        with pytest.raises(Exception, match=r"forbid|extra"):
            MercuryTransactionEvent(**{**base, forbidden: "x"})  # type: ignore[arg-type]


def test_handle_with_at_sign_is_rejected() -> None:
    payload = _ach_incoming_payload(counterparty_name="leak@example.com")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"validation"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Multi-currency
# ---------------------------------------------------------------------------


def test_eur_wire_normalizes_to_cents() -> None:
    payload = _wire_incoming_payload(amount="1234.56", currency="EUR")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 123456
    assert event.currency == "EUR"


def test_jpy_zero_decimal_currency_passes_through() -> None:
    """JPY is zero-decimal in ISO 4217; the cents normalization × 100 still
    produces the natural integer minor-unit representation."""
    payload = _wire_incoming_payload(amount="1500", currency="JPY")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 150000
    assert event.currency == "JPY"


def test_lowercase_currency_is_normalized_to_upper() -> None:
    payload = _ach_incoming_payload(currency="usd")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.currency == "USD"


def test_negative_amount_is_absolute_value() -> None:
    """Mercury occasionally signs reversals; receiver expresses gross movement."""
    payload = _ach_incoming_payload(amount="-50.00", kind="credit_returned")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 5000


def test_invalid_currency_format_fails_closed() -> None:
    payload = _ach_incoming_payload(currency="DOLLAR")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"validation"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Schema rejection — missing / malformed fields
# ---------------------------------------------------------------------------


def test_non_dict_payload_fails() -> None:
    receiver = MercuryRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match=r"must be a dict"):
        receiver.ingest_webhook("not-a-dict", None)  # type: ignore[arg-type]


def test_missing_data_object_fails() -> None:
    payload: dict = {"type": "transaction.created"}
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"'data' / 'transaction'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_legacy_transaction_key_accepted() -> None:
    """Some legacy / partner forwarders use 'transaction' instead of 'data'."""
    payload = _ach_incoming_payload()
    payload["transaction"] = payload.pop("data")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.counterparty_handle == "Acme Foundation"


def test_missing_counterparty_name_fails() -> None:
    payload = _ach_incoming_payload()
    del payload["data"]["counterparty_name"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'counterparty_name'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_amount_fails() -> None:
    payload = _ach_incoming_payload()
    del payload["data"]["amount"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'amount'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_amount_as_bool_fails() -> None:
    payload = _ach_incoming_payload()
    payload["data"]["amount"] = True  # type: ignore[assignment]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"numeric string or number"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_invalid_decimal_amount_fails() -> None:
    payload = _ach_incoming_payload(amount="not-a-number")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"invalid 'amount'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_currency_fails() -> None:
    payload = _ach_incoming_payload()
    del payload["data"]["currency"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'currency'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_timestamp_fails() -> None:
    payload = _ach_incoming_payload()
    del payload["data"]["created_at"]
    del payload["data"]["posted_at"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'created_at'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_invalid_timestamp_fails() -> None:
    payload = _ach_incoming_payload(created_at="yesterday-noon")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"invalid ISO 8601"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_unknown_event_type_fails() -> None:
    payload = _ach_incoming_payload(event_type="account.balance_changed")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"unaccepted webhook event type"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_non_string_event_type_fails() -> None:
    payload = _ach_incoming_payload()
    payload["type"] = 42  # type: ignore[assignment]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"must be a string"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Heartbeat / no-op
# ---------------------------------------------------------------------------


def test_empty_payload_with_no_signature_returns_none() -> None:
    receiver = MercuryRailReceiver()
    assert receiver.ingest_webhook({}, None) is None


# ---------------------------------------------------------------------------
# Payload hash + raw-body fallback
# ---------------------------------------------------------------------------


def test_raw_payload_sha256_hex_format() -> None:
    payload = _ach_incoming_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert len(event.raw_payload_sha256) == 64
    assert all(c in "0123456789abcdef" for c in event.raw_payload_sha256)


def test_raw_body_fallback_uses_canonical_encoding() -> None:
    payload = _ach_incoming_payload()
    canonical = _canonical(payload)
    sig = _sign(canonical)
    receiver = MercuryRailReceiver()
    with mock.patch.dict("os.environ", {MERCURY_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig)  # raw_body omitted
    assert event is not None


# ---------------------------------------------------------------------------
# Module-level static checks
# ---------------------------------------------------------------------------


def test_module_carries_no_outbound_calls() -> None:
    """Receive-only rail; source must not import network clients."""
    import inspect

    import shared.mercury_receive_only_rail as mod

    src = inspect.getsource(mod)
    forbidden = ("requests.", "httpx.", "urllib.request", "aiohttp", "import mercury")
    for token in forbidden:
        assert token not in src, f"unexpected I/O reference: {token!r}"


def test_module_carries_no_send_path() -> None:
    """Receive-only rail; source must not declare any send/transfer/payout."""
    import inspect

    import shared.mercury_receive_only_rail as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer_out",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


def test_incoming_and_outgoing_kinds_are_disjoint() -> None:
    from shared.mercury_receive_only_rail import _INCOMING_KINDS, _OUTGOING_KINDS

    assert _INCOMING_KINDS.isdisjoint(_OUTGOING_KINDS)


def test_secret_env_var_constant_is_canonical() -> None:
    assert MERCURY_WEBHOOK_SECRET_ENV == "MERCURY_WEBHOOK_SECRET"


def test_receive_only_error_subclasses_exception() -> None:
    assert issubclass(ReceiveOnlyRailError, Exception)


# ---------------------------------------------------------------------------
# jr-mercury-rail-idempotency-pin regression pins
# ---------------------------------------------------------------------------


def test_idempotency_store_rejects_duplicate_txn_id(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "mercury-idem.db")
    receiver = MercuryRailReceiver(idempotency_store=store)
    payload = _ach_incoming_payload()
    payload["data"]["id"] = "txn-test-001"

    first = receiver.ingest_webhook(payload, signature=None)
    second = receiver.ingest_webhook(payload, signature=None)

    assert first is not None
    assert second is None


def test_idempotency_store_distinct_txn_ids_both_processed(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "mercury-idem.db")
    receiver = MercuryRailReceiver(idempotency_store=store)
    payload_a = _ach_incoming_payload()
    payload_a["data"]["id"] = "txn-a"
    payload_b = _ach_incoming_payload()
    payload_b["data"]["id"] = "txn-b"

    first = receiver.ingest_webhook(payload_a, signature=None)
    second = receiver.ingest_webhook(payload_b, signature=None)

    assert first is not None
    assert second is not None


def test_idempotency_store_provided_but_data_id_missing_raises(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "mercury-idem.db")
    receiver = MercuryRailReceiver(idempotency_store=store)
    payload = _ach_incoming_payload()
    del payload["data"]["id"]

    with pytest.raises(ReceiveOnlyRailError, match="data.id"):
        receiver.ingest_webhook(payload, signature=None)


def test_no_idempotency_store_means_no_idempotency_check():
    receiver = MercuryRailReceiver()
    payload = _ach_incoming_payload()
    a = receiver.ingest_webhook(payload, signature=None)
    b = receiver.ingest_webhook(payload, signature=None)
    assert a is not None
    assert b is not None


def test_idempotency_store_persists_across_receivers(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    db = tmp_path / "mercury-idem.db"
    payload = _ach_incoming_payload()
    payload["data"]["id"] = "txn-persist"

    a = MercuryRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    first = a.ingest_webhook(payload, signature=None)
    b = MercuryRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    second = b.ingest_webhook(payload, signature=None)

    assert first is not None
    assert second is None
