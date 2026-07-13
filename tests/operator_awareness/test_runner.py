"""Tests for ``agents.operator_awareness.runner``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.operator_awareness.aggregator import Aggregator
from agents.operator_awareness.runner import AwarenessRunner
from agents.operator_awareness.state import AwarenessState


def _now() -> datetime:
    return datetime.now(UTC)


class TestRunOnce:
    def test_writes_state_to_path(self, tmp_path, monkeypatch):
        from agents.payment_processors import resource_receipts

        state = AwarenessState(timestamp=_now())
        agg = mock.Mock(spec=Aggregator)
        agg.collect.return_value = state
        agg.monetization_log_path = tmp_path / "events.jsonl"
        monkeypatch.setenv(
            resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
            str(tmp_path / "resource-receipts.jsonl"),
        )
        out = tmp_path / "state.json"
        runner = AwarenessRunner(aggregator=agg, state_path=out, registry=CollectorRegistry())
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
        runner = AwarenessRunner(aggregator=agg, state_path=out, registry=CollectorRegistry())
        result = runner.run_once()
        assert result == "aggregator_error"
        assert not out.exists()
        assert runner.writes_total.labels(result="aggregator_error")._value.get() == 1.0

    def test_write_failure_yields_error_label(self, tmp_path, monkeypatch):
        from agents.operator_awareness import runner as runner_mod
        from agents.payment_processors import resource_receipts
        from agents.payment_processors.resource_receipts import (
            MoneyRailReceiptOperation,
            tail_resource_receipts,
        )

        state = AwarenessState(timestamp=_now())
        agg = mock.Mock(spec=Aggregator)
        agg.collect.return_value = state
        agg.monetization_log_path = tmp_path / "events.jsonl"
        receipt_log = tmp_path / "resource-receipts.jsonl"
        monkeypatch.setenv(
            resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
            str(receipt_log),
        )
        runner = AwarenessRunner(
            aggregator=agg,
            state_path=tmp_path / "blocked" / "state.json",
            registry=CollectorRegistry(),
        )
        monkeypatch.setattr(runner_mod, "write_state_atomic", lambda *_args, **_kwargs: False)
        result = runner.run_once()
        assert result == "error"
        assert runner.writes_total.labels(result="error")._value.get() == 1.0
        receipts = tail_resource_receipts(log_path=receipt_log)
        assert len(receipts) == 1
        assert receipts[0].operation is MoneyRailReceiptOperation.AWARENESS_STATE_WRITE
        assert receipts[0].downstream_action == "operator_awareness.write_state_atomic"
        assert not (tmp_path / "blocked" / "state.json").exists()


class TestTickFloor:
    def test_tick_s_floor(self):
        runner = AwarenessRunner(tick_s=1.0, registry=CollectorRegistry())
        assert runner._tick_s >= 5.0


class TestSdNotifyIntegration:
    """sd_notify must be a no-op outside systemd; ready+watchdog under it."""

    def test_no_notifier_when_sdnotify_absent(self, monkeypatch):
        from agents.operator_awareness import runner as runner_mod

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
        from agents.operator_awareness import runner as runner_mod

        notifier = mock.Mock()
        monkeypatch.setattr(runner_mod, "_sd_notifier", notifier)
        runner_mod.sd_notify_ready()
        runner_mod.sd_notify_watchdog()
        assert notifier.notify.call_args_list == [
            mock.call("READY=1"),
            mock.call("WATCHDOG=1"),
        ]
