"""Tests for the JSONL write-failure counter."""

from __future__ import annotations

import pytest

prometheus_client = pytest.importorskip("prometheus_client")

from shared.affordance_jsonl_write_metrics import (  # noqa: E402
    ALL_SINKS,
    KNOWN_SINKS,
    UNKNOWN_SINK,
    record_write_failure,
    write_failure_counter_value,
)


class TestCardinalityBound:
    def test_known_sinks_are_three(self) -> None:
        assert set(KNOWN_SINKS) == {
            "dispatch_trace",
            "recruitment_log",
            "perceptual_impingements",
        }

    def test_all_sinks_caps_at_four(self) -> None:
        assert ALL_SINKS == KNOWN_SINKS + (UNKNOWN_SINK,)
        assert len(ALL_SINKS) == 4


class TestRecordWriteFailure:
    @pytest.mark.parametrize("sink", KNOWN_SINKS)
    def test_known_sink_increments_its_label(self, sink: str) -> None:
        before = write_failure_counter_value(sink) or 0.0
        record_write_failure(sink)
        after = write_failure_counter_value(sink) or 0.0
        assert after - before == 1

    def test_unknown_sink_collapses_to_unknown(self) -> None:
        before = write_failure_counter_value(UNKNOWN_SINK) or 0.0
        record_write_failure("a_sink_we_have_not_seen_yet")
        after = write_failure_counter_value(UNKNOWN_SINK) or 0.0
        assert after - before == 1

    def test_increments_isolated_per_sink(self) -> None:
        before_d = write_failure_counter_value("dispatch_trace") or 0.0
        before_r = write_failure_counter_value("recruitment_log") or 0.0
        record_write_failure("dispatch_trace")
        record_write_failure("dispatch_trace")
        record_write_failure("recruitment_log")
        after_d = write_failure_counter_value("dispatch_trace") or 0.0
        after_r = write_failure_counter_value("recruitment_log") or 0.0
        assert after_d - before_d == 2
        assert after_r - before_r == 1


class TestPipelineWiring:
    def test_three_oserror_paths_all_call_record_write_failure(self) -> None:
        from pathlib import Path

        source = Path("shared/affordance_pipeline.py").read_text(encoding="utf-8")
        # Three OSError-swallow sites must all call record_write_failure
        # (one per JSONL sink).
        for sink in KNOWN_SINKS:
            assert f'record_write_failure("{sink}")' in source, (
                f"affordance_pipeline.py is missing record_write_failure({sink!r}) wire"
            )
