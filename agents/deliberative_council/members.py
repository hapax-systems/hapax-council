from __future__ import annotations

from enum import StrEnum

from pydantic_ai import Agent

from shared.config import get_model

from .tools import FULL_TOOLS, RESTRICTED_TOOLS


class ToolLevel(StrEnum):
    FULL = "full"
    RESTRICTED = "restricted"


MODEL_TOOL_LEVELS: dict[str, ToolLevel] = {
    "opus": ToolLevel.FULL,
    "balanced": ToolLevel.FULL,
    "gemini-3-pro": ToolLevel.FULL,
    "local-fast": ToolLevel.RESTRICTED,
    "web-research": ToolLevel.FULL,
    "mistral-large": ToolLevel.FULL,
}

MODEL_FAMILIES: dict[str, str] = {
    "opus": "anthropic",
    "balanced": "anthropic",
    "gemini-3-pro": "google",
    "local-fast": "cohere",
    "web-research": "perplexity",
    "mistral-large": "mistral",
}


def build_member(
    model_alias: str,
    tool_level: ToolLevel | None = None,
) -> Agent[None, str]:
    if tool_level is None:
        tool_level = MODEL_TOOL_LEVELS.get(model_alias, ToolLevel.FULL)

    tools = list(FULL_TOOLS if tool_level == ToolLevel.FULL else RESTRICTED_TOOLS)

    return Agent(
        get_model(model_alias),
        tools=tools,  # type: ignore[arg-type]
    )
