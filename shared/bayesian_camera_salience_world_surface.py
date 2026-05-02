"""Bayesian camera salience broker for WCS-backed perception evidence.

This module is the contract layer for cc-task
``bayesian-camera-salience-world-surface-broker``.  It does not run a camera
classifier, open devices, or wire runtime consumers.  Existing producers such
as ``VisionBackend``, the cross-camera stitcher, IR presence, compositor
snapshots, archive windows, and WCS semantic state hand their outputs to this
broker as typed evidence envelopes.  The broker then returns compact,
authority-bounded salience bundles for downstream consumers.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
BAYESIAN_CAMERA_SALIENCE_FIXTURES = (
    REPO_ROOT / "config" / "bayesian-camera-salience-world-surface-fixtures.json"
)

REQUIRED_APERTURE_KINDS = frozenset(
    {
        "studio_rgb_camera",
        "studio_ir_camera",
        "livestream_composed_frame",
        "archive_video_window",
        "semantic_surface_state",
        "future_sensor",
    }
)

REQUIRED_EVIDENCE_CLASSES = frozenset(
    {
        "frame",
        "object_track",
        "composed_livestream",
        "archive_window",
        "ir_presence",
        "cross_camera_tracklet",
        "semantic_state",
    }
)

REQUIRED_CONSUMERS = frozenset(
    {
        "director",
        "affordance",
        "content_opportunity",
        "voice",
        "wcs_health",
        "archive",
        "visual_variance",
    }
)

FAIL_CLOSED_POLICY = {
    "classification_alone_authorizes_public_truth": False,
    "classifier_label_authorizes_clip_label": False,
    "classifier_label_authorizes_caption_or_title": False,
    "classifier_label_authorizes_director_success": False,
    "stale_observation_affects_current_claim": False,
    "unknown_evidence_counts_as_absence": False,
    "low_voi_recruits_expensive_model": False,
    "private_frame_attached_to_public_query": False,
    "parallel_vision_stack_allowed": False,
}

_BANNED_PRODUCERS = frozenset({"parallel_vision_stack", "standalone_camera_classifier"})


class CameraSalienceError(ValueError):
    """Raised when camera salience fixtures or envelopes fail closed."""


class ObservationApertureKind(StrEnum):
    STUDIO_RGB_CAMERA = "studio_rgb_camera"
    STUDIO_IR_CAMERA = "studio_ir_camera"
    LIVESTREAM_COMPOSED_FRAME = "livestream_composed_frame"
    ARCHIVE_VIDEO_WINDOW = "archive_video_window"
    SEMANTIC_SURFACE_STATE = "semantic_surface_state"
    FUTURE_SENSOR = "future_sensor"


class EvidenceClass(StrEnum):
    FRAME = "frame"
    OBJECT_TRACK = "object_track"
    COMPOSED_LIVESTREAM = "composed_livestream"
    ARCHIVE_WINDOW = "archive_window"
    IR_PRESENCE = "ir_presence"
    CROSS_CAMERA_TRACKLET = "cross_camera_tracklet"
    SEMANTIC_STATE = "semantic_state"


class ProducerKind(StrEnum):
    VISION_BACKEND = "vision_backend"
    CROSS_CAMERA_STITCHER = "cross_camera_stitcher"
    IR_PRESENCE_BACKEND = "ir_presence_backend"
    CONTACT_MIC_IR_FUSION = "contact_mic_ir_fusion"
    COMPOSITOR_SNAPSHOT = "compositor_snapshot"
    ARCHIVE_REPLAY_INDEX = "archive_replay_index"
    WCS_SEMANTIC_SURFACE = "wcs_semantic_surface"
    FUTURE_SENSOR_ADAPTER = "future_sensor_adapter"
    PARALLEL_VISION_STACK = "parallel_vision_stack"
    STANDALONE_CAMERA_CLASSIFIER = "standalone_camera_classifier"


class ConsumerKind(StrEnum):
    DIRECTOR = "director"
    AFFORDANCE = "affordance"
    CONTENT_OPPORTUNITY = "content_opportunity"
    VOICE = "voice"
    WCS_HEALTH = "wcs_health"
    ARCHIVE = "archive"
    VISUAL_VARIANCE = "visual_variance"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class ObservationState(StrEnum):
    OBSERVED = "observed"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"
    STALE = "stale"
    OCCLUDED = "occluded"
    CONTRADICTORY = "contradictory"
    BLOCKED = "blocked"


class TemporalWindowKind(StrEnum):
    CURRENT_FRAME = "current_frame"
    ACTIVITY_WINDOW = "activity_window"
    CONTEXT_WINDOW = "context_window"
    ARCHIVE_REFERENCE = "archive_reference"
    CROSS_CAMERA_DELTA = "cross_camera_delta"


class PrivacyMode(StrEnum):
    PRIVATE = "private"
    PUBLIC_SAFE = "public_safe"
    DRY_RUN = "dry_run"
    BLOCKED = "blocked"


class PublicClaimMode(StrEnum):
    NONE = "none"
    PUBLIC_SUMMARY = "public_summary"
    PUBLIC_LIVE = "public_live"
    PUBLIC_ARCHIVE = "public_archive"


class ClaimAuthorityCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    INTERNAL_ONLY = "internal_only"
    PRIVATE_ONLY = "private_only"
    EVIDENCE_BOUND = "evidence_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class ImageAttachmentMode(StrEnum):
    OMIT = "omit"
    REF_ONLY = "ref_only"
    CROP_ALLOWED = "crop_allowed"
    RAW_FRAME_ALLOWED = "raw_frame_allowed"


class CameraFreshness(BaseModel):
    """Freshness metadata with an explicit WCS/source reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: FreshnessState
    checked_at: str
    ttl_s: int | None = Field(default=None, ge=0)
    observed_age_s: int | None = Field(default=None, ge=0)
    source_ref: str | None = None

    @model_validator(mode="after")
    def _validate_freshness_contract(self) -> Self:
        if self.state is FreshnessState.FRESH:
            if self.ttl_s is None or self.observed_age_s is None or not self.source_ref:
                raise ValueError("fresh evidence requires ttl_s, observed_age_s, and source_ref")
            if self.observed_age_s > self.ttl_s:
                raise ValueError("fresh evidence cannot exceed ttl_s")
        if self.state is FreshnessState.STALE and not self.source_ref:
            raise ValueError("stale evidence requires a stale source_ref")
        return self


class ObservationAperture(BaseModel):
    """Registered environmental aperture the salience broker may consult."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    aperture_id: str = Field(pattern=r"^aperture:[a-z0-9_.:-]+$")
    kind: ObservationApertureKind
    modality: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    semantic_role: str = Field(min_length=1)
    supported_evidence_classes: tuple[EvidenceClass, ...] = Field(min_length=1)
    resource_cost: float = Field(ge=0.0)
    latency_cost_ms: int = Field(ge=0)
    privacy_mode: PrivacyMode
    public_claim_ceiling: ClaimAuthorityCeiling
    wcs_surface_refs: tuple[str, ...] = Field(min_length=1)
    topology_refs: tuple[str, ...] = Field(default_factory=tuple)
    producer_refs: tuple[str, ...] = Field(min_length=1)
    route_refs: tuple[str, ...] = Field(min_length=1)
    freshness_ttl_s: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_aperture_contract(self) -> Self:
        if (
            self.kind is ObservationApertureKind.STUDIO_IR_CAMERA
            and EvidenceClass.IR_PRESENCE not in self.supported_evidence_classes
        ):
            raise ValueError("IR apertures must support ir_presence evidence")
        if (
            self.kind is ObservationApertureKind.LIVESTREAM_COMPOSED_FRAME
            and EvidenceClass.COMPOSED_LIVESTREAM not in self.supported_evidence_classes
        ):
            raise ValueError("livestream apertures must support composed_livestream evidence")
        if (
            self.kind is ObservationApertureKind.ARCHIVE_VIDEO_WINDOW
            and EvidenceClass.ARCHIVE_WINDOW not in self.supported_evidence_classes
        ):
            raise ValueError("archive apertures must support archive_window evidence")
        if (
            self.kind is ObservationApertureKind.FUTURE_SENSOR
            and self.public_claim_ceiling is not ClaimAuthorityCeiling.NO_CLAIM
        ):
            raise ValueError("future sensors cannot ship public claim authority")
        return self


class CameraTemporalWindow(BaseModel):
    """Temporal span for frame, activity-window, archive, or tracklet evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_id: str = Field(pattern=r"^camera-window:[a-z0-9_.:-]+$")
    kind: TemporalWindowKind
    aperture_id: str
    observed_at: str
    duration_s: float = Field(ge=0.0)
    span_ref: str = Field(min_length=1)
    start_ref: str | None = None
    end_ref: str | None = None

    @model_validator(mode="after")
    def _archive_windows_need_bounds(self) -> Self:
        if self.kind is TemporalWindowKind.ARCHIVE_REFERENCE and (
            not self.start_ref or not self.end_ref
        ):
            raise ValueError("archive reference windows require start_ref and end_ref")
        return self


ScalarMetadata = str | int | float | bool


class CameraEvidenceRow(BaseModel):
    """One likelihood row consumed by the Bayesian posterior update."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_ref: str = Field(min_length=1)
    evidence_class: EvidenceClass
    hypothesis: str = Field(min_length=1)
    likelihood: float = Field(ge=0.001, le=0.999)
    confidence: float = Field(ge=0.0, le=1.0)
    observation_state: ObservationState
    supports_hypothesis: bool = True
    source_refs: tuple[str, ...] = Field(min_length=1)
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    span_refs: tuple[str, ...] = Field(default_factory=tuple)
    wcs_refs: tuple[str, ...] = Field(min_length=1)
    metadata: dict[str, ScalarMetadata] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_evidence_refs(self) -> Self:
        if self.evidence_class is not EvidenceClass.SEMANTIC_STATE and (
            not self.witness_refs or not self.span_refs
        ):
            raise ValueError(f"{self.evidence_ref} requires witness_refs and span_refs")
        if self.evidence_class is EvidenceClass.CROSS_CAMERA_TRACKLET:
            required = {"topology_path", "time_delta_s", "similarity", "uncertainty"}
            missing = sorted(required - set(self.metadata))
            if missing:
                raise ValueError(
                    f"{self.evidence_ref} missing cross-camera metadata: " + ", ".join(missing)
                )
        return self


class CameraObservationEnvelope(BaseModel):
    """Typed observation packet supplied by an existing perception producer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    envelope_id: str = Field(pattern=r"^camera-observation:[a-z0-9_.:-]+$")
    aperture_id: str
    aperture_kind: ObservationApertureKind
    producer: ProducerKind
    evidence_class: EvidenceClass
    observation_state: ObservationState
    temporal_window: CameraTemporalWindow
    freshness: CameraFreshness
    confidence: float = Field(ge=0.0, le=1.0)
    semantic_labels: tuple[str, ...] = Field(default_factory=tuple)
    evidence_rows: tuple[CameraEvidenceRow, ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    wcs_surface_refs: tuple[str, ...] = Field(min_length=1)
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    span_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    authority_ceiling: ClaimAuthorityCeiling
    privacy_mode: PrivacyMode
    image_ref: str | None = None
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    stale_refs: tuple[str, ...] = Field(default_factory=tuple)
    negative_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    classification_public_claim_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _validate_observation_contract(self) -> Self:
        if self.producer.value in _BANNED_PRODUCERS:
            raise ValueError("camera salience cannot create or consume a parallel vision stack")
        if self.evidence_class is EvidenceClass.IR_PRESENCE and (
            self.aperture_kind is not ObservationApertureKind.STUDIO_IR_CAMERA
        ):
            raise ValueError("ir_presence evidence requires an IR aperture")
        if self.evidence_class is EvidenceClass.COMPOSED_LIVESTREAM and (
            self.aperture_kind is not ObservationApertureKind.LIVESTREAM_COMPOSED_FRAME
        ):
            raise ValueError("composed_livestream evidence requires livestream aperture")
        if self.evidence_class is EvidenceClass.ARCHIVE_WINDOW and (
            self.aperture_kind is not ObservationApertureKind.ARCHIVE_VIDEO_WINDOW
        ):
            raise ValueError("archive_window evidence requires archive aperture")
        if any(row.evidence_class is not self.evidence_class for row in self.evidence_rows):
            raise ValueError("observation evidence_rows must match envelope evidence_class")
        if self.evidence_class is not EvidenceClass.SEMANTIC_STATE and (
            not self.witness_refs or not self.span_refs
        ):
            raise ValueError("camera observations require witness_refs and span_refs")
        if self.freshness.state is FreshnessState.FRESH and self.observation_state in {
            ObservationState.STALE,
            ObservationState.UNKNOWN,
            ObservationState.BLOCKED,
        }:
            raise ValueError("fresh freshness cannot wrap stale/unknown/blocked state")
        if self.freshness.state is FreshnessState.STALE and (
            not self.stale_refs or "stale_evidence" not in self.blocked_reasons
        ):
            raise ValueError("stale camera observations require stale refs and blocker")
        if (
            self.observation_state
            in {
                ObservationState.UNKNOWN,
                ObservationState.OCCLUDED,
                ObservationState.BLOCKED,
            }
            and not self.blocked_reasons
        ):
            raise ValueError("unknown/occluded/blocked observations require blocked_reasons")
        if self.observation_state is ObservationState.NEGATIVE and not self.negative_evidence_refs:
            raise ValueError("negative evidence must name negative_evidence_refs")
        return self


class CameraSalienceQuery(BaseModel):
    """Typed query API accepted by the broker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    query_id: str = Field(pattern=r"^camera-salience-query:[a-z0-9_.:-]+$")
    consumer: ConsumerKind
    decision_context: str = Field(min_length=1)
    candidate_action: str = Field(min_length=1)
    time_budget_ms: int = Field(ge=0)
    privacy_mode: PrivacyMode
    public_claim_mode: PublicClaimMode
    evidence_classes: tuple[EvidenceClass, ...] = Field(min_length=1)
    max_images: int = Field(ge=0)
    max_tokens: int = Field(ge=0)
    min_expected_value: float = Field(default=0.05, ge=0.0)
    min_posterior: float = Field(default=0.35, ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)


class CameraSaliencePosterior(BaseModel):
    """Bayesian posterior over one environmental hypothesis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hypothesis: str = Field(min_length=1)
    prior: float = Field(ge=0.001, le=0.999)
    likelihood: float = Field(ge=0.001, le=0.999)
    posterior: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    supporting_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    contradicting_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    stale_or_blocked_refs: tuple[str, ...] = Field(default_factory=tuple)
    authority_ceiling: ClaimAuthorityCeiling
    public_claim_allowed: Literal[False] = False


class ValueOfInformation(BaseModel):
    """Expected value calculation used for aperture/window selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    aperture_id: str
    hypothesis: str
    decision_change_probability: float = Field(ge=0.0, le=1.0)
    decision_utility: float = Field(ge=0.0)
    sensing_cost: float = Field(ge=0.0)
    latency_cost: float = Field(ge=0.0)
    privacy_risk_cost: float = Field(ge=0.0)
    contention_cost: float = Field(ge=0.0)
    expected_value: float
    selected: bool
    no_op_reason: str | None = None

    @model_validator(mode="after")
    def _validate_selection(self) -> Self:
        if self.selected and self.expected_value < 0:
            raise ValueError("selected VOI rows cannot have negative expected_value")
        if not self.selected and not self.no_op_reason:
            raise ValueError("unselected VOI rows require no_op_reason")
        return self


class ImageAttachmentPolicy(BaseModel):
    """Whether the bundle may carry image refs or raw/cropped imagery."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: ImageAttachmentMode
    max_images: int = Field(ge=0)
    attachment_refs: tuple[str, ...] = Field(default_factory=tuple)
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_attachment_bounds(self) -> Self:
        if self.mode is ImageAttachmentMode.OMIT and self.attachment_refs:
            raise ValueError("omitted image attachments cannot carry refs")
        if len(self.attachment_refs) > self.max_images:
            raise ValueError("image attachment refs exceed max_images")
        if self.mode in {ImageAttachmentMode.CROP_ALLOWED, ImageAttachmentMode.RAW_FRAME_ALLOWED}:
            if not self.attachment_refs:
                raise ValueError("image attachment modes require attachment refs")
        return self


class PublicClaimPolicy(BaseModel):
    """Public claim prevention for classifier-derived salience."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authority_ceiling: ClaimAuthorityCeiling
    public_truth_allowed: Literal[False] = False
    public_clip_label_allowed: Literal[False] = False
    public_caption_allowed: Literal[False] = False
    public_title_allowed: Literal[False] = False
    director_success_allowed: Literal[False] = False
    blocked_reasons: tuple[str, ...] = Field(min_length=1)


class RankedCameraObservation(BaseModel):
    """One ranked salience result with compact evidence refs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rank: int = Field(ge=1)
    envelope_id: str
    aperture_id: str
    evidence_class: EvidenceClass
    posterior_hypothesis: str
    value_of_information: ValueOfInformation
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    summary: str = Field(min_length=1)


class CameraSalienceBundle(BaseModel):
    """Bounded answer returned to director/WCS/archive/etc. consumers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    bundle_id: str = Field(pattern=r"^camera-salience-bundle:[a-z0-9_.:-]+$")
    generated_at: str
    query: CameraSalienceQuery
    ranked_observations: tuple[RankedCameraObservation, ...] = Field(default_factory=tuple)
    posterior_summary: tuple[CameraSaliencePosterior, ...] = Field(default_factory=tuple)
    uncertainty: float = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    blocked_or_stale_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_claim_ceiling: ClaimAuthorityCeiling
    image_attachment_policy: ImageAttachmentPolicy
    recommended_next_probe: str = Field(min_length=1)
    public_claim_policy: PublicClaimPolicy

    @model_validator(mode="after")
    def _validate_bundle_contract(self) -> Self:
        if self.public_claim_policy.authority_ceiling is not self.public_claim_ceiling:
            raise ValueError("public claim policy must mirror bundle public_claim_ceiling")
        if (
            self.query.public_claim_mode is not PublicClaimMode.NONE
            and self.image_attachment_policy.mode is not ImageAttachmentMode.OMIT
        ):
            raise ValueError("public claim queries cannot receive image attachments")
        ranked_refs = {ref for row in self.ranked_observations for ref in row.evidence_refs}
        if not set(self.evidence_refs).issubset(ranked_refs | set(self.blocked_or_stale_refs)):
            raise ValueError("bundle evidence_refs must come from ranked or blocked refs")
        return self

    def to_director_world_surface_projection(self) -> dict[str, Any]:
        """Return compact director-readable data without compositor internals."""

        return {
            "query_id": self.query.query_id,
            "consumer": self.query.consumer.value,
            "candidate_action": self.query.candidate_action,
            "public_claim_ceiling": self.public_claim_ceiling.value,
            "public_truth_allowed": False,
            "image_attachment_mode": self.image_attachment_policy.mode.value,
            "ranked": [
                {
                    "rank": row.rank,
                    "aperture_id": row.aperture_id,
                    "evidence_class": row.evidence_class.value,
                    "hypothesis": row.posterior_hypothesis,
                    "expected_value": row.value_of_information.expected_value,
                    "evidence_refs": list(row.evidence_refs),
                }
                for row in self.ranked_observations
            ],
            "blocked_or_stale_refs": list(self.blocked_or_stale_refs),
        }

    def to_wcs_projection_payload(self) -> dict[str, Any]:
        """Return WCS-oriented refs, ceilings, and freshness blockers."""

        return {
            "bundle_id": self.bundle_id,
            "evidence_refs": list(self.evidence_refs),
            "blocked_or_stale_refs": list(self.blocked_or_stale_refs),
            "public_claim_ceiling": self.public_claim_ceiling.value,
            "claim_authorizations": {
                "public_truth": False,
                "public_clip_label": False,
                "public_caption": False,
                "public_title": False,
                "director_success": False,
            },
            "recommended_next_probe": self.recommended_next_probe,
        }


class CameraSalienceBroker:
    """Pure Bayesian/VOI broker over already-produced camera evidence."""

    def __init__(
        self,
        apertures: tuple[ObservationAperture, ...],
        observations: tuple[CameraObservationEnvelope, ...],
    ) -> None:
        self.apertures = {aperture.aperture_id: aperture for aperture in apertures}
        self.observations = observations
        for observation in observations:
            aperture = self.apertures.get(observation.aperture_id)
            if aperture is None:
                raise CameraSalienceError(f"unknown aperture for observation: {observation}")
            if observation.evidence_class not in aperture.supported_evidence_classes:
                raise CameraSalienceError(
                    f"{observation.envelope_id} uses unsupported evidence class "
                    f"{observation.evidence_class.value}"
                )

    def evaluate(
        self,
        query: CameraSalienceQuery,
        *,
        priors: dict[str, float] | None = None,
        generated_at: str | None = None,
    ) -> CameraSalienceBundle:
        now = generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        blocked_or_stale_refs: list[str] = []
        rows_by_hypothesis: dict[str, list[tuple[CameraEvidenceRow, CameraObservationEnvelope]]] = (
            defaultdict(list)
        )

        for observation in self.observations:
            if observation.evidence_class not in query.evidence_classes:
                continue
            if not _observation_is_fresh_enough(observation):
                blocked_or_stale_refs.extend(_blocked_refs_for(observation))
                continue
            for row in observation.evidence_rows:
                if (
                    row.confidence < query.min_confidence
                    or observation.confidence < query.min_confidence
                ):
                    blocked_or_stale_refs.append(f"{row.evidence_ref}:low_confidence")
                    continue
                rows_by_hypothesis[row.hypothesis].append((row, observation))

        posterior_summary = tuple(
            self._posterior_for_hypothesis(hypothesis, row_pairs, priors or {})
            for hypothesis, row_pairs in sorted(rows_by_hypothesis.items())
        )
        ranked = self._rank_posteriors(query, posterior_summary, rows_by_hypothesis)
        selected_ranked = tuple(row for row in ranked if row.value_of_information.selected)
        evidence_refs = tuple(
            dict.fromkeys(ref for row in selected_ranked for ref in row.evidence_refs)
        )
        uncertainty = _bundle_uncertainty(posterior_summary)
        image_policy = _image_policy_for(query, selected_ranked, self.observations)
        ceiling = _bundle_public_claim_ceiling(query, selected_ranked, posterior_summary)
        recommended_next_probe = _recommended_probe(selected_ranked, blocked_or_stale_refs)

        return CameraSalienceBundle(
            bundle_id=f"camera-salience-bundle:{query.query_id.removeprefix('camera-salience-query:')}",
            generated_at=now,
            query=query,
            ranked_observations=selected_ranked,
            posterior_summary=posterior_summary,
            uncertainty=uncertainty,
            evidence_refs=evidence_refs,
            blocked_or_stale_refs=tuple(dict.fromkeys(blocked_or_stale_refs)),
            public_claim_ceiling=ceiling,
            image_attachment_policy=image_policy,
            recommended_next_probe=recommended_next_probe,
            public_claim_policy=PublicClaimPolicy(
                authority_ceiling=ceiling,
                blocked_reasons=(
                    "classifier_salience_requires_wcs_public_gate",
                    "classification_alone_cannot_authorize_public_truth",
                ),
            ),
        )

    def _posterior_for_hypothesis(
        self,
        hypothesis: str,
        row_pairs: list[tuple[CameraEvidenceRow, CameraObservationEnvelope]],
        priors: dict[str, float],
    ) -> CameraSaliencePosterior:
        prior = _clamp_probability(priors.get(hypothesis, 0.50))
        log_odds = _logit(prior)
        likelihoods: list[float] = []
        supporting: list[str] = []
        contradicting: list[str] = []
        ceilings: list[ClaimAuthorityCeiling] = []
        stale_or_blocked: list[str] = []

        for row, observation in row_pairs:
            weight = row.confidence * observation.confidence
            likelihood = _clamp_probability(row.likelihood)
            likelihoods.append(likelihood)
            delta = _logit(likelihood) * weight
            if row.supports_hypothesis:
                log_odds += delta
                supporting.append(row.evidence_ref)
            else:
                log_odds -= delta
                contradicting.append(row.evidence_ref)
            ceilings.append(_min_ceiling(row.wcs_refs, observation.authority_ceiling))
            stale_or_blocked.extend(_blocked_refs_for(observation))

        posterior = _clamp_probability(_inv_logit(log_odds))
        uncertainty = _posterior_uncertainty(posterior, bool(supporting), bool(contradicting))
        return CameraSaliencePosterior(
            hypothesis=hypothesis,
            prior=prior,
            likelihood=_clamp_probability(sum(likelihoods) / len(likelihoods)),
            posterior=posterior,
            uncertainty=uncertainty,
            supporting_evidence_refs=tuple(dict.fromkeys(supporting)),
            contradicting_evidence_refs=tuple(dict.fromkeys(contradicting)),
            stale_or_blocked_refs=tuple(dict.fromkeys(stale_or_blocked)),
            authority_ceiling=_lowest_authority(ceilings)
            if ceilings
            else ClaimAuthorityCeiling.NO_CLAIM,
        )

    def _rank_posteriors(
        self,
        query: CameraSalienceQuery,
        posterior_summary: tuple[CameraSaliencePosterior, ...],
        rows_by_hypothesis: dict[str, list[tuple[CameraEvidenceRow, CameraObservationEnvelope]]],
    ) -> tuple[RankedCameraObservation, ...]:
        ranked: list[RankedCameraObservation] = []
        rank = 1
        for posterior in sorted(
            posterior_summary,
            key=lambda row: row.posterior - row.uncertainty * 0.25,
            reverse=True,
        ):
            row_pairs = rows_by_hypothesis[posterior.hypothesis]
            first_observation = row_pairs[0][1]
            voi = _value_of_information(
                query,
                posterior,
                first_observation,
                self.apertures[first_observation.aperture_id],
            )
            if not voi.selected:
                continue
            refs = tuple(
                dict.fromkeys(
                    [
                        *posterior.supporting_evidence_refs,
                        *posterior.contradicting_evidence_refs,
                    ]
                )
            )
            ranked.append(
                RankedCameraObservation(
                    rank=rank,
                    envelope_id=first_observation.envelope_id,
                    aperture_id=first_observation.aperture_id,
                    evidence_class=first_observation.evidence_class,
                    posterior_hypothesis=posterior.hypothesis,
                    value_of_information=voi,
                    evidence_refs=refs,
                    summary=_summary_for(posterior, first_observation),
                )
            )
            rank += 1
        return tuple(ranked)


class CameraSalienceFixtureSet(BaseModel):
    """Fixture packet validating apertures, evidence classes, and fail-closed policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: Literal["schemas/bayesian-camera-salience-world-surface.schema.json"]
    declared_at: str
    generated_from: tuple[str, ...] = Field(min_length=1)
    required_aperture_kinds: tuple[ObservationApertureKind, ...] = Field(min_length=1)
    required_evidence_classes: tuple[EvidenceClass, ...] = Field(min_length=1)
    required_consumers: tuple[ConsumerKind, ...] = Field(min_length=1)
    apertures: tuple[ObservationAperture, ...] = Field(min_length=1)
    observations: tuple[CameraObservationEnvelope, ...] = Field(min_length=1)
    queries: tuple[CameraSalienceQuery, ...] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_fixture_contract(self) -> Self:
        kinds = {kind.value for kind in self.required_aperture_kinds}
        if kinds != REQUIRED_APERTURE_KINDS:
            raise ValueError("fixture packet must name every required aperture kind")
        evidence_classes = {klass.value for klass in self.required_evidence_classes}
        if evidence_classes != REQUIRED_EVIDENCE_CLASSES:
            raise ValueError("fixture packet must name every required evidence class")
        consumers = {consumer.value for consumer in self.required_consumers}
        if consumers != REQUIRED_CONSUMERS:
            raise ValueError("fixture packet must name every required consumer")
        aperture_kinds = {aperture.kind.value for aperture in self.apertures}
        missing_kinds = REQUIRED_APERTURE_KINDS - aperture_kinds
        if missing_kinds:
            raise ValueError("apertures missing kinds: " + ", ".join(sorted(missing_kinds)))
        observed_classes = {observation.evidence_class.value for observation in self.observations}
        missing_classes = REQUIRED_EVIDENCE_CLASSES - observed_classes
        if missing_classes:
            raise ValueError("observations missing evidence classes: " + ", ".join(missing_classes))
        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("camera salience fail_closed_policy must pin gates false")
        aperture_ids = [aperture.aperture_id for aperture in self.apertures]
        duplicates = sorted(
            {aperture_id for aperture_id in aperture_ids if aperture_ids.count(aperture_id) > 1}
        )
        if duplicates:
            raise ValueError("duplicate aperture ids: " + ", ".join(duplicates))
        self._validate_observation_apertures()
        return self

    def _validate_observation_apertures(self) -> None:
        apertures = {aperture.aperture_id: aperture for aperture in self.apertures}
        for observation in self.observations:
            aperture = apertures.get(observation.aperture_id)
            if aperture is None:
                raise ValueError(f"{observation.envelope_id} references unknown aperture")
            if observation.evidence_class not in aperture.supported_evidence_classes:
                raise ValueError(f"{observation.envelope_id} evidence class not supported")

    def broker(self) -> CameraSalienceBroker:
        return CameraSalienceBroker(self.apertures, self.observations)

    def query_by_id(self, query_id: str) -> CameraSalienceQuery:
        for query in self.queries:
            if query.query_id == query_id:
                return query
        raise KeyError(f"unknown salience query: {query_id}")


def adapt_vision_backend_observation(
    *,
    aperture: ObservationAperture,
    envelope_id: str,
    evidence_class: EvidenceClass,
    observed_at: str,
    semantic_labels: tuple[str, ...],
    confidence: float,
    evidence_ref: str,
    hypothesis: str,
    likelihood: float,
    span_ref: str,
    witness_ref: str,
    source_ref: str,
    observed_age_s: int,
) -> CameraObservationEnvelope:
    """Wrap existing ``VisionBackend`` output without running another classifier."""

    return _single_row_observation(
        aperture=aperture,
        envelope_id=envelope_id,
        producer=ProducerKind.VISION_BACKEND,
        evidence_class=evidence_class,
        observed_at=observed_at,
        semantic_labels=semantic_labels,
        confidence=confidence,
        evidence_ref=evidence_ref,
        hypothesis=hypothesis,
        likelihood=likelihood,
        span_ref=span_ref,
        witness_ref=witness_ref,
        source_ref=source_ref,
        observed_age_s=observed_age_s,
    )


def adapt_ir_presence_observation(
    *,
    aperture: ObservationAperture,
    envelope_id: str,
    observed_at: str,
    confidence: float,
    evidence_ref: str,
    hypothesis: str,
    likelihood: float,
    span_ref: str,
    witness_ref: str,
    source_ref: str,
    observed_age_s: int,
) -> CameraObservationEnvelope:
    """Wrap IR presence/hand-zone evidence into the shared posterior model."""

    return _single_row_observation(
        aperture=aperture,
        envelope_id=envelope_id,
        producer=ProducerKind.IR_PRESENCE_BACKEND,
        evidence_class=EvidenceClass.IR_PRESENCE,
        observed_at=observed_at,
        semantic_labels=("ir_presence",),
        confidence=confidence,
        evidence_ref=evidence_ref,
        hypothesis=hypothesis,
        likelihood=likelihood,
        span_ref=span_ref,
        witness_ref=witness_ref,
        source_ref=source_ref,
        observed_age_s=observed_age_s,
    )


def adapt_cross_camera_tracklet(
    *,
    aperture: ObservationAperture,
    envelope_id: str,
    observed_at: str,
    evidence_ref: str,
    hypothesis: str,
    confidence: float,
    span_ref: str,
    witness_ref: str,
    source_ref: str,
    topology_path: str,
    time_delta_s: float,
    similarity: float,
    uncertainty: float,
    observed_age_s: int,
) -> CameraObservationEnvelope:
    """Wrap ``agents.models.cross_camera`` merge suggestions as evidence."""

    return _single_row_observation(
        aperture=aperture,
        envelope_id=envelope_id,
        producer=ProducerKind.CROSS_CAMERA_STITCHER,
        evidence_class=EvidenceClass.CROSS_CAMERA_TRACKLET,
        observed_at=observed_at,
        semantic_labels=("cross_camera_tracklet",),
        confidence=confidence,
        evidence_ref=evidence_ref,
        hypothesis=hypothesis,
        likelihood=max(0.001, min(0.999, similarity)),
        span_ref=span_ref,
        witness_ref=witness_ref,
        source_ref=source_ref,
        observed_age_s=observed_age_s,
        metadata={
            "topology_path": topology_path,
            "time_delta_s": time_delta_s,
            "similarity": similarity,
            "uncertainty": uncertainty,
        },
    )


def load_camera_salience_fixtures(
    path: Path = BAYESIAN_CAMERA_SALIENCE_FIXTURES,
) -> CameraSalienceFixtureSet:
    """Load the camera salience fixture packet, failing closed on drift."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise CameraSalienceError(f"{path} did not contain a JSON object")
        return CameraSalienceFixtureSet.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise CameraSalienceError(f"invalid camera salience fixtures at {path}: {exc}") from exc


def _single_row_observation(
    *,
    aperture: ObservationAperture,
    envelope_id: str,
    producer: ProducerKind,
    evidence_class: EvidenceClass,
    observed_at: str,
    semantic_labels: tuple[str, ...],
    confidence: float,
    evidence_ref: str,
    hypothesis: str,
    likelihood: float,
    span_ref: str,
    witness_ref: str,
    source_ref: str,
    observed_age_s: int,
    metadata: dict[str, ScalarMetadata] | None = None,
) -> CameraObservationEnvelope:
    row = CameraEvidenceRow(
        evidence_ref=evidence_ref,
        evidence_class=evidence_class,
        hypothesis=hypothesis,
        likelihood=likelihood,
        confidence=confidence,
        observation_state=ObservationState.OBSERVED,
        source_refs=(source_ref,),
        witness_refs=(witness_ref,),
        span_refs=(span_ref,),
        wcs_refs=aperture.wcs_surface_refs,
        metadata=metadata or {},
    )
    window = CameraTemporalWindow(
        window_id=f"camera-window:{envelope_id.removeprefix('camera-observation:')}",
        kind=TemporalWindowKind.CURRENT_FRAME,
        aperture_id=aperture.aperture_id,
        observed_at=observed_at,
        duration_s=0.0,
        span_ref=span_ref,
    )
    return CameraObservationEnvelope(
        envelope_id=envelope_id,
        aperture_id=aperture.aperture_id,
        aperture_kind=aperture.kind,
        producer=producer,
        evidence_class=evidence_class,
        observation_state=ObservationState.OBSERVED,
        temporal_window=window,
        freshness=CameraFreshness(
            state=FreshnessState.FRESH,
            checked_at=observed_at,
            ttl_s=aperture.freshness_ttl_s,
            observed_age_s=observed_age_s,
            source_ref=source_ref,
        ),
        confidence=confidence,
        semantic_labels=semantic_labels,
        evidence_rows=(row,),
        source_refs=(source_ref,),
        wcs_surface_refs=aperture.wcs_surface_refs,
        witness_refs=(witness_ref,),
        span_refs=(span_ref,),
        authority_ceiling=aperture.public_claim_ceiling,
        privacy_mode=aperture.privacy_mode,
        image_ref=f"image-ref:{envelope_id.removeprefix('camera-observation:')}",
    )


def _observation_is_fresh_enough(observation: CameraObservationEnvelope) -> bool:
    return (
        observation.freshness.state is FreshnessState.FRESH
        and observation.observation_state
        in {
            ObservationState.OBSERVED,
            ObservationState.NEGATIVE,
            ObservationState.CONTRADICTORY,
        }
    )


def _blocked_refs_for(observation: CameraObservationEnvelope) -> list[str]:
    refs = [*observation.stale_refs, *observation.negative_evidence_refs]
    refs.extend(
        f"{observation.envelope_id}:blocker:{reason}" for reason in observation.blocked_reasons
    )
    if observation.freshness.state is not FreshnessState.FRESH:
        refs.append(f"{observation.envelope_id}:freshness:{observation.freshness.state.value}")
    return list(dict.fromkeys(refs))


def _value_of_information(
    query: CameraSalienceQuery,
    posterior: CameraSaliencePosterior,
    observation: CameraObservationEnvelope,
    aperture: ObservationAperture,
) -> ValueOfInformation:
    decision_change = max(0.0, posterior.posterior - query.min_posterior)
    decision_change *= max(0.0, 1.0 - posterior.uncertainty * 0.35)
    utility = _consumer_utility(query.consumer)
    sensing_cost = aperture.resource_cost * 0.08
    latency_cost = (
        min(1.0, aperture.latency_cost_ms / max(1, query.time_budget_ms)) * 0.20
        if query.time_budget_ms
        else 0.20
    )
    privacy_cost = (
        0.18
        if query.public_claim_mode is not PublicClaimMode.NONE
        and (observation.privacy_mode is not PrivacyMode.PUBLIC_SAFE)
        else 0.0
    )
    contention_cost = aperture.resource_cost * 0.05
    expected_value = (
        decision_change * utility - sensing_cost - latency_cost - privacy_cost - contention_cost
    )
    selected = (
        expected_value >= query.min_expected_value and posterior.posterior >= query.min_posterior
    )
    no_op_reason = None
    if not selected:
        if posterior.posterior < query.min_posterior:
            no_op_reason = "posterior_below_floor"
        elif expected_value < query.min_expected_value:
            no_op_reason = "expected_value_below_cost"
        else:
            no_op_reason = "not_selected"
    return ValueOfInformation(
        aperture_id=observation.aperture_id,
        hypothesis=posterior.hypothesis,
        decision_change_probability=round(decision_change, 6),
        decision_utility=utility,
        sensing_cost=round(sensing_cost, 6),
        latency_cost=round(latency_cost, 6),
        privacy_risk_cost=round(privacy_cost, 6),
        contention_cost=round(contention_cost, 6),
        expected_value=round(expected_value, 6),
        selected=selected,
        no_op_reason=no_op_reason,
    )


def _image_policy_for(
    query: CameraSalienceQuery,
    ranked: tuple[RankedCameraObservation, ...],
    observations: tuple[CameraObservationEnvelope, ...],
) -> ImageAttachmentPolicy:
    if query.public_claim_mode is not PublicClaimMode.NONE:
        return ImageAttachmentPolicy(
            mode=ImageAttachmentMode.OMIT,
            max_images=query.max_images,
            blocked_reasons=("public_claim_queries_receive_refs_not_images",),
        )
    if query.max_images == 0 or not ranked:
        return ImageAttachmentPolicy(
            mode=ImageAttachmentMode.OMIT,
            max_images=query.max_images,
            blocked_reasons=("no_images_requested_or_no_selected_observation",),
        )
    by_id = {observation.envelope_id: observation for observation in observations}
    refs = [
        observation.image_ref
        for row in ranked
        if (observation := by_id.get(row.envelope_id)) is not None and observation.image_ref
    ]
    if not refs:
        return ImageAttachmentPolicy(
            mode=ImageAttachmentMode.OMIT,
            max_images=query.max_images,
            blocked_reasons=("no_image_refs_available",),
        )
    return ImageAttachmentPolicy(
        mode=ImageAttachmentMode.REF_ONLY,
        max_images=query.max_images,
        attachment_refs=tuple(refs[: query.max_images]),
    )


def _bundle_public_claim_ceiling(
    query: CameraSalienceQuery,
    ranked: tuple[RankedCameraObservation, ...],
    posteriors: tuple[CameraSaliencePosterior, ...],
) -> ClaimAuthorityCeiling:
    if query.public_claim_mode is PublicClaimMode.NONE:
        return ClaimAuthorityCeiling.INTERNAL_ONLY if ranked else ClaimAuthorityCeiling.NO_CLAIM
    if not ranked:
        return ClaimAuthorityCeiling.NO_CLAIM
    if any(
        posterior.authority_ceiling is ClaimAuthorityCeiling.PUBLIC_GATE_REQUIRED
        for posterior in posteriors
    ):
        return ClaimAuthorityCeiling.PUBLIC_GATE_REQUIRED
    return ClaimAuthorityCeiling.NO_CLAIM


def _recommended_probe(
    ranked: tuple[RankedCameraObservation, ...],
    blocked_or_stale_refs: list[str],
) -> str:
    if ranked:
        return f"probe:{ranked[0].aperture_id}"
    if blocked_or_stale_refs:
        return "refresh_stale_or_blocked_evidence"
    return "no_op:expected_value_below_cost"


def _summary_for(
    posterior: CameraSaliencePosterior,
    observation: CameraObservationEnvelope,
) -> str:
    return (
        f"{posterior.hypothesis} posterior={posterior.posterior:.2f} "
        f"uncertainty={posterior.uncertainty:.2f} via {observation.evidence_class.value}"
    )


def _consumer_utility(consumer: ConsumerKind) -> float:
    return {
        ConsumerKind.DIRECTOR: 1.00,
        ConsumerKind.AFFORDANCE: 0.90,
        ConsumerKind.CONTENT_OPPORTUNITY: 0.95,
        ConsumerKind.VOICE: 0.85,
        ConsumerKind.WCS_HEALTH: 0.80,
        ConsumerKind.ARCHIVE: 0.75,
        ConsumerKind.VISUAL_VARIANCE: 0.80,
    }[consumer]


def _posterior_uncertainty(
    posterior: float,
    has_supporting: bool,
    has_contradicting: bool,
) -> float:
    base = 1.0 - abs(posterior - 0.5) * 2.0
    if has_supporting and has_contradicting:
        base = max(base, 0.55)
    return round(max(0.0, min(1.0, base)), 6)


def _bundle_uncertainty(posteriors: tuple[CameraSaliencePosterior, ...]) -> float:
    if not posteriors:
        return 1.0
    return round(sum(posterior.uncertainty for posterior in posteriors) / len(posteriors), 6)


def _min_ceiling(
    wcs_refs: tuple[str, ...],
    observation_ceiling: ClaimAuthorityCeiling,
) -> ClaimAuthorityCeiling:
    if not wcs_refs:
        return ClaimAuthorityCeiling.NO_CLAIM
    return observation_ceiling


def _lowest_authority(ceilings: list[ClaimAuthorityCeiling]) -> ClaimAuthorityCeiling:
    order = {
        ClaimAuthorityCeiling.NO_CLAIM: 0,
        ClaimAuthorityCeiling.INTERNAL_ONLY: 1,
        ClaimAuthorityCeiling.PRIVATE_ONLY: 2,
        ClaimAuthorityCeiling.EVIDENCE_BOUND: 3,
        ClaimAuthorityCeiling.PUBLIC_GATE_REQUIRED: 4,
    }
    return min(ceilings, key=lambda ceiling: order[ceiling])


def _clamp_probability(value: float) -> float:
    return max(0.001, min(0.999, value))


def _logit(value: float) -> float:
    value = _clamp_probability(value)
    return math.log(value / (1.0 - value))


def _inv_logit(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


__all__ = [
    "BAYESIAN_CAMERA_SALIENCE_FIXTURES",
    "FAIL_CLOSED_POLICY",
    "REQUIRED_APERTURE_KINDS",
    "REQUIRED_CONSUMERS",
    "REQUIRED_EVIDENCE_CLASSES",
    "CameraEvidenceRow",
    "CameraFreshness",
    "CameraObservationEnvelope",
    "CameraSalienceBroker",
    "CameraSalienceBundle",
    "CameraSalienceError",
    "CameraSalienceFixtureSet",
    "CameraSaliencePosterior",
    "CameraSalienceQuery",
    "CameraTemporalWindow",
    "ClaimAuthorityCeiling",
    "ConsumerKind",
    "EvidenceClass",
    "FreshnessState",
    "ImageAttachmentMode",
    "ImageAttachmentPolicy",
    "ObservationAperture",
    "ObservationApertureKind",
    "ObservationState",
    "PrivacyMode",
    "ProducerKind",
    "PublicClaimMode",
    "PublicClaimPolicy",
    "RankedCameraObservation",
    "TemporalWindowKind",
    "ValueOfInformation",
    "adapt_cross_camera_tracklet",
    "adapt_ir_presence_observation",
    "adapt_vision_backend_observation",
    "load_camera_salience_fixtures",
]
