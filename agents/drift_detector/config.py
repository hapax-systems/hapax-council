"""Path constants and model factory for drift detector."""

from __future__ import annotations

import os
import warnings
from pathlib import Path

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.litellm import LiteLLMProvider

# ── Environment ──────────────────────────────────────────────────────────────

LITELLM_BASE: str = os.environ.get(
    "LITELLM_API_BASE",
    os.environ.get("LITELLM_BASE_URL", "http://localhost:4000"),
)
LITELLM_KEY: str = os.environ.get("LITELLM_API_KEY", "")
if not LITELLM_KEY:
    warnings.warn(
        "LITELLM_API_KEY is not set — LLM calls will fail until a valid key is provided",
        stacklevel=1,
    )
OLLAMA_URL: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# ── Canonical paths ─────────────────────────────────────────────────────────

HAPAX_HOME: Path = Path(os.environ.get("HAPAX_HOME", str(Path.home())))
HAPAX_CACHE_DIR: Path = HAPAX_HOME / ".cache"
HAPAX_PROJECTS_DIR: Path = HAPAX_HOME / "projects"
LLM_STACK_DIR: Path = HAPAX_HOME / "llm-stack"
CLAUDE_CONFIG_DIR: Path = HAPAX_HOME / ".claude"
PASSWORD_STORE_DIR: Path = HAPAX_HOME / ".password-store"

# State directories
AXIOM_AUDIT_DIR: Path = HAPAX_CACHE_DIR / "axiom-audit"
LOGOS_STATE_DIR: Path = HAPAX_CACHE_DIR / "logos"

# Project directories
HAPAX_COUNCIL_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-council"
HAPAX_CONSTITUTION_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-constitution"
OBSIDIAN_HAPAX_DIR: Path = HAPAX_COUNCIL_DIR / "obsidian-hapax"

# Legacy aliases (used by docs.py and other modules)
AI_AGENTS_DIR: Path = HAPAX_COUNCIL_DIR
HAPAXROMANA_DIR: Path = HAPAX_CONSTITUTION_DIR
LOGOS_WEB_DIR: Path = HAPAX_COUNCIL_DIR / "hapax-logos"
HAPAX_VSCODE_DIR: Path = HAPAX_COUNCIL_DIR / "vscode"

PROFILES_DIR: Path = Path(__file__).resolve().parent.parent.parent / "profiles"

# ── Model aliases ──────────────────────────────────────────────────────────

MODELS: dict[str, str] = {
    "fast": "gemini-flash",
}


# ── Factories ──────────────────────────────────────────────────────────────


def get_model(alias_or_id: str = "fast") -> OpenAIChatModel:
    """Create a LiteLLM-backed chat model."""
    model_id = MODELS.get(alias_or_id, alias_or_id)
    return OpenAIChatModel(
        model_id,
        provider=LiteLLMProvider(
            api_base=LITELLM_BASE,
            api_key=LITELLM_KEY,
        ),
    )


def get_model_adaptive(alias: str = "fast") -> OpenAIChatModel:
    """Stimmung-aware model selection — downgrades when system is stressed."""
    import json
    from pathlib import Path as _Path

    try:
        raw = json.loads(_Path("/dev/shm/hapax-stimmung/state.json").read_text(encoding="utf-8"))
        stance = raw.get("overall_stance", "nominal")
        cost = raw.get("llm_cost_pressure", {}).get("value", 0.0)
        resource = raw.get("resource_pressure", {}).get("value", 0.0)

        if stance == "critical":
            return get_model("local-fast")

        if resource > 0.7:
            downgraded = {"balanced": "fast", "fast": "local-fast", "reasoning": "local-fast"}
            if alias in downgraded:
                return get_model(downgraded[alias])

        if cost > 0.6:
            downgraded = {"balanced": "fast"}
            if alias in downgraded:
                return get_model(downgraded[alias])
    except Exception:
        pass  # stimmung unavailable — use requested alias as-is

    return get_model(alias)
