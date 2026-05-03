"""Tests for the Patreon receive-only rail.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from unittest import mock

import pytest

from shared.patreon_receive_only_rail import (
    PATREON_WEBHOOK_SECRET_ENV,
    PatreonRailReceiver,
    PledgeEvent,
    PledgeEventKind,
    ReceiveOnlyRailError,
)

# ---------------------------------------------------------------------------
# Fixture builders — JSON:API-shaped payloads
# ---------------------------------------------------------------------------


def _members_create_payload(
    *,
    vanity: str = "ada-lovelace",
    currently_entitled_amount_cents: int = 500,
    will_pay_amount_cents: int = 500,
    pledge_relationship_start: str = "2026-04-15T12:34:56.000+00:00",
    currency: str = "USD",
) -> dict:
    """Build a JSON:API ``member`` payload with linked user + campaign."""
    return {
        "data": {
            "type": "member",
            "id": "mbr_01",
            "attributes": {
                "patron_status": "active_patron",
                "currently_entitled_amount_cents": currently_entitled_amount_cents,
                "will_pay_amount_cents": will_pay_amount_cents,
                "pledge_relationship_start": pledge_relationship_start,
                "last_charge_status": "Paid",
                "last_charge_date": "2026-04-15T12:34:56.000+00:00",
                "lifetime_support_cents": 500,
                "campaign_lifetime_support_cents": 500,
            },
            "relationships": {
                "user": {"data": {"type": "user", "id": "usr_01"}},
                "campaign": {"data": {"type": "campaign", "id": "cmp_01"}},
            },
        },
        "included": [
            {
                "type": "user",
                "id": "usr_01",
                "attributes": {"vanity": vanity},
            },
            {
                "type": "campaign",
                "id": "cmp_01",
                "attributes": {"currency": currency, "vanity": "creator-vanity"},
            },
        ],
    }


def _members_update_payload(**kwargs) -> dict:
    payload = _members_create_payload(**kwargs)
    # Update events typically carry a fresher last_charge_date.
    payload["data"]["attributes"]["last_charge_date"] = "2026-05-15T08:00:00.000+00:00"
    return payload


def _members_pledge_create_payload(
    *,
    vanity: str = "grace-hopper",
    will_pay_amount_cents: int = 1000,
    currency: str = "EUR",
) -> dict:
    payload = _members_create_payload(
        vanity=vanity,
        currently_entitled_amount_cents=0,  # entitlement not yet computed
        will_pay_amount_cents=will_pay_amount_cents,
        currency=currency,
    )
    return payload


def _members_pledge_delete_payload(
    *,
    vanity: str = "alan-turing",
    currency: str = "GBP",
) -> dict:
    """Pledge-delete may carry no pricing — fall back path covered."""
    return {
        "data": {
            "type": "member",
            "id": "mbr_02",
            "attributes": {
                "patron_status": "former_patron",
                "pledge_relationship_start": "2025-01-01T00:00:00.000+00:00",
                "last_charge_date": "2026-04-30T15:00:00.000+00:00",
            },
            "relationships": {
                "user": {"data": {"type": "user", "id": "usr_02"}},
                "campaign": {"data": {"type": "campaign", "id": "cmp_01"}},
            },
        },
        "included": [
            {"type": "user", "id": "usr_02", "attributes": {"vanity": vanity}},
            {"type": "campaign", "id": "cmp_01", "attributes": {"currency": currency}},
        ],
    }


def _patreon_sign(payload: dict, secret: str) -> str:
    """Build an X-Patreon-Signature header for the canonical-JSON payload."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), body, hashlib.md5).hexdigest()


# ---------------------------------------------------------------------------
# Happy paths × 4 event kinds
# ---------------------------------------------------------------------------


def test_ingest_members_create_returns_normalized_event():
    receiver = PatreonRailReceiver()
    payload = _members_create_payload()
    event = receiver.ingest_webhook(payload, signature=None, event_header="members:create")
    assert isinstance(event, PledgeEvent)
    assert event.event_kind is PledgeEventKind.MEMBERS_CREATE
    assert event.patron_handle == "ada-lovelace"
    assert event.amount_currency_cents == 500
    assert event.currency == "USD"
    assert event.occurred_at == datetime.fromisoformat("2026-04-15T12:34:56.000+00:00")
    assert len(event.raw_payload_sha256) == 64


def test_ingest_members_update_returns_normalized_event():
    receiver = PatreonRailReceiver()
    event = receiver.ingest_webhook(
        _members_update_payload(),
        signature=None,
        event_header="members:update",
    )
    assert event is not None
    assert event.event_kind is PledgeEventKind.MEMBERS_UPDATE
    # Update prefers last_charge_date as occurred_at.
    assert event.occurred_at == datetime.fromisoformat("2026-05-15T08:00:00.000+00:00")


def test_ingest_members_pledge_create_falls_back_to_will_pay_amount():
    receiver = PatreonRailReceiver()
    payload = _members_pledge_create_payload(will_pay_amount_cents=1000, currency="EUR")
    event = receiver.ingest_webhook(payload, signature=None, event_header="members:pledge:create")
    assert event is not None
    assert event.event_kind is PledgeEventKind.MEMBERS_PLEDGE_CREATE
    assert event.amount_currency_cents == 1000  # currently_entitled was 0, falls to will_pay
    assert event.currency == "EUR"
    assert event.patron_handle == "grace-hopper"


def test_ingest_members_pledge_delete_no_pricing_defaults_to_zero():
    receiver = PatreonRailReceiver()
    payload = _members_pledge_delete_payload()
    event = receiver.ingest_webhook(payload, signature=None, event_header="members:pledge:delete")
    assert event is not None
    assert event.event_kind is PledgeEventKind.MEMBERS_PLEDGE_DELETE
    assert event.amount_currency_cents == 0
    assert event.currency == "GBP"


# ---------------------------------------------------------------------------
# HMAC MD5 signature verification
# ---------------------------------------------------------------------------


def test_valid_md5_signature_succeeds():
    secret = "patreon_webhook_topsecret"
    payload = _members_create_payload()
    sig = _patreon_sign(payload, secret)
    with mock.patch.dict("os.environ", {PATREON_WEBHOOK_SECRET_ENV: secret}, clear=False):
        receiver = PatreonRailReceiver()
        event = receiver.ingest_webhook(payload, signature=sig, event_header="members:create")
    assert event is not None
    assert event.patron_handle == "ada-lovelace"


def test_invalid_md5_signature_raises():
    payload = _members_create_payload()
    bad_sig = "0" * 32  # MD5 hex is 32 chars, not 64
    with mock.patch.dict(
        "os.environ", {PATREON_WEBHOOK_SECRET_ENV: "patreon_webhook_topsecret"}, clear=False
    ):
        receiver = PatreonRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="signature mismatch"):
            receiver.ingest_webhook(payload, signature=bad_sig, event_header="members:create")


def test_signature_present_but_secret_missing_raises():
    payload = _members_create_payload()
    sig = "a" * 32
    with mock.patch.dict("os.environ", {}, clear=True):
        receiver = PatreonRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="not set"):
            receiver.ingest_webhook(payload, signature=sig, event_header="members:create")


def test_missing_signature_skips_verification_and_succeeds():
    receiver = PatreonRailReceiver()
    event = receiver.ingest_webhook(
        _members_create_payload(), signature=None, event_header="members:create"
    )
    assert event is not None


def test_md5_signature_is_32_hex_chars_not_sha256_64():
    """Patreon's MD5 hex digest is 32 chars; SHA-256 would be 64. Pin the wire format."""
    secret = "x"
    sig = _patreon_sign(_members_create_payload(), secret)
    assert len(sig) == 32
    assert all(c in "0123456789abcdef" for c in sig)


# ---------------------------------------------------------------------------
# JSON:API payload structure parsing — included[] walking
# ---------------------------------------------------------------------------


def test_walks_included_for_user_vanity():
    """The patron handle must come from included[type=user].attributes.vanity."""
    receiver = PatreonRailReceiver()
    payload = _members_create_payload(vanity="distinct-vanity")
    event = receiver.ingest_webhook(payload, signature=None, event_header="members:create")
    assert event is not None
    assert event.patron_handle == "distinct-vanity"


def test_falls_back_to_user_relationship_id_when_included_missing():
    """If included[] has no user, fall back to relationships.user.data.id."""
    payload = _members_create_payload()
    # Drop the user from included; keep only the campaign.
    payload["included"] = [e for e in payload["included"] if e["type"] != "user"]
    receiver = PatreonRailReceiver()
    event = receiver.ingest_webhook(payload, signature=None, event_header="members:create")
    assert event is not None
    assert event.patron_handle == "usr_01"  # from relationships.user.data.id


def test_walks_included_for_campaign_currency():
    """Currency must come from included[type=campaign].attributes.currency."""
    receiver = PatreonRailReceiver()
    for currency in ("EUR", "GBP", "CAD"):
        payload = _members_create_payload(currency=currency)
        event = receiver.ingest_webhook(payload, signature=None, event_header="members:create")
        assert event is not None
        assert event.currency == currency


def test_currency_defaults_to_usd_when_no_campaign_included():
    """If included[] has no campaign, default to USD (Patreon's default)."""
    payload = _members_create_payload()
    payload["included"] = [e for e in payload["included"] if e["type"] != "campaign"]
    receiver = PatreonRailReceiver()
    event = receiver.ingest_webhook(payload, signature=None, event_header="members:create")
    assert event is not None
    assert event.currency == "USD"


def test_lowercase_campaign_currency_normalized_to_uppercase():
    """Patreon may emit lowercase currency codes; normalize to uppercase."""
    payload = _members_create_payload()
    payload["included"][1]["attributes"]["currency"] = "eur"
    receiver = PatreonRailReceiver()
    event = receiver.ingest_webhook(payload, signature=None, event_header="members:create")
    assert event is not None
    assert event.currency == "EUR"


# ---------------------------------------------------------------------------
# Event-header coercion
# ---------------------------------------------------------------------------


def test_underscored_event_kind_canonical_accepted():
    """Underscored canonical form is accepted (parity with siblings)."""
    receiver = PatreonRailReceiver()
    event = receiver.ingest_webhook(
        _members_create_payload(), signature=None, event_header="members_create"
    )
    assert event is not None
    assert event.event_kind is PledgeEventKind.MEMBERS_CREATE


def test_unknown_event_kind_raises():
    receiver = PatreonRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="unaccepted webhook event kind"):
        receiver.ingest_webhook(
            _members_create_payload(), signature=None, event_header="posts:publish"
        )


def test_members_delete_rejected_as_unaccepted():
    """members:delete is documented but we don't accept it — only the 4 chosen kinds."""
    receiver = PatreonRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="unaccepted"):
        receiver.ingest_webhook(
            _members_create_payload(), signature=None, event_header="members:delete"
        )


def test_missing_event_header_raises():
    """Patreon ships event kind in X-Patreon-Event header; missing → raise."""
    receiver = PatreonRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="missing 'X-Patreon-Event'"):
        receiver.ingest_webhook(_members_create_payload(), signature=None, event_header=None)


# ---------------------------------------------------------------------------
# Malformed payload rejection
# ---------------------------------------------------------------------------


def test_payload_not_dict_raises():
    receiver = PatreonRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="payload must be a dict"):
        receiver.ingest_webhook("not a dict", signature=None, event_header="members:create")  # type: ignore[arg-type]


def test_payload_missing_data_raises():
    receiver = PatreonRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="missing 'data'"):
        receiver.ingest_webhook({}, signature=None, event_header="members:create")


def test_payload_missing_data_attributes_raises():
    receiver = PatreonRailReceiver()
    payload = {"data": {"type": "member", "id": "mbr_01"}}
    with pytest.raises(ReceiveOnlyRailError, match="missing 'data.attributes'"):
        receiver.ingest_webhook(payload, signature=None, event_header="members:create")


def test_payload_missing_user_and_relationships_raises():
    receiver = PatreonRailReceiver()
    payload = _members_create_payload()
    payload["included"] = [e for e in payload["included"] if e["type"] != "user"]
    del payload["data"]["relationships"]["user"]
    with pytest.raises(ReceiveOnlyRailError, match="missing both"):
        receiver.ingest_webhook(payload, signature=None, event_header="members:create")


def test_members_create_missing_amount_raises():
    receiver = PatreonRailReceiver()
    payload = _members_create_payload()
    del payload["data"]["attributes"]["currently_entitled_amount_cents"]
    del payload["data"]["attributes"]["will_pay_amount_cents"]
    with pytest.raises(ReceiveOnlyRailError, match="currently_entitled_amount_cents"):
        receiver.ingest_webhook(payload, signature=None, event_header="members:create")


def test_payload_missing_timestamp_raises():
    receiver = PatreonRailReceiver()
    payload = _members_create_payload()
    del payload["data"]["attributes"]["pledge_relationship_start"]
    del payload["data"]["attributes"]["last_charge_date"]
    with pytest.raises(ReceiveOnlyRailError, match="pledge_relationship_start"):
        receiver.ingest_webhook(payload, signature=None, event_header="members:create")


def test_invalid_iso_timestamp_raises():
    receiver = PatreonRailReceiver()
    payload = _members_create_payload()
    payload["data"]["attributes"]["pledge_relationship_start"] = "not-a-date"
    payload["data"]["attributes"]["last_charge_date"] = "also-not-a-date"
    with pytest.raises(ReceiveOnlyRailError, match="invalid ISO 8601"):
        receiver.ingest_webhook(payload, signature=None, event_header="members:create")


def test_patron_handle_with_email_rejected():
    """Even if Patreon somehow ships an email in the vanity field, reject it."""
    receiver = PatreonRailReceiver()
    payload = _members_create_payload(vanity="leaked@example.com")
    with pytest.raises(ReceiveOnlyRailError, match="vanity slug"):
        receiver.ingest_webhook(payload, signature=None, event_header="members:create")


def test_patron_handle_with_slash_rejected():
    """A slash would mean a qualified URL leaked through."""
    receiver = PatreonRailReceiver()
    payload = _members_create_payload(vanity="patreon.com/ada")
    with pytest.raises(ReceiveOnlyRailError, match="vanity slug"):
        receiver.ingest_webhook(payload, signature=None, event_header="members:create")


# ---------------------------------------------------------------------------
# Receive-only invariant: NO outbound network calls
# ---------------------------------------------------------------------------


def test_no_outbound_network_calls_during_ingest():
    """Mock urllib + assert the receiver never invokes it across all 4 kinds."""
    receiver = PatreonRailReceiver()
    with (
        mock.patch("urllib.request.urlopen") as mock_urlopen,
        mock.patch("urllib.request.Request") as mock_request,
    ):
        cases = [
            (_members_create_payload(), "members:create"),
            (_members_update_payload(), "members:update"),
            (_members_pledge_create_payload(), "members:pledge:create"),
            (_members_pledge_delete_payload(), "members:pledge:delete"),
        ]
        for payload, header in cases:
            event = receiver.ingest_webhook(payload, signature=None, event_header=header)
            assert event is not None
        # Also exercise an error path — no network even when failing.
        with pytest.raises(ReceiveOnlyRailError):
            receiver.ingest_webhook(
                _members_create_payload(),
                signature=None,
                event_header="garbage:event",
            )
    assert mock_urlopen.call_count == 0
    assert mock_request.call_count == 0


def test_receiver_does_not_use_httpx():
    """If httpx is in the env, ensure none of its surfaces are invoked."""
    pytest.importorskip("httpx")
    import httpx  # type: ignore[import-not-found]

    receiver = PatreonRailReceiver()
    with (
        mock.patch.object(httpx, "Client") as mock_client,
        mock.patch.object(httpx, "AsyncClient") as mock_async_client,
        mock.patch.object(httpx, "post") as mock_post,
        mock.patch.object(httpx, "get") as mock_get,
    ):
        event = receiver.ingest_webhook(
            _members_create_payload(), signature=None, event_header="members:create"
        )
        assert event is not None
    assert mock_client.call_count == 0
    assert mock_async_client.call_count == 0
    assert mock_post.call_count == 0
    assert mock_get.call_count == 0


def test_receiver_does_not_use_requests():
    """If requests is in the env, ensure none of its surfaces are invoked."""
    pytest.importorskip("requests")
    import requests  # type: ignore[import-untyped]

    receiver = PatreonRailReceiver()
    with (
        mock.patch.object(requests, "post") as mock_post,
        mock.patch.object(requests, "get") as mock_get,
        mock.patch.object(requests, "Session") as mock_session,
    ):
        event = receiver.ingest_webhook(
            _members_create_payload(), signature=None, event_header="members:create"
        )
        assert event is not None
    assert mock_post.call_count == 0
    assert mock_get.call_count == 0
    assert mock_session.call_count == 0


def test_receiver_does_not_import_patreon_sdk():
    """The production module must NOT import any Patreon SDK."""
    import shared.patreon_receive_only_rail as rail_mod

    src = rail_mod.__file__
    assert src is not None
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    assert "\nimport patreon" not in text
    assert "\nfrom patreon" not in text


# ---------------------------------------------------------------------------
# Other invariants
# ---------------------------------------------------------------------------


def test_empty_payload_with_no_signature_or_event_returns_none():
    """Heartbeat: empty payload + no signature + no event header → None."""
    receiver = PatreonRailReceiver()
    assert receiver.ingest_webhook({}, signature=None, event_header=None) is None


def test_sha256_in_event_matches_canonical_payload():
    """raw_payload_sha256 is SHA-256 (NOT MD5) of the canonical JSON bytes."""
    receiver = PatreonRailReceiver()
    payload = _members_create_payload()
    event = receiver.ingest_webhook(payload, signature=None, event_header="members:create")
    expected = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert event is not None
    assert event.raw_payload_sha256 == expected


def test_pledge_event_is_frozen_no_pii_fields():
    """Pydantic ``extra='forbid'`` rejects PII keys at construction time."""
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        PledgeEvent(
            patron_handle="ada-lovelace",
            amount_currency_cents=500,
            currency="USD",
            event_kind=PledgeEventKind.MEMBERS_CREATE,
            occurred_at=datetime.fromisoformat("2026-04-15T12:34:56+00:00"),
            raw_payload_sha256="a" * 64,
            email="leaked@example.com",  # type: ignore[call-arg]
        )


def test_negative_amount_normalized_to_absolute():
    """Refunds/chargebacks ship as negative; rail expresses gross movement."""
    receiver = PatreonRailReceiver()
    payload = _members_create_payload(currently_entitled_amount_cents=-500)
    event = receiver.ingest_webhook(payload, signature=None, event_header="members:create")
    assert event is not None
    assert event.amount_currency_cents == 500


# ---------------------------------------------------------------------------
# jr-patreon-rail-idempotency-pin regression pins
# ---------------------------------------------------------------------------


def test_idempotency_store_rejects_duplicate_webhook_id(tmp_path):
    """Replay of the same X-Patreon-Webhook-Id is short-circuited to None."""
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "patreon-idem.db")
    receiver = PatreonRailReceiver(idempotency_store=store)

    payload = _members_create_payload()
    first = receiver.ingest_webhook(
        payload,
        signature=None,
        event_header="members:create",
        webhook_id="wh_test_idempotent_001",
    )
    assert first is not None
    assert first.amount_currency_cents == 500

    # Same webhook_id arrives again.
    second = receiver.ingest_webhook(
        payload,
        signature=None,
        event_header="members:create",
        webhook_id="wh_test_idempotent_001",
    )
    assert second is None  # short-circuit; caller returns 200 OK


def test_idempotency_store_distinct_webhook_ids_both_processed(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "patreon-idem.db")
    receiver = PatreonRailReceiver(idempotency_store=store)

    payload = _members_create_payload()
    first = receiver.ingest_webhook(
        payload, signature=None, event_header="members:create", webhook_id="wh_a"
    )
    second = receiver.ingest_webhook(
        payload, signature=None, event_header="members:create", webhook_id="wh_b"
    )
    assert first is not None
    assert second is not None


def test_idempotency_store_provided_but_webhook_id_missing_raises(tmp_path):
    """Receiver constructed with store but caller didn't pass webhook_id → fail closed."""
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "patreon-idem.db")
    receiver = PatreonRailReceiver(idempotency_store=store)

    payload = _members_create_payload()
    with pytest.raises(ReceiveOnlyRailError, match="webhook_id missing"):
        receiver.ingest_webhook(
            payload,
            signature=None,
            event_header="members:create",
        )


def test_no_idempotency_store_means_no_idempotency_check():
    """Receiver constructed without store: duplicates processed twice (legacy shape)."""
    receiver = PatreonRailReceiver()  # no idempotency_store
    payload = _members_create_payload()
    a = receiver.ingest_webhook(
        payload, signature=None, event_header="members:create", webhook_id="ignored"
    )
    b = receiver.ingest_webhook(
        payload, signature=None, event_header="members:create", webhook_id="ignored"
    )
    assert a is not None
    assert b is not None  # no store → no short-circuit


def test_idempotency_store_table_persists_on_disk(tmp_path):
    """Two receivers pointed at the same db share the seen-set."""
    from shared._rail_idempotency import IdempotencyStore

    db_path = tmp_path / "patreon-idem.db"
    payload = _members_create_payload()

    receiver_a = PatreonRailReceiver(idempotency_store=IdempotencyStore(db_path=db_path))
    assert (
        receiver_a.ingest_webhook(
            payload,
            signature=None,
            event_header="members:create",
            webhook_id="wh_persist",
        )
        is not None
    )

    # Fresh receiver, fresh store, same db path → duplicate short-circuited.
    receiver_b = PatreonRailReceiver(idempotency_store=IdempotencyStore(db_path=db_path))
    assert (
        receiver_b.ingest_webhook(
            payload,
            signature=None,
            event_header="members:create",
            webhook_id="wh_persist",
        )
        is None
    )
