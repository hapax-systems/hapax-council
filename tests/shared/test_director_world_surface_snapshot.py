"""Tests for Director World Surface snapshot fixtures."""

from __future__ import annotations

from typing import Any, cast

import pytest

from shared.director_world_surface_snapshot import (
    DIRECTOR_MOVE_ROW_REQUIRED_FIELDS,
    DIRECTOR_SNAPSHOT_REQUIRED_FIELDS,
    PUBLIC_LIVE_REQUIRED_OBLIGATIONS,
    REQUIRED_MOVE_STATUSES,
    REQUIRED_SURFACE_FAMILIES,
    DirectorWorldSurfaceMoveRow,
    FallbackMode,
    MoveStatus,
    SurfaceFamily,
    TargetType,
    load_director_world_surface_snapshot_fixtures,
)


def test_director_snapshot_loader_covers_statuses_families_and_fields() -> None:
    fixtures = load_director_world_surface_snapshot_fixtures()

    assert {status.value for status in fixtures.move_statuses} == REQUIRED_MOVE_STATUSES
    assert {family.value for family in fixtures.surface_families} >= REQUIRED_SURFACE_FAMILIES
    assert set(fixtures.director_move_row_required_fields) == set(DIRECTOR_MOVE_ROW_REQUIRED_FIELDS)
    assert set(fixtures.director_snapshot_required_fields) == set(DIRECTOR_SNAPSHOT_REQUIRED_FIELDS)

    rows = fixtures.all_moves()
    assert {row.status.value for row in rows} == REQUIRED_MOVE_STATUSES
    assert {row.surface_family.value for row in rows} >= REQUIRED_SURFACE_FAMILIES


def test_only_public_live_row_satisfies_public_claimability() -> None:
    fixtures = load_director_world_surface_snapshot_fixtures()
    public_live = fixtures.snapshots[0].public_live_moves()

    assert [row.surface_id for row in public_live] == ["audio_route:broadcast.master.normalized"]
    public_row = public_live[0]
    assert public_row.status is MoveStatus.PUBLIC
    assert public_row.availability.available_to_claim_public_live is True
    assert public_row.public_claim_allowed is True
    assert public_row.claim_posture.public_live_claim_allowed is True
    assert {
        obligation.dimension.value
        for obligation in public_row.evidence_obligations
        if obligation.satisfied
    } >= PUBLIC_LIVE_REQUIRED_OBLIGATIONS


def test_static_prompt_hint_row_remains_unavailable_and_unclaimable() -> None:
    fixtures = load_director_world_surface_snapshot_fixtures()
    row = fixtures.require_surface("prompt_hint:director.static-surface-family")

    assert row.surface_family is SurfaceFamily.STATIC_PROMPT_HINT
    assert row.availability.any_available() is False
    assert row.public_claim_allowed is False
    assert row.claim_posture.public_live_claim_allowed is False
    assert row.prompt_projection_payload()["source_refs"] == [
        "prompt-hint:director.static-surface-family"
    ]

    payload = cast("dict[str, Any]", row.model_dump(mode="json"))
    cast("dict[str, Any]", payload["availability"])["available_to_attempt"] = True
    with pytest.raises(ValueError, match="static prompt hints cannot satisfy availability"):
        DirectorWorldSurfaceMoveRow.model_validate(payload)


def test_blocked_hardware_row_is_visible_operator_no_op() -> None:
    fixtures = load_director_world_surface_snapshot_fixtures()
    row = fixtures.require_surface("device:resplay-s4.transport")

    assert row.status is MoveStatus.BLOCKED_HARDWARE_NO_OP
    assert row.target_type is TargetType.HARDWARE_DEVICE
    assert row.fallback.mode is FallbackMode.OPERATOR_REASON
    assert row.fallback.no_op is True
    assert row.blocker_reason
    assert row.prompt_projection_payload()["blocked_reasons"] == ["hardware_absent"]


def test_public_rows_require_all_public_live_obligations() -> None:
    fixtures = load_director_world_surface_snapshot_fixtures()
    public_row = fixtures.require_surface("audio_route:broadcast.master.normalized")
    payload = cast("dict[str, Any]", public_row.model_dump(mode="json"))
    payload["evidence_obligations"] = [
        obligation
        for obligation in cast("list[dict[str, Any]]", payload["evidence_obligations"])
        if obligation["dimension"] != "egress"
    ]

    with pytest.raises(ValueError, match="public rows missing obligations: egress"):
        DirectorWorldSurfaceMoveRow.model_validate(payload)


def test_snapshot_buckets_keep_blocked_and_fallback_rows_visible() -> None:
    fixtures = load_director_world_surface_snapshot_fixtures()
    snapshot = fixtures.snapshots[0]

    assert {row.status for row in snapshot.available_moves} == {
        MoveStatus.MOUNTED,
        MoveStatus.PUBLIC,
    }
    assert {row.status for row in snapshot.blocked_moves} == {
        MoveStatus.BLOCKED,
        MoveStatus.UNAVAILABLE,
        MoveStatus.BLOCKED_HARDWARE_NO_OP,
    }
    assert [row.status for row in snapshot.fallback_moves] == [MoveStatus.STALE]
    assert all(payload["source_refs"] for payload in snapshot.prompt_projection_payloads())


def test_downstream_consumers_can_import_director_surface_vocabulary() -> None:
    assert MoveStatus.DRY_RUN.value == "dry_run"
    assert MoveStatus.BLOCKED_HARDWARE_NO_OP.value == "blocked_hardware_no_op"
    assert SurfaceFamily.PUBLICATION_ENDPOINT.value == "publication_endpoint"
    assert SurfaceFamily.BLOCKED_DECOMMISSIONED.value == "blocked_decommissioned"
