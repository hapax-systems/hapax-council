"""Tests for the Liberapay receive-only rail.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from shared.liberapay_receive_only_rail import (
    LIBERAPAY_REQUIRE_IP_ALLOWLIST_ENV,
    LIBERAPAY_WEBHOOK_SECRET_ENV,
    DonationEvent,
    DonationEventKind,
    LiberapayRailReceiver,
    ReceiveOnlyRailError,
)


def _payload(
    *,
    event: str = "payin_succeeded",
    donor_username: str = "alice",
    amount: str | int | float = "5.00",
    currency: str = "EUR",
    occurred_at: str = "2026-05-02T12:00:00Z",
    timestamp: str | None = None,
    source_ip: str | None = None,
) -> dict:
    payload: dict = {
        "event": event,
        "donor": {"username": donor_username},
        "amount": {"amount": amount, "currency": currency},
        "occurred_at": occurred_at,
    }
    if timestamp is not None:
        del payload["occurred_at"]
        payload["timestamp"] = timestamp
    if source_ip is not None:
        payload["source_ip"] = source_ip
    return payload


def _sign(payload: dict, secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# Happy paths for all 4 accepted event kinds
# ---------------------------------------------------------------------------


def test_ingest_payin_created_returns_normalized_event():
    receiver = LiberapayRailReceiver()
    event = receiver.ingest_webhook(_payload(event="payin_created"), signature=None)
    assert isinstance(event, DonationEvent)
    assert event.event_kind is DonationEventKind.PAYIN_CREATED
    assert event.donor_handle == "alice"
    assert event.amount_eur_cents == 500
    assert event.occurred_at == datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    assert len(event.raw_payload_sha256) == 64


def test_ingest_payin_succeeded_returns_normalized_event():
    receiver = LiberapayRailReceiver()
    event = receiver.ingest_webhook(_payload(event="payin_succeeded"), signature=None)
    assert event is not None
    assert event.event_kind is DonationEventKind.PAYIN_SUCCEEDED


def test_ingest_tip_set_returns_normalized_event():
    receiver = LiberapayRailReceiver()
    event = receiver.ingest_webhook(_payload(event="tip_set", amount="2.50"), signature=None)
    assert event is not None
    assert event.event_kind is DonationEventKind.TIP_SET
    assert event.amount_eur_cents == 250


def test_ingest_tip_cancelled_returns_normalized_event():
    receiver = LiberapayRailReceiver()
    event = receiver.ingest_webhook(_payload(event="tip_cancelled", amount="0.00"), signature=None)
    assert event is not None
    assert event.event_kind is DonationEventKind.TIP_CANCELLED
    assert event.amount_eur_cents == 0


def test_ingest_dotted_action_alias_normalizes_to_canonical_kind():
    """The bridge may forward Liberapay's dotted form (e.g. 'payin.succeeded')."""
    receiver = LiberapayRailReceiver()
    event = receiver.ingest_webhook(_payload(event="payin.succeeded"), signature=None)
    assert event is not None
    assert event.event_kind is DonationEventKind.PAYIN_SUCCEEDED


# ---------------------------------------------------------------------------
# HMAC signature verification
# ---------------------------------------------------------------------------


def test_valid_signature_succeeds():
    secret = "topsecret-shh"
    payload = _payload()
    sig = _sign(payload, secret)
    with mock.patch.dict("os.environ", {LIBERAPAY_WEBHOOK_SECRET_ENV: secret}, clear=False):
        receiver = LiberapayRailReceiver()
        event = receiver.ingest_webhook(payload, signature=sig)
    assert event is not None
    assert event.donor_handle == "alice"


def test_invalid_signature_raises_receive_only_rail_error():
    payload = _payload()
    bad_sig = "sha256=" + ("0" * 64)
    with mock.patch.dict(
        "os.environ", {LIBERAPAY_WEBHOOK_SECRET_ENV: "topsecret-shh"}, clear=False
    ):
        receiver = LiberapayRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="HMAC SHA-256 signature mismatch"):
            receiver.ingest_webhook(payload, signature=bad_sig)


def test_signature_present_but_secret_missing_raises():
    payload = _payload()
    sig = "sha256=" + ("a" * 64)
    with mock.patch.dict("os.environ", {}, clear=True):
        receiver = LiberapayRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="not set"):
            receiver.ingest_webhook(payload, signature=sig)


def test_missing_signature_skips_verification_and_succeeds():
    receiver = LiberapayRailReceiver()
    event = receiver.ingest_webhook(_payload(), signature=None)
    assert event is not None


# ---------------------------------------------------------------------------
# IP allowlist enforcement
# ---------------------------------------------------------------------------


def test_ip_allowlist_required_with_source_ip_succeeds():
    payload = _payload(source_ip="203.0.113.7")
    with mock.patch.dict("os.environ", {LIBERAPAY_REQUIRE_IP_ALLOWLIST_ENV: "1"}, clear=False):
        receiver = LiberapayRailReceiver()
        event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None


def test_ip_allowlist_required_without_source_ip_raises():
    payload = _payload()  # no source_ip claim
    with mock.patch.dict("os.environ", {LIBERAPAY_REQUIRE_IP_ALLOWLIST_ENV: "1"}, clear=False):
        receiver = LiberapayRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 'source_ip'"):
            receiver.ingest_webhook(payload, signature=None)


def test_ip_allowlist_disabled_allows_missing_source_ip():
    payload = _payload()
    with mock.patch.dict("os.environ", {LIBERAPAY_REQUIRE_IP_ALLOWLIST_ENV: "0"}, clear=False):
        receiver = LiberapayRailReceiver()
        event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None


# ---------------------------------------------------------------------------
# Malformed payload rejection
# ---------------------------------------------------------------------------


def test_unknown_action_raises():
    receiver = LiberapayRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="unaccepted webhook event"):
        receiver.ingest_webhook(_payload(event="payin.refunded"), signature=None)


def test_payload_not_dict_raises():
    receiver = LiberapayRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="payload must be a dict"):
        receiver.ingest_webhook("not a dict", signature=None)  # type: ignore[arg-type]


def test_payload_missing_donor_raises():
    receiver = LiberapayRailReceiver()
    payload = _payload()
    del payload["donor"]
    with pytest.raises(ReceiveOnlyRailError, match="missing 'donor'"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_donor_username_raises():
    receiver = LiberapayRailReceiver()
    payload = _payload()
    del payload["donor"]["username"]
    with pytest.raises(ReceiveOnlyRailError, match="donor.username"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_amount_raises():
    receiver = LiberapayRailReceiver()
    payload = _payload()
    del payload["amount"]
    with pytest.raises(ReceiveOnlyRailError, match="missing 'amount'"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_non_eur_currency_raises():
    receiver = LiberapayRailReceiver()
    payload = _payload(currency="USD")
    with pytest.raises(ReceiveOnlyRailError, match="non-EUR currency"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_invalid_amount_string_raises():
    receiver = LiberapayRailReceiver()
    payload = _payload(amount="not-a-number")
    with pytest.raises(ReceiveOnlyRailError, match="invalid 'amount.amount'"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_negative_amount_raises():
    receiver = LiberapayRailReceiver()
    payload = _payload(amount="-1.00")
    with pytest.raises(ReceiveOnlyRailError, match="non-negative"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_timestamp_raises():
    receiver = LiberapayRailReceiver()
    payload = _payload()
    del payload["occurred_at"]
    with pytest.raises(ReceiveOnlyRailError, match="occurred_at"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_invalid_timestamp_raises():
    receiver = LiberapayRailReceiver()
    payload = _payload(occurred_at="not-a-real-iso-8601-timestamp")
    with pytest.raises(ReceiveOnlyRailError, match="invalid ISO 8601"):
        receiver.ingest_webhook(payload, signature=None)


def test_donor_handle_with_email_rejected():
    receiver = LiberapayRailReceiver()
    payload = _payload(donor_username="alice@example.com")
    with pytest.raises(ReceiveOnlyRailError, match="must be a Liberapay username"):
        receiver.ingest_webhook(payload, signature=None)


def test_event_must_be_string():
    receiver = LiberapayRailReceiver()
    payload = _payload()
    payload["event"] = 42
    with pytest.raises(ReceiveOnlyRailError, match="must be a string"):
        receiver.ingest_webhook(payload, signature=None)


def test_amount_amount_bool_rejected():
    """bool is a subclass of int; the receiver must explicitly reject it."""
    receiver = LiberapayRailReceiver()
    payload = _payload()
    payload["amount"]["amount"] = True
    with pytest.raises(ReceiveOnlyRailError, match="must be a number or numeric string"):
        receiver.ingest_webhook(payload, signature=None)


# ---------------------------------------------------------------------------
# Receive-only invariant: NO outbound network calls
# ---------------------------------------------------------------------------


def test_no_outbound_network_calls_during_ingest():
    """Mock urllib + httpx; assert the receiver never invokes them."""
    receiver = LiberapayRailReceiver()
    with (
        mock.patch("urllib.request.urlopen") as mock_urlopen,
        mock.patch("urllib.request.Request") as mock_request,
    ):
        for action in (
            "payin_created",
            "payin_succeeded",
            "tip_set",
            "tip_cancelled",
        ):
            event = receiver.ingest_webhook(_payload(event=action), signature=None)
            assert event is not None
        # Also exercise an error path — no network even when failing.
        with pytest.raises(ReceiveOnlyRailError):
            receiver.ingest_webhook(_payload(event="garbage"), signature=None)
    assert mock_urlopen.call_count == 0
    assert mock_request.call_count == 0


def test_receiver_does_not_import_or_use_httpx():
    """If httpx is importable, ensure none of its surfaces are invoked."""
    pytest.importorskip("httpx")
    import httpx  # type: ignore[import-not-found]

    receiver = LiberapayRailReceiver()
    with (
        mock.patch.object(httpx, "Client") as mock_client,
        mock.patch.object(httpx, "AsyncClient") as mock_async_client,
        mock.patch.object(httpx, "post") as mock_post,
        mock.patch.object(httpx, "get") as mock_get,
    ):
        event = receiver.ingest_webhook(_payload(), signature=None)
        assert event is not None
    assert mock_client.call_count == 0
    assert mock_async_client.call_count == 0
    assert mock_post.call_count == 0
    assert mock_get.call_count == 0


# ---------------------------------------------------------------------------
# Other invariants
# ---------------------------------------------------------------------------


def test_empty_payload_with_no_signature_returns_none():
    receiver = LiberapayRailReceiver()
    assert receiver.ingest_webhook({}, signature=None) is None


def test_sha256_in_event_matches_canonical_payload():
    receiver = LiberapayRailReceiver()
    payload = _payload()
    event = receiver.ingest_webhook(payload, signature=None)
    expected = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert event is not None
    assert event.raw_payload_sha256 == expected


def test_donation_event_is_frozen_no_pii_fields():
    """Pydantic ``extra='forbid'`` rejects PII keys at construction time."""
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        DonationEvent(
            donor_handle="alice",
            amount_eur_cents=500,
            event_kind=DonationEventKind.PAYIN_SUCCEEDED,
            occurred_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            raw_payload_sha256="a" * 64,
            email="leaked@example.com",  # type: ignore[call-arg]
        )


def test_amount_in_decimal_string_is_normalized_to_eur_cents():
    """Liberapay quotes amounts as decimal strings; receiver normalizes to int cents."""
    receiver = LiberapayRailReceiver()
    payload = _payload(amount="12.34")
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_eur_cents == 1234


def test_amount_in_numeric_form_is_normalized_to_eur_cents():
    """Numeric (int/float) ``amount.amount`` is also accepted."""
    receiver = LiberapayRailReceiver()
    payload = _payload(amount=7)
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_eur_cents == 700


def test_timestamp_field_is_accepted_when_occurred_at_absent():
    """The bridge may use 'timestamp' instead of 'occurred_at'."""
    receiver = LiberapayRailReceiver()
    payload = _payload(timestamp="2026-04-01T08:30:00Z")
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.occurred_at == datetime(2026, 4, 1, 8, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# jr-liberapay-rail-idempotency-pin regression pins
# ---------------------------------------------------------------------------


def test_idempotency_store_rejects_duplicate_delivery_id(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "lp-idem.db")
    receiver = LiberapayRailReceiver(idempotency_store=store)
    payload = _payload()

    first = receiver.ingest_webhook(payload, signature=None, delivery_id="lp-001")
    second = receiver.ingest_webhook(payload, signature=None, delivery_id="lp-001")

    assert first is not None
    assert second is None  # short-circuit


def test_idempotency_store_distinct_delivery_ids_both_processed(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "lp-idem.db")
    receiver = LiberapayRailReceiver(idempotency_store=store)
    payload = _payload()

    first = receiver.ingest_webhook(payload, signature=None, delivery_id="lp-a")
    second = receiver.ingest_webhook(payload, signature=None, delivery_id="lp-b")

    assert first is not None
    assert second is not None


def test_idempotency_store_provided_but_delivery_id_missing_raises(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "lp-idem.db")
    receiver = LiberapayRailReceiver(idempotency_store=store)
    payload = _payload()

    with pytest.raises(ReceiveOnlyRailError, match="delivery_id"):
        receiver.ingest_webhook(payload, signature=None)


def test_no_idempotency_store_means_no_idempotency_check():
    receiver = LiberapayRailReceiver()  # no store
    payload = _payload()
    a = receiver.ingest_webhook(payload, signature=None, delivery_id="ignored")
    b = receiver.ingest_webhook(payload, signature=None, delivery_id="ignored")
    assert a is not None
    assert b is not None


def test_idempotency_store_persists_across_receivers(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    db = tmp_path / "lp-idem.db"
    payload = _payload()

    a = LiberapayRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    first = a.ingest_webhook(payload, signature=None, delivery_id="lp-persist")
    b = LiberapayRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    second = b.ingest_webhook(payload, signature=None, delivery_id="lp-persist")

    assert first is not None
    assert second is None
