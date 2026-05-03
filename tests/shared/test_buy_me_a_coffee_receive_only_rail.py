"""Tests for the Buy Me a Coffee receive-only rail.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from shared.buy_me_a_coffee_receive_only_rail import (
    BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV,
    BuyMeACoffeeRailReceiver,
    CoffeeEvent,
    CoffeeEventKind,
    ReceiveOnlyRailError,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_VALID_SECRET = "bmac-webhook-secret-aBcDeFgHiJkLmN"


def _sign(payload_bytes: bytes, secret: str = _VALID_SECRET) -> str:
    """Compute the X-Signature-Sha256 hex digest BMaC would ship."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def _canonical(payload: dict) -> bytes:
    """Round-trip canonical bytes used by tests as the 'raw' body."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _donation_payload(
    *,
    supporter_name: str = "Cosmo Kramer",
    amount: str = "5.00",
    currency: str = "USD",
    created_at: str = "2026-05-02T12:00:00Z",
) -> dict:
    return {
        "type": "donation",
        "live_mode": True,
        "attempt": 1,
        "created": created_at,
        "event_id": "11111111-1111-1111-1111-111111111111",
        "data": {
            "id": "donation-id-1",
            "supporter_name": supporter_name,
            "amount": amount,
            "currency": currency,
            "created_at": created_at,
            "support_note": "thanks for the work",
            "supporter_email": "supporter@example.com",  # PII; rail must NOT extract
        },
    }


def _membership_started_payload(
    *,
    supporter_name: str = "Elaine Benes",
    amount: str = "12.50",
    currency: str = "EUR",
    created_at: str = "2026-05-02T12:01:00Z",
) -> dict:
    return {
        "type": "membership.started",
        "live_mode": True,
        "attempt": 1,
        "created": created_at,
        "event_id": "22222222-2222-2222-2222-222222222222",
        "data": {
            "id": "membership-id-2",
            "supporter_name": supporter_name,
            "amount": amount,
            "currency": currency,
            "created_at": created_at,
            "membership_level_id": 7,
            "membership_level_name": "Patron",
        },
    }


def _membership_cancelled_payload(
    *,
    supporter_name: str = "Newman",
    amount: str = "200.00",
    currency: str = "GBP",
    created_at: str = "2026-05-02T12:02:00Z",
) -> dict:
    return {
        "type": "membership.cancelled",
        "live_mode": True,
        "attempt": 1,
        "created": created_at,
        "event_id": "33333333-3333-3333-3333-333333333333",
        "data": {
            "id": "membership-id-3",
            "supporter_name": supporter_name,
            "amount": amount,
            "currency": currency,
            "created_at": created_at,
            "membership_level_id": 11,
            "membership_level_name": "Devotee",
            "cancellation_reason": "supporter_initiated",
        },
    }


def _extras_purchase_payload(
    *,
    supporter_name: str = "Jerry",
    amount: str = "1500",
    currency: str = "JPY",
    created_at: str = "2026-05-02T12:03:00Z",
) -> dict:
    return {
        "type": "extras_purchase",
        "live_mode": True,
        "attempt": 1,
        "created": created_at,
        "event_id": "44444444-4444-4444-4444-444444444444",
        "data": {
            "id": "extras-id-4",
            "supporter_name": supporter_name,
            "amount": amount,
            "currency": currency,
            "created_at": created_at,
            "extras_id": "abc123",
            "extras_name": "Sticker Pack",
            "quantity": 1,
        },
    }


# ---------------------------------------------------------------------------
# Happy paths × 4 event kinds
# ---------------------------------------------------------------------------


def test_ingest_donation_returns_normalized_event():
    payload = _donation_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert isinstance(event, CoffeeEvent)
    assert event.event_kind is CoffeeEventKind.DONATION
    assert event.supporter_handle == "Cosmo Kramer"
    assert event.amount_currency_cents == 500
    assert event.currency == "USD"
    assert event.occurred_at == datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    assert len(event.raw_payload_sha256) == 64


def test_ingest_membership_started_returns_normalized_event():
    payload = _membership_started_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.event_kind is CoffeeEventKind.MEMBERSHIP_STARTED
    assert event.amount_currency_cents == 1250
    assert event.currency == "EUR"


def test_ingest_membership_cancelled_returns_normalized_event():
    payload = _membership_cancelled_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.event_kind is CoffeeEventKind.MEMBERSHIP_CANCELLED
    assert event.amount_currency_cents == 20000
    assert event.currency == "GBP"


def test_ingest_extras_purchase_returns_normalized_event():
    payload = _extras_purchase_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.event_kind is CoffeeEventKind.EXTRAS_PURCHASE
    # JPY is a zero-decimal currency, but BMaC ships strings; the rail
    # multiplies by 100 uniformly. Downstream consumers that need
    # currency-specific minor-unit handling can post-process.
    assert event.amount_currency_cents == 150000
    assert event.currency == "JPY"


# ---------------------------------------------------------------------------
# HMAC SHA-256 signature verification
# ---------------------------------------------------------------------------


def test_valid_hmac_signature_succeeds():
    payload = _donation_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None


def test_signature_with_sha256_prefix_accepted():
    payload = _donation_payload()
    raw = _canonical(payload)
    sig = "sha256=" + _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None


def test_invalid_hmac_signature_rejected():
    payload = _donation_payload()
    raw = _canonical(payload)
    bad_sig = _sign(raw, secret="WRONG-SECRET")
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="HMAC SHA-256 signature mismatch"):
            receiver.ingest_webhook(payload, bad_sig, raw_body=raw)


def test_unset_secret_with_signature_present_rejected():
    payload = _donation_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict("os.environ", {}, clear=True):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="not set"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_signature_none_skips_verification():
    """Tests/devtools may pass signature=None to skip env lookup."""
    payload = _donation_payload()
    with mock.patch.dict("os.environ", {}, clear=True):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, None)
    assert event is not None
    assert event.event_kind is CoffeeEventKind.DONATION


def test_raw_body_falls_back_to_canonical_when_omitted():
    """If raw_body is not passed, signature is computed over canonical bytes."""
    payload = _donation_payload()
    canonical = _canonical(payload)
    sig = _sign(canonical)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        # Note: no raw_body= passed; receiver canonical-encodes payload.
        event = receiver.ingest_webhook(payload, sig)
    assert event is not None


# ---------------------------------------------------------------------------
# Multi-currency handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "currency,expected_upper",
    [("usd", "USD"), ("EUR", "EUR"), ("gbp", "GBP"), ("cad", "CAD"), ("AUD", "AUD")],
)
def test_multi_currency_normalized_to_uppercase_iso_4217(
    currency: str, expected_upper: str
) -> None:
    payload = _donation_payload(currency=currency)
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.currency == expected_upper


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
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == expected_cents


def test_negative_amount_normalized_to_absolute():
    """Refunds/credits ship as negative; rail expresses gross movement."""
    payload = _donation_payload(amount="-5.00")
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.amount_currency_cents == 500


# ---------------------------------------------------------------------------
# Event kind aliases and rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alias,expected_kind",
    [
        ("coffee_purchase", CoffeeEventKind.DONATION),
        ("Donation", CoffeeEventKind.DONATION),
        ("membership_started", CoffeeEventKind.MEMBERSHIP_STARTED),
        ("membership.created", CoffeeEventKind.MEMBERSHIP_STARTED),
        ("membership_cancelled", CoffeeEventKind.MEMBERSHIP_CANCELLED),
        ("membership.canceled", CoffeeEventKind.MEMBERSHIP_CANCELLED),
        ("extras.purchase", CoffeeEventKind.EXTRAS_PURCHASE),
        ("extras_purchased", CoffeeEventKind.EXTRAS_PURCHASE),
    ],
)
def test_documented_event_aliases_coerce_to_canonical_kind(
    alias: str, expected_kind: CoffeeEventKind
) -> None:
    payload = _donation_payload()
    payload["type"] = alias
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.event_kind is expected_kind


def test_unknown_event_type_raises():
    payload = _donation_payload()
    payload["type"] = "membership.level_updated"  # known-but-unaccepted
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="unaccepted webhook event type"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_event_type_not_string_raises():
    payload = _donation_payload()
    payload["type"] = 42
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="must be a string"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Envelope shape: data vs response key
# ---------------------------------------------------------------------------


def test_legacy_response_key_accepted_when_data_absent():
    """Legacy / Laravel-doc-shape deliveries nest under 'response' not 'data'."""
    payload = {
        "type": "donation",
        "created": "2026-05-02T12:00:00Z",
        "response": {
            "supporter_name": "Legacy Sender",
            "amount": "3.00",
            "currency": "USD",
            "support_created_on": "2026-05-02T12:00:00Z",
        },
    }
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.supporter_handle == "Legacy Sender"
    assert event.amount_currency_cents == 300


def test_data_takes_precedence_over_response_when_both_present():
    payload = _donation_payload()
    payload["response"] = {
        "supporter_name": "Should Be Ignored",
        "amount": "999.99",
        "currency": "EUR",
    }
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.supporter_handle == "Cosmo Kramer"  # from data
    assert event.currency == "USD"


# ---------------------------------------------------------------------------
# Malformed payload rejection
# ---------------------------------------------------------------------------


def test_payload_not_dict_raises():
    receiver = BuyMeACoffeeRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="payload must be a dict"):
        receiver.ingest_webhook("not a dict", None)  # type: ignore[arg-type]


def test_payload_missing_data_object_raises():
    payload = {"type": "donation", "created": "2026-05-02T12:00:00Z"}
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 'data' / 'response'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_payload_missing_supporter_name_raises():
    payload = _donation_payload()
    del payload["data"]["supporter_name"]
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 'supporter_name'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_payload_missing_amount_raises():
    payload = _donation_payload()
    del payload["data"]["amount"]
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 'amount'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_payload_missing_currency_raises():
    payload = _donation_payload()
    del payload["data"]["currency"]
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 'currency'"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_payload_missing_all_timestamps_raises():
    payload = _donation_payload()
    del payload["data"]["created_at"]
    del payload["created"]
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="created_at"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_envelope_created_used_when_data_created_at_absent():
    """Falls back to envelope `created` if `data.created_at` is absent."""
    payload = _donation_payload()
    del payload["data"]["created_at"]
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.occurred_at == datetime(2026, 5, 2, 12, 0, tzinfo=UTC)


def test_invalid_amount_decimal_string_raises():
    payload = _donation_payload(amount="not-a-number")
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="invalid 'amount' decimal"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_invalid_iso_timestamp_raises():
    payload = _donation_payload(created_at="not-a-real-date")
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="invalid ISO 8601 timestamp"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_supporter_handle_with_email_rejected_at_validation():
    """Defensive: even if BMaC ever leaks an email in supporter_name, reject it."""
    payload = _donation_payload(supporter_name="leaked@example.com")
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="must be a BMaC display name"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_amount_as_bool_rejected():
    payload = _donation_payload()
    payload["data"]["amount"] = True
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="must be a numeric string or number"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


# ---------------------------------------------------------------------------
# Receive-only invariant: NO outbound network calls
# ---------------------------------------------------------------------------


def test_no_outbound_network_calls_during_ingest():
    """Mock urllib + assert the receiver never invokes it across all 4 kinds."""
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with (
            mock.patch("urllib.request.urlopen") as mock_urlopen,
            mock.patch("urllib.request.Request") as mock_request,
        ):
            for builder in (
                _donation_payload,
                _membership_started_payload,
                _membership_cancelled_payload,
                _extras_purchase_payload,
            ):
                payload = builder()
                raw = _canonical(payload)
                sig = _sign(raw)
                event = receiver.ingest_webhook(payload, sig, raw_body=raw)
                assert event is not None
            # Also exercise an error path — no network even when failing.
            with pytest.raises(ReceiveOnlyRailError):
                bad = _donation_payload()
                bad["type"] = "garbage.event"
                bad_raw = _canonical(bad)
                bad_sig = _sign(bad_raw)
                receiver.ingest_webhook(bad, bad_sig, raw_body=bad_raw)
        assert mock_urlopen.call_count == 0
        assert mock_request.call_count == 0


def test_receiver_does_not_import_or_use_httpx():
    """If httpx is in the env, ensure none of its surfaces are invoked."""
    pytest.importorskip("httpx")
    import httpx  # type: ignore[import-not-found]

    payload = _donation_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        with (
            mock.patch.object(httpx, "Client") as mock_client,
            mock.patch.object(httpx, "AsyncClient") as mock_async_client,
            mock.patch.object(httpx, "post") as mock_post,
            mock.patch.object(httpx, "get") as mock_get,
        ):
            event = receiver.ingest_webhook(payload, sig, raw_body=raw)
            assert event is not None
        assert mock_client.call_count == 0
        assert mock_async_client.call_count == 0
        assert mock_post.call_count == 0
        assert mock_get.call_count == 0


def test_receiver_does_not_import_bmac_sdk():
    """The production module must NOT import any BMaC SDK."""
    import shared.buy_me_a_coffee_receive_only_rail as rail_mod

    src = rail_mod.__file__
    assert src is not None
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    # No official BMaC SDK packages exist on PyPI under these names today,
    # but pin the invariant defensively for future drift.
    assert "\nimport buymeacoffee" not in text
    assert "\nfrom buymeacoffee " not in text
    assert "\nimport bmac" not in text
    assert "\nfrom bmac " not in text
    assert "\nimport buy_me_a_coffee" not in text
    assert "\nfrom buy_me_a_coffee " not in text


# ---------------------------------------------------------------------------
# Other invariants
# ---------------------------------------------------------------------------


def test_empty_payload_with_signature_none_returns_none():
    receiver = BuyMeACoffeeRailReceiver()
    assert receiver.ingest_webhook({}, None) is None


def test_sha256_in_event_matches_raw_body():
    payload = _donation_payload()
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    expected = hashlib.sha256(raw).hexdigest()
    assert event is not None
    assert event.raw_payload_sha256 == expected


def test_coffee_event_is_frozen_no_pii_fields():
    """Pydantic ``extra='forbid'`` rejects PII keys at construction time."""
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        CoffeeEvent(
            supporter_handle="Cosmo Kramer",
            amount_currency_cents=500,
            currency="USD",
            event_kind=CoffeeEventKind.DONATION,
            occurred_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            raw_payload_sha256="a" * 64,
            email="leaked@example.com",  # type: ignore[call-arg]
        )


def test_anonymous_supporter_handle_passthrough():
    """BMaC ships ``supporter_name="Anonymous"`` for unattributed support."""
    payload = _donation_payload(supporter_name="Anonymous")
    raw = _canonical(payload)
    sig = _sign(raw)
    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        event = receiver.ingest_webhook(payload, sig, raw_body=raw)
    assert event is not None
    assert event.supporter_handle == "Anonymous"


# ---------------------------------------------------------------------------
# jr-buy-me-a-coffee-rail-idempotency-pin regression pins
# ---------------------------------------------------------------------------


def test_idempotency_store_rejects_duplicate_event_id(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "bmac-idem.db")
    receiver = BuyMeACoffeeRailReceiver(idempotency_store=store)
    payload = _donation_payload()
    payload["event_id"] = "evt-bmac-test-001"
    raw = _canonical(payload)
    sig = _sign(raw)

    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        first = receiver.ingest_webhook(payload, sig, raw_body=raw)
        second = receiver.ingest_webhook(payload, sig, raw_body=raw)

    assert first is not None
    assert second is None  # short-circuit


def test_idempotency_store_distinct_event_ids_both_processed(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "bmac-idem.db")
    receiver = BuyMeACoffeeRailReceiver(idempotency_store=store)

    payload_a = _donation_payload()
    payload_a["event_id"] = "evt-a"
    raw_a = _canonical(payload_a)
    sig_a = _sign(raw_a)

    payload_b = _donation_payload(supporter_name="Bob")
    payload_b["event_id"] = "evt-b"
    raw_b = _canonical(payload_b)
    sig_b = _sign(raw_b)

    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        first = receiver.ingest_webhook(payload_a, sig_a, raw_body=raw_a)
        second = receiver.ingest_webhook(payload_b, sig_b, raw_body=raw_b)

    assert first is not None
    assert second is not None


def test_idempotency_store_provided_but_event_id_missing_raises(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "bmac-idem.db")
    receiver = BuyMeACoffeeRailReceiver(idempotency_store=store)
    payload = _donation_payload()
    del payload["event_id"]
    raw = _canonical(payload)
    sig = _sign(raw)

    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        with pytest.raises(ReceiveOnlyRailError, match="event_id"):
            receiver.ingest_webhook(payload, sig, raw_body=raw)


def test_no_idempotency_store_means_no_idempotency_check():
    payload = _donation_payload()
    payload["event_id"] = "ignored-without-store"
    raw = _canonical(payload)
    sig = _sign(raw)

    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        receiver = BuyMeACoffeeRailReceiver()
        a = receiver.ingest_webhook(payload, sig, raw_body=raw)
        b = receiver.ingest_webhook(payload, sig, raw_body=raw)

    assert a is not None
    assert b is not None  # no short-circuit


def test_idempotency_store_persists_across_receivers(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    db = tmp_path / "bmac-idem.db"
    payload = _donation_payload()
    payload["event_id"] = "evt-persist"
    raw = _canonical(payload)
    sig = _sign(raw)

    with mock.patch.dict(
        "os.environ", {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV: _VALID_SECRET}, clear=False
    ):
        a = BuyMeACoffeeRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
        first = a.ingest_webhook(payload, sig, raw_body=raw)
        b = BuyMeACoffeeRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
        second = b.ingest_webhook(payload, sig, raw_body=raw)

    assert first is not None
    assert second is None
