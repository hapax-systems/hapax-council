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

import re

__all__ = [
    "canonical_family",
    "REVIEW_FAMILY_MODEL_FAMILY",
    "effective_review_family",
    "substitute_pin_inflates",
    "HTTP_SUBSTITUTE_FAMILIES",
    "observed_served_model",
]

HTTP_SUBSTITUTE_FAMILIES = frozenset({"kimi", "featherless", "verboo"})

# Recognized model-name prefixes and family tokens. Conflicting families remain unknown;
# these labels do not establish measured error independence or capability admission.
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
    "kimi": "kimi",
    "featherless": "deepseek",
    "verboo": "minimax",
}


def canonical_family(served_model: str | None) -> str | None:
    """Resolve a served model id to its model family, or None when unknown."""
    if not isinstance(served_model, str) or not served_model:
        return None
    model = served_model.lower().rsplit("/", 1)[-1]
    matches = {
        family
        for needle, family in _MODEL_FAMILY_PATTERNS
        if re.search(rf"(?:^|[-_.]){needle}(?=$|[-_.\d])", model)
    }
    # Opaque gateway aliases and ambiguous/distilled names are not ancestry evidence.
    if len(matches) != 1 or not any(
        re.match(rf"^{needle}(?=$|[-_.\d])", model) for needle, _ in _MODEL_FAMILY_PATTERNS
    ):
        return None
    return matches.pop()


def effective_review_family(declared_family: str, served_model: str | None) -> str | None:
    """The family a substitute seat counts as for independence.

    When the served model's family is one a core/seated review family already occupies, the
    seat counts as that review family (anti-inflation). Other known ancestry uses its
    canonical name; unknown ancestry receives no voting-family credit. Never use the pin
    as a substitute for the observed response model.
    """
    model_family = canonical_family(served_model)
    if model_family is not None:
        for review_family, occupied in REVIEW_FAMILY_MODEL_FAMILY.items():
            if occupied == model_family:
                return review_family
    return model_family


def substitute_pin_inflates(declared_family: str, pinned_model: str | None) -> str | None:
    """Return the core/seated review family a substitute pin would collapse into, or None when
    the pin is a genuinely distinct family. A test uses this to refuse a duplicate pin."""
    effective = effective_review_family(declared_family, pinned_model)
    return (effective or "unknown") if effective != declared_family else None


def observed_served_model(declared_family: str, stderr: str) -> str | None:
    """Read exactly one wrapper identity line from process stderr, never review text.

    The caller supplies the actual dispatched route. Foreign/duplicate/malformed lines
    cannot supply identity. The pin is diagnostic only, even if the provider omits model.
    """
    if declared_family not in HTTP_SUBSTITUTE_FAMILIES:
        return None
    prefix = f"hapax-{declared_family}-reviewer: served_model="
    lines = [line for line in stderr.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        return None
    token = r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}"
    match = re.fullmatch(re.escape(prefix) + rf"({token}) pinned_model={token}", lines[0])
    return match[1] if match and match[1] != "unknown" else None
