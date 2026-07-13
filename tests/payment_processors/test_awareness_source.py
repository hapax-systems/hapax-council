"""Tests for the awareness-side monetization source wiring."""

from __future__ import annotations

from datetime import UTC, datetime

from prometheus_client import CollectorRegistry

from agents.operator_awareness.aggregator import Aggregator
from agents.operator_awareness.runner import AwarenessRunner
from agents.operator_awareness.sources.monetization import (
    collect_monetization_block,
)
from agents.operator_awareness.state import AwarenessState, PaymentEvent, write_state_atomic
from agents.payment_processors.event_log import append_event
from agents.payment_processors.resource_receipts import tail_resource_receipts


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


class TestAwarenessRunnerReceiptGate:
    def test_run_once_writes_resource_receipt_before_state(self, tmp_path, monkeypatch):
        import agents.payment_processors.resource_receipts as resource_receipts

        receipt_log = tmp_path / "resource-receipts.jsonl"
        monkeypatch.setenv(
            resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
            str(receipt_log),
        )
        log_path = tmp_path / "events.jsonl"
        state_path = tmp_path / "state.json"
        append_event(_make("L1", sats=21), log_path=log_path)
        runner = AwarenessRunner(
            aggregator=Aggregator(
                refusals_log_path=tmp_path / "refusals.jsonl",
                infra_snapshot_path=tmp_path / "infra.json",
                chronicle_events_path=tmp_path / "chronicle.jsonl",
                monetization_log_path=log_path,
            ),
            state_path=state_path,
            registry=CollectorRegistry(),
        )

        assert runner.run_once() == "ok"
        assert state_path.exists()
        receipts = tail_resource_receipts(log_path=receipt_log)
        assert len(receipts) == 1
        assert receipts[0].operation.value == "awareness_state_write"
        assert "route:agents.operator_awareness.runner" in receipts[0].route_provenance
        assert any(
            ref.startswith("payment_event_window_sha256:")
            for ref in receipts[0].resource_provenance
        )

    def test_run_once_uses_same_monetization_window_for_state_and_receipt(
        self, tmp_path, monkeypatch
    ):
        import agents.payment_processors.resource_receipts as resource_receipts

        receipt_log = tmp_path / "resource-receipts.jsonl"
        monkeypatch.setenv(
            resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
            str(receipt_log),
        )
        log_path = tmp_path / "events.jsonl"
        state_path = tmp_path / "state.json"
        append_event(_make("L1", sats=21), log_path=log_path)

        class _FakeAggregator:
            monetization_log_path = log_path
            captured_state_block = None

            def collect(self, *, monetization_block):
                self.captured_state_block = monetization_block
                return AwarenessState(
                    timestamp=datetime.now(UTC),
                    monetization=monetization_block,
                )

        aggregator = _FakeAggregator()
        runner = AwarenessRunner(
            aggregator=aggregator,  # type: ignore[arg-type]
            state_path=state_path,
            registry=CollectorRegistry(),
        )

        assert runner.run_once() == "ok"
        assert aggregator.captured_state_block is not None
        assert aggregator.captured_state_block.lightning_receipts_count == 1
        assert aggregator.captured_state_block.total_sats_received == 21
        receipt = tail_resource_receipts(log_path=receipt_log)[0]
        assert "receipt_count:1" in receipt.resource_provenance

    def test_run_once_fails_closed_when_resource_receipt_missing(self, tmp_path, monkeypatch):
        import agents.operator_awareness.runner as runner_mod

        monkeypatch.setattr(
            runner_mod,
            "commit_prepared_resource_receipt",
            lambda _receipt, **_kwargs: None,
        )
        log_path = tmp_path / "events.jsonl"
        state_path = tmp_path / "state.json"
        append_event(_make("L1", sats=21), log_path=log_path)
        runner = AwarenessRunner(
            aggregator=Aggregator(
                refusals_log_path=tmp_path / "refusals.jsonl",
                infra_snapshot_path=tmp_path / "infra.json",
                chronicle_events_path=tmp_path / "chronicle.jsonl",
                monetization_log_path=log_path,
            ),
            state_path=state_path,
            registry=CollectorRegistry(),
        )

        assert runner.run_once() == "resource_receipt_error"
        assert not state_path.exists()

    def test_run_once_preserves_receipt_when_state_write_fails(self, tmp_path, monkeypatch):
        import agents.operator_awareness.runner as runner_mod
        import agents.payment_processors.resource_receipts as resource_receipts

        receipt_log = tmp_path / "resource-receipts.jsonl"
        monkeypatch.setenv(
            resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
            str(receipt_log),
        )
        monkeypatch.setattr(runner_mod, "write_state_atomic", lambda *_args, **_kwargs: False)
        log_path = tmp_path / "events.jsonl"
        state_path = tmp_path / "state.json"
        append_event(_make("L1", sats=21), log_path=log_path)
        runner = AwarenessRunner(
            aggregator=Aggregator(
                refusals_log_path=tmp_path / "refusals.jsonl",
                infra_snapshot_path=tmp_path / "infra.json",
                chronicle_events_path=tmp_path / "chronicle.jsonl",
                monetization_log_path=log_path,
            ),
            state_path=state_path,
            registry=CollectorRegistry(),
        )

        assert runner.run_once() == "error"
        assert not state_path.exists()
        receipts = tail_resource_receipts(log_path=receipt_log)
        assert len(receipts) == 1
        assert receipts[0].operation.value == "awareness_state_write"
