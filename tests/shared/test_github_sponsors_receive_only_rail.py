"""Tests for the GitHub Sponsors receive-only rail.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from shared.github_sponsors_receive_only_rail import (
    GITHUB_SPONSORS_WEBHOOK_SECRET_ENV,
    GitHubSponsorsRailReceiver,
    ReceiveOnlyRailError,
    SponsorshipEvent,
    SponsorshipEventKind,
)


def _payload(
    *,
    action: str = "created",
    sponsor_login: str = "octocat",
    monthly_usd: int | float = 25,
    created_at: str = "2026-05-02T12:00:00Z",
    effective_date: str | None = None,
) -> dict:
    payload = {
        "action": action,
        "sponsorship": {
            "created_at": created_at,
            "sponsor": {"login": sponsor_login},
            "tier": {"monthly_price_in_dollars": monthly_usd},
        },
    }
    if effective_date is not None:
        payload["effective_date"] = effective_date
    return payload


def _sign(payload: dict, secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# Happy paths for all 4 accepted event kinds
# ---------------------------------------------------------------------------


def test_ingest_created_event_unsigned_returns_normalized_event():
    receiver = GitHubSponsorsRailReceiver()
    event = receiver.ingest_webhook(_payload(action="created"), signature=None)
    assert isinstance(event, SponsorshipEvent)
    assert event.event_kind is SponsorshipEventKind.CREATED
    assert event.sponsor_login == "octocat"
    assert event.amount_usd_cents == 2500
    assert event.occurred_at == datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    assert len(event.raw_payload_sha256) == 64


def test_ingest_cancelled_event_returns_normalized_event():
    receiver = GitHubSponsorsRailReceiver()
    event = receiver.ingest_webhook(_payload(action="cancelled"), signature=None)
    assert event is not None
    assert event.event_kind is SponsorshipEventKind.CANCELLED


def test_ingest_tier_changed_event_returns_normalized_event():
    receiver = GitHubSponsorsRailReceiver()
    event = receiver.ingest_webhook(
        _payload(action="tier_changed", monthly_usd=100), signature=None
    )
    assert event is not None
    assert event.event_kind is SponsorshipEventKind.TIER_CHANGED
    assert event.amount_usd_cents == 10000


def test_ingest_pending_cancellation_event_uses_effective_date_or_created_at():
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload(
        action="pending_cancellation",
        created_at="2026-04-01T00:00:00Z",
        effective_date="2026-06-01T00:00:00Z",
    )
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.event_kind is SponsorshipEventKind.PENDING_CANCELLATION
    # `created_at` takes precedence when present (canonical for the event)
    assert event.occurred_at == datetime(2026, 4, 1, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_valid_signature_succeeds():
    secret = "topsecret-shh"
    payload = _payload()
    sig = _sign(payload, secret)
    with mock.patch.dict("os.environ", {GITHUB_SPONSORS_WEBHOOK_SECRET_ENV: secret}, clear=False):
        receiver = GitHubSponsorsRailReceiver()
        event = receiver.ingest_webhook(payload, signature=sig)
    assert event is not None
    assert event.sponsor_login == "octocat"


def test_invalid_signature_raises_receive_only_rail_error():
    payload = _payload()
    bad_sig = "sha256=" + ("0" * 64)
    with mock.patch.dict(
        "os.environ", {GITHUB_SPONSORS_WEBHOOK_SECRET_ENV: "topsecret-shh"}, clear=False
    ):
        receiver = GitHubSponsorsRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="HMAC SHA-256 signature mismatch"):
            receiver.ingest_webhook(payload, signature=bad_sig)


def test_signature_present_but_secret_missing_raises():
    # Wipe any inherited value of the secret env var.
    payload = _payload()
    sig = "sha256=" + ("a" * 64)
    with mock.patch.dict("os.environ", {}, clear=True):
        receiver = GitHubSponsorsRailReceiver()
        with pytest.raises(ReceiveOnlyRailError, match="not set"):
            receiver.ingest_webhook(payload, signature=sig)


def test_missing_signature_skips_verification_and_succeeds():
    receiver = GitHubSponsorsRailReceiver()
    event = receiver.ingest_webhook(_payload(), signature=None)
    assert event is not None


# ---------------------------------------------------------------------------
# Malformed payload rejection
# ---------------------------------------------------------------------------


def test_unknown_action_raises():
    receiver = GitHubSponsorsRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="unaccepted webhook action"):
        receiver.ingest_webhook(_payload(action="edited"), signature=None)


def test_payload_not_dict_raises():
    receiver = GitHubSponsorsRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="payload must be a dict"):
        receiver.ingest_webhook("not a dict", signature=None)  # type: ignore[arg-type]


def test_payload_missing_sponsorship_raises():
    receiver = GitHubSponsorsRailReceiver()
    with pytest.raises(ReceiveOnlyRailError, match="missing 'sponsorship'"):
        receiver.ingest_webhook({"action": "created"}, signature=None)


def test_payload_missing_sponsor_login_raises():
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    del payload["sponsorship"]["sponsor"]["login"]
    with pytest.raises(ReceiveOnlyRailError, match="sponsorship.sponsor.login"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_tier_raises():
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    del payload["sponsorship"]["tier"]
    with pytest.raises(ReceiveOnlyRailError, match="sponsorship.tier"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_missing_timestamp_raises():
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    del payload["sponsorship"]["created_at"]
    with pytest.raises(ReceiveOnlyRailError, match="created_at"):
        receiver.ingest_webhook(payload, signature=None)


def test_payload_invalid_timestamp_raises():
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload(created_at="not-a-real-iso-8601-timestamp")
    with pytest.raises(ReceiveOnlyRailError, match="invalid ISO 8601"):
        receiver.ingest_webhook(payload, signature=None)


def test_negative_tier_amount_raises():
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload(monthly_usd=-1)
    with pytest.raises(ReceiveOnlyRailError, match="non-negative"):
        receiver.ingest_webhook(payload, signature=None)


def test_sponsor_login_with_email_rejected():
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload(sponsor_login="alice@example.com")
    with pytest.raises(ReceiveOnlyRailError, match="must be a GitHub handle"):
        receiver.ingest_webhook(payload, signature=None)


def test_action_must_be_string():
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    payload["action"] = 42
    with pytest.raises(ReceiveOnlyRailError, match="must be a string"):
        receiver.ingest_webhook(payload, signature=None)


# ---------------------------------------------------------------------------
# Receive-only invariant: NO outbound network calls
# ---------------------------------------------------------------------------


def test_no_outbound_network_calls_during_ingest():
    """Mock urllib + httpx; assert the receiver never invokes them."""
    receiver = GitHubSponsorsRailReceiver()
    with (
        mock.patch("urllib.request.urlopen") as mock_urlopen,
        mock.patch("urllib.request.Request") as mock_request,
    ):
        # Cover all four accepted event kinds in one ingest sweep.
        for action in ("created", "cancelled", "tier_changed", "pending_cancellation"):
            event = receiver.ingest_webhook(_payload(action=action), signature=None)
            assert event is not None
        # Also exercise an error path — no network even when failing.
        with pytest.raises(ReceiveOnlyRailError):
            receiver.ingest_webhook(_payload(action="garbage"), signature=None)
    assert mock_urlopen.call_count == 0
    assert mock_request.call_count == 0


def test_receiver_does_not_import_or_use_httpx():
    """If httpx is importable in the env, ensure none of its surfaces
    are invoked during ingest."""
    pytest.importorskip("httpx")
    import httpx  # type: ignore[import-not-found]

    receiver = GitHubSponsorsRailReceiver()
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
    receiver = GitHubSponsorsRailReceiver()
    assert receiver.ingest_webhook({}, signature=None) is None


def test_sha256_in_event_matches_canonical_payload():
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    event = receiver.ingest_webhook(payload, signature=None)
    expected = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert event is not None
    assert event.raw_payload_sha256 == expected


def test_sponsorship_event_is_frozen_no_pii_fields():
    """Pydantic ``extra='forbid'`` rejects PII keys at construction time."""
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        SponsorshipEvent(
            sponsor_login="octocat",
            amount_usd_cents=2500,
            event_kind=SponsorshipEventKind.CREATED,
            occurred_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            raw_payload_sha256="a" * 64,
            email="leaked@example.com",  # type: ignore[call-arg]
        )


def test_tier_amount_in_cents_passes_through_as_int():
    """If GitHub emits monthly_price_in_cents, it's passed through as int."""
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    del payload["sponsorship"]["tier"]["monthly_price_in_dollars"]
    payload["sponsorship"]["tier"]["monthly_price_in_cents"] = 2500
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_usd_cents == 2500
    assert isinstance(event.amount_usd_cents, int)


# ---------------------------------------------------------------------------
# jr-github-sponsors-rail-cents-normalization regression pins
# ---------------------------------------------------------------------------


def test_amount_usd_cents_is_int_not_float():
    """SponsorshipEvent.amount_usd_cents must be int (not float, no drift)."""
    receiver = GitHubSponsorsRailReceiver()
    event = receiver.ingest_webhook(_payload(monthly_usd=25), signature=None)
    assert event is not None
    assert isinstance(event.amount_usd_cents, int)
    # Floats explicitly disallowed by Pydantic when type is int.


def test_dollars_value_with_fractional_cents_rejected():
    """$1.234 doesn't multiply to integer cents — fail closed."""
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    payload["sponsorship"]["tier"]["monthly_price_in_dollars"] = 1.234
    with pytest.raises(ReceiveOnlyRailError, match="does not multiply to integer cents"):
        receiver.ingest_webhook(payload, signature=None)


def test_cents_field_with_bool_rejected():
    """``monthly_price_in_cents=True`` is not a valid int (bool is also int)."""
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    del payload["sponsorship"]["tier"]["monthly_price_in_dollars"]
    payload["sponsorship"]["tier"]["monthly_price_in_cents"] = True
    with pytest.raises(ReceiveOnlyRailError, match="must be int"):
        receiver.ingest_webhook(payload, signature=None)


def test_dollars_field_with_bool_rejected():
    """``monthly_price_in_dollars=False`` is not a valid amount."""
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    payload["sponsorship"]["tier"]["monthly_price_in_dollars"] = False
    with pytest.raises(ReceiveOnlyRailError, match="must be int or float"):
        receiver.ingest_webhook(payload, signature=None)


def test_canonical_bytes_helper_is_only_canonicalizer():
    """Module source must not carry any inline json.dumps with sort_keys.

    The receiver canonicalizes via :func:`_canonical_bytes`; any other
    inline call is a drift item that breaks the SHA echo invariant.
    """
    import inspect

    import shared.github_sponsors_receive_only_rail as mod

    src = inspect.getsource(mod)
    occurrences = src.count("json.dumps(")
    # Exactly one occurrence allowed — inside _canonical_bytes itself.
    assert occurrences == 1, f"expected 1 json.dumps call in module, got {occurrences}"


def test_dollars_value_at_one_dollar_yields_one_hundred_cents():
    """$1.00 → 100 cents (the canonical happy path for dollars input)."""
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload(monthly_usd=1)
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_usd_cents == 100


def test_dollars_value_with_two_decimals_yields_correct_cents():
    """$1.99 → 199 cents (no float drift)."""
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    payload["sponsorship"]["tier"]["monthly_price_in_dollars"] = 1.99
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_usd_cents == 199


def test_cents_field_preferred_over_dollars_when_both_present():
    """When both fields present, monthly_price_in_cents wins (canonical wire shape)."""
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    payload["sponsorship"]["tier"]["monthly_price_in_dollars"] = 99
    payload["sponsorship"]["tier"]["monthly_price_in_cents"] = 12345
    event = receiver.ingest_webhook(payload, signature=None)
    assert event is not None
    assert event.amount_usd_cents == 12345  # cents wins, not 99 * 100 = 9900


# ---------------------------------------------------------------------------
# jr-github-sponsors-rail-idempotency-pin regression pins
# ---------------------------------------------------------------------------


def test_idempotency_store_rejects_duplicate_delivery_id(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "ghs-idem.db")
    receiver = GitHubSponsorsRailReceiver(idempotency_store=store)
    payload = _payload()

    first = receiver.ingest_webhook(payload, signature=None, delivery_id="gh-001")
    second = receiver.ingest_webhook(payload, signature=None, delivery_id="gh-001")

    assert first is not None
    assert second is None


def test_idempotency_store_distinct_delivery_ids_both_processed(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "ghs-idem.db")
    receiver = GitHubSponsorsRailReceiver(idempotency_store=store)
    payload = _payload()

    first = receiver.ingest_webhook(payload, signature=None, delivery_id="gh-a")
    second = receiver.ingest_webhook(payload, signature=None, delivery_id="gh-b")

    assert first is not None
    assert second is not None


def test_idempotency_store_provided_but_delivery_id_missing_raises(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=tmp_path / "ghs-idem.db")
    receiver = GitHubSponsorsRailReceiver(idempotency_store=store)
    payload = _payload()

    with pytest.raises(ReceiveOnlyRailError, match="delivery_id"):
        receiver.ingest_webhook(payload, signature=None)


def test_no_idempotency_store_means_no_idempotency_check():
    receiver = GitHubSponsorsRailReceiver()
    payload = _payload()
    a = receiver.ingest_webhook(payload, signature=None, delivery_id="ignored")
    b = receiver.ingest_webhook(payload, signature=None, delivery_id="ignored")
    assert a is not None
    assert b is not None


def test_idempotency_store_persists_across_receivers(tmp_path):
    from shared._rail_idempotency import IdempotencyStore

    db = tmp_path / "ghs-idem.db"
    payload = _payload()

    a = GitHubSponsorsRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    first = a.ingest_webhook(payload, signature=None, delivery_id="gh-persist")
    b = GitHubSponsorsRailReceiver(idempotency_store=IdempotencyStore(db_path=db))
    second = b.ingest_webhook(payload, signature=None, delivery_id="gh-persist")

    assert first is not None
    assert second is None
