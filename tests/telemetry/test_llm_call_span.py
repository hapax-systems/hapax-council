"""Tests for agents.telemetry.llm_call_span."""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry


@pytest.fixture
def isolated_metrics(monkeypatch):
    """Fresh CollectorRegistry per test so we can read exact counters."""
    import agents.telemetry.condition_metrics as cm

    cm.reset_for_testing()
    registry = CollectorRegistry()
    cm._ensure_metrics(registry=registry)
    monkeypatch.setattr(
        "shared.research_condition.get_current_condition",
        lambda *_a, **_kw: "qwen3.5-9b-baseline",
    )
    yield cm
    cm.reset_for_testing()


class TestSuccessPath:
    def test_success_block_increments_calls_and_success_outcome(self, isolated_metrics):
        from agents.telemetry.llm_call_span import llm_call_span

        cm = isolated_metrics
        with llm_call_span(model="qwen3.5-9b", route="local-fast"):
            pass

        calls = cm._LLM_CALLS_TOTAL.labels(
            condition="qwen3.5-9b-baseline", model="qwen3.5-9b", route="local-fast"
        )._value.get()
        assert calls == 1

        success = cm._LLM_CALL_OUTCOMES_TOTAL.labels(
            condition="qwen3.5-9b-baseline",
            model="qwen3.5-9b",
            route="local-fast",
            outcome="success",
        )._value.get()
        assert success == 1

    def test_custom_outcome_overrides_default(self, isolated_metrics):
        from agents.telemetry.llm_call_span import llm_call_span

        cm = isolated_metrics
        with llm_call_span(model="qwen3.5-9b", route="local-fast") as span:
            span.set_outcome("refused")

        refused = cm._LLM_CALL_OUTCOMES_TOTAL.labels(
            condition="qwen3.5-9b-baseline",
            model="qwen3.5-9b",
            route="local-fast",
            outcome="refused",
        )._value.get()
        assert refused == 1


class TestErrorPath:
    def test_generic_exception_labels_as_error_and_propagates(self, isolated_metrics):
        from agents.telemetry.llm_call_span import llm_call_span

        cm = isolated_metrics
        with pytest.raises(RuntimeError):
            with llm_call_span(model="qwen3.5-9b", route="local-fast"):
                raise RuntimeError("boom")

        err = cm._LLM_CALL_OUTCOMES_TOTAL.labels(
            condition="qwen3.5-9b-baseline",
            model="qwen3.5-9b",
            route="local-fast",
            outcome="error",
        )._value.get()
        assert err == 1

    def test_timeout_error_labels_as_timeout(self, isolated_metrics):
        from agents.telemetry.llm_call_span import llm_call_span

        cm = isolated_metrics
        with pytest.raises(TimeoutError):
            with llm_call_span(model="qwen3.5-9b", route="local-fast"):
                raise TimeoutError("took too long")

        timeout = cm._LLM_CALL_OUTCOMES_TOTAL.labels(
            condition="qwen3.5-9b-baseline",
            model="qwen3.5-9b",
            route="local-fast",
            outcome="timeout",
        )._value.get()
        assert timeout == 1


class TestLatency:
    def test_latency_histogram_records_observation(self, isolated_metrics):
        from agents.telemetry.llm_call_span import llm_call_span

        cm = isolated_metrics
        with llm_call_span(model="m", route="r"):
            pass

        hist = cm._LLM_CALL_LATENCY_SECONDS.labels(
            condition="qwen3.5-9b-baseline", model="m", route="r"
        )
        # The histogram should have at least one sample
        assert hist._sum.get() >= 0
        total_count = sum(b.get() for b in hist._buckets)
        assert total_count >= 1
