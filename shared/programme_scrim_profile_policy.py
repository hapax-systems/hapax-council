"""Programme-format to scrim-profile soft-prior policy.

This module deliberately emits scheduler hints only. WCS evidence, public
event gates, and director moves decide whether any scrim state can be used.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRAMME_SCRIM_PROFILE_POLICY = REPO_ROOT / "config" / "programme-scrim-profile-policy.json"

type TargetId = Literal[
    "tier_list",
    "ranking",
    "bracket",
    "react_commentary",
    "watch_along",
    "review",
    "explainer",
    "rundown",
    "what_is_this",
    "refusal_breakdown",
    "evidence_audit",
    "failure_autopsy",
    "listening",
    "hothouse",
    "ritual_boundary",
]
type TargetKind = Literal["format", "programme_posture"]
type FormatId = Literal[
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
type ProgrammePosture = Literal["failure_autopsy", "listening", "hothouse", "ritual_boundary"]
type ScrimProfile = Literal[
    "gauzy_quiet",
    "warm_haze",
    "moire_crackle",
    "clarity_peak",
    "dissolving",
    "ritual_open",
    "rain_streak",
]
type PermeabilityMode = Literal["semipermeable_membrane", "solute_suspension", "ionised_glow"]
type FocusRegionKind = Literal[
    "criteria_table",
    "source_metadata",
    "rank_trace",
    "object_focus",
    "refusal_reason",
    "correction_boundary",
    "conversion_held_state",
    "timeline",
    "question_frame",
    "listening_field",
    "ritual_boundary_marker",
]
type BlockerState = Literal[
    "missing_evidence_ref",
    "missing_grounding_gate",
    "grounding_gate_failed",
    "source_stale",
    "rights_blocked",
    "privacy_blocked",
    "consent_blocked",
    "public_event_missing",
    "world_surface_blocked",
    "health_failed",
    "monetization_blocked",
    "monetization_readiness_missing",
    "conversion_held",
    "operator_review_required",
    "unknown_state",
]
type FallbackMode = Literal["none", "neutral_hold", "minimum_density"]
type PublicPrivateMode = Literal[
    "private", "dry_run", "public_live", "public_archive", "public_monetizable"
]
type EvidenceStatus = Literal[
    "fresh", "stale", "missing", "unknown", "blocked", "private_only", "dry_run"
]
type WcsHealthState = Literal[
    "healthy",
    "degraded",
    "blocked",
    "unsafe",
    "stale",
    "missing",
    "unknown",
    "private_only",
    "dry_run",
    "quiet_off_air",
    "candidate",
]
type RightsState = Literal[
    "operator_original", "cleared", "platform_embed_only", "blocked", "unknown"
]
type PrivacyState = Literal[
    "operator_private", "public_safe", "aggregate_only", "blocked", "unknown"
]
type GateState = Literal["pass", "fail", "missing", "unknown"]
type PublicEventState = Literal["linked", "required", "missing", "held", "blocked", "not_public"]
type MonetizationState = Literal["not_requested", "ready", "blocked", "unknown"]
type ConversionState = Literal[
    "candidate", "held", "blocked", "linked", "emitted", "not_applicable"
]


class ProgrammeScrimProfilePolicyError(ValueError):
    """Raised when the programme-scrim policy cannot be loaded."""


class PolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LegibilityConstraints(PolicyModel):
    oq02_minimum_translucency: float = Field(ge=0.2, le=0.85)
    oq02_label_required: Literal[True]
    anti_visualizer_required: Literal[True]
    audio_reactive_visualizer_allowed: Literal[False]
    preserve_operator_foreground: Literal[True]
    max_motion_rate: float = Field(ge=0.0, le=0.65)


class ProfilePrior(PolicyModel):
    profile_id: ScrimProfile
    permeability_mode: PermeabilityMode
    weight: float = Field(ge=0.0, le=1.0)
    priority: int = Field(ge=0, le=100)
    density: float = Field(ge=0.0, le=1.0)
    refraction: float = Field(ge=0.0, le=1.0)
    motion_rate: float = Field(ge=0.0, le=1.0)
    depth_bias: float = Field(ge=0.0, le=1.0)
    focus_region_kinds: tuple[FocusRegionKind, ...]
    legibility_constraints: LegibilityConstraints
    rationale: str


class BlockedExposure(PolicyModel):
    scheduler_field: Literal["unavailable_profile_reasons"]
    runner_field: Literal["blocked_reasons"]
    include_blocked_reasons: Literal[True]
    include_unavailable_profile_reasons: Literal[True]


class PolicyTarget(PolicyModel):
    target_id: TargetId
    target_kind: TargetKind
    display_name: str
    covered_format_ids: tuple[FormatId, ...] = Field(default_factory=tuple)
    covered_postures: tuple[ProgrammePosture, ...] = Field(default_factory=tuple)
    grounding_intent: str
    profile_priors: tuple[ProfilePrior, ...]
    blocked_exposure: BlockedExposure

    def preferred_prior(self) -> ProfilePrior:
        """Return the strongest soft prior. Callers still need WCS/director approval."""
        return max(self.profile_priors, key=lambda prior: (prior.priority, prior.weight))


class SoftPriorOnlyPolicy(PolicyModel):
    policy_grants_public_claim_authority: Literal[False]
    policy_grants_live_control: Literal[False]
    policy_can_override_wcs_blockers: Literal[False]
    wcs_decision_required: Literal[True]
    director_decision_required: Literal[True]
    scheduler_hint_only: Literal[True]


class WcsBlockerPolicy(PolicyModel):
    blocked_context_returns_profile: Literal[False]
    blocked_reasons_exposed: Literal[True]
    unavailable_profile_reasons_required: Literal[True]
    blocked_fallback_mode: Literal["neutral_hold", "minimum_density"]
    blocker_states: tuple[BlockerState, ...]


class ProgrammeScrimProfilePolicy(PolicyModel):
    schema_version: Literal[1]
    policy_id: str
    schema_ref: Literal["schemas/programme-scrim-profile-policy.schema.json"]
    generated_at: str
    content_programme_format_schema_ref: Literal["schemas/content-programme-format.schema.json"]
    scrim_state_schema_ref: Literal["schemas/scrim-state-envelope.schema.json"]
    soft_prior_only: SoftPriorOnlyPolicy
    wcs_blocker_policy: WcsBlockerPolicy
    targets: tuple[PolicyTarget, ...]

    def target(self, target_id: str) -> PolicyTarget:
        for target in self.targets:
            if target.target_id == target_id:
                return target
        raise KeyError(f"unknown programme scrim policy target: {target_id}")


class ProfileSelectionContext(PolicyModel):
    public_private_mode: PublicPrivateMode = "public_archive"
    evidence_status: EvidenceStatus = "fresh"
    health_state: WcsHealthState = "healthy"
    rights_state: RightsState = "operator_original"
    privacy_state: PrivacyState = "public_safe"
    grounding_gate_state: GateState = "pass"
    public_event_state: PublicEventState = "linked"
    monetization_state: MonetizationState = "not_requested"
    conversion_state: ConversionState = "not_applicable"
    explicit_blocked_reasons: tuple[BlockerState, ...] = Field(default_factory=tuple)

    def blocker_states(self) -> tuple[BlockerState, ...]:
        blockers: list[BlockerState] = list(self.explicit_blocked_reasons)

        if self.evidence_status in {"missing", "unknown", "blocked"}:
            blockers.append("missing_evidence_ref")
        elif self.evidence_status == "stale":
            blockers.append("source_stale")

        if self.grounding_gate_state == "missing":
            blockers.append("missing_grounding_gate")
        elif self.grounding_gate_state in {"fail", "unknown"}:
            blockers.append("grounding_gate_failed")

        if self.health_state in {"blocked", "unsafe"}:
            blockers.append("world_surface_blocked")
        elif self.health_state in {"stale", "missing", "unknown"}:
            blockers.append("health_failed")

        if self.rights_state == "blocked":
            blockers.append("rights_blocked")
        elif self.rights_state == "unknown":
            blockers.append("unknown_state")

        if self.privacy_state == "blocked":
            blockers.append("privacy_blocked")
        elif self.privacy_state == "unknown":
            blockers.append("unknown_state")

        if self.public_event_state in {"missing", "held", "blocked"}:
            blockers.append("public_event_missing")

        if self.public_private_mode == "public_monetizable":
            if self.monetization_state == "blocked":
                blockers.append("monetization_blocked")
            elif self.monetization_state != "ready":
                blockers.append("monetization_readiness_missing")

        if self.conversion_state == "held":
            blockers.append("conversion_held")
        elif self.conversion_state == "blocked":
            blockers.append("operator_review_required")

        return tuple(dict.fromkeys(blockers))


class ProfileSelectionResult(PolicyModel):
    target_id: str
    selected_profile_id: ScrimProfile | None
    selected_permeability_mode: PermeabilityMode | None
    selected_weight: float | None
    selected_priority: int | None
    focus_region_kinds: tuple[FocusRegionKind, ...]
    fallback_mode: FallbackMode
    blocked_reasons: tuple[BlockerState, ...]
    unavailable_profile_reasons: tuple[str, ...]
    candidate_profile_ids: tuple[ScrimProfile, ...]
    scheduler_hint_only: Literal[True]
    soft_prior_only: Literal[True]
    wcs_decision_required: Literal[True]
    director_decision_required: Literal[True]
    public_claim_allowed: Literal[False]

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_reasons)


def load_policy(path: Path = PROGRAMME_SCRIM_PROFILE_POLICY) -> ProgrammeScrimProfilePolicy:
    """Load the machine-readable policy, failing closed on malformed packets."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ProgrammeScrimProfilePolicy.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise ProgrammeScrimProfilePolicyError(
            f"invalid programme scrim profile policy: {exc}"
        ) from exc


@cache
def default_policy() -> ProgrammeScrimProfilePolicy:
    return load_policy()


def select_profile_prior(
    target_id: str,
    context: ProfileSelectionContext | None = None,
    *,
    policy: ProgrammeScrimProfilePolicy | None = None,
) -> ProfileSelectionResult:
    """Select a soft scrim prior or expose why profiles are unavailable.

    Returning ``selected_profile_id=None`` is the expected fail-closed behavior
    whenever WCS evidence, health, rights/privacy, public-event, monetization,
    or conversion blockers exist.
    """
    resolved_policy = policy or default_policy()
    target = resolved_policy.target(target_id)
    resolved_context = context or ProfileSelectionContext()
    blockers = tuple(
        blocker
        for blocker in resolved_context.blocker_states()
        if blocker in resolved_policy.wcs_blocker_policy.blocker_states
    )
    candidate_profile_ids = tuple(prior.profile_id for prior in target.profile_priors)

    if blockers:
        unavailable = tuple(
            f"{target.target_id}:{profile_id}:unavailable:{blocker}"
            for profile_id in candidate_profile_ids
            for blocker in blockers
        )
        return ProfileSelectionResult(
            target_id=target.target_id,
            selected_profile_id=None,
            selected_permeability_mode=None,
            selected_weight=None,
            selected_priority=None,
            focus_region_kinds=(),
            fallback_mode=resolved_policy.wcs_blocker_policy.blocked_fallback_mode,
            blocked_reasons=blockers,
            unavailable_profile_reasons=unavailable,
            candidate_profile_ids=candidate_profile_ids,
            scheduler_hint_only=True,
            soft_prior_only=True,
            wcs_decision_required=True,
            director_decision_required=True,
            public_claim_allowed=False,
        )

    prior = target.preferred_prior()
    return ProfileSelectionResult(
        target_id=target.target_id,
        selected_profile_id=prior.profile_id,
        selected_permeability_mode=prior.permeability_mode,
        selected_weight=prior.weight,
        selected_priority=prior.priority,
        focus_region_kinds=prior.focus_region_kinds,
        fallback_mode="none",
        blocked_reasons=(),
        unavailable_profile_reasons=(),
        candidate_profile_ids=candidate_profile_ids,
        scheduler_hint_only=True,
        soft_prior_only=True,
        wcs_decision_required=True,
        director_decision_required=True,
        public_claim_allowed=False,
    )


__all__ = [
    "PROGRAMME_SCRIM_PROFILE_POLICY",
    "ProfileSelectionContext",
    "ProfileSelectionResult",
    "ProgrammeScrimProfilePolicy",
    "ProgrammeScrimProfilePolicyError",
    "default_policy",
    "load_policy",
    "select_profile_prior",
]
