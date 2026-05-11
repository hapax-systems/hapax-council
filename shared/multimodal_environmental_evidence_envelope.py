"""Multimodal environmental evidence envelope.

This module is a contract surface for camera, IR, livestream, archive,
public-reembed, classifier, HOMAGE/render-state, and synthetic/audit evidence.
It keeps lineage, freshness, witnesses, privacy/rights, and claim ceilings
together so raw labels or render state cannot silently become public truth.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
MULTIMODAL_ENVIRONMENTAL_EVIDENCE_FIXTURES = (
    REPO_ROOT / "config" / "multimodal-environmental-evidence-envelope-fixtures.json"
)

REQUIRED_SOURCE_CLASSES = frozenset(
    {
        "raw_camera",
        "ir_fusion",
        "composed_livestream",
        "archive_replay",
        "public_event",
        "classifier_label",
        "homage_render_state",
        "decorative_ward_render_state",
        "synthetic_marker",
    }
)

REQUIRED_FIXTURE_CASES = frozenset(
    {
        "fresh",
        "stale",
        "missing",
        "blank",
        "contradictory",
        "archive_only",
        "public_reembed",
        "synthetic_only",
    }
)

MULTIMODAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS = (
    "schema_version",
    "envelope_id",
    "source_family",
    "source_class",
    "source_payload_state",
    "observed_at",
    "valid_until",
    "raw_refs",
    "transform_chain",
    "aperture_id",
    "camera_role",
    "perceptual_field_key",
    "confidence",
    "uncertainty",
    "freshness",
    "observation_polarity",
    "privacy_state",
    "rights_state",
    "witness_kind",
    "witness_refs",
    "temporal_span_refs",
    "wcs_refs",
    "public_event_refs",
    "claim_authority_ceiling",
    "ir_training_state",
    "scene_classifier_fallback",
    "diagnostic_reason_codes",
    "fixture_case",
)

FAIL_CLOSED_POLICY = {
    "raw_camera_implies_public_claim": False,
    "ir_no_detection_undertrained_counts_as_absence": False,
    "scene_classifier_fallback_zero_confidence_satisfies_claim": False,
    "composed_livestream_blank_counts_as_negative_truth": False,
    "archive_replay_counts_as_live": False,
    "public_reembed_counts_as_live_scene_truth": False,
    "synthetic_marker_satisfies_factual_claim": False,
    "decorative_ward_render_state_satisfies_factual_claim": False,
}

_SOURCE_CLASS_FAMILY = {
    "raw_camera": "camera",
    "ir_fusion": "ir",
    "composed_livestream": "livestream",
    "archive_replay": "archive",
    "public_event": "public_event",
    "classifier_label": "classifier",
    "homage_render_state": "render_state",
    "decorative_ward_render_state": "render_state",
    "synthetic_marker": "synthetic",
}


class MultimodalEnvironmentalEvidenceError(ValueError):
    """Raised when multimodal environmental evidence fails validation."""


class SourceFamily(StrEnum):
    CAMERA = "camera"
    IR = "ir"
    LIVESTREAM = "livestream"
    ARCHIVE = "archive"
    PUBLIC_EVENT = "public_event"
    CLASSIFIER = "classifier"
    RENDER_STATE = "render_state"
    SYNTHETIC = "synthetic"


class SourceClass(StrEnum):
    RAW_CAMERA = "raw_camera"
    IR_FUSION = "ir_fusion"
    COMPOSED_LIVESTREAM = "composed_livestream"
    ARCHIVE_REPLAY = "archive_replay"
    PUBLIC_EVENT = "public_event"
    CLASSIFIER_LABEL = "classifier_label"
    HOMAGE_RENDER_STATE = "homage_render_state"
    DECORATIVE_WARD_RENDER_STATE = "decorative_ward_render_state"
    SYNTHETIC_MARKER = "synthetic_marker"


class SourcePayloadState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    BLANK = "blank"
    CONTRADICTORY = "contradictory"
    ARCHIVE_ONLY = "archive_only"
    PUBLIC_REEMBED = "public_reembed"
    SYNTHETIC_ONLY = "synthetic_only"
    RENDER_STATE = "render_state"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ObservationPolarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"
    DIAGNOSTIC = "diagnostic"
    RENDER_STATE = "render_state"


class PrivacyState(StrEnum):
    PUBLIC_SAFE = "public_safe"
    PRIVATE_ONLY = "private_only"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class RightsState(StrEnum):
    PUBLIC_CLEAR = "public_clear"
    PRIVATE_ONLY = "private_only"
    BLOCKED = "blocked"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class WitnessKind(StrEnum):
    SENSOR_FRAME = "sensor_frame"
    IR_FUSION_REPORT = "ir_fusion_report"
    BROADCAST_FRAME = "broadcast_frame"
    ARCHIVE_SPAN = "archive_span"
    PUBLIC_EVENT = "public_event"
    CLASSIFIER_OUTPUT = "classifier_output"
    RENDER_STATE = "render_state"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class ClaimAuthorityCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    RENDER_STATE_ONLY = "render_state_only"
    LAST_OBSERVED_ONLY = "last_observed_only"
    PRIVATE_EVIDENCE_BOUND = "private_evidence_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class CameraRole(StrEnum):
    OPERATOR = "operator"
    DESK = "desk"
    OVERHEAD = "overhead"
    ROOM = "room"
    LIVESTREAM_COMPOSITE = "livestream_composite"
    ARCHIVE_REPLAY = "archive_replay"
    PUBLIC_EVENT = "public_event"
    HOMAGE = "homage"
    DECORATIVE_WARD = "decorative_ward"
    SYNTHETIC = "synthetic"
    NOT_APPLICABLE = "not_applicable"


class IrTrainingState(StrEnum):
    CALIBRATED = "calibrated"
    UNDERTRAINED = "undertrained"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ClaimShape(StrEnum):
    PRESENT_CURRENT = "present_current"
    ABSENCE = "absence"
    PUBLIC_LIVE = "public_live"
    LAST_OBSERVED = "last_observed"
    PUBLIC_REEMBED = "public_reembed"
    ARCHIVE_REPLAY = "archive_replay"
    DIAGNOSTIC = "diagnostic"
    RENDER_STATE = "render_state"


class ClaimSupportStatus(StrEnum):
    ALLOWED = "allowed"
    ALLOWED_LAST_OBSERVED_ONLY = "allowed_last_observed_only"
    ALLOWED_PUBLIC_REEMBED_REFS_ONLY = "allowed_public_reembed_refs_only"
    ALLOWED_DIAGNOSTIC_ONLY = "allowed_diagnostic_only"
    ALLOWED_RENDER_STATE_ONLY = "allowed_render_state_only"
    BLOCKED_STALE_OR_EXPIRED = "blocked_stale_or_expired"
    BLOCKED_MISSING_OR_BLANK = "blocked_missing_or_blank"
    BLOCKED_CONTRADICTORY = "blocked_contradictory"
    BLOCKED_NEUTRAL_IR_NO_DETECTION = "blocked_neutral_ir_no_detection"
    BLOCKED_CLASSIFIER_FALLBACK = "blocked_classifier_fallback"
    BLOCKED_SYNTHETIC_ONLY = "blocked_synthetic_only"
    BLOCKED_RENDER_STATE_NOT_FACTUAL = "blocked_render_state_not_factual"
    BLOCKED_ARCHIVE_NOT_LIVE = "blocked_archive_not_live"
    BLOCKED_PUBLIC_REEMBED_NOT_LIVE_SCENE = "blocked_public_reembed_not_live_scene"
    BLOCKED_PUBLIC_GATE = "blocked_public_gate"
    BLOCKED_PRIVACY_RIGHTS = "blocked_privacy_rights"
    BLOCKED_MISSING_WITNESS = "blocked_missing_witness"
    BLOCKED_AUTHORITY_CEILING = "blocked_authority_ceiling"
    BLOCKED_OBSERVATION_POLARITY = "blocked_observation_polarity"


class RenderedClaimMode(StrEnum):
    PRESENT_CURRENT = "present_current"
    PUBLIC_LIVE = "public_live"
    LAST_OBSERVED_WITH_AGE_WINDOW = "last_observed_with_age_window"
    PUBLIC_REEMBED_REFS_ONLY = "public_reembed_refs_only"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    RENDER_STATE_ONLY = "render_state_only"
    NONE = "none"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MultimodalEnvironmentalEvidenceEnvelope(FrozenModel):
    """One evidence object from an environmental/aperture source."""

    schema_version: Literal[1] = 1
    envelope_id: str = Field(pattern=r"^multimodal-evidence:[a-z0-9_.:-]+$")
    source_family: SourceFamily
    source_class: SourceClass
    source_payload_state: SourcePayloadState
    observed_at: str
    valid_until: str
    raw_refs: tuple[str, ...] = Field(default_factory=tuple)
    transform_chain: tuple[str, ...] = Field(min_length=1)
    aperture_id: str = Field(pattern=r"^aperture:[a-z0-9_.:-]+$")
    camera_role: CameraRole
    perceptual_field_key: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    freshness: FreshnessState
    observation_polarity: ObservationPolarity
    privacy_state: PrivacyState
    rights_state: RightsState
    witness_kind: WitnessKind
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    temporal_span_refs: tuple[str, ...] = Field(default_factory=tuple)
    wcs_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    claim_authority_ceiling: ClaimAuthorityCeiling
    ir_training_state: IrTrainingState = IrTrainingState.NOT_APPLICABLE
    scene_classifier_fallback: bool = False
    diagnostic_reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    fixture_case: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_envelope_contract(self) -> Self:
        if _epoch(self.valid_until) < _epoch(self.observed_at):
            raise ValueError("valid_until cannot precede observed_at")

        expected_family = _SOURCE_CLASS_FAMILY[self.source_class.value]
        if self.source_family.value != expected_family:
            raise ValueError(f"{self.source_class.value} requires source_family={expected_family}")

        if (
            self.source_payload_state
            in {
                SourcePayloadState.FRESH,
                SourcePayloadState.ARCHIVE_ONLY,
                SourcePayloadState.PUBLIC_REEMBED,
                SourcePayloadState.RENDER_STATE,
            }
            and not self.raw_refs
        ):
            raise ValueError(f"{self.source_payload_state.value} evidence requires raw_refs")

        if self.source_payload_state in {
            SourcePayloadState.MISSING,
            SourcePayloadState.BLANK,
            SourcePayloadState.CONTRADICTORY,
        }:
            if self.claim_authority_ceiling is not ClaimAuthorityCeiling.NO_CLAIM:
                raise ValueError("missing/blank/contradictory evidence must keep no_claim")
            if not self.diagnostic_reason_codes:
                raise ValueError("missing/blank/contradictory evidence requires reason codes")

        if self.source_payload_state is SourcePayloadState.STALE:
            if self.claim_authority_ceiling not in {
                ClaimAuthorityCeiling.NO_CLAIM,
                ClaimAuthorityCeiling.LAST_OBSERVED_ONLY,
            }:
                raise ValueError("stale evidence can only be no_claim or last_observed_only")

        if self.source_class is SourceClass.IR_FUSION:
            if self.witness_kind is not WitnessKind.IR_FUSION_REPORT:
                raise ValueError("ir_fusion evidence requires witness_kind=ir_fusion_report")
            if (
                self.ir_training_state is IrTrainingState.UNDERTRAINED
                and self.observation_polarity is ObservationPolarity.NEGATIVE
            ):
                raise ValueError("undertrained IR no-detection must be neutral, not negative")
        elif self.ir_training_state is not IrTrainingState.NOT_APPLICABLE:
            raise ValueError("ir_training_state is only applicable to ir_fusion evidence")

        if self.source_class is SourceClass.CLASSIFIER_LABEL:
            if self.witness_kind is not WitnessKind.CLASSIFIER_OUTPUT:
                raise ValueError("classifier_label evidence requires classifier_output witness")
            if self.scene_classifier_fallback and self.confidence != 0.0:
                raise ValueError("scene classifier fallback fixtures must carry confidence 0.0")
            if (self.scene_classifier_fallback or self.confidence == 0.0) and (
                self.claim_authority_ceiling
                not in {ClaimAuthorityCeiling.NO_CLAIM, ClaimAuthorityCeiling.DIAGNOSTIC_ONLY}
            ):
                raise ValueError("zero-confidence classifier fallback cannot carry claim authority")
        elif self.scene_classifier_fallback:
            raise ValueError("scene_classifier_fallback is only valid for classifier_label")

        if self.source_class in {
            SourceClass.HOMAGE_RENDER_STATE,
            SourceClass.DECORATIVE_WARD_RENDER_STATE,
        }:
            if self.witness_kind is not WitnessKind.RENDER_STATE:
                raise ValueError("render state evidence requires witness_kind=render_state")
            if self.claim_authority_ceiling not in {
                ClaimAuthorityCeiling.NO_CLAIM,
                ClaimAuthorityCeiling.DIAGNOSTIC_ONLY,
                ClaimAuthorityCeiling.RENDER_STATE_ONLY,
            }:
                raise ValueError("render state cannot carry factual claim authority")
            if self.observation_polarity not in {
                ObservationPolarity.RENDER_STATE,
                ObservationPolarity.DIAGNOSTIC,
            }:
                raise ValueError("render state evidence must use render_state/diagnostic polarity")

        if (
            self.source_class is SourceClass.SYNTHETIC_MARKER
            or self.source_payload_state is SourcePayloadState.SYNTHETIC_ONLY
        ):
            if self.witness_kind is not WitnessKind.SYNTHETIC_FIXTURE:
                raise ValueError("synthetic evidence requires witness_kind=synthetic_fixture")
            if self.claim_authority_ceiling not in {
                ClaimAuthorityCeiling.NO_CLAIM,
                ClaimAuthorityCeiling.DIAGNOSTIC_ONLY,
            }:
                raise ValueError("synthetic evidence cannot carry factual claim authority")

        if self.claim_authority_ceiling is ClaimAuthorityCeiling.PUBLIC_GATE_REQUIRED:
            missing: list[str] = []
            if self.privacy_state is not PrivacyState.PUBLIC_SAFE:
                missing.append("public_safe privacy")
            if self.rights_state is not RightsState.PUBLIC_CLEAR:
                missing.append("public_clear rights")
            if not self.witness_refs:
                missing.append("witness refs")
            if not self.temporal_span_refs:
                missing.append("temporal span refs")
            if not self.public_event_refs:
                missing.append("public event refs")
            if missing:
                raise ValueError("public_gate_required missing " + ", ".join(missing))

        return self

    def expired_at(self, now: str) -> bool:
        """Return true if this evidence is outside its validity window."""

        return self.freshness is FreshnessState.EXPIRED or _epoch(now) > _epoch(self.valid_until)


class MultimodalClaimSupportRequest(FrozenModel):
    claim_id: str = Field(pattern=r"^claim:[a-z0-9_.:-]+$")
    claim_name: str = Field(min_length=1)
    claim_shape: ClaimShape
    public_or_director: bool
    now: str
    includes_age_window_language: bool = False


class MultimodalClaimSupportDecision(FrozenModel):
    claim_id: str
    envelope_id: str
    allowed: bool
    status: ClaimSupportStatus
    rendered_claim_mode: RenderedClaimMode
    authority_ceiling: ClaimAuthorityCeiling
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    required_language: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_decision_shape(self) -> Self:
        if self.allowed and self.status.value.startswith("blocked_"):
            raise ValueError("allowed decisions cannot use blocked status")
        if not self.allowed and self.rendered_claim_mode is not RenderedClaimMode.NONE:
            raise ValueError("blocked decisions must render no claim")
        if self.status is ClaimSupportStatus.ALLOWED_LAST_OBSERVED_ONLY:
            required = {"last_observed", "age_s", "valid_until"}
            if not required.issubset(set(self.required_language)):
                raise ValueError("last observed decisions require age/window language")
        return self


class MultimodalClaimSupportFixture(FrozenModel):
    fixture_case: str = Field(min_length=1)
    envelope_ref: str = Field(pattern=r"^multimodal-evidence:[a-z0-9_.:-]+$")
    request: MultimodalClaimSupportRequest
    expected: MultimodalClaimSupportDecision


class MultimodalEnvironmentalEvidenceFixtureSet(FrozenModel):
    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: Literal["schemas/multimodal-environmental-evidence-envelope.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: str
    required_source_classes: tuple[SourceClass, ...] = Field(min_length=1)
    required_fixture_cases: tuple[str, ...] = Field(min_length=1)
    evidence_envelope_required_fields: tuple[str, ...]
    fail_closed_policy: dict[str, bool]
    envelopes: tuple[MultimodalEnvironmentalEvidenceEnvelope, ...] = Field(min_length=1)
    claim_support_fixtures: tuple[MultimodalClaimSupportFixture, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_fixture_set(self) -> Self:
        if {source_class.value for source_class in self.required_source_classes} != (
            REQUIRED_SOURCE_CLASSES
        ):
            raise ValueError("required_source_classes drifted")
        if set(self.required_fixture_cases) != REQUIRED_FIXTURE_CASES:
            raise ValueError("required_fixture_cases drifted")
        if set(self.evidence_envelope_required_fields) != set(
            MULTIMODAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS
        ):
            raise ValueError("evidence_envelope_required_fields drifted")
        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("fail_closed_policy drifted")

        envelope_map = self.envelopes_by_id()
        source_classes = {envelope.source_class.value for envelope in self.envelopes}
        missing_source_classes = REQUIRED_SOURCE_CLASSES - source_classes
        if missing_source_classes:
            raise ValueError(f"missing source classes: {sorted(missing_source_classes)}")

        fixture_cases = {envelope.fixture_case for envelope in self.envelopes}
        missing_fixture_cases = REQUIRED_FIXTURE_CASES - fixture_cases
        if missing_fixture_cases:
            raise ValueError(f"missing fixture cases: {sorted(missing_fixture_cases)}")

        for fixture in self.claim_support_fixtures:
            envelope = envelope_map.get(fixture.envelope_ref)
            if envelope is None:
                raise ValueError(f"claim fixture cites unknown envelope: {fixture.envelope_ref}")
            actual = evaluate_multimodal_claim_support(envelope, fixture.request)
            if actual != fixture.expected:
                raise ValueError(f"claim support fixture drifted: {fixture.fixture_case}")
        return self

    def envelopes_by_id(self) -> dict[str, MultimodalEnvironmentalEvidenceEnvelope]:
        return {envelope.envelope_id: envelope for envelope in self.envelopes}


def evaluate_multimodal_claim_support(
    envelope: MultimodalEnvironmentalEvidenceEnvelope,
    request: MultimodalClaimSupportRequest,
) -> MultimodalClaimSupportDecision:
    """Return the fail-closed claim-support decision for one evidence envelope."""

    base = {
        "claim_id": request.claim_id,
        "envelope_id": envelope.envelope_id,
        "authority_ceiling": envelope.claim_authority_ceiling,
    }

    def block(
        status: ClaimSupportStatus,
        *reasons: str,
    ) -> MultimodalClaimSupportDecision:
        return MultimodalClaimSupportDecision(
            **base,
            allowed=False,
            status=status,
            rendered_claim_mode=RenderedClaimMode.NONE,
            reason_codes=tuple(reasons),
        )

    if envelope.source_payload_state in {SourcePayloadState.MISSING, SourcePayloadState.BLANK}:
        return block(
            ClaimSupportStatus.BLOCKED_MISSING_OR_BLANK,
            f"source_payload_state_{envelope.source_payload_state.value}",
        )
    if envelope.source_payload_state is SourcePayloadState.CONTRADICTORY:
        return block(ClaimSupportStatus.BLOCKED_CONTRADICTORY, "contradictory_sources")

    if envelope.source_class is SourceClass.SYNTHETIC_MARKER:
        if request.claim_shape is ClaimShape.DIAGNOSTIC:
            return MultimodalClaimSupportDecision(
                **base,
                allowed=True,
                status=ClaimSupportStatus.ALLOWED_DIAGNOSTIC_ONLY,
                rendered_claim_mode=RenderedClaimMode.DIAGNOSTIC_ONLY,
                required_language=("diagnostic_only",),
            )
        return block(ClaimSupportStatus.BLOCKED_SYNTHETIC_ONLY, "synthetic_marker")

    if envelope.source_class in {
        SourceClass.HOMAGE_RENDER_STATE,
        SourceClass.DECORATIVE_WARD_RENDER_STATE,
    }:
        if request.claim_shape is ClaimShape.RENDER_STATE:
            return MultimodalClaimSupportDecision(
                **base,
                allowed=True,
                status=ClaimSupportStatus.ALLOWED_RENDER_STATE_ONLY,
                rendered_claim_mode=RenderedClaimMode.RENDER_STATE_ONLY,
                required_language=("render_state_only",),
            )
        if request.claim_shape is ClaimShape.DIAGNOSTIC:
            return MultimodalClaimSupportDecision(
                **base,
                allowed=True,
                status=ClaimSupportStatus.ALLOWED_DIAGNOSTIC_ONLY,
                rendered_claim_mode=RenderedClaimMode.DIAGNOSTIC_ONLY,
                required_language=("diagnostic_only",),
            )
        return block(
            ClaimSupportStatus.BLOCKED_RENDER_STATE_NOT_FACTUAL,
            f"source_class_{envelope.source_class.value}",
        )

    if envelope.scene_classifier_fallback or envelope.confidence == 0.0:
        if request.claim_shape is ClaimShape.DIAGNOSTIC:
            return MultimodalClaimSupportDecision(
                **base,
                allowed=True,
                status=ClaimSupportStatus.ALLOWED_DIAGNOSTIC_ONLY,
                rendered_claim_mode=RenderedClaimMode.DIAGNOSTIC_ONLY,
                required_language=("classifier_fallback", "diagnostic_only"),
            )
        return block(
            ClaimSupportStatus.BLOCKED_CLASSIFIER_FALLBACK,
            "zero_confidence_or_fallback_classifier",
        )

    if (
        envelope.source_class is SourceClass.IR_FUSION
        and envelope.ir_training_state is IrTrainingState.UNDERTRAINED
        and envelope.observation_polarity is ObservationPolarity.NEUTRAL
        and request.claim_shape is ClaimShape.ABSENCE
    ):
        return block(
            ClaimSupportStatus.BLOCKED_NEUTRAL_IR_NO_DETECTION,
            "undertrained_ir_no_detection_is_neutral_not_negative",
        )

    if request.public_or_director:
        if envelope.privacy_state not in {PrivacyState.PUBLIC_SAFE, PrivacyState.PRIVATE_ONLY}:
            return block(
                ClaimSupportStatus.BLOCKED_PRIVACY_RIGHTS,
                f"privacy_state_{envelope.privacy_state.value}",
            )
        if envelope.rights_state in {
            RightsState.BLOCKED,
            RightsState.MISSING,
            RightsState.UNKNOWN,
        }:
            return block(
                ClaimSupportStatus.BLOCKED_PRIVACY_RIGHTS,
                f"rights_state_{envelope.rights_state.value}",
            )
        if not envelope.witness_refs or not envelope.temporal_span_refs:
            return block(
                ClaimSupportStatus.BLOCKED_MISSING_WITNESS,
                "witness_and_span_refs_required",
            )

    if request.claim_shape in {ClaimShape.PRESENT_CURRENT, ClaimShape.PUBLIC_LIVE}:
        if envelope.source_class is SourceClass.ARCHIVE_REPLAY:
            return block(ClaimSupportStatus.BLOCKED_ARCHIVE_NOT_LIVE, "archive_replay_not_live")
        if envelope.source_payload_state is SourcePayloadState.PUBLIC_REEMBED:
            return block(
                ClaimSupportStatus.BLOCKED_PUBLIC_REEMBED_NOT_LIVE_SCENE,
                "public_reembed_is_not_live_scene_truth",
            )
        if envelope.freshness is not FreshnessState.FRESH or envelope.expired_at(request.now):
            return block(
                ClaimSupportStatus.BLOCKED_STALE_OR_EXPIRED,
                f"freshness_{envelope.freshness.value}",
                "validity_window_expired" if envelope.expired_at(request.now) else "not_fresh",
            )
        if envelope.observation_polarity is not ObservationPolarity.POSITIVE:
            return block(
                ClaimSupportStatus.BLOCKED_OBSERVATION_POLARITY,
                f"observation_polarity_{envelope.observation_polarity.value}",
            )
        if request.claim_shape is ClaimShape.PUBLIC_LIVE:
            public_gate = _public_gate_reasons(envelope)
            if public_gate:
                return block(ClaimSupportStatus.BLOCKED_PUBLIC_GATE, *public_gate)
            return MultimodalClaimSupportDecision(
                **base,
                allowed=True,
                status=ClaimSupportStatus.ALLOWED,
                rendered_claim_mode=RenderedClaimMode.PUBLIC_LIVE,
            )
        if envelope.claim_authority_ceiling is ClaimAuthorityCeiling.NO_CLAIM:
            return block(ClaimSupportStatus.BLOCKED_AUTHORITY_CEILING, "authority_no_claim")
        return MultimodalClaimSupportDecision(
            **base,
            allowed=True,
            status=ClaimSupportStatus.ALLOWED,
            rendered_claim_mode=RenderedClaimMode.PRESENT_CURRENT,
        )

    if request.claim_shape in {ClaimShape.LAST_OBSERVED, ClaimShape.ARCHIVE_REPLAY}:
        if envelope.claim_authority_ceiling not in {
            ClaimAuthorityCeiling.LAST_OBSERVED_ONLY,
            ClaimAuthorityCeiling.PRIVATE_EVIDENCE_BOUND,
            ClaimAuthorityCeiling.PUBLIC_GATE_REQUIRED,
        }:
            return block(
                ClaimSupportStatus.BLOCKED_AUTHORITY_CEILING,
                f"authority_{envelope.claim_authority_ceiling.value}",
            )
        if not request.includes_age_window_language:
            return block(
                ClaimSupportStatus.BLOCKED_STALE_OR_EXPIRED,
                "last_observed_requires_age_window_language",
            )
        return MultimodalClaimSupportDecision(
            **base,
            allowed=True,
            status=ClaimSupportStatus.ALLOWED_LAST_OBSERVED_ONLY,
            rendered_claim_mode=RenderedClaimMode.LAST_OBSERVED_WITH_AGE_WINDOW,
            required_language=("last_observed", "age_s", "valid_until"),
        )

    if request.claim_shape is ClaimShape.PUBLIC_REEMBED:
        public_gate = _public_gate_reasons(envelope)
        if envelope.source_payload_state is not SourcePayloadState.PUBLIC_REEMBED:
            return block(
                ClaimSupportStatus.BLOCKED_PUBLIC_GATE,
                f"source_payload_state_{envelope.source_payload_state.value}",
            )
        if public_gate:
            return block(ClaimSupportStatus.BLOCKED_PUBLIC_GATE, *public_gate)
        return MultimodalClaimSupportDecision(
            **base,
            allowed=True,
            status=ClaimSupportStatus.ALLOWED_PUBLIC_REEMBED_REFS_ONLY,
            rendered_claim_mode=RenderedClaimMode.PUBLIC_REEMBED_REFS_ONLY,
            required_language=("public_reembed_refs_only",),
        )

    return MultimodalClaimSupportDecision(
        **base,
        allowed=True,
        status=ClaimSupportStatus.ALLOWED_DIAGNOSTIC_ONLY,
        rendered_claim_mode=RenderedClaimMode.DIAGNOSTIC_ONLY,
        required_language=("diagnostic_only",),
    )


def _public_gate_reasons(envelope: MultimodalEnvironmentalEvidenceEnvelope) -> tuple[str, ...]:
    reasons: list[str] = []
    if envelope.claim_authority_ceiling is not ClaimAuthorityCeiling.PUBLIC_GATE_REQUIRED:
        reasons.append(f"authority_{envelope.claim_authority_ceiling.value}")
    if envelope.privacy_state is not PrivacyState.PUBLIC_SAFE:
        reasons.append(f"privacy_{envelope.privacy_state.value}")
    if envelope.rights_state is not RightsState.PUBLIC_CLEAR:
        reasons.append(f"rights_{envelope.rights_state.value}")
    if not envelope.public_event_refs:
        reasons.append("public_event_refs_missing")
    if not envelope.witness_refs:
        reasons.append("witness_refs_missing")
    if not envelope.temporal_span_refs:
        reasons.append("temporal_span_refs_missing")
    return tuple(reasons)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MultimodalEnvironmentalEvidenceError(f"{path} did not contain a JSON object")
    return payload


@cache
def load_multimodal_environmental_evidence_fixtures(
    path: Path = MULTIMODAL_ENVIRONMENTAL_EVIDENCE_FIXTURES,
) -> MultimodalEnvironmentalEvidenceFixtureSet:
    """Load and validate the multimodal environmental evidence fixtures."""

    try:
        return MultimodalEnvironmentalEvidenceFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise MultimodalEnvironmentalEvidenceError(
            f"invalid multimodal environmental evidence fixtures at {path}: {exc}"
        ) from exc


def _epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).timestamp()


__all__ = [
    "FAIL_CLOSED_POLICY",
    "MULTIMODAL_ENVIRONMENTAL_EVIDENCE_FIXTURES",
    "MULTIMODAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS",
    "REQUIRED_FIXTURE_CASES",
    "REQUIRED_SOURCE_CLASSES",
    "CameraRole",
    "ClaimAuthorityCeiling",
    "ClaimShape",
    "ClaimSupportStatus",
    "FreshnessState",
    "IrTrainingState",
    "MultimodalClaimSupportDecision",
    "MultimodalClaimSupportFixture",
    "MultimodalClaimSupportRequest",
    "MultimodalEnvironmentalEvidenceEnvelope",
    "MultimodalEnvironmentalEvidenceError",
    "MultimodalEnvironmentalEvidenceFixtureSet",
    "ObservationPolarity",
    "PrivacyState",
    "RenderedClaimMode",
    "RightsState",
    "SourceClass",
    "SourceFamily",
    "SourcePayloadState",
    "WitnessKind",
    "evaluate_multimodal_claim_support",
    "load_multimodal_environmental_evidence_fixtures",
]
