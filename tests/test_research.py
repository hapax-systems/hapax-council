"""Tests for research.py — system prompt, tool functions, query pipeline.

No LLM calls; tests focus on deterministic logic and mocked dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from agents.research import _build_system_prompt, Deps


# ── _build_system_prompt tests ────────────────────────────────────────────

def test_build_system_prompt_includes_base_context():
    """System prompt contains SYSTEM_CONTEXT."""
    prompt = _build_system_prompt()
    assert "knowledge base" in prompt.lower()


def test_build_system_prompt_includes_goals():
    """System prompt includes operator goals when available."""
    mock_goals = [
        {"goal": "Learn Rust"},
        {"description": "Build MIDI tools"},
    ]
    with patch("agents.research.get_goals", return_value=mock_goals):
        prompt = _build_system_prompt()
    assert "Learn Rust" in prompt
    assert "Build MIDI tools" in prompt


def test_build_system_prompt_no_goals():
    """System prompt works without goals."""
    with patch("agents.research.get_goals", return_value=[]):
        prompt = _build_system_prompt()
    assert "knowledge base" in prompt.lower()
    assert "active goals" not in prompt.lower()


def test_build_system_prompt_string_goals():
    """System prompt handles plain string goals."""
    with patch("agents.research.get_goals", return_value=["Goal A", "Goal B"]):
        prompt = _build_system_prompt()
    assert "- Goal A" in prompt
    assert "- Goal B" in prompt


# ── search_knowledge_base tool tests ──────────────────────────────────────

@pytest.mark.asyncio
async def test_search_knowledge_base_no_results():
    """Returns message when no documents found."""
    from agents.research import search_knowledge_base

    mock_qdrant = MagicMock()
    mock_results = MagicMock()
    mock_results.points = []
    mock_qdrant.query_points.return_value = mock_results

    deps = Deps(qdrant=mock_qdrant)
    ctx = MagicMock()
    ctx.deps = deps

    with patch("agents.research.embed", return_value=[0.1] * 768):
        result = await search_knowledge_base(ctx, "test query")

    assert "No relevant documents" in result


@pytest.mark.asyncio
async def test_search_knowledge_base_with_results():
    """Returns formatted chunks with source attribution."""
    from agents.research import search_knowledge_base

    mock_point = MagicMock()
    mock_point.payload = {"filename": "midi-routing.md", "text": "MIDI works via ALSA"}
    mock_point.score = 0.85

    mock_results = MagicMock()
    mock_results.points = [mock_point]

    mock_qdrant = MagicMock()
    mock_qdrant.query_points.return_value = mock_results

    deps = Deps(qdrant=mock_qdrant)
    ctx = MagicMock()
    ctx.deps = deps

    with patch("agents.research.embed", return_value=[0.1] * 768):
        result = await search_knowledge_base(ctx, "MIDI routing")

    assert "midi-routing.md" in result
    assert "MIDI works via ALSA" in result
    assert "0.850" in result


# ── query() pipeline tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_returns_output():
    """query() returns agent output on success."""
    mock_result = MagicMock()
    mock_result.output = "Research response"

    with patch("agents.research.agent") as mock_agent, \
         patch("agents.research.get_qdrant"):
        mock_agent.run = AsyncMock(return_value=mock_result)
        from agents.research import query
        result = await query("test prompt")

    assert result == "Research response"


@pytest.mark.asyncio
async def test_query_handles_error():
    """query() returns error message on LLM failure."""
    with patch("agents.research.agent") as mock_agent, \
         patch("agents.research.get_qdrant"):
        async def _fail(*a, **kw):
            raise RuntimeError("model unavailable")
        mock_agent.run = _fail
        from agents.research import query
        result = await query("test prompt")

    assert "Research query failed" in result
    assert "model unavailable" in result


# ── F-6.6: CLI main() tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_main_with_prompt(capsys):
    """main() with args runs query and prints output."""
    from agents.research import main

    with patch("agents.research.query", new_callable=AsyncMock, return_value="test response"), \
         patch("sys.argv", ["research", "test query"]):
        await main()

    captured = capsys.readouterr()
    assert "test response" in captured.out


@pytest.mark.asyncio
async def test_main_no_args(capsys):
    """main() with no args prints usage."""
    from agents.research import main

    with patch("sys.argv", ["research"]):
        await main()

    captured = capsys.readouterr()
    assert "Usage" in captured.out
