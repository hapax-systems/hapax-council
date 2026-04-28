"""Tests for the shared Tavily client."""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from shared.tavily_client import (
    TavilyBudgetExceeded,
    TavilyClient,
    TavilyConfigError,
    TavilyCrawlRequest,
    TavilyExtractRequest,
    TavilyMapRequest,
    TavilyPolicyViolation,
    TavilyResearchRequest,
    TavilySearchRequest,
    load_tavily_api_key,
)


def _config(path: Path, *, lane_credits: int = 100, ttl: int = 86400) -> Path:
    path.write_text(
        "\n".join(
            [
                "monthly_credits: 1000",
                "monthly_reserve_credits: 0",
                "daily_nominal_credits: 100",
                "daily_p0_credits: 200",
                "lanes:",
                f"  scout_horizon: {lane_credits}",
                "defaults:",
                "  cache_ttl_s:",
                f"    search: {ttl}",
            ]
        )
    )
    return path


def _now() -> datetime:
    return datetime(2026, 4, 28, 12, 0, tzinfo=UTC)


def test_load_tavily_api_key_prefers_env(monkeypatch) -> None:
    monkeypatch.setattr("shared.tavily_client.pass_first_line", lambda name: "pass-token")

    assert load_tavily_api_key({"TAVILY_API_KEY": "env-token"}) == "env-token"


def test_load_tavily_api_key_falls_back_to_expected_pass_entries(monkeypatch) -> None:
    seen: list[str] = []

    def fake_pass_first_line(name: str) -> str:
        seen.append(name)
        return "pass-token" if name == "tavily/api-key" else ""

    monkeypatch.setattr("shared.tavily_client.pass_first_line", fake_pass_first_line)

    assert load_tavily_api_key({}) == "pass-token"
    assert seen == ["tavily/api-key"]


def test_malformed_config_fails_closed(tmp_path: Path) -> None:
    config = tmp_path / "tavily.yaml"
    config.write_text("- not\n- a\n- mapping\n")

    with pytest.raises(TavilyConfigError):
        TavilyClient(api_key="test-token", config_path=config)


def test_search_uses_bearer_project_header_and_records_redacted_ledger(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert body["query"] == "qdrant alternatives"
        assert "safe_search" not in body
        assert "api_key" not in body
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.headers["x-project-id"] == "hapax-scout_horizon"
        return httpx.Response(
            200,
            json={
                "query": body["query"],
                "results": [
                    {
                        "title": "Qdrant vs Milvus",
                        "url": "https://example.com",
                        "content": "Comparison",
                    }
                ],
                "usage": {"credits": 1},
            },
        )

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    response = client.search(TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon"))

    assert response.results[0].title == "Qdrant vs Milvus"
    assert response.usage.actual_credits == 1
    assert len(requests) == 1
    ledger = (tmp_path / "usage.jsonl").read_text()
    assert "qdrant alternatives" not in ledger
    assert "test-token" not in ledger
    assert "query_hash" in ledger


def test_unknown_lane_fails_closed_before_http(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP should not be called for an unconfigured lane")

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    with pytest.raises(TavilyConfigError, match="lane is not configured"):
        client.search(TavilySearchRequest(query="qdrant alternatives", lane="ad_hoc"))


def test_configured_bibliographic_people_guardrail_allows_public_citation_query(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path / "tavily.yaml", lane_credits=200)
    config.write_text(
        config.read_text()
        + "\n"
        + "\n".join(
            [
                "guardrails:",
                "  allow_public_bibliographic_people: true",
            ]
        )
        + "\n"
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"query": "q", "results": [], "usage": {"credits": 1}})

    client = TavilyClient(
        api_key="test-token",
        config_path=config,
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    client.search(
        TavilySearchRequest(
            query="ORCID publication record for researcher@example.org",
            lane="scout_horizon",
        )
    )

    assert len(seen) == 1


def test_default_bibliographic_people_guardrail_rejects_email_query(tmp_path: Path) -> None:
    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
        now=_now,
    )

    with pytest.raises(TavilyPolicyViolation):
        client.search(
            TavilySearchRequest(
                query="ORCID publication record for researcher@example.org",
                lane="scout_horizon",
            )
        )


def test_safe_search_is_forwarded_only_when_enabled_for_supported_depth(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["safe_search"] is True
        return httpx.Response(200, json={"query": body["query"], "results": [], "usage": {}})

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    response = client.search(
        TavilySearchRequest(
            query="qdrant alternatives",
            lane="scout_horizon",
            safe_search=True,
        )
    )

    assert response.usage.estimated_credits == 1


def test_safe_search_rejects_unsupported_fast_depth_before_http(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP should not be called for unsupported safe_search")

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    with pytest.raises(TavilyPolicyViolation):
        client.search(
            TavilySearchRequest(
                query="qdrant alternatives",
                lane="scout_horizon",
                search_depth="fast",
                safe_search=True,
            )
        )


def test_search_cache_hit_avoids_http_and_records_zero_actual_credits(tmp_path: Path) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "query": "qdrant alternatives",
                "results": [],
                "usage": {"credits": 1},
            },
        )

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    first = client.search(TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon"))
    second = client.search(TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon"))

    assert first.usage.cache_hit is False
    assert second.usage.cache_hit is True
    assert second.usage.actual_credits == 0
    assert call_count == 1


def test_lane_cache_ttl_overrides_endpoint_default(tmp_path: Path) -> None:
    config = tmp_path / "tavily.yaml"
    config.write_text(
        "\n".join(
            [
                "monthly_credits: 1000",
                "monthly_reserve_credits: 0",
                "daily_nominal_credits: 100",
                "daily_p0_credits: 200",
                "lanes:",
                "  scout_horizon: 100",
                "defaults:",
                "  cache_ttl_s:",
                "    search: 1",
                "lane_cache_ttl_s:",
                "  scout_horizon:",
                "    search: 60",
            ]
        )
    )
    current = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
    call_count = 0

    def now() -> datetime:
        return current

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        body = json.loads(request.content)
        return httpx.Response(200, json={"query": body["query"], "results": [], "usage": {}})

    client = TavilyClient(
        api_key="test-token",
        config_path=config,
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=now,
    )

    first = client.search(TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon"))
    current += timedelta(seconds=2)
    second = client.search(TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon"))

    assert first.usage.cache_hit is False
    assert second.usage.cache_hit is True
    assert call_count == 1


def test_budget_exhaustion_happens_before_http(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP should not be called after budget exhaustion")

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=1),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    with pytest.raises(TavilyBudgetExceeded):
        client.search(
            TavilySearchRequest(
                query="qdrant alternatives",
                lane="scout_horizon",
                search_depth="advanced",
            )
        )
    ledger = (tmp_path / "usage.jsonl").read_text()
    assert "budget_denied" in ledger
    assert "qdrant alternatives" not in ledger


def test_auto_parameters_cost_two_credits_before_http(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP should not be called after budget exhaustion")

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=1),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    with pytest.raises(TavilyBudgetExceeded):
        client.search(
            TavilySearchRequest(
                query="qdrant alternatives",
                lane="scout_horizon",
                auto_parameters=True,
            )
        )


def test_open_reservations_count_against_budget(tmp_path: Path) -> None:
    ledger = tmp_path / "usage.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "timestamp": _now().isoformat(),
                "request_id": "in-flight",
                "status": "reserved",
                "lane": "scout_horizon",
                "estimated_credits": 1,
                "actual_credits": 0,
            }
        )
        + "\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP should not be called when an in-flight reservation fills budget")

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=1),
        cache_dir=tmp_path / "cache",
        ledger_path=ledger,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    with pytest.raises(TavilyBudgetExceeded):
        client.search(TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon"))


def test_stale_reservations_do_not_count_against_budget(tmp_path: Path) -> None:
    ledger = tmp_path / "usage.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "timestamp": (_now() - timedelta(hours=1)).isoformat(),
                "request_id": "stale-in-flight",
                "status": "reserved",
                "lane": "scout_horizon",
                "estimated_credits": 1,
                "actual_credits": 0,
            }
        )
        + "\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"query": body["query"], "results": [], "usage": {}})

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=1),
        cache_dir=tmp_path / "cache",
        ledger_path=ledger,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    response = client.search(TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon"))

    assert response.usage.estimated_credits == 1


def test_5xx_retries_before_recording_success(tmp_path: Path) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503, request=request, json={"error": "busy"})
        body = json.loads(request.content)
        return httpx.Response(200, json={"query": body["query"], "results": [], "usage": {}})

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    response = client.search(TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon"))

    assert response.results == []
    assert call_count == 2
    statuses = [
        json.loads(line)["status"] for line in (tmp_path / "usage.jsonl").read_text().splitlines()
    ]
    assert statuses == ["reserved", "ok"]


def test_request_errors_retry_before_recording_success(tmp_path: Path) -> None:
    config = _config(tmp_path / "tavily.yaml", lane_credits=200)
    with config.open("a") as fh:
        fh.write("\nmax_retries: 1\nretry_base_delay_s: 0\n")
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError("temporary network failure", request=request)
        body = json.loads(request.content)
        return httpx.Response(200, json={"query": body["query"], "results": [], "usage": {}})

    client = TavilyClient(
        api_key="test-token",
        config_path=config,
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    response = client.search(TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon"))

    assert response.results == []
    assert call_count == 2
    statuses = [
        json.loads(line)["status"] for line in (tmp_path / "usage.jsonl").read_text().splitlines()
    ]
    assert statuses == ["reserved", "ok"]


def test_identical_concurrent_cache_misses_are_single_flight(tmp_path: Path) -> None:
    call_count = 0
    calls_lock = threading.Lock()
    http_started = threading.Event()
    release_http = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        with calls_lock:
            call_count += 1
        http_started.set()
        assert release_http.wait(timeout=2)
        body = json.loads(request.content)
        return httpx.Response(200, json={"query": body["query"], "results": [], "usage": {}})

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )
    request = TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.search, request)
        assert http_started.wait(timeout=2)
        second = executor.submit(client.search, request)
        time.sleep(0.05)
        with calls_lock:
            assert call_count == 1
        release_http.set()
        first_response = first.result(timeout=2)
        second_response = second.result(timeout=2)

    assert first_response.usage.cache_hit is False
    assert second_response.usage.cache_hit is True
    assert call_count == 1


def test_cross_process_concurrency_slot_blocks_http_until_available(tmp_path: Path) -> None:
    config = _config(tmp_path / "tavily.yaml", lane_credits=200)
    with config.open("a") as fh:
        fh.write("\nmax_concurrent_requests: 1\n")
    lock_dir = tmp_path / "locks"
    slot_dir = lock_dir / "concurrency"
    slot_dir.mkdir(parents=True)
    slot_fd = os.open(str(slot_dir / "slot.0"), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(slot_fd, fcntl.LOCK_EX)
    http_started = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        http_started.set()
        body = json.loads(request.content)
        return httpx.Response(200, json={"query": body["query"], "results": [], "usage": {}})

    client = TavilyClient(
        api_key="test-token",
        config_path=config,
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        lock_dir=lock_dir,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            client.search,
            TavilySearchRequest(query="qdrant alternatives", lane="scout_horizon"),
        )
        time.sleep(0.05)
        assert not http_started.is_set()
        fcntl.flock(slot_fd, fcntl.LOCK_UN)
        os.close(slot_fd)
        response = future.result(timeout=2)

    assert response.results == []
    assert http_started.is_set()


def test_empty_search_results_are_successful_response(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"query": "unlikely query", "results": [], "usage": {"credits": 1}}
        )

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml"),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    response = client.search(TavilySearchRequest(query="unlikely query", lane="scout_horizon"))

    assert response.results == []
    assert response.usage.actual_credits == 1


def test_fast_search_depth_is_valid_and_costs_one_credit(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["search_depth"] == "fast"
        return httpx.Response(200, json={"query": body["query"], "results": [], "usage": {}})

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml"),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    response = client.search(
        TavilySearchRequest(
            query="latest qdrant release", lane="scout_horizon", search_depth="fast"
        )
    )

    assert response.usage.estimated_credits == 1


def test_research_payload_uses_input_field(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "input" in body
        assert "query" not in body
        assert body["input"] == "latest vector databases"
        return httpx.Response(
            201,
            json={"request_id": "r1", "status": "pending", "usage": {"credits": 4}},
        )

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    response = client.create_research(
        TavilyResearchRequest(query="latest vector databases", lane="scout_horizon", p0=True)
    )

    assert response.data["request_id"] == "r1"
    ledger = (tmp_path / "usage.jsonl").read_text()
    assert "latest vector databases" not in ledger
    assert "input_hash" in ledger


def test_usage_endpoint_uses_get_and_project_header(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/usage"
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.headers["x-project-id"] == "hapax-usage"
        return httpx.Response(
            200,
            json={
                "key": {"usage": 12, "limit": 150000, "search_usage": 3},
                "account": {"usage": 24, "limit": 150000, "research_usage": 4},
            },
        )

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml"),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    response = client.usage()

    assert response.key.usage == 12
    assert response.account.research_usage == 4
    assert not (tmp_path / "usage.jsonl").exists()


def test_extract_map_and_crawl_forward_supported_options(tmp_path: Path) -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_paths.append(request.url.path)
        if request.url.path == "/extract":
            assert body["urls"] == ["https://docs.tavily.com"]
            assert body["query"] == "usage endpoint"
            assert body["include_favicon"] is True
        elif request.url.path == "/map":
            assert body["select_domains"] == ["docs.tavily.com"]
            assert body["select_paths"] == ["/documentation/.*"]
        elif request.url.path == "/crawl":
            assert body["select_domains"] == ["docs.tavily.com"]
            assert body["select_paths"] == ["/documentation/.*"]
            assert body["include_images"] is True
        else:
            raise AssertionError(f"unexpected path {request.url.path}")
        return httpx.Response(200, json={"results": [], "usage": {}})

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    client.extract(
        TavilyExtractRequest(
            urls=["https://docs.tavily.com"],
            lane="scout_horizon",
            query="usage endpoint",
            include_favicon=True,
        )
    )
    client.map(
        TavilyMapRequest(
            url="https://docs.tavily.com",
            lane="scout_horizon",
            select_domains=["docs.tavily.com"],
            select_paths=["/documentation/.*"],
        )
    )
    client.crawl(
        TavilyCrawlRequest(
            url="https://docs.tavily.com",
            lane="scout_horizon",
            select_domains=["docs.tavily.com"],
            select_paths=["/documentation/.*"],
            include_images=True,
        )
    )

    assert seen_paths == ["/extract", "/map", "/crawl"]


def test_extract_map_and_crawl_validate_free_text_before_http(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP should not be called after text guardrail failure")

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml", lane_credits=200),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    with pytest.raises(TavilyPolicyViolation):
        client.extract(
            TavilyExtractRequest(
                urls=["https://docs.tavily.com"],
                lane="scout_horizon",
                query="from: private email thread",
            )
        )
    with pytest.raises(TavilyPolicyViolation):
        client.map(
            TavilyMapRequest(
                url="https://docs.tavily.com",
                lane="scout_horizon",
                instructions="meeting transcript about roadmap",
            )
        )
    with pytest.raises(TavilyPolicyViolation):
        client.crawl(
            TavilyCrawlRequest(
                url="https://docs.tavily.com",
                lane="scout_horizon",
                instructions="internal only release details",
            )
        )


def test_auto_research_requires_p0_budget_lane(tmp_path: Path) -> None:
    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml"),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
        now=_now,
    )

    with pytest.raises(TavilyBudgetExceeded):
        client.create_research(TavilyResearchRequest(query="broad AI landscape", model="auto"))


def test_map_and_crawl_estimates_are_conservative_for_limit(tmp_path: Path) -> None:
    seen_estimates: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [], "usage": {}})

    client = TavilyClient(
        api_key="test-token",
        config_path=_config(tmp_path / "tavily.yaml"),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "usage.jsonl",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=_now,
    )

    mapped = client.map(
        TavilyMapRequest(
            url="https://docs.tavily.com",
            lane="scout_horizon",
            limit=25,
            instructions="Find API pages",
        )
    )
    crawled = client.crawl(
        TavilyCrawlRequest(
            url="https://docs.tavily.com",
            lane="scout_horizon",
            limit=12,
            extract_depth="advanced",
        )
    )

    seen_estimates.extend([mapped.usage.estimated_credits, crawled.usage.estimated_credits])
    assert seen_estimates == [6, 8]
