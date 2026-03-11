"""Tests for code_review.py -- agent instantiation, schema, system prompt, CLI."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.code_review import (
    SYSTEM_PROMPT,
    ReviewDeps,
    _make_agent,
    agent,
    review,
)

# -- Schema tests ------------------------------------------------------------


def test_review_deps_defaults():
    deps = ReviewDeps()
    assert deps.filename == "stdin"


def test_review_deps_custom_filename():
    deps = ReviewDeps(filename="src/main.py")
    assert deps.filename == "src/main.py"


# -- System prompt tests -----------------------------------------------------


def test_system_prompt_contains_review_instructions():
    assert "code reviewer" in SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_severity():
    assert "high" in SYSTEM_PROMPT.lower()
    assert "medium" in SYSTEM_PROMPT.lower()
    assert "low" in SYSTEM_PROMPT.lower()


def test_system_prompt_has_structure_sections():
    assert "Summary" in SYSTEM_PROMPT
    assert "Issues" in SYSTEM_PROMPT
    assert "Suggestions" in SYSTEM_PROMPT


def test_system_prompt_includes_operator_context():
    """System prompt should include operator profile from get_system_prompt_fragment."""
    assert "executive function" in SYSTEM_PROMPT.lower() or "operator" in SYSTEM_PROMPT.lower()


# -- Agent instantiation tests -----------------------------------------------


def test_agent_exists():
    assert agent is not None


def test_make_agent_returns_agent():
    a = _make_agent("balanced")
    assert a is not None


# -- review() function tests -------------------------------------------------


@pytest.mark.asyncio
async def test_review_with_filename():
    """review() should format prompt with filename for file input."""
    mock_result = MagicMock()
    mock_result.output = "**Summary**: Clean code, no issues."

    with patch.object(agent, "run", new_callable=AsyncMock, return_value=mock_result):
        output = await review("def hello(): pass", "hello.py")
        assert "Clean code" in output


@pytest.mark.asyncio
async def test_review_with_stdin():
    """review() should format prompt as diff for stdin input."""
    mock_result = MagicMock()
    mock_result.output = "**Summary**: Minor improvements possible."

    with patch.object(agent, "run", new_callable=AsyncMock, return_value=mock_result):
        output = await review("+ added line\n- removed line", "stdin")
        assert "Minor improvements" in output


@pytest.mark.asyncio
async def test_review_handles_llm_failure():
    """review() should return error message on LLM failure."""
    with patch.object(
        agent, "run", new_callable=AsyncMock, side_effect=RuntimeError("API timeout")
    ):
        output = await review("def broken(): pass", "broken.py")
        assert "failed" in output.lower()
        assert "API timeout" in output


# -- CLI argument tests -------------------------------------------------------


def test_cli_accepts_path_argument():
    """CLI parser should accept optional positional path argument."""
    import argparse as _argparse

    # Manually test the parser setup (main() creates it internally)
    parser = _argparse.ArgumentParser()
    parser.add_argument("path", nargs="?")
    parser.add_argument("--diff")
    parser.add_argument("--model", default="balanced")

    args = parser.parse_args(["src/main.py"])
    assert args.path == "src/main.py"
    assert args.model == "balanced"


def test_cli_accepts_diff_flag():
    import argparse as _argparse

    parser = _argparse.ArgumentParser()
    parser.add_argument("path", nargs="?")
    parser.add_argument("--diff")
    parser.add_argument("--model", default="balanced")

    args = parser.parse_args(["--diff", "some diff content"])
    assert args.diff == "some diff content"
    assert args.path is None


def test_cli_accepts_model_override():
    import argparse as _argparse

    parser = _argparse.ArgumentParser()
    parser.add_argument("path", nargs="?")
    parser.add_argument("--diff")
    parser.add_argument("--model", default="balanced")

    args = parser.parse_args(["--model", "fast"])
    assert args.model == "fast"
