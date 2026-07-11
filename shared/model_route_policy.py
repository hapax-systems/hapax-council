"""Source-level model route policy for Hapax runtime callers.

This module is intentionally small and dependency-free so both ``shared`` and
vendored ``agents`` config helpers can use the same no-escape defaults before
constructing a LiteLLM-backed model.
"""

from __future__ import annotations

import os

ROUTINE_DEFAULT_MODEL = os.environ.get("HAPAX_ROUTINE_DEFAULT_MODEL", "local-fast")
STRONG_DEFAULT_MODEL = os.environ.get("HAPAX_STRONG_DEFAULT_MODEL", "gemini-pro")
SDLC_DEFAULT_MODEL = os.environ.get("HAPAX_SDLC_DEFAULT_MODEL", STRONG_DEFAULT_MODEL)
STRUCTURAL_JUDGE_DEFAULT_MODEL = os.environ.get(
    "HAPAX_STRUCTURAL_JUDGE_DEFAULT_MODEL", STRONG_DEFAULT_MODEL
)

_PROVIDER_PREFIXES = ("anthropic:", "anthropic/", "openrouter:", "openrouter/")


def strip_provider_prefix(model_name: str) -> str:
    """Return the route portion of a provider-prefixed model string."""
    route = model_name.strip()
    for prefix in _PROVIDER_PREFIXES:
        if route.startswith(prefix):
            return route.removeprefix(prefix)
    return route


def sanitize_model_route(model_name: str, *, replacement: str = STRONG_DEFAULT_MODEL) -> str:
    """Normalize disallowed escaped routes to an admitted in-gateway route.

    The runtime LiteLLM guard is the egress backstop. This helper keeps source
    defaults and env overrides from reintroducing direct Sonnet/OpenRouter
    model names before they reach Pydantic AI or raw LiteLLM clients.
    """
    raw = model_name.strip()
    lowered_raw = raw.lower()
    if "openrouter" in lowered_raw:
        return replacement
    route = strip_provider_prefix(raw)
    lowered = route.lower()
    if "claude" in lowered and "sonnet" in lowered:
        return replacement
    return route
