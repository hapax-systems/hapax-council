"""Tests for the director control-move WCS normalizer (Phase 1).

The normalizer's contract: turn an intended director move + a runtime
world-surface snapshot into a typed ``NormalizedDirectorControlMove``
whose ``status`` reflects whether the move can be executed and at what
authority. The decision ladder is documented inline in
``shared/director_control_move_normalizer.py``.

These tests mock ``_find_move_row`` to inject simple row objects rather
than constructing full ``DirectorWorldSurfaceMoveRow`` instances (which
require ~30 cross-validated fields). The contract under test is the
ladder logic, not the existing snapshot model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from shared.capability_outcome import ExpectedEffect
from shared.director_control_move_normalizer import (
    DirectorControlMoveIntent,
    NormalizedDirectorControlMove,
    normalize_director_control_move,
)
from shared.director_world_surface_snapshot import (
    EvidenceStatus,
    FreshnessState,
    MoveStatus,
    SurfaceFamily,
)

NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)


def _make_intent(
    *,
    move_id: str = "test-move",
    target_ref: str = "test-target",
    public: bool = False,
    dry_run: bool = False,
    target_surface: str = "audio_route",
) -> DirectorControlMoveIntent:
    return DirectorControlMoveIntent(
        move_id=move_id,
        target_surface=target_surface,  # type: ignore[arg-type]
        target_ref=target_ref,
        expected_effect=ExpectedEffect(
            effect_id="test-effect",
            description="test effect",
            witness_class="runtime_event",
            public_claim_bearing=public,
            action_bearing=True,
        ),
        public_claim_intended=public,
        dry_run_requested=dry_run,
    )


def _make_obligation(dim: str, status: EvidenceStatus = EvidenceStatus.FRESH):
    return SimpleNamespace(dimension=dim, status=status)


def _make_row(
    *,
    move_id: str = "move.test",
    target_id: str = "test-target",
    status: MoveStatus = MoveStatus.MOUNTED,
    surface_family: SurfaceFamily = SurfaceFamily.AUDIO_ROUTE,
    freshness_state: FreshnessState = FreshnessState.FRESH,
    claim_authority_ceiling: str = "private",
    obligations: list | None = None,
):
    """Build a SimpleNamespace mock row matching DirectorWorldSurfaceMoveRow's
    accessed shape. The normalizer only reads a small subset of fields."""

    if obligations is None:
        obligations = [
            _make_obligation(d)
            for d in ("egress", "audio", "rights", "privacy", "source", "public_event")
        ]
    return SimpleNamespace(
        move_id=move_id,
        target_id=target_id,
        status=status,
        surface_family=surface_family,
        freshness=SimpleNamespace(state=freshness_state),
        claim_authority_ceiling=claim_authority_ceiling,
        evidence_obligations=obligations,
    )


def _patch_snapshot(row=None):
    """Patch _find_move_row to return ``row`` regardless of snapshot input."""

    return patch(
        "shared.director_control_move_normalizer._find_move_row",
        return_value=row,
    )


def test_unavailable_when_target_ref_not_in_snapshot() -> None:
    intent = _make_intent()
    with _patch_snapshot(row=None):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.UNAVAILABLE
    assert "target_ref_not_in_snapshot" in result.missing_evidence_dimensions
    assert not result.is_executable


def test_blocked_hardware_no_op_when_surface_decommissioned() -> None:
    row = _make_row(surface_family=SurfaceFamily.BLOCKED_DECOMMISSIONED)
    intent = _make_intent()
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.BLOCKED_HARDWARE_NO_OP
    assert "blocked / decommissioned" in result.operator_visible_reason


def test_blocked_hardware_no_op_when_row_status_says_so() -> None:
    """Even with a non-decommissioned surface_family, a row whose own
    status is BLOCKED_HARDWARE_NO_OP should propagate."""

    row = _make_row(status=MoveStatus.BLOCKED_HARDWARE_NO_OP)
    intent = _make_intent()
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.BLOCKED_HARDWARE_NO_OP


def test_stale_when_row_freshness_stale() -> None:
    row = _make_row(freshness_state=FreshnessState.STALE)
    intent = _make_intent()
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.STALE
    assert not result.is_executable


def test_dry_run_when_intent_requests_it() -> None:
    row = _make_row()
    intent = _make_intent(dry_run=True)
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.DRY_RUN


def test_public_succeeds_when_all_required_evidence_fresh() -> None:
    row = _make_row()  # all 6 obligations FRESH by default
    intent = _make_intent(public=True)
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.PUBLIC
    assert result.is_public_authoritative
    assert result.missing_evidence_dimensions == ()


def test_public_blocked_when_egress_evidence_missing() -> None:
    obligations = [
        _make_obligation("egress", EvidenceStatus.MISSING),
        _make_obligation("audio"),
        _make_obligation("rights"),
        _make_obligation("privacy"),
        _make_obligation("source"),
        _make_obligation("public_event"),
    ]
    row = _make_row(obligations=obligations)
    intent = _make_intent(public=True)
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.BLOCKED
    assert "egress" in result.missing_evidence_dimensions
    assert "missing evidence dimensions" in result.operator_visible_reason


def test_public_blocked_when_required_dimension_missing_entirely() -> None:
    """If the row's evidence_obligations doesn't even mention a required
    dimension (e.g. row has only egress + audio), public-bearing
    moves must fail closed for the un-listed dimensions."""

    row = _make_row(obligations=[_make_obligation("egress"), _make_obligation("audio")])
    intent = _make_intent(public=True)
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.BLOCKED
    # rights / privacy / source / public_event all unlisted → all missing
    for dim in ("rights", "privacy", "source", "public_event"):
        assert dim in result.missing_evidence_dimensions


def test_private_when_row_ceiling_is_private() -> None:
    row = _make_row(claim_authority_ceiling="private_only")
    intent = _make_intent(public=False)
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.PRIVATE


def test_mounted_default_when_neither_public_nor_private() -> None:
    row = _make_row(claim_authority_ceiling="public_visible")
    intent = _make_intent(public=False)
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.MOUNTED
    assert result.is_executable


def test_normalized_move_validator_rejects_public_with_missing_evidence() -> None:
    """Defense-in-depth: if anything constructs a NormalizedDirectorControlMove
    with status=PUBLIC and a non-empty missing_evidence_dimensions, the
    model itself raises. The normalizer's ladder should never let this
    through; this validator is the last-resort fence."""

    with pytest.raises(ValueError, match="status=PUBLIC but"):
        NormalizedDirectorControlMove(
            move_id="bad",
            status=MoveStatus.PUBLIC,
            target_surface=SurfaceFamily.AUDIO_ROUTE,
            target_ref="t",
            expected_effect=ExpectedEffect(
                effect_id="e",
                description="d",
                witness_class="w",
                public_claim_bearing=True,
                action_bearing=False,
            ),
            missing_evidence_dimensions=("egress",),
            operator_visible_reason="should not be allowed",
            normalized_at=NOW,
        )


def test_dry_run_takes_precedence_over_public_intent() -> None:
    """If both public_claim_intended AND dry_run_requested are set, the
    dry-run wins — no public claim emerges from a dry-run move."""

    row = _make_row()
    intent = _make_intent(public=True, dry_run=True)
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.DRY_RUN
    assert not result.is_public_authoritative


def test_stale_takes_precedence_over_public() -> None:
    """A stale row cannot carry public authority even if all evidence
    obligations look fresh — staleness is structural."""

    row = _make_row(freshness_state=FreshnessState.STALE)
    intent = _make_intent(public=True)
    with _patch_snapshot(row=row):
        result = normalize_director_control_move(intent, snapshot=None, now=NOW)  # type: ignore[arg-type]
    assert result.status == MoveStatus.STALE
    assert not result.is_public_authoritative
