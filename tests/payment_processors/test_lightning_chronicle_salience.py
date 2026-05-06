"""Tests for chronicle salience tagging on lightning payment events.

Fifth in the *no in-tree emitter sets salience* cleanup series after
stimmung (#2637), m8 day-roll (#2661), narration_triad (#2669), and
mail-operational (#2682). ``payment_processors.lightning`` is not in
the chronicle-ticker source allow-list, so without ``salience >= 0.7``
payment receipts never surface in the lore strip.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import mock


def test_record_chronicle_tags_salience() -> None:
    from agents.payment_processors.lightning_receiver import (
        PaymentEvent,
        _record_chronicle,
    )

    captured: list = []

    def fake_record(event):  # type: ignore[no-untyped-def]
        captured.append(event)

    event = PaymentEvent(
        rail="lightning",
        amount_sats=2100,
        timestamp=datetime(2026, 5, 6, tzinfo=UTC),
        external_id="invoice-test",
    )
    with mock.patch("agents.payment_processors.lightning_receiver.record", fake_record):
        _record_chronicle(event)

    assert len(captured) == 1
    chronicle_event = captured[0]
    assert chronicle_event.source == "payment_processors.lightning"
    assert chronicle_event.event_type == "payment.received"
    # Payment receipts must clear the chronicle-ticker 0.7 floor so they
    # surface independent of the source allow-list.
    assert chronicle_event.payload["salience"] >= 0.7
    assert chronicle_event.payload["salience"] == 0.95


def test_payload_preserves_existing_fields() -> None:
    """Salience addition is purely additive — existing payload keys remain."""
    from agents.payment_processors.lightning_receiver import (
        PaymentEvent,
        _record_chronicle,
    )

    captured: list = []

    def fake_record(event):  # type: ignore[no-untyped-def]
        captured.append(event)

    event = PaymentEvent(
        rail="lightning",
        amount_sats=420,
        timestamp=datetime(2026, 5, 6, tzinfo=UTC),
        external_id="invoice-preserve",
    )
    with mock.patch("agents.payment_processors.lightning_receiver.record", fake_record):
        _record_chronicle(event)

    payload = captured[0].payload
    assert payload["rail"] == "lightning"
    assert payload["amount_sats"] == 420
    assert payload["external_id"] == "invoice-preserve"
    assert payload["salience"] == 0.95
