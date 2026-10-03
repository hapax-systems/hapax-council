"""Anti-inflation family mapping for substitute review seats.

Review independence counts DISTINCT model families (scripts/review_team.py). A substitute seat
(kimi, featherless, verboo) that serves a model whose family is already a core or seated
family must count as THAT family, never as a new one — otherwise a second seat of the same
model family would inflate the independence count (for example GLM-5.3 on Featherless is still
``glm``, not a distinct ``featherless``).

This module is the single mapping: :func:`canonical_family` resolves a served model id to its
model family, and :func:`effective_review_family` resolves what family a substitute seat counts
as. :func:`substitute_pin_inflates` lets a test refuse a registry that pins a substitute to a
model family a core/seated family already occupies ("pin non-duplicate models").
"""

from __future__ import annotations

__all__ = [
    "canonical_family",
    "REVIEW_FAMILY_MODEL_FAMILY",
    "effective_review_family",
    "substitute_pin_inflates",
]

# Served-model id substring -> model family. Ordered: the first substring that appears in the
# lowercased model id wins (so "deepseek-v4" resolves before a bare vendor prefix).
_MODEL_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("glm", "glm"),
    ("claude", "claude"),
    ("gemini", "gemini"),
    ("gemma", "gemma"),
    ("codex", "gpt"),
    ("gpt", "gpt"),
    ("kimi", "kimi"),
    ("moonshot", "kimi"),
    ("deepseek", "deepseek"),
    ("minimax", "minimax"),
    ("qwen", "qwen"),
    ("codestral", "mistral"),
    ("devstral", "mistral"),
    ("magistral", "mistral"),
    ("mistral", "mistral"),
    ("llama", "llama"),
    ("grok", "grok"),
)

#: The model family each CORE or already-SEATED review family occupies. A substitute that pins a
#: model in this set does not add independence; it counts as the occupying review family.
REVIEW_FAMILY_MODEL_FAMILY: dict[str, str] = {
    "claude": "claude",
    "codex": "gpt",
    "gemini": "gemini",
    "glm": "glm",
    "local": "qwen",  # scripts/hapax-local-reviewer serves qwen3.8-flash-next
    "vibe": "mistral",  # scripts/hapax-vibe-reviewer serves Mistral Medium 3.5
}


def canonical_family(served_model: str | None) -> str | None:
    """Resolve a served model id to its model family, or None when unknown."""
    if not served_model:
        return None
    lowered = served_model.lower()
    for needle, family in _MODEL_FAMILY_PATTERNS:
        if needle in lowered:
            return family
    return None


def effective_review_family(declared_family: str, served_model: str | None) -> str:
    """The family a substitute seat counts as for independence.

    When the served model's family is one a core/seated review family already occupies, the
    seat counts as that review family (anti-inflation). Otherwise it keeps its declared
    substitute family.
    """
    model_family = canonical_family(served_model)
    if model_family is not None:
        for review_family, occupied in REVIEW_FAMILY_MODEL_FAMILY.items():
            if occupied == model_family and review_family != declared_family:
                return review_family
    return declared_family


def substitute_pin_inflates(declared_family: str, pinned_model: str | None) -> str | None:
    """Return the core/seated review family a substitute pin would collapse into, or None when
    the pin is a genuinely distinct family. A test uses this to refuse a duplicate pin."""
    effective = effective_review_family(declared_family, pinned_model)
    return effective if effective != declared_family else None
