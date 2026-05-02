"""Director read-model projection for content programme format actions.

The projection is deliberately fixture-backed: it joins the content programme
run envelopes, the format WCS requirement matrix, and the director world-surface
snapshot rows without authorizing availability from static hints.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.director_world_surface_snapshot import (
    DirectorWorldSurfaceMoveRow,
    DirectorWorldSurfaceSnapshot,
    DirectorWorldSurfaceSnapshotError,
    MoveStatus,
    load_director_world_surface_snapshot_fixtures,
)
from shared.format_wcs_requirement_matrix import (
    FormatWCSRequirementMatrix,
    WCSSurfaceRequirement,
    load_format_wcs_requirement_matrix,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTENT_PROGRAMME_RUN_ENVELOPE_FIXTURES = (
    REPO_ROOT / "config" / "content-programme-run-envelope-fixtures.json"
)

REQUIRED_ACTION_STATES = frozenset(
    {
        "private",
        "dry_run",
        "archive_only",
        "public_live",
        "blocked",
        "stale",
        "unavailable",
        "monetization_blocked",
    }
)


class DirectorProgrammeFormatActionError(ValueError):
    """Raised when programme format action projection fails closed."""


class ProgrammeFormatActionState(StrEnum):
    PRIVATE = "private"
    DRY_RUN = "dry_run"
    ARCHIVE_ONLY = "archive_only"
    PUBLIC_LIVE = "public_live"
    BLOCKED = "blocked"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    MONETIZATION_BLOCKED = "monetization_blocked"


class SurfaceRefState(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    AVAILABLE = "available"
    MISSING = "missing"
    BLOCKED = "blocked"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class ProgrammeWCSSurfaceRef(BaseModel):
    """One WCS surface reference displayed to the director for a format action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    surface_id: str = Field(min_length=1)
    state: SurfaceRefState
    source: Literal["format_wcs_matrix", "run_envelope", "director_snapshot"]
    family: str | None = None
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    reason_code: str | None = None

    @model_validator(mode="after")
    def _blocked_or_missing_surfaces_need_reason(self) -> Self:
        if (
            self.state
            in {
                SurfaceRefState.MISSING,
                SurfaceRefState.BLOCKED,
                SurfaceRefState.STALE,
                SurfaceRefState.UNAVAILABLE,
            }
            and not self.reason_code
        ):
            raise ValueError(f"{self.surface_id} is {self.state.value} without reason_code")
        return self


class DirectorProgrammeFormatActionRow(BaseModel):
    """One director-consumable action row for a content programme format."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    action_id: str = Field(pattern=r"^programme-format-action:[a-z0-9_.:-]+$")
    format_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    action_state: ProgrammeFormatActionState
    requested_mode: str = Field(min_length=1)
    effective_mode: str = Field(min_length=1)
    final_status: str = Field(min_length=1)
    run_id: str | None = None
    fixture_case: str | None = None
    source_refs: tuple[str, ...] = Field(min_length=1)
    director_snapshot_ref: str
    format_matrix_ref: str
    run_envelope_ref: str | None = None
    required_wcs_surfaces: tuple[ProgrammeWCSSurfaceRef, ...] = Field(min_length=1)
    optional_wcs_surfaces: tuple[ProgrammeWCSSurfaceRef, ...] = Field(default_factory=tuple)
    available_surface_refs: tuple[str, ...] = Field(default_factory=tuple)
    missing_surface_refs: tuple[str, ...] = Field(default_factory=tuple)
    blocked_surface_refs: tuple[ProgrammeWCSSurfaceRef, ...] = Field(default_factory=tuple)
    director_moves: tuple[str, ...] = Field(min_length=1)
    grounding_question_ref: str = Field(min_length=1)
    permitted_claim_shape_ref: str = Field(min_length=1)
    claim_authority_ceiling: str = Field(min_length=1)
    public_claim_allowed: bool
    public_live_claim_allowed: bool
    archive_claim_allowed: bool
    monetization_claim_allowed: bool
    evidence_obligations: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    rights_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    conversion_paths: tuple[str, ...] = Field(default_factory=tuple)
    conversion_obligations: tuple[str, ...] = Field(default_factory=tuple)
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    operator_visible_reason: str = Field(min_length=1)
    static_hint_authorizes_availability: Literal[False] = False

    @model_validator(mode="after")
    def _validate_fail_closed_programme_action(self) -> Self:
        if self._has_static_hint_source():
            if self.action_state is not ProgrammeFormatActionState.UNAVAILABLE:
                raise ValueError("static hints cannot authorize available programme actions")
            if self.public_claim_allowed or self.public_live_claim_allowed:
                raise ValueError("static hints cannot authorize public/live programme actions")
        if self.public_live_claim_allowed and not self.public_claim_allowed:
            raise ValueError("public_live_claim_allowed requires public_claim_allowed")
        if self.monetization_claim_allowed and not self.public_live_claim_allowed:
            raise ValueError("monetization claimability requires public-live claimability first")
        if self.action_state is ProgrammeFormatActionState.PUBLIC_LIVE:
            if not self.public_live_claim_allowed or not self.public_claim_allowed:
                raise ValueError("public-live format actions require public-live claim posture")
            if not self.public_event_refs or not self.witness_refs or not self.rights_refs:
                raise ValueError("public-live format actions require public event, witness, rights")
            if self.blocked_reasons or self.missing_surface_refs or self.blocked_surface_refs:
                raise ValueError("public-live format actions cannot have blockers")
        if self.action_state in {
            ProgrammeFormatActionState.BLOCKED,
            ProgrammeFormatActionState.STALE,
            ProgrammeFormatActionState.UNAVAILABLE,
        }:
            if not self.blocked_reasons:
                raise ValueError(f"{self.action_state.value} format actions require blockers")
            if self.public_claim_allowed or self.public_live_claim_allowed:
                raise ValueError(
                    f"{self.action_state.value} format actions cannot allow public claims"
                )
        if self.action_state is ProgrammeFormatActionState.MONETIZATION_BLOCKED:
            if self.monetization_claim_allowed:
                raise ValueError("monetization-blocked actions cannot allow monetization claims")
            if not any("monetization" in reason for reason in self.blocked_reasons):
                raise ValueError("monetization-blocked actions require monetization blocker")
            if not self.archive_claim_allowed:
                raise ValueError(
                    "monetization blockers must preserve archive posture when available"
                )
        if self.action_state is ProgrammeFormatActionState.ARCHIVE_ONLY:
            if not self.archive_claim_allowed:
                raise ValueError("archive-only actions require archive claim posture")
            if self.public_live_claim_allowed:
                raise ValueError("archive-only actions cannot claim public-live availability")
        if self.missing_surface_refs and not self.blocked_reasons:
            raise ValueError("missing surfaces must remain operator-visible as blockers")
        return self

    def _has_static_hint_source(self) -> bool:
        return any(ref.startswith("prompt-hint:") for ref in self.source_refs) or any(
            surface.surface_id.startswith("prompt_hint:")
            for surface in (*self.required_wcs_surfaces, *self.blocked_surface_refs)
        )


class DirectorProgrammeFormatActionProjection(BaseModel):
    """Projection batch consumed by director read-model tests and adapters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    projection_id: str = Field(pattern=r"^director-programme-format-actions-[a-z0-9-]+$")
    director_snapshot_id: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    action_states: tuple[ProgrammeFormatActionState, ...] = Field(min_length=1)
    actions: tuple[DirectorProgrammeFormatActionRow, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_projection_coverage(self) -> Self:
        action_ids = [row.action_id for row in self.actions]
        duplicates = sorted(
            {action_id for action_id in action_ids if action_ids.count(action_id) > 1}
        )
        if duplicates:
            raise ValueError("duplicate programme format action ids: " + ", ".join(duplicates))
        observed = {state.value for state in self.action_states}
        if observed != REQUIRED_ACTION_STATES:
            raise ValueError("programme action states do not match required state set")
        row_states = {row.action_state.value for row in self.actions}
        missing = REQUIRED_ACTION_STATES - row_states
        if missing:
            raise ValueError(
                "programme action projection missing state rows: " + ", ".join(sorted(missing))
            )
        return self

    def rows_for_state(
        self, state: ProgrammeFormatActionState
    ) -> tuple[DirectorProgrammeFormatActionRow, ...]:
        return tuple(row for row in self.actions if row.action_state is state)

    def require_action(self, action_id: str) -> DirectorProgrammeFormatActionRow:
        for row in self.actions:
            if row.action_id == action_id:
                return row
        raise KeyError(f"unknown programme format action: {action_id}")


def load_director_programme_format_action_projection(
    *,
    run_fixture_path: Path = CONTENT_PROGRAMME_RUN_ENVELOPE_FIXTURES,
) -> DirectorProgrammeFormatActionProjection:
    """Load fixture-backed programme format actions for the director read model."""

    try:
        snapshot_fixture_set = load_director_world_surface_snapshot_fixtures()
        matrix = load_format_wcs_requirement_matrix()
        run_payload = _load_json_object(run_fixture_path)
        return build_director_programme_format_action_projection(
            snapshot=snapshot_fixture_set.snapshots[0],
            matrix=matrix,
            run_fixture_payload=run_payload,
        )
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise DirectorProgrammeFormatActionError(
            f"invalid director programme format action projection: {exc}"
        ) from exc


def build_director_programme_format_action_projection(
    *,
    snapshot: DirectorWorldSurfaceSnapshot,
    matrix: FormatWCSRequirementMatrix,
    run_fixture_payload: dict[str, Any],
) -> DirectorProgrammeFormatActionProjection:
    """Join director snapshot, programme run envelopes, and WCS format matrix rows."""

    run_rows = cast("list[dict[str, Any]]", run_fixture_payload.get("runs", []))
    actions = [
        _action_from_run_envelope(snapshot=snapshot, matrix=matrix, run=run) for run in run_rows
    ]
    actions.extend(_actions_from_snapshot_blockers(snapshot=snapshot, matrix=matrix))

    return DirectorProgrammeFormatActionProjection(
        projection_id=f"director-programme-format-actions-{snapshot.snapshot_id.removeprefix('director-wcs-snapshot-')}",
        director_snapshot_id=snapshot.snapshot_id,
        source_refs=(
            f"DirectorWorldSurfaceSnapshot:{snapshot.snapshot_id}",
            "config:content-programme-run-envelope-fixtures",
            matrix.matrix_id,
        ),
        action_states=tuple(ProgrammeFormatActionState(state) for state in REQUIRED_ACTION_STATES),
        actions=tuple(actions),
    )


def _action_from_run_envelope(
    *,
    snapshot: DirectorWorldSurfaceSnapshot,
    matrix: FormatWCSRequirementMatrix,
    run: dict[str, Any],
) -> DirectorProgrammeFormatActionRow:
    format_id = str(run["format_id"])
    matrix_row = matrix.require_row(cast("Any", format_id))
    action_state = _action_state_from_run(run)
    evidence = cast("dict[str, Any]", run["evidence_obligations"])
    claim_shape = cast("dict[str, Any]", run["claim_shape"])
    outcomes = cast("dict[str, Any]", run["outcomes"])
    conversion = cast("dict[str, Any]", run["conversion_posture"])
    wcs = cast("dict[str, Any]", run["wcs_snapshot"])

    required_surfaces = tuple(
        _surface_from_matrix_block(block, SurfaceRefState.REQUIRED)
        for block in matrix_row.required_surface_blocks
    )
    optional_surfaces = tuple(
        _surface_from_matrix_block(block, SurfaceRefState.OPTIONAL)
        for block in matrix_row.optional_surface_blocks
    )
    missing_surface_refs = tuple(str(ref) for ref in wcs.get("missing_surface_refs", ()))
    blocked_reasons = _blocked_reasons_for_run(run, action_state)
    blocked_surface_refs = tuple(
        ProgrammeWCSSurfaceRef(
            surface_id=ref,
            state=SurfaceRefState.MISSING,
            source="run_envelope",
            reason_code=_reason_for_missing_run_surface(ref, blocked_reasons),
        )
        for ref in missing_surface_refs
    )

    return DirectorProgrammeFormatActionRow(
        action_id=f"programme-format-action:{run['fixture_case']}",
        format_id=format_id,
        display_name=format_id.replace("_", " "),
        action_state=action_state,
        requested_mode=str(run["requested_mode"]),
        effective_mode=str(run["effective_mode"]),
        final_status=str(run["final_status"]),
        run_id=str(run["run_id"]),
        fixture_case=str(run["fixture_case"]),
        source_refs=(
            f"ContentProgrammeRunEnvelope:{run['run_id']}",
            f"FormatWCSRequirementRow:{format_id}",
            f"DirectorWorldSurfaceSnapshot:{snapshot.snapshot_id}",
        ),
        director_snapshot_ref=str(cast("dict[str, Any]", run["director"])["director_snapshot_ref"]),
        format_matrix_ref=f"FormatWCSRequirementRow:{format_id}",
        run_envelope_ref=f"ContentProgrammeRunEnvelope:{run['run_id']}",
        required_wcs_surfaces=required_surfaces,
        optional_wcs_surfaces=optional_surfaces,
        available_surface_refs=tuple(str(ref) for ref in wcs.get("available_surface_refs", ())),
        missing_surface_refs=missing_surface_refs,
        blocked_surface_refs=blocked_surface_refs,
        director_moves=tuple(str(move) for move in matrix_row.director_moves),
        grounding_question_ref=matrix_row.grounding_question_ref,
        permitted_claim_shape_ref=matrix_row.permitted_claim_shape_ref,
        claim_authority_ceiling=str(claim_shape["authority_ceiling"]),
        public_claim_allowed=bool(claim_shape["public_claim_allowed"]),
        public_live_claim_allowed=action_state is ProgrammeFormatActionState.PUBLIC_LIVE,
        archive_claim_allowed=bool(claim_shape["public_claim_allowed"])
        and action_state
        in {
            ProgrammeFormatActionState.ARCHIVE_ONLY,
            ProgrammeFormatActionState.PUBLIC_LIVE,
            ProgrammeFormatActionState.MONETIZATION_BLOCKED,
        },
        monetization_claim_allowed=str(conversion["monetization_state"]) == "ready",
        evidence_obligations=_merge_unique(
            matrix_row.required_evidence_classes,
            cast("list[str]", evidence.get("required_evidence_classes", [])),
            cast("list[str]", evidence.get("missing_obligations", [])),
            ("public_event",) if outcomes.get("public_event_refs") else (),
        ),
        evidence_refs=tuple(str(ref) for ref in evidence.get("evidence_envelope_refs", ())),
        witness_refs=tuple(str(ref) for ref in evidence.get("witness_refs", ())),
        rights_refs=tuple(str(ref) for ref in evidence.get("rights_refs", ())),
        public_event_refs=tuple(str(ref) for ref in outcomes.get("public_event_refs", ())),
        conversion_paths=_merge_unique(
            matrix_row.conversion_paths,
            cast("list[str]", conversion.get("allowed_routes", [])),
            cast("list[str]", conversion.get("held_routes", [])),
            cast("list[str]", conversion.get("blocked_routes", [])),
        ),
        conversion_obligations=_merge_unique(
            matrix_row.monetization_obligations,
            (f"held:{route}" for route in conversion.get("held_routes", ())),
            (f"blocked:{route}" for route in conversion.get("blocked_routes", ())),
        ),
        blocked_reasons=blocked_reasons,
        operator_visible_reason=_operator_reason_for_run(run, action_state, blocked_reasons),
    )


def _actions_from_snapshot_blockers(
    *,
    snapshot: DirectorWorldSurfaceSnapshot,
    matrix: FormatWCSRequirementMatrix,
) -> list[DirectorProgrammeFormatActionRow]:
    rows: list[DirectorProgrammeFormatActionRow] = []
    for surface_row, format_id in (
        (_first_row(snapshot, MoveStatus.STALE), "rundown"),
        (_first_row(snapshot, MoveStatus.UNAVAILABLE, "model_provider:"), "what_is_this"),
        (_first_row(snapshot, MoveStatus.UNAVAILABLE, "prompt_hint:"), "explainer"),
    ):
        if surface_row is None:
            continue
        rows.append(_action_from_snapshot_blocker(snapshot, matrix, surface_row, format_id))
    return rows


def _action_from_snapshot_blocker(
    snapshot: DirectorWorldSurfaceSnapshot,
    matrix: FormatWCSRequirementMatrix,
    surface_row: DirectorWorldSurfaceMoveRow,
    format_id: str,
) -> DirectorProgrammeFormatActionRow:
    matrix_row = matrix.require_row(cast("Any", format_id))
    action_state = _action_state_from_surface(surface_row)
    blocked_reason = surface_row.blocker_reason or ",".join(surface_row.blocked_reasons)
    required_surfaces = tuple(
        _surface_from_matrix_block(block, SurfaceRefState.REQUIRED)
        for block in matrix_row.required_surface_blocks
    )

    return DirectorProgrammeFormatActionRow(
        action_id=f"programme-format-action:{action_state.value}:{surface_row.surface_id.replace(':', '.')}",
        format_id=format_id,
        display_name=format_id.replace("_", " "),
        action_state=action_state,
        requested_mode="public_live",
        effective_mode=action_state.value,
        final_status="blocked",
        run_id=None,
        fixture_case=None,
        source_refs=tuple(
            dict.fromkeys(
                (
                    *surface_row.source_refs,
                    f"FormatWCSRequirementRow:{format_id}",
                    f"DirectorWorldSurfaceSnapshot:{snapshot.snapshot_id}",
                )
            )
        ),
        director_snapshot_ref=f"DirectorWorldSurfaceSnapshot:{snapshot.snapshot_id}",
        format_matrix_ref=f"FormatWCSRequirementRow:{format_id}",
        run_envelope_ref=None,
        required_wcs_surfaces=required_surfaces,
        optional_wcs_surfaces=tuple(
            _surface_from_matrix_block(block, SurfaceRefState.OPTIONAL)
            for block in matrix_row.optional_surface_blocks
        ),
        available_surface_refs=(),
        missing_surface_refs=(surface_row.surface_id,),
        blocked_surface_refs=(
            ProgrammeWCSSurfaceRef(
                surface_id=surface_row.surface_id,
                state=SurfaceRefState(action_state.value),
                source="director_snapshot",
                family=surface_row.surface_family.value,
                witness_refs=tuple(surface_row.required_witness_refs),
                evidence_refs=tuple(surface_row.source_refs),
                reason_code=blocked_reason,
            ),
        ),
        director_moves=tuple(str(move) for move in matrix_row.director_moves),
        grounding_question_ref=matrix_row.grounding_question_ref,
        permitted_claim_shape_ref=matrix_row.permitted_claim_shape_ref,
        claim_authority_ceiling=surface_row.claim_authority_ceiling.value,
        public_claim_allowed=False,
        public_live_claim_allowed=False,
        archive_claim_allowed=False,
        monetization_claim_allowed=False,
        evidence_obligations=_merge_unique(
            matrix_row.required_evidence_classes,
            (obligation.obligation_id for obligation in surface_row.evidence_obligations),
        ),
        evidence_refs=tuple(surface_row.source_refs),
        witness_refs=tuple(surface_row.required_witness_refs),
        rights_refs=(),
        public_event_refs=(),
        conversion_paths=tuple(str(path) for path in matrix_row.conversion_paths),
        conversion_obligations=_merge_unique(
            matrix_row.monetization_obligations,
            (f"blocked_surface:{surface_row.surface_id}",),
        ),
        blocked_reasons=tuple(dict.fromkeys((*surface_row.blocked_reasons, blocked_reason))),
        operator_visible_reason=surface_row.fallback.operator_visible_reason,
    )


def _surface_from_matrix_block(
    block: WCSSurfaceRequirement,
    state: SurfaceRefState,
) -> ProgrammeWCSSurfaceRef:
    return ProgrammeWCSSurfaceRef(
        surface_id=block.surface_id,
        state=state,
        source="format_wcs_matrix",
        family=block.family,
        witness_refs=tuple(block.witness_refs),
        evidence_refs=tuple(block.evidence_refs),
        reason_code=block.blocked_reason_code if state is not SurfaceRefState.REQUIRED else None,
    )


def _action_state_from_run(run: dict[str, Any]) -> ProgrammeFormatActionState:
    requested_mode = str(run["requested_mode"])
    effective_mode = str(run["effective_mode"])
    final_status = str(run["final_status"])
    conversion = cast("dict[str, Any]", run["conversion_posture"])

    if requested_mode == "public_monetizable" and conversion["monetization_state"] == "blocked":
        return ProgrammeFormatActionState.MONETIZATION_BLOCKED
    if final_status == "refused":
        return ProgrammeFormatActionState.BLOCKED
    if effective_mode == "private":
        return ProgrammeFormatActionState.PRIVATE
    if effective_mode == "dry_run":
        return ProgrammeFormatActionState.DRY_RUN
    if effective_mode == "public_archive":
        return ProgrammeFormatActionState.ARCHIVE_ONLY
    if effective_mode in {"public_live", "public_monetizable"}:
        return ProgrammeFormatActionState.PUBLIC_LIVE
    return ProgrammeFormatActionState.BLOCKED


def _action_state_from_surface(
    row: DirectorWorldSurfaceMoveRow,
) -> ProgrammeFormatActionState:
    if row.status is MoveStatus.STALE:
        return ProgrammeFormatActionState.STALE
    if row.status is MoveStatus.UNAVAILABLE:
        return ProgrammeFormatActionState.UNAVAILABLE
    return ProgrammeFormatActionState.BLOCKED


def _blocked_reasons_for_run(
    run: dict[str, Any],
    action_state: ProgrammeFormatActionState,
) -> tuple[str, ...]:
    blockers = tuple(str(reason) for reason in run.get("blockers", ()))
    conversion = cast("dict[str, Any]", run["conversion_posture"])
    conversion_blockers = tuple(
        f"conversion_{route}_blocked" for route in conversion.get("blocked_routes", ())
    )
    if action_state in {
        ProgrammeFormatActionState.BLOCKED,
        ProgrammeFormatActionState.DRY_RUN,
        ProgrammeFormatActionState.PRIVATE,
    }:
        return _merge_unique(blockers, conversion_blockers)
    if action_state is ProgrammeFormatActionState.MONETIZATION_BLOCKED:
        return _merge_unique(blockers, conversion_blockers, ("monetization_readiness_missing",))
    return ()


def _operator_reason_for_run(
    run: dict[str, Any],
    action_state: ProgrammeFormatActionState,
    blockers: tuple[str, ...],
) -> str:
    format_id = str(run["format_id"]).replace("_", " ")
    if action_state is ProgrammeFormatActionState.PUBLIC_LIVE:
        return f"{format_id} can run public-live because WCS, rights, witnesses, and public-event refs are present."
    if action_state is ProgrammeFormatActionState.ARCHIVE_ONLY:
        return f"{format_id} can produce archive/public artifacts, but it is not a live authorization row."
    if action_state is ProgrammeFormatActionState.MONETIZATION_BLOCKED:
        return f"{format_id} keeps archive grounding visible while monetization remains blocked."
    if blockers:
        return f"{format_id} remains visible as {action_state.value}: {', '.join(blockers)}."
    return f"{format_id} remains visible as {action_state.value}."


def _reason_for_missing_run_surface(ref: str, blockers: tuple[str, ...]) -> str:
    if "public_event" in ref:
        return "public_event_readiness_missing"
    if blockers:
        return blockers[0]
    return "missing_wcs_surface"


def _first_row(
    snapshot: DirectorWorldSurfaceSnapshot,
    status: MoveStatus,
    surface_prefix: str | None = None,
) -> DirectorWorldSurfaceMoveRow | None:
    for row in snapshot.rows_for_status(status):
        if surface_prefix is None or row.surface_id.startswith(surface_prefix):
            return row
    return None


def _merge_unique(*groups: Any) -> tuple[str, ...]:
    values: list[str] = []
    for group in groups:
        for value in group:
            text = str(value)
            if text not in values:
                values.append(text)
    return tuple(values)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DirectorWorldSurfaceSnapshotError(f"{path} did not contain a JSON object")
    return payload


__all__ = [
    "CONTENT_PROGRAMME_RUN_ENVELOPE_FIXTURES",
    "REQUIRED_ACTION_STATES",
    "DirectorProgrammeFormatActionError",
    "DirectorProgrammeFormatActionProjection",
    "DirectorProgrammeFormatActionRow",
    "ProgrammeFormatActionState",
    "ProgrammeWCSSurfaceRef",
    "SurfaceRefState",
    "build_director_programme_format_action_projection",
    "load_director_programme_format_action_projection",
]
