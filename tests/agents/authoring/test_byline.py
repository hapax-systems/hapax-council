"""V0-V5 byline-renderer scaffolding (V5 weave wk1 d1-2 — epsilon).

Pins the contract for ``agents.authoring.byline``: 6 variants V0-V5
covering the spectrum of co-publication attribution shapes the V5
sprint specifies. Variants:

  * **V0 — solo operator legal name**: surfaces that ban co-authorship
    (eg. some bibliographic systems before policy update). Operator's
    legal name only; no Hapax/Claude Code byline.
  * **V1 — operator + Hapax co-author**: academic register; both
    appear in author block; no third co-publisher line.
  * **V2 — operator + Hapax + Claude Code co-publisher**: research
    papers / arXiv / PsyArXiv; full three-way co-publish line.
  * **V3 — PROTO precedent**: Bandcamp/music surfaces; Hapax-as-
    PERFORMER (track credit), operator-as-distributor-of-record
    (account holder, legal name).
  * **V4 — Hapax-canonical with operator-of-record**: surfaces where
    Hapax is the primary author (Manifesto, persona-canon docs); the
    operator credit appears as "operator-of-record" rather than
    co-author.
  * **V5 — unsettled-contribution sentence**: explicit prose about
    authorship indeterminacy as a celebrated polysemic-surface
    channel (per ``feedback_co_publishing_auto_only_unsettled_contribution``).

Spec: V5 weave inflection (2026-04-25T15:08Z), § 2.1 PUB-CITATION-A
+ § 2.4 ``byline.py V0-V5 renderer``, § 11 PROTO precedent (Bandcamp).
"""

from __future__ import annotations

import pytest

from agents.authoring.byline import (
    Byline,
    BylineCoauthor,
    BylineVariant,
    render_byline,
)


@pytest.fixture
def operator_only_byline() -> Byline:
    return Byline(
        operator_legal_name="Real Person",
        operator_referent="Oudepode",
    )


@pytest.fixture
def full_coauthor_byline() -> Byline:
    return Byline(
        operator_legal_name="Real Person",
        operator_referent="Oudepode",
        coauthors=(
            BylineCoauthor(name="Hapax", role="instrument"),
            BylineCoauthor(name="Claude Code", role="co-publisher"),
        ),
    )


# ── Enum ─────────────────────────────────────────────────────────────


class TestBylineVariantEnum:
    def test_six_variants_exist(self) -> None:
        # The V0-V5 contract is a finite enumeration; pin the count
        # so accidental additions are noticed at code-review time.
        assert len(list(BylineVariant)) == 6

    def test_variant_names_are_v0_through_v5(self) -> None:
        names = {v.name for v in BylineVariant}
        assert names == {"V0", "V1", "V2", "V3", "V4", "V5"}


# ── V0 — solo operator legal name ────────────────────────────────────


class TestV0SoloOperator:
    """V0: legal name only, no Hapax/Claude Code reference."""

    def test_v0_renders_legal_name(self, full_coauthor_byline: Byline) -> None:
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V0)
        assert "Real Person" in out

    def test_v0_omits_coauthors(self, full_coauthor_byline: Byline) -> None:
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V0)
        assert "Hapax" not in out
        assert "Claude Code" not in out


# ── V1 — operator + Hapax co-author ──────────────────────────────────


class TestV1OperatorPlusHapax:
    def test_v1_renders_legal_name(self, full_coauthor_byline: Byline) -> None:
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V1)
        assert "Real Person" in out

    def test_v1_renders_hapax(self, full_coauthor_byline: Byline) -> None:
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V1)
        assert "Hapax" in out

    def test_v1_omits_claude_code(self, full_coauthor_byline: Byline) -> None:
        """V1 is academic-register two-author byline; Claude Code as
        co-publisher is a V2 concern only."""
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V1)
        assert "Claude Code" not in out


# ── V2 — full three-way co-publish ───────────────────────────────────


class TestV2FullCopublish:
    def test_v2_includes_all_three(self, full_coauthor_byline: Byline) -> None:
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V2)
        assert "Real Person" in out
        assert "Hapax" in out
        assert "Claude Code" in out


# ── V3 — PROTO precedent (Bandcamp) ──────────────────────────────────


class TestV3ProtoPrecedent:
    """V3: Hapax-as-PERFORMER + operator-as-distributor-of-record.
    Per § 11 PROTO precedent, the operator's legal name is on the
    distributor side, Hapax is on the performer side."""

    def test_v3_renders_legal_name_as_distributor(self, full_coauthor_byline: Byline) -> None:
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V3)
        assert "Real Person" in out

    def test_v3_renders_hapax_as_performer(self, full_coauthor_byline: Byline) -> None:
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V3)
        assert "Hapax" in out

    def test_v3_uses_performer_register(self, full_coauthor_byline: Byline) -> None:
        """V3 is music-platform shape; the prose register includes
        'performer' or 'performance' as the role-of-Hapax marker."""
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V3)
        assert "performer" in out.lower()


# ── V4 — Hapax-canonical with operator-of-record ─────────────────────


class TestV4HapaxCanonical:
    def test_v4_renders_hapax_first_or_primary(self, full_coauthor_byline: Byline) -> None:
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V4)
        # Hapax-as-primary: appears in output AND before any other
        # name (substring index check; not a strict left-anchor since
        # the byline may have a leading prefix).
        assert "Hapax" in out
        # operator-of-record register: legal name follows Hapax.
        hapax_idx = out.lower().find("hapax")
        op_idx = out.find("Real Person")
        assert hapax_idx < op_idx, f"V4 should put Hapax before operator-of-record; got {out!r}"


# ── V5 — unsettled-contribution sentence ─────────────────────────────


class TestV5UnsettledContribution:
    """V5 frames authorship indeterminacy as a CELEBRATED polysemic-
    surface channel. The byline includes prose acknowledging the
    contribution boundary is unsettled — this is intentional, not a
    disclosure-of-uncertainty caveat."""

    def test_v5_renders_unsettled_sentence(self, full_coauthor_byline: Byline) -> None:
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V5)
        # The unsettled-contribution sentence is the variant's
        # signature; pin the presence of one of several allowed
        # phrasings (loose match — final phrasing settles in wk1 d2).
        assert any(
            phrase in out.lower()
            for phrase in (
                "unsettled",
                "indeterminate",
                "co-publication",
                "co-authorship",
            )
        )

    def test_v5_includes_all_three_attributions(self, full_coauthor_byline: Byline) -> None:
        out = render_byline(full_coauthor_byline, variant=BylineVariant.V5)
        assert "Real Person" in out
        assert "Hapax" in out
        assert "Claude Code" in out


# ── Empty / minimal byline ───────────────────────────────────────────


class TestEdgeCases:
    def test_no_coauthors_v2_falls_back_to_legal_name(self, operator_only_byline: Byline) -> None:
        """When the byline has no coauthors, V2 still renders — just
        without the Hapax / Claude Code lines. Pure-additive: no
        crash, no None."""
        out = render_byline(operator_only_byline, variant=BylineVariant.V2)
        assert "Real Person" in out

    def test_render_returns_string(self, full_coauthor_byline: Byline) -> None:
        for variant in BylineVariant:
            out = render_byline(full_coauthor_byline, variant=variant)
            assert isinstance(out, str)
            assert out  # non-empty


# ── Coauthor model ───────────────────────────────────────────────────


class TestBylineCoauthor:
    def test_coauthor_with_role(self) -> None:
        ca = BylineCoauthor(name="Hapax", role="instrument")
        assert ca.name == "Hapax"
        assert ca.role == "instrument"

    def test_coauthor_without_role(self) -> None:
        ca = BylineCoauthor(name="Hapax")
        assert ca.name == "Hapax"
        assert ca.role is None
