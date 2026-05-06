"""Tests for chronicle salience tagging on liberapay payment events.

Sibling to #2697 (lightning) and #2706 (nostr zap). Completes the
salience-tagging trio across all three payment rails.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import mock


def test_record_chronicle_tags_salience() -> None:
    from agents.operator_awareness.state import PaymentEvent
    from agents.payment_processors.liberapay_receiver import _record_chronicle

    captured: list = []

    def fake_record(event):  # type: ignore[no-untyped-def]
        captured.append(event)

    event = PaymentEvent(
        rail="liberapay",
        amount_eur=5,
        timestamp=datetime(2026, 5, 6, tzinfo=UTC),
        external_id="lp-test",
    )
    with mock.patch("agents.payment_processors.liberapay_receiver.record", fake_record):
        _record_chronicle(event)

    assert len(captured) == 1
    chronicle_event = captured[0]
    assert chronicle_event.source == "payment_processors.liberapay"
    assert chronicle_event.event_type == "payment.received"
    assert chronicle_event.payload["salience"] >= 0.7
    assert chronicle_event.payload["salience"] == 0.95


def test_payload_preserves_existing_fields() -> None:
    from agents.operator_awareness.state import PaymentEvent
    from agents.payment_processors.liberapay_receiver import _record_chronicle

    captured: list = []

    def fake_record(event):  # type: ignore[no-untyped-def]
        captured.append(event)

    event = PaymentEvent(
        rail="liberapay",
        amount_eur=10,
        timestamp=datetime(2026, 5, 6, tzinfo=UTC),
        external_id="lp-preserve",
    )
    with mock.patch("agents.payment_processors.liberapay_receiver.record", fake_record):
        _record_chronicle(event)

    payload = captured[0].payload
    assert payload["rail"] == "liberapay"
    assert payload["amount_eur"] == 10
    assert payload["external_id"] == "lp-preserve"
    assert payload["salience"] == 0.95
