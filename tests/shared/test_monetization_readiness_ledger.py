"""Tests for the monetization readiness ledger."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.conversion_target_readiness import (
    REQUIRED_GATE_DIMENSIONS,
    REQUIRED_TARGET_FAMILIES,
    GateDimension,
    load_conversion_target_readiness_matrix,
)
from shared.monetization_readiness_ledger import (
    GateDimensionEvidence,
    MonetizationReadinessSnapshot,
    evaluate_default_monetization_readiness,
    evaluate_monetization_readiness,
)

NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
ALL_DIMS: frozenset[GateDimension] = frozenset(REQUIRED_GATE_DIMENSIONS)


def _evidence(
    *,
    satisfied: frozenset[GateDimension],
    refs_per_dim: dict[GateDimension, tuple[str, ...]] | None = None,
) -> dict[GateDimension, GateDimensionEvidence]:
    """Build a full evidence dict where ``satisfied`` is the satisfied set."""

    refs_per_dim = refs_per_dim or {}
    return {
        dim: GateDimensionEvidence(
            dimension=dim,
            satisfied=dim in satisfied,
            evidence_refs=refs_per_dim.get(dim, ()),
            operator_visible_reason=(f"{dim} satisfied" if dim in satisfied else f"{dim} missing"),
        )
        for dim in REQUIRED_GATE_DIMENSIONS
    }


def _snapshot(
    *,
    satisfied: frozenset[GateDimension],
    source: str = "test",
    refs_per_dim: dict[GateDimension, tuple[str, ...]] | None = None,
) -> MonetizationReadinessSnapshot:
    return MonetizationReadinessSnapshot(
        captured_at=NOW,
        evidence=_evidence(satisfied=satisfied, refs_per_dim=refs_per_dim),
        snapshot_source=source,
    )


def test_empty_snapshot_blocks_every_target_family() -> None:
    snapshot = MonetizationReadinessSnapshot.empty(captured_at=NOW)
    ledger = evaluate_default_monetization_readiness(snapshot)

    assert {entry.target_family_id for entry in ledger.entries} == set(REQUIRED_TARGET_FAMILIES)
    assert set(ledger.blocked_target_families()) == set(REQUIRED_TARGET_FAMILIES)
    assert ledger.public_target_families() == ()
    assert ledger.monetizable_target_families() == ()


def test_full_snapshot_unlocks_public_states_for_at_least_one_family() -> None:
    snapshot = _snapshot(satisfied=ALL_DIMS)
    matrix = load_conversion_target_readiness_matrix()
    ledger = evaluate_monetization_readiness(matrix, snapshot)

    assert len(ledger.public_target_families()) >= 1, (
        "with every gate dimension satisfied at least one family should reach a "
        "public readiness state — otherwise the matrix has degenerated"
    )


def test_full_snapshot_can_reach_monetizable_for_at_least_one_family() -> None:
    snapshot = _snapshot(satisfied=ALL_DIMS)
    matrix = load_conversion_target_readiness_matrix()
    ledger = evaluate_monetization_readiness(matrix, snapshot)

    assert len(ledger.monetizable_target_families()) >= 1, (
        "with every gate dimension satisfied at least one family should reach "
        "public-monetizable; otherwise the matrix forbids monetization across the board"
    )


def test_pinned_requested_state_round_trips_through_decision() -> None:
    snapshot = _snapshot(satisfied=ALL_DIMS)
    matrix = load_conversion_target_readiness_matrix()
    ledger = evaluate_monetization_readiness(
        matrix,
        snapshot,
        requested_states={"grants_fellowships": "private-evidence"},
    )
    grants_entry = ledger.for_target_family("grants_fellowships")
    assert grants_entry.decision.requested_state == "private-evidence"
    # private-evidence with all dims satisfied should be allowed
    assert grants_entry.decision.allowed is True
    assert grants_entry.decision.effective_state == "private-evidence"


def test_partial_snapshot_walks_the_probe_ladder_down_to_allowed_state() -> None:
    """Drop the public-event + egress + monetization gates; the ledger
    should fall back from public-monetizable past public-* down to a
    state the partial evidence supports (or block, whichever the matrix
    actually permits)."""

    partial = ALL_DIMS - {"public_event", "egress", "monetization"}
    snapshot = _snapshot(satisfied=partial)
    matrix = load_conversion_target_readiness_matrix()
    ledger = evaluate_monetization_readiness(matrix, snapshot)

    assert ledger.monetizable_target_families() == (), (
        "monetization gate is missing; nothing should be monetizable"
    )
    # at least one family should still reach private-evidence or dry-run
    non_blocked = [e for e in ledger.entries if e.decision.allowed]
    assert non_blocked, (
        "with wcs+programme+rights+privacy+provenance+labor satisfied at least "
        "one family should be allowed at the private-evidence or dry-run tier"
    )
    for entry in non_blocked:
        assert entry.decision.effective_state in {"private-evidence", "dry-run"}


def test_blocked_entry_carries_missing_dimensions_and_reasons() -> None:
    snapshot = _snapshot(satisfied=frozenset())
    matrix = load_conversion_target_readiness_matrix()
    ledger = evaluate_monetization_readiness(matrix, snapshot)
    entry = ledger.for_target_family("youtube_vod_packaging")
    assert entry.decision.allowed is False
    assert entry.decision.missing_gate_dimensions, (
        "a blocked decision must list the missing dimensions"
    )
    assert entry.operator_visible_reasons, (
        "a blocked entry must surface at least one human-readable reason"
    )


def test_evidence_refs_aggregate_across_relevant_dimensions() -> None:
    refs = {
        "wcs": ("axioms/contracts/some-wcs.yaml",),
        "rights": ("docs/governance/rights-2026-05-01.md",),
        "monetization": ("config/monetization-policy.yaml",),
    }
    snapshot = _snapshot(satisfied=ALL_DIMS, refs_per_dim=refs)
    matrix = load_conversion_target_readiness_matrix()
    ledger = evaluate_monetization_readiness(matrix, snapshot)
    licensing_entry = ledger.for_target_family("licensing")
    # licensing requires monetization at the public-monetizable tier
    assert "config/monetization-policy.yaml" in licensing_entry.evidence_refs


def test_ledger_for_target_family_raises_for_unknown() -> None:
    snapshot = MonetizationReadinessSnapshot.empty(captured_at=NOW)
    ledger = evaluate_default_monetization_readiness(snapshot)
    with pytest.raises(KeyError):
        ledger.for_target_family("not_a_real_family")  # type: ignore[arg-type]


def test_anti_overclaim_signals_never_upgrade_state() -> None:
    """Even with engagement / revenue_potential / trend / operator_desire
    in the snapshot's evidence refs, the matrix gate dimensions are the
    only thing that can move state. Anti-overclaim is enforced by the
    matrix itself, but we sanity-check that the ledger doesn't somehow
    leak those signals into a satisfied dimension."""

    refs = {dim: ("operator wants this!",) for dim in REQUIRED_GATE_DIMENSIONS}
    snapshot = _snapshot(satisfied=frozenset(), refs_per_dim=refs)
    matrix = load_conversion_target_readiness_matrix()
    ledger = evaluate_monetization_readiness(matrix, snapshot)
    assert ledger.monetizable_target_families() == ()
    assert ledger.public_target_families() == ()
