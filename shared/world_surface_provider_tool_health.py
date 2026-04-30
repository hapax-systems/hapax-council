"""Provider/tool route health projection for World Capability Surface rows."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.capability_classification_inventory import (
    AvailabilityState,
    CapabilityClassificationRow,
    PublicClaimPolicy,
    load_capability_classification_inventory,
)
from shared.grounding_provider_router import provider_by_id
from shared.world_surface_health import (
    AuthorityCeiling,
    Claimability,
    Fallback,
    FixtureCase,
    Freshness,
    FreshnessState,
    HealthDimension,
    HealthDimensionId,
    HealthDimensionState,
    HealthStatus,
    KillSwitchState,
    KillSwitchStatus,
    PrivacyState,
    PublicPrivatePosture,
    RightsState,
    SurfaceFamily,
    WitnessPolicy,
    WorldSurfaceHealthRecord,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_TOOL_HEALTH_FIXTURES = (
    REPO_ROOT / "config" / "world-surface-provider-tool-health-fixtures.json"
)

REQUIRED_PROVIDER_TOOL_FAMILIES = frozenset(
    {
        "model_provider",
        "search_provider",
        "mcp_tool",
        "publication_endpoint",
        "storage_sync",
        "local_api",
        "docker_container",
    }
)


class ProviderToolHealthError(ValueError):
    """Raised when provider/tool health fixtures cannot project safely."""


class ProviderToolRouteFamily(StrEnum):
    MODEL_PROVIDER = "model_provider"
    SEARCH_PROVIDER = "search_provider"
    MCP_TOOL = "mcp_tool"
    PUBLICATION_ENDPOINT = "publication_endpoint"
    STORAGE_SYNC = "storage_sync"
    LOCAL_API = "local_api"
    DOCKER_CONTAINER = "docker_container"


class SuppliedEvidenceMode(StrEnum):
    NOT_SUPPLIED_EVIDENCE = "not_supplied_evidence"
    REQUIRES_SUPPLIED_EVIDENCE = "requires_supplied_evidence"
    SUPPLIED_EVIDENCE_ONLY = "supplied_evidence_only"
    NON_ACQUIRING_ROUTE = "non_acquiring_route"


class RedactionPrivacyPosture(StrEnum):
    PUBLIC_SAFE = "public_safe"
    REDACTION_REQUIRED = "redaction_required"
    PRIVATE_ONLY = "private_only"
    BLOCKED = "blocked"


class ProviderToolRouteHealth(BaseModel):
    """One model/provider/tool route row before WCS health projection."""

    model_config = ConfigDict(extra="forbid")

    route_id: str = Field(pattern=r"^provider_tool\.[a-z0-9_.-]+$")
    display_name: str = Field(min_length=1)
    classification_row_id: str = Field(min_length=1)
    route_family: ProviderToolRouteFamily
    provider_registry_id: str | None = None
    provider_kind: str | None = None
    model_id: str | None = None
    tool_id: str | None = None
    route_ref: str = Field(min_length=1)
    availability_state: AvailabilityState
    status: HealthStatus
    source_acquisition_capability: bool
    source_acquisition_evidence_refs: list[str] = Field(default_factory=list)
    supplied_evidence_mode: SuppliedEvidenceMode
    redaction_privacy_posture: RedactionPrivacyPosture
    redaction_evidence_refs: list[str] = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    producer_refs: list[str] = Field(min_length=1)
    consumer_refs: list[str] = Field(min_length=1)
    substrate_refs: list[str] = Field(min_length=1)
    capability_refs: list[str] = Field(min_length=1)
    evidence_envelope_refs: list[str] = Field(min_length=1)
    witness_refs: list[str] = Field(default_factory=list)
    grounding_gate_refs: list[str] = Field(default_factory=list)
    public_event_refs: list[str] = Field(default_factory=list)
    rights_evidence_refs: list[str] = Field(min_length=1)
    privacy_evidence_refs: list[str] = Field(min_length=1)
    freshness: Freshness
    confidence: float = Field(ge=0.0, le=1.0)
    authority_ceiling: AuthorityCeiling
    public_claim_policy: PublicClaimPolicy
    rights_state: RightsState
    public_private_posture: PublicPrivatePosture
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    fallback: Fallback
    kill_switch_state: KillSwitchState
    owner: str
    next_probe_due_at: str
    witness_policy: WitnessPolicy
    fixture_case: FixtureCase

    @model_validator(mode="after")
    def _validate_route_claim_authority(self) -> Self:
        if self.source_acquisition_capability and not self.source_acquisition_evidence_refs:
            raise ValueError(
                f"{self.route_id} claims source acquisition without acquisition evidence refs"
            )
        if (
            self.supplied_evidence_mode is SuppliedEvidenceMode.SUPPLIED_EVIDENCE_ONLY
            and self.source_acquisition_capability
        ):
            raise ValueError(
                f"{self.route_id} cannot be supplied-evidence-only and source-acquiring"
            )
        if (
            self.supplied_evidence_mode is SuppliedEvidenceMode.NOT_SUPPLIED_EVIDENCE
            and not self.source_acquisition_capability
        ):
            raise ValueError(
                f"{self.route_id} non-source-acquiring rows must name supplied/non-acquiring mode"
            )
        if self.status is not HealthStatus.HEALTHY and not self.blocking_reasons:
            raise ValueError(f"{self.route_id} non-healthy route health needs blocking reasons")
        if self.status is HealthStatus.STALE and self.freshness.state is not FreshnessState.STALE:
            raise ValueError(f"{self.route_id} stale route health requires stale freshness")
        if (
            self.status is HealthStatus.MISSING
            and self.freshness.state is not FreshnessState.MISSING
        ):
            raise ValueError(f"{self.route_id} missing route health requires missing freshness")
        if (
            self.status is HealthStatus.UNKNOWN
            and self.freshness.state is not FreshnessState.UNKNOWN
        ):
            raise ValueError(f"{self.route_id} unknown route health requires unknown freshness")
        return self

    def to_world_surface_health_record(self) -> WorldSurfaceHealthRecord:
        """Project route health into a bounded WCS health row."""

        privacy_state = self._privacy_state()
        private_only = (
            privacy_state is PrivacyState.PRIVATE_ONLY
            or self.public_private_posture is PublicPrivatePosture.PRIVATE_ONLY
        )
        dry_run_allowed = self.public_private_posture is PublicPrivatePosture.DRY_RUN
        return WorldSurfaceHealthRecord(
            surface_id=f"{self.route_id}.health",
            surface_family=SurfaceFamily.PROVIDER_TOOL,
            checked_at=self.freshness.checked_at,
            status=self.status,
            health_dimensions=self._health_dimensions(),
            source_refs=self.source_refs,
            producer_refs=self.producer_refs,
            consumer_refs=self.consumer_refs,
            route_refs=[self.route_ref],
            substrate_refs=self.substrate_refs,
            capability_refs=self.capability_refs,
            evidence_envelope_refs=self.evidence_envelope_refs,
            outcome_envelope_refs=[],
            witness_refs=self.witness_refs,
            grounding_gate_refs=self.grounding_gate_refs,
            public_event_refs=self.public_event_refs,
            freshness=self.freshness,
            confidence=self.confidence,
            authority_ceiling=self.authority_ceiling,
            privacy_state=privacy_state,
            rights_state=self.rights_state,
            public_private_posture=self.public_private_posture,
            public_claim_allowed=False,
            private_only=private_only,
            dry_run_allowed=dry_run_allowed,
            monetization_allowed=False,
            blocking_reasons=self.blocking_reasons,
            warnings=[
                *self.warnings,
                "provider_tool_route_health_does_not_grant_public_authority",
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

    def _privacy_state(self) -> PrivacyState:
        if self.redaction_privacy_posture is RedactionPrivacyPosture.PUBLIC_SAFE:
            return PrivacyState.PUBLIC_SAFE
        if self.redaction_privacy_posture is RedactionPrivacyPosture.REDACTION_REQUIRED:
            return PrivacyState.DRY_RUN
        if self.redaction_privacy_posture is RedactionPrivacyPosture.PRIVATE_ONLY:
            return PrivacyState.PRIVATE_ONLY
        return PrivacyState.BLOCKED

    def _health_dimensions(self) -> list[HealthDimension]:
        return [
            self._source_freshness_dimension(),
            self._dimension(
                HealthDimensionId.PRODUCER_EXISTS,
                self._pass_unless_blocked(),
                True,
                self.producer_refs,
                "Provider/tool producer is named from the classification inventory.",
            ),
            self._dimension(
                HealthDimensionId.CONSUMER_EXISTS,
                HealthDimensionState.PASS,
                True,
                self.consumer_refs,
                "Provider/tool consumers are explicit WCS/publication gate consumers.",
            ),
            self._dimension(
                HealthDimensionId.ROUTE_BINDING,
                self._route_binding_state(),
                True,
                [self.route_ref],
                "Route binding is named separately from claim authority.",
            ),
            self._dimension(
                HealthDimensionId.EXECUTION_WITNESS,
                self._witness_state(),
                True,
                self.witness_refs,
                "Route execution/health witness is distinct from public-world outcome.",
            ),
            self._world_witness_dimension(),
            self._dimension(
                HealthDimensionId.NO_LEAK,
                self._no_leak_state(),
                True,
                self.redaction_evidence_refs,
                "Redaction/privacy posture is explicit before public publication.",
            ),
            self._dimension(
                HealthDimensionId.EGRESS_PUBLIC,
                HealthDimensionState.MISSING,
                True,
                [],
                "Provider/tool route health cannot by itself prove public egress.",
            ),
            self._dimension(
                HealthDimensionId.PUBLIC_EVENT_POLICY,
                HealthDimensionState.MISSING,
                True,
                [],
                "Provider/tool route health cannot by itself attach public event policy.",
            ),
            self._dimension(
                HealthDimensionId.RIGHTS_PROVENANCE,
                self._rights_state_dimension(),
                True,
                self.rights_evidence_refs,
                "Rights posture is carried through but does not grant publication.",
            ),
            self._dimension(
                HealthDimensionId.PRIVACY_CONSENT,
                self._privacy_dimension_state(),
                True,
                self.privacy_evidence_refs,
                "Privacy posture is carried through but cannot bypass egress gates.",
            ),
            self._dimension(
                HealthDimensionId.GROUNDING_GATE,
                self._grounding_gate_state(),
                True,
                self.grounding_gate_refs,
                "Grounding route health is inspectable before publication.",
            ),
            self._dimension(
                HealthDimensionId.CLAIM_AUTHORITY,
                self._claim_authority_state(),
                True,
                [f"authority:{self.authority_ceiling.value}", self.classification_row_id],
                "Authority ceiling is explicit; route availability is not claim authority.",
            ),
            self._dimension(
                HealthDimensionId.MONETIZATION_READINESS,
                HealthDimensionState.NOT_APPLICABLE,
                False,
                [],
                "Provider/tool health carries no monetization permission.",
            ),
            self._dimension(
                HealthDimensionId.FALLBACK_KNOWN,
                HealthDimensionState.PASS,
                True,
                [f"fallback:{self.route_id}:{self.fallback.reason_code}"],
                "Fail-closed fallback is explicit.",
            ),
            self._dimension(
                HealthDimensionId.KILL_SWITCH,
                self._kill_switch_dimension_state(),
                True,
                self.kill_switch_state.evidence_refs,
                "Kill-switch state is explicit for publication preflight.",
            ),
        ]

    def _dimension(
        self,
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
            evidence_refs=evidence_refs if state is HealthDimensionState.PASS else evidence_refs,
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
            "Provider/tool health freshness is bounded by the route witness TTL.",
        )

    def _world_witness_dimension(self) -> HealthDimension:
        if self.source_acquisition_capability:
            return self._dimension(
                HealthDimensionId.WORLD_WITNESS,
                HealthDimensionState.PASS,
                True,
                self.source_acquisition_evidence_refs,
                "Actual source acquisition evidence is present for this route.",
            )
        return self._dimension(
            HealthDimensionId.WORLD_WITNESS,
            HealthDimensionState.NOT_APPLICABLE,
            False,
            [],
            "Supplied-evidence/local routes do not claim source acquisition.",
        )

    def _pass_unless_blocked(self) -> HealthDimensionState:
        if self.availability_state in {
            AvailabilityState.BLOCKED,
            AvailabilityState.UNAVAILABLE,
            AvailabilityState.DECOMMISSIONED,
        }:
            return HealthDimensionState.FAIL
        return HealthDimensionState.PASS

    def _route_binding_state(self) -> HealthDimensionState:
        if self.status in {HealthStatus.BLOCKED, HealthStatus.MISSING, HealthStatus.UNKNOWN}:
            return HealthDimensionState.FAIL
        return HealthDimensionState.PASS

    def _witness_state(self) -> HealthDimensionState:
        return HealthDimensionState.PASS if self.witness_refs else HealthDimensionState.MISSING

    def _no_leak_state(self) -> HealthDimensionState:
        if self.redaction_privacy_posture is RedactionPrivacyPosture.BLOCKED:
            return HealthDimensionState.FAIL
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

    def _privacy_dimension_state(self) -> HealthDimensionState:
        if self._privacy_state() in {
            PrivacyState.PUBLIC_SAFE,
            PrivacyState.PRIVATE_ONLY,
            PrivacyState.DRY_RUN,
            PrivacyState.ARCHIVE_ONLY,
        }:
            return HealthDimensionState.PASS
        if self._privacy_state() is PrivacyState.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        return HealthDimensionState.FAIL

    def _grounding_gate_state(self) -> HealthDimensionState:
        return (
            HealthDimensionState.PASS if self.grounding_gate_refs else HealthDimensionState.MISSING
        )

    def _claim_authority_state(self) -> HealthDimensionState:
        if self.authority_ceiling in {
            AuthorityCeiling.EVIDENCE_BOUND,
            AuthorityCeiling.PUBLIC_GATE_REQUIRED,
        }:
            return HealthDimensionState.PASS
        if self.authority_ceiling is AuthorityCeiling.NO_CLAIM:
            return HealthDimensionState.FAIL
        return HealthDimensionState.BLOCKED

    def _kill_switch_dimension_state(self) -> HealthDimensionState:
        if self.kill_switch_state.state is KillSwitchStatus.CLEAR:
            return HealthDimensionState.PASS
        if self.kill_switch_state.state is KillSwitchStatus.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        return HealthDimensionState.FAIL


class ProviderToolHealthFixtureSet(BaseModel):
    """Fixture set for provider/tool route health rows."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: Literal["schemas/world-surface-provider-tool-health.schema.json"]
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    required_route_families: list[ProviderToolRouteFamily] = Field(min_length=1)
    routes: list[ProviderToolRouteHealth] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_fixture_contract(self) -> Self:
        route_ids = [route.route_id for route in self.routes]
        duplicate_route_ids = sorted(
            {route_id for route_id in route_ids if route_ids.count(route_id) > 1}
        )
        if duplicate_route_ids:
            raise ValueError("duplicate provider/tool route ids: " + ", ".join(duplicate_route_ids))

        family_values = {family.value for family in self.required_route_families}
        missing_families = REQUIRED_PROVIDER_TOOL_FAMILIES - family_values
        if missing_families:
            raise ValueError(
                "missing provider/tool route families: " + ", ".join(sorted(missing_families))
            )
        record_families = {route.route_family.value for route in self.routes}
        missing_record_families = REQUIRED_PROVIDER_TOOL_FAMILIES - record_families
        if missing_record_families:
            raise ValueError(
                "provider/tool routes do not cover families: "
                + ", ".join(sorted(missing_record_families))
            )

        if self.fail_closed_policy != {
            "route_availability_grants_public_claim": False,
            "supplied_evidence_counts_as_source_acquisition": False,
            "source_acquisition_without_evidence_allowed": False,
            "monetization_allowed_from_route_health": False,
            "private_route_can_publish_by_default": False,
        }:
            raise ValueError("provider/tool route fail_closed_policy must pin gates false")

        self._validate_against_capability_inventory()
        self._validate_provider_registry_refs()
        return self

    def _validate_against_capability_inventory(self) -> None:
        inventory_rows = load_capability_classification_inventory().by_id()
        for route in self.routes:
            try:
                inventory_row = inventory_rows[route.classification_row_id]
            except KeyError as exc:
                raise ValueError(
                    f"{route.route_id} references missing classification row "
                    f"{route.classification_row_id}"
                ) from exc
            _validate_route_matches_inventory(route, inventory_row)

    def _validate_provider_registry_refs(self) -> None:
        providers = provider_by_id()
        for route in self.routes:
            if route.provider_registry_id and route.provider_registry_id not in providers:
                raise ValueError(
                    f"{route.route_id} references missing grounding provider "
                    f"{route.provider_registry_id}"
                )
            if route.provider_registry_id:
                provider = providers[route.provider_registry_id]
                if route.provider_kind and route.provider_kind != provider.provider_kind.value:
                    raise ValueError(f"{route.route_id} provider_kind does not match registry")
                if route.model_id and route.model_id != provider.model_id:
                    raise ValueError(f"{route.route_id} model_id does not match registry")
                if route.tool_id and route.tool_id != provider.tool_id:
                    raise ValueError(f"{route.route_id} tool_id does not match registry")

    def to_world_surface_health_records(self) -> list[WorldSurfaceHealthRecord]:
        """Project every provider/tool route into WCS health records."""

        return [route.to_world_surface_health_record() for route in self.routes]


def _validate_route_matches_inventory(
    route: ProviderToolRouteHealth,
    inventory_row: CapabilityClassificationRow,
) -> None:
    if route.route_family.value != inventory_row.surface_family.value:
        raise ValueError(f"{route.route_id} route_family does not match classification row")
    if route.availability_state is not inventory_row.availability_state:
        raise ValueError(f"{route.route_id} availability_state does not match classification row")
    if route.source_acquisition_capability != inventory_row.can_acquire_sources:
        raise ValueError(
            f"{route.route_id} source_acquisition_capability does not match classification row"
        )
    if inventory_row.supplied_evidence_only:
        if route.supplied_evidence_mode is not SuppliedEvidenceMode.SUPPLIED_EVIDENCE_ONLY:
            raise ValueError(f"{route.route_id} must be supplied-evidence-only")
    elif (
        route.source_acquisition_capability
        and route.supplied_evidence_mode is not SuppliedEvidenceMode.NOT_SUPPLIED_EVIDENCE
    ):
        raise ValueError(f"{route.route_id} source-acquiring rows must not use supplied mode")
    if route.public_claim_policy is not inventory_row.public_claim_policy:
        raise ValueError(f"{route.route_id} public_claim_policy does not match classification row")
    if route.authority_ceiling.value != inventory_row.claim_authority_ceiling.value:
        raise ValueError(f"{route.route_id} authority_ceiling does not match classification row")
    if inventory_row.evidence_ref not in route.source_refs:
        raise ValueError(f"{route.route_id} source_refs must include inventory evidence_ref")
    if inventory_row.producer not in route.producer_refs:
        raise ValueError(f"{route.route_id} producer_refs must include inventory producer")
    if not set(inventory_row.consumer_refs).issubset(route.consumer_refs):
        raise ValueError(f"{route.route_id} consumer_refs must include inventory consumers")
    if inventory_row.surface_id not in route.capability_refs:
        raise ValueError(f"{route.route_id} capability_refs must include inventory surface id")


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProviderToolHealthError(f"{path} did not contain a JSON object")
    return payload


def load_provider_tool_health_fixtures(
    path: Path = PROVIDER_TOOL_HEALTH_FIXTURES,
) -> ProviderToolHealthFixtureSet:
    """Load provider/tool route health fixtures, failing closed on malformed data."""

    try:
        return ProviderToolHealthFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ProviderToolHealthError(
            f"invalid provider/tool health fixtures at {path}: {exc}"
        ) from exc


def project_provider_tool_health_records(
    path: Path = PROVIDER_TOOL_HEALTH_FIXTURES,
) -> list[WorldSurfaceHealthRecord]:
    """Load and project provider/tool route health fixtures into WCS rows."""

    return load_provider_tool_health_fixtures(path).to_world_surface_health_records()


__all__ = [
    "PROVIDER_TOOL_HEALTH_FIXTURES",
    "REQUIRED_PROVIDER_TOOL_FAMILIES",
    "ProviderToolHealthError",
    "ProviderToolHealthFixtureSet",
    "ProviderToolRouteFamily",
    "ProviderToolRouteHealth",
    "RedactionPrivacyPosture",
    "SuppliedEvidenceMode",
    "load_provider_tool_health_fixtures",
    "project_provider_tool_health_records",
]
