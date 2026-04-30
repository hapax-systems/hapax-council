"""Programme/revenue projections for braided-value snapshot rows."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.content_programme_feedback_ledger import PosteriorUpdateFamily, SourceSignal
from shared.conversion_target_readiness import (
    GateDimension,
    ReadinessState,
    TargetFamilyId,
    decide_readiness_state,
    load_conversion_target_readiness_matrix,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADAPTER_FIXTURE_PATH = REPO_ROOT / "config" / "programme-revenue-braid-adapters.json"

type BraidModeCeiling = Literal[
    "private",
    "dry_run",
    "public_archive",
    "public_live",
    "public_monetizable",
]
type BraidValueChannel = Literal[
    "grounding",
    "artifact_replay",
    "audience_response",
    "revenue_response",
    "refusal_correction",
    "rights_provenance",
]
type AdapterEvidenceScope = Literal[
    "private_programme",
    "private_grant_application",
    "dry_run_conversion",
    "public_release_candidate",
    "blocked_overclaim",
]

PUBLIC_REQUESTED_STATES: frozenset[ReadinessState] = frozenset(
    {"public-archive", "public-live", "public-monetizable"}
)
GROUNDING_SOURCE_SIGNALS: frozenset[SourceSignal] = frozenset(
    {"format_grounding_evaluation", "capability_outcome_witness"}
)


class BraidAdapterModel(BaseModel):
    """Strict immutable base for adapter records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class BraidFamilyValues(BraidAdapterModel):
    """Normalized braid family values from a snapshot row."""

    engagement: float = Field(ge=0, le=1)
    monetary: float = Field(ge=0, le=1)
    research: float = Field(ge=0, le=1)
    tree_effect: float = Field(ge=0, le=1)


class BraidGatePostureRef(BraidAdapterModel):
    """Gate posture subset consumed from the snapshot runner."""

    hard_vetoes: tuple[str, ...] = Field(default_factory=tuple)
    evidence_ceiling: BraidModeCeiling
    deny_wins: bool
    trend_can_upgrade_claim_confidence: Literal[False] = False


class BraidSnapshotRowRef(BraidAdapterModel):
    """Stable adapter input view of one braid snapshot row."""

    snapshot_ref: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    mode_ceiling: BraidModeCeiling
    max_public_claim: str = Field(min_length=1)
    potential: BraidFamilyValues
    realized: BraidFamilyValues
    gate_posture: BraidGatePostureRef
    review_reasons: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _private_ceiling_has_no_public_claim(self) -> Self:
        if self.mode_ceiling == "private" and self.max_public_claim != "none":
            raise ValueError("private braid rows cannot carry public claim text")
        if self.gate_posture.deny_wins and self.mode_ceiling != "private":
            raise ValueError("deny-wins gate posture must keep the row private")
        return self


class ProgrammeFeedbackBraidProjection(BraidAdapterModel):
    """Read-only programme feedback consumer projection."""

    projection_id: str = Field(min_length=1)
    source_task_id: str = Field(min_length=1)
    source_snapshot_ref: str = Field(min_length=1)
    value_channels: tuple[BraidValueChannel, ...] = Field(min_length=1)
    source_signals: tuple[SourceSignal, ...] = Field(min_length=1)
    allowed_posterior_families: tuple[PosteriorUpdateFamily, ...]
    blocked_posterior_families: tuple[PosteriorUpdateFamily, ...]
    grounding_update_allowed: bool
    public_truth_claim_allowed: Literal[False] = False
    operator_scoring_required: Literal[False] = False
    audience_revenue_can_upgrade_grounding: Literal[False] = False
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _grounding_updates_need_grounding_signal(self) -> Self:
        if self.grounding_update_allowed:
            if "grounding_quality" not in self.allowed_posterior_families:
                raise ValueError("grounding updates must expose grounding_quality posterior")
            if "grounding" not in self.value_channels:
                raise ValueError("grounding updates need a grounding value channel")
            if not (set(self.source_signals) & GROUNDING_SOURCE_SIGNALS):
                raise ValueError("grounding updates need grounding/capability source signals")
        if (
            "grounding_quality" in self.allowed_posterior_families
            and not self.grounding_update_allowed
        ):
            raise ValueError("grounding_quality cannot be allowed when grounding update is false")
        return self


class ConversionReadinessBraidProjection(BraidAdapterModel):
    """Read-only conversion readiness consumer projection."""

    projection_id: str = Field(min_length=1)
    source_task_id: str = Field(min_length=1)
    target_family_id: TargetFamilyId
    requested_state: ReadinessState
    effective_state: ReadinessState
    allowed: bool
    evidence_scope: AdapterEvidenceScope
    satisfied_gate_dimensions: tuple[GateDimension, ...]
    missing_gate_dimensions: tuple[GateDimension, ...]
    operator_visible_reason: str = Field(min_length=1)
    private_grant_application_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_support_or_release_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    revenue_potential_can_bypass_gates: Literal[False] = False
    audience_response_can_bypass_gates: Literal[False] = False
    adapter_grants_public_authority: Literal[False] = False
    adapter_grants_monetization_authority: Literal[False] = False

    @model_validator(mode="after")
    def _grant_private_evidence_stays_separate(self) -> Self:
        if self.target_family_id == "grants_fellowships":
            if not self.private_grant_application_evidence_refs:
                raise ValueError("grant/fellowship projections need private evidence refs")
            if self.public_support_or_release_evidence_refs:
                raise ValueError("grant private evidence cannot be public support/release evidence")
        if self.requested_state in PUBLIC_REQUESTED_STATES and self.allowed:
            if self.adapter_grants_public_authority:
                raise ValueError("adapter rows must not grant public authority")
        if self.requested_state == "public-monetizable" and self.allowed:
            if self.adapter_grants_monetization_authority:
                raise ValueError("adapter rows must not grant monetization authority")
        return self


class ProgrammeRevenueBraidAdapterRow(BraidAdapterModel):
    """One braid snapshot projection into programme and conversion consumers."""

    adapter_row_id: str = Field(pattern=r"^[a-z0-9_.:-]+$")
    snapshot_row: BraidSnapshotRowRef
    target_family_id: TargetFamilyId
    requested_state: ReadinessState
    satisfied_gate_dimensions: tuple[GateDimension, ...]
    programme_feedback: ProgrammeFeedbackBraidProjection
    conversion_readiness: ConversionReadinessBraidProjection


class ProgrammeRevenueBraidAdapterFixture(BraidAdapterModel):
    """Fixture row with expected adapter outcomes."""

    fixture_id: str = Field(pattern=r"^[a-z0-9_]+$")
    snapshot_row: BraidSnapshotRowRef
    target_family_id: TargetFamilyId
    requested_state: ReadinessState
    satisfied_gate_dimensions: tuple[GateDimension, ...]
    expected_allowed: bool
    expected_effective_state: ReadinessState
    expected_grounding_update_allowed: bool
    expected_missing_gate_dimensions: tuple[GateDimension, ...] = Field(default_factory=tuple)
    expected_allowed_posterior_families: tuple[PosteriorUpdateFamily, ...]


class ProgrammeRevenueBraidAdapterFixtureSet(BraidAdapterModel):
    """Canonical fixtures for programme/revenue braid adapters."""

    schema_version: Literal[1]
    fixture_set_id: Literal["programme_revenue_braid_adapters"]
    schema_ref: Literal["schemas/programme-revenue-braid-adapters.schema.json"]
    source_refs: tuple[str, ...] = Field(min_length=1)
    fixtures: tuple[ProgrammeRevenueBraidAdapterFixture, ...] = Field(min_length=5)


def load_programme_revenue_braid_adapter_fixtures(
    path: Path = DEFAULT_ADAPTER_FIXTURE_PATH,
) -> ProgrammeRevenueBraidAdapterFixtureSet:
    """Load and validate canonical adapter fixtures."""

    return ProgrammeRevenueBraidAdapterFixtureSet.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def project_braid_snapshot_row(
    snapshot_row: BraidSnapshotRowRef,
    *,
    target_family_id: TargetFamilyId,
    requested_state: ReadinessState,
    satisfied_gate_dimensions: Iterable[GateDimension],
) -> ProgrammeRevenueBraidAdapterRow:
    """Project one snapshot row into programme feedback and conversion readiness."""

    matrix = load_conversion_target_readiness_matrix()
    satisfied = tuple(dict.fromkeys(satisfied_gate_dimensions))
    decision = decide_readiness_state(matrix, target_family_id, requested_state, satisfied)
    value_channels = _value_channels(snapshot_row, target_family_id)
    source_signals = _source_signals(value_channels)
    grounding_allowed = _grounding_update_allowed(snapshot_row, value_channels, source_signals)
    allowed_posteriors = _allowed_posterior_families(value_channels, grounding_allowed)
    blocked_posteriors = tuple(
        family
        for family in (
            "grounding_quality",
            "audience_response",
            "revenue_support_response",
            "rights_pass_probability",
            "safety_refusal_rate",
        )
        if family not in allowed_posteriors
    )

    programme_projection = ProgrammeFeedbackBraidProjection(
        projection_id=f"programme-feedback:{snapshot_row.task_id}",
        source_task_id=snapshot_row.task_id,
        source_snapshot_ref=snapshot_row.snapshot_ref,
        value_channels=value_channels,
        source_signals=source_signals,
        allowed_posterior_families=allowed_posteriors,
        blocked_posterior_families=blocked_posteriors,
        grounding_update_allowed=grounding_allowed,
        evidence_refs=snapshot_row.evidence_refs,
    )
    conversion_projection = ConversionReadinessBraidProjection(
        projection_id=f"conversion-readiness:{snapshot_row.task_id}:{target_family_id}",
        source_task_id=snapshot_row.task_id,
        target_family_id=target_family_id,
        requested_state=requested_state,
        effective_state=decision.effective_state,
        allowed=decision.allowed,
        evidence_scope=_evidence_scope(target_family_id, requested_state, decision.allowed),
        satisfied_gate_dimensions=satisfied,
        missing_gate_dimensions=decision.missing_gate_dimensions,
        operator_visible_reason=decision.operator_visible_reason,
        private_grant_application_evidence_refs=_private_grant_refs(
            target_family_id,
            snapshot_row,
        ),
        public_support_or_release_evidence_refs=_public_release_refs(
            target_family_id,
            requested_state,
            decision.allowed,
            snapshot_row,
        ),
    )

    return ProgrammeRevenueBraidAdapterRow(
        adapter_row_id=f"braid-adapter:{snapshot_row.task_id}:{target_family_id}",
        snapshot_row=snapshot_row,
        target_family_id=target_family_id,
        requested_state=requested_state,
        satisfied_gate_dimensions=satisfied,
        programme_feedback=programme_projection,
        conversion_readiness=conversion_projection,
    )


def project_fixture(
    fixture: ProgrammeRevenueBraidAdapterFixture,
) -> ProgrammeRevenueBraidAdapterRow:
    """Project a canonical fixture row."""

    return project_braid_snapshot_row(
        fixture.snapshot_row,
        target_family_id=fixture.target_family_id,
        requested_state=fixture.requested_state,
        satisfied_gate_dimensions=fixture.satisfied_gate_dimensions,
    )


def _value_channels(
    snapshot_row: BraidSnapshotRowRef,
    target_family_id: TargetFamilyId,
) -> tuple[BraidValueChannel, ...]:
    channels: list[BraidValueChannel] = []
    refs = " ".join(snapshot_row.evidence_refs).lower()
    if snapshot_row.potential.research > 0 or any(
        marker in refs for marker in ("grounding", "wcs", "capability")
    ):
        channels.append("grounding")
    if target_family_id in {
        "youtube_vod_packaging",
        "replay_demo",
        "dataset_card",
        "artifact_edition_release",
        "licensing",
    }:
        channels.append("artifact_replay")
    if snapshot_row.potential.engagement > 0:
        channels.append("audience_response")
    if snapshot_row.potential.monetary > 0:
        channels.append("revenue_response")
    if any(
        reason in {"refused", "corrected", "run_refused"} for reason in snapshot_row.review_reasons
    ):
        channels.append("refusal_correction")
    if any(marker in refs for marker in ("rights", "privacy", "provenance")):
        channels.append("rights_provenance")
    return tuple(dict.fromkeys(channels or ["grounding"]))


def _source_signals(channels: Iterable[BraidValueChannel]) -> tuple[SourceSignal, ...]:
    signals: list[SourceSignal] = []
    for channel in channels:
        if channel == "grounding":
            signals.append("format_grounding_evaluation")
        elif channel == "artifact_replay":
            signals.append("artifact_conversion")
        elif channel == "audience_response":
            signals.append("audience_aggregate")
        elif channel == "revenue_response":
            signals.append("revenue_aggregate")
        elif channel == "refusal_correction":
            signals.append("safety_gate")
        elif channel == "rights_provenance":
            signals.append("rights_gate")
    return tuple(dict.fromkeys(signals))


def _grounding_update_allowed(
    snapshot_row: BraidSnapshotRowRef,
    channels: tuple[BraidValueChannel, ...],
    source_signals: tuple[SourceSignal, ...],
) -> bool:
    if snapshot_row.gate_posture.deny_wins:
        return False
    if "grounding" not in channels:
        return False
    if not (set(source_signals) & GROUNDING_SOURCE_SIGNALS):
        return False
    refs = " ".join(snapshot_row.evidence_refs).lower()
    return any(marker in refs for marker in ("grounding", "wcs", "capability"))


def _allowed_posterior_families(
    channels: tuple[BraidValueChannel, ...],
    grounding_allowed: bool,
) -> tuple[PosteriorUpdateFamily, ...]:
    families: list[PosteriorUpdateFamily] = []
    if grounding_allowed:
        families.append("grounding_quality")
    if "audience_response" in channels:
        families.append("audience_response")
    if "revenue_response" in channels:
        families.append("revenue_support_response")
    if "artifact_replay" in channels:
        families.append("artifact_conversion")
    if "rights_provenance" in channels:
        families.append("rights_pass_probability")
    if "refusal_correction" in channels:
        families.append("safety_refusal_rate")
    return tuple(dict.fromkeys(families))


def _evidence_scope(
    target_family_id: TargetFamilyId,
    requested_state: ReadinessState,
    allowed: bool,
) -> AdapterEvidenceScope:
    if target_family_id == "grants_fellowships":
        return "private_grant_application"
    if not allowed:
        return "blocked_overclaim"
    if requested_state == "dry-run":
        return "dry_run_conversion"
    if requested_state in PUBLIC_REQUESTED_STATES:
        return "public_release_candidate"
    return "private_programme"


def _private_grant_refs(
    target_family_id: TargetFamilyId,
    snapshot_row: BraidSnapshotRowRef,
) -> tuple[str, ...]:
    if target_family_id != "grants_fellowships":
        return ()
    return tuple(
        ref for ref in snapshot_row.evidence_refs if "grant" in ref or "private" in ref
    ) or (*snapshot_row.evidence_refs,)


def _public_release_refs(
    target_family_id: TargetFamilyId,
    requested_state: ReadinessState,
    allowed: bool,
    snapshot_row: BraidSnapshotRowRef,
) -> tuple[str, ...]:
    if target_family_id == "grants_fellowships" or not allowed:
        return ()
    if requested_state not in PUBLIC_REQUESTED_STATES:
        return ()
    return snapshot_row.evidence_refs
