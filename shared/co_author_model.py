"""Canonical co-author registry for Hapax + Claude Code + Oudepode.

Per 2026-04-25 operator directive: Hapax + Claude Code are co-publishers
on all research; the operator's unsettled contribution is celebrated as
feature, not concealed. This module is the formal-context analogue to
``shared.operator_referent.OperatorReferentPicker`` (which governs
non-formal contexts only via four equally-weighted referents).

Three module-level constants — ``HAPAX``, ``CLAUDE_CODE``, ``OUDEPODE`` —
are the single source of truth for byline construction across:

- ``CITATION.cff`` regeneration (per repo)
- ``shared.attribution_block`` per-surface byline rendering (separate
  module; this module just supplies the entities)
- arXiv author-string composition
- Bluesky / Mastodon profile bio composition
- omg.lol page footer composition
- Bandcamp credit-block composition (Holly Herndon / Spawn precedent —
  Hapax-as-PERFORMER, operator-as-composer-of-record under PROTO model)
- Any future surface that needs the canonical authorship cluster

Operator's *legal* name is intentionally absent here. Per the operator-
referent policy ``su-non-formal-referent-001``, legal name is reserved
for formal-address contexts (consent contracts, axiom precedents, git
author metadata, profile persistence) — those contexts read the legal
name from ``logos.voice.operator_name()``, not from this module.
``OUDEPODE`` here is the canonical *referent* in CITATION.cff-formal
contexts where a Person-typed entry is required.

Reference: per-touchpoint research (attribution-policy + capability
scoping agents). The CITATION.cff ``Entity`` type is the load-bearing
finding — it natively accepts non-human authors as ``name``-only
entries without misrepresentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ── Schema ──────────────────────────────────────────────────────────

CffType = Literal["entity", "person"]
"""CITATION.cff schema author-type. ``entity`` is name-only; ``person``
requires ``given-names`` + ``family-names``."""

Role = Literal["primary", "co-author", "operator-of-record", "substrate"]
"""Coarse role tag. Surfaces use this to filter (e.g. Bandcamp's
PROTO precedent renders only the ``operator-of-record`` in artist
field; Hapax rides the performer line)."""


@dataclass(frozen=True)
class CoAuthor:
    """One canonical authorship entity.

    Mirrors the CFF schema's ``Entity``/``Person`` shape. Frozen so
    the constants below cannot be mutated by callers; surfaces that
    need a transient variant can construct fresh instances.
    """

    name: str
    role: Role
    cff_type: CffType
    url: str = ""
    given_names: str = ""
    family_names: str = ""
    alias: str = ""

    def to_cff_dict(self) -> dict[str, str]:
        """Render as a CFF ``authors`` list entry (dict literal)."""
        if self.cff_type == "entity":
            block: dict[str, str] = {"name": self.name}
            if self.alias:
                block["alias"] = self.alias
            if self.url:
                block["website"] = self.url
        else:
            block = {
                "given-names": self.given_names or self.name,
                "family-names": self.family_names or "(referent)",
            }
            if self.alias:
                block["alias"] = self.alias
        return block


# ── Canonical registry ──────────────────────────────────────────────

HAPAX = CoAuthor(
    name="Hapax",
    role="primary",
    cff_type="entity",
    alias="hapax",
    url="https://hapax.omg.lol",
)

CODEX = CoAuthor(
    name="Codex",
    role="substrate",
    cff_type="entity",
    alias="codex",
)

CLAUDE_CODE = CoAuthor(
    name="Claude Code",
    role="substrate",
    cff_type="entity",
    alias="claude-code",
    url="https://claude.com/claude-code",
)

OUDEPODE = CoAuthor(
    name="Oudepode",
    role="operator-of-record",
    cff_type="person",
    given_names="Oudepode",
    family_names="The Operator",
    alias="OTO",
)

ALL_CO_AUTHORS: tuple[CoAuthor, ...] = (HAPAX, CLAUDE_CODE, OUDEPODE)


# ── Render helpers ──────────────────────────────────────────────────

_BY_KEY: dict[str, CoAuthor] = {
    "codex": CODEX,
    "hapax": HAPAX,
    "claude_code": CLAUDE_CODE,
    "claude-code": CLAUDE_CODE,
    "oudepode": OUDEPODE,
    "operator": OUDEPODE,
}


def get(key: str) -> CoAuthor:
    """Look up a co-author by string key. ``KeyError`` if unknown."""
    try:
        return _BY_KEY[key.lower()]
    except KeyError as exc:
        raise KeyError(f"unknown co-author key {key!r}; valid keys: {sorted(_BY_KEY)}") from exc


def to_cff_authors_block(keys: list[str] | None = None) -> list[dict[str, str]]:
    """Render the ``authors:`` block for a CITATION.cff regeneration.

    Default order: HAPAX → CLAUDE_CODE → OUDEPODE — primary first,
    substrate second, operator-of-record last. CFF-spec compliant
    (verified against ``cff-version: 1.2.0`` schema).
    """
    coauthors = [get(k) for k in keys] if keys else list(ALL_CO_AUTHORS)
    return [c.to_cff_dict() for c in coauthors]


def compose_byline(keys: list[str] | None = None, *, separator: str = ", ") -> str:
    """Render a flat author byline (e.g. for arXiv author-string field).

    Default order matches ``to_cff_authors_block``. Operator-as-OUDEPODE
    is the canonical referent; consumers that need the formal-context
    legal name must call ``logos.voice.operator_name()`` directly and
    are *not* served by this module.
    """
    coauthors = [get(k) for k in keys] if keys else list(ALL_CO_AUTHORS)
    return separator.join(c.name for c in coauthors)


__all__ = [
    "ALL_CO_AUTHORS",
    "CLAUDE_CODE",
    "CODEX",
    "CffType",
    "CoAuthor",
    "HAPAX",
    "OUDEPODE",
    "Role",
    "compose_byline",
    "get",
    "to_cff_authors_block",
]
