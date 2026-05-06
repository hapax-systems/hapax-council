"""Tests for chronicle salience tagging on nostr zap payment events.

Sibling to #2697 (lightning). ``payment_processors.nostr_zap`` is not
in the chronicle-ticker source allow-list, so without ``salience >= 0.7``
zap receipts never surface in the lore strip.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import mock


def test_record_chronicle_tags_salience() -> None:
    from agents.operator_awareness.state import PaymentEvent
    from agents.payment_processors.nostr_zap_listener import _record_chronicle

    captured: list = []

    def fake_record(event):  # type: ignore[no-untyped-def]
        captured.append(event)

    event = PaymentEvent(
        rail="nostr_zap",
        amount_sats=2100,
        timestamp=datetime(2026, 5, 6, tzinfo=UTC),
        external_id="zap-test",
    )
    with mock.patch("agents.payment_processors.nostr_zap_listener.record", fake_record):
        _record_chronicle(event)

    assert len(captured) == 1
    chronicle_event = captured[0]
    assert chronicle_event.source == "payment_processors.nostr_zap"
    assert chronicle_event.event_type == "payment.received"
    assert chronicle_event.payload["salience"] >= 0.7
    assert chronicle_event.payload["salience"] == 0.95


def test_payload_preserves_existing_fields() -> None:
    from agents.operator_awareness.state import PaymentEvent
    from agents.payment_processors.nostr_zap_listener import _record_chronicle

    captured: list = []

    def fake_record(event):  # type: ignore[no-untyped-def]
        captured.append(event)

    event = PaymentEvent(
        rail="nostr_zap",
        amount_sats=420,
        timestamp=datetime(2026, 5, 6, tzinfo=UTC),
        external_id="zap-preserve",
    )
    with mock.patch("agents.payment_processors.nostr_zap_listener.record", fake_record):
        _record_chronicle(event)

    payload = captured[0].payload
    assert payload["rail"] == "nostr_zap"
    assert payload["amount_sats"] == 420
    assert payload["external_id"] == "zap-preserve"
    assert payload["salience"] == 0.95
