"""Tests for the Stripe Payment Link receive-only rail.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest

from shared.stripe_payment_link_receive_only_rail import (
    DEFAULT_TOLERANCE_SECONDS,
    STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV,
    PaymentEvent,
    PaymentEventKind,
    ReceiveOnlyRailError,
    StripePaymentLinkRailReceiver,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _payment_intent_payload(
    *,
    customer: str = "cus_AbCdEfGhIj01",
    amount: int = 2500,
    currency: str = "usd",
    created: int = 1_745_000_000,
) -> dict:
    return {
        "id": "evt_test_payment_intent",
        "type": "payment_intent.succeeded",
        "created": created,
        "data": {
            "object": {
                "id": "pi_test_01",
                "object": "payment_intent",
                "customer": customer,
                "amount": amount,
                "amount_received": amount,
                "currency": currency,
            }
        },
    }


def _checkout_session_payload(
    *,
    customer: str = "cus_AbCdEfGhIj02",
    amount_total: int = 5000,
    currency: str = "eur",
    created: int = 1_745_000_010,
) -> dict:
    return {
        "id": "evt_test_checkout",
        "type": "checkout.session.completed",
        "created": created,
        "data": {
            "object": {
                "id": "cs_test_01",
                "object": "checkout.session",
                "customer": customer,
                "amount_total": amount_total,
                "amount_subtotal": amount_total,
                "currency": currency,
            }
        },
    }


def _subscription_created_payload(
    *,
    customer: str = "cus_AbCdEfGhIj03",
    unit_amount: int = 1000,
    currency: str = "gbp",
    created: int = 1_745_000_020,
) -> dict:
    return {
        "id": "evt_test_sub_created",
        "type": "customer.subscription.created",
        "created": created,
        "data": {
            "object": {
                "id": "sub_test_01",
                "object": "subscription",
                "customer": customer,
                "items": {
                    "data": [
                        {
                            "id": "si_test_01",
                            "quantity": 1,
                            "price": {
                                "id": "price_test_01",
                                "unit_amount": unit_amount,
                                "currency": currency,
                            },
                        }
                    ]
                },
            }
        },
    }


def _subscription_deleted_payload(
    *,
    customer: str = "cus_AbCdEfGhIj04",
    currency: str = "jpy",
    created: int = 1_745_000_030,
) -> dict:
    """Subscription deletion may carry no pricing — just IDs + currency."""
    return {
        "id": "evt_test_sub_deleted",
        "type": "customer.subscription.deleted",
        "created": created,
        "data": {
            "object": {
                "id": "sub_test_02",
                "object": "subscription",
                "customer": customer,
                "currency": currency,
            }
        },
    }


def _stripe_sign(payload: dict, secret: str, *, timestamp: int | None = None) -> str:
    """Build a Stripe-Signature header for the canonical-JSON payload."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ts = timestamp if timestamp is not None else int(time.time())
    signed = f"{ts}.".encode() + body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


# ---------------------------------------------------------------------------
# Happy paths × 4 event kinds
# ---------------------------------------------------------------------------


def test_ingest_payment_intent_succeeded_unsigned_returns_normalized_event():
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    event = receiver.ingest_webhook(payload, signature=None)
    assert isinstance(event, PaymentEvent)
    assert event.event_kind is PaymentEventKind.PAYMENT_INTENT_SUCCEEDED
    assert event.customer_handle == "cus_AbCdEfGhIj01"
    assert event.amount_currency_cents == 2500
    assert event.currency == "USD"
    assert event.occurred_at == datetime(2025, 4, 18, 18, 13, 20, tzinfo=UTC)
    assert len(event.raw_payload_sha256) == 64


def test_ingest_checkout_session_completed_returns_normalized_event():
    receiver = StripePaymentLinkRailReceiver()
    event = receiver.ingest_webhook(_checkout_session_payload(), signature=None)
    assert event is not None
    assert event.event_kind is PaymentEventKind.CHECKOUT_SESSION_COMPLETED
    assert event.amount_currency_cents == 5000
    assert event.currency == "EUR"


def test_ingest_subscription_created_sums_item_prices():
    receiver = StripePaymentLinkRailReceiver()
    event = receiver.ingest_webhook(_subscription_created_payload(), signature=None)
    assert event is not None
    assert event.event_kind is PaymentEventKind.CUSTOMER_SUBSCRIPTION_CREATED
    assert event.amount_currency_cents == 1000
    assert event.currency == "GBP"


def test_ingest_subscription_deleted_no_pricing_defaults_to_zero():
    receiver = StripePaymentLinkRailReceiver()
    event = receiver.ingest_webhook(_subscription_deleted_payload(), signature=None)
    assert event is not None
    assert event.event_kind is PaymentEventKind.CUSTOMER_SUBSCRIPTION_DELETED
    assert event.amount_currency_cents == 0
    assert event.currency == "JPY"  # zero-decimal currency passthrough


# ---------------------------------------------------------------------------
# Stripe signature verification
# ---------------------------------------------------------------------------


def test_valid_signature_within_tolerance_succeeds():
    secret = "whsec_test_topsecret"
    payload = _payment_intent_payload()
    ts = int(time.time())
    sig = _stripe_sign(payload, secret, timestamp=ts)
    with mock.patch.dict(
        "os.environ", {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV: secret}, clear=False
    ):
        receiver = StripePaymentLinkRailReceiver()
        event = receiver.ingest_webhook(payload, signature=sig, now=float(ts))
    assert event is not None
    assert event.customer_handle == "cus_AbCdEfGhIj01"


def test_invalid_signature_raises_receive_only_rail_error():
    payload = _payment_intent_payload()
    ts = int(time.time())
    bad_sig = f"t={ts},v1={'0' * 64}"
    with mock.patch.dict(
        "os.environ",
        {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV: "whsec_test_topsecret"},
        clear=False,
    ):
        receiver = StripePaymentLinkRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="signature mismatch"):
            receiver.ingest_webhook(payload, signature=bad_sig, now=float(ts))


def test_signature_present_but_secret_missing_raises():
    payload = _payment_intent_payload()
    ts = int(time.time())
    sig = f"t={ts},v1={'a' * 64}"
    with mock.patch.dict("os.environ", {}, clear=True):
        receiver = StripePaymentLinkRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="not set"):
            receiver.ingest_webhook(payload, signature=sig, now=float(ts))


def test_missing_signature_skips_verification_and_succeeds():
    receiver = StripePaymentLinkRailReceiver()
    event = receiver.ingest_webhook(_payment_intent_payload(), signature=None)
    assert event is not None


def test_expired_timestamp_raises_replay_protection():
    secret = "whsec_test_topsecret"
    payload = _payment_intent_payload()
    # Sign with a timestamp 600s in the past — beyond default 300s tolerance.
    now = int(time.time())
    expired_ts = now - 600
    sig = _stripe_sign(payload, secret, timestamp=expired_ts)
    with mock.patch.dict(
        "os.environ", {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV: secret}, clear=False
    ):
        receiver = StripePaymentLinkRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="replay rejected"):
            receiver.ingest_webhook(payload, signature=sig, now=float(now))


def test_signature_within_custom_wider_tolerance_succeeds():
    """Custom tolerance lets a 600s-old delivery through."""
    secret = "whsec_test_topsecret"
    payload = _payment_intent_payload()
    now = int(time.time())
    older_ts = now - 600
    sig = _stripe_sign(payload, secret, timestamp=older_ts)
    with mock.patch.dict(
        "os.environ", {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV: secret}, clear=False
    ):
        receiver = StripePaymentLinkRailReceiver(tolerance_seconds=900)
        event = receiver.ingest_webhook(payload, signature=sig, now=float(now))
    assert event is not None


def test_signature_header_missing_timestamp_raises():
    secret = "whsec_test_topsecret"
    payload = _payment_intent_payload()
    bad_header = "v1=" + ("a" * 64)
    with mock.patch.dict(
        "os.environ", {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV: secret}, clear=False
    ):
        receiver = StripePaymentLinkRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing 't' timestamp"):
            receiver.ingest_webhook(payload, signature=bad_header)


def test_signature_header_missing_v1_raises():
    secret = "whsec_test_topsecret"
    payload = _payment_intent_payload()
    bad_header = f"t={int(time.time())},v0=irrelevant"
    with mock.patch.dict(
        "os.environ", {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV: secret}, clear=False
    ):
        receiver = StripePaymentLinkRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="missing any 'v1'"):
            receiver.ingest_webhook(payload, signature=bad_header, now=float(time.time()))


def test_signature_header_with_multiple_v1_signatures_accepts_any_match():
    """During Stripe secret rotation the header may carry two v1 sigs."""
    secret_b = "whsec_test_new"
    payload = _payment_intent_payload()
    ts = int(time.time())
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signed = f"{ts}.".encode() + body
    # Two v1 signatures — first is bogus, second computed with the active
    # secret. Multi-v1 verifier must accept on any match (Stripe rotation).
    digest_new = hmac.new(secret_b.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    multi_sig = f"t={ts},v1={'0' * 64},v1={digest_new}"
    with mock.patch.dict(
        "os.environ", {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV: secret_b}, clear=False
    ):
        receiver = StripePaymentLinkRailReceiver()
        event = receiver.ingest_webhook(payload, signature=multi_sig, now=float(ts))
    assert event is not None


# ---------------------------------------------------------------------------
# Multi-currency handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "currency,expected_upper",
    [("usd", "USD"), ("eur", "EUR"), ("gbp", "GBP")],
)
def test_multi_currency_normalized_to_uppercase_iso_4217(currency: str, expected_upper: str):
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload(currency=currency)
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.currency == expected_upper


def test_dotted_event_type_alias_accepted():
    """Stripe emits dotted event type strings; both forms must work."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    # Dotted form is what Stripe ships in production.
    assert payload["type"] == "payment_intent.succeeded"
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.event_kind is PaymentEventKind.PAYMENT_INTENT_SUCCEEDED


def test_underscored_event_type_canonical_accepted():
    """Underscored canonical form is also accepted (parity with siblings)."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    payload["type"] = "payment_intent_succeeded"
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.event_kind is PaymentEventKind.PAYMENT_INTENT_SUCCEEDED


# ---------------------------------------------------------------------------
# Malformed payload rejection
# ---------------------------------------------------------------------------


def test_unknown_event_type_raises():
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    payload["type"] = "charge.succeeded"
    with pytest.raises(ReceiveOnlyRailError, match="unaccepted webhook event type"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_not_dict_raises():
    receiver = StripePaymentLinkRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="payload must be a dict"):
        receiver.ingest_webhook("not a dict", signature=None)  # type: ignore[arg-type]


def test_payload_missing_data_raises():
    receiver = StripePaymentLinkRailReceiver()
    payload = {"type": "payment_intent.succeeded", "created": 1_745_000_000}
    with pytest.raises(ReceiveOnlyRailError, match="missing 'data'"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_data_object_raises():
    receiver = StripePaymentLinkRailReceiver()
    payload = {
        "type": "payment_intent.succeeded",
        "created": 1_745_000_000,
        "data": {"not_object": True},
    }
    with pytest.raises(ReceiveOnlyRailError, match="missing 'data.object'"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_customer_and_id_raises():
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    del payload["data"]["object"]["customer"]
    del payload["data"]["object"]["id"]
    with pytest.raises(ReceiveOnlyRailError, match="customer.*or.*id"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_currency_raises():
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    del payload["data"]["object"]["currency"]
    with pytest.raises(ReceiveOnlyRailError, match="missing 'currency'"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_created_timestamp_raises():
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    del payload["created"]
    with pytest.raises(ReceiveOnlyRailError, match="missing 'created'"):
        receiver.ingest_webhook(payload, signature=None)


def test_event_type_not_string_raises():
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    payload["type"] = 42
    with pytest.raises(ReceiveOnlyRailError, match="must be a string"):
        receiver.ingest_webhook(payload, signature=None)


def test_amount_not_integer_raises():
    """Non-numeric strings still fail closed (Dahlia accepts decimal strings only)."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    payload["data"]["object"]["amount"] = "twenty-five-bucks"
    payload["data"]["object"]["amount_received"] = "twenty-five-bucks"
    with pytest.raises(ReceiveOnlyRailError, match="not a valid integer"):
        receiver.ingest_webhook(payload, signature=None)


def test_customer_handle_with_email_rejected():
    """Even if Stripe somehow ships an email in the customer field, reject it."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload(customer="leaked@example.com")
    with pytest.raises(ReceiveOnlyRailError, match="must be a Stripe object ID"):
        receiver.ingest_webhook(payload, signature=None)


# ---------------------------------------------------------------------------
# Receive-only invariant: NO outbound network calls
# ---------------------------------------------------------------------------


def test_no_outbound_network_calls_during_ingest():
    """Mock urllib + assert the receiver never invokes it across all 4 kinds."""
    receiver = StripePaymentLinkRailReceiver()
    with (
        mock.patch("urllib.request.urlopen") as mock_urlopen,
        mock.patch("urllib.request.Request") as mock_request,
    ):
        for builder in (
            _payment_intent_payload,
            _checkout_session_payload,
            _subscription_created_payload,
            _subscription_deleted_payload,
        ):
            event = receiver.ingest_webhook(builder(), signature=None)
            assert event is not None
        # Also exercise an error path — no network even when failing.
        with pytest.raises(ReceiveOnlyRailError):
            bad = _payment_intent_payload()
            bad["type"] = "garbage.event"
            receiver.ingest_webhook(bad, signature=None)
    assert mock_urlopen.call_count == 0
    assert mock_request.call_count == 0


def test_receiver_does_not_import_or_use_httpx():
    """If httpx is in the env, ensure none of its surfaces are invoked."""
    pytest.importorskip("httpx")
    import httpx  # type: ignore[import-not-found]

    receiver = StripePaymentLinkRailReceiver()
    with (
        mock.patch.object(httpx, "Client") as mock_client,
        mock.patch.object(httpx, "AsyncClient") as mock_async_client,
        mock.patch.object(httpx, "post") as mock_post,
        mock.patch.object(httpx, "get") as mock_get,
    ):
        event = receiver.ingest_webhook(_payment_intent_payload(), signature=None)
        assert event is not None
    assert mock_client.call_count == 0
    assert mock_async_client.call_count == 0
    assert mock_post.call_count == 0
    assert mock_get.call_count == 0


def test_receiver_does_not_import_stripe_sdk():
    """The production module must NOT import the stripe SDK."""
    import shared.stripe_payment_link_receive_only_rail as rail_mod

    src = rail_mod.__file__
    assert src is not None
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    # Module-level imports (anchored on import line starts).
    assert "\nimport stripe" not in text
    assert "\nfrom stripe " not in text


# ---------------------------------------------------------------------------
# Other invariants
# ---------------------------------------------------------------------------


def test_empty_payload_with_no_signature_returns_none():
    receiver = StripePaymentLinkRailReceiver()
    assert receiver.ingest_webhook({}, signature=None) is None


def test_sha256_in_event_matches_canonical_payload():
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    event = receiver.ingest_webhook(payload, signature=None)
    expected = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert event is not None
    assert event.raw_payload_sha256 == expected


def test_payment_event_is_frozen_no_pii_fields():
    """Pydantic ``extra='forbid'`` rejects PII keys at construction time."""
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        PaymentEvent(
            customer_handle="cus_test01",
            amount_currency_cents=2500,
            currency="USD",
            event_kind=PaymentEventKind.PAYMENT_INTENT_SUCCEEDED,
            occurred_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            raw_payload_sha256="a" * 64,
            email="leaked@example.com",  # type: ignore[call-arg]
        )


def test_default_tolerance_seconds_is_300():
    """Stripe documents 300s as the recommended replay window."""
    assert DEFAULT_TOLERANCE_SECONDS == 300


def test_negative_amount_normalized_to_absolute():
    """Refunds/credits ship as negative amounts; rail expresses gross movement."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload(amount=-2500)
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_currency_cents == 2500


def test_session_id_used_as_handle_when_no_customer():
    """Guest checkout: no customer object — fall back to data.object.id."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _checkout_session_payload()
    del payload["data"]["object"]["customer"]
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.customer_handle == "cs_test_01"


# ---------------------------------------------------------------------------
# Idempotency (jr-stripe-payment-link-replay-idempotency-pin pin #1)
# ---------------------------------------------------------------------------


def test_idempotency_store_rejects_duplicate_event_id(tmp_path):
    """Replay of the same evt_... id is short-circuited to a no-op."""
    from shared.stripe_payment_link_receive_only_rail import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    receiver = StripePaymentLinkRailReceiver(idempotency_store=store)

    payload = _payment_intent_payload()
    first = receiver.ingest_webhook(payload, signature=None)
    assert first is not None
    assert first.amount_currency_cents == 2500

    # Same event id arrives a second time.
    second = receiver.ingest_webhook(payload, signature=None)
    assert second is None  # short-circuit; caller returns 200 OK without re-processing


def test_idempotency_store_distinct_event_ids_both_processed(tmp_path):
    """Two distinct evt_... ids both insert + return events."""
    from shared.stripe_payment_link_receive_only_rail import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    receiver = StripePaymentLinkRailReceiver(idempotency_store=store)

    a = _payment_intent_payload()
    b = _checkout_session_payload()
    assert a["id"] != b["id"]

    assert receiver.ingest_webhook(a, signature=None) is not None
    assert receiver.ingest_webhook(b, signature=None) is not None


def test_idempotency_store_table_persists_on_disk(tmp_path):
    """A second receiver pointed at the same db path sees prior inserts."""
    from shared.stripe_payment_link_receive_only_rail import IdempotencyStore

    db_path = tmp_path / "idem.db"
    receiver_a = StripePaymentLinkRailReceiver(idempotency_store=IdempotencyStore(db_path=db_path))
    payload = _payment_intent_payload()
    assert receiver_a.ingest_webhook(payload, signature=None) is not None

    # Fresh receiver, fresh store, same db path → duplicate is short-circuited.
    receiver_b = StripePaymentLinkRailReceiver(idempotency_store=IdempotencyStore(db_path=db_path))
    assert receiver_b.ingest_webhook(payload, signature=None) is None


def test_idempotency_store_missing_event_id_raises(tmp_path):
    """Idempotency-on payload without top-level 'id' raises (not silent-fail)."""
    from shared.stripe_payment_link_receive_only_rail import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    receiver = StripePaymentLinkRailReceiver(idempotency_store=store)

    payload = _payment_intent_payload()
    del payload["id"]
    with pytest.raises(ReceiveOnlyRailError, match="missing top-level 'id'"):
        receiver.ingest_webhook(payload, signature=None)


def test_idempotency_store_record_or_skip_returns_correct_booleans(tmp_path):
    from shared.stripe_payment_link_receive_only_rail import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    assert store.record_or_skip("evt_test_first") is True
    assert store.record_or_skip("evt_test_first") is False
    assert store.record_or_skip("evt_test_second") is True
    assert store.has_seen("evt_test_first") is True
    assert store.has_seen("evt_test_third") is False


def test_idempotency_store_empty_event_id_raises(tmp_path):
    from shared.stripe_payment_link_receive_only_rail import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    with pytest.raises(ReceiveOnlyRailError, match="event_id must be a non-empty string"):
        store.record_or_skip("")


def test_no_idempotency_store_means_no_idempotency_check(tmp_path):
    """When constructed without a store, duplicates are processed twice (legacy shape)."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    first = receiver.ingest_webhook(payload, signature=None)
    second = receiver.ingest_webhook(payload, signature=None)
    assert first is not None
    assert second is not None  # no idempotency store → no short-circuit


# ---------------------------------------------------------------------------
# Thin-event rejection (jr-stripe-payment-link-replay-idempotency-pin pin #2)
# ---------------------------------------------------------------------------


def test_thin_event_rejected_with_explicit_error():
    """data.object with only id+object (Stripe thin payload) fails closed."""
    receiver = StripePaymentLinkRailReceiver()
    payload = {
        "id": "evt_test_thin",
        "type": "payment_intent.succeeded",
        "created": 1_745_000_000,
        "data": {"object": {"id": "pi_test_thin", "object": "payment_intent"}},
    }
    with pytest.raises(ReceiveOnlyRailError, match="thin-payload event rejected"):
        receiver.ingest_webhook(payload, signature=None)


def test_full_payload_with_id_and_object_plus_data_is_not_thin():
    """A standard payload with id+object+customer+amount+currency is processed normally."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    assert "customer" in payload["data"]["object"]
    assert "currency" in payload["data"]["object"]
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.customer_handle == "cus_AbCdEfGhIj01"


def test_thin_event_with_only_id_key_rejected():
    """Even minimal {id: ...} alone (Stripe shapes) fails closed."""
    receiver = StripePaymentLinkRailReceiver()
    payload = {
        "id": "evt_test_thin_2",
        "type": "checkout.session.completed",
        "created": 1_745_000_010,
        "data": {"object": {"id": "cs_test_thin"}},
    }
    with pytest.raises(ReceiveOnlyRailError, match="thin-payload event rejected"):
        receiver.ingest_webhook(payload, signature=None)


# ---------------------------------------------------------------------------
# Startup secret validation (jr-stripe-payment-link-replay-idempotency-pin pin #3)
# ---------------------------------------------------------------------------


def test_validate_secret_or_raise_with_unset_env_raises():
    from shared.stripe_payment_link_receive_only_rail import validate_secret_or_raise

    with mock.patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ReceiveOnlyRailError, match="must be set to a non-empty"):
            validate_secret_or_raise()


def test_validate_secret_or_raise_with_empty_env_raises():
    from shared.stripe_payment_link_receive_only_rail import validate_secret_or_raise

    with mock.patch.dict("os.environ", {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV: ""}, clear=False):
        with pytest.raises(ReceiveOnlyRailError, match="must be set to a non-empty"):
            validate_secret_or_raise()


def test_validate_secret_or_raise_with_whitespace_only_raises():
    from shared.stripe_payment_link_receive_only_rail import validate_secret_or_raise

    with mock.patch.dict(
        "os.environ", {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV: "   \t\n  "}, clear=False
    ):
        with pytest.raises(ReceiveOnlyRailError, match="must be set to a non-empty"):
            validate_secret_or_raise()


def test_validate_secret_or_raise_with_valid_secret_does_not_raise():
    from shared.stripe_payment_link_receive_only_rail import validate_secret_or_raise

    with mock.patch.dict(
        "os.environ",
        {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV: "whsec_real_secret_value"},
        clear=False,
    ):
        validate_secret_or_raise()  # should not raise


def test_validate_secret_or_raise_supports_custom_env_var_name():
    from shared.stripe_payment_link_receive_only_rail import validate_secret_or_raise

    with mock.patch.dict("os.environ", {"CUSTOM_STRIPE_SECRET": "whsec_x"}, clear=False):
        validate_secret_or_raise(env_var="CUSTOM_STRIPE_SECRET")


# ---------------------------------------------------------------------------
# Default idempotency DB path respects HAPAX_HOME
# ---------------------------------------------------------------------------


def test_default_idempotency_db_path_uses_hapax_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    from shared.stripe_payment_link_receive_only_rail import (
        IdempotencyStore,
        _default_idempotency_db_path,
    )

    p = _default_idempotency_db_path()
    assert p == tmp_path / "stripe-payment-link" / "idempotency.db"

    store = IdempotencyStore()
    assert store.db_path == p
    assert p.parent.is_dir()


def test_default_idempotency_db_path_falls_back_to_home(monkeypatch):
    from shared.stripe_payment_link_receive_only_rail import _default_idempotency_db_path

    monkeypatch.delenv("HAPAX_HOME", raising=False)
    p = _default_idempotency_db_path()
    assert p == Path.home() / "hapax-state" / "stripe-payment-link" / "idempotency.db"


# ---------------------------------------------------------------------------
# Stripe API version 2026-03-25.dahlia decimal-string forward-compat
# (cc-task: stripe-dahlia-decimal-readiness)
# ---------------------------------------------------------------------------


def test_amount_integer_minor_units_still_accepted():
    """Pre-Dahlia: amount as int (current production shape) still works."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload(amount=2500)
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_currency_cents == 2500


def test_amount_integer_string_dahlia_minor_units_accepted():
    """Dahlia: amount as integer string ("2500") accepted as minor units."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    payload["data"]["object"]["amount"] = "2500"
    payload["data"]["object"]["amount_received"] = "2500"
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_currency_cents == 2500


def test_amount_decimal_string_dahlia_major_units_accepted():
    """Dahlia: amount as decimal string ("25.00") → 2500 cents."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    payload["data"]["object"]["amount"] = "25.00"
    payload["data"]["object"]["amount_received"] = "25.00"
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_currency_cents == 2500


def test_amount_decimal_string_with_one_cent_accepted():
    """Dahlia: "0.01" → 1 cent, no float drift."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    payload["data"]["object"]["amount"] = "0.01"
    payload["data"]["object"]["amount_received"] = "0.01"
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_currency_cents == 1


def test_amount_decimal_string_fractional_cents_rejected():
    """Dahlia: "1.234" doesn't multiply to integer cents — fail closed."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    payload["data"]["object"]["amount"] = "1.234"
    payload["data"]["object"]["amount_received"] = "1.234"
    with pytest.raises(ReceiveOnlyRailError, match="does not multiply to integer cents"):
        receiver.ingest_webhook(payload, signature=None)


def test_amount_empty_string_rejected():
    """Dahlia: empty amount string fails closed."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    payload["data"]["object"]["amount"] = ""
    payload["data"]["object"]["amount_received"] = ""
    with pytest.raises(ReceiveOnlyRailError, match="empty"):
        receiver.ingest_webhook(payload, signature=None)


def test_amount_bool_rejected():
    """``True``/``False`` (bool subclasses int) explicitly fails closed."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _payment_intent_payload()
    payload["data"]["object"]["amount"] = True
    payload["data"]["object"]["amount_received"] = True
    with pytest.raises(ReceiveOnlyRailError, match="amount must be"):
        receiver.ingest_webhook(payload, signature=None)


def test_subscription_unit_amount_decimal_string_accepted():
    """Dahlia: subscription line items can ship unit_amount as decimal string."""
    receiver = StripePaymentLinkRailReceiver()
    payload = _subscription_created_payload()
    # Replace unit_amount int with Dahlia decimal-string form ($10.00).
    payload["data"]["object"]["items"]["data"][0]["price"]["unit_amount"] = "10.00"
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_currency_cents == 1000  # $10.00 → 1000 cents
