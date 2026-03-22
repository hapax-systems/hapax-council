"""Tests for chat_agent.py and chat screen error classification.

No LLM calls; tests focus on deterministic split/repair/classification logic.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from logos.chat_agent import (
    ChatSession,
    _find_safe_split,
    classify_chat_error,
    format_conversation_export,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _user(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _assistant(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


def _tool_call(tool_name: str, tool_call_id: str) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={"key": "val"},
                tool_call_id=tool_call_id,
            )
        ]
    )


def _tool_result(tool_name: str, tool_call_id: str) -> ModelRequest:
    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name=tool_name,
                content="ok",
                tool_call_id=tool_call_id,
            )
        ]
    )


# ── _find_safe_split tests ──────────────────────────────────────────────────


def test_find_safe_split_no_tool_returns():
    """Clean history with no tool calls — split at the expected position."""
    msgs = [
        _user("hello"),
        _assistant("hi"),
        _user("how are you"),
        _assistant("good"),
        _user("cool"),
        _assistant("thanks"),
    ]
    # keep_recent=2 → target index 4, which is _user("cool") — clean user turn
    split = _find_safe_split(msgs, 2)
    assert split == 4
    assert isinstance(msgs[split], ModelRequest)


def test_find_safe_split_avoids_orphan():
    """Split must not leave an orphaned ToolReturnPart in recent messages."""
    msgs = [
        _user("hello"),  # 0 — safe
        _assistant("hi"),  # 1
        _user("do something"),  # 2 — safe
        _tool_call("record_fact", "tc1"),  # 3
        _tool_result("record_fact", "tc1"),  # 4 — NOT safe (tool return)
        _assistant("noted"),  # 5
        _user("thanks"),  # 6 — safe
    ]
    # keep_recent=3 → target index 4. Index 4 is a ToolReturnPart — unsafe.
    # Should scan backward to index 2 ("do something" — clean user turn).
    split = _find_safe_split(msgs, 3)
    assert split == 2
    msg = msgs[split]
    assert isinstance(msg, ModelRequest)
    assert any(isinstance(p, UserPromptPart) for p in msg.parts)
    assert not any(isinstance(p, ToolReturnPart) for p in msg.parts)


def test_find_safe_split_no_safe_point():
    """History of only tool exchanges — returns 0 (don't compact)."""
    msgs = [
        _tool_call("record_fact", "tc1"),
        _tool_result("record_fact", "tc1"),
        _tool_call("record_fact", "tc2"),
        _tool_result("record_fact", "tc2"),
    ]
    split = _find_safe_split(msgs, 2)
    assert split == 0


def test_find_safe_split_empty_history():
    """Empty history returns 0."""
    assert _find_safe_split([], 6) == 0


def test_find_safe_split_keep_more_than_length():
    """keep_recent larger than history — target is 0, still finds safe point."""
    msgs = [_user("hello"), _assistant("hi")]
    split = _find_safe_split(msgs, 100)
    assert split == 0


# ── _repair_history tests ───────────────────────────────────────────────────


def test_repair_history_preserves_interview_state():
    """Repair clears broken history but preserves interview_state."""
    session = ChatSession(project_dir=Path("/tmp"))
    session.interview_state = {"facts": ["a", "b"], "insights": ["c"]}
    session.message_history = [
        _user("hello"),
        _assistant("hi"),
        _tool_call("record_fact", "tc1"),
        _tool_result("record_fact", "tc1"),  # orphaned if history started here
        _user("thanks"),
        _assistant("noted"),
    ]

    session._repair_history()

    # interview_state must survive
    assert session.interview_state == {"facts": ["a", "b"], "insights": ["c"]}
    # History should start at a clean user turn
    assert len(session.message_history) > 0
    first = session.message_history[0]
    assert isinstance(first, ModelRequest)
    assert any(isinstance(p, UserPromptPart) for p in first.parts)


def test_repair_history_clears_when_no_safe_point():
    """When no safe point exists, history is cleared but interview state preserved."""
    session = ChatSession(project_dir=Path("/tmp"))
    session.interview_state = {"facts": ["x"]}
    session.conversation_summary = "some summary"
    session.message_history = [
        _tool_call("record_fact", "tc1"),
        _tool_result("record_fact", "tc1"),
    ]

    session._repair_history()

    assert session.interview_state == {"facts": ["x"]}
    assert session.message_history == []
    assert session.conversation_summary == ""


# ── classify_chat_error tests ───────────────────────────────────────────────


def test_classify_tool_result_error():
    """tool_result / tool_use_id mismatch → history_corrupt."""
    e = Exception("unexpected 'tool_use_id' found in 'tool_result' blocks: toolu_abc123")
    msg, cat = classify_chat_error(e)
    assert cat == "history_corrupt"
    assert "orphaned tool_result" in msg.lower()


def test_classify_rate_limit():
    """Rate limit errors → rate_limit."""
    e = Exception("litellm.RateLimitError: Rate limit exceeded (429)")
    msg, cat = classify_chat_error(e)
    assert cat == "rate_limit"


def test_classify_context_length():
    """Context length errors → context_length."""
    e = Exception("This request has too many tokens. Max tokens: 200000")
    msg, cat = classify_chat_error(e)
    assert cat == "context_length"
    assert "context length" in msg.lower()


def test_classify_connection_error():
    """Connection errors → provider_down."""
    e = Exception("Connection refused: connect to localhost:4000 failed")
    msg, cat = classify_chat_error(e)
    assert cat == "provider_down"


def test_classify_unknown_truncates():
    """Unknown errors are truncated to 200 chars."""
    long_msg = "x" * 500
    e = Exception(long_msg)
    msg, cat = classify_chat_error(e)
    assert cat == "unknown"
    assert len(msg) <= 204  # 200 + "..."
    assert msg.endswith("...")


# ── last_turn_tokens tests ─────────────────────────────────────────────────


def test_last_turn_tokens_default():
    """ChatSession.last_turn_tokens defaults to 0."""
    session = ChatSession(project_dir=Path("/tmp"))
    assert session.last_turn_tokens == 0


# ── format_conversation_export tests ───────────────────────────────────────


def test_format_export_basic():
    """User + assistant messages formatted as markdown."""
    history = [_user("hello"), _assistant("Hi there!")]
    result = format_conversation_export(history, "balanced")
    assert "# Chat Export" in result
    assert "**Model**: balanced" in result
    assert "> hello" in result
    assert "### Assistant" in result
    assert "Hi there!" in result


def test_format_export_empty():
    """Empty history produces header only."""
    result = format_conversation_export([], "fast")
    assert "# Chat Export" in result
    assert "**Model**: fast" in result
    assert "**Messages**: 0" in result
    assert "### You" not in result
    assert "### Assistant" not in result


def test_format_export_with_tools():
    """Tool calls appear in export output."""
    history = [
        _user("check health"),
        _tool_call("check_health", "tc1"),
        _tool_result("check_health", "tc1"),
        _assistant("Everything looks good."),
    ]
    result = format_conversation_export(history, "balanced")
    assert "> check health" in result
    assert "check_health" in result
    assert "Everything looks good." in result


# ── Interview model_alias tests ────────────────────────────────────────────


def test_interview_agent_accepts_model_alias():
    """create_interview_agent accepts model_alias parameter with default 'balanced'."""
    import inspect

    from logos.interview import create_interview_agent

    sig = inspect.signature(create_interview_agent)
    assert "model_alias" in sig.parameters
    assert sig.parameters["model_alias"].default == "balanced"


def test_interview_plan_accepts_model_alias():
    """generate_interview_plan accepts model_alias parameter with default 'balanced'."""
    import inspect

    from logos.interview import generate_interview_plan

    sig = inspect.signature(generate_interview_plan)
    assert "model_alias" in sig.parameters
    assert sig.parameters["model_alias"].default == "balanced"


# ── F-2.2: end_interview preserves state on flush failure ────────────────


@pytest.mark.asyncio
async def test_end_interview_preserves_state_on_flush_failure():
    """Interview state is preserved when flush_interview_facts raises."""
    from unittest.mock import AsyncMock

    from logos.interview import InterviewPlan, InterviewState, InterviewTopic, RecordedFact

    session = ChatSession.__new__(ChatSession)
    session.mode = "interview"
    session.message_history = []
    session.conversation_summary = ""
    session._interview_agent = AsyncMock()
    session.interview_state = InterviewState(
        plan=InterviewPlan(
            topics=[
                InterviewTopic(
                    topic="test",
                    dimension="test_dim",
                    rationale="testing",
                    question_seed="q?",
                    depth="surface",
                )
            ],
            overall_focus="testing",
        ),
        facts=[
            RecordedFact(
                dimension="test_dim", key="k", value="v", confidence=0.8, evidence="said so"
            )
        ],
        insights=[],
        topics_explored=[],
    )

    with patch("agents.profiler.flush_interview_facts", side_effect=RuntimeError("disk full")):
        result = await session.end_interview()

    # State should be preserved on failure
    assert session.interview_state is not None
    assert session.mode == "interview"
    assert "Failed to flush" in result
    assert "preserved" in result.lower()
