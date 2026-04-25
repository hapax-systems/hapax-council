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
    def test_writes_state_to_path(self, tmp_path):
        state = AwarenessState(timestamp=_now())
        agg = mock.Mock(spec=Aggregator)
        agg.collect.return_value = state
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
        out = tmp_path / "state.json"
        runner = AwarenessRunner(aggregator=agg, state_path=out, registry=CollectorRegistry())
        result = runner.run_once()
        assert result == "aggregator_error"
        assert not out.exists()
        assert runner.writes_total.labels(result="aggregator_error")._value.get() == 1.0

    def test_write_failure_yields_error_label(self, tmp_path, monkeypatch):
        state = AwarenessState(timestamp=_now())
        agg = mock.Mock(spec=Aggregator)
        agg.collect.return_value = state
        runner = AwarenessRunner(
            aggregator=agg,
            state_path=tmp_path / "blocked" / "state.json",
            registry=CollectorRegistry(),
        )
        # Force write_state_atomic to fail by making the parent unwritable.
        from pathlib import Path as _Path

        def _fail_mkdir(*_a, **_k):
            raise OSError("read-only")

        monkeypatch.setattr(_Path, "mkdir", _fail_mkdir)
        result = runner.run_once()
        assert result == "error"
        assert runner.writes_total.labels(result="error")._value.get() == 1.0


class TestTickFloor:
    def test_tick_s_floor(self):
        runner = AwarenessRunner(tick_s=1.0, registry=CollectorRegistry())
        assert runner._tick_s >= 5.0
