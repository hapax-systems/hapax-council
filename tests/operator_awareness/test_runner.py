"""Tests for ``agents.operator_awareness.runner``."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.operator_awareness import runner as runner_mod
from agents.operator_awareness.aggregator import Aggregator
from agents.operator_awareness.state import AwarenessState, PaymentEvent
from agents.payment_processors import resource_receipts
from agents.payment_processors.event_log import append_event


def _now() -> datetime:
    return datetime.now(UTC)


class TestRunOnce:
    def test_writes_state_to_path(self, tmp_path, monkeypatch):

        state = AwarenessState(timestamp=_now())
        agg = mock.Mock(spec=Aggregator)
        agg.collect.return_value = state
        agg.monetization_log_path = tmp_path / "events.jsonl"
        monkeypatch.setenv(
            resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
            str(tmp_path / "resource-receipts.jsonl"),
        )
        out = tmp_path / "state.json"
        runner = runner_mod.AwarenessRunner(
            aggregator=agg, state_path=out, registry=CollectorRegistry()
        )
        result = runner.run_once()
        assert result == "ok"
        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["schema_version"] == 1
        assert runner.writes_total.labels(result="ok")._value.get() == 1.0

    def test_aggregator_exception_yields_label(self, tmp_path):
        agg = mock.Mock(spec=Aggregator)
        agg.collect.side_effect = RuntimeError("boom")
        agg.monetization_log_path = tmp_path / "events.jsonl"
        out = tmp_path / "state.json"
        runner = runner_mod.AwarenessRunner(
            aggregator=agg, state_path=out, registry=CollectorRegistry()
        )
        result = runner.run_once()
        assert result == "aggregator_error"
        assert not out.exists()
        assert runner.writes_total.labels(result="aggregator_error")._value.get() == 1.0

    def test_write_failure_yields_error_label(self, tmp_path, monkeypatch, caplog):

        state = AwarenessState(timestamp=_now())
        agg = mock.Mock(spec=Aggregator)
        agg.collect.return_value = state
        agg.monetization_log_path = tmp_path / "events.jsonl"
        receipt_log = tmp_path / "resource-receipts.jsonl"
        monkeypatch.setenv(
            resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
            str(receipt_log),
        )
        state_path = tmp_path / "blocked" / "state.json"
        runner = runner_mod.AwarenessRunner(
            aggregator=agg,
            state_path=state_path,
            registry=CollectorRegistry(),
        )
        monkeypatch.setattr(runner_mod, "write_state_atomic", lambda *_args, **_kwargs: False)
        with caplog.at_level(logging.WARNING, logger=runner_mod.__name__):
            result = runner.run_once()
        assert result == "error"
        assert runner.writes_total.labels(result="error")._value.get() == 1.0
        receipts = resource_receipts.tail_resource_receipts(log_path=receipt_log)
        assert len(receipts) == 1
        assert (
            receipts[0].operation
            is resource_receipts.MoneyRailReceiptOperation.AWARENESS_STATE_WRITE
        )
        assert receipts[0].downstream_action == "operator_awareness.write_state_atomic"
        assert not state_path.exists()
        # The post-receipt state-write failure warning is actionable: it names the
        # exact non-secret state target and its parent, is not mislabelled as a
        # receipt-log failure, and preserves the immutable admission-evidence line.
        assert "state write failed" in caplog.text
        assert str(state_path) in caplog.text
        assert str(state_path.parent) in caplog.text
        assert "not a receipt-log failure" in caplog.text
        assert "write permission and free space" in caplog.text
        assert str(state_path.with_suffix(".json.tmp.*")) in caplog.text
        assert "retry" in caplog.text
        assert "immutable admission evidence" in caplog.text

    def test_resource_receipt_missing_yields_error_label(self, tmp_path, monkeypatch, caplog):

        state = AwarenessState(timestamp=_now())
        agg = mock.Mock(spec=Aggregator)
        agg.collect.return_value = state
        agg.monetization_log_path = tmp_path / "events.jsonl"
        receipt_log = tmp_path / "resource-receipts.jsonl"
        monkeypatch.setenv(
            resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
            str(receipt_log),
        )
        state_path = tmp_path / "state.json"
        runner = runner_mod.AwarenessRunner(
            aggregator=agg, state_path=state_path, registry=CollectorRegistry()
        )
        # Force the committed-receipt precondition to fail so the block path runs.
        monkeypatch.setattr(
            runner_mod, "commit_prepared_resource_receipt", lambda _receipt, **_kwargs: None
        )
        with caplog.at_level(logging.WARNING, logger=runner_mod.__name__):
            result = runner.run_once()
        assert result == "resource_receipt_error"
        assert runner.writes_total.labels(result="resource_receipt_error")._value.get() == 1.0
        assert not state_path.exists()
        # The receipt-missing block warning emits the canonical resource-receipt
        # recovery guidance verbatim: exact target ledger path, env var, and the
        # action/claim ceiling (preserve valid committed receipts). It is distinct
        # from the state-write-failure guidance asserted above.
        assert "resource receipt missing" in caplog.text
        guidance = resource_receipts.resource_receipt_recovery_guidance(log_path=receipt_log)
        assert guidance in caplog.text
        assert str(receipt_log) in caplog.text
        assert "preserve valid committed receipts" in caplog.text
        assert "state write failed" not in caplog.text

    def test_held_payment_log_preserves_prior_state(self, tmp_path, monkeypatch, caplog):
        # A HELD (append in-flight) payment-event log is UNKNOWN, not zero: the
        # canonical writer must preserve the prior state.json and refuse to
        # receipt+write, so a transient HOLD never erases last-known money truth.
        state = AwarenessState(timestamp=_now())
        events_log = tmp_path / "events.jsonl"
        append_event(
            PaymentEvent(timestamp=_now(), rail="lightning", amount_sats=42, external_id="L1"),
            log_path=events_log,
        )
        # Inject a valid pre-append WAL/HOLD marker (start_offset at the confirmed
        # newline boundary) so the read is classified HELD, not empty.
        size = events_log.stat().st_size
        header = json.dumps(
            {
                "marker_version": 1,
                "target": str(events_log),
                "start_offset": size,
                "line_sha256": "a" * 64,
            }
        )
        events_log.with_name(events_log.name + ".hold").write_bytes((header + "\n").encode("utf-8"))

        agg = mock.Mock(spec=Aggregator)
        agg.collect.return_value = state
        agg.monetization_log_path = events_log
        receipt_log = tmp_path / "resource-receipts.jsonl"
        monkeypatch.setenv(resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV, str(receipt_log))
        out = tmp_path / "state.json"
        runner = runner_mod.AwarenessRunner(
            aggregator=agg, state_path=out, registry=CollectorRegistry()
        )
        with caplog.at_level(logging.WARNING, logger=runner_mod.__name__):
            result = runner.run_once()
        assert result == "payment_log_unavailable"
        assert not out.exists()  # prior state preserved (nothing written)
        # no awareness-write receipt committed on HOLD
        assert resource_receipts.tail_resource_receipts(log_path=receipt_log) == []
        assert runner.writes_total.labels(result="payment_log_unavailable")._value.get() == 1.0
        assert "preserving prior state" in caplog.text


class TestTickFloor:
    def test_tick_s_floor(self):
        runner = runner_mod.AwarenessRunner(tick_s=1.0, registry=CollectorRegistry())
        assert runner._tick_s >= 5.0


class TestSdNotifyIntegration:
    """sd_notify must be a no-op outside systemd; ready+watchdog under it."""

    def test_no_notifier_when_sdnotify_absent(self, monkeypatch):

        # Reset cache then force the import to fail.
        monkeypatch.setattr(runner_mod, "_sd_notifier", None)
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kw):
            if name == "sdnotify":
                raise ImportError("no sdnotify in test env")
            return real_import(name, *args, **kw)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        # Should not raise — silently no-op.
        runner_mod.sd_notify_ready()
        runner_mod.sd_notify_watchdog()
        # Cached negative — second call hits the cache, not import.
        assert runner_mod._sd_notifier is False

    def test_ready_and_watchdog_call_through(self, monkeypatch):

        notifier = mock.Mock()
        monkeypatch.setattr(runner_mod, "_sd_notifier", notifier)
        runner_mod.sd_notify_ready()
        runner_mod.sd_notify_watchdog()
        assert notifier.notify.call_args_list == [
            mock.call("READY=1"),
            mock.call("WATCHDOG=1"),
        ]
