"""Tests for the Open Collective receive-only rail.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from shared.open_collective_receive_only_rail import (
    OPEN_COLLECTIVE_WEBHOOK_SECRET_ENV,
    CollectiveEvent,
    CollectiveEventKind,
    OpenCollectiveRailReceiver,
    ReceiveOnlyRailError,
)


def _txn_payload(
    *,
    activity: str = "collective_transaction_created",
    slug: str = "alice",
    value: float | int | str = 5.0,
    currency: str = "USD",
    created_at: str = "2026-05-02T12:00:00Z",
) -> dict:
    """Build a transaction-shaped delivery (modern GraphQL value form)."""
    return {
        "type": activity,
        "createdAt": created_at,
        "data": {
            "fromCollective": {"slug": slug},
            "transaction": {
                "amount": {"value": value, "currency": currency},
            },
        },
    }


def _order_payload(
    *,
    activity: str = "order_processed",
    slug: str = "bob",
    value: float | int = 12.50,
    currency: str = "EUR",
    created_at: str = "2026-05-02T12:00:00Z",
) -> dict:
    return {
        "type": activity,
        "createdAt": created_at,
        "data": {
            "order": {
                "fromAccount": {"slug": slug},
                "totalAmount": {"value": value, "currency": currency},
            },
        },
    }


def _member_payload(
    *,
    activity: str = "member_created",
    slug: str = "carol",
    value: float | int = 25,
    currency: str = "GBP",
    created_at: str = "2026-05-02T12:00:00Z",
) -> dict:
    return {
        "type": activity,
        "createdAt": created_at,
        "data": {
            "member": {
                "memberAccount": {"slug": slug},
                "tier": {
                    "amount": {"value": value, "currency": currency},
                },
            },
        },
    }


def _expense_payload(
    *,
    activity: str = "expense_paid",
    slug: str = "the-collective",
    value: float | int = 100,
    currency: str = "CAD",
    created_at: str = "2026-05-02T12:00:00Z",
) -> dict:
    return {
        "type": activity,
        "createdAt": created_at,
        "data": {
            "collective": {"slug": slug},
            "expense": {
                "amount": {"value": value, "currency": currency},
            },
        },
    }


def _sign(payload: dict, secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# Happy paths for all 4 accepted event kinds
# ---------------------------------------------------------------------------


def test_ingest_collective_transaction_created_returns_normalized_event():
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(_txn_payload(), signature=None)
    assert isinstance(event, CollectiveEvent)
    assert event.event_kind is CollectiveEventKind.COLLECTIVE_TRANSACTION_CREATED
    assert event.member_handle == "alice"
    assert event.amount_currency_cents == 500
    assert event.currency == "USD"
    assert event.occurred_at == datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    assert len(event.raw_payload_sha256) == 64


def test_ingest_order_processed_returns_normalized_event():
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(_order_payload(), signature=None)
    assert event is not None
    assert event.event_kind is CollectiveEventKind.ORDER_PROCESSED
    assert event.member_handle == "bob"
    assert event.amount_currency_cents == 1250
    assert event.currency == "EUR"


def test_ingest_member_created_returns_normalized_event():
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(_member_payload(), signature=None)
    assert event is not None
    assert event.event_kind is CollectiveEventKind.MEMBER_CREATED
    assert event.member_handle == "carol"
    assert event.amount_currency_cents == 2500
    assert event.currency == "GBP"


def test_ingest_expense_paid_returns_normalized_event():
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(_expense_payload(), signature=None)
    assert event is not None
    assert event.event_kind is CollectiveEventKind.EXPENSE_PAID
    assert event.member_handle == "the-collective"
    assert event.amount_currency_cents == 10000
    assert event.currency == "CAD"


def test_ingest_dotted_activity_alias_normalizes_to_canonical_kind():
    """Open Collective emits dotted activity types in the webhook envelope."""
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(
        _txn_payload(activity="collective.transaction.created"), signature=None
    )
    assert event is not None
    assert event.event_kind is CollectiveEventKind.COLLECTIVE_TRANSACTION_CREATED


# ---------------------------------------------------------------------------
# Multi-currency handling — the new shape vs prior rails
# ---------------------------------------------------------------------------


def test_currency_is_preserved_per_delivery_usd():
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(_txn_payload(value=10, currency="USD"), signature=None)
    assert event is not None
    assert event.currency == "USD"
    assert event.amount_currency_cents == 1000


def test_currency_is_preserved_per_delivery_eur():
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(_txn_payload(value="3.50", currency="EUR"), signature=None)
    assert event is not None
    assert event.currency == "EUR"
    assert event.amount_currency_cents == 350


def test_currency_is_preserved_per_delivery_gbp():
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(_txn_payload(value=2.99, currency="GBP"), signature=None)
    assert event is not None
    assert event.currency == "GBP"
    assert event.amount_currency_cents == 299


def test_currency_lowercase_is_uppercased_for_iso_4217_compliance():
    """Open Collective sometimes emits lowercase currency; receiver uppercases."""
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(_txn_payload(currency="usd"), signature=None)
    assert event is not None
    assert event.currency == "USD"


def test_invalid_currency_code_too_long_raises():
    """Pydantic ``max_length=3`` rejects oversized currency strings."""
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    payload["data"]["transaction"]["amount"]["currency"] = "DOLLARS"
    with pytest.raises(ReceiveOnlyRailError, match="normalized event failed validation"):
        receiver.ingest_webhook(payload, signature=None)


def test_invalid_currency_code_non_letters_raises():
    """ISO 4217 validator rejects 3-char non-letter codes (e.g. digits)."""
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    payload["data"]["transaction"]["amount"]["currency"] = "123"
    with pytest.raises(ReceiveOnlyRailError, match="3-letter uppercase ISO 4217"):
        receiver.ingest_webhook(payload, signature=None)


def test_value_in_cents_graphql_shape_is_accepted():
    """GraphQL `valueInCents` shape — already integer minor-units; preserved."""
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    payload["data"]["transaction"]["amount"] = {"valueInCents": 750, "currency": "AUD"}
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_currency_cents == 750
    assert event.currency == "AUD"


def test_legacy_rest_shape_integer_cents_is_accepted():
    """Legacy REST shape: integer cents at amount + sibling currency."""
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    payload["data"]["transaction"]["amount"] = 1500
    payload["data"]["transaction"]["currency"] = "JPY"
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_currency_cents == 1500
    assert event.currency == "JPY"


def test_negative_amount_debit_is_normalized_to_absolute_value():
    """Open Collective debits emit negative amounts; rail preserves gross flow."""
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(_txn_payload(value=-7.0), signature=None)
    assert event is not None
    assert event.amount_currency_cents == 700


# ---------------------------------------------------------------------------
# HMAC signature verification
# ---------------------------------------------------------------------------


def test_valid_signature_succeeds():
    secret = "topsecret-shh"
    payload = _txn_payload()
    sig = _sign(payload, secret)
    with mock.patch.dict("os.environ", {OPEN_COLLECTIVE_WEBHOOK_SECRET_ENV: secret}, clear=False):
        receiver = OpenCollectiveRailReceiver()
        event = receiver.ingest_webhook(payload, signature=sig)
    assert event is not None
    assert event.member_handle == "alice"


def test_valid_signature_bare_hex_no_prefix_succeeds():
    """Open Collective emits bare hex; rail accepts both bare and sha256= prefix."""
    secret = "topsecret-shh"
    payload = _txn_payload()
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    bare_digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    with mock.patch.dict("os.environ", {OPEN_COLLECTIVE_WEBHOOK_SECRET_ENV: secret}, clear=False):
        receiver = OpenCollectiveRailReceiver()
        event = receiver.ingest_webhook(payload, signature=bare_digest)
    assert event is not None


def test_invalid_signature_raises_receive_only_rail_error():
    payload = _txn_payload()
    bad_sig = "sha256=" + ("0" * 64)
    with mock.patch.dict(
        "os.environ", {OPEN_COLLECTIVE_WEBHOOK_SECRET_ENV: "topsecret-shh"}, clear=False
    ):
        receiver = OpenCollectiveRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="HMAC SHA-256 signature mismatch"):
            receiver.ingest_webhook(payload, signature=bad_sig)


def test_signature_present_but_secret_missing_raises():
    payload = _txn_payload()
    sig = "sha256=" + ("a" * 64)
    with mock.patch.dict("os.environ", {}, clear=True):
        receiver = OpenCollectiveRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="not set"):
            receiver.ingest_webhook(payload, signature=sig)


def test_missing_signature_skips_verification_and_succeeds():
    receiver = OpenCollectiveRailReceiver()
    event = receiver.ingest_webhook(_txn_payload(), signature=None)
    assert event is not None


# ---------------------------------------------------------------------------
# Malformed payload rejection
# ---------------------------------------------------------------------------


def test_unknown_activity_raises():
    receiver = OpenCollectiveRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="unaccepted webhook activity"):
        receiver.ingest_webhook(_txn_payload(activity="user.created"), signature=None)


def test_payload_not_dict_raises():
    receiver = OpenCollectiveRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="payload must be a dict"):
        receiver.ingest_webhook("not a dict", signature=None)  # type: ignore[arg-type]


def test_payload_missing_data_raises():
    receiver = OpenCollectiveRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="missing 'data'"):
        receiver.ingest_webhook(
            {"type": "collective_transaction_created", "createdAt": "2026-05-02T12:00:00Z"},
            signature=None,
        )


def test_payload_missing_slug_raises():
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    del payload["data"]["fromCollective"]
    with pytest.raises(ReceiveOnlyRailError, match="missing a slug"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_amount_raises():
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    del payload["data"]["transaction"]
    with pytest.raises(ReceiveOnlyRailError, match="missing amount"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_timestamp_raises():
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    del payload["createdAt"]
    with pytest.raises(ReceiveOnlyRailError, match="createdAt"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_invalid_timestamp_raises():
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload(created_at="not-a-real-iso-8601-timestamp")
    with pytest.raises(ReceiveOnlyRailError, match="invalid ISO 8601"):
        receiver.ingest_webhook(payload, signature=None)


def test_member_handle_with_email_rejected():
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload(slug="alice@example.com")
    with pytest.raises(ReceiveOnlyRailError, match="must be an Open Collective slug"):
        receiver.ingest_webhook(payload, signature=None)


def test_activity_must_be_string():
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    payload["type"] = 42
    with pytest.raises(ReceiveOnlyRailError, match="must be a string"):
        receiver.ingest_webhook(payload, signature=None)


def test_amount_value_bool_rejected():
    """bool is a subclass of int; the receiver must explicitly reject it."""
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    payload["data"]["transaction"]["amount"]["value"] = True
    with pytest.raises(ReceiveOnlyRailError, match="must be a number or numeric string"):
        receiver.ingest_webhook(payload, signature=None)


def test_amount_invalid_string_raises():
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    payload["data"]["transaction"]["amount"]["value"] = "not-a-number"
    with pytest.raises(ReceiveOnlyRailError, match="invalid amount value"):
        receiver.ingest_webhook(payload, signature=None)


def test_missing_currency_raises():
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    del payload["data"]["transaction"]["amount"]["currency"]
    with pytest.raises(ReceiveOnlyRailError, match="missing currency"):
        receiver.ingest_webhook(payload, signature=None)


# ---------------------------------------------------------------------------
# Receive-only invariant: NO outbound network calls
# ---------------------------------------------------------------------------


def test_no_outbound_network_calls_during_ingest():
    """Mock urllib + httpx; assert the receiver never invokes them."""
    receiver = OpenCollectiveRailReceiver()
    with (
        mock.patch("urllib.request.urlopen") as mock_urlopen,
        mock.patch("urllib.request.Request") as mock_request,
    ):
        for builder in (
            _txn_payload,
            _order_payload,
            _member_payload,
            _expense_payload,
        ):
            event = receiver.ingest_webhook(builder(), signature=None)
            assert event is not None
        # Also exercise an error path — no network even when failing.
        with pytest.raises(ReceiveOnlyRailError):
            receiver.ingest_webhook(_txn_payload(activity="garbage"), signature=None)
    assert mock_urlopen.call_count == 0
    assert mock_request.call_count == 0


def test_receiver_does_not_import_or_use_httpx():
    """If httpx is importable, ensure none of its surfaces are invoked."""
    pytest.importorskip("httpx")
    import httpx  # type: ignore[import-not-found]

    receiver = OpenCollectiveRailReceiver()
    with (
        mock.patch.object(httpx, "Client") as mock_client,
        mock.patch.object(httpx, "AsyncClient") as mock_async_client,
        mock.patch.object(httpx, "post") as mock_post,
        mock.patch.object(httpx, "get") as mock_get,
    ):
        event = receiver.ingest_webhook(_txn_payload(), signature=None)
        assert event is not None
    assert mock_client.call_count == 0
    assert mock_async_client.call_count == 0
    assert mock_post.call_count == 0
    assert mock_get.call_count == 0


# ---------------------------------------------------------------------------
# Other invariants
# ---------------------------------------------------------------------------


def test_empty_payload_with_no_signature_returns_none():
    receiver = OpenCollectiveRailReceiver()
    assert receiver.ingest_webhook({}, signature=None) is None


def test_sha256_in_event_matches_canonical_payload():
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    event = receiver.ingest_webhook(payload, signature=None)
    expected = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert event is not None
    assert event.raw_payload_sha256 == expected


def test_collective_event_is_frozen_no_pii_fields():
    """Pydantic ``extra='forbid'`` rejects PII keys at construction time."""
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        CollectiveEvent(
            member_handle="alice",
            amount_currency_cents=500,
            currency="USD",
            event_kind=CollectiveEventKind.COLLECTIVE_TRANSACTION_CREATED,
            occurred_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            raw_payload_sha256="a" * 64,
            email="leaked@example.com",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# jr-open-collective-rail-idempotency-pin regression pins
# ---------------------------------------------------------------------------


def test_idempotency_store_rejects_duplicate_delivery_id(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "oc-idem.db")
    receiver = OpenCollectiveRailReceiver(idempotency_store=store)
    payload = _txn_payload()

    first = receiver.ingest_webhook(payload, signature=None, delivery_id="oc-001")
    second = receiver.ingest_webhook(payload, signature=None, delivery_id="oc-001")

    assert first is not None
    assert second is None


def test_idempotency_store_distinct_delivery_ids_both_processed(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "oc-idem.db")
    receiver = OpenCollectiveRailReceiver(idempotency_store=store)
    payload = _txn_payload()

    first = receiver.ingest_webhook(payload, signature=None, delivery_id="oc-a")
    second = receiver.ingest_webhook(payload, signature=None, delivery_id="oc-b")

    assert first is not None
    assert second is not None


def test_idempotency_store_provided_but_delivery_id_missing_raises(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "oc-idem.db")
    receiver = OpenCollectiveRailReceiver(idempotency_store=store)
    payload = _txn_payload()

    with pytest.raises(ReceiveOnlyRailError, match="delivery_id"):
        receiver.ingest_webhook(payload, signature=None)


def test_no_idempotency_store_means_no_idempotency_check():
    receiver = OpenCollectiveRailReceiver()
    payload = _txn_payload()
    a = receiver.ingest_webhook(payload, signature=None, delivery_id="ignored")
    b = receiver.ingest_webhook(payload, signature=None, delivery_id="ignored")
    assert a is not None
    assert b is not None


def test_idempotency_store_persists_across_receivers(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    db = tmp_path / "oc-idem.db"
    payload = _txn_payload()

    a = OpenCollectiveRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    first = a.ingest_webhook(payload, signature=None, delivery_id="oc-persist")
    b = OpenCollectiveRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    second = b.ingest_webhook(payload, signature=None, delivery_id="oc-persist")

    assert first is not None
    assert second is None
