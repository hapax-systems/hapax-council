"""vision-cost-guard-prometheus-emitter — cost counter + span integration.

cc-task `vision-cost-guard-prometheus-emitter`. Tests:

  * `record_llm_call_cost` increments the cost counter with the right labels
  * Zero / negative / NaN / None cost is a no-op (no counter emission)
  * `LlmCallSpan.set_cost` records cost; emitted on span exit
  * `set_cost(None)` (default) → no cost emission
  * `_extract_litellm_response_cost` handles dict-shaped, attr-shaped,
    and missing _hidden_params
  * Integration: span block + set_cost during block → cost in counter
"""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry


@pytest.fixture
def fresh_metrics(monkeypatch):
    """Give each test a fresh CollectorRegistry; patch condition to known value."""
    import agents.telemetry.condition_metrics as cm

    cm.reset_for_testing()
    registry = CollectorRegistry()
    cm._ensure_metrics(registry=registry)
    monkeypatch.setattr(
        "shared.research_condition.get_current_condition",
        lambda *_a, **_kw: "test-condition",
    )
    yield cm
    cm.reset_for_testing()


def _cost_value(cm, model: str, route: str) -> float:
    """Read the current value of the cost counter for the given labels."""
    return cm._LLM_CALL_COST_DOLLARS_TOTAL.labels(
        condition="test-condition", model=model, route=route
    )._value.get()


# ── record_llm_call_cost ────────────────────────────────────────────


class TestRecordLlmCallCost:
    def test_positive_cost_increments_counter(self, fresh_metrics) -> None:
        cm = fresh_metrics
        cm.record_llm_call_cost(model="m", route="r", cost_dollars=0.00014)
        assert _cost_value(cm, "m", "r") == pytest.approx(0.00014)

    def test_repeated_calls_accumulate(self, fresh_metrics) -> None:
        cm = fresh_metrics
        cm.record_llm_call_cost(model="m", route="r", cost_dollars=0.00014)
        cm.record_llm_call_cost(model="m", route="r", cost_dollars=0.00014)
        cm.record_llm_call_cost(model="m", route="r", cost_dollars=0.00010)
        assert _cost_value(cm, "m", "r") == pytest.approx(0.00038)

    def test_zero_cost_no_op(self, fresh_metrics) -> None:
        cm = fresh_metrics
        cm.record_llm_call_cost(model="m", route="r", cost_dollars=0.0)
        assert _cost_value(cm, "m", "r") == 0.0

    def test_negative_cost_no_op(self, fresh_metrics) -> None:
        cm = fresh_metrics
        cm.record_llm_call_cost(model="m", route="r", cost_dollars=-0.5)
        assert _cost_value(cm, "m", "r") == 0.0

    def test_none_cost_no_op(self, fresh_metrics) -> None:
        cm = fresh_metrics
        cm.record_llm_call_cost(model="m", route="r", cost_dollars=None)
        assert _cost_value(cm, "m", "r") == 0.0

    def test_nan_cost_no_op(self, fresh_metrics) -> None:
        cm = fresh_metrics
        cm.record_llm_call_cost(model="m", route="r", cost_dollars=float("nan"))
        assert _cost_value(cm, "m", "r") == 0.0

    def test_different_routes_distinct_label_sets(self, fresh_metrics) -> None:
        cm = fresh_metrics
        cm.record_llm_call_cost(model="m", route="r1", cost_dollars=0.001)
        cm.record_llm_call_cost(model="m", route="r2", cost_dollars=0.002)
        assert _cost_value(cm, "m", "r1") == pytest.approx(0.001)
        assert _cost_value(cm, "m", "r2") == pytest.approx(0.002)


# ── LlmCallSpan.set_cost integration ─────────────────────────────────


class TestSpanCostIntegration:
    def test_set_cost_during_block_emits_on_exit(self, fresh_metrics) -> None:
        from agents.telemetry.llm_call_span import llm_call_span

        with llm_call_span(model="m", route="r") as span:
            span.set_cost(0.00014)
        assert _cost_value(fresh_metrics, "m", "r") == pytest.approx(0.00014)

    def test_no_set_cost_no_emission(self, fresh_metrics) -> None:
        from agents.telemetry.llm_call_span import llm_call_span

        with llm_call_span(model="m", route="r"):
            pass  # never called set_cost
        assert _cost_value(fresh_metrics, "m", "r") == 0.0

    def test_set_cost_none_no_emission(self, fresh_metrics) -> None:
        from agents.telemetry.llm_call_span import llm_call_span

        with llm_call_span(model="m", route="r") as span:
            span.set_cost(None)
        assert _cost_value(fresh_metrics, "m", "r") == 0.0

    def test_set_cost_zero_no_emission(self, fresh_metrics) -> None:
        from agents.telemetry.llm_call_span import llm_call_span

        with llm_call_span(model="m", route="r") as span:
            span.set_cost(0.0)
        assert _cost_value(fresh_metrics, "m", "r") == 0.0

    def test_set_cost_emits_even_on_exception(self, fresh_metrics) -> None:
        """Span exit fires in finally — cost should emit even if block raises."""
        from agents.telemetry.llm_call_span import llm_call_span

        with pytest.raises(ValueError):
            with llm_call_span(model="m", route="r") as span:
                span.set_cost(0.00014)
                raise ValueError("synthetic")
        assert _cost_value(fresh_metrics, "m", "r") == pytest.approx(0.00014)


# ── _extract_litellm_response_cost ──────────────────────────────────


class _FakeRespDictHidden:
    def __init__(self, cost: float | None) -> None:
        self._hidden_params = {"_response_cost": cost} if cost is not None else {}


class _FakeRespAttrHidden:
    class _Hidden:
        pass

    def __init__(self, cost: float | None) -> None:
        self._hidden_params = self._Hidden()
        if cost is not None:
            self._hidden_params._response_cost = cost


class _FakeRespNoHidden:
    pass


class TestExtractLitellmResponseCost:
    def test_dict_shape_with_cost(self) -> None:
        from agents.dmn.ollama import _extract_litellm_response_cost

        assert _extract_litellm_response_cost(_FakeRespDictHidden(0.00014)) == pytest.approx(
            0.00014
        )

    def test_attr_shape_with_cost(self) -> None:
        from agents.dmn.ollama import _extract_litellm_response_cost

        assert _extract_litellm_response_cost(_FakeRespAttrHidden(0.00014)) == pytest.approx(
            0.00014
        )

    def test_missing_hidden_returns_none(self) -> None:
        from agents.dmn.ollama import _extract_litellm_response_cost

        assert _extract_litellm_response_cost(_FakeRespNoHidden()) is None

    def test_dict_shape_missing_cost_key_returns_none(self) -> None:
        from agents.dmn.ollama import _extract_litellm_response_cost

        # Dict with _hidden_params but no _response_cost key.
        class _R:
            _hidden_params = {"some_other_key": 1}

        assert _extract_litellm_response_cost(_R()) is None

    def test_attr_shape_missing_cost_attr_returns_none(self) -> None:
        from agents.dmn.ollama import _extract_litellm_response_cost

        # _hidden_params attr exists but _response_cost not set.
        class _Hidden:
            pass

        class _R:
            _hidden_params = _Hidden()

        assert _extract_litellm_response_cost(_R()) is None

    def test_non_numeric_cost_returns_none(self) -> None:
        from agents.dmn.ollama import _extract_litellm_response_cost

        # cost is a string; float() raises ValueError → caught.
        class _R:
            _hidden_params = {"_response_cost": "not-a-number"}

        assert _extract_litellm_response_cost(_R()) is None
