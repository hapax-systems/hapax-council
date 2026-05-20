"""Scrim value-conversion cue policy.

This policy sits below the coarse ``conversion_ready`` / ``conversion_held``
scrim claim posture. It decides which value-stream cue is visually legible and
keeps conversion, support, grant, monetization, and revenue signals from
becoming claim-confidence, freshness, public-live, or truth signals.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.conversion_target_readiness import (
    GateDimension,
    ReadinessState,
    TargetFamilyId,
)
from shared.revenue_metrics_dashboard import (
    FORMAT_FAMILY_BY_FORMAT,
    ContentFormat,
    FormatFamily,
    PublicPrivateMode,
    RightsClass,
    SourceClass,
)

type ScrimConversionCueFamily = Literal[
    "archive",
    "replay",
    "artifact",
    "support",
    "grant",
    "monetization",
]
type ScrimConversionCuePosture = Literal[
    "conversion_ready",
    "conversion_held",
    "monetization_held",
]
type ScrimConversionCueTreatment = Literal[
    "conversion_cue_visible",
    "conversion_held_visible",
    "monetization_held_visible",
]
type OperatorLaborPolicy = Literal[
    "no_recurring_operator_labor",
    "operator_recurring_labor_required",
    "unknown",
]
type SupporterProgrammingPolicy = Literal[
    "no_supporter_control",
    "supporter_feedback_only",
    "supporter_controlled_programming",
]

REQUIRED_CUE_FAMILIES: frozenset[ScrimConversionCueFamily] = frozenset(
    {"archive", "replay", "artifact", "support", "grant", "monetization"}
)
PUBLIC_VALUE_STATES: frozenset[ReadinessState] = frozenset(
    {"public-archive", "public-live", "public-monetizable"}
)
RIGHTS_BLOCKING_CLASSES: frozenset[RightsClass] = frozenset(
    {"fair_use_candidate", "forbidden", "unknown"}
)
TRUTH_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "conversion:",
    "readiness:",
    "revenue:",
    "support:",
    "grant:",
    "archive:",
    "replay:",
    "artifact:",
    "monetization:",
)


class FrozenModel(BaseModel):
    """Strict immutable pydantic base for cue policy records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ScrimConversionCuePolicyRow(FrozenModel):
    cue_family: ScrimConversionCueFamily
    allowed_target_families: tuple[TargetFamilyId, ...] = Field(min_length=1)
    ready_states: tuple[ReadinessState, ...] = Field(min_length=1)
    ready_language: str = Field(min_length=1)
    held_language: str = Field(min_length=1)


class ScrimValueConversionNoGrantPolicy(FrozenModel):
    """Negative authority contract for value-conversion cues."""

    conversion_cue_grants_truth: Literal[False] = False
    conversion_cue_grants_claim_confidence: Literal[False] = False
    conversion_cue_grants_freshness: Literal[False] = False
    conversion_cue_grants_public_live_status: Literal[False] = False
    conversion_cue_grants_monetization_status: Literal[False] = False
    revenue_metric_updates_truth_posterior: Literal[False] = False
    revenue_potential_can_upgrade_readiness: Literal[False] = False
    supporter_controls_programming: Literal[False] = False
    recurring_operator_labor_assumed: Literal[False] = False


class ScrimRevenueMetricExport(FrozenModel):
    """Format-aware revenue metric labels emitted as non-truth context."""

    format_id: ContentFormat
    format_family: FormatFamily
    source_class: SourceClass
    rights_class: RightsClass
    public_private_mode: PublicPrivateMode
    revenue_potential_score: float = Field(ge=0.0, le=1.0)
    metric_refs: tuple[str, ...] = Field(default_factory=tuple)
    updates_truth_posteriors: Literal[False] = False


class ScrimValueConversionCueInput(FrozenModel):
    """One candidate value-stream cue before scrim projection."""

    cue_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    cue_family: ScrimConversionCueFamily
    target_family_id: TargetFamilyId
    requested_state: ReadinessState
    readiness_state: ReadinessState
    format_id: ContentFormat
    source_class: SourceClass
    rights_class: RightsClass
    public_private_mode: PublicPrivateMode
    conversion_refs: tuple[str, ...] = Field(min_length=1)
    readiness_evidence_refs: tuple[str, ...] = Field(min_length=1)
    source_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    revenue_metric_refs: tuple[str, ...] = Field(default_factory=tuple)
    missing_gate_dimensions: tuple[GateDimension, ...] = Field(default_factory=tuple)
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    revenue_potential_score: float = Field(default=0.0, ge=0.0, le=1.0)
    operator_labor_policy: OperatorLaborPolicy = "unknown"
    supporter_programming_policy: SupporterProgrammingPolicy = "no_supporter_control"

    @model_validator(mode="after")
    def _target_family_must_match_cue_family(self) -> Self:
        policy = policy_for_cue_family(self.cue_family)
        if self.target_family_id not in policy.allowed_target_families:
            msg = f"{self.target_family_id!r} is not valid for {self.cue_family!r} scrim cues"
            raise ValueError(msg)
        return self


class ScrimValueConversionCueProjection(FrozenModel):
    """Bounded scrim cue projection for value conversion paths."""

    schema_version: Literal[1] = 1
    projection_id: str
    cue_id: str
    run_id: str
    cue_family: ScrimConversionCueFamily
    target_family_id: TargetFamilyId
    requested_state: ReadinessState
    readiness_state: ReadinessState
    format_id: ContentFormat
    format_family: FormatFamily
    source_class: SourceClass
    rights_class: RightsClass
    public_private_mode: PublicPrivateMode
    posture: ScrimConversionCuePosture
    visibility_treatment: ScrimConversionCueTreatment
    cue_language: str
    conversion_refs: tuple[str, ...]
    readiness_evidence_refs: tuple[str, ...]
    source_event_refs: tuple[str, ...]
    blocker_dimensions: tuple[GateDimension, ...]
    blocked_reasons: tuple[str, ...]
    truth_signal_refs: tuple[str, ...]
    non_truth_signal_refs: tuple[str, ...]
    revenue_metric_export: ScrimRevenueMetricExport
    no_grant_policy: ScrimValueConversionNoGrantPolicy = Field(
        default_factory=ScrimValueConversionNoGrantPolicy
    )

    @model_validator(mode="after")
    def _validate_no_grant_boundary(self) -> Self:
        if self.posture == "conversion_ready":
            if self.blocker_dimensions or self.blocked_reasons:
                raise ValueError("ready conversion cues cannot retain blockers")
            if self.readiness_state not in policy_for_cue_family(self.cue_family).ready_states:
                raise ValueError("ready conversion cue must use a cue-family ready state")
        if any(ref.startswith(TRUTH_FORBIDDEN_PREFIXES) for ref in self.truth_signal_refs):
            raise ValueError("conversion/readiness/revenue refs cannot be truth signal refs")
        forbidden_language = ("truth", "claim confidence", "freshness", "public-live")
        lowered = self.cue_language.lower()
        if any(token in lowered for token in forbidden_language):
            raise ValueError(
                "conversion cue language must not imply truth/confidence/freshness/live"
            )
        return self

    @property
    def is_ready(self) -> bool:
        return self.posture == "conversion_ready"

    @property
    def is_held(self) -> bool:
        return self.posture in {"conversion_held", "monetization_held"}


POLICY_ROWS: tuple[ScrimConversionCuePolicyRow, ...] = (
    ScrimConversionCuePolicyRow(
        cue_family="archive",
        allowed_target_families=("youtube_vod_packaging",),
        ready_states=("public-archive", "public-live", "public-monetizable"),
        ready_language="Archive packaging is ready from conversion evidence.",
        held_language="Archive packaging is held pending conversion evidence.",
    ),
    ScrimConversionCuePolicyRow(
        cue_family="replay",
        allowed_target_families=("replay_demo",),
        ready_states=("public-archive", "public-live", "public-monetizable"),
        ready_language="Replay packaging is ready from conversion evidence.",
        held_language="Replay packaging is held pending conversion evidence.",
    ),
    ScrimConversionCuePolicyRow(
        cue_family="artifact",
        allowed_target_families=("dataset_card", "artifact_edition_release", "licensing"),
        ready_states=("public-archive", "public-monetizable"),
        ready_language="Artifact packaging is ready from conversion evidence.",
        held_language="Artifact packaging is held pending conversion evidence.",
    ),
    ScrimConversionCuePolicyRow(
        cue_family="support",
        allowed_target_families=("support_prompt",),
        ready_states=("public-live", "public-monetizable"),
        ready_language="Support path is ready from conversion evidence.",
        held_language="Support path is held pending readiness evidence.",
    ),
    ScrimConversionCuePolicyRow(
        cue_family="grant",
        allowed_target_families=("grants_fellowships", "residency"),
        ready_states=("private-evidence", "dry-run"),
        ready_language="Grant packet evidence is ready for internal conversion.",
        held_language="Grant packet evidence is held pending readiness evidence.",
    ),
    ScrimConversionCuePolicyRow(
        cue_family="monetization",
        allowed_target_families=(
            "youtube_vod_packaging",
            "replay_demo",
            "artifact_edition_release",
            "support_prompt",
            "licensing",
        ),
        ready_states=("public-monetizable",),
        ready_language="Monetization path is ready from readiness evidence.",
        held_language="Monetization path is held pending readiness evidence.",
    ),
)
_POLICY_BY_CUE = {row.cue_family: row for row in POLICY_ROWS}


def policy_for_cue_family(cue_family: ScrimConversionCueFamily) -> ScrimConversionCuePolicyRow:
    """Return the static policy row for a cue family."""

    return _POLICY_BY_CUE[cue_family]


def project_scrim_value_conversion_cue(
    cue: ScrimValueConversionCueInput,
) -> ScrimValueConversionCueProjection:
    """Project a conversion/readiness input into a bounded scrim cue."""

    policy = policy_for_cue_family(cue.cue_family)
    blocker_dimensions, blocked_reasons = _derive_blockers(cue, policy)
    posture = _select_posture(cue, policy, blocker_dimensions, blocked_reasons)
    return ScrimValueConversionCueProjection(
        projection_id=f"scrim_value_conversion_cue:{cue.cue_id}",
        cue_id=cue.cue_id,
        run_id=cue.run_id,
        cue_family=cue.cue_family,
        target_family_id=cue.target_family_id,
        requested_state=cue.requested_state,
        readiness_state=cue.readiness_state,
        format_id=cue.format_id,
        format_family=FORMAT_FAMILY_BY_FORMAT[cue.format_id],
        source_class=cue.source_class,
        rights_class=cue.rights_class,
        public_private_mode=cue.public_private_mode,
        posture=posture,
        visibility_treatment=_visibility_treatment(posture),
        cue_language=_cue_language(policy, posture),
        conversion_refs=cue.conversion_refs,
        readiness_evidence_refs=cue.readiness_evidence_refs,
        source_event_refs=cue.source_event_refs,
        blocker_dimensions=blocker_dimensions,
        blocked_reasons=blocked_reasons,
        truth_signal_refs=(),
        non_truth_signal_refs=_non_truth_signal_refs(cue),
        revenue_metric_export=ScrimRevenueMetricExport(
            format_id=cue.format_id,
            format_family=FORMAT_FAMILY_BY_FORMAT[cue.format_id],
            source_class=cue.source_class,
            rights_class=cue.rights_class,
            public_private_mode=cue.public_private_mode,
            revenue_potential_score=cue.revenue_potential_score,
            metric_refs=cue.revenue_metric_refs,
        ),
    )


def _derive_blockers(
    cue: ScrimValueConversionCueInput,
    policy: ScrimConversionCuePolicyRow,
) -> tuple[tuple[GateDimension, ...], tuple[str, ...]]:
    dimensions = list(cue.missing_gate_dimensions)
    reasons = list(cue.blocked_reasons)

    if cue.readiness_state not in policy.ready_states:
        reasons.append(f"readiness_state:{cue.readiness_state}")
    if cue.rights_class in RIGHTS_BLOCKING_CLASSES:
        _append_once(dimensions, "rights")
        reasons.append(f"rights_class:{cue.rights_class}")
    if cue.operator_labor_policy != "no_recurring_operator_labor":
        _append_once(dimensions, "no_hidden_operator_labor")
        reasons.append(f"operator_labor_policy:{cue.operator_labor_policy}")
    if cue.supporter_programming_policy == "supporter_controlled_programming":
        _append_once(dimensions, "no_hidden_operator_labor")
        reasons.append("supporter_controlled_programming")
    if cue.readiness_state in PUBLIC_VALUE_STATES and cue.public_private_mode in {
        "private",
        "dry_run",
    }:
        _append_once(dimensions, "public_event")
        reasons.append(f"public_private_mode:{cue.public_private_mode}")

    return _dedupe(dimensions), _dedupe(reasons)


def _select_posture(
    cue: ScrimValueConversionCueInput,
    policy: ScrimConversionCuePolicyRow,
    blocker_dimensions: tuple[GateDimension, ...],
    blocked_reasons: tuple[str, ...],
) -> ScrimConversionCuePosture:
    if (
        not blocker_dimensions
        and not blocked_reasons
        and cue.readiness_state in policy.ready_states
    ):
        return "conversion_ready"
    if cue.cue_family == "monetization" or "monetization" in blocker_dimensions:
        return "monetization_held"
    if cue.requested_state == "public-monetizable" and cue.readiness_state != "public-monetizable":
        return "monetization_held"
    return "conversion_held"


def _visibility_treatment(posture: ScrimConversionCuePosture) -> ScrimConversionCueTreatment:
    return {
        "conversion_ready": "conversion_cue_visible",
        "conversion_held": "conversion_held_visible",
        "monetization_held": "monetization_held_visible",
    }[posture]


def _cue_language(
    policy: ScrimConversionCuePolicyRow,
    posture: ScrimConversionCuePosture,
) -> str:
    return policy.ready_language if posture == "conversion_ready" else policy.held_language


def _non_truth_signal_refs(cue: ScrimValueConversionCueInput) -> tuple[str, ...]:
    return _dedupe(
        (
            *cue.conversion_refs,
            *cue.readiness_evidence_refs,
            *cue.source_event_refs,
            *cue.revenue_metric_refs,
            f"cue-family:{cue.cue_family}",
            f"target-family:{cue.target_family_id}",
        )
    )


def _append_once(values: list[GateDimension], value: GateDimension) -> None:
    if value not in values:
        values.append(value)


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
