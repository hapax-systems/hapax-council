from __future__ import annotations

import os
from enum import StrEnum
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import CachePoint, UserPromptPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.litellm import LiteLLMProvider

from shared.config import LITELLM_BASE, LITELLM_KEY, MODELS

from .capability_admission import admit_model_alias
from .tools import FULL_TOOLS, RESTRICTED_TOOLS


class ToolLevel(StrEnum):
    FULL = "full"
    RESTRICTED = "restricted"
    NONE = "none"


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
    # deepseek + glm were added to the roster (PR #4233, models.py) and to the served
    # substring table below, but were MISSING here — so model_family() returned "unknown"
    # for healthy on-roster deepseek/glm seats while served_model_family() resolved them,
    # making the substitution test (engine._assess_health) count them as PHANTOM
    # substitutions (served_substitutions>=2 unconditionally, quarantining every segment
    # regardless of provider health). The glm value MUST be "zhipu" to match
    # _SERVED_FAMILY_SUBSTRINGS, not "glm". 2026-06-21.
    "deepseek": "deepseek",
    "glm": "zhipu",
}

LEGACY_MODEL_ALIASES: dict[str, str] = {
    "claude-opus": "opus",
    "claude-sonnet": "balanced",
    "gemini-pro": "gemini-3-pro",
}

CACHE_CONTROL_FAMILIES = frozenset({"anthropic", "google"})
OPENAI_PROMPT_CACHE_FAMILIES = frozenset({"openai"})
_CACHE_OFF_VALUES = {"0", "false", "no", "off"}
_CACHE_TTLS = {"5m", "1h"}
_CACHE_CONTROL_TTLS_BY_FAMILY = {
    "anthropic": {
        "5m": "5m",
        "1h": "1h",
    },
    "google": {
        "5m": "300s",
        "1h": "3600s",
    },
}
_OPENAI_CACHE_RETENTIONS = {"in_memory", "24h"}


class CCTVLiteLLMChatModel(OpenAIChatModel):
    """OpenAI-compatible LiteLLM model that preserves Pydantic AI cache points.

    Pydantic AI's stock OpenAI-chat adapter drops ``CachePoint`` because OpenAI
    itself does not use block-level cache markers. LiteLLM does map
    ``cache_control`` content blocks for Anthropic and Gemini routes, so CCTV
    needs this narrow adapter when those families are selected.
    """

    async def _map_user_prompt(self, part: UserPromptPart) -> dict[str, Any]:
        if isinstance(part.content, str):
            return await super()._map_user_prompt(part)

        content: list[dict[str, Any]] = []
        for item in part.content:
            if isinstance(item, CachePoint):
                if content and content[-1].get("type") == "text":
                    content[-1]["cache_control"] = {
                        "type": "ephemeral",
                        "ttl": item.ttl,
                    }
                continue
            mapped_item = await self._map_content_item(item)
            if mapped_item is not None:
                content.append(dict(mapped_item))
        return {"role": "user", "content": content}


def normalize_model_alias(model_alias: str) -> str:
    return LEGACY_MODEL_ALIASES.get(model_alias, model_alias)


def model_family(model_alias: str) -> str:
    return MODEL_FAMILIES.get(normalize_model_alias(model_alias), "unknown")


# Substrings of SERVED model names (LiteLLM ModelResponse.model_name) -> family. Counting
# family-diversity by the model that ACTUALLY answered (not the requested alias) is what stops a
# gateway fail-over (e.g. balanced->gemini-pro on an Anthropic credit cap) from satisfying the
# quorum's diversity floor with a phantom-anthropic gemini.
_SERVED_FAMILY_SUBSTRINGS: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("gemini", "google"),
    ("command-r", "cohere"),
    ("compassverifier", "cohere"),
    ("mistral", "mistral"),
    ("sonar", "perplexity"),
    # The live perplexity routes serve as web-research/web-reason/web-scout (NOT "sonar"),
    # so the served-family counter was blind to them (returned "unknown"). Map them so a
    # perplexity->anthropic fail-over is correctly seen as a real cross-family swap.
    ("web-research", "perplexity"),
    ("web-reason", "perplexity"),
    ("web-scout", "perplexity"),
    ("perplexity", "perplexity"),
    ("deepseek", "deepseek"),
    ("glm", "zhipu"),
)


def served_model_family(served_model: str) -> str:
    """Family of the model that actually answered, by name substring; 'unknown' if unrecognized."""
    name = (served_model or "").lower()
    for needle, family in _SERVED_FAMILY_SUBSTRINGS:
        if needle in name:
            return family
    return "unknown"


def prompt_cache_enabled() -> bool:
    raw = os.environ.get("HAPAX_CCTV_PROMPT_CACHE", "1").strip().lower()
    return raw not in _CACHE_OFF_VALUES


def prompt_cache_ttl() -> str:
    raw = os.environ.get("HAPAX_CCTV_PROMPT_CACHE_TTL", "5m").strip()
    return raw if raw in _CACHE_TTLS else "5m"


def openai_prompt_cache_retention() -> str:
    raw = os.environ.get("HAPAX_CCTV_OPENAI_PROMPT_CACHE_RETENTION", "in_memory").strip()
    return raw if raw in _OPENAI_CACHE_RETENTIONS else "in_memory"


def cache_control_ttl_for_alias(model_alias: str) -> str | None:
    if not prompt_cache_enabled():
        return None
    family = model_family(model_alias)
    if family not in CACHE_CONTROL_FAMILIES:
        return None
    return _CACHE_CONTROL_TTLS_BY_FAMILY[family][prompt_cache_ttl()]


def model_settings_for_alias(model_alias: str) -> dict[str, Any]:
    if not prompt_cache_enabled():
        return {}
    alias = normalize_model_alias(model_alias)
    if model_family(alias) not in OPENAI_PROMPT_CACHE_FAMILIES:
        return {}
    return {
        "openai_prompt_cache_key": f"cctv-deliberative-council:{alias}",
        "openai_prompt_cache_retention": openai_prompt_cache_retention(),
    }


def cache_policy_for_alias(model_alias: str) -> dict[str, Any]:
    alias = normalize_model_alias(model_alias)
    family = model_family(alias)
    ttl = cache_control_ttl_for_alias(alias)
    settings = model_settings_for_alias(alias)
    return {
        "alias": alias,
        "family": family,
        "cache_control": bool(ttl),
        "cache_control_ttl": ttl,
        "cache_control_ttl_setting": prompt_cache_ttl() if ttl else None,
        "openai_prompt_cache": bool(settings),
        "openai_prompt_cache_retention": settings.get("openai_prompt_cache_retention"),
    }


def cache_policy_for_aliases(model_aliases: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    return {alias: cache_policy_for_alias(alias) for alias in model_aliases}


def get_cctv_model(model_alias: str) -> CCTVLiteLLMChatModel:
    alias = normalize_model_alias(model_alias)
    model_id = MODELS.get(alias, alias)
    return CCTVLiteLLMChatModel(
        model_id,
        provider=LiteLLMProvider(api_base=LITELLM_BASE, api_key=LITELLM_KEY),
    )


def build_member(
    model_alias: str,
    tool_level: ToolLevel | None = None,
    *,
    system_prompt: str | None = None,
) -> Agent[None, str]:
    model_alias = normalize_model_alias(model_alias)
    capability_admission = admit_model_alias(model_alias)
    if tool_level is None:
        tool_level = MODEL_TOOL_LEVELS.get(model_alias, ToolLevel.FULL)

    if tool_level == ToolLevel.NONE:
        tools = []
    elif tool_level == ToolLevel.FULL:
        tools = list(FULL_TOOLS)
    else:
        tools = list(RESTRICTED_TOOLS)

    # retries=0: a non-conforming structured output (or a failed tool call) fails
    # LOUD rather than silently retrying. Combined with the per-run UsageLimits in
    # engine._call_member, a member can no longer runaway-loop or degrade quietly.
    # cc-task cctv-council-perfect-health-faillloud-convergence.
    agent = Agent(
        get_cctv_model(model_alias),
        system_prompt=system_prompt or "",
        model_settings=model_settings_for_alias(model_alias),
        tools=tools,  # type: ignore[arg-type]
        retries=0,
    )
    agent._cctv_model_alias = model_alias
    agent._cctv_capability_admission = capability_admission
    return agent
