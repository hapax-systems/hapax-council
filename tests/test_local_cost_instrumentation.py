"""Tests for local-inference volume instrumentation (cost-efficiency).

Local models (Ollama embed, TabbyAPI/Command-R) emit token/call VOLUME — never
dollars. The cloud-$ cost path must stay untouched.
"""

from __future__ import annotations

import json
from multiprocessing import Event, Process
from pathlib import Path

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


def _set_capacity_paths(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "hapax-local-capacity.json"
    monkeypatch.setattr(cm, "LOCAL_CAPACITY_FILE", path)
    monkeypatch.setattr(cm, "LOCAL_CAPACITY_LEASE_DIR", tmp_path / "local-capacity-leases")
    return path


def _hold_local_capacity_span(file_path: str, lease_dir: str, ready: Event, release: Event) -> None:
    from agents.telemetry import condition_metrics as child_cm
    from agents.telemetry.llm_call_span import llm_call_span as child_llm_call_span

    child_cm.LOCAL_CAPACITY_FILE = Path(file_path)
    child_cm.LOCAL_CAPACITY_LEASE_DIR = Path(lease_dir)
    child_cm.LOCAL_CAPACITY_CEILING = 4.0
    child_cm.reset_for_testing()

    with child_llm_call_span(model="command-r", route="dmn-thinking"):
        ready.set()
        release.wait(5)


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
    def test_local_capacity_route_detection_boundaries(self):
        assert cm._is_local_capacity_route(model="claude-opus", route="local-fast")
        assert cm._is_local_capacity_route(model="claude-opus", route="dmn-thinking")
        assert cm._is_local_capacity_route(model="local-fast", route="conversation")
        assert cm._is_local_capacity_route(model="qwen2.5-coder", route="general")
        assert not cm._is_local_capacity_route(model="claude-opus", route="reasoning")

    def test_set_tokens_emits_on_exit(self):
        reg = _fresh_registry()
        with llm_call_span(model="command-r", route="dmn-thinking") as span:
            span.set_tokens(prompt_tokens=100, completion_tokens=50)
        assert _total(reg, "hapax_llm_tokens_total") == 150.0
        # set_tokens must NOT emit dollars
        assert _total(reg, "hapax_llm_call_cost_dollars_total") == 0.0

    def test_local_span_without_ttft_writes_neutral_capacity_snapshot(self, tmp_path, monkeypatch):
        path = _set_capacity_paths(tmp_path, monkeypatch)
        monkeypatch.setattr(cm, "LOCAL_CAPACITY_CEILING", 2.0)
        monkeypatch.setattr(cm, "LOCAL_CAPACITY_BASELINE_S", 0.01)
        _fresh_registry()

        with llm_call_span(model="command-r", route="dmn-thinking") as span:
            assert path.exists()
            active = json.loads(path.read_text(encoding="utf-8"))
            assert active["inflight"] == 1
            assert active["ceiling"] == 2.0
            span.set_tokens(prompt_tokens=10, completion_tokens=5)

        finished = json.loads(path.read_text(encoding="utf-8"))
        assert finished["inflight"] == 0
        assert finished["ttft_ewma_s"] == 0.0
        assert finished["ttft_ratio"] == 1.0

    def test_local_span_publishes_explicit_ttft_snapshot(self, tmp_path, monkeypatch):
        path = _set_capacity_paths(tmp_path, monkeypatch)
        monkeypatch.setattr(cm, "LOCAL_CAPACITY_BASELINE_S", 0.1)
        _fresh_registry()

        with llm_call_span(model="command-r", route="dmn-thinking") as span:
            span.set_ttft_seconds(0.25)

        finished = json.loads(path.read_text(encoding="utf-8"))
        assert finished["inflight"] == 0
        assert finished["ttft_ewma_s"] == 0.25
        assert finished["ttft_ratio"] == 2.5

    def test_pytest_default_local_capacity_file_is_suppressed(self, tmp_path, monkeypatch):
        path = tmp_path / "default-local-capacity.json"
        monkeypatch.setattr(cm, "LOCAL_CAPACITY_FILE", path)
        monkeypatch.setattr(cm, "LOCAL_CAPACITY_LEASE_DIR", tmp_path / "local-capacity-leases")
        monkeypatch.setattr(cm, "_DEFAULT_LOCAL_CAPACITY_FILE", path)
        _fresh_registry()

        with llm_call_span(model="command-r", route="dmn-thinking") as span:
            span.set_ttft_seconds(0.25)

        assert not path.exists()

    def test_cloud_span_does_not_write_capacity_snapshot(self, tmp_path, monkeypatch):
        path = _set_capacity_paths(tmp_path, monkeypatch)
        _fresh_registry()

        with llm_call_span(model="claude-opus", route="reasoning"):
            pass

        assert not path.exists()

    def test_local_capacity_snapshot_aggregates_process_leases(self, tmp_path, monkeypatch):
        path = _set_capacity_paths(tmp_path, monkeypatch)
        lease_dir = tmp_path / "local-capacity-leases"
        monkeypatch.setattr(cm, "LOCAL_CAPACITY_CEILING", 4.0)
        _fresh_registry()

        ready = Event()
        release = Event()
        proc = Process(
            target=_hold_local_capacity_span,
            args=(str(path), str(lease_dir), ready, release),
        )
        proc.start()
        try:
            assert ready.wait(5)
            with llm_call_span(model="command-r", route="dmn-thinking"):
                active = json.loads(path.read_text(encoding="utf-8"))
                assert active["inflight"] == 2
                assert active["ceiling"] == 4.0

            after_parent = json.loads(path.read_text(encoding="utf-8"))
            assert after_parent["inflight"] == 1
        finally:
            release.set()
            proc.join(5)
            if proc.is_alive():
                proc.terminate()
                proc.join(5)

        assert proc.exitcode == 0
        finished = json.loads(path.read_text(encoding="utf-8"))
        assert finished["inflight"] == 0

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
