"""Tests for ``agents.payment_processors.monetization_aggregator``."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from agents.operator_awareness.state import (
    AwarenessState,
    PaymentEvent,
    write_state_atomic,
)
from agents.payment_processors.event_log import append_event
from agents.payment_processors.monetization_aggregator import (
    build_monetization_block,
)


def _make(
    rail: str, *, ext: str, sats: int | None = None, eur: float | None = None
) -> PaymentEvent:
    return PaymentEvent(
        timestamp=datetime.now(UTC),
        rail=rail,  # type: ignore[arg-type]
        amount_sats=sats,
        amount_eur=eur,
        sender_excerpt="",
        external_id=ext,
    )


class TestBuildMonetizationBlock:
    def test_empty_log_returns_default_block(self, tmp_path):
        block = build_monetization_block(log_path=tmp_path / "absent.jsonl")
        assert block.lightning_receipts_count == 0
        assert block.nostr_zap_receipts_count == 0
        assert block.liberapay_receipts_count == 0
        assert block.last_event is None
        assert block.public is False

    def test_counts_per_rail(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make("lightning", ext="L1", sats=100), log_path=path)
        append_event(_make("lightning", ext="L2", sats=200), log_path=path)
        append_event(_make("nostr_zap", ext="N1", sats=50), log_path=path)
        append_event(_make("liberapay", ext="P1", eur=5.0), log_path=path)
        block = build_monetization_block(log_path=path)
        assert block.lightning_receipts_count == 2
        assert block.nostr_zap_receipts_count == 1
        assert block.liberapay_receipts_count == 1
        assert block.total_sats_received == 350
        assert block.total_eur_received == 5.0

    def test_dedupes_on_external_id(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make("lightning", ext="L1", sats=100), log_path=path)
        append_event(_make("lightning", ext="L1", sats=100), log_path=path)
        block = build_monetization_block(log_path=path)
        assert block.lightning_receipts_count == 1
        assert block.total_sats_received == 100

    def test_grid_string(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make("lightning", ext="L1"), log_path=path)
        append_event(_make("lightning", ext="L2"), log_path=path)
        append_event(_make("nostr_zap", ext="N1"), log_path=path)
        block = build_monetization_block(log_path=path)
        assert block.surfaces_dot_grid_compact == "L:2 N:1 LP:0"

    def test_last_event_is_newest(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make("lightning", ext="L1"), log_path=path)
        append_event(_make("nostr_zap", ext="N1"), log_path=path)
        block = build_monetization_block(log_path=path)
        assert block.last_event is not None
        assert block.last_event.external_id == "N1"

    def test_public_flag_propagates(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make("lightning", ext="L1"), log_path=path)
        block = build_monetization_block(log_path=path, public=True)
        assert block.public is True


class TestStateJsonRoundTrip:
    """End-to-end: write awareness state including monetization block,
    parse the JSON, confirm shape."""

    def test_state_json_contains_monetization(self, tmp_path):
        log_path = tmp_path / "events.jsonl"
        append_event(_make("lightning", ext="L1", sats=42), log_path=log_path)
        block = build_monetization_block(log_path=log_path)
        state = AwarenessState(timestamp=datetime.now(UTC), monetization=block)
        out_path = tmp_path / "state.json"
        assert write_state_atomic(state, out_path)
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert "monetization" in data
        m = data["monetization"]
        assert m["lightning_receipts_count"] == 1
        assert m["total_sats_received"] == 42
        assert m["surfaces_dot_grid_compact"] == "L:1 N:0 LP:0"
        assert m["public"] is False
