"""Temporal/perceptual health projection for World Capability Surface rows.

This adapter is the WCS-facing fallback for temporal grounding and
PerceptualField evidence. It does not resolve temporal deictics and it does not
wire runtime consumers; it turns existing temporal/perceptual contract rows into
bounded ``WorldSurfaceHealthRecord`` rows that public/live/action gates can
inspect before making claims.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

log = logging.getLogger(__name__)

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.perceptual_field_grounding_registry import default_registry
from shared.temporal_band_evidence import (
    REQUIRED_TEMPORAL_BANDS,
    load_temporal_band_evidence_fixtures,
)
from shared.world_surface_health import (
    REQUIRED_CLAIM_BLOCKER_CASES,
    AuthorityCeiling,
    Claimability,
    EnvelopeStatus,
    Fallback,
    FixtureCase,
    Freshness,
    FreshnessState,
    HealthDimension,
    HealthDimensionId,
    HealthDimensionState,
    HealthStatus,
    HealthSummary,
    KillSwitchState,
    KillSwitchStatus,
    PrivacyState,
    PublicPrivatePosture,
    RightsState,
    SurfaceFamily,
    WitnessPolicy,
    WorldSurfaceHealthEnvelope,
    WorldSurfaceHealthRecord,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPORAL_PERCEPTUAL_HEALTH_FIXTURES = (
    REPO_ROOT / "config" / "world-surface-temporal-perceptual-health-fixtures.json"
)

REQUIRED_OBSERVATION_CATEGORIES = frozenset(
    {
        "temporal_band",
        "perception_state",
        "perceptual_field",
        "stimmung",
        "autonomous_narration_context",
        "impingement_evidence",
    }
)

TEMPORAL_FALSE_GROUNDING_METRIC = "hapax_wcs_temporal_false_grounding_risk_total{cause}"

FAIL_CLOSED_POLICY = {
    "stale_temporal_band_allows_current_claim": False,
    "missing_temporal_band_allows_claim": False,
    "unknown_temporal_band_allows_claim": False,
    "unknown_perception_state_allows_public_live": False,
    "inferred_perceptual_data_satisfies_witness": False,
    "spanless_perceptual_data_satisfies_grounded_claim": False,
    "protention_satisfies_current_claim": False,
    "protention_as_fact_satisfies_current_claim": False,
    "stale_temporal_xml_allows_current_claim": False,
    "fresh_temporal_xml_without_evidence_refs_allows_claim": False,
    "stale_perceptual_field_allows_current_claim": False,
    "empty_real_provenance_satisfies_grounded_claim": False,
    "synthetic_only_provenance_satisfies_witness": False,
    "contradictory_epochs_allow_current_claim": False,
    "autonomous_narration_without_wcs_health_allowed": False,
    "impingement_without_witness_satisfies_claim": False,
}


class TemporalPerceptualHealthError(ValueError):
    """Raised when temporal/perceptual health fixtures cannot project safely."""


class ObservationCategory(StrEnum):
    TEMPORAL_BAND = "temporal_band"
    PERCEPTION_STATE = "perception_state"
    PERCEPTUAL_FIELD = "perceptual_field"
    STIMMUNG = "stimmung"
    AUTONOMOUS_NARRATION_CONTEXT = "autonomous_narration_context"
    IMPINGEMENT_EVIDENCE = "impingement_evidence"


class TemporalBand(StrEnum):
    RETENTION = "retention"
    IMPRESSION = "impression"
    PROTENTION = "protention"
    SURPRISE = "surprise"
    NONCLAIMABLE_DIAGNOSTIC = "nonclaimable_diagnostic"


class FalseGroundingRiskCause(StrEnum):
    STALE_TEMPORAL_BAND = "stale_temporal_band"
    MISSING_TEMPORAL_BAND = "missing_temporal_band"
    UNKNOWN_TEMPORAL_BAND = "unknown_temporal_band"
    UNKNOWN_PERCEPTION_STATE = "unknown_perception_state"
    INFERRED_PERCEPTUAL_DATA = "inferred_perceptual_data"
    SPANLESS_PERCEPTUAL_DATA = "spanless_perceptual_data"
    PROTENTION_AS_CURRENT = "protention_as_current"
    PROTENTION_AS_FACT = "protention_as_fact"
    SURPRISE_AS_CURRENT = "surprise_as_current"
    STALE_TEMPORAL_XML = "stale_temporal_xml"
    FRESH_TEMPORAL_XML_WITHOUT_EVIDENCE_REFS = "fresh_temporal_xml_without_evidence_refs"
    STALE_PERCEPTUAL_FIELD = "stale_perceptual_field"
    EMPTY_REAL_PROVENANCE = "empty_real_provenance"
    SYNTHETIC_ONLY_PROVENANCE = "synthetic_only_provenance"
    CONTRADICTORY_PERCEPTION_TEMPORAL_EPOCHS = "contradictory_perception_temporal_epochs"
    STALE_STIMMUNG = "stale_stimmung"
    MISSING_GROUNDING_KEY = "missing_grounding_key"
    AUTONOMOUS_NARRATION_UNGATED = "autonomous_narration_ungated"
    IMPINGEMENT_WITHOUT_WITNESS = "impingement_without_witness"


class TemporalPerceptualHealthRow(BaseModel):
    """One temporal/perceptual observation row before WCS projection."""

    model_config = ConfigDict(extra="forbid")

    row_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)+$")
    display_name: str = Field(min_length=1)
    category: ObservationCategory
    temporal_band: TemporalBand
    status: HealthStatus
    freshness: Freshness
    confidence: float = Field(ge=0.0, le=1.0)
    authority_ceiling: AuthorityCeiling
    privacy_state: PrivacyState
    rights_state: RightsState
    public_private_posture: PublicPrivatePosture
    source_refs: list[str] = Field(min_length=1)
    producer_refs: list[str] = Field(min_length=1)
    consumer_refs: list[str] = Field(min_length=1)
    route_refs: list[str] = Field(min_length=1)
    substrate_refs: list[str] = Field(min_length=1)
    capability_refs: list[str] = Field(min_length=1)
    evidence_envelope_refs: list[str] = Field(min_length=1)
    witness_refs: list[str] = Field(default_factory=list)
    span_refs: list[str] = Field(default_factory=list)
    grounding_gate_refs: list[str] = Field(default_factory=list)
    public_event_refs: list[str] = Field(default_factory=list)
    grounding_key_paths: list[str] = Field(default_factory=list)
    false_grounding_risk_causes: list[FalseGroundingRiskCause] = Field(default_factory=list)
    blocker_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    fallback: Fallback
    kill_switch_state: KillSwitchState
    owner: str
    next_probe_due_at: str
    witness_policy: WitnessPolicy
    fixture_case: FixtureCase

    @model_validator(mode="after")
    def _validate_temporal_perceptual_row(self) -> Self:
        if self.status is not HealthStatus.HEALTHY and not self.blocker_reason:
            raise ValueError(f"{self.row_id} non-healthy row needs blocker_reason")
        if self.status is HealthStatus.STALE and self.freshness.state is not FreshnessState.STALE:
            raise ValueError(f"{self.row_id} stale status requires stale freshness")
        if (
            self.status is HealthStatus.MISSING
            and self.freshness.state is not FreshnessState.MISSING
        ):
            raise ValueError(f"{self.row_id} missing status requires missing freshness")
        if (
            self.status is HealthStatus.UNKNOWN
            and self.freshness.state is not FreshnessState.UNKNOWN
        ):
            raise ValueError(f"{self.row_id} unknown status requires unknown freshness")
        if self.false_grounding_risk_causes and not self.blocker_reason:
            raise ValueError(f"{self.row_id} false-grounding risk needs blocker_reason")
        if (
            self.category is ObservationCategory.TEMPORAL_BAND
            and self.temporal_band is TemporalBand.NONCLAIMABLE_DIAGNOSTIC
        ):
            raise ValueError(f"{self.row_id} temporal-band rows must name a canonical band")
        if self.temporal_band is TemporalBand.PROTENTION and self.status is HealthStatus.HEALTHY:
            raise ValueError(f"{self.row_id} protention cannot be healthy current-world health")
        return self

    def to_world_surface_health_record(self) -> WorldSurfaceHealthRecord:
        """Project this observation row into a bounded WCS health record."""

        blocking_reasons = []
        if self.blocker_reason:
            blocking_reasons.append(self.blocker_reason)
        blocking_reasons.extend(
            f"false_grounding_risk:{cause.value}" for cause in self.false_grounding_risk_causes
        )
        capability_refs = [
            *self.capability_refs,
            f"temporal_band:{self.temporal_band.value}",
            f"observation_category:{self.category.value}",
        ]
        if self.grounding_key_paths:
            capability_refs.extend(f"grounding_key:{path}" for path in self.grounding_key_paths)

        return WorldSurfaceHealthRecord(
            surface_id=f"{self.row_id}.health",
            surface_family=SurfaceFamily.PERCEPTION_OBSERVATION,
            checked_at=self.freshness.checked_at,
            status=self.status,
            health_dimensions=self._health_dimensions(),
            source_refs=self.source_refs,
            producer_refs=self.producer_refs,
            consumer_refs=self.consumer_refs,
            route_refs=self.route_refs,
            substrate_refs=self.substrate_refs,
            capability_refs=capability_refs,
            evidence_envelope_refs=self.evidence_envelope_refs,
            outcome_envelope_refs=[],
            witness_refs=self.witness_refs,
            grounding_gate_refs=self.grounding_gate_refs,
            public_event_refs=self.public_event_refs,
            freshness=self.freshness,
            confidence=self.confidence,
            authority_ceiling=self.authority_ceiling,
            privacy_state=self.privacy_state,
            rights_state=self.rights_state,
            public_private_posture=self.public_private_posture,
            public_claim_allowed=False,
            private_only=self._private_only(),
            dry_run_allowed=self.public_private_posture is PublicPrivatePosture.DRY_RUN,
            monetization_allowed=False,
            blocking_reasons=list(dict.fromkeys(blocking_reasons)),
            warnings=[
                *self.warnings,
                "temporal_perceptual_health_does_not_grant_public_claim_authority",
            ],
            fallback=self.fallback,
            kill_switch_state=self.kill_switch_state,
            owner=self.owner,
            next_probe_due_at=self.next_probe_due_at,
            claimable_health=False,
            claimability=Claimability(
                public_live=False,
                action=False,
                grounded=False,
                monetization=False,
            ),
            witness_policy=self.witness_policy,
            fixture_case=self.fixture_case,
        )

    def _health_dimensions(self) -> list[HealthDimension]:
        return [
            self._source_freshness_dimension(),
            self._dimension(
                HealthDimensionId.PRODUCER_EXISTS,
                self._producer_state(),
                True,
                self.producer_refs,
                "Temporal/perceptual producer is named and separately health-checked.",
            ),
            self._dimension(
                HealthDimensionId.CONSUMER_EXISTS,
                HealthDimensionState.PASS,
                True,
                self.consumer_refs,
                "Consumers are explicit; presence does not grant claim authority.",
            ),
            self._dimension(
                HealthDimensionId.ROUTE_BINDING,
                self._route_state(),
                True,
                self.route_refs,
                "Route binding names the observed temporal/perceptual source path.",
            ),
            self._dimension(
                HealthDimensionId.EXECUTION_WITNESS,
                self._execution_witness_state(),
                True,
                self.evidence_envelope_refs,
                "Evidence envelope presence is distinct from world witness sufficiency.",
            ),
            self._dimension(
                HealthDimensionId.WORLD_WITNESS,
                self._world_witness_state(),
                True,
                [*self.witness_refs, *self.span_refs],
                "World witness requires explicit witness refs and span refs.",
            ),
            self._dimension(
                HealthDimensionId.RENDERABILITY,
                HealthDimensionState.NOT_APPLICABLE,
                False,
                [],
                "Temporal/perceptual health does not assert renderability.",
            ),
            self._dimension(
                HealthDimensionId.NO_LEAK,
                self._no_leak_state(),
                True,
                [f"privacy:{self.row_id}:{self.privacy_state.value}"],
                "Privacy posture is explicit before any public projection.",
            ),
            self._dimension(
                HealthDimensionId.EGRESS_PUBLIC,
                HealthDimensionState.MISSING,
                True,
                [],
                "Temporal/perceptual health cannot prove public egress.",
            ),
            self._dimension(
                HealthDimensionId.PUBLIC_EVENT_POLICY,
                HealthDimensionState.MISSING,
                True,
                [],
                "Temporal/perceptual health cannot attach public-event policy.",
            ),
            self._dimension(
                HealthDimensionId.RIGHTS_PROVENANCE,
                self._rights_state_dimension(),
                True,
                [f"rights:{self.row_id}:{self.rights_state.value}"],
                "Rights posture is explicit and bounded to this row.",
            ),
            self._dimension(
                HealthDimensionId.PRIVACY_CONSENT,
                self._privacy_state_dimension(),
                True,
                [f"privacy:{self.row_id}:{self.privacy_state.value}"],
                "Privacy/consent posture is explicit and cannot be inferred from data.",
            ),
            self._dimension(
                HealthDimensionId.GROUNDING_GATE,
                self._grounding_gate_state(),
                True,
                self.grounding_gate_refs,
                "Grounding gate refs are required before public/live/current claims.",
            ),
            self._dimension(
                HealthDimensionId.CLAIM_AUTHORITY,
                self._claim_authority_state(),
                True,
                [f"authority:{self.row_id}:{self.authority_ceiling.value}"],
                "Authority ceiling is explicit and never upgraded by this adapter.",
            ),
            self._dimension(
                HealthDimensionId.MONETIZATION_READINESS,
                HealthDimensionState.NOT_APPLICABLE,
                False,
                [],
                "Temporal/perceptual health carries no monetization permission.",
            ),
            self._dimension(
                HealthDimensionId.FALLBACK_KNOWN,
                HealthDimensionState.PASS,
                True,
                [f"fallback:{self.row_id}:{self.fallback.reason_code}"],
                "Fail-closed fallback is explicit.",
            ),
            self._dimension(
                HealthDimensionId.KILL_SWITCH,
                self._kill_switch_state(),
                True,
                self.kill_switch_state.evidence_refs,
                "Kill-switch state is explicit.",
            ),
        ]

    @staticmethod
    def _dimension(
        dimension: HealthDimensionId,
        state: HealthDimensionState,
        required_for_claimable: bool,
        evidence_refs: list[str],
        note: str,
    ) -> HealthDimension:
        return HealthDimension(
            dimension=dimension,
            state=state,
            required_for_claimable=required_for_claimable,
            evidence_refs=evidence_refs,
            note=note,
        )

    def _source_freshness_dimension(self) -> HealthDimension:
        state_by_freshness = {
            FreshnessState.FRESH: HealthDimensionState.PASS,
            FreshnessState.STALE: HealthDimensionState.STALE,
            FreshnessState.MISSING: HealthDimensionState.MISSING,
            FreshnessState.UNKNOWN: HealthDimensionState.UNKNOWN,
            FreshnessState.NOT_APPLICABLE: HealthDimensionState.NOT_APPLICABLE,
        }
        evidence_refs = [self.freshness.source_ref] if self.freshness.source_ref else []
        return self._dimension(
            HealthDimensionId.SOURCE_FRESHNESS,
            state_by_freshness[self.freshness.state],
            True,
            evidence_refs,
            "Freshness is bounded by the temporal/perceptual source TTL.",
        )

    def _producer_state(self) -> HealthDimensionState:
        if self.status is HealthStatus.MISSING:
            return HealthDimensionState.MISSING
        if self.status is HealthStatus.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        if self.status in {HealthStatus.BLOCKED, HealthStatus.UNSAFE}:
            return HealthDimensionState.BLOCKED
        return HealthDimensionState.PASS

    def _route_state(self) -> HealthDimensionState:
        if self.freshness.state is FreshnessState.MISSING:
            return HealthDimensionState.MISSING
        if self.freshness.state is FreshnessState.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        if self.freshness.state is FreshnessState.STALE:
            return HealthDimensionState.STALE
        return HealthDimensionState.PASS

    def _execution_witness_state(self) -> HealthDimensionState:
        if self.evidence_envelope_refs:
            return HealthDimensionState.PASS
        return HealthDimensionState.MISSING

    def _world_witness_state(self) -> HealthDimensionState:
        if self.witness_policy is WitnessPolicy.INFERRED:
            return HealthDimensionState.BLOCKED
        if self.witness_policy is WitnessPolicy.ABSENT:
            return HealthDimensionState.MISSING
        if self.freshness.state is FreshnessState.STALE:
            return HealthDimensionState.STALE
        if self.witness_refs and self.span_refs:
            return HealthDimensionState.PASS
        if self.span_refs:
            return HealthDimensionState.MISSING
        return HealthDimensionState.MISSING

    def _no_leak_state(self) -> HealthDimensionState:
        if self.privacy_state is PrivacyState.BLOCKED:
            return HealthDimensionState.FAIL
        if self.privacy_state is PrivacyState.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        return HealthDimensionState.PASS

    def _rights_state_dimension(self) -> HealthDimensionState:
        if self.rights_state in {
            RightsState.PUBLIC_CLEAR,
            RightsState.PRIVATE_ONLY,
            RightsState.AGGREGATE_ONLY,
            RightsState.NOT_APPLICABLE,
        }:
            return HealthDimensionState.PASS
        if self.rights_state is RightsState.MISSING:
            return HealthDimensionState.MISSING
        if self.rights_state is RightsState.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        return HealthDimensionState.FAIL

    def _privacy_state_dimension(self) -> HealthDimensionState:
        if self.privacy_state in {
            PrivacyState.PUBLIC_SAFE,
            PrivacyState.PRIVATE_ONLY,
            PrivacyState.DRY_RUN,
            PrivacyState.ARCHIVE_ONLY,
        }:
            return HealthDimensionState.PASS
        if self.privacy_state is PrivacyState.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        return HealthDimensionState.FAIL

    def _grounding_gate_state(self) -> HealthDimensionState:
        if self.false_grounding_risk_causes:
            return HealthDimensionState.BLOCKED
        if self.grounding_gate_refs:
            return HealthDimensionState.PASS
        return HealthDimensionState.MISSING

    def _claim_authority_state(self) -> HealthDimensionState:
        if self.false_grounding_risk_causes:
            return HealthDimensionState.BLOCKED
        if self.authority_ceiling is AuthorityCeiling.NO_CLAIM:
            return HealthDimensionState.FAIL
        if self.authority_ceiling in {
            AuthorityCeiling.EVIDENCE_BOUND,
            AuthorityCeiling.POSTERIOR_BOUND,
            AuthorityCeiling.PUBLIC_GATE_REQUIRED,
        }:
            return HealthDimensionState.PASS
        return HealthDimensionState.BLOCKED

    def _kill_switch_state(self) -> HealthDimensionState:
        if self.kill_switch_state.state is KillSwitchStatus.CLEAR:
            return HealthDimensionState.PASS
        if self.kill_switch_state.state is KillSwitchStatus.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        return HealthDimensionState.FAIL

    def _private_only(self) -> bool:
        return (
            self.privacy_state is PrivacyState.PRIVATE_ONLY
            or self.rights_state is RightsState.PRIVATE_ONLY
            or self.public_private_posture is PublicPrivatePosture.PRIVATE_ONLY
        )


class TemporalPerceptualHealthFixtureSet(BaseModel):
    """Fixture set for temporal/perceptual WCS health rows."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: Literal["schemas/world-surface-temporal-perceptual-health.schema.json"]
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    required_observation_categories: list[ObservationCategory] = Field(min_length=1)
    required_temporal_bands: list[TemporalBand] = Field(min_length=4)
    rows: list[TemporalPerceptualHealthRow] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]
    metrics_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_fixture_contract(self) -> Self:
        row_ids = [row.row_id for row in self.rows]
        duplicate_row_ids = sorted({row_id for row_id in row_ids if row_ids.count(row_id) > 1})
        if duplicate_row_ids:
            raise ValueError("duplicate temporal/perceptual rows: " + ", ".join(duplicate_row_ids))

        categories = {category.value for category in self.required_observation_categories}
        missing_categories = REQUIRED_OBSERVATION_CATEGORIES - categories
        if missing_categories:
            raise ValueError(
                "missing temporal/perceptual categories: " + ", ".join(sorted(missing_categories))
            )

        row_categories = {row.category.value for row in self.rows}
        missing_row_categories = REQUIRED_OBSERVATION_CATEGORIES - row_categories
        if missing_row_categories:
            raise ValueError(
                "temporal/perceptual rows do not cover categories: "
                + ", ".join(sorted(missing_row_categories))
            )

        temporal_band_values = {band.value for band in self.required_temporal_bands}
        if REQUIRED_TEMPORAL_BANDS - temporal_band_values:
            raise ValueError("required_temporal_bands must cover canonical temporal bands")
        row_temporal_bands = {
            row.temporal_band.value
            for row in self.rows
            if row.category is ObservationCategory.TEMPORAL_BAND
        }
        missing_row_bands = REQUIRED_TEMPORAL_BANDS - row_temporal_bands
        if missing_row_bands:
            raise ValueError("temporal rows do not cover bands: " + ", ".join(missing_row_bands))

        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("temporal/perceptual fail_closed_policy must pin gates false")
        if f"metrics:{TEMPORAL_FALSE_GROUNDING_METRIC}" not in self.metrics_refs:
            raise ValueError("metrics_refs must include temporal false-grounding risk metric")

        self._validate_temporal_evidence_refs()
        self._validate_grounding_key_refs()
        return self

    def _validate_temporal_evidence_refs(self) -> None:
        temporal_envelopes = load_temporal_band_evidence_fixtures().envelopes_by_id()
        for row in self.rows:
            for ref in row.evidence_envelope_refs:
                if ref.startswith("temporal-evidence:") and ref not in temporal_envelopes:
                    raise ValueError(f"{row.row_id} references missing temporal evidence {ref}")

    def _validate_grounding_key_refs(self) -> None:
        registry_rows = default_registry().by_key_path()
        for row in self.rows:
            for key_path in row.grounding_key_paths:
                if key_path not in registry_rows:
                    raise ValueError(f"{row.row_id} references missing grounding key {key_path}")

    def to_world_surface_health_records(self) -> list[WorldSurfaceHealthRecord]:
        """Project every fixture row into WCS health records."""

        return [row.to_world_surface_health_record() for row in self.rows]


def temporal_false_grounding_risk_counts(
    rows: list[TemporalPerceptualHealthRow],
) -> dict[str, int]:
    """Return temporal/perceptual false-grounding risk counts by cause."""

    counts: Counter[str] = Counter(
        cause.value for row in rows for cause in row.false_grounding_risk_causes
    )
    return dict(sorted(counts.items()))


def project_temporal_false_grounding_risk_metrics(
    path: Path = TEMPORAL_PERCEPTUAL_HEALTH_FIXTURES,
) -> dict[str, int]:
    """Load fixtures and return the metric payload keyed by false-grounding cause."""

    return temporal_false_grounding_risk_counts(load_temporal_perceptual_health_fixtures(path).rows)


def build_temporal_perceptual_health_envelope(
    fixture_set: TemporalPerceptualHealthFixtureSet,
) -> WorldSurfaceHealthEnvelope:
    """Build a WCS health envelope from temporal/perceptual fixture rows."""

    records = fixture_set.to_world_surface_health_records()
    statuses = [record.status for record in records]
    families = [record.surface_family for record in records]
    return WorldSurfaceHealthEnvelope(
        envelope_id=f"world-surface-health:temporal-perceptual:{fixture_set.declared_at}",
        checked_at=fixture_set.declared_at,
        overall_status=_overall_status(statuses),
        records=records,
        summary=HealthSummary(
            total_records=len(records),
            by_status={
                status.value: statuses.count(status)
                for status in sorted(set(statuses), key=lambda value: value.value)
            },
            by_surface_family={
                family.value: families.count(family)
                for family in sorted(set(families), key=lambda value: value.value)
            },
            claimable_health_count=0,
            public_claim_allowed_count=0,
        ),
        public_live_allowed=False,
        public_archive_allowed=False,
        public_monetization_allowed=False,
        blocked_surface_count=statuses.count(HealthStatus.BLOCKED),
        unsafe_surface_count=statuses.count(HealthStatus.UNSAFE),
        stale_surface_count=statuses.count(HealthStatus.STALE),
        unknown_surface_count=statuses.count(HealthStatus.UNKNOWN),
        false_grounding_risk_count=_wcs_false_grounding_risk_count(records),
        next_required_actions=_next_required_actions(records),
        metrics_refs=fixture_set.metrics_refs,
    )


def _overall_status(statuses: list[HealthStatus]) -> EnvelopeStatus:
    if HealthStatus.UNSAFE in statuses:
        return EnvelopeStatus.UNSAFE
    if any(status in statuses for status in {HealthStatus.BLOCKED, HealthStatus.MISSING}):
        return EnvelopeStatus.BLOCKED
    if any(status in statuses for status in {HealthStatus.UNKNOWN, HealthStatus.CANDIDATE}):
        return EnvelopeStatus.UNKNOWN
    if any(
        status in statuses
        for status in {
            HealthStatus.DEGRADED,
            HealthStatus.STALE,
            HealthStatus.PRIVATE_ONLY,
            HealthStatus.DRY_RUN,
            HealthStatus.QUIET_OFF_AIR,
        }
    ):
        return EnvelopeStatus.DEGRADED
    return EnvelopeStatus.HEALTHY


def _wcs_false_grounding_risk_count(records: list[WorldSurfaceHealthRecord]) -> int:
    return sum(
        record.fixture_case.value in REQUIRED_CLAIM_BLOCKER_CASES
        or record.witness_policy
        in {
            WitnessPolicy.INFERRED,
            WitnessPolicy.SELECTED_ONLY,
            WitnessPolicy.COMMANDED_ONLY,
        }
        for record in records
    )


def _next_required_actions(records: list[WorldSurfaceHealthRecord]) -> list[str]:
    reasons = [
        reason
        for record in records
        for reason in record.blocking_reasons
        if reason.startswith("false_grounding_risk:") or not record.satisfies_claimable_health()
    ]
    return list(dict.fromkeys(reasons[:8])) or [
        "Collect fresh temporal/perceptual witnesses before public/live/current claims."
    ]


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TemporalPerceptualHealthError(f"{path} did not contain a JSON object")
    return payload


def load_temporal_perceptual_health_fixtures(
    path: Path = TEMPORAL_PERCEPTUAL_HEALTH_FIXTURES,
) -> TemporalPerceptualHealthFixtureSet:
    """Load temporal/perceptual WCS health fixtures, failing closed on malformed data."""

    try:
        return TemporalPerceptualHealthFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise TemporalPerceptualHealthError(
            f"invalid temporal/perceptual health fixtures at {path}: {exc}"
        ) from exc


def project_temporal_perceptual_health_records(
    path: Path = TEMPORAL_PERCEPTUAL_HEALTH_FIXTURES,
) -> list[WorldSurfaceHealthRecord]:
    """Load fixtures and project them into WCS health rows."""

    return load_temporal_perceptual_health_fixtures(path).to_world_surface_health_records()


def project_temporal_perceptual_health_envelope(
    path: Path = TEMPORAL_PERCEPTUAL_HEALTH_FIXTURES,
) -> WorldSurfaceHealthEnvelope:
    """Load fixtures and project them into a WCS health envelope."""

    return build_temporal_perceptual_health_envelope(load_temporal_perceptual_health_fixtures(path))


def _query_camera_salience_for_wcs_health(envelope_id: str) -> dict[str, Any] | None:
    """Query the broker for the WCS-health envelope context.

    Mirrors the inline pattern used by ``director_loop`` and
    ``affordance_pipeline``. Fails closed (returns ``None``) on any
    broker error so the health envelope never depends on a salience
    lookup succeeding.
    """
    try:
        from shared.camera_salience_singleton import broker as _camera_broker

        bundle = _camera_broker().query(
            consumer="wcs_health",
            decision_context=f"wcs_health_envelope:{envelope_id}",
            candidate_action="project_temporal_perceptual_health",
        )
        if bundle is None:
            return None
        return bundle.to_wcs_projection_payload()
    except Exception:
        log.debug("camera salience wcs_health query failed", exc_info=True)
        return None


def project_temporal_perceptual_health_envelope_with_camera_salience(
    path: Path = TEMPORAL_PERCEPTUAL_HEALTH_FIXTURES,
) -> dict[str, Any]:
    """Project the WCS health envelope alongside the camera-salience snapshot.

    Returns a dict with two keys:

      * ``envelope`` — the standard ``WorldSurfaceHealthEnvelope``.
      * ``camera_salience`` — the broker's WCS projection (``None`` when
        unavailable).

    The salience projection is *used* by attaching it as the second key
    of the returned health-row payload; downstream consumers consult it
    when constructing the next-required-actions list or when annotating
    a health row with the apertures that backed (or failed to back) the
    fixture set's claims.
    """
    envelope = project_temporal_perceptual_health_envelope(path)
    salience = _query_camera_salience_for_wcs_health(envelope.envelope_id)
    return {"envelope": envelope, "camera_salience": salience}


__all__ = [
    "FAIL_CLOSED_POLICY",
    "REQUIRED_OBSERVATION_CATEGORIES",
    "TEMPORAL_FALSE_GROUNDING_METRIC",
    "TEMPORAL_PERCEPTUAL_HEALTH_FIXTURES",
    "FalseGroundingRiskCause",
    "ObservationCategory",
    "TemporalBand",
    "TemporalPerceptualHealthError",
    "TemporalPerceptualHealthFixtureSet",
    "TemporalPerceptualHealthRow",
    "build_temporal_perceptual_health_envelope",
    "load_temporal_perceptual_health_fixtures",
    "project_temporal_false_grounding_risk_metrics",
    "project_temporal_perceptual_health_envelope",
    "project_temporal_perceptual_health_envelope_with_camera_salience",
    "project_temporal_perceptual_health_records",
    "temporal_false_grounding_risk_counts",
]
