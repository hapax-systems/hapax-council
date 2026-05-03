"""Tests for the Ko-fi receive-only rail.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from shared.ko_fi_receive_only_rail import (
    KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV,
    KoFiEvent,
    KoFiEventKind,
    KoFiRailReceiver,
    ReceiveOnlyRailError,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_VALID_TOKEN = "test-verification-token-aBcDeFgHiJ"


def _donation_payload(
    *,
    from_name: str = "Cosmo Kramer",
    amount: str = "5.00",
    currency: str = "USD",
    timestamp: str = "2026-05-02T12:00:00Z",
    verification_token: str = _VALID_TOKEN,
) -> dict:
    return {
        "verification_token": verification_token,
        "type": "Donation",
        "from_name": from_name,
        "amount": amount,
        "currency": currency,
        "timestamp": timestamp,
        "kofi_transaction_id": "11111111-1111-1111-1111-111111111111",
        "message": "thanks for the work",
    }


def _subscription_payload(
    *,
    from_name: str = "Elaine Benes",
    amount: str = "12.50",
    currency: str = "EUR",
    timestamp: str = "2026-05-02T12:01:00Z",
) -> dict:
    return {
        "verification_token": _VALID_TOKEN,
        "type": "Subscription",
        "from_name": from_name,
        "amount": amount,
        "currency": currency,
        "timestamp": timestamp,
        "kofi_transaction_id": "22222222-2222-2222-2222-222222222222",
        "is_subscription_payment": True,
        "is_first_subscription_payment": True,
    }


def _commission_payload(
    *,
    from_name: str = "Newman",
    amount: str = "200.00",
    currency: str = "GBP",
    timestamp: str = "2026-05-02T12:02:00Z",
) -> dict:
    return {
        "verification_token": _VALID_TOKEN,
        "type": "Commission",
        "from_name": from_name,
        "amount": amount,
        "currency": currency,
        "timestamp": timestamp,
        "kofi_transaction_id": "33333333-3333-3333-3333-333333333333",
    }


def _shop_order_payload(
    *,
    from_name: str = "Jerry",
    amount: str = "1500",
    currency: str = "JPY",
    timestamp: str = "2026-05-02T12:03:00Z",
) -> dict:
    return {
        "verification_token": _VALID_TOKEN,
        "type": "Shop Order",
        "from_name": from_name,
        "amount": amount,
        "currency": currency,
        "timestamp": timestamp,
        "kofi_transaction_id": "44444444-4444-4444-4444-444444444444",
        "shop_items": [{"direct_link_code": "abc123", "variation_name": "Default", "quantity": 1}],
    }


# ---------------------------------------------------------------------------
# Happy paths × 4 event kinds
# ---------------------------------------------------------------------------


def test_ingest_donation_returns_normalized_event():
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(_donation_payload())
    assert isinstance(event, KoFiEvent)
    assert event.event_kind is KoFiEventKind.DONATION
    assert event.sender_handle == "Cosmo Kramer"
    assert event.amount_currency_cents == 500
    assert event.currency == "USD"
    assert event.occurred_at == datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    assert len(event.raw_payload_sha256) == 64


def test_ingest_subscription_returns_normalized_event():
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(_subscription_payload())
    assert event is not None
    assert event.event_kind is KoFiEventKind.SUBSCRIPTION
    assert event.amount_currency_cents == 1250
    assert event.currency == "EUR"


def test_ingest_commission_returns_normalized_event():
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(_commission_payload())
    assert event is not None
    assert event.event_kind is KoFiEventKind.COMMISSION
    assert event.amount_currency_cents == 20000
    assert event.currency == "GBP"


def test_ingest_shop_order_returns_normalized_event():
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(_shop_order_payload())
    assert event is not None
    assert event.event_kind is KoFiEventKind.SHOP_ORDER
    # JPY is a zero-decimal currency, but Ko-fi still ships strings; the
    # rail multiplies by 100 uniformly. Downstream consumers that need
    # currency-specific minor-unit handling can post-process.
    assert event.amount_currency_cents == 150000
    assert event.currency == "JPY"


# ---------------------------------------------------------------------------
# Verification token validation
# ---------------------------------------------------------------------------


def test_valid_verification_token_succeeds():
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(_donation_payload())
    assert event is not None


def test_mismatched_verification_token_rejected():
    payload = _donation_payload(verification_token="WRONG-TOKEN-aBcDeF")
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="verification_token mismatch"):
            receiver.ingest_webhook(payload)


def test_missing_verification_token_in_payload_rejected():
    payload = _donation_payload()
    del payload["verification_token"]
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 'verification_token'"):
            receiver.ingest_webhook(payload)


def test_unset_env_var_with_token_required_rejected():
    """Even if the payload carries a token, an unset env var must fail closed."""
    with mock.patch.dict("os.environ", {}, clear=True):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="not set"):
            receiver.ingest_webhook(_donation_payload())


def test_verify_token_false_skips_check():
    """Tests/devtools may pass verify_token=False to skip env lookup."""
    payload = _donation_payload()
    del payload["verification_token"]
    with mock.patch.dict("os.environ", {}, clear=True):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(payload, verify_token=False)
    assert event is not None
    assert event.event_kind is KoFiEventKind.DONATION


# ---------------------------------------------------------------------------
# Multi-currency handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "currency,expected_upper",
    [("usd", "USD"), ("EUR", "EUR"), ("gbp", "GBP")],
)
def test_multi_currency_normalized_to_uppercase_iso_4217(
    currency: str, expected_upper: str
) -> None:
    payload = _donation_payload(currency=currency)
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(payload)
    assert event is not None
    assert event.currency == expected_upper


def test_human_readable_type_alias_donation_accepted():
    """Ko-fi ships ``"Donation"``; alias must coerce to canonical kind."""
    payload = _donation_payload()
    assert payload["type"] == "Donation"
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(payload)
    assert event is not None
    assert event.event_kind is KoFiEventKind.DONATION


def test_underscored_canonical_type_accepted():
    """Underscored canonical form is also accepted (parity with siblings)."""
    payload = _donation_payload()
    payload["type"] = "donation"
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(payload)
    assert event is not None
    assert event.event_kind is KoFiEventKind.DONATION


# ---------------------------------------------------------------------------
# Decimal-string amount normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount_str,expected_cents",
    [
        ("5.00", 500),
        ("12.50", 1250),
        ("0.01", 1),
        ("100", 10000),
        ("0.99", 99),
        ("999.99", 99999),
    ],
)
def test_decimal_string_amount_normalized_to_cents(amount_str: str, expected_cents: int) -> None:
    payload = _donation_payload(amount=amount_str)
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(payload)
    assert event is not None
    assert event.amount_currency_cents == expected_cents


def test_negative_amount_normalized_to_absolute():
    """Refunds/credits ship as negative; rail expresses gross movement."""
    payload = _donation_payload(amount="-5.00")
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(payload)
    assert event is not None
    assert event.amount_currency_cents == 500


# ---------------------------------------------------------------------------
# Malformed payload rejection
# ---------------------------------------------------------------------------


def test_unknown_event_type_raises():
    payload = _donation_payload()
    payload["type"] = "Membership"  # known-but-unaccepted
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="unaccepted webhook event type"):
            receiver.ingest_webhook(payload)


def test_payload_not_dict_raises():
    receiver = KoFiRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="payload must be a dict"):
        receiver.ingest_webhook("not a dict")  # type: ignore[arg-type]


def test_payload_missing_from_name_raises():
    payload = _donation_payload()
    del payload["from_name"]
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 'from_name'"):
            receiver.ingest_webhook(payload)


def test_payload_missing_amount_raises():
    payload = _donation_payload()
    del payload["amount"]
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 'amount'"):
            receiver.ingest_webhook(payload)


def test_payload_missing_currency_raises():
    payload = _donation_payload()
    del payload["currency"]
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 'currency'"):
            receiver.ingest_webhook(payload)


def test_payload_missing_timestamp_raises():
    payload = _donation_payload()
    del payload["timestamp"]
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 'timestamp'"):
            receiver.ingest_webhook(payload)


def test_invalid_amount_decimal_string_raises():
    payload = _donation_payload(amount="not-a-number")
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="invalid 'amount' decimal"):
            receiver.ingest_webhook(payload)


def test_event_type_not_string_raises():
    payload = _donation_payload()
    payload["type"] = 42
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="must be a string"):
            receiver.ingest_webhook(payload)


def test_invalid_iso_timestamp_raises():
    payload = _donation_payload(timestamp="not-a-real-date")
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="invalid ISO 8601 timestamp"):
            receiver.ingest_webhook(payload)


def test_sender_handle_with_email_rejected_at_validation():
    """Defensive: even if Ko-fi ever leaks an email in from_name, reject it."""
    payload = _donation_payload(from_name="leaked@example.com")
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="must be a Ko-fi display name"):
            receiver.ingest_webhook(payload)


# ---------------------------------------------------------------------------
# Receive-only invariant: NO outbound network calls
# ---------------------------------------------------------------------------


def test_no_outbound_network_calls_during_ingest():
    """Mock urllib + assert the receiver never invokes it across all 4 kinds."""
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with (
            mock.patch("urllib.request.urlopen") as mock_urlopen,
            mock.patch("urllib.request.Request") as mock_request,
        ):
            for builder in (
                _donation_payload,
                _subscription_payload,
                _commission_payload,
                _shop_order_payload,
            ):
                event = receiver.ingest_webhook(builder())
                assert event is not None
            # Also exercise an error path — no network even when failing.
            with pytest.raises(ReceiveOnlyRailError):
                bad = _donation_payload()
                bad["type"] = "garbage.event"
                receiver.ingest_webhook(bad)
        assert mock_urlopen.call_count == 0
        assert mock_request.call_count == 0


def test_receiver_does_not_import_or_use_httpx():
    """If httpx is in the env, ensure none of its surfaces are invoked."""
    pytest.importorskip("httpx")
    import httpx  # type: ignore[import-not-found]

    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        with (
            mock.patch.object(httpx, "Client") as mock_client,
            mock.patch.object(httpx, "AsyncClient") as mock_async_client,
            mock.patch.object(httpx, "post") as mock_post,
            mock.patch.object(httpx, "get") as mock_get,
        ):
            event = receiver.ingest_webhook(_donation_payload())
            assert event is not None
        assert mock_client.call_count == 0
        assert mock_async_client.call_count == 0
        assert mock_post.call_count == 0
        assert mock_get.call_count == 0


def test_receiver_does_not_import_kofi_sdk():
    """The production module must NOT import any Ko-fi SDK."""
    import shared.ko_fi_receive_only_rail as rail_mod

    src = rail_mod.__file__
    assert src is not None
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    # No Ko-fi SDK packages exist on PyPI under these names today, but
    # pin the invariant defensively for future drift.
    assert "\nimport kofi" not in text
    assert "\nfrom kofi " not in text
    assert "\nimport ko_fi" not in text
    assert "\nfrom ko_fi " not in text


# ---------------------------------------------------------------------------
# Other invariants
# ---------------------------------------------------------------------------


def test_empty_payload_with_verify_off_returns_none():
    receiver = KoFiRailReceiver()
    assert receiver.ingest_webhook({}, verify_token=False) is None


def test_sha256_in_event_matches_canonical_payload():
    payload = _donation_payload()
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(payload)
    expected = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert event is not None
    assert event.raw_payload_sha256 == expected


def test_kofi_event_is_frozen_no_pii_fields():
    """Pydantic ``extra='forbid'`` rejects PII keys at construction time."""
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        KoFiEvent(
            sender_handle="Cosmo Kramer",
            amount_currency_cents=500,
            currency="USD",
            event_kind=KoFiEventKind.DONATION,
            occurred_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            raw_payload_sha256="a" * 64,
            email="leaked@example.com",  # type: ignore[call-arg]
        )


def test_anonymous_supporter_handle_passthrough():
    """Ko-fi ships ``from_name="Anonymous"`` for unattributed support."""
    payload = _donation_payload(from_name="Anonymous")
    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()
        event = receiver.ingest_webhook(payload)
    assert event is not None
    assert event.sender_handle == "Anonymous"


# ---------------------------------------------------------------------------
# jr-ko-fi-rail-idempotency-pin regression pins
# ---------------------------------------------------------------------------


def test_idempotency_store_rejects_duplicate_kofi_transaction_id(tmp_path):
    """Replay of the same kofi_transaction_id is short-circuited to None."""
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "ko-fi-idem.db")
    receiver = KoFiRailReceiver(idempotency_store=store)
    payload = _donation_payload()
    payload["kofi_transaction_id"] = "tx-test-001"

    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        first = receiver.ingest_webhook(payload)
        second = receiver.ingest_webhook(payload)

    assert first is not None
    assert second is None  # short-circuit


def test_idempotency_store_distinct_transaction_ids_both_processed(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "ko-fi-idem.db")
    receiver = KoFiRailReceiver(idempotency_store=store)

    payload_a = _donation_payload()
    payload_a["kofi_transaction_id"] = "tx-a"
    payload_b = _donation_payload(from_name="Bob")
    payload_b["kofi_transaction_id"] = "tx-b"

    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        first = receiver.ingest_webhook(payload_a)
        second = receiver.ingest_webhook(payload_b)

    assert first is not None
    assert second is not None


def test_idempotency_store_provided_but_transaction_id_missing_raises(tmp_path):
    """Idempotency store + missing kofi_transaction_id → fail closed."""
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "ko-fi-idem.db")
    receiver = KoFiRailReceiver(idempotency_store=store)
    payload = _donation_payload()
    del payload["kofi_transaction_id"]

    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        with pytest.raises(ReceiveOnlyRailError, match="kofi_transaction_id"):
            receiver.ingest_webhook(payload)


def test_no_idempotency_store_means_no_idempotency_check():
    """No store → duplicates processed twice (legacy shape)."""
    payload = _donation_payload()
    payload["kofi_transaction_id"] = "ignored-without-store"

    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        receiver = KoFiRailReceiver()  # no idempotency_store
        a = receiver.ingest_webhook(payload)
        b = receiver.ingest_webhook(payload)

    assert a is not None
    assert b is not None  # no short-circuit


def test_idempotency_store_table_persists_on_disk(tmp_path):
    """Two receivers pointed at the same db share the seen-set."""
    from shared._rail_idempotency import IdempotencyStore

    db = tmp_path / "ko-fi-idem.db"
    payload = _donation_payload()
    payload["kofi_transaction_id"] = "tx-persist"

    with mock.patch.dict(
        "os.environ", {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV: _VALID_TOKEN}, clear=False
    ):
        a = KoFiRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
        first = a.ingest_webhook(payload)
        b = KoFiRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
        second = b.ingest_webhook(payload)

    assert first is not None
    assert second is None  # persisted across receivers
