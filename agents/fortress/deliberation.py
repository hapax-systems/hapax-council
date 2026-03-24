"""ReAct deliberation loop — LLM-driven strategic reasoning.

Runs once per game-day. Receives 4 situation chunks, reasons with
observation tools, produces strategic actions. Uses Claude Sonnet
via LiteLLM for daily deliberation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from agents.fortress.chunks import ChunkCompressor
from agents.fortress.config import DeliberationConfig
from agents.fortress.schema import FastFortressState, FullFortressState
from agents.fortress.tools_registry import FORTRESS_TOOLS

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the governor of a dwarf fortress. Your role is to make strategic \
decisions about expansion, production, defense, and welfare.

You receive a situation summary each game-day. Use your observation tools \
to investigate concerns, then decide on actions.

Rules:
- Focus on the most urgent issue first
- Use observation tools to gather information before deciding
- Each tool call costs attention — be deliberate about what you investigate
- Respond with your reasoning, then a final list of actions

Available actions you can request:
- dig_room: Designate an area for mining
- build_workshop: Place a workshop (Still, Kitchen, Craftsdwarfs, Masons, etc.)
- import_orders: Import production order library
- pause/unpause: Control game flow
- Any DFHack command via "raw" action
"""


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert Anthropic-style tool defs to OpenAI function-calling format."""
    result = []
    for t in tools:
        result.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
        )
    return result


def build_deliberation_prompt(
    fortress_name: str,
    day: int,
    season: int,
    year: int,
    chunks: list[str],
    recent_events: list[str] | None = None,
    recent_decisions: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build the U-shaped prompt for deliberation.

    Top: identity + alerts (high attention)
    Middle: recent history (lower attention)
    Bottom: current situation + question (high attention)
    """
    season_names = {0: "Spring", 1: "Summer", 2: "Autumn", 3: "Winter"}
    season_name = season_names.get(season, f"Season {season}")

    # Check for critical alerts in chunks
    alerts = [c for c in chunks if "CRITICAL" in c]
    alert_section = ""
    if alerts:
        alert_section = "\nCRITICAL ALERTS:\n" + "\n".join(f"  ! {a}" for a in alerts) + "\n"

    # Middle: recent history
    history_section = ""
    if recent_events:
        history_section += (
            "\nRECENT EVENTS:\n" + "\n".join(f"  - {e}" for e in recent_events[-5:]) + "\n"
        )
    if recent_decisions:
        history_section += (
            "\nRECENT DECISIONS:\n" + "\n".join(f"  - {d}" for d in recent_decisions[-3:]) + "\n"
        )

    # Bottom: current situation
    situation = "\n".join(f"  {i + 1}. {c}" for i, c in enumerate(chunks))

    user_content = f"""{alert_section}{history_section}
CURRENT SITUATION — Day {day}, {season_name}, Year {year}:
{situation}

What should we focus on today? Investigate if needed, then decide."""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content.strip()},
    ]


async def run_deliberation(
    state: FastFortressState | FullFortressState,
    compressor: ChunkCompressor,
    prev_state: FastFortressState | FullFortressState | None,
    config: DeliberationConfig,
    tool_dispatch: dict[str, Any] | None = None,
    recent_events: list[str] | None = None,
    recent_decisions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run a single ReAct deliberation cycle.

    Returns list of action dicts suitable for bridge dispatch.
    """
    import litellm

    chunks = compressor.compress(state, prev_state)
    messages = build_deliberation_prompt(
        fortress_name=state.fortress_name,
        day=state.day,
        season=state.season,
        year=state.year,
        chunks=chunks,
        recent_events=recent_events,
        recent_decisions=recent_decisions,
    )

    openai_tools = _to_openai_tools(FORTRESS_TOOLS)
    actions: list[dict[str, Any]] = []
    tool_calls_used = 0
    start_time = time.monotonic()
    iteration = 0

    for iteration in range(config.max_iterations):
        # Check timeout
        elapsed = time.monotonic() - start_time
        if elapsed > config.timeout_s:
            log.warning("Deliberation timeout after %.1fs (%d iterations)", elapsed, iteration)
            break

        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=config.model_daily,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                    max_tokens=500,
                ),
                timeout=config.timeout_s - elapsed,
            )
        except TimeoutError:
            log.warning("LLM call timed out at iteration %d", iteration)
            break
        except Exception as exc:
            log.error("LLM call failed: %s", exc)
            break

        choice = response.choices[0]
        msg = choice.message

        # If no tool calls, extract final answer
        if not msg.tool_calls:
            if msg.content:
                log.info("Deliberation reasoning: %s", msg.content[:200])
                # Parse any action requests from the text
                actions.extend(_parse_text_actions(msg.content))
            break

        # Process tool calls
        messages.append(msg.model_dump())
        for tc in msg.tool_calls:
            if tool_calls_used >= config.max_tool_calls:
                log.info("Tool budget exhausted (%d calls)", tool_calls_used)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "Observation budget exhausted for this cycle.",
                    }
                )
                continue

            tool_name = tc.function.name
            tool_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            tool_calls_used += 1

            # Dispatch tool
            result = _dispatch_tool(tool_name, tool_args, tool_dispatch)
            log.info("  Tool: %s(%s) -> %s", tool_name, tool_args, result[:100])

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
            )

    log.info(
        "Deliberation complete: %d iterations, %d tool calls, %d actions, %.1fs",
        iteration + 1,
        tool_calls_used,
        len(actions),
        time.monotonic() - start_time,
    )
    return actions


def _dispatch_tool(
    name: str,
    args: dict[str, Any],
    dispatch_table: dict[str, Any] | None,
) -> str:
    """Route tool call to the appropriate observation function."""
    if dispatch_table and name in dispatch_table:
        try:
            result = dispatch_table[name](**args)
            return str(result)
        except Exception as exc:
            return f"Tool error: {exc}"
    return f"Tool '{name}' not available in this context."


def _parse_text_actions(text: str) -> list[dict[str, Any]]:
    """Parse action requests from LLM's final text response.

    Looks for structured action blocks like:
    ACTION: dig_room at center
    ACTION: import_orders library/basic
    """
    actions: list[dict[str, Any]] = []
    for line in text.split("\n"):
        line = line.strip()
        if line.upper().startswith("ACTION:"):
            parts = line[7:].strip().split(None, 1)
            if parts:
                action: dict[str, Any] = {"action": parts[0]}
                if len(parts) > 1:
                    action["params"] = parts[1]
                actions.append(action)
    return actions
