"""Tests for the guarded Tavily client."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.error import HTTPError

import pytest

from shared.tavily_client import (
    TavilyClient,
    TavilyConfig,
    TavilyConfigError,
    TavilyOperationConfig,
    TavilyStatePaths,
)


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _config(tmp_path: Path, **overrides) -> TavilyConfig:
    operations = overrides.pop(
        "operations",
        {
            "search": TavilyOperationConfig(True, 2, 1),
            "extract": TavilyOperationConfig(False, 0, 1),
        },
    )
    caller_daily_budgets = overrides.pop(
        "caller_daily_budgets",
        {
            "tests": 2,
            "default": 2,
        },
    )
    return TavilyConfig(
        state=TavilyStatePaths(
            cache_path=tmp_path / "cache.json",
            budget_path=tmp_path / "budget.json",
            ledger_path=tmp_path / "ledger.jsonl",
            lock_path=tmp_path / "state.lock",
        ),
        operations=operations,
        caller_daily_budgets=caller_daily_budgets,
        **overrides,
    )


def _ledger(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_default_config_loads_without_network_or_pass(tmp_path, monkeypatch):
    config_file = tmp_path / "tavily.yaml"
    config_file.write_text("state:\n  cache_path: '~/tmp-cache.json'\n")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    config = TavilyConfig.load(config_file)

    assert config.base_url == "https://api.tavily.com"
    assert config.operations["search"].enabled is True
    assert str(config.state.cache_path).endswith("tmp-cache.json")


def test_malformed_config_fails_closed(tmp_path):
    config_file = tmp_path / "tavily.yaml"
    config_file.write_text("operations: [not-a-map]\n")

    with pytest.raises(TavilyConfigError, match="operations must be a map"):
        TavilyConfig.load(config_file)


def test_invalid_scalar_config_fails_closed(tmp_path):
    config_file = tmp_path / "tavily.yaml"
    config_file.write_text("timeout_s: nope\noperations:\n  search:\n    enabled: 'false'\n")

    with pytest.raises(TavilyConfigError, match="enabled must be a boolean"):
        TavilyConfig.load(config_file)


def test_no_key_returns_no_key_without_http(tmp_path):
    called = False

    def opener(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("HTTP should not be called")

    client = TavilyClient(_config(tmp_path), opener=opener, key_loader=lambda: "")

    result = client.search("qdrant alternatives", caller="tests")

    assert result.status == "no_key"
    assert called is False
    ledger = _ledger(tmp_path / "ledger.jsonl")
    assert ledger[0]["status"] == "no_key"
    assert ledger[0]["estimated_cost_units"] == 0
    assert not (tmp_path / "budget.json").exists()


def test_env_key_path_sends_authorization_header(tmp_path):
    seen_headers = {}

    def opener(req, **_kwargs):
        seen_headers.update(dict(req.header_items()))
        return _Response(
            {
                "results": [
                    {
                        "title": "Result",
                        "url": "https://example.com",
                        "content": "Content",
                    }
                ]
            }
        )

    client = TavilyClient(_config(tmp_path), opener=opener, key_loader=lambda: "env-key")

    result = client.search("qdrant alternatives", caller="tests")

    assert result.status == "ok"
    assert result.results[0]["url"] == "https://example.com"
    assert seen_headers["Authorization"] == "Bearer env-key"


def test_cache_hit_avoids_http_and_writes_ledger(tmp_path):
    calls = 0

    def opener(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _Response(
            {
                "results": [
                    {
                        "title": "Cached",
                        "url": "https://example.com",
                        "content": "Content",
                    }
                ]
            }
        )

    client = TavilyClient(_config(tmp_path), opener=opener, key_loader=lambda: "key")

    first = client.search("same query", caller="tests")
    second = client.search("same query", caller="tests")

    assert first.status == "ok"
    assert second.status == "cache_hit"
    assert second.cache_hit is True
    assert calls == 1
    assert [row["status"] for row in _ledger(tmp_path / "ledger.jsonl")] == [
        "ok",
        "cache_hit",
    ]


def test_budget_exhaustion_avoids_http(tmp_path):
    calls = 0

    def opener(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _Response({"results": []})

    client = TavilyClient(
        _config(
            tmp_path,
            operations={"search": TavilyOperationConfig(True, 1, 1)},
            caller_daily_budgets={"tests": 1, "default": 1},
        ),
        opener=opener,
        key_loader=lambda: "key",
    )

    assert client.search("first", caller="tests").status == "ok"
    denied = client.search("second", caller="tests")

    assert denied.status == "over_budget"
    assert denied.error_class == "operation_daily_budget_exhausted"
    assert calls == 1


def test_guarded_payload_denial_avoids_http(tmp_path):
    client = TavilyClient(
        _config(tmp_path),
        opener=lambda *_args, **_kwargs: pytest.fail("HTTP should not be called"),
        key_loader=lambda: "key",
    )

    result = client.search("summarize /home/hapax/.ssh/id_rsa", caller="tests")

    assert result.status == "guard_denied"
    assert result.error_class == "local_path_payload"


def test_429_retries_then_succeeds(tmp_path):
    calls = 0

    def opener(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError("https://api.tavily.com/search", 429, "rate", {}, None)
        return _Response({"results": [{"title": "OK", "url": "https://ok", "content": ""}]})

    client = TavilyClient(
        _config(tmp_path), opener=opener, sleep=lambda _s: None, key_loader=lambda: "key"
    )

    result = client.search("retry me", caller="tests")

    assert result.status == "ok"
    assert calls == 2


def test_concurrent_calls_respect_configured_limit(tmp_path):
    active = 0
    max_active = 0
    lock = threading.Lock()

    def opener(*_args, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return _Response({"results": []})

    client = TavilyClient(
        _config(
            tmp_path,
            max_concurrent_requests=1,
            operations={"search": TavilyOperationConfig(True, 4, 1)},
            caller_daily_budgets={"tests": 4, "default": 4},
        ),
        opener=opener,
        key_loader=lambda: "key",
    )

    threads = [
        threading.Thread(target=client.search, args=(f"query {i}",), kwargs={"caller": "tests"})
        for i in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active == 1


def test_pass_fallback_loader_is_used_after_cache_and_budget(tmp_path):
    client = TavilyClient(
        _config(tmp_path),
        opener=lambda *_args, **_kwargs: _Response({"results": []}),
        key_loader=lambda: "pass-key",
    )

    assert client.search("uses pass loader", caller="tests").status == "ok"
