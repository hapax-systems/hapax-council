"""Tests for agents/scout.py — horizon scanner for external fitness evaluation.

All I/O mocked: Langfuse, Tavily HTTP, filesystem, LLM calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import yaml

from agents.scout import (
    ComponentSpec,
    Finding,
    Recommendation,
    ScoutReport,
    _build_usage_map,
    _tavily_search,
    format_report_human,
    format_report_md,
    load_registry,
    search_component,
    send_notification,
)

# ── Registry tests ──────────────────────────────────────────────────────────

SAMPLE_REGISTRY = {
    "components": {
        "vector-database": {
            "role": "Vector storage for embeddings",
            "current": "Qdrant",
            "provider": "qdrant.tech",
            "constraints": ["Must support filtering", "Docker-deployable"],
            "preferences": ["Low resource usage"],
            "search_hints": ["qdrant vs alternatives 2026"],
            "eval_notes": "Migration would require re-indexing",
        },
        "llm-gateway": {
            "role": "API proxy for all model calls",
            "current": "LiteLLM",
            "provider": "litellm.ai",
            "constraints": ["OpenAI-compatible API"],
            "preferences": ["Langfuse integration"],
            "search_hints": ["litellm alternatives 2026"],
            "eval_notes": "Central to stack — high migration cost",
        },
    }
}


@patch("agents.scout.REGISTRY_FILE")
def test_load_registry_parses_yaml(mock_file):
    mock_file.exists.return_value = True
    mock_file.read_text.return_value = yaml.dump(SAMPLE_REGISTRY)

    components = load_registry()
    assert len(components) == 2
    names = {c.key for c in components}
    assert "vector-database" in names
    assert "llm-gateway" in names


@patch("agents.scout.REGISTRY_FILE")
def test_load_registry_filter_component(mock_file):
    mock_file.exists.return_value = True
    mock_file.read_text.return_value = yaml.dump(SAMPLE_REGISTRY)

    components = load_registry(filter_component="vector-database")
    assert len(components) == 1
    assert components[0].key == "vector-database"
    assert components[0].current == "Qdrant"


@patch("agents.scout.REGISTRY_FILE")
def test_load_registry_filter_nonexistent(mock_file):
    mock_file.exists.return_value = True
    mock_file.read_text.return_value = yaml.dump(SAMPLE_REGISTRY)

    components = load_registry(filter_component="nonexistent")
    assert components == []


@patch("agents.scout.REGISTRY_FILE")
def test_load_registry_missing_file(mock_file):
    mock_file.exists.return_value = False
    components = load_registry()
    assert components == []


@patch("agents.scout.REGISTRY_FILE")
def test_load_registry_parses_component_fields(mock_file):
    mock_file.exists.return_value = True
    mock_file.read_text.return_value = yaml.dump(SAMPLE_REGISTRY)

    components = load_registry(filter_component="vector-database")
    c = components[0]
    assert c.role == "Vector storage for embeddings"
    assert c.provider == "qdrant.tech"
    assert len(c.constraints) == 2
    assert len(c.preferences) == 1
    assert len(c.search_hints) == 1
    assert "re-indexing" in c.eval_notes


@patch("agents.scout.REGISTRY_FILE")
def test_load_registry_handles_missing_fields(mock_file):
    """Components with missing optional fields should get defaults."""
    minimal = {"components": {"minimal": {"current": "foo"}}}
    mock_file.exists.return_value = True
    mock_file.read_text.return_value = yaml.dump(minimal)

    components = load_registry()
    assert len(components) == 1
    c = components[0]
    assert c.role == ""
    assert c.constraints == []
    assert c.search_hints == []


# ── Tavily search tests ─────────────────────────────────────────────────────


@patch("agents.scout.TAVILY_API_KEY", "test-key")
@patch("agents.scout.urlopen")
def test_tavily_search_returns_results(mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {
            "results": [
                {
                    "title": "Qdrant vs Milvus",
                    "url": "https://example.com",
                    "content": "Comparison...",
                },
                {
                    "title": "Vector DB Benchmark",
                    "url": "https://bench.io",
                    "content": "Results...",
                },
            ]
        }
    ).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    results = _tavily_search("qdrant alternatives", max_results=5)
    assert len(results) == 2
    assert results[0]["title"] == "Qdrant vs Milvus"
    assert results[0]["url"] == "https://example.com"


@patch("agents.scout.TAVILY_API_KEY", "")
def test_tavily_search_no_api_key():
    """Should return empty list when no API key set."""
    results = _tavily_search("query")
    assert results == []


@patch("agents.scout.TAVILY_API_KEY", "test-key")
@patch("agents.scout.urlopen")
def test_tavily_search_handles_error(mock_urlopen):
    from urllib.error import URLError

    mock_urlopen.side_effect = URLError("Connection refused")
    results = _tavily_search("query")
    assert results == []


# ── search_component tests ──────────────────────────────────────────────────


@patch("agents.scout.time.sleep")  # Don't actually sleep
@patch("agents.scout._tavily_search")
def test_search_component_aggregates_results(mock_search, mock_sleep):
    spec = ComponentSpec(
        key="test",
        role="test",
        current="Test",
        provider="test",
        constraints=[],
        preferences=[],
        search_hints=["hint1", "hint2"],
        eval_notes="",
    )
    mock_search.side_effect = [
        [{"title": "Result A", "url": "https://a.com", "content": "Content A"}],
        [{"title": "Result B", "url": "https://b.com", "content": "Content B"}],
    ]
    text = search_component(spec)
    assert "Result A" in text
    assert "Result B" in text
    assert mock_search.call_count == 2


@patch("agents.scout.time.sleep")
@patch("agents.scout._tavily_search")
def test_search_component_deduplicates_by_url(mock_search, mock_sleep):
    spec = ComponentSpec(
        key="test",
        role="test",
        current="Test",
        provider="test",
        constraints=[],
        preferences=[],
        search_hints=["hint1", "hint2"],
        eval_notes="",
    )
    mock_search.return_value = [
        {"title": "Same", "url": "https://same.com", "content": "Same content"},
    ]
    text = search_component(spec)
    # Even though _tavily_search called twice with same URL, only one entry
    assert text.count("### Same") == 1


@patch("agents.scout.time.sleep")
@patch("agents.scout._tavily_search")
def test_search_component_no_results(mock_search, mock_sleep):
    spec = ComponentSpec(
        key="test",
        role="test",
        current="Test",
        provider="test",
        constraints=[],
        preferences=[],
        search_hints=["hint1"],
        eval_notes="",
    )
    mock_search.return_value = []
    text = search_component(spec)
    assert "No search results found" in text


# ── Usage map tests ─────────────────────────────────────────────────────────


@patch("agents._langfuse_client.is_available", return_value=True)
@patch("agents._langfuse_client.langfuse_get")
def test_build_usage_map_with_data(mock_get, mock_avail):
    mock_get.return_value = {
        "data": [
            {"model": "claude-haiku"},
            {"model": "claude-haiku"},
            {"model": "qwen-coder-32b"},
            {"model": "nomic-embed"},
        ],
        "meta": {"totalItems": 100},
    }
    usage = _build_usage_map()
    assert "litellm" in usage
    assert "100" in usage["litellm"]


@patch("agents._langfuse_client.is_available", return_value=False)
def test_build_usage_map_langfuse_unavailable(mock_avail):
    usage = _build_usage_map()
    assert usage == {}


# ── Tier/schema tests ──────────────────────────────────────────────────────


def test_recommendation_tiers():
    for tier in ("adopt", "evaluate", "monitor", "current-best"):
        r = Recommendation(
            component="test",
            current="Test",
            tier=tier,
            summary="Test summary",
        )
        assert r.tier == tier


def test_scout_report_defaults():
    r = ScoutReport(generated_at="2026-03-01T00:00:00Z")
    assert r.components_scanned == 0
    assert r.recommendations == []
    assert r.errors == []


def test_finding_schema():
    f = Finding(name="Milvus", description="Open-source vector DB")
    assert f.url == ""


# ── Formatter tests ────────────────────────────────────────────────────────


def _sample_report() -> ScoutReport:
    return ScoutReport(
        generated_at="2026-03-01T10:00:00Z",
        components_scanned=3,
        recommendations=[
            Recommendation(
                component="vector-database",
                current="Qdrant",
                tier="current-best",
                summary="Still the best choice for our constraints.",
                confidence="high",
            ),
            Recommendation(
                component="llm-gateway",
                current="LiteLLM",
                tier="evaluate",
                summary="Portkey showing promise.",
                findings=[
                    Finding(name="Portkey", description="New gateway", url="https://portkey.ai")
                ],
                migration_effort="medium",
                confidence="medium",
            ),
        ],
    )


def test_format_report_md_has_headers():
    output = format_report_md(_sample_report())
    assert "# Scout Report" in output
    assert "Horizon Scan" in output


def test_format_report_md_groups_by_tier():
    output = format_report_md(_sample_report())
    assert "Current Best" in output
    assert "Evaluate" in output


def test_format_report_md_includes_findings():
    output = format_report_md(_sample_report())
    assert "Portkey" in output
    assert "portkey.ai" in output


def test_format_report_md_includes_migration_effort():
    output = format_report_md(_sample_report())
    assert "medium" in output


def test_format_report_human_contains_icons():
    output = format_report_human(_sample_report())
    assert "[✓]" in output or "[?]" in output


def test_format_report_human_contains_confidence():
    output = format_report_human(_sample_report())
    assert "high confidence" in output
    assert "medium confidence" in output


def test_format_report_md_errors_section():
    report = ScoutReport(
        generated_at="2026-03-01T10:00:00Z",
        errors=["vector-database: timeout"],
    )
    output = format_report_md(report)
    assert "## Errors" in output
    assert "timeout" in output


# ── Notification tests ──────────────────────────────────────────────────────


@patch("agents._notify.send_notification")
def test_send_notification_called_with_actionable(mock_notify):
    report = _sample_report()
    send_notification(report)
    mock_notify.assert_called_once()
    assert "Scout" in mock_notify.call_args[0][0] or "Scout" in str(mock_notify.call_args)


@patch("agents._notify.send_notification")
def test_send_notification_skipped_when_no_actionable(mock_notify):
    report = ScoutReport(
        generated_at="2026-03-01T10:00:00Z",
        recommendations=[
            Recommendation(component="test", current="Test", tier="current-best", summary="Fine"),
        ],
    )
    send_notification(report)
    mock_notify.assert_not_called()
