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
    NON_ENGAGEMENT_CLAUSE_LONG,
    NON_ENGAGEMENT_CLAUSE_SHORT,
    SURFACE_DEVIATION_MATRIX,
    UNSETTLED_CONTRIBUTION_VARIANTS,
    AttributionBlock,
    NonEngagementForm,
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

    def test_v5_lead_with_7_target_surfaces_present(self) -> None:
        """V5 lead-with #7 (Self-Censorship as Aesthetic) target surfaces
        — Triple Canopy / Bandcamp Daily / Wax Poetics — have direct
        matrix entries (wk1 follow-on; previously the artifact fell back
        to ``lesswrong``).

        Pin: each entry has byline + unsettled + non_engagement_form
        fields populated so the render pipeline does not produce
        ``None`` clauses on these surfaces.
        """
        for surface in ("triple_canopy", "bandcamp_daily", "wax_poetics"):
            entry = SURFACE_DEVIATION_MATRIX.get(surface)
            assert entry is not None, f"{surface} matrix entry missing"
            assert isinstance(entry["byline"], BylineVariant)
            assert isinstance(entry["unsettled"], UnsettledContributionVariant)
            assert "non_engagement_form" in entry

    def test_long_form_essay_surfaces_use_long_clause(self) -> None:
        """Triple Canopy + Wax Poetics + Bandcamp Daily are long-form
        capacity surfaces; LONG non-engagement clause fits comfortably
        and is the right register for editorial publications."""
        for surface in ("triple_canopy", "bandcamp_daily", "wax_poetics"):
            entry = SURFACE_DEVIATION_MATRIX[surface]
            assert entry["non_engagement_form"] == NonEngagementForm.LONG, (
                f"{surface} should use LONG form; got {entry['non_engagement_form']}"
            )


# ── Refusal Brief: non_engagement_clause ──────────────────────────────
#
# Per beta inflection 20260425T171500Z (4-agent fold synthesis of
# operator's full-automation-or-no-engagement directive). Every
# AttributionBlock carries a non_engagement_clause linking back to the
# Refusal Brief; per-surface character-budget gets short vs. long form.


class TestNonEngagementClauseConstants:
    """Module-level constants ship two phrasings (short / long) of the
    Refusal Brief reference. Both must be non-empty strings; long must
    contain more characters than short (the discrimination criterion)."""

    def test_short_clause_present(self) -> None:
        assert NON_ENGAGEMENT_CLAUSE_SHORT
        assert isinstance(NON_ENGAGEMENT_CLAUSE_SHORT, str)

    def test_long_clause_present(self) -> None:
        assert NON_ENGAGEMENT_CLAUSE_LONG
        assert isinstance(NON_ENGAGEMENT_CLAUSE_LONG, str)

    def test_long_strictly_longer_than_short(self) -> None:
        assert len(NON_ENGAGEMENT_CLAUSE_LONG) > len(NON_ENGAGEMENT_CLAUSE_SHORT)

    def test_short_fits_bsky_300_char_budget(self) -> None:
        """Bluesky post body cap is 300 chars. The short form must
        leave headroom for the byline + content; ≤200 chars target."""
        assert len(NON_ENGAGEMENT_CLAUSE_SHORT) <= 200

    def test_both_reference_refusal_brief(self) -> None:
        """Both forms must include a pointer to the Refusal Brief
        URL or the literal phrase `Refusal Brief` so downstream
        readers can discover the source."""
        assert "refusal" in NON_ENGAGEMENT_CLAUSE_SHORT.lower()
        assert "refusal" in NON_ENGAGEMENT_CLAUSE_LONG.lower()


class TestNonEngagementForm:
    def test_form_enum_two_values(self) -> None:
        names = {f.name for f in NonEngagementForm}
        assert names == {"SHORT", "LONG"}


class TestRenderWithNonEngagement:
    def test_default_no_clause_when_form_omitted(self, full_byline: Byline) -> None:
        """Backward compat: render_attribution_block called without
        non_engagement_form returns a block whose
        non_engagement_clause is None."""
        block = render_attribution_block(
            full_byline,
            byline_variant=BylineVariant.V2,
            unsettled_variant=UnsettledContributionVariant.V1,
        )
        assert block.non_engagement_clause is None

    def test_short_form_renders_short_clause(self, full_byline: Byline) -> None:
        block = render_attribution_block(
            full_byline,
            byline_variant=BylineVariant.V2,
            unsettled_variant=UnsettledContributionVariant.V1,
            non_engagement_form=NonEngagementForm.SHORT,
        )
        assert block.non_engagement_clause == NON_ENGAGEMENT_CLAUSE_SHORT

    def test_long_form_renders_long_clause(self, full_byline: Byline) -> None:
        block = render_attribution_block(
            full_byline,
            byline_variant=BylineVariant.V2,
            unsettled_variant=UnsettledContributionVariant.V1,
            non_engagement_form=NonEngagementForm.LONG,
        )
        assert block.non_engagement_clause == NON_ENGAGEMENT_CLAUSE_LONG


class TestSurfaceMatrixNonEngagementForm:
    """Per-surface deviation matrix carries the non_engagement_form
    choice so consumers can lookup-and-render in one shot. Per
    beta synthesis: bsky/mastodon → SHORT (char-limited);
    arena/discord/osf → LONG (capacity available)."""

    def test_bsky_uses_short_form(self) -> None:
        entry = SURFACE_DEVIATION_MATRIX.get("bsky")
        assert entry is not None
        assert entry["non_engagement_form"] == NonEngagementForm.SHORT

    def test_mastodon_uses_short_form(self) -> None:
        entry = SURFACE_DEVIATION_MATRIX.get("mastodon")
        assert entry is not None
        assert entry["non_engagement_form"] == NonEngagementForm.SHORT

    def test_arena_uses_long_form(self) -> None:
        entry = SURFACE_DEVIATION_MATRIX.get("arena")
        assert entry is not None
        assert entry["non_engagement_form"] == NonEngagementForm.LONG

    def test_osf_preprint_uses_long_form(self) -> None:
        entry = SURFACE_DEVIATION_MATRIX.get("osf_preprint")
        assert entry is not None
        assert entry["non_engagement_form"] == NonEngagementForm.LONG

    def test_every_entry_has_non_engagement_form(self) -> None:
        """Pin: every matrix entry carries the form choice. Required for
        consumers to lookup unambiguously."""
        for surface, entry in SURFACE_DEVIATION_MATRIX.items():
            assert "non_engagement_form" in entry, (
                f"{surface} matrix entry missing non_engagement_form"
            )


class TestExplicitOverride:
    def test_explicit_override_takes_precedence(self, full_byline: Byline) -> None:
        """A caller can pass an explicit ``non_engagement_clause``
        string overriding the form-driven default. Operator-level
        per-artifact override is the design point per beta synthesis
        ('default-on, operator-overridable')."""
        custom = "Custom override clause for this specific artifact."
        block = render_attribution_block(
            full_byline,
            byline_variant=BylineVariant.V2,
            unsettled_variant=UnsettledContributionVariant.V1,
            non_engagement_form=NonEngagementForm.SHORT,
            non_engagement_clause_override=custom,
        )
        assert block.non_engagement_clause == custom
