"""WCS companion requirement matrix for content programme formats."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORMAT_WCS_MATRIX_PATH = REPO_ROOT / "config" / "format-wcs-requirement-matrix.json"

type ContentProgrammeFormatId = Literal[
    "tier_list",
    "react_commentary",
    "ranking",
    "comparison",
    "review",
    "watch_along",
    "explainer",
    "rundown",
    "debate",
    "bracket",
    "what_is_this",
    "refusal_breakdown",
    "evidence_audit",
]
type FormatWCSMode = Literal[
    "private",
    "dry_run",
    "public_archive",
    "public_live",
    "public_monetizable",
]
type FormatWCSDecisionMode = Literal[
    "private",
    "dry_run",
    "public_archive",
    "public_live",
    "public_monetizable",
    "monetization_blocked",
    "refused",
    "blocked",
]
type WCSSurfaceFamily = Literal[
    "source",
    "media",
    "rights",
    "claim_gate",
    "evidence",
    "director",
    "public_event",
    "archive",
    "monetization",
    "refusal_correction",
]
type MissingSurfaceBehavior = Literal[
    "private_only",
    "dry_run",
    "refuse",
    "block",
    "monetization_blocked",
]
type ConversionPath = Literal[
    "youtube_metadata",
    "chapter",
    "caption",
    "shorts",
    "archive_replay",
    "public_refusal_artifact",
    "correction_artifact",
    "support_prompt",
    "grant_demo_evidence",
    "artifact",
    "dataset",
    "licensing",
]
type ArchiveOutput = Literal[
    "run_card",
    "rank_table",
    "criteria_sheet",
    "chapter_markers",
    "caption",
    "refusal_artifact",
    "correction_artifact",
    "evidence_table",
    "replay_note",
]
type DirectorMove = Literal[
    "foreground",
    "background",
    "hold",
    "suppress",
    "transition",
    "crossfade",
    "intensify",
    "stabilize",
    "route_attention",
    "mark_boundary",
]

REQUIRED_FORMAT_IDS: frozenset[ContentProgrammeFormatId] = frozenset(
    {
        "tier_list",
        "react_commentary",
        "ranking",
        "comparison",
        "review",
        "watch_along",
        "explainer",
        "rundown",
        "debate",
        "bracket",
        "what_is_this",
        "refusal_breakdown",
        "evidence_audit",
    }
)
PUBLIC_MODES: frozenset[FormatWCSMode] = frozenset(
    {"public_archive", "public_live", "public_monetizable"}
)
ORDERED_MISSING_BEHAVIORS: tuple[MissingSurfaceBehavior, ...] = (
    "block",
    "refuse",
    "monetization_blocked",
    "dry_run",
    "private_only",
)


class FormatWCSModel(BaseModel):
    """Strict immutable base for WCS format matrix records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class WCSSurfaceRequirement(FormatWCSModel):
    """One required or optional WCS surface for a content format."""

    surface_id: str = Field(pattern=r"^[a-z0-9_.:-]+$")
    family: WCSSurfaceFamily
    required_for_modes: tuple[FormatWCSMode, ...] = Field(default_factory=tuple)
    witness_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    missing_behavior: MissingSurfaceBehavior
    blocked_reason_code: str = Field(pattern=r"^[a-z0-9_.:-]+$")
    public_claim_authority: Literal[False] = False

    @property
    def required(self) -> bool:
        """Whether this surface gates any execution mode."""

        return bool(self.required_for_modes)


class RefusalCorrectionPolicy(FormatWCSModel):
    """How blocked/corrected runs become bounded programme outputs."""

    public_safe_refusal_artifact_allowed: bool
    correction_artifact_required_on_public_error: Literal[True] = True
    blocked_claim_validated_by_aesthetic_emphasis: Literal[False] = False
    private_details_must_be_suppressed: Literal[True] = True
    evidence_refs_required: Literal[True] = True


class FormatWCSRequirementRow(FormatWCSModel):
    """WCS companion block for one ContentProgrammeFormat row."""

    format_id: ContentProgrammeFormatId
    content_programme_format_ref: str = Field(min_length=1)
    grounding_question_ref: str = Field(min_length=1)
    permitted_claim_shape_ref: str = Field(min_length=1)
    required_surface_blocks: tuple[WCSSurfaceRequirement, ...] = Field(min_length=4)
    optional_surface_blocks: tuple[WCSSurfaceRequirement, ...] = Field(min_length=1)
    required_evidence_classes: tuple[str, ...] = Field(min_length=1)
    required_grounding_gate_refs: tuple[str, ...] = Field(min_length=1)
    required_public_event_policy: str = Field(min_length=1)
    archive_outputs: tuple[ArchiveOutput, ...] = Field(min_length=1)
    conversion_paths: tuple[ConversionPath, ...] = Field(min_length=1)
    monetization_obligations: tuple[str, ...] = Field(min_length=1)
    director_moves: tuple[DirectorMove, ...] = Field(min_length=1)
    refusal_correction_policy: RefusalCorrectionPolicy
    safe_private_mode: Literal[True] = True
    safe_dry_run_mode: Literal[True] = True
    public_live_requires_egress: Literal[True] = True
    monetization_requires_readiness_ledger: Literal[True] = True
    matrix_grants_public_authority: Literal[False] = False
    matrix_grants_monetization_authority: Literal[False] = False

    @model_validator(mode="after")
    def _validate_format_wcs_contract(self) -> Self:
        families = {block.family for block in self.required_surface_blocks}
        missing = {
            "source",
            "rights",
            "claim_gate",
            "evidence",
            "public_event",
            "archive",
            "monetization",
        } - families
        if missing:
            raise ValueError(f"{self.format_id} missing required WCS families: {sorted(missing)}")
        if not any(
            "public_archive" in block.required_for_modes for block in self.required_surface_blocks
        ):
            raise ValueError(f"{self.format_id} must define public-archive requirements")
        if not any(
            block.family == "monetization" and "public_monetizable" in block.required_for_modes
            for block in self.required_surface_blocks
        ):
            raise ValueError(f"{self.format_id} must gate monetizable mode on monetization")
        if "refusal" in self.required_evidence_classes and not (
            self.refusal_correction_policy.public_safe_refusal_artifact_allowed
        ):
            raise ValueError(f"{self.format_id} refusal formats must allow public-safe artifacts")
        return self

    def required_surfaces_for_mode(self, mode: FormatWCSMode) -> tuple[WCSSurfaceRequirement, ...]:
        """Return required WCS blocks for ``mode``."""

        return tuple(
            block for block in self.required_surface_blocks if mode in block.required_for_modes
        )

    def surface_ids_for_director(self) -> tuple[str, ...]:
        """Return all surface ids a director read model can display as requirements."""

        return tuple(
            block.surface_id
            for block in (*self.required_surface_blocks, *self.optional_surface_blocks)
        )


class FormatWCSReadinessDecision(FormatWCSModel):
    """Fail-closed readiness decision for a format/mode request."""

    format_id: ContentProgrammeFormatId
    requested_mode: FormatWCSMode
    effective_mode: FormatWCSDecisionMode
    allowed: bool
    missing_surface_ids: tuple[str, ...]
    blocked_reason_codes: tuple[str, ...]
    required_surface_ids: tuple[str, ...]
    optional_surface_ids: tuple[str, ...]
    public_claim_authorized: Literal[False] = False
    monetization_authorized: Literal[False] = False


class DirectorFormatWCSProjection(FormatWCSModel):
    """Compact projection for director/read-model consumers."""

    format_id: ContentProgrammeFormatId
    required_surface_ids: tuple[str, ...]
    optional_surface_ids: tuple[str, ...]
    director_moves: tuple[DirectorMove, ...]
    grounding_question_ref: str
    permitted_claim_shape_ref: str
    matrix_grants_public_authority: Literal[False] = False


class OpportunityFormatWCSProjection(FormatWCSModel):
    """Compact projection for opportunity-to-run gate consumers."""

    format_id: ContentProgrammeFormatId
    safe_private_mode: Literal[True]
    safe_dry_run_mode: Literal[True]
    public_live_requires_egress: Literal[True]
    monetization_requires_readiness_ledger: Literal[True]
    conversion_paths: tuple[ConversionPath, ...]
    monetization_obligations: tuple[str, ...]
    refusal_correction_policy: RefusalCorrectionPolicy
    matrix_grants_monetization_authority: Literal[False] = False


class FormatWCSRequirementMatrix(FormatWCSModel):
    """Canonical matrix mapping initial content formats to WCS requirements."""

    schema_version: Literal[1]
    matrix_id: Literal["format_wcs_requirement_matrix"]
    schema_ref: Literal["schemas/format-wcs-requirement-matrix.schema.json"]
    content_programme_format_schema_ref: Literal["schemas/content-programme-format.schema.json"]
    source_refs: tuple[str, ...] = Field(min_length=1)
    rows: tuple[FormatWCSRequirementRow, ...] = Field(min_length=13)

    @model_validator(mode="after")
    def _validate_all_initial_formats_present(self) -> Self:
        format_ids = [row.format_id for row in self.rows]
        duplicates = sorted(
            {format_id for format_id in format_ids if format_ids.count(format_id) > 1}
        )
        if duplicates:
            raise ValueError(f"duplicate format ids: {duplicates}")
        format_id_set: set[ContentProgrammeFormatId] = set(format_ids)
        missing = REQUIRED_FORMAT_IDS - format_id_set
        if missing:
            raise ValueError(f"missing initial format ids: {sorted(missing)}")
        return self

    def by_format_id(self) -> dict[ContentProgrammeFormatId, FormatWCSRequirementRow]:
        """Return rows keyed by format id."""

        return {row.format_id: row for row in self.rows}

    def require_row(self, format_id: ContentProgrammeFormatId) -> FormatWCSRequirementRow:
        """Return one format row or raise KeyError."""

        return self.by_format_id()[format_id]


def load_format_wcs_requirement_matrix(
    path: Path = DEFAULT_FORMAT_WCS_MATRIX_PATH,
) -> FormatWCSRequirementMatrix:
    """Load and validate the canonical format WCS requirement matrix."""

    return FormatWCSRequirementMatrix.model_validate(json.loads(path.read_text(encoding="utf-8")))


def decide_format_wcs_readiness(
    row: FormatWCSRequirementRow,
    *,
    requested_mode: FormatWCSMode,
    available_surface_ids: Iterable[str],
) -> FormatWCSReadinessDecision:
    """Evaluate whether available surfaces satisfy one requested format mode."""

    required = row.required_surfaces_for_mode(requested_mode)
    available = set(available_surface_ids)
    missing = tuple(block for block in required if block.surface_id not in available)
    effective_mode = requested_mode if not missing else _effective_mode_for_missing(row, missing)

    return FormatWCSReadinessDecision(
        format_id=row.format_id,
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        allowed=not missing,
        missing_surface_ids=tuple(block.surface_id for block in missing),
        blocked_reason_codes=tuple(dict.fromkeys(block.blocked_reason_code for block in missing)),
        required_surface_ids=tuple(block.surface_id for block in required),
        optional_surface_ids=tuple(block.surface_id for block in row.optional_surface_blocks),
    )


def director_projection(row: FormatWCSRequirementRow) -> DirectorFormatWCSProjection:
    """Build a read-only director/read-model projection for one format."""

    return DirectorFormatWCSProjection(
        format_id=row.format_id,
        required_surface_ids=tuple(block.surface_id for block in row.required_surface_blocks),
        optional_surface_ids=tuple(block.surface_id for block in row.optional_surface_blocks),
        director_moves=row.director_moves,
        grounding_question_ref=row.grounding_question_ref,
        permitted_claim_shape_ref=row.permitted_claim_shape_ref,
    )


def opportunity_gate_projection(row: FormatWCSRequirementRow) -> OpportunityFormatWCSProjection:
    """Build a read-only opportunity-to-run projection for one format."""

    return OpportunityFormatWCSProjection(
        format_id=row.format_id,
        safe_private_mode=row.safe_private_mode,
        safe_dry_run_mode=row.safe_dry_run_mode,
        public_live_requires_egress=row.public_live_requires_egress,
        monetization_requires_readiness_ledger=row.monetization_requires_readiness_ledger,
        conversion_paths=row.conversion_paths,
        monetization_obligations=row.monetization_obligations,
        refusal_correction_policy=row.refusal_correction_policy,
    )


def _effective_mode_for_missing(
    row: FormatWCSRequirementRow,
    missing: tuple[WCSSurfaceRequirement, ...],
) -> FormatWCSDecisionMode:
    behaviors = {block.missing_behavior for block in missing}
    for behavior in ORDERED_MISSING_BEHAVIORS:
        if behavior in behaviors:
            if behavior == "private_only":
                return "private"
            if behavior == "dry_run":
                return "dry_run" if row.safe_dry_run_mode else "private"
            if behavior == "monetization_blocked":
                return "monetization_blocked"
            if behavior == "refuse":
                return "refused"
            return "blocked"
    return "blocked"
