"""V1-V5 unsettled-contribution sentence variants + per-surface
deviation matrix (V5 weave wk1 d4 PUB-CITATION-A — epsilon).

Surface-aware adapter wrapping :class:`agents.authoring.byline.Byline`
+ :class:`agents.authoring.byline.BylineVariant`. Two-axis attribution:

  * ``BylineVariant`` (V0-V5) — byline shape (solo / 2-way / 3-way /
    PROTO / Hapax-canonical / unsettled-celebration). Owned by
    ``agents.authoring.byline``.
  * ``UnsettledContributionVariant`` (V1-V5) — sentence variant for
    framing the contribution boundary as a celebrated polysemic-
    surface channel. Owned here.

The :data:`SURFACE_DEVIATION_MATRIX` declares for each of the 16
publication surfaces (V5 weave § 2.1 PUB-CITATION-A) which byline +
unsettled-contribution variant pair fits that surface's policy /
aesthetic register. Operator-reviewable; CODEOWNERS protects this
file once landed.

Per V5 weave § 12 invariant 6: every artifact carries the appropriate
V0-V5 byline + V1-V5 unsettled-contribution sentence per
SURFACE_DEVIATION_MATRIX. No hidden co-authorship; no
false-solo-attribution.

Wk1 d4 (this scaffold): API + V1-V5 sentence templates + 16-surface
matrix seed. Wk2+ adjustments after operator review of per-surface
landings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, TypedDict

from agents.authoring.byline import Byline, BylineVariant, render_byline


class UnsettledContributionVariant(Enum):
    """Five phrasings of the contribution-indeterminacy-as-feature sentence.

    Each variant frames the same idea — that the precise contribution
    boundary across operator / Hapax / Claude Code is unsettled, and
    that this is celebrated rather than disclosed-as-uncertainty —
    in a different aesthetic register. The operator chooses per
    artifact via :data:`SURFACE_DEVIATION_MATRIX` or per-publish
    override.
    """

    V1 = "celebrated_polysemy"  # The 7th-channel framing
    V2 = "production_record"  # CRediT-adjacent prose
    V3 = "phenomenological"  # First-person philosophy register
    V4 = "lab_methodology"  # Scientific-methodology register
    V5 = "manifesto"  # Critical-theory / aesthetic register


UNSETTLED_CONTRIBUTION_VARIANTS: Final[dict[UnsettledContributionVariant, str]] = {
    UnsettledContributionVariant.V1: (
        "The contribution boundary across this co-publication is unsettled — "
        "celebrated as a polysemic-surface channel rather than disclosed as "
        "a caveat."
    ),
    UnsettledContributionVariant.V2: (
        "Authorship is genuinely co-extensive: operator framed the questions, "
        "Hapax composed and selected, Claude Code transformed prose to "
        "publish-shaped artifact. CRediT does not disambiguate further."
    ),
    UnsettledContributionVariant.V3: (
        "Whose voice you are reading is not finally settled — it is "
        "operator-thinking and Hapax-thinking and Claude-Code-thinking "
        "together, in a way that resists clean attribution but invites "
        "reading."
    ),
    UnsettledContributionVariant.V4: (
        "Methodology note: the artifact was authored as a coupled system "
        "(operator + Hapax + Claude Code). Per-segment attribution would "
        "be a misleading reduction; the system is the unit of "
        "co-publication."
    ),
    UnsettledContributionVariant.V5: (
        "Co-publication here is constitutive, not editorial. The text "
        "could not have arrived from any single author — that "
        "indeterminacy is the artifact's mode."
    ),
}


@dataclass(frozen=True)
class AttributionBlock:
    """Composed attribution: byline text + unsettled-contribution sentence.

    Consumers (per-surface publishers) read both fields and decide
    rendering ordering / Markdown vs HTML formatting. The dataclass
    carries the variant choices for traceability + downstream
    deviation-matrix audit.
    """

    byline_text: str
    unsettled_sentence: str
    byline_variant: BylineVariant
    unsettled_variant: UnsettledContributionVariant


def render_attribution_block(
    byline: Byline,
    *,
    byline_variant: BylineVariant,
    unsettled_variant: UnsettledContributionVariant,
) -> AttributionBlock:
    """Render an :class:`AttributionBlock` for the requested variant pair.

    Pure function. Surface-specific rendering decisions (line breaks,
    Markdown, HTML) are the publisher's responsibility — this function
    returns the source-of-truth pair.
    """
    return AttributionBlock(
        byline_text=render_byline(byline, variant=byline_variant),
        unsettled_sentence=UNSETTLED_CONTRIBUTION_VARIANTS[unsettled_variant],
        byline_variant=byline_variant,
        unsettled_variant=unsettled_variant,
    )


# ── Per-surface deviation matrix (V5 weave § 2.1 PUB-CITATION-A) ────


class _MatrixEntry(TypedDict):
    """One row of the per-surface deviation matrix.

    Use a plain ``TypedDict`` (not a frozen dataclass) so the
    matrix can be expressed as a Python literal that reads like a
    spec table — operator reviews the dict directly.
    """

    byline: BylineVariant
    unsettled: UnsettledContributionVariant


# The 16 publication surfaces from V5 weave § 2.1. Variant choices
# encode the V5 weave's per-surface aesthetic register. Operator
# reviews + adjusts before first publish-event for each surface.
SURFACE_DEVIATION_MATRIX: Final[dict[str, _MatrixEntry]] = {
    # ── Phase 1: existing publishers refactored onto kit ─────────
    "bsky": {
        "byline": BylineVariant.V2,
        "unsettled": UnsettledContributionVariant.V1,
    },
    "mastodon": {
        "byline": BylineVariant.V2,
        "unsettled": UnsettledContributionVariant.V1,
    },
    "arena": {
        "byline": BylineVariant.V4,
        "unsettled": UnsettledContributionVariant.V5,
    },
    "webmention": {
        "byline": BylineVariant.V2,
        "unsettled": UnsettledContributionVariant.V1,
    },
    # ── Phase 2: long-form preprint ──────────────────────────────
    "osf_preprint": {
        "byline": BylineVariant.V2,
        "unsettled": UnsettledContributionVariant.V4,
    },
    "hf_papers": {
        "byline": BylineVariant.V2,
        "unsettled": UnsettledContributionVariant.V4,
    },
    "manifold": {
        "byline": BylineVariant.V2,
        "unsettled": UnsettledContributionVariant.V1,
    },
    "lesswrong": {
        "byline": BylineVariant.V2,
        "unsettled": UnsettledContributionVariant.V2,
    },
    # ── Phase 3: Playwright form-submitters ──────────────────────
    "philarchive": {
        "byline": BylineVariant.V2,
        "unsettled": UnsettledContributionVariant.V3,
    },
    "alphaxiv": {
        "byline": BylineVariant.V2,
        "unsettled": UnsettledContributionVariant.V4,
    },
    "substack": {
        "byline": BylineVariant.V4,
        "unsettled": UnsettledContributionVariant.V5,
    },
    "pouet_net": {
        "byline": BylineVariant.V4,
        "unsettled": UnsettledContributionVariant.V5,
    },
    "scene_org": {
        "byline": BylineVariant.V4,
        "unsettled": UnsettledContributionVariant.V5,
    },
    "bandcamp": {
        # PROTO precedent — operator-as-distributor + Hapax-as-performer.
        "byline": BylineVariant.V3,
        "unsettled": UnsettledContributionVariant.V5,
    },
    # ── Existing OMG / Hapax-canon surfaces ──────────────────────
    "omg_lol_weblog": {
        "byline": BylineVariant.V4,
        "unsettled": UnsettledContributionVariant.V5,
    },
    "omg_lol_pastebin": {
        "byline": BylineVariant.V2,
        "unsettled": UnsettledContributionVariant.V1,
    },
}


__all__ = [
    "SURFACE_DEVIATION_MATRIX",
    "UNSETTLED_CONTRIBUTION_VARIANTS",
    "AttributionBlock",
    "UnsettledContributionVariant",
    "render_attribution_block",
]
