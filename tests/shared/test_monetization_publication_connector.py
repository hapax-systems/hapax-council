"""Tests for shared.monetization_publication_connector."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.conversion_target_readiness import ConversionReadinessDecision
from shared.monetization_publication_connector import (
    REVENUE_BEARING_SURFACES,
    MonetizationDecision,
    check_surface_monetization_readiness,
)
from shared.monetization_readiness_ledger import (
    MonetizationReadinessLedger,
    TargetFamilyLedgerEntry,
)


def _make_ledger(entries: list[TargetFamilyLedgerEntry]) -> MonetizationReadinessLedger:
    return MonetizationReadinessLedger(
        snapshot_captured_at=datetime.now(UTC),
        snapshot_source="test",
        entries=tuple(entries),
    )


def _make_entry(
    family_id: str,
    *,
    allowed: bool,
    effective_state: str = "private-evidence",
    missing: tuple[str, ...] = (),
    reason: str = "test reason",
) -> TargetFamilyLedgerEntry:
    return TargetFamilyLedgerEntry(
        target_family_id=family_id,
        decision=ConversionReadinessDecision(
            target_family_id=family_id,
            requested_state="public-monetizable",
            effective_state=effective_state,
            allowed=allowed,
            missing_gate_dimensions=missing,
            operator_visible_reason=reason,
        ),
        relevant_dimensions=("provenance", "egress", "monetization"),
        satisfied_dimensions=("provenance",)
        if missing
        else ("provenance", "egress", "monetization"),
        evidence_refs=("test-evidence-ref",),
        operator_visible_reasons=(reason,) if not allowed else (),
    )


def test_non_revenue_surface_always_proceeds() -> None:
    result = check_surface_monetization_readiness("omg-weblog")
    assert result.decision == MonetizationDecision.PROCEED
    assert not result.revenue_bearing


def test_non_revenue_surface_ignores_ledger() -> None:
    result = check_surface_monetization_readiness("mastodon-post", ledger=None)
    assert result.decision == MonetizationDecision.PROCEED


def test_revenue_surface_without_ledger_blocks() -> None:
    result = check_surface_monetization_readiness("github-sponsors", ledger=None)
    assert result.decision == MonetizationDecision.NOT_READY
    assert result.revenue_bearing


def test_revenue_surface_allowed_proceeds() -> None:
    entry = _make_entry("support_prompt", allowed=True, effective_state="public-monetizable")
    ledger = _make_ledger([entry])
    result = check_surface_monetization_readiness("github-sponsors", ledger=ledger)
    assert result.decision == MonetizationDecision.PROCEED
    assert result.revenue_bearing
    assert "public-monetizable" in result.reason


def test_revenue_surface_not_ready_blocks() -> None:
    entry = _make_entry(
        "support_prompt",
        allowed=False,
        missing=("egress", "monetization"),
        reason="missing egress and monetization gates",
    )
    ledger = _make_ledger([entry])
    result = check_surface_monetization_readiness("github-sponsors", ledger=ledger)
    assert result.decision == MonetizationDecision.NOT_READY
    assert result.revenue_bearing
    assert len(result.missing_dimensions) > 0


def test_missing_target_family_blocks() -> None:
    ledger = _make_ledger([])
    result = check_surface_monetization_readiness("youtube-monetized", ledger=ledger)
    assert result.decision == MonetizationDecision.NOT_READY
    assert "youtube_vod_packaging" in result.reason


def test_surface_to_target_family_mapping() -> None:
    entry = _make_entry("support_prompt", allowed=True, effective_state="public-monetizable")
    ledger = _make_ledger([entry])
    result = check_surface_monetization_readiness("ko-fi", ledger=ledger)
    assert result.decision == MonetizationDecision.PROCEED


def test_all_revenue_surfaces_are_known() -> None:
    for surface in REVENUE_BEARING_SURFACES:
        result = check_surface_monetization_readiness(surface, ledger=None)
        assert result.revenue_bearing, f"{surface} should be revenue-bearing"
