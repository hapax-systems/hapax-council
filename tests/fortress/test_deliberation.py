"""Tests for deliberation loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.fortress.chunks import ChunkCompressor
from agents.fortress.config import DeliberationConfig
from agents.fortress.deliberation import (
    _dispatch_tool,
    _parse_text_actions,
    _to_openai_tools,
    build_deliberation_prompt,
)
from agents.fortress.schema import FastFortressState
from agents.fortress.tools_registry import FORTRESS_TOOLS


def _state(**kw):
    defaults = dict(
        timestamp=0,
        game_tick=100000,
        year=1,
        season=0,
        month=0,
        day=5,
        fortress_name="TestFort",
        paused=False,
        population=20,
        food_count=200,
        drink_count=100,
        active_threats=0,
        job_queue_length=5,
        idle_dwarf_count=2,
        most_stressed_value=5000,
    )
    defaults.update(kw)
    return FastFortressState(**defaults)


class TestPromptStructure:
    def test_u_shape_has_system_and_user(self):
        chunks = ["Food ok.", "Pop ok.", "Industry ok.", "Safety ok."]
        messages = build_deliberation_prompt("TestFort", 5, 0, 1, chunks)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_prompt_has_governor_role(self):
        messages = build_deliberation_prompt("TestFort", 5, 0, 1, ["a", "b", "c", "d"])
        assert "governor" in messages[0]["content"].lower()

    def test_user_prompt_has_situation(self):
        chunks = ["Food: 200. Drink: 100.", "Pop: 20.", "Industry ok.", "Safety clear."]
        messages = build_deliberation_prompt("TestFort", 5, 0, 1, chunks)
        content = messages[1]["content"]
        assert "Day 5" in content
        assert "Spring" in content
        assert "Food: 200" in content

    def test_critical_alerts_at_top(self):
        chunks = ["[CRITICAL] Food: 5.", "Pop ok.", "Industry ok.", "Safety ok."]
        messages = build_deliberation_prompt("TestFort", 5, 0, 1, chunks)
        content = messages[1]["content"]
        # Alert should appear before situation
        alert_pos = content.find("CRITICAL ALERTS")
        situation_pos = content.find("CURRENT SITUATION")
        assert alert_pos < situation_pos

    def test_no_alerts_when_nominal(self):
        chunks = ["Food ok.", "Pop ok.", "Industry ok.", "Safety ok."]
        messages = build_deliberation_prompt("TestFort", 5, 0, 1, chunks)
        assert "CRITICAL ALERTS" not in messages[1]["content"]

    def test_recent_events_in_middle(self):
        chunks = ["a", "b", "c", "d"]
        messages = build_deliberation_prompt(
            "TestFort", 5, 0, 1, chunks, recent_events=["Siege arrived"]
        )
        content = messages[1]["content"]
        assert "Siege arrived" in content

    def test_recent_decisions_in_middle(self):
        chunks = ["a", "b", "c", "d"]
        messages = build_deliberation_prompt(
            "TestFort", 5, 0, 1, chunks, recent_decisions=["Built still"]
        )
        content = messages[1]["content"]
        assert "Built still" in content

    def test_season_names(self):
        for season, name in [(0, "Spring"), (1, "Summer"), (2, "Autumn"), (3, "Winter")]:
            messages = build_deliberation_prompt("F", 1, season, 1, ["a"])
            assert name in messages[1]["content"]


class TestToolDispatch:
    def test_dispatch_known_tool(self):
        table = {"check_stockpile": lambda category="food": f"Stock: {category}"}
        result = _dispatch_tool("check_stockpile", {"category": "drink"}, table)
        assert "drink" in result

    def test_dispatch_unknown_tool(self):
        result = _dispatch_tool("unknown_tool", {}, {})
        assert "not available" in result

    def test_dispatch_error_handling(self):
        table = {"bad_tool": lambda: 1 / 0}
        result = _dispatch_tool("bad_tool", {}, table)
        assert "Tool error" in result

    def test_dispatch_none_table(self):
        result = _dispatch_tool("anything", {}, None)
        assert "not available" in result

    def test_dispatch_returns_string(self):
        table = {"numeric": lambda: 42}
        result = _dispatch_tool("numeric", {}, table)
        assert result == "42"


class TestParseTextActions:
    def test_parse_action_line(self):
        text = "I think we should brew.\nACTION: import_orders library/basic\nDone."
        actions = _parse_text_actions(text)
        assert len(actions) == 1
        assert actions[0]["action"] == "import_orders"
        assert actions[0]["params"] == "library/basic"

    def test_no_actions(self):
        text = "Everything looks fine. No actions needed."
        actions = _parse_text_actions(text)
        assert len(actions) == 0

    def test_multiple_actions(self):
        text = "ACTION: dig_room center\nACTION: build_workshop Still"
        actions = _parse_text_actions(text)
        assert len(actions) == 2
        assert actions[0]["action"] == "dig_room"
        assert actions[1]["action"] == "build_workshop"

    def test_case_insensitive_prefix(self):
        text = "action: pause"
        actions = _parse_text_actions(text)
        assert len(actions) == 1
        assert actions[0]["action"] == "pause"

    def test_action_without_params(self):
        text = "ACTION: pause"
        actions = _parse_text_actions(text)
        assert len(actions) == 1
        assert "params" not in actions[0]


class TestToolConversion:
    def test_converts_to_openai_format(self):
        tools = _to_openai_tools(FORTRESS_TOOLS)
        assert len(tools) == len(FORTRESS_TOOLS)
        for t in tools:
            assert t["type"] == "function"
            assert "name" in t["function"]
            assert "parameters" in t["function"]

    def test_preserves_tool_names(self):
        tools = _to_openai_tools(FORTRESS_TOOLS)
        names = {t["function"]["name"] for t in tools}
        expected = {t["name"] for t in FORTRESS_TOOLS}
        assert names == expected


class TestRunDeliberation:
    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_text_actions(self):
        """LLM responds with text actions, no tool use."""
        state = _state()
        compressor = ChunkCompressor()
        config = DeliberationConfig()

        mock_msg = MagicMock()
        mock_msg.tool_calls = None
        mock_msg.content = "Let's brew.\nACTION: import_orders basic"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            actions = await run_deliberation_import(state, compressor, None, config)

        assert len(actions) == 1
        assert actions[0]["action"] == "import_orders"

    @pytest.mark.asyncio
    async def test_tool_call_then_final_answer(self):
        """LLM calls a tool, then responds with actions."""
        state = _state()
        compressor = ChunkCompressor()
        config = DeliberationConfig()

        # First response: tool call
        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "check_stockpile"
        tc.function.arguments = '{"category": "food"}'

        msg1 = MagicMock()
        msg1.tool_calls = [tc]
        msg1.content = None
        msg1.model_dump.return_value = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "check_stockpile", "arguments": '{"category": "food"}'},
                }
            ],
        }
        choice1 = MagicMock()
        choice1.message = msg1
        resp1 = MagicMock()
        resp1.choices = [choice1]

        # Second response: final answer
        msg2 = MagicMock()
        msg2.tool_calls = None
        msg2.content = "Food is fine.\nACTION: build_workshop Still"
        choice2 = MagicMock()
        choice2.message = msg2
        resp2 = MagicMock()
        resp2.choices = [choice2]

        dispatch = {"check_stockpile": lambda category="food": f"Stock: {category} ok"}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [resp1, resp2]
            actions = await run_deliberation_import(
                state, compressor, None, config, tool_dispatch=dispatch
            )

        assert len(actions) == 1
        assert actions[0]["action"] == "build_workshop"
        assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_stops_loop(self):
        """Deliberation respects timeout."""
        state = _state()
        compressor = ChunkCompressor()
        config = DeliberationConfig(timeout_s=0.001)

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = TimeoutError()
            actions = await run_deliberation_import(state, compressor, None, config)

        assert actions == []

    @pytest.mark.asyncio
    async def test_llm_error_stops_gracefully(self):
        """LLM exception is caught and loop stops."""
        state = _state()
        compressor = ChunkCompressor()
        config = DeliberationConfig()

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = RuntimeError("API down")
            actions = await run_deliberation_import(state, compressor, None, config)

        assert actions == []


# Helper to avoid circular import issues in test — import at function level
async def run_deliberation_import(*args, **kwargs):
    from agents.fortress.deliberation import run_deliberation

    return await run_deliberation(*args, **kwargs)
