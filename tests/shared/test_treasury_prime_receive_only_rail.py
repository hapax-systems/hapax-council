"""Tests for the Treasury Prime receive-only rail (Phase 0).

cc-task: treasury-prime-receive-only-rail.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from shared.treasury_prime_receive_only_rail import (
    TREASURY_PRIME_WEBHOOK_SECRET_ENV,
    IncomingAchEvent,
    IncomingAchEventKind,
    ReceiveOnlyRailError,
    TreasuryPrimeRailReceiver,
)

_VALID_SECRET = "treasury-prime-webhook-secret-aBcDeFgHiJkLmN"


def _sign(payload_bytes: bytes, secret: str = _VALID_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _ach_payload(
    *,
    event: str = "incoming_ach.create",
    originating_party_name: str = "Acme Foundation",
    amount: object = 10000,
    currency: str = "USD",
    created_at: str = "2026-05-02T12:00:00Z",
) -> dict:
    """Realistic Treasury Prime delivery for an incoming ACH on a ledger account.

    Includes banking PII fields the receiver MUST NOT extract.
    """
    return {
        "event": event,
        "data": {
            "id": "tp-incoming-ach-uuid",
            "amount": amount,
            "currency": currency,
            "originating_party_name": originating_party_name,
            "originating_account_number": "999111888777",  # banking PII
            "originating_routing_number": "021000089",  # banking PII
            "originating_address": "1 Main St",  # PII
            "trace_number": "TRACE-12345",  # internal banking metadata
            "company_entry_description": "PAYROLL-Q2",  # internal metadata
            "ledger_account_id": "la-uuid-1234",  # operator-internal
            "settlement_date": "2026-05-04",
            "created_at": created_at,
        },
    }


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_ingest_incoming_ach_returns_normalized_event() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.event_kind is IncomingAchEventKind.INCOMING_ACH_CREATED
    assert event.originating_party_handle == "Acme Foundation"
    assert event.amount_currency_cents == 10000
    assert event.currency == "USD"


# ---------------------------------------------------------------------------
# Direction filter via event-kind taxonomy
# ---------------------------------------------------------------------------


def test_ach_origination_event_rejected_as_outgoing() -> None:
    payload = _ach_payload(event="ach_origination.create")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"refusing outgoing"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_payment_order_event_rejected_as_outgoing() -> None:
    payload = _ach_payload(event="payment_order.create")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"refusing outgoing"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_transaction_create_rejected_as_phase_1_scope() -> None:
    """Phase 0 explicitly does not accept core-direct-account events."""
    payload = _ach_payload(event="transaction.create")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"out of Phase 0 scope"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_unknown_event_rejected() -> None:
    payload = _ach_payload(event="account.balance_changed")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"unaccepted webhook event type"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# HMAC SHA-256 verification
# ---------------------------------------------------------------------------


def test_signature_mismatch_fails_closed() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    bad_sig = "0" * 64
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"signature mismatch"):
            receiver.ingest_webhook(payload, bad_sig, raw_body=raw)


def test_signature_with_sha256_prefix_accepted() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    sig = "sha256=" + _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None


def test_signature_provided_but_secret_unset_fails() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ReceiveOnlyRailError, match=r"is not set"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_signature_none_skips_verification() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    receiver = TreasuryPrimeRailReceiver()
    event = receiver.ingest_webhook(payload, None, raw_body=raw)
    assert event is not None


# ---------------------------------------------------------------------------
# Banking-PII guard
# ---------------------------------------------------------------------------


def test_normalized_event_carries_no_banking_pii() -> None:
    payload = _ach_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    field_names = set(IncomingAchEvent.model_fields.keys())
    forbidden = {
        "originating_account_number",
        "originating_routing_number",
        "originating_address",
        "trace_number",
        "company_entry_description",
        "ledger_account_id",
        "settlement_date",
    }
    assert field_names.isdisjoint(forbidden)
    serialized = event.model_dump_json()
    assert "021000089" not in serialized
    assert "999111888777" not in serialized
    assert "TRACE-12345" not in serialized
    assert "PAYROLL-Q2" not in serialized
    assert "1 Main St" not in serialized
    assert "la-uuid-1234" not in serialized


def test_event_refuses_extras_at_construction() -> None:
    base = {
        "originating_party_handle": "Acme",
        "amount_currency_cents": 10000,
        "currency": "USD",
        "event_kind": IncomingAchEventKind.INCOMING_ACH_CREATED,
        "occurred_at": datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        "raw_payload_sha256": "0" * 64,
    }
    for forbidden in ("trace_number", "company_entry_description", "ledger_account_id"):
        with pytest.raises(Exception, match=r"forbid|extra"):
            IncomingAchEvent(**{**base, forbidden: "x"})  # type: ignore[arg-type]


def test_handle_with_at_sign_is_rejected() -> None:
    payload = _ach_payload(originating_party_name="leak@example.com")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"validation"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Multi-currency + amount normalization
# ---------------------------------------------------------------------------


def test_integer_amount_treated_as_cents() -> None:
    payload = _ach_payload(amount=12345)
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 12345


def test_decimal_string_with_dot_is_major_units() -> None:
    payload = _ach_payload(amount="100.00")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 10000


def test_decimal_string_without_dot_is_already_cents() -> None:
    payload = _ach_payload(amount="10000")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 10000


def test_negative_amount_is_absolute_value() -> None:
    payload = _ach_payload(amount=-5000)
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 5000


def test_lowercase_currency_normalized_to_upper() -> None:
    payload = _ach_payload(currency="usd")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.currency == "USD"


def test_invalid_currency_format_fails() -> None:
    payload = _ach_payload(currency="DOLLAR")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"validation"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_amount_as_bool_fails() -> None:
    payload = _ach_payload(amount=True)
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"numeric string or number"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_invalid_decimal_string_fails() -> None:
    payload = _ach_payload(amount="not-a-number")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"invalid 'amount'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Schema rejection
# ---------------------------------------------------------------------------


def test_non_dict_payload_fails() -> None:
    receiver = TreasuryPrimeRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match=r"must be a dict"):
        receiver.ingest_webhook("not-a-dict", None)  # type: ignore[arg-type]


def test_missing_data_fails() -> None:
    payload: dict = {"event": "incoming_ach.create"}
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'data'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_originating_party_name_fails() -> None:
    payload = _ach_payload()
    del payload["data"]["originating_party_name"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'originating_party_name'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_amount_fails() -> None:
    payload = _ach_payload()
    del payload["data"]["amount"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'amount'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_currency_fails() -> None:
    payload = _ach_payload()
    del payload["data"]["currency"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'currency'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_missing_timestamp_fails() -> None:
    payload = _ach_payload()
    del payload["data"]["created_at"]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"missing 'created_at'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_invalid_timestamp_fails() -> None:
    payload = _ach_payload(created_at="yesterday-noon")
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"invalid ISO 8601"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_non_string_event_fails() -> None:
    payload = _ach_payload()
    payload["event"] = 42  # type: ignore[assignment]
    raw = _canonical(payload)
    sig = _sign(raw)
    receiver = TreasuryPrimeRailReceiver()
    with mock.patch.dict("os.environ", {TREASURY_PRIME_WEBHOOK_SECRET_ENV: _VALID_SECRET}):
        with pytest.raises(ReceiveOnlyRailError, match=r"must be a string"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Heartbeat / no-op
# ---------------------------------------------------------------------------


def test_empty_payload_with_no_signature_returns_none() -> None:
    receiver = TreasuryPrimeRailReceiver()
    assert receiver.ingest_webhook({}, None) is None


# ---------------------------------------------------------------------------
# Module-level static checks
# ---------------------------------------------------------------------------


def test_module_carries_no_outbound_calls() -> None:
    import inspect

    import shared.treasury_prime_receive_only_rail as mod

    src = inspect.getsource(mod)
    forbidden = ("requests.", "httpx.", "urllib.request", "aiohttp", "treasuryprime")
    for token in forbidden:
        assert token not in src, f"unexpected I/O reference: {token!r}"


def test_module_carries_no_send_path() -> None:
    import inspect

    import shared.treasury_prime_receive_only_rail as mod

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
    assert TREASURY_PRIME_WEBHOOK_SECRET_ENV == "TREASURY_PRIME_WEBHOOK_SECRET"


def test_event_kind_enum_only_accepts_phase_0_event() -> None:
    """Phase 0 accepts ONLY incoming_ach.create."""
    assert {k.value for k in IncomingAchEventKind} == {"incoming_ach.create"}


def test_receive_only_error_subclasses_exception() -> None:
    assert issubclass(ReceiveOnlyRailError, Exception)


# ---------------------------------------------------------------------------
# jr-treasury-prime-rail-idempotency-pin regression pins
# ---------------------------------------------------------------------------


def test_idempotency_store_rejects_duplicate_ach_id(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "tp-idem.db")
    receiver = TreasuryPrimeRailReceiver(idempotency_store=store)
    payload = _ach_payload()
    payload["data"]["id"] = "tp-test-001"

    first = receiver.ingest_webhook(payload, signature=None)
    second = receiver.ingest_webhook(payload, signature=None)

    assert first is not None
    assert second is None


def test_idempotency_store_distinct_ach_ids_both_processed(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "tp-idem.db")
    receiver = TreasuryPrimeRailReceiver(idempotency_store=store)
    payload_a = _ach_payload()
    payload_a["data"]["id"] = "tp-a"
    payload_b = _ach_payload()
    payload_b["data"]["id"] = "tp-b"

    first = receiver.ingest_webhook(payload_a, signature=None)
    second = receiver.ingest_webhook(payload_b, signature=None)

    assert first is not None
    assert second is not None


def test_idempotency_store_provided_but_data_id_missing_raises(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "tp-idem.db")
    receiver = TreasuryPrimeRailReceiver(idempotency_store=store)
    payload = _ach_payload()
    del payload["data"]["id"]

    with pytest.raises(ReceiveOnlyRailError, match="data.id"):
        receiver.ingest_webhook(payload, signature=None)


def test_no_idempotency_store_means_no_idempotency_check():
    receiver = TreasuryPrimeRailReceiver()
    payload = _ach_payload()
    a = receiver.ingest_webhook(payload, signature=None)
    b = receiver.ingest_webhook(payload, signature=None)
    assert a is not None
    assert b is not None


def test_idempotency_store_persists_across_receivers(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    db = tmp_path / "tp-idem.db"
    payload = _ach_payload()
    payload["data"]["id"] = "tp-persist"

    a = TreasuryPrimeRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    first = a.ingest_webhook(payload, signature=None)
    b = TreasuryPrimeRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    second = b.ingest_webhook(payload, signature=None)

    assert first is not None
    assert second is None
