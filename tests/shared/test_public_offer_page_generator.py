"""Tests for the public offer page generator.

Covers the no-perk doctrine invariants, readiness gating, refusal-page
fallback, and that prohibited fields cannot be smuggled into either
shape via Pydantic's ``extra="forbid"``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.conversion_target_readiness import REQUIRED_GATE_DIMENSIONS, GateDimension
from shared.monetization_readiness_ledger import (
    GateDimensionEvidence,
    MonetizationReadinessLedger,
    MonetizationReadinessSnapshot,
    evaluate_default_monetization_readiness,
)
from shared.public_offer_page_generator import (
    PROHIBITED_PAGE_FIELDS,
    AggregateReceiptSummary,
    OfferPage,
    OfferPageKind,
    RefusalEntry,
    RefusalPage,
    SupportRail,
    generate_offer_page,
    render_offer_page_markdown,
)
from shared.support_surface_registry import SupportSurfaceRegistry, load_support_surface_registry

NOW = datetime(2026, 5, 2, 7, 30, tzinfo=UTC)
ALL_DIMS: frozenset[GateDimension] = frozenset(REQUIRED_GATE_DIMENSIONS)


def _empty_ledger() -> MonetizationReadinessLedger:
    snap = MonetizationReadinessSnapshot.empty(captured_at=NOW)
    return evaluate_default_monetization_readiness(snap)


def _full_ledger() -> MonetizationReadinessLedger:
    snap = MonetizationReadinessSnapshot(
        captured_at=NOW,
        snapshot_source="test",
        evidence={
            dim: GateDimensionEvidence(
                dimension=dim,
                satisfied=dim in ALL_DIMS,
                evidence_refs=(f"evidence:{dim}",),
                operator_visible_reason=f"{dim} satisfied",
            )
            for dim in REQUIRED_GATE_DIMENSIONS
        },
    )
    return evaluate_default_monetization_readiness(snap)


def _registry() -> SupportSurfaceRegistry:
    return load_support_surface_registry()


def _all_registry_refs() -> dict[str, bool]:
    registry = load_support_surface_registry()
    return {gate: True for surface in registry.surfaces for gate in surface.readiness_gates}


# ── Refusal-page path (default fail-closed) ─────────────────────────


class TestRefusalPagePath:
    def test_empty_snapshot_yields_refusal_page(self) -> None:
        page = generate_offer_page(_registry(), _empty_ledger(), now=NOW)
        assert isinstance(page, RefusalPage)
        assert page.kind == OfferPageKind.REFUSAL
        assert page.readiness_state == "blocked"
        assert page.target_family_id == "support_prompt"

    def test_refusal_page_includes_blocked_reason_pointing_at_state(self) -> None:
        page = generate_offer_page(_registry(), _empty_ledger(), now=NOW)
        assert isinstance(page, RefusalPage)
        assert "support_prompt" in page.blocked_reason
        assert "public-safe" in page.blocked_reason  # mentions required support-copy state

    def test_refusal_page_missing_evidence_dimensions_is_a_tuple(self) -> None:
        # When the entry's decision falls back to "blocked" without a
        # specific requested state, relevant_dimensions can be empty —
        # the field just needs to be a well-typed tuple, not necessarily
        # populated (the blocked_reason carries the diagnostic instead).
        page = generate_offer_page(_registry(), _empty_ledger(), now=NOW)
        assert isinstance(page, RefusalPage)
        assert isinstance(page.missing_evidence_dimensions, tuple)

    def test_refusal_page_includes_refusal_brief_refs_from_registry(self) -> None:
        page = generate_offer_page(_registry(), _empty_ledger(), now=NOW)
        assert isinstance(page, RefusalPage)
        assert page.refusal_brief_refs, (
            "registry's refusal_conversion surfaces must surface their refusal "
            "briefs on the public refusal page (operator stance is publishable)"
        )

    def test_unknown_target_family_raises(self) -> None:
        with pytest.raises(ValueError, match="not present in ledger"):
            generate_offer_page(
                _registry(),
                _empty_ledger(),
                target_family_id="not_a_real_family",  # type: ignore[arg-type]
                now=NOW,
            )


# ── No-perk invariant — Pydantic enforces via extra="forbid" ────────


class TestNoPerkInvariants:
    def test_offer_page_rejects_payer_identity_field(self) -> None:
        with pytest.raises(ValidationError):
            OfferPage(
                generated_at=NOW,
                target_family_id="support_prompt",
                readiness_state="public-live",
                no_perk_doctrine_summary="x",
                rails=(),
                refusal_entries=(
                    RefusalEntry(
                        surface_id="x",
                        display_name="X",
                        refusal_brief_refs=("ref",),
                    ),
                ),
                aggregate_receipt_summary=None,
                artifact_links=(),
                payer_identity="alice",  # type: ignore[call-arg]
            )

    def test_offer_page_rejects_leaderboard_field(self) -> None:
        with pytest.raises(ValidationError):
            OfferPage(
                generated_at=NOW,
                target_family_id="support_prompt",
                readiness_state="public-live",
                no_perk_doctrine_summary="x",
                rails=(),
                refusal_entries=(
                    RefusalEntry(
                        surface_id="x",
                        display_name="X",
                        refusal_brief_refs=("ref",),
                    ),
                ),
                aggregate_receipt_summary=None,
                artifact_links=(),
                leaderboard=[],  # type: ignore[call-arg]
            )

    def test_support_rail_rejects_perks_field(self) -> None:
        with pytest.raises(ValidationError):
            SupportRail(
                surface_id="x",
                display_name="X",
                money_form="grant",
                allowed_public_copy=("c",),
                perks=("a",),  # type: ignore[call-arg]
            )

    def test_prohibited_fields_match_doctrine_constants(self) -> None:
        """Pin the doctrine constant against accidental drift."""
        for field in PROHIBITED_PAGE_FIELDS:
            assert field not in OfferPage.model_fields, (
                f"{field!r} must NEVER appear in OfferPage model"
            )
            assert field not in SupportRail.model_fields, (
                f"{field!r} must NEVER appear in SupportRail model"
            )
            assert field not in RefusalPage.model_fields, (
                f"{field!r} must NEVER appear in RefusalPage model"
            )


# ── State-gating invariants ─────────────────────────────────────────


class TestStateGating:
    def test_offer_page_validator_rejects_blocked_state(self) -> None:
        with pytest.raises(ValidationError, match="cannot be constructed in state"):
            OfferPage(
                generated_at=NOW,
                target_family_id="support_prompt",
                readiness_state="blocked",
                no_perk_doctrine_summary="x",
                rails=(),
                refusal_entries=(
                    RefusalEntry(
                        surface_id="x",
                        display_name="X",
                        refusal_brief_refs=("ref",),
                    ),
                ),
                aggregate_receipt_summary=None,
                artifact_links=(),
            )

    def test_full_ledger_without_support_refs_still_refuses(self) -> None:
        page = generate_offer_page(_registry(), _full_ledger(), now=NOW)

        assert isinstance(page, RefusalPage)
        assert "bootstrap-needed" in page.blocked_reason
        assert "support_surface_registry.no_perk_copy_valid" in page.missing_evidence_dimensions

    def test_full_ledger_with_support_refs_renders_offer(self) -> None:
        page = generate_offer_page(
            _registry(),
            _full_ledger(),
            support_readiness_refs=_all_registry_refs(),
            now=NOW,
        )

        assert isinstance(page, OfferPage)
        assert page.readiness_state == "public-monetizable"
        assert page.rails
        assert page.aggregate_receipt_summary is not None
        assert "No access" in page.no_perk_doctrine_summary

    def test_offer_page_requires_at_least_one_rail_or_refusal(self) -> None:
        with pytest.raises(ValidationError, match="at least one rail OR one refusal"):
            OfferPage(
                generated_at=NOW,
                target_family_id="support_prompt",
                readiness_state="public-live",
                no_perk_doctrine_summary="x",
                rails=(),
                refusal_entries=(),
                aggregate_receipt_summary=None,
                artifact_links=(),
            )


# ── Markdown rendering ──────────────────────────────────────────────


class TestRendering:
    def test_refusal_page_markdown_is_pure_markdown(self) -> None:
        page = generate_offer_page(_registry(), _empty_ledger(), now=NOW)
        md = render_offer_page_markdown(page)
        # No HTML, no JS, no external assets
        assert "<script" not in md.lower()
        assert "<iframe" not in md.lower()
        assert "javascript:" not in md.lower()
        # Heading + state line present
        assert "# Support Currently Unavailable" in md
        assert "blocked" in md

    def test_offer_page_markdown_includes_no_perk_summary(self) -> None:
        # Construct manually with valid public-live state for renderer test
        page = OfferPage(
            generated_at=NOW,
            target_family_id="support_prompt",
            readiness_state="public-live",
            no_perk_doctrine_summary="No perks. No supporter identity. Just artefacts.",
            rails=(
                SupportRail(
                    surface_id="github_sponsors",
                    display_name="GitHub Sponsors",
                    money_form="recurring patronage",
                    allowed_public_copy=("Support open research",),
                ),
            ),
            refusal_entries=(),
            aggregate_receipt_summary=AggregateReceiptSummary(
                aggregate_count=42,
                public_fields=("count", "currency", "period_start", "period_end"),
            ),
            artifact_links=("https://example.com/artefact",),
        )
        md = render_offer_page_markdown(page)
        assert "No perks" in md
        assert "GitHub Sponsors" in md
        assert "Support open research" in md
        assert "count: 42" in md
        assert "https://example.com/artefact" in md
        # Forbidden elements never appear
        assert "leaderboard" not in md.lower()
        assert "shoutout" not in md.lower()
        assert "subscriber" not in md.lower()
