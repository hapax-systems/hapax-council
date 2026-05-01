"""Director control-move WCS normalizer (Phase 1).

Every director move becomes an inspectable grounding attempt. The
normalizer takes an intended move, looks at the runtime evidence
(world-surface snapshot + capability outcome envelope refs), and emits
a typed ``NormalizedDirectorControlMove`` whose ``status`` is one of:

  accepted / no_op / blocked / dry_run / private / public /
  stale / unavailable / blocked_hardware_no_op

The normalizer is the gate that separates *intention* from *outcome*.
It refuses to mark a move ``public`` unless the move's target surface
has all required evidence (egress, audio safety, rights, privacy,
source, public-event). Missing target or blocked hardware degenerates
to ``blocked_hardware_no_op``, never silent success.

Spec: ``hapax-research/specs/2026-04-29-director-world-surface-read-model.md``
Companion: ``hapax-research/specs/2026-04-29-capability-outcome-witness-learning.md``
cc-task: ``director-control-move-wcs-normalizer`` (WSJF 8.8, p1).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.capability_outcome import ExpectedEffect
from shared.director_world_surface_snapshot import (
    DirectorWorldSurfaceMoveRow,
    DirectorWorldSurfaceSnapshot,
    EvidenceStatus,
    FreshnessState,
    MoveStatus,
    SurfaceFamily,
)

# ---------------------------------------------------------------------------
# Input model — what the director loop knows when it formulates a move
# ---------------------------------------------------------------------------


class NormalizerModel(BaseModel):
    """Frozen-by-default base, mirrors the dossier/matrix idiom."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DirectorControlMoveIntent(NormalizerModel):
    """One intended director move before normalization.

    The director's prompt path emits these as candidate actions; the
    normalizer decides whether each can become an executable move and
    whether its outcome can carry public/live authority.
    """

    move_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    target_surface: SurfaceFamily
    target_ref: str = Field(min_length=1)  # canonical ref for the snapshot row
    expected_effect: ExpectedEffect
    public_claim_intended: bool = False
    dry_run_requested: bool = False
    operator_command: bool = False  # True when the move came from a direct operator action


class NormalizedDirectorControlMove(NormalizerModel):
    """Normalized output: a director move bound to its evidence + outcome refs."""

    move_id: str
    status: MoveStatus
    target_surface: SurfaceFamily
    target_ref: str
    expected_effect: ExpectedEffect
    move_row_ref: str | None = None  # snapshot row that resolved this move (if any)
    missing_evidence_dimensions: tuple[str, ...] = ()
    outcome_envelope_id: str | None = None
    operator_visible_reason: str = Field(min_length=1)
    normalized_at: datetime

    @property
    def is_executable(self) -> bool:
        return self.status in {MoveStatus.MOUNTED, MoveStatus.PUBLIC, MoveStatus.PRIVATE}

    @property
    def is_public_authoritative(self) -> bool:
        return self.status == MoveStatus.PUBLIC

    @model_validator(mode="after")
    def _validate_public_carries_evidence(self) -> Self:
        """A PUBLIC move must not list missing evidence dimensions —
        the normalizer must have already rejected it. This is a
        defense-in-depth invariant: if anything sets status=public
        with missing_evidence, the model raises."""

        if self.status == MoveStatus.PUBLIC and self.missing_evidence_dimensions:
            msg = (
                f"move {self.move_id!r}: status=PUBLIC but "
                f"missing_evidence_dimensions={list(self.missing_evidence_dimensions)!r} "
                "— normalizer must downgrade public moves with missing evidence to "
                "BLOCKED or DRY_RUN before construction"
            )
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


# Public-bearing moves require all of these dimensions in the resolved
# snapshot row's evidence_obligations field. Spec acceptance:
# "Public claim-bearing moves fail closed on missing egress/audio/rights/
# privacy/source/public-event evidence."
_PUBLIC_REQUIRED_DIMENSIONS: frozenset[str] = frozenset(
    {
        "egress",
        "audio",
        "rights",
        "privacy",
        "source",
        "public_event",
    }
)


def _find_move_row(
    snapshot: DirectorWorldSurfaceSnapshot,
    target_ref: str,
) -> DirectorWorldSurfaceMoveRow | None:
    """Look up a row by ``target_id`` or ``move_id`` across all buckets."""

    for row in snapshot.all_moves():
        if row.target_id == target_ref or row.move_id == target_ref:
            return row
    return None


def _collect_missing_dimensions(
    row: DirectorWorldSurfaceMoveRow,
    *,
    required: Iterable[str] = _PUBLIC_REQUIRED_DIMENSIONS,
) -> tuple[str, ...]:
    """Return the subset of ``required`` whose evidence is missing /
    stale / blocked on the row's evidence_obligations.

    The row's evidence_obligations reflect WHICH dimensions matter for
    that surface; we cross-check against the public-required set. If a
    required dimension has no obligation entry, treat it as missing.
    """

    obligations_by_dim = {str(ob.dimension): ob for ob in row.evidence_obligations}
    missing: list[str] = []
    for dim in required:
        ob = obligations_by_dim.get(dim)
        if ob is None:
            missing.append(dim)
            continue
        # EvidenceObligation has its own status enum; we conservatively
        # flag anything that isn't FRESH as missing for public-bearing
        # purposes. The exact mapping lives in EvidenceStatus.
        if hasattr(ob, "status") and ob.status in {
            EvidenceStatus.MISSING,
            EvidenceStatus.STALE,
            EvidenceStatus.BLOCKED,
        }:
            missing.append(dim)
    return tuple(sorted(missing))


def normalize_director_control_move(
    intent: DirectorControlMoveIntent,
    snapshot: DirectorWorldSurfaceSnapshot,
    *,
    now: datetime | None = None,
    outcome_envelope_id: str | None = None,
) -> NormalizedDirectorControlMove:
    """Normalize one director-move intent against a runtime snapshot.

    Decision ladder (top-most match wins):

      1. target_ref not in snapshot → ``unavailable``
      2. row's status indicates blocked-hardware (e.g. decommissioned
         surface) → ``blocked_hardware_no_op``
      3. row freshness=stale → ``stale``
      4. dry_run_requested=True → ``dry_run``
      5. public_claim_intended=True AND any required dimension is
         missing/stale/blocked → ``blocked`` (with missing dims listed)
      6. public_claim_intended=True AND all required dims OK → ``public``
      7. private surface (claim_authority_ceiling=private/grounded_private)
         → ``private``
      8. else → ``mounted`` (accepted, not authoritative)
    """

    when = now or datetime.now(tz=UTC)
    row = _find_move_row(snapshot, intent.target_ref)

    if row is None:
        return NormalizedDirectorControlMove(
            move_id=intent.move_id,
            status=MoveStatus.UNAVAILABLE,
            target_surface=intent.target_surface,
            target_ref=intent.target_ref,
            expected_effect=intent.expected_effect,
            move_row_ref=None,
            missing_evidence_dimensions=("target_ref_not_in_snapshot",),
            outcome_envelope_id=outcome_envelope_id,
            operator_visible_reason=(
                f"target_ref {intent.target_ref!r} did not resolve to any row in the "
                "current world-surface snapshot"
            ),
            normalized_at=when,
        )

    if (
        row.surface_family == SurfaceFamily.BLOCKED_DECOMMISSIONED
        or row.status == MoveStatus.BLOCKED_HARDWARE_NO_OP
    ):
        return NormalizedDirectorControlMove(
            move_id=intent.move_id,
            status=MoveStatus.BLOCKED_HARDWARE_NO_OP,
            target_surface=intent.target_surface,
            target_ref=intent.target_ref,
            expected_effect=intent.expected_effect,
            move_row_ref=row.move_id,
            outcome_envelope_id=outcome_envelope_id,
            operator_visible_reason=(
                f"target row {row.move_id!r} reports blocked / decommissioned hardware; "
                "move is recorded as no-op, not success"
            ),
            normalized_at=when,
        )

    if row.freshness.state == FreshnessState.STALE:
        return NormalizedDirectorControlMove(
            move_id=intent.move_id,
            status=MoveStatus.STALE,
            target_surface=intent.target_surface,
            target_ref=intent.target_ref,
            expected_effect=intent.expected_effect,
            move_row_ref=row.move_id,
            outcome_envelope_id=outcome_envelope_id,
            operator_visible_reason=(
                f"row {row.move_id!r} freshness state is stale; move cannot claim live success"
            ),
            normalized_at=when,
        )

    if intent.dry_run_requested:
        return NormalizedDirectorControlMove(
            move_id=intent.move_id,
            status=MoveStatus.DRY_RUN,
            target_surface=intent.target_surface,
            target_ref=intent.target_ref,
            expected_effect=intent.expected_effect,
            move_row_ref=row.move_id,
            outcome_envelope_id=outcome_envelope_id,
            operator_visible_reason="dry_run_requested by intent; move recorded but not applied",
            normalized_at=when,
        )

    if intent.public_claim_intended:
        missing = _collect_missing_dimensions(row)
        if missing:
            return NormalizedDirectorControlMove(
                move_id=intent.move_id,
                status=MoveStatus.BLOCKED,
                target_surface=intent.target_surface,
                target_ref=intent.target_ref,
                expected_effect=intent.expected_effect,
                move_row_ref=row.move_id,
                missing_evidence_dimensions=missing,
                outcome_envelope_id=outcome_envelope_id,
                operator_visible_reason=(
                    f"public claim requested but missing evidence dimensions: {', '.join(missing)}"
                ),
                normalized_at=when,
            )
        return NormalizedDirectorControlMove(
            move_id=intent.move_id,
            status=MoveStatus.PUBLIC,
            target_surface=intent.target_surface,
            target_ref=intent.target_ref,
            expected_effect=intent.expected_effect,
            move_row_ref=row.move_id,
            outcome_envelope_id=outcome_envelope_id,
            operator_visible_reason=("all public-required evidence dimensions present and fresh"),
            normalized_at=when,
        )

    # Default: private/mounted, depending on the row's claim authority.
    # The row's claim_authority_ceiling mirrors claim_posture.authority_ceiling
    # per the row's own model_validator; we use the top-level field directly.
    private_ceiling = "private" in str(row.claim_authority_ceiling).lower()
    if private_ceiling:
        return NormalizedDirectorControlMove(
            move_id=intent.move_id,
            status=MoveStatus.PRIVATE,
            target_surface=intent.target_surface,
            target_ref=intent.target_ref,
            expected_effect=intent.expected_effect,
            move_row_ref=row.move_id,
            outcome_envelope_id=outcome_envelope_id,
            operator_visible_reason=(
                f"row {row.move_id!r} ceiling is private; move accepted at private authority"
            ),
            normalized_at=when,
        )
    return NormalizedDirectorControlMove(
        move_id=intent.move_id,
        status=MoveStatus.MOUNTED,
        target_surface=intent.target_surface,
        target_ref=intent.target_ref,
        expected_effect=intent.expected_effect,
        move_row_ref=row.move_id,
        outcome_envelope_id=outcome_envelope_id,
        operator_visible_reason="move accepted as mounted (not public-authoritative)",
        normalized_at=when,
    )
