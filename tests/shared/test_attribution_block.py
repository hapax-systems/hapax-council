"""V1-V5 unsettled-contribution sentence variants + per-surface
deviation matrix scaffold (V5 weave wk1 d4 PUB-CITATION-A — epsilon).

Pins the contract for ``shared.attribution_block``: the surface-aware
attribution adapter that wraps :class:`agents.authoring.byline.Byline`
with:

  * **V1-V5 unsettled-contribution sentence variants** — five
    phrasings of the authorship-indeterminacy-as-feature sentence
    (per ``feedback_co_publishing_auto_only_unsettled_contribution``).
  * **Per-surface deviation matrix** — for each of the 16 publication
    surfaces (V5 weave § 2.1 PUB-CITATION-A), declare which byline
    variant + which unsettled-contribution variant fits that
    surface's policy/aesthetic register.

Wk1 d4 (this scaffold): API contract + V1-V5 sentence templates +
deviation-matrix stub structure + tests. Per-surface variant
assignments are operator-reviewable (each surface line in the
matrix may be revised after first publish-event).
"""

from __future__ import annotations

import pytest

from agents.authoring.byline import Byline, BylineCoauthor, BylineVariant
from shared.attribution_block import (
    SURFACE_DEVIATION_MATRIX,
    UNSETTLED_CONTRIBUTION_VARIANTS,
    AttributionBlock,
    UnsettledContributionVariant,
    render_attribution_block,
)


@pytest.fixture
def full_byline() -> Byline:
    return Byline(
        operator_legal_name="Real Person",
        operator_referent="Oudepode",
        coauthors=(
            BylineCoauthor(name="Hapax", role="instrument"),
            BylineCoauthor(name="Claude Code", role="co-publisher"),
        ),
    )


# ── UnsettledContributionVariant enum ────────────────────────────────


class TestUnsettledContributionVariantEnum:
    def test_five_variants_v1_through_v5(self) -> None:
        names = {v.name for v in UnsettledContributionVariant}
        assert names == {"V1", "V2", "V3", "V4", "V5"}

    def test_variants_have_template_strings(self) -> None:
        for variant in UnsettledContributionVariant:
            assert variant in UNSETTLED_CONTRIBUTION_VARIANTS
            template = UNSETTLED_CONTRIBUTION_VARIANTS[variant]
            assert isinstance(template, str)
            assert template.strip()


class TestSentenceVariantsAreDistinct:
    """V1-V5 must each be DIFFERENT phrasings — the operator chooses
    per artifact based on surface aesthetic register. Identical
    templates would collapse the variant axis to one."""

    def test_all_five_templates_distinct(self) -> None:
        templates = {UNSETTLED_CONTRIBUTION_VARIANTS[v] for v in UnsettledContributionVariant}
        assert len(templates) == 5


# ── render_attribution_block ─────────────────────────────────────────


class TestRenderAttributionBlock:
    def test_returns_attribution_block_dataclass(self, full_byline: Byline) -> None:
        block = render_attribution_block(
            full_byline,
            byline_variant=BylineVariant.V2,
            unsettled_variant=UnsettledContributionVariant.V1,
        )
        assert isinstance(block, AttributionBlock)

    def test_byline_text_in_block(self, full_byline: Byline) -> None:
        block = render_attribution_block(
            full_byline,
            byline_variant=BylineVariant.V2,
            unsettled_variant=UnsettledContributionVariant.V1,
        )
        # Byline carries all three names for V2.
        assert "Real Person" in block.byline_text
        assert "Hapax" in block.byline_text
        assert "Claude Code" in block.byline_text

    def test_unsettled_sentence_in_block(self, full_byline: Byline) -> None:
        block = render_attribution_block(
            full_byline,
            byline_variant=BylineVariant.V2,
            unsettled_variant=UnsettledContributionVariant.V3,
        )
        assert block.unsettled_sentence
        assert isinstance(block.unsettled_sentence, str)

    def test_unsettled_variant_changes_sentence(self, full_byline: Byline) -> None:
        b1 = render_attribution_block(
            full_byline,
            byline_variant=BylineVariant.V2,
            unsettled_variant=UnsettledContributionVariant.V1,
        )
        b3 = render_attribution_block(
            full_byline,
            byline_variant=BylineVariant.V2,
            unsettled_variant=UnsettledContributionVariant.V3,
        )
        assert b1.unsettled_sentence != b3.unsettled_sentence

    def test_v0_byline_still_renders_block(self, full_byline: Byline) -> None:
        """V0 byline is solo-operator — the block still renders, but
        consumers may choose to omit the unsettled-contribution
        sentence at publish time. The block returns both."""
        block = render_attribution_block(
            full_byline,
            byline_variant=BylineVariant.V0,
            unsettled_variant=UnsettledContributionVariant.V1,
        )
        assert "Real Person" in block.byline_text
        # V0 byline omits coauthors but the block still has the V1 sentence.
        assert block.unsettled_sentence


# ── AttributionBlock dataclass ───────────────────────────────────────


class TestAttributionBlockDataclass:
    def test_constructable(self) -> None:
        block = AttributionBlock(
            byline_text="Real Person, Hapax, Claude Code",
            unsettled_sentence="(test sentence)",
            byline_variant=BylineVariant.V2,
            unsettled_variant=UnsettledContributionVariant.V1,
        )
        assert block.byline_text.startswith("Real Person")
        assert block.unsettled_sentence == "(test sentence)"


# ── SURFACE_DEVIATION_MATRIX ─────────────────────────────────────────


class TestSurfaceDeviationMatrix:
    """The matrix declares per-surface byline-variant + unsettled-
    contribution-variant assignment. V5 weave PUB-CITATION-A specifies
    16 surfaces; this scaffold lists at least that many keys."""

    def test_matrix_has_at_least_16_surfaces(self) -> None:
        # V5 weave § 2.1 PUB-CITATION-A: "Per-surface deviation matrix
        # (16 surfaces)". Pin the floor — additions OK, deletions need
        # explicit governance review.
        assert len(SURFACE_DEVIATION_MATRIX) >= 16

    def test_each_entry_pairs_byline_with_unsettled(self) -> None:
        for surface, entry in SURFACE_DEVIATION_MATRIX.items():
            assert isinstance(surface, str)
            assert isinstance(entry["byline"], BylineVariant)
            assert isinstance(entry["unsettled"], UnsettledContributionVariant)

    def test_proto_surfaces_use_v3(self) -> None:
        """Bandcamp-style surfaces use V3 (PROTO precedent: distributor
        + performer). Pin so future revisions don't accidentally drift
        a music surface to a non-PROTO byline shape."""
        bandcamp_entry = SURFACE_DEVIATION_MATRIX.get("bandcamp")
        assert bandcamp_entry is not None
        assert bandcamp_entry["byline"] == BylineVariant.V3

    def test_research_papers_use_v2_or_v5(self) -> None:
        """Academic preprint surfaces use V2 (full three-way co-publish)
        or V5 (unsettled-contribution as feature). Either is on-spec
        for `psyarxiv` / `arxiv` / `philarchive` / etc.

        Pin: the variant must be in {V2, V5} — never V0/V1 (which
        understate co-pub) or V4 (which over-emphasizes Hapax-as-primary
        for a research paper)."""
        for surface in ("philarchive", "psyarxiv", "arxiv"):
            entry = SURFACE_DEVIATION_MATRIX.get(surface)
            if entry is None:
                continue  # surface not in seed matrix; OK
            assert entry["byline"] in {BylineVariant.V2, BylineVariant.V5}, (
                f"{surface} should be V2 or V5; got {entry['byline']}"
            )
