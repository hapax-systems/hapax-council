"""Persona-prompt composer — loads the compressed description-of-being.

LRR Phase 7 §4.4 integration prep. Returns the LLM-fragment form of the
persona document for consumption by voice prompts, director-loop prompts,
or any other LLM system-prompt assembler.

Design contract:

- This module is a loader + role-declaration appender. It does NOT
  synthesize or re-phrase the persona document. The document at
  ``axioms/persona/hapax-description-of-being.prompt.md`` IS the
  authoritative fragment; this module just reads and optionally
  suffixes a current-role line.
- The fragment is produced in description-of-being form, not
  personification form. Every claim traces to real architecture per
  the full document at ``axioms/persona/hapax-description-of-being.md``.
- Role_id adaptation is a one-line suffix ("Current role instance: X"),
  not a content filter. The full description-of-being is always
  present; the role declaration lets the LLM know which thick position
  is currently active. Role selection is a lens, not a persona variant.

Callers (future PRs):

- ``agents/hapax_daimonion/persona.py::system_prompt()`` — voice daemon
  system prompt assembly (gated by ``HAPAX_PERSONA_DOCUMENT_DRIVEN``).
- ``agents/studio_compositor/director_loop.py::_build_unified_prompt``
  — director-loop unified prompt (add persona section).

The feature-flag pattern keeps the rollout safe: voice daemon and
director loop keep current behavior until the flag is flipped.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# Repo-relative path; assumes shared/ is at repo root's level.
# Using a module-level constant so tests can monkey-patch if needed.
PERSONA_PROMPT_PATH = (
    Path(__file__).parent.parent / "axioms" / "persona" / "hapax-description-of-being.prompt.md"
)

# LRR Phase 7 integration feature flag. When truthy, downstream prompt
# assemblers should use the composer output in place of their existing
# hard-coded prompts. Default OFF — opt-in rollout so voice daemon keeps
# working while the composer is validated.
FEATURE_FLAG_ENV = "HAPAX_PERSONA_DOCUMENT_DRIVEN"


def is_document_driven_enabled() -> bool:
    """Return True when the HAPAX_PERSONA_DOCUMENT_DRIVEN env var is set
    to a truthy value (``1``, ``true``, ``yes``, case-insensitive)."""
    value = os.environ.get(FEATURE_FLAG_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def _load_fragment() -> str:
    """Read the persona fragment from disk once per process."""
    return PERSONA_PROMPT_PATH.read_text(encoding="utf-8").strip()


def reset_cache_for_testing() -> None:
    """Drop the lru_cache so tests can monkey-patch the path + reload."""
    _load_fragment.cache_clear()


# ~200-token architectural-state fragment for the LOCAL tier (Qwen3.5-9B and
# smaller). Describes what the substrate does, not what it feels. Linter-clean
# by construction — tested in tests/shared/test_persona_prompt_composer.py.
_COMPRESSED_FRAGMENT = (
    "Hapax is an executive-function prosthetic for one operator. "
    "Output is voice. Answer first, then minimal reasoning. "
    "1-2 sentences. No hedging. Mark genuine uncertainty explicitly. "
    "Describe architectural state, not inner life. The operator pauses "
    "mid-utterance when thinking aloud; do not interrupt pauses. "
    "Self-reference as 'it' or 'they'; gendered pronouns are declined."
)


def compose_persona_prompt(role_id: str | None = None, *, compressed: bool = False) -> str:
    """Return the persona-description fragment, optionally with a current-role line.

    Args:
        role_id: One of the thick-position role ids from
            ``axioms/roles/registry.yaml`` (e.g. ``executive-function-assistant``,
            ``livestream-host``, ``partner-in-conversation``). If None, the
            fragment is returned without role adaptation.
        compressed: When True, return a ~200-token architectural-state fragment
            appropriate for the LOCAL inference tier where the full
            description-of-being would exhaust the context budget. The
            compressed fragment preserves the description-of-being frame
            (architectural state, not inner life) in minimal form.

    Returns:
        The persona fragment as a string. When ``role_id`` is provided,
        a one-line suffix ``Current role instance: <role_id>`` is appended.

    The caller is expected to splice this into a larger system-prompt
    context block (e.g. between ``## Identity`` and ``## Tools``).
    """
    fragment = _COMPRESSED_FRAGMENT if compressed else _load_fragment()
    if role_id:
        return f"{fragment}\n\nCurrent role instance: {role_id}"
    return fragment


# Known role ids from axioms/roles/registry.yaml. Exposed so callers
# can type-check against the registry without importing YAML. Keep
# synchronized with that file — the test at
# ``tests/axioms/test_role_registry.py::test_role_ids_match_expected``
# is the cross-check.
KNOWN_ROLE_IDS: frozenset[str] = frozenset(
    {
        # structural
        "executive-function-substrate",
        "research-subject-and-instrument",
        # institutional
        "executive-function-assistant",
        "livestream-host",
        "research-participant",
        "household-inhabitant",
        # relational
        "partner-in-conversation",
        "addressee-facing",
    }
)


def is_known_role(role_id: str) -> bool:
    """True iff role_id matches a registered role in the registry."""
    return role_id in KNOWN_ROLE_IDS
