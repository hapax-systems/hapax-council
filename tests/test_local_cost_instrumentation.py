"""Tests for local-inference volume instrumentation (cost-efficiency).

Local models (Ollama embed, TabbyAPI/Command-R) emit token/call VOLUME — never
dollars. The cloud-$ cost path must stay untouched.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry

from agents.dmn.ollama import _extract_openai_usage
from agents.telemetry import condition_metrics as cm
from agents.telemetry.llm_call_span import llm_call_span


def _fresh_registry() -> CollectorRegistry:
    cm.reset_for_testing()
    reg = CollectorRegistry()
    cm._ensure_metrics(reg)
    return reg


def _total(reg: CollectorRegistry, name: str) -> float:
    return sum(s.value for metric in reg.collect() for s in metric.samples if s.name == name)


class TestTokenVolume:
    def test_record_tokens_increments_by_direction(self):
        reg = _fresh_registry()
        cm.record_llm_call_tokens(
            model="command-r", route="dmn-sensory", prompt_tokens=9, completion_tokens=7
        )
        assert _total(reg, "hapax_llm_tokens_total") == 16.0

    def test_zero_tokens_is_noop(self):
        reg = _fresh_registry()
        cm.record_llm_call_tokens(model="m", route="r", prompt_tokens=0, completion_tokens=0)
        assert _total(reg, "hapax_llm_tokens_total") == 0.0


class TestEmbedVolume:
    def test_record_embed_calls_and_chars(self):
        reg = _fresh_registry()
        cm.record_embed(model="nomic-embed-cpu", kind="batch", n_calls=4, input_chars=1234)
        assert _total(reg, "hapax_embed_calls_total") == 4.0
        assert _total(reg, "hapax_embed_input_chars_total") == 1234.0

    def test_embed_records_no_dollars(self):
        reg = _fresh_registry()
        cm.record_embed(model="nomic-embed-cpu", kind="single", n_calls=1, input_chars=10)
        # local volume must never touch the dollar cost counter
        assert _total(reg, "hapax_llm_call_cost_dollars_total") == 0.0


class TestSpanEmitsTokensNotCost:
    def test_set_tokens_emits_on_exit(self):
        reg = _fresh_registry()
        with llm_call_span(model="command-r", route="dmn-thinking") as span:
            span.set_tokens(prompt_tokens=100, completion_tokens=50)
        assert _total(reg, "hapax_llm_tokens_total") == 150.0
        # set_tokens must NOT emit dollars
        assert _total(reg, "hapax_llm_call_cost_dollars_total") == 0.0

    def test_cloud_cost_path_unchanged(self):
        # regression guard: set_cost still emits to the dollar counter, independent of tokens
        reg = _fresh_registry()
        with llm_call_span(model="claude-opus", route="reasoning") as span:
            span.set_cost(0.42)
        assert round(_total(reg, "hapax_llm_call_cost_dollars_total"), 3) == 0.42
        assert _total(reg, "hapax_llm_tokens_total") == 0.0


class TestExtractOpenAIUsage:
    def test_parses_tabbyapi_usage(self):
        data = {"usage": {"prompt_tokens": 9, "completion_tokens": 7, "total_tokens": 16}}
        assert _extract_openai_usage(data) == (9, 7)

    def test_missing_usage_is_zero(self):
        assert _extract_openai_usage({"choices": []}) == (0, 0)
        assert _extract_openai_usage({"usage": None}) == (0, 0)
        assert _extract_openai_usage({"usage": {"prompt_tokens": "bad"}}) == (0, 0)
