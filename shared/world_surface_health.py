"""Typed World Capability Surface health envelope fixtures.

The fixture envelope is a contract surface, not a runtime witness. It pins the
health vocabulary and fail-closed claimability rules that downstream adapters
must use before they can describe a world surface as live, grounded, public, or
monetizable.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
WORLD_SURFACE_HEALTH_FIXTURES = REPO_ROOT / "config" / "world-surface-health-fixtures.json"

REQUIRED_HEALTH_STATUSES = frozenset(
    {
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
    }
)

REQUIRED_SURFACE_FAMILIES = frozenset(
    {
        "audio",
        "visual",
        "control",
        "provider_tool",
        "public_event",
        "archive_file",
        "refusal_correction",
    }
)

REQUIRED_CLAIM_BLOCKER_CASES = frozenset(
    {
        "candidate",
        "unknown",
        "stale",
        "missing",
        "inferred",
        "selected_only",
        "commanded_only",
        "wrong_route",
        "leak",
        "unsupported_claim",
        "false_monetization",
    }
)

REQUIRED_CLAIMABLE_DIMENSIONS = frozenset(
    {
        "source_freshness",
        "producer_exists",
        "consumer_exists",
        "route_binding",
        "execution_witness",
        "world_witness",
        "no_leak",
        "egress_public",
        "public_event_policy",
        "rights_provenance",
        "privacy_consent",
        "grounding_gate",
        "claim_authority",
        "fallback_known",
        "kill_switch",
    }
)

HEALTH_RECORD_REQUIRED_FIELDS = (
    "schema_version",
    "surface_id",
    "surface_family",
    "checked_at",
    "status",
    "health_dimensions",
    "source_refs",
    "producer_refs",
    "consumer_refs",
    "route_refs",
    "substrate_refs",
    "capability_refs",
    "evidence_envelope_refs",
    "outcome_envelope_refs",
    "witness_refs",
    "grounding_gate_refs",
    "public_event_refs",
    "freshness",
    "confidence",
    "authority_ceiling",
    "privacy_state",
    "rights_state",
    "public_private_posture",
    "public_claim_allowed",
    "private_only",
    "dry_run_allowed",
    "monetization_allowed",
    "blocking_reasons",
    "warnings",
    "fallback",
    "kill_switch_state",
    "owner",
    "next_probe_due_at",
    "claimable_health",
    "claimability",
    "witness_policy",
    "fixture_case",
)

HEALTH_ENVELOPE_REQUIRED_FIELDS = (
    "schema_version",
    "envelope_id",
    "checked_at",
    "overall_status",
    "records",
    "summary",
    "public_live_allowed",
    "public_archive_allowed",
    "public_monetization_allowed",
    "blocked_surface_count",
    "unsafe_surface_count",
    "stale_surface_count",
    "unknown_surface_count",
    "false_grounding_risk_count",
    "next_required_actions",
    "metrics_refs",
)


class WorldSurfaceHealthError(ValueError):
    """Raised when WCS health fixtures or envelopes cannot be loaded safely."""


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    UNSAFE = "unsafe"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"
    PRIVATE_ONLY = "private_only"
    DRY_RUN = "dry_run"
    QUIET_OFF_AIR = "quiet_off_air"
    CANDIDATE = "candidate"


class EnvelopeStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    UNSAFE = "unsafe"
    UNKNOWN = "unknown"


class SurfaceFamily(StrEnum):
    AUDIO = "audio"
    VISUAL = "visual"
    CONTROL = "control"
    PROVIDER_TOOL = "provider_tool"
    PUBLIC_EVENT = "public_event"
    ARCHIVE_FILE = "archive_file"
    REFUSAL_CORRECTION = "refusal_correction"
    PERCEPTION_OBSERVATION = "perception_observation"


class HealthDimensionId(StrEnum):
    SOURCE_FRESHNESS = "source_freshness"
    PRODUCER_EXISTS = "producer_exists"
    CONSUMER_EXISTS = "consumer_exists"
    ROUTE_BINDING = "route_binding"
    EXECUTION_WITNESS = "execution_witness"
    WORLD_WITNESS = "world_witness"
    RENDERABILITY = "renderability"
    NO_LEAK = "no_leak"
    EGRESS_PUBLIC = "egress_public"
    PUBLIC_EVENT_POLICY = "public_event_policy"
    RIGHTS_PROVENANCE = "rights_provenance"
    PRIVACY_CONSENT = "privacy_consent"
    GROUNDING_GATE = "grounding_gate"
    CLAIM_AUTHORITY = "claim_authority"
    MONETIZATION_READINESS = "monetization_readiness"
    FALLBACK_KNOWN = "fallback_known"
    KILL_SWITCH = "kill_switch"


class HealthDimensionState(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class AuthorityCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    INTERNAL_ONLY = "internal_only"
    SPECULATIVE = "speculative"
    EVIDENCE_BOUND = "evidence_bound"
    POSTERIOR_BOUND = "posterior_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class PrivacyState(StrEnum):
    PUBLIC_SAFE = "public_safe"
    PRIVATE_ONLY = "private_only"
    DRY_RUN = "dry_run"
    ARCHIVE_ONLY = "archive_only"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class RightsState(StrEnum):
    PUBLIC_CLEAR = "public_clear"
    PRIVATE_ONLY = "private_only"
    AGGREGATE_ONLY = "aggregate_only"
    BLOCKED = "blocked"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class PublicPrivatePosture(StrEnum):
    PUBLIC_LIVE = "public_live"
    PRIVATE_ONLY = "private_only"
    DRY_RUN = "dry_run"
    ARCHIVE_ONLY = "archive_only"
    DISABLED = "disabled"
    BLOCKED = "blocked"


class WitnessPolicy(StrEnum):
    WITNESSED = "witnessed"
    INFERRED = "inferred"
    SELECTED_ONLY = "selected_only"
    COMMANDED_ONLY = "commanded_only"
    FIXTURE_ONLY = "fixture_only"
    ABSENT = "absent"
    CANDIDATE = "candidate"


class FixtureCase(StrEnum):
    HEALTHY_WITNESSED = "healthy_witnessed"
    DEGRADED_WITNESSED = "degraded_witnessed"
    BLOCKED_WITH_REASON = "blocked_with_reason"
    UNSAFE_NO_LEAK = "unsafe_no_leak"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"
    PRIVATE_ONLY = "private_only"
    DRY_RUN = "dry_run"
    QUIET_OFF_AIR = "quiet_off_air"
    CANDIDATE = "candidate"
    INFERRED = "inferred"
    SELECTED_ONLY = "selected_only"
    COMMANDED_ONLY = "commanded_only"
    WRONG_ROUTE = "wrong_route"
    LEAK = "leak"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    FALSE_MONETIZATION = "false_monetization"


class FallbackMode(StrEnum):
    NONE = "none"
    HIDE = "hide"
    NO_OP_EXPLAIN = "no_op_explain"
    DRY_RUN_BADGE = "dry_run_badge"
    PRIVATE_ONLY = "private_only"
    ARCHIVE_ONLY = "archive_only"
    HOLD_LAST_SAFE = "hold_last_safe"
    SUPPRESS = "suppress"
    DEGRADED_STATUS = "degraded_status"
    OPERATOR_PROMPT = "operator_prompt"
    KILL_SWITCH = "kill_switch"
    BLOCK_PUBLIC_CLAIM = "block_public_claim"
    CORRECTION_REQUIRED = "correction_required"


class KillSwitchStatus(StrEnum):
    CLEAR = "clear"
    TRIGGERED = "triggered"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class HealthDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: HealthDimensionId
    state: HealthDimensionState
    required_for_claimable: bool
    evidence_refs: list[str] = Field(default_factory=list)
    note: str

    @model_validator(mode="after")
    def _passing_required_dimensions_need_evidence(self) -> Self:
        if (
            self.required_for_claimable
            and self.state is HealthDimensionState.PASS
            and not self.evidence_refs
        ):
            raise ValueError(
                f"{self.dimension.value} passes without evidence_refs; required dimensions "
                "must be evidenced"
            )
        return self


class Freshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: FreshnessState
    ttl_s: int | None = Field(default=None, ge=0)
    observed_age_s: int | None = Field(default=None, ge=0)
    source_ref: str | None = None
    checked_at: str

    @model_validator(mode="after")
    def _fresh_sources_need_age_and_ttl(self) -> Self:
        if self.state is FreshnessState.FRESH:
            if self.ttl_s is None or self.observed_age_s is None or self.source_ref is None:
                raise ValueError("fresh health requires ttl_s, observed_age_s, and source_ref")
            if self.observed_age_s > self.ttl_s:
                raise ValueError("fresh health observed_age_s cannot exceed ttl_s")
        return self


class Fallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: FallbackMode
    reason_code: str
    operator_visible_reason: str
    safe_state: str


class KillSwitchState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: KillSwitchStatus
    evidence_refs: list[str] = Field(default_factory=list)


class Claimability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_live: bool
    action: bool
    grounded: bool
    monetization: bool


class WorldSurfaceHealthRecord(BaseModel):
    """Runtime-shaped health record for one world capability surface."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    surface_id: str
    surface_family: SurfaceFamily
    checked_at: str
    status: HealthStatus
    health_dimensions: list[HealthDimension] = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    producer_refs: list[str] = Field(min_length=1)
    consumer_refs: list[str] = Field(min_length=1)
    route_refs: list[str] = Field(min_length=1)
    substrate_refs: list[str] = Field(min_length=1)
    capability_refs: list[str] = Field(min_length=1)
    evidence_envelope_refs: list[str] = Field(min_length=1)
    outcome_envelope_refs: list[str] = Field(default_factory=list)
    witness_refs: list[str] = Field(default_factory=list)
    grounding_gate_refs: list[str] = Field(default_factory=list)
    public_event_refs: list[str] = Field(default_factory=list)
    freshness: Freshness
    confidence: float = Field(ge=0.0, le=1.0)
    authority_ceiling: AuthorityCeiling
    privacy_state: PrivacyState
    rights_state: RightsState
    public_private_posture: PublicPrivatePosture
    public_claim_allowed: bool
    private_only: bool
    dry_run_allowed: bool
    monetization_allowed: bool
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    fallback: Fallback
    kill_switch_state: KillSwitchState
    owner: str
    next_probe_due_at: str
    claimable_health: bool
    claimability: Claimability
    witness_policy: WitnessPolicy
    fixture_case: FixtureCase

    @model_validator(mode="after")
    def _validate_fail_closed_claimability(self) -> Self:
        blockers = self.claimability_blockers()
        if self.claimable_health and blockers:
            raise ValueError(
                f"{self.surface_id} claimable_health is true but blockers remain: "
                + ", ".join(blockers)
            )
        if self.public_claim_allowed and not self.claimable_health:
            raise ValueError(f"{self.surface_id} public_claim_allowed requires claimable_health")
        if self.monetization_allowed and not self.public_claim_allowed:
            raise ValueError(
                f"{self.surface_id} monetization_allowed requires public_claim_allowed"
            )
        if self.claimability.public_live and not self.public_claim_allowed:
            raise ValueError(
                f"{self.surface_id} claimability.public_live requires public_claim_allowed"
            )
        if (self.claimability.action or self.claimability.grounded) and not self.claimable_health:
            raise ValueError(
                f"{self.surface_id} action/grounded claimability requires claimable_health"
            )
        if self.claimability.monetization and not self.monetization_allowed:
            raise ValueError(
                f"{self.surface_id} claimability.monetization requires monetization_allowed"
            )
        if self.status is HealthStatus.PRIVATE_ONLY and not self.private_only:
            raise ValueError(f"{self.surface_id} private_only status must set private_only")
        if self.status is HealthStatus.DRY_RUN and not self.dry_run_allowed:
            raise ValueError(f"{self.surface_id} dry_run status must set dry_run_allowed")
        if self.status is HealthStatus.STALE and self.freshness.state is not FreshnessState.STALE:
            raise ValueError(f"{self.surface_id} stale status requires stale freshness")
        if (
            self.status is HealthStatus.MISSING
            and self.freshness.state is not FreshnessState.MISSING
        ):
            raise ValueError(f"{self.surface_id} missing status requires missing freshness")
        if (
            self.status is HealthStatus.UNKNOWN
            and self.freshness.state is not FreshnessState.UNKNOWN
        ):
            raise ValueError(f"{self.surface_id} unknown status requires unknown freshness")
        if self.status is not HealthStatus.HEALTHY and not self.blocking_reasons:
            raise ValueError(f"{self.surface_id} non-healthy health must name blocking_reasons")
        return self

    def claimability_blockers(self) -> list[str]:
        """Return reasons this record cannot satisfy claimable public health."""

        blockers: list[str] = []
        if self.status is not HealthStatus.HEALTHY:
            blockers.append(f"status:{self.status.value}")
        if self.fixture_case.value in REQUIRED_CLAIM_BLOCKER_CASES:
            blockers.append(f"fixture_case:{self.fixture_case.value}")
        if self.witness_policy is not WitnessPolicy.WITNESSED:
            blockers.append(f"witness_policy:{self.witness_policy.value}")
        if self.freshness.state is not FreshnessState.FRESH:
            blockers.append(f"freshness:{self.freshness.state.value}")
        if self.public_private_posture is not PublicPrivatePosture.PUBLIC_LIVE:
            blockers.append(f"posture:{self.public_private_posture.value}")
        if self.privacy_state is not PrivacyState.PUBLIC_SAFE:
            blockers.append(f"privacy_state:{self.privacy_state.value}")
        if self.rights_state is not RightsState.PUBLIC_CLEAR:
            blockers.append(f"rights_state:{self.rights_state.value}")
        if self.authority_ceiling is not AuthorityCeiling.PUBLIC_GATE_REQUIRED:
            blockers.append(f"authority_ceiling:{self.authority_ceiling.value}")
        if self.blocking_reasons:
            blockers.append("blocking_reasons")
        if self.kill_switch_state.state is not KillSwitchStatus.CLEAR:
            blockers.append(f"kill_switch:{self.kill_switch_state.state.value}")
        if not self.witness_refs:
            blockers.append("witness_refs:missing")
        if not self.grounding_gate_refs:
            blockers.append("grounding_gate_refs:missing")
        if not self.public_event_refs:
            blockers.append("public_event_refs:missing")

        dimensions_by_id = {
            dimension.dimension.value: dimension for dimension in self.health_dimensions
        }
        for dimension_id in sorted(REQUIRED_CLAIMABLE_DIMENSIONS):
            dimension = dimensions_by_id.get(dimension_id)
            if dimension is None:
                blockers.append(f"dimension:{dimension_id}:missing")
            elif (
                dimension.required_for_claimable
                and dimension.state is not HealthDimensionState.PASS
            ):
                blockers.append(f"dimension:{dimension_id}:{dimension.state.value}")
        return blockers

    def satisfies_claimable_health(self) -> bool:
        """Return true only when every public/live/grounded claim gate passes."""

        return (
            self.claimable_health
            and self.public_claim_allowed
            and self.claimability.public_live
            and self.claimability.action
            and self.claimability.grounded
            and not self.claimability_blockers()
        )


class HealthSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_records: int = Field(ge=0)
    by_status: dict[str, int]
    by_surface_family: dict[str, int]
    claimable_health_count: int = Field(ge=0)
    public_claim_allowed_count: int = Field(ge=0)


class WorldSurfaceHealthEnvelope(BaseModel):
    """Envelope consumed by WCS health adapters and public egress gates."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    envelope_id: str
    checked_at: str
    overall_status: EnvelopeStatus
    records: list[WorldSurfaceHealthRecord] = Field(min_length=1)
    summary: HealthSummary
    public_live_allowed: bool
    public_archive_allowed: bool
    public_monetization_allowed: bool
    blocked_surface_count: int = Field(ge=0)
    unsafe_surface_count: int = Field(ge=0)
    stale_surface_count: int = Field(ge=0)
    unknown_surface_count: int = Field(ge=0)
    false_grounding_risk_count: int = Field(ge=0)
    next_required_actions: list[str] = Field(min_length=1)
    metrics_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_envelope_counts_and_public_gates(self) -> Self:
        statuses = [record.status for record in self.records]
        families = [record.surface_family for record in self.records]
        claimable_records = [
            record for record in self.records if record.satisfies_claimable_health()
        ]
        false_grounding_records = [
            record
            for record in self.records
            if record.fixture_case.value in REQUIRED_CLAIM_BLOCKER_CASES
            or record.witness_policy
            in {
                WitnessPolicy.INFERRED,
                WitnessPolicy.SELECTED_ONLY,
                WitnessPolicy.COMMANDED_ONLY,
            }
        ]

        expected_summary = HealthSummary(
            total_records=len(self.records),
            by_status={status.value: statuses.count(status) for status in sorted(set(statuses))},
            by_surface_family={
                family.value: families.count(family) for family in sorted(set(families))
            },
            claimable_health_count=len(claimable_records),
            public_claim_allowed_count=sum(record.public_claim_allowed for record in self.records),
        )
        if self.summary != expected_summary:
            raise ValueError("health envelope summary does not match records")
        if self.blocked_surface_count != statuses.count(HealthStatus.BLOCKED):
            raise ValueError("blocked_surface_count does not match records")
        if self.unsafe_surface_count != statuses.count(HealthStatus.UNSAFE):
            raise ValueError("unsafe_surface_count does not match records")
        if self.stale_surface_count != statuses.count(HealthStatus.STALE):
            raise ValueError("stale_surface_count does not match records")
        if self.unknown_surface_count != statuses.count(HealthStatus.UNKNOWN):
            raise ValueError("unknown_surface_count does not match records")
        if self.false_grounding_risk_count != len(false_grounding_records):
            raise ValueError("false_grounding_risk_count does not match records")
        if self.public_live_allowed and not claimable_records:
            raise ValueError("public_live_allowed requires at least one claimable health record")
        if self.public_monetization_allowed and not self.public_live_allowed:
            raise ValueError("public_monetization_allowed requires public_live_allowed")
        if self.overall_status is not self._derived_overall_status(statuses):
            raise ValueError("overall_status does not match record severities")
        return self

    @staticmethod
    def _derived_overall_status(statuses: list[HealthStatus]) -> EnvelopeStatus:
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

    def records_by_surface_id(self) -> dict[str, WorldSurfaceHealthRecord]:
        """Return envelope records keyed by surface id."""

        return {record.surface_id: record for record in self.records}


class HealthStatusFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: HealthStatus
    claimable_health_allowed: bool
    public_live_allowed_without_witness: Literal[False] = False
    meaning: str
    failure_reason: str


class WorldSurfaceHealthFixtureSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: Literal["schemas/world-surface-health-envelope.schema.json"]
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    health_statuses: list[HealthStatus] = Field(min_length=1)
    surface_families: list[SurfaceFamily] = Field(min_length=1)
    health_record_required_fields: list[str] = Field(min_length=1)
    health_envelope_required_fields: list[str] = Field(min_length=1)
    claim_blocker_cases: list[FixtureCase] = Field(min_length=1)
    status_fixtures: list[HealthStatusFixture] = Field(min_length=1)
    envelopes: list[WorldSurfaceHealthEnvelope] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_contract_coverage(self) -> Self:
        status_values = {status.value for status in self.health_statuses}
        missing_statuses = REQUIRED_HEALTH_STATUSES - status_values
        if missing_statuses:
            raise ValueError("missing WCS health statuses: " + ", ".join(sorted(missing_statuses)))

        fixture_statuses = {fixture.status.value for fixture in self.status_fixtures}
        missing_fixture_statuses = REQUIRED_HEALTH_STATUSES - fixture_statuses
        if missing_fixture_statuses:
            raise ValueError(
                "missing WCS health status fixtures: " + ", ".join(sorted(missing_fixture_statuses))
            )

        family_values = {family.value for family in self.surface_families}
        missing_families = REQUIRED_SURFACE_FAMILIES - family_values
        if missing_families:
            raise ValueError(
                "missing WCS health surface families: " + ", ".join(sorted(missing_families))
            )

        if set(self.health_record_required_fields) != set(HEALTH_RECORD_REQUIRED_FIELDS):
            raise ValueError("health_record_required_fields does not match typed contract")
        if set(self.health_envelope_required_fields) != set(HEALTH_ENVELOPE_REQUIRED_FIELDS):
            raise ValueError("health_envelope_required_fields does not match typed contract")

        records = self.all_records()
        record_statuses = {record.status.value for record in records}
        missing_record_statuses = REQUIRED_HEALTH_STATUSES - record_statuses
        if missing_record_statuses:
            raise ValueError(
                "health records do not cover statuses: "
                + ", ".join(sorted(missing_record_statuses))
            )
        record_families = {record.surface_family.value for record in records}
        missing_record_families = REQUIRED_SURFACE_FAMILIES - record_families
        if missing_record_families:
            raise ValueError(
                "health records do not cover surface families: "
                + ", ".join(sorted(missing_record_families))
            )

        blocker_cases = {case.value for case in self.claim_blocker_cases}
        missing_blocker_cases = REQUIRED_CLAIM_BLOCKER_CASES - blocker_cases
        if missing_blocker_cases:
            raise ValueError(
                "claim_blocker_cases missing: " + ", ".join(sorted(missing_blocker_cases))
            )
        record_blocker_cases = {record.fixture_case.value for record in records}
        missing_record_blocker_cases = REQUIRED_CLAIM_BLOCKER_CASES - record_blocker_cases
        if missing_record_blocker_cases:
            raise ValueError(
                "health records do not cover claim blockers: "
                + ", ".join(sorted(missing_record_blocker_cases))
            )

        if self.fail_closed_policy != {
            "unknown_health_allows_public_claim": False,
            "candidate_surface_allows_claim": False,
            "selected_only_satisfies_action": False,
            "commanded_only_satisfies_action": False,
            "inferred_context_satisfies_witness": False,
            "stale_source_allows_public_live": False,
            "missing_source_allows_claim": False,
            "monetization_without_public_health": False,
            "wrong_route_satisfies_action": False,
            "leak_allows_public_claim": False,
            "unsupported_claim_allows_grounded_success": False,
            "false_monetization_allows_monetized_success": False,
        }:
            raise ValueError("fail_closed_policy must pin all no-false-grounding gates false")

        for fixture in self.status_fixtures:
            if fixture.status is not HealthStatus.HEALTHY and fixture.claimable_health_allowed:
                raise ValueError(f"{fixture.status.value} cannot allow claimable health")
        return self

    def all_records(self) -> list[WorldSurfaceHealthRecord]:
        """Return all health records across envelope fixtures."""

        return [record for envelope in self.envelopes for record in envelope.records]

    def records_by_surface_id(self) -> dict[str, WorldSurfaceHealthRecord]:
        """Return all fixture records keyed by surface id."""

        return {record.surface_id: record for record in self.all_records()}

    def require_surface(self, surface_id: str) -> WorldSurfaceHealthRecord:
        """Return a health record or raise a fail-closed lookup error."""

        record = self.records_by_surface_id().get(surface_id)
        if record is None:
            raise KeyError(f"unknown WCS health surface: {surface_id}")
        return record

    def rows_for_fixture_case(self, fixture_case: FixtureCase) -> list[WorldSurfaceHealthRecord]:
        """Return health records for a no-false-grounding fixture case."""

        return [record for record in self.all_records() if record.fixture_case is fixture_case]


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise WorldSurfaceHealthError(f"{path} did not contain a JSON object")
    return payload


def load_world_surface_health_fixtures(
    path: Path = WORLD_SURFACE_HEALTH_FIXTURES,
) -> WorldSurfaceHealthFixtureSet:
    """Load WCS health envelope fixtures, failing closed on malformed data."""

    try:
        return WorldSurfaceHealthFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise WorldSurfaceHealthError(f"invalid WCS health fixtures at {path}: {exc}") from exc


__all__ = [
    "HEALTH_ENVELOPE_REQUIRED_FIELDS",
    "HEALTH_RECORD_REQUIRED_FIELDS",
    "REQUIRED_CLAIM_BLOCKER_CASES",
    "REQUIRED_HEALTH_STATUSES",
    "REQUIRED_SURFACE_FAMILIES",
    "WORLD_SURFACE_HEALTH_FIXTURES",
    "AuthorityCeiling",
    "EnvelopeStatus",
    "FixtureCase",
    "FreshnessState",
    "HealthDimensionId",
    "HealthDimensionState",
    "HealthStatus",
    "PublicPrivatePosture",
    "SurfaceFamily",
    "WitnessPolicy",
    "WorldSurfaceHealthError",
    "WorldSurfaceHealthFixtureSet",
    "WorldSurfaceHealthRecord",
    "load_world_surface_health_fixtures",
]
