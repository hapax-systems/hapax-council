"""Tests for the awareness-side monetization source wiring."""

from __future__ import annotations

from datetime import UTC, datetime

from agents.operator_awareness.aggregator import Aggregator
from agents.operator_awareness.sources.monetization import (
    collect_monetization_block,
)
from agents.operator_awareness.state import PaymentEvent, write_state_atomic
from agents.payment_processors.event_log import append_event


def _make(ext: str, *, sats: int = 100) -> PaymentEvent:
    return PaymentEvent(
        timestamp=datetime.now(UTC),
        rail="lightning",
        amount_sats=sats,
        sender_excerpt="",
        external_id=ext,
    )


class TestCollectMonetizationBlock:
    def test_missing_log_returns_default_block(self, tmp_path):
        block = collect_monetization_block(tmp_path / "absent.jsonl")
        assert block.lightning_receipts_count == 0
        assert block.last_event is None

    def test_with_events(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make("L1", sats=100), log_path=path)
        block = collect_monetization_block(path)
        assert block.lightning_receipts_count == 1
        assert block.total_sats_received == 100


class TestAggregatorWiresMonetization:
    """Integration: the Aggregator.collect() path includes monetization."""

    def test_collect_includes_monetization(self, tmp_path):
        log_path = tmp_path / "events.jsonl"
        append_event(_make("L1", sats=300), log_path=log_path)
        agg = Aggregator(
            refusals_log_path=tmp_path / "refusals.jsonl",
            infra_snapshot_path=tmp_path / "infra.json",
            chronicle_events_path=tmp_path / "chronicle.jsonl",
            monetization_log_path=log_path,
        )
        state = agg.collect()
        assert state.monetization.lightning_receipts_count == 1
        assert state.monetization.total_sats_received == 300

    def test_state_serialises_monetization_to_json(self, tmp_path):
        """End-to-end: aggregator → state → /dev/shm-style atomic write."""
        log_path = tmp_path / "events.jsonl"
        append_event(_make("L1", sats=21), log_path=log_path)
        agg = Aggregator(
            refusals_log_path=tmp_path / "refusals.jsonl",
            infra_snapshot_path=tmp_path / "infra.json",
            chronicle_events_path=tmp_path / "chronicle.jsonl",
            monetization_log_path=log_path,
        )
        state = agg.collect()
        out = tmp_path / "state.json"
        assert write_state_atomic(state, out)
        import json

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["monetization"]["lightning_receipts_count"] == 1
        assert data["monetization"]["total_sats_received"] == 21
        assert data["monetization"]["surfaces_dot_grid_compact"] == "L:1 N:0 LP:0"
