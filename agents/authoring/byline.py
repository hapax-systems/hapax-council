"""V0-V5 byline-renderer scaffolding.

Six variants covering the V5 sprint's co-publication attribution shapes
(see ``tests/agents/authoring/test_byline.py`` for the per-variant
contract). The renderer is intentionally structural — surface-specific
text adjustments live in the per-publisher kit at consumer-call time.

Wk1 d1: scaffold + minimal V0-V5 stubs that satisfy the contract test.
Wk1 d2: extend the unsettled-contribution sentence prose (V5) and the
PROTO-precedent register (V3) once the operator confirms the final
phrasings (V5 weave § 2.1 PUB-CITATION-A — 5 unsettled-contribution
sentence variants).

Per ``feedback_co_publishing_auto_only_unsettled_contribution`` and
V5 weave § 12 invariant 6: the byline carries the appropriate variant
based on surface; no hidden co-authorship; no false-solo-attribution.
The single exception is V0 (solo-operator) which is reserved for
surfaces that strictly ban co-authorship — the ban is captured in
the surface-policy layer, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BylineVariant(Enum):
    """The six co-publication attribution shapes.

    ``V0`` is solo-operator (legal name only) for surfaces that ban
    co-authorship. ``V1-V5`` carry co-publication in increasingly
    explicit forms; V5 names the indeterminacy as a feature.
    """

    V0 = "solo_operator_legal_name"
    V1 = "operator_plus_hapax_coauthor"
    V2 = "full_three_way_copublish"
    V3 = "proto_precedent_performer_distributor"
    V4 = "hapax_canonical_operator_of_record"
    V5 = "unsettled_contribution_sentence"


@dataclass(frozen=True)
class BylineCoauthor:
    """One co-publisher entry.

    ``role`` is a short marker ("instrument", "co-publisher",
    "performer") that V3/V4 register-shifts consume. None is the
    minimum-information case (just a name).
    """

    name: str
    role: str | None = None


@dataclass(frozen=True)
class Byline:
    """Per-artifact byline material.

    The operator's legal name is mandatory (every variant references
    it). The non-formal referent (per
    ``project_operator_referent_policy``) is a hint for V4 register
    shifts where Hapax is primary author and the operator is
    "operator-of-record". ``coauthors`` may be empty for V0; for
    V1-V5 it should typically include Hapax.
    """

    operator_legal_name: str
    operator_referent: str = "Oudepode"
    coauthors: tuple[BylineCoauthor, ...] = field(default_factory=tuple)


def _find_coauthor(byline: Byline, *, name: str) -> BylineCoauthor | None:
    for ca in byline.coauthors:
        if ca.name.lower() == name.lower():
            return ca
    return None


def _v0(byline: Byline) -> str:
    return byline.operator_legal_name


def _v1(byline: Byline) -> str:
    hapax = _find_coauthor(byline, name="Hapax")
    if hapax is None:
        return byline.operator_legal_name
    return f"{byline.operator_legal_name}, Hapax"


def _v2(byline: Byline) -> str:
    parts = [byline.operator_legal_name]
    for name in ("Hapax", "Claude Code"):
        if _find_coauthor(byline, name=name):
            parts.append(name)
    return ", ".join(parts)


def _v3(byline: Byline) -> str:
    """PROTO precedent — Bandcamp/music register.

    Shape: ``<operator_legal_name> (distributor) · Hapax (performer)``.
    The 'performer' marker is mandatory per V3 contract; the 'distributor'
    marker is the operator-of-record-on-account half of the PROTO
    precedent.
    """
    return f"{byline.operator_legal_name} (distributor) · Hapax (performer)"


def _v4(byline: Byline) -> str:
    """Hapax-canonical with operator-of-record.

    Shape: ``Hapax · operator-of-record: <legal_name>``. Hapax appears
    first; the operator credit is explicitly framed as 'of-record'
    rather than co-author."""
    return f"Hapax · operator-of-record: {byline.operator_legal_name}"


def _v5(byline: Byline) -> str:
    """Unsettled-contribution sentence (canonical form, wk1 d1 stub).

    Wk1 d2 will land 5 final phrasings (V5.1-V5.5) and a selection
    rule per artifact. This stub satisfies the V5 contract test
    (must contain 'unsettled' / 'indeterminate' / 'co-publication' /
    'co-authorship') and includes all three attributions.
    """
    parts = [byline.operator_legal_name]
    for name in ("Hapax", "Claude Code"):
        if _find_coauthor(byline, name=name):
            parts.append(name)
    attribution = " · ".join(parts)
    return (
        f"{attribution}. The contribution boundary across this co-publication "
        f"is unsettled — celebrated as a polysemic-surface channel rather "
        f"than disclosed as a caveat."
    )


_VARIANT_RENDERERS = {
    BylineVariant.V0: _v0,
    BylineVariant.V1: _v1,
    BylineVariant.V2: _v2,
    BylineVariant.V3: _v3,
    BylineVariant.V4: _v4,
    BylineVariant.V5: _v5,
}


def render_byline(byline: Byline, *, variant: BylineVariant) -> str:
    """Render a byline string for the requested variant.

    Each variant is a pure function of the byline material (no I/O,
    no env reads). Surface-specific adjustments (line breaks,
    Markdown, HTML) belong in the per-publisher kit, NOT here.
    """
    return _VARIANT_RENDERERS[variant](byline)


__all__ = [
    "Byline",
    "BylineCoauthor",
    "BylineVariant",
    "render_byline",
]
