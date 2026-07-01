"""Tests for ``agents.payment_processors.monetization_aggregator``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

from agents.operator_awareness.state import (
    AwarenessState,
    PaymentEvent,
    write_state_atomic,
)
from agents.payment_processors.event_log import append_event
from agents.payment_processors.monetization_aggregator import (
    MonetizationAggregator,
    build_monetization_block,
)
from agents.payment_processors.resource_receipts import tail_resource_receipts


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


class TestAwarenessWriteReceipts:
    def test_flush_writes_resource_receipt_before_state(self, tmp_path, monkeypatch):
        receipt_log = tmp_path / "resource-receipts.jsonl"
        import agents.payment_processors.resource_receipts as resource_receipts

        monkeypatch.setattr(
            resource_receipts,
            "DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH",
            receipt_log,
        )
        log_path = tmp_path / "events.jsonl"
        state_path = tmp_path / "state.json"
        append_event(_make("lightning", ext="L1", sats=42), log_path=log_path)
        aggregator = MonetizationAggregator(
            lightning=MagicMock(),
            nostr=MagicMock(),
            liberapay=MagicMock(),
            state_path=state_path,
            log_path=log_path,
            aggregate_tick_s=5.0,
        )

        assert aggregator.flush_awareness_block() is True
        assert state_path.exists()
        receipts = tail_resource_receipts(log_path=receipt_log)
        assert len(receipts) == 1
        assert receipts[0].operation.value == "awareness_state_write"
        assert receipts[0].spend_authority_granted is False
        assert any(
            ref.startswith("payment_event_window_sha256:")
            for ref in receipts[0].resource_provenance
        )

    def test_flush_fails_closed_when_resource_receipt_missing(self, tmp_path, monkeypatch):
        import agents.payment_processors.monetization_aggregator as aggregator_mod

        monkeypatch.setattr(
            aggregator_mod,
            "record_awareness_write_resource_receipt",
            lambda **_kwargs: None,
        )
        log_path = tmp_path / "events.jsonl"
        state_path = tmp_path / "state.json"
        append_event(_make("lightning", ext="L1", sats=42), log_path=log_path)
        aggregator = MonetizationAggregator(
            lightning=MagicMock(),
            nostr=MagicMock(),
            liberapay=MagicMock(),
            state_path=state_path,
            log_path=log_path,
            aggregate_tick_s=5.0,
        )

        assert aggregator.flush_awareness_block() is False
        assert not state_path.exists()
