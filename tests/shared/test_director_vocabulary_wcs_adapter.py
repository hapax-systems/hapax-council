"""Tests for the WCS-snapshot → director-vocabulary adapter."""

from __future__ import annotations

import pytest

from shared.director_vocabulary_wcs_adapter import vocabulary_entries_from_wcs_snapshot
from shared.director_world_surface_snapshot import (
    DirectorWorldSurfaceSnapshot,
    MoveStatus,
    TargetType,
    load_director_world_surface_snapshot_fixtures,
)


@pytest.fixture(scope="module")
def fixture_snapshot() -> DirectorWorldSurfaceSnapshot:
    fixtures = load_director_world_surface_snapshot_fixtures()
    return fixtures.snapshots[0]


# ── Status coverage ────────────────────────────────────────────────────


def test_adapter_emits_entry_per_scenic_target(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    scenic_targets = {
        TargetType.AUDIO_ROUTE,
        TargetType.VIDEO_SURFACE,
        TargetType.CONTROL_SURFACE,
        TargetType.PUBLIC_EVENT,
        TargetType.HARDWARE_DEVICE,
        TargetType.ARCHIVE,
    }
    expected = sum(1 for row in fixture_snapshot.all_moves() if row.target_type in scenic_targets)
    assert len(entries) == expected
    assert expected > 0


def test_adapter_filters_non_scenic_target_types(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    """Tools, model routes, state files, services, prompt hints are not scenic."""
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    emitted_target_ids = {entry.target_id for entry in entries}
    non_scenic = {
        TargetType.TOOL,
        TargetType.MODEL_ROUTE,
        TargetType.STATE_FILE,
        TargetType.SERVICE,
        TargetType.PROMPT_HINT,
    }
    for row in fixture_snapshot.all_moves():
        if row.target_type in non_scenic:
            assert row.target_id not in emitted_target_ids, (
                f"non-scenic {row.target_type.value} {row.target_id} leaked into vocabulary"
            )


def test_adapter_does_not_duplicate_build_director_vocabulary_substrate_seam() -> None:
    """The adapter is meant to extend, not re-derive, the existing seam.

    Verifies the adapter's emitted entries reference the WCS snapshot
    `move_id`, not the substrate-seam ids that `build_director_vocabulary()`
    consumes. This guards against accidental seam collision with the
    existing substrate/lane builder.
    """
    fixtures = load_director_world_surface_snapshot_fixtures()
    snapshot = fixtures.snapshots[0]
    entries = vocabulary_entries_from_wcs_snapshot(snapshot)
    for entry in entries:
        assert entry.evidence
        assert entry.evidence[0].source_type == "director_world_surface_snapshot"
        assert entry.evidence[0].ref.startswith("move.")


# ── Per-status semantics ──────────────────────────────────────────────


def test_mounted_or_public_row_is_commandable(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    by_id = {entry.evidence[0].ref: entry for entry in entries}
    for row in fixture_snapshot.all_moves():
        if row.status not in {MoveStatus.MOUNTED, MoveStatus.PUBLIC}:
            continue
        if row.move_id not in by_id:
            continue
        entry = by_id[row.move_id]
        assert entry.verbs == ["foreground", "hold"]
        assert entry.unavailable_reason is None
        assert entry.public_claim_allowed == row.public_claim_allowed


def test_private_row_carries_private_only_marker(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    by_id = {entry.evidence[0].ref: entry for entry in entries}
    for row in fixture_snapshot.all_moves():
        if row.status is not MoveStatus.PRIVATE or row.move_id not in by_id:
            continue
        entry = by_id[row.move_id]
        assert entry.verbs == ["foreground", "hold"]
        assert entry.public_claim_allowed is False
        assert entry.unavailable_reason == "private_only"


def test_dry_run_row_holds_only_with_dry_run_fallback(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    by_id = {entry.evidence[0].ref: entry for entry in entries}
    for row in fixture_snapshot.all_moves():
        if row.status is not MoveStatus.DRY_RUN or row.move_id not in by_id:
            continue
        entry = by_id[row.move_id]
        assert entry.verbs == ["hold"]
        assert entry.public_claim_allowed is False
        assert entry.unavailable_reason == "dry_run_only"


def test_stale_row_holds_only_with_stale_marker(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    by_id = {entry.evidence[0].ref: entry for entry in entries}
    for row in fixture_snapshot.all_moves():
        if row.status is not MoveStatus.STALE or row.move_id not in by_id:
            continue
        entry = by_id[row.move_id]
        assert entry.verbs == ["hold"]
        assert entry.unavailable_reason == "stale"


def test_blocked_row_has_no_verbs_and_carries_blocker_reason(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    by_id = {entry.evidence[0].ref: entry for entry in entries}
    blocked_statuses = {
        MoveStatus.BLOCKED,
        MoveStatus.UNAVAILABLE,
        MoveStatus.BLOCKED_HARDWARE_NO_OP,
    }
    for row in fixture_snapshot.all_moves():
        if row.status not in blocked_statuses or row.move_id not in by_id:
            continue
        entry = by_id[row.move_id]
        assert entry.verbs == []
        assert entry.public_claim_allowed is False
        assert entry.unavailable_reason is not None
        if row.blocker_reason:
            assert entry.unavailable_reason == row.blocker_reason


# ── Public-claim posture preservation ─────────────────────────────────


def test_public_claim_only_allowed_when_wcs_says_so(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    by_id = {entry.evidence[0].ref: entry for entry in entries}
    for row in fixture_snapshot.all_moves():
        if row.move_id not in by_id:
            continue
        entry = by_id[row.move_id]
        assert entry.public_claim_allowed == row.public_claim_allowed


def test_at_most_one_public_claim_allowed_entry(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    """Public claimability is a strong fail-closed posture; the WCS fixture
    has exactly one row with public_claim_allowed=True (the broadcast
    master) — the adapter must preserve that count."""
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    public_allowed = [e for e in entries if e.public_claim_allowed]
    assert len(public_allowed) == 1
    assert public_allowed[0].verbs == ["foreground", "hold"]


# ── Evidence projection ──────────────────────────────────────────────


def test_evidence_carries_freshness_and_move_id(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    for entry in entries:
        ev = entry.evidence[0]
        assert ev.source_type == "director_world_surface_snapshot"
        assert ev.ref.startswith("move.")
        assert ev.detail.startswith("wcs_move:")
        assert ev.observed_at  # checked_at always present on the snapshot freshness


# ── Source-refs preservation ──────────────────────────────────────────


def test_source_refs_passed_through(
    fixture_snapshot: DirectorWorldSurfaceSnapshot,
) -> None:
    entries = vocabulary_entries_from_wcs_snapshot(fixture_snapshot)
    by_id = {entry.evidence[0].ref: entry for entry in entries}
    for row in fixture_snapshot.all_moves():
        if row.move_id not in by_id:
            continue
        assert by_id[row.move_id].source_refs == list(row.source_refs)
