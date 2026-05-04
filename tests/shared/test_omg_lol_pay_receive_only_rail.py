"""Tests for the omg.lol Pay receive-only rail.

cc-task: ``publication-bus-monetization-rails-surfaces`` (closes the
keystone — 4 of 5 rails shipped previously; this rail completes
the set).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from shared.omg_lol_pay_receive_only_rail import (
    OMG_LOL_PAY_REQUIRE_IP_ALLOWLIST_ENV,
    OMG_LOL_PAY_WEBHOOK_SECRET_ENV,
    OmgLolPayRailReceiver,
    PaymentEvent,
    PaymentEventKind,
    ReceiveOnlyRailError,
)


def _payload(
    *,
    event: str = "payment_succeeded",
    donor_address: str = "alice",
    amount: str | int | float = "5.00",
    currency: str = "USD",
    occurred_at: str = "2026-05-04T23:00:00+00:00",
    source_ip: str | None = None,
) -> dict:
    body: dict = {
        "event": event,
        "donor": {"address": donor_address},
        "amount": {"amount": amount, "currency": currency},
        "occurred_at": occurred_at,
    }
    if source_ip is not None:
        body["source_ip"] = source_ip
    return body


def _sig(payload: dict, secret: str) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


# ── Happy path ────────────────────────────────────────────────────────


class TestHappyPath:
    def test_payment_succeeded_normalizes(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        evt = receiver.ingest_webhook(_payload())
        assert isinstance(evt, PaymentEvent)
        assert evt.event_kind is PaymentEventKind.PAYMENT_SUCCEEDED
        assert evt.donor_handle == "alice"
        assert evt.amount_usd_cents == 500
        assert evt.occurred_at == datetime(2026, 5, 4, 23, 0, 0, tzinfo=UTC)
        assert len(evt.raw_payload_sha256) == 64

    def test_payment_refunded_normalizes(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        evt = receiver.ingest_webhook(_payload(event="payment_refunded"))
        assert evt.event_kind is PaymentEventKind.PAYMENT_REFUNDED

    def test_subscription_set_normalizes(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        evt = receiver.ingest_webhook(_payload(event="subscription_set"))
        assert evt.event_kind is PaymentEventKind.SUBSCRIPTION_SET

    def test_subscription_cancelled_normalizes(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        evt = receiver.ingest_webhook(_payload(event="subscription_cancelled"))
        assert evt.event_kind is PaymentEventKind.SUBSCRIPTION_CANCELLED


# ── Action coercion ───────────────────────────────────────────────────


class TestActionCoercion:
    def test_dotted_alias_is_accepted(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        evt = receiver.ingest_webhook(_payload(event="payment.succeeded"))
        assert evt.event_kind is PaymentEventKind.PAYMENT_SUCCEEDED

    def test_unknown_event_is_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        with pytest.raises(ReceiveOnlyRailError, match="unaccepted webhook event"):
            receiver.ingest_webhook(_payload(event="unknown.kind"))

    def test_non_string_event_is_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        payload = _payload()
        payload["event"] = 42
        with pytest.raises(ReceiveOnlyRailError, match="must be a string"):
            receiver.ingest_webhook(payload)


# ── HMAC verification ─────────────────────────────────────────────────


class TestHmacVerification:
    def test_valid_signature_passes(self):
        secret = "deadbeef"
        receiver = OmgLolPayRailReceiver(webhook_secret=secret)
        payload = _payload()
        evt = receiver.ingest_webhook(payload, signature=_sig(payload, secret))
        assert evt.event_kind is PaymentEventKind.PAYMENT_SUCCEEDED

    def test_sha256_prefixed_signature_passes(self):
        secret = "deadbeef"
        receiver = OmgLolPayRailReceiver(webhook_secret=secret)
        payload = _payload()
        evt = receiver.ingest_webhook(payload, signature=f"sha256={_sig(payload, secret)}")
        assert evt.event_kind is PaymentEventKind.PAYMENT_SUCCEEDED

    def test_invalid_signature_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="deadbeef")
        with pytest.raises(ReceiveOnlyRailError, match="HMAC SHA-256 signature mismatch"):
            receiver.ingest_webhook(_payload(), signature="0" * 64)

    def test_signature_provided_without_secret_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        with pytest.raises(ReceiveOnlyRailError, match="not set"):
            receiver.ingest_webhook(_payload(), signature="abc")

    def test_secret_set_but_no_signature_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="deadbeef")
        with pytest.raises(ReceiveOnlyRailError, match="no signature was provided"):
            receiver.ingest_webhook(_payload())


# ── Currency / amount handling ────────────────────────────────────────


class TestAmountAndCurrency:
    def test_non_usd_currency_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        with pytest.raises(ReceiveOnlyRailError, match="non-USD currency"):
            receiver.ingest_webhook(_payload(currency="EUR"))

    def test_string_amount_converted_to_cents(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        evt = receiver.ingest_webhook(_payload(amount="12.34"))
        assert evt.amount_usd_cents == 1234

    def test_int_amount_converted_to_cents(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        evt = receiver.ingest_webhook(_payload(amount=10))
        assert evt.amount_usd_cents == 1000

    def test_negative_amount_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        with pytest.raises(ReceiveOnlyRailError, match="non-negative"):
            receiver.ingest_webhook(_payload(amount="-1.00"))

    def test_bool_amount_rejected(self):
        """Bool is an int subclass in Python; we reject it explicitly."""
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        payload = _payload()
        payload["amount"]["amount"] = True
        with pytest.raises(ReceiveOnlyRailError, match="must be a number"):
            receiver.ingest_webhook(payload)

    def test_invalid_decimal_string_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        with pytest.raises(ReceiveOnlyRailError, match="invalid 'amount.amount' decimal"):
            receiver.ingest_webhook(_payload(amount="not-a-number"))


# ── Donor handle validation ───────────────────────────────────────────


class TestDonorHandle:
    def test_username_alias_accepted(self):
        """``donor.username`` is accepted as an alias for ``donor.address``."""
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        payload = _payload()
        payload["donor"] = {"username": "bob"}
        evt = receiver.ingest_webhook(payload)
        assert evt.donor_handle == "bob"

    def test_email_in_handle_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        with pytest.raises(ReceiveOnlyRailError, match="omg.lol address"):
            receiver.ingest_webhook(_payload(donor_address="alice@example.com"))

    def test_path_in_handle_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        with pytest.raises(ReceiveOnlyRailError, match="omg.lol address"):
            receiver.ingest_webhook(_payload(donor_address="org/alice"))

    def test_missing_donor_object_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        payload = _payload()
        del payload["donor"]
        with pytest.raises(ReceiveOnlyRailError, match="missing 'donor'"):
            receiver.ingest_webhook(payload)


# ── IP allowlist enforcement ──────────────────────────────────────────


class TestIpAllowlist:
    def test_allowlist_required_but_no_source_ip_rejects(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="", require_ip_allowlist=True)
        with pytest.raises(ReceiveOnlyRailError, match="missing 'source_ip'"):
            receiver.ingest_webhook(_payload())

    def test_allowlist_required_with_source_ip_passes(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="", require_ip_allowlist=True)
        evt = receiver.ingest_webhook(_payload(source_ip="203.0.113.5"))
        assert evt.donor_handle == "alice"

    def test_env_var_enables_ip_allowlist(self):
        with mock.patch.dict("os.environ", {OMG_LOL_PAY_REQUIRE_IP_ALLOWLIST_ENV: "1"}):
            receiver = OmgLolPayRailReceiver(webhook_secret="")
            with pytest.raises(ReceiveOnlyRailError, match="missing 'source_ip'"):
                receiver.ingest_webhook(_payload())


# ── Payload shape ─────────────────────────────────────────────────────


class TestPayloadShape:
    def test_non_dict_payload_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        with pytest.raises(ReceiveOnlyRailError, match="must be a JSON object"):
            receiver.ingest_webhook("not-a-dict")  # type: ignore[arg-type]

    def test_missing_amount_object_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        payload = _payload()
        del payload["amount"]
        with pytest.raises(ReceiveOnlyRailError, match="missing 'amount'"):
            receiver.ingest_webhook(payload)

    def test_missing_occurred_at_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        payload = _payload()
        del payload["occurred_at"]
        with pytest.raises(ReceiveOnlyRailError, match="missing 'occurred_at'"):
            receiver.ingest_webhook(payload)

    def test_invalid_iso_timestamp_rejected(self):
        receiver = OmgLolPayRailReceiver(webhook_secret="")
        with pytest.raises(ReceiveOnlyRailError, match="invalid ISO 8601 timestamp"):
            receiver.ingest_webhook(_payload(occurred_at="not-a-date"))


# ── Env var loading ───────────────────────────────────────────────────


class TestEnvLoading:
    def test_secret_loaded_from_env_when_not_passed(self):
        with mock.patch.dict("os.environ", {OMG_LOL_PAY_WEBHOOK_SECRET_ENV: "envsecret"}):
            receiver = OmgLolPayRailReceiver()
            payload = _payload()
            evt = receiver.ingest_webhook(payload, signature=_sig(payload, "envsecret"))
            assert evt.donor_handle == "alice"
