"""Inert provider/tool capability bridge for SDLC route-supply facts.

The bridge projects existing capability inventory, provider/tool health, tool
outcome, and provider-gateway registry rows into fail-closed route-supply
facts. It does not dispatch work, call providers, write receipts, mutate
ledgers, or promote any route into authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.capability_classification_inventory import (
    AvailabilityState,
    CapabilityClassificationInventory,
    CapabilityClassificationRow,
    PublicClaimPolicy,
    SurfaceFamily,
    load_capability_classification_inventory,
)
from shared.platform_capability_registry import (
    CapacityPool,
    PlatformCapabilityRegistry,
    PlatformCapabilityRoute,
    Profile,
    RouteState,
    load_platform_capability_registry,
)
from shared.route_metadata_schema import SourceGroundingNeed
from shared.tool_provider_outcome import (
    ToolProviderOutcomeEnvelope,
    ToolProviderOutcomeFixtureSet,
    load_tool_provider_outcome_fixtures,
)
from shared.world_surface_provider_tool_health import (
    ProviderToolHealthFixtureSet,
    ProviderToolRouteFamily,
    ProviderToolRouteHealth,
    RedactionPrivacyPosture,
    SuppliedEvidenceMode,
    load_provider_tool_health_fixtures,
)

CURRENT_WORLD_SOURCE_NEEDS = frozenset(
    {
        SourceGroundingNeed.OFFICIAL_DOCS_CURRENT,
        SourceGroundingNeed.WEB_CURRENT,
        SourceGroundingNeed.LITERATURE,
        SourceGroundingNeed.MULTIMODAL,
    }
)

SATISFYING_AVAILABILITY_STATES = frozenset({AvailabilityState.AVAILABLE.value})
SATISFYING_PROVIDER_GATEWAY_STATES = frozenset({RouteState.ACTIVE.value})
SATISFYING_PROVIDER_HEALTH_STATUSES = frozenset({"healthy"})


class SdlcToolCapabilityBridgeError(ValueError):
    """Raised when bridge inputs cannot be projected safely."""


class RouteSupplyOrigin(StrEnum):
    CAPABILITY_CLASSIFICATION_INVENTORY = "capability_classification_inventory"
    PROVIDER_TOOL_HEALTH = "provider_tool_health"
    PLATFORM_PROVIDER_GATEWAY = "platform_provider_gateway"


class RouteSupplyRole(StrEnum):
    SOURCE_ACQUISITION = "source_acquisition"
    SUPPLIED_EVIDENCE_RECALL = "supplied_evidence_recall"
    VERIFIER_FLOOR_CHECKING = "verifier_floor_checking"
    PUBLICATION_EGRESS = "publication_egress"
    AVSDLC_AUDIO_TOOL = "avsdlc_audio_tool"
    TELEMETRY_RESOURCE = "telemetry_resource"
    PROVIDER_GATEWAY = "provider_gateway"
    STORAGE_INFRA_CONTROL = "storage_infra_control"


class ProviderSpendPosture(StrEnum):
    NOT_PROVIDER_GATEWAY = "not_provider_gateway"
    SPEND_BLOCKED = "spend_blocked"
    SPEND_REQUIRES_RECEIPT = "spend_requires_receipt"
    SPEND_EVIDENCED = "spend_evidenced"


class RouteSupplyMatchStatus(StrEnum):
    SATISFIES = "satisfies"
    HELD = "held"
    ROLE_MISMATCH = "role_mismatch"


class BridgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SdlcRouteDemand(BridgeModel):
    """One route-supply demand to test against projected bridge facts."""

    role: RouteSupplyRole
    source_grounding_need: SourceGroundingNeed = SourceGroundingNeed.NONE
    requires_fresh_current_world_evidence: bool = False
    requires_public_claim_evidence: bool = False
    requires_publication_egress: bool = False
    publication_authorized: bool = False
    rights_evidence_refs: tuple[str, ...] = Field(default=())
    privacy_redaction_evidence_refs: tuple[str, ...] = Field(default=())
    explicit_receipt_refs: tuple[str, ...] = Field(default=())
    provider_spend_authorized: bool = False
    provider_budget_evidence_refs: tuple[str, ...] = Field(default=())
    routine_fallback: bool = False

    @model_validator(mode="after")
    def _current_world_need_sets_fresh_requirement(self) -> Self:
        if (
            self.source_grounding_need in CURRENT_WORLD_SOURCE_NEEDS
            and not self.requires_fresh_current_world_evidence
        ):
            object.__setattr__(self, "requires_fresh_current_world_evidence", True)
        return self


class SdlcRouteSupplyFact(BridgeModel):
    """A visible route-supply fact; satisfiability is explicit and fail-closed."""

    supply_schema: Literal[1] = 1
    supply_id: str
    origin: RouteSupplyOrigin
    role: RouteSupplyRole
    route_ref: str
    display_name: str
    classification_row_id: str | None = None
    provider_tool_route_id: str | None = None
    platform_route_id: str | None = None
    availability_state: str | None = None
    health_status: str | None = None
    authority_ceiling: str | None = None
    public_claim_policy: str | None = None
    visible: bool = True
    can_satisfy_required_demands: bool = False
    source_acquisition_capable: bool = False
    source_acquisition_evidence_refs: tuple[str, ...] = Field(default=())
    fresh_current_world_evidence_allowed: bool = False
    public_claim_evidence_allowed: bool = False
    supplied_evidence_only: bool = False
    publication_egress_allowed: bool = False
    publication_authority_granted: bool = False
    rights_evidence_refs: tuple[str, ...] = Field(default=())
    privacy_redaction_evidence_refs: tuple[str, ...] = Field(default=())
    explicit_receipt_refs: tuple[str, ...] = Field(default=())
    provider_spend_required: bool = False
    provider_spend_posture: ProviderSpendPosture = ProviderSpendPosture.NOT_PROVIDER_GATEWAY
    provider_budget_evidence_refs: tuple[str, ...] = Field(default=())
    paid_provider: str | None = None
    paid_profile: str | None = None
    capacity_pool: str | None = None
    routine_fallback_allowed: bool = False
    blocking_reasons: tuple[str, ...] = Field(default=())
    warnings: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())
    outcome_refs: tuple[str, ...] = Field(default=())
    fresh_source_outcome_refs: tuple[str, ...] = Field(default=())
    supplied_evidence_outcome_refs: tuple[str, ...] = Field(default=())
    public_claim_outcome_refs: tuple[str, ...] = Field(default=())
    world_truth_witnessed: Literal[False] = False

    @model_validator(mode="after")
    def _satisfying_fact_obeys_role_gates(self) -> Self:
        if self.supplied_evidence_only:
            if self.fresh_current_world_evidence_allowed or self.public_claim_evidence_allowed:
                raise ValueError("supplied-evidence recall cannot satisfy fresh/public claims")

        if self.role is RouteSupplyRole.PROVIDER_GATEWAY:
            if self.routine_fallback_allowed:
                raise ValueError("provider gateways cannot be routine fallback capacity")
            if not self.provider_spend_required:
                raise ValueError("provider gateway facts must carry provider spend posture")

        if not self.can_satisfy_required_demands:
            return self

        if not self.visible:
            raise ValueError("hidden route supply cannot satisfy demands")
        if self.role is RouteSupplyRole.PROVIDER_GATEWAY:
            if self.availability_state not in {None, *SATISFYING_PROVIDER_GATEWAY_STATES}:
                raise ValueError("inactive provider gateway supply cannot satisfy demands")
        elif self.availability_state not in {None, *SATISFYING_AVAILABILITY_STATES}:
            raise ValueError("non-available route supply cannot satisfy demands")
        if self.health_status not in {None, *SATISFYING_PROVIDER_HEALTH_STATUSES}:
            raise ValueError("non-healthy provider/tool route cannot satisfy demands")

        if self.role is RouteSupplyRole.SOURCE_ACQUISITION:
            if not self.source_acquisition_capable or not self.source_acquisition_evidence_refs:
                raise ValueError(
                    "source-acquisition supply needs capability and acquisition evidence"
                )
            if not self.fresh_current_world_evidence_allowed:
                raise ValueError("source-acquisition supply must allow fresh-world evidence")

        if self.role is RouteSupplyRole.PUBLICATION_EGRESS:
            if not self.publication_egress_allowed:
                raise ValueError("publication egress supply must be explicitly allowed")
            if not self.publication_authority_granted:
                raise ValueError("publication egress supply needs publication authority")
            if (
                not self.rights_evidence_refs
                or not self.privacy_redaction_evidence_refs
                or not self.explicit_receipt_refs
            ):
                raise ValueError(
                    "publication egress supply needs rights, privacy/redaction, and receipts"
                )

        if self.role is RouteSupplyRole.PROVIDER_GATEWAY:
            if self.provider_spend_posture is not ProviderSpendPosture.SPEND_EVIDENCED:
                raise ValueError("provider gateway supply requires evidenced spend posture")
            if not self.provider_budget_evidence_refs:
                raise ValueError("provider gateway supply requires budget evidence refs")

        return self

    def assess(self, demand: SdlcRouteDemand) -> RouteSupplyAssessment:
        """Evaluate this fact against a route demand without selecting the route."""

        return assess_sdlc_route_supply(self, demand)


class RouteSupplyAssessment(BridgeModel):
    supply_id: str
    demand_role: RouteSupplyRole
    status: RouteSupplyMatchStatus
    satisfies: bool
    reason_codes: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())


def assess_sdlc_route_supply(
    fact: SdlcRouteSupplyFact,
    demand: SdlcRouteDemand,
) -> RouteSupplyAssessment:
    """Return a fail-closed satisfiability assessment for one supply/demand pair."""

    reason_codes: list[str] = []
    evidence_refs: list[str] = [*fact.evidence_refs]

    if fact.role is not demand.role:
        return RouteSupplyAssessment(
            supply_id=fact.supply_id,
            demand_role=demand.role,
            status=RouteSupplyMatchStatus.ROLE_MISMATCH,
            satisfies=False,
            reason_codes=("role_mismatch",),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
        )

    if not fact.can_satisfy_required_demands:
        reason_codes.extend(["supply_fact_held", *fact.blocking_reasons])

    if demand.requires_fresh_current_world_evidence:
        if not fact.fresh_current_world_evidence_allowed:
            reason_codes.append("fresh_current_world_evidence_absent")
        if not fact.source_acquisition_capable:
            reason_codes.append("source_acquisition_capability_absent")
        if not fact.source_acquisition_evidence_refs:
            reason_codes.append("source_acquisition_evidence_absent")
        evidence_refs.extend(fact.source_acquisition_evidence_refs)

    if demand.requires_public_claim_evidence:
        if fact.supplied_evidence_only:
            reason_codes.append("supplied_evidence_not_public_claim_evidence")
        if not fact.public_claim_evidence_allowed:
            reason_codes.append("public_claim_evidence_absent")
        evidence_refs.extend(fact.public_claim_outcome_refs)

    if demand.requires_publication_egress or fact.role is RouteSupplyRole.PUBLICATION_EGRESS:
        if not fact.publication_egress_allowed:
            reason_codes.append("publication_egress_held")
        if not (demand.publication_authorized and fact.publication_authority_granted):
            reason_codes.append("publication_authority_absent")
        if not (demand.rights_evidence_refs and fact.rights_evidence_refs):
            reason_codes.append("publication_rights_evidence_absent")
        if not (demand.privacy_redaction_evidence_refs and fact.privacy_redaction_evidence_refs):
            reason_codes.append("publication_privacy_redaction_evidence_absent")
        if not (demand.explicit_receipt_refs and fact.explicit_receipt_refs):
            reason_codes.append("publication_explicit_receipts_absent")
        evidence_refs.extend(
            [
                *fact.rights_evidence_refs,
                *fact.privacy_redaction_evidence_refs,
                *fact.explicit_receipt_refs,
            ]
        )

    if fact.role is RouteSupplyRole.PROVIDER_GATEWAY:
        if demand.routine_fallback or fact.routine_fallback_allowed:
            reason_codes.append("provider_gateway_routine_fallback_forbidden")
        if not demand.provider_spend_authorized:
            reason_codes.append("provider_spend_authority_absent")
        if (
            fact.provider_spend_posture is not ProviderSpendPosture.SPEND_EVIDENCED
            or not fact.provider_budget_evidence_refs
        ):
            reason_codes.append("provider_budget_evidence_absent")
        if not demand.provider_budget_evidence_refs:
            reason_codes.append("provider_budget_receipt_absent")
        evidence_refs.extend(
            [*fact.provider_budget_evidence_refs, *demand.provider_budget_evidence_refs]
        )

    reason_codes = list(dict.fromkeys(reason_codes))
    satisfies = not reason_codes
    return RouteSupplyAssessment(
        supply_id=fact.supply_id,
        demand_role=demand.role,
        status=RouteSupplyMatchStatus.SATISFIES if satisfies else RouteSupplyMatchStatus.HELD,
        satisfies=satisfies,
        reason_codes=tuple(reason_codes),
        evidence_refs=tuple(dict.fromkeys(evidence_refs)),
    )


def project_sdlc_route_supply_facts(
    *,
    inventory: CapabilityClassificationInventory | None = None,
    provider_health: ProviderToolHealthFixtureSet | None = None,
    tool_outcomes: ToolProviderOutcomeFixtureSet | None = None,
    platform_registry: PlatformCapabilityRegistry | None = None,
    include_inventory_rows: bool = True,
) -> list[SdlcRouteSupplyFact]:
    """Project all bridge inputs into visible SDLC route-supply facts."""

    resolved_inventory = inventory or load_capability_classification_inventory()
    facts: list[SdlcRouteSupplyFact] = []
    if include_inventory_rows:
        facts.extend(project_capability_inventory_supply_facts(resolved_inventory))
    facts.extend(
        project_provider_tool_route_supply_facts(
            provider_health=provider_health,
            inventory=resolved_inventory,
            tool_outcomes=tool_outcomes,
        )
    )
    facts.extend(project_provider_gateway_supply_facts(platform_registry=platform_registry))
    return facts


def project_capability_inventory_supply_facts(
    inventory: CapabilityClassificationInventory | None = None,
) -> list[SdlcRouteSupplyFact]:
    """Project inventory rows into inert route-supply facts."""

    resolved_inventory = inventory or load_capability_classification_inventory()
    return [_inventory_row_supply_fact(row) for row in resolved_inventory.rows]


def project_provider_tool_route_supply_facts(
    *,
    provider_health: ProviderToolHealthFixtureSet | None = None,
    inventory: CapabilityClassificationInventory | None = None,
    tool_outcomes: ToolProviderOutcomeFixtureSet | None = None,
) -> list[SdlcRouteSupplyFact]:
    """Project provider/tool health rows into SDLC route-supply facts."""

    resolved_health = provider_health or load_provider_tool_health_fixtures()
    resolved_inventory = inventory or load_capability_classification_inventory()
    resolved_outcomes = tool_outcomes or load_tool_provider_outcome_fixtures()
    rows_by_id = resolved_inventory.by_id()
    outcomes_by_route = _outcomes_by_route(resolved_outcomes.outcomes)
    return [
        project_provider_tool_route_supply_fact(
            route,
            inventory_row=rows_by_id.get(route.classification_row_id),
            outcomes=outcomes_by_route.get(_route_key(route.route_id), ()),
        )
        for route in resolved_health.routes
    ]


def project_provider_tool_route_supply_fact(
    route: ProviderToolRouteHealth,
    *,
    inventory_row: CapabilityClassificationRow | None,
    outcomes: Sequence[ToolProviderOutcomeEnvelope] = (),
) -> SdlcRouteSupplyFact:
    """Project one provider/tool health row, preserving mismatch blockers."""

    role = _provider_tool_role(route)
    mismatch_reasons = _provider_route_mismatch_reasons(route, inventory_row)
    blocking_reasons = [
        *mismatch_reasons,
        *_provider_tool_blocking_reasons(route, role),
        *route.blocking_reasons,
    ]
    can_satisfy = not blocking_reasons
    fresh_source_outcomes = [
        outcome.outcome_id for outcome in outcomes if outcome.can_support_fresh_source_claim()
    ]
    supplied_outcomes = [
        outcome.outcome_id for outcome in outcomes if outcome.can_support_supplied_evidence_claim()
    ]
    public_outcomes = [
        outcome.outcome_id for outcome in outcomes if outcome.can_support_public_claim()
    ]
    evidence_refs = _unique(
        [
            *route.source_refs,
            *route.evidence_envelope_refs,
            *route.witness_refs,
            *route.grounding_gate_refs,
            *route.source_acquisition_evidence_refs,
            *[ref for outcome in outcomes for ref in outcome.action_receipt_consumption_refs()],
        ]
    )
    source_ready = (
        route.source_acquisition_capability
        and bool(route.source_acquisition_evidence_refs)
        and route.status.value in SATISFYING_PROVIDER_HEALTH_STATUSES
        and not mismatch_reasons
    )
    supplied_only = route.supplied_evidence_mode is SuppliedEvidenceMode.SUPPLIED_EVIDENCE_ONLY
    return SdlcRouteSupplyFact(
        supply_id=f"sdlc_route_supply:{route.route_id}",
        origin=RouteSupplyOrigin.PROVIDER_TOOL_HEALTH,
        role=role,
        route_ref=route.route_ref,
        display_name=route.display_name,
        classification_row_id=route.classification_row_id,
        provider_tool_route_id=route.route_id,
        availability_state=route.availability_state.value,
        health_status=route.status.value,
        authority_ceiling=route.authority_ceiling.value,
        public_claim_policy=route.public_claim_policy.value,
        can_satisfy_required_demands=can_satisfy,
        source_acquisition_capable=route.source_acquisition_capability,
        source_acquisition_evidence_refs=tuple(route.source_acquisition_evidence_refs),
        fresh_current_world_evidence_allowed=source_ready,
        public_claim_evidence_allowed=(
            source_ready
            and route.public_claim_policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED
            and route.redaction_privacy_posture is RedactionPrivacyPosture.PUBLIC_SAFE
            and bool(public_outcomes or route.grounding_gate_refs)
        ),
        supplied_evidence_only=supplied_only,
        publication_egress_allowed=False,
        publication_authority_granted=False,
        rights_evidence_refs=tuple(route.rights_evidence_refs),
        privacy_redaction_evidence_refs=tuple(
            _unique([*route.privacy_evidence_refs, *route.redaction_evidence_refs])
        ),
        explicit_receipt_refs=tuple(route.public_event_refs),
        blocking_reasons=tuple(_unique(blocking_reasons)),
        warnings=tuple(
            _unique(
                [
                    *route.warnings,
                    "provider_tool_health_is_route_supply_not_dispatch_authority",
                    "tool_provider_outcomes_are_not_world_truth",
                ]
            )
        ),
        evidence_refs=tuple(evidence_refs),
        outcome_refs=tuple(outcome.outcome_id for outcome in outcomes),
        fresh_source_outcome_refs=tuple(fresh_source_outcomes),
        supplied_evidence_outcome_refs=tuple(supplied_outcomes),
        public_claim_outcome_refs=tuple(public_outcomes),
    )


def project_provider_gateway_supply_facts(
    *,
    platform_registry: PlatformCapabilityRegistry | None = None,
) -> list[SdlcRouteSupplyFact]:
    """Project provider-gateway platform rows with spend posture visible."""

    registry = platform_registry or load_platform_capability_registry()
    return [
        _provider_gateway_supply_fact(route)
        for route in registry.routes
        if route.profile is Profile.PROVIDER_GATEWAY or route.mutability.provider_spend
    ]


def _inventory_row_supply_fact(row: CapabilityClassificationRow) -> SdlcRouteSupplyFact:
    role = _inventory_row_role(row)
    blocking_reasons = _inventory_blocking_reasons(row, role)
    source_ready = (
        row.can_acquire_sources
        and bool(row.evidence_refs)
        and row.availability_state is AvailabilityState.AVAILABLE
        and not blocking_reasons
    )
    supplied_only = row.supplied_evidence_only
    return SdlcRouteSupplyFact(
        supply_id=f"sdlc_route_supply:inventory:{row.row_id}",
        origin=RouteSupplyOrigin.CAPABILITY_CLASSIFICATION_INVENTORY,
        role=role,
        route_ref=row.surface_id,
        display_name=row.display_name,
        classification_row_id=row.row_id,
        availability_state=row.availability_state.value,
        authority_ceiling=row.claim_authority_ceiling.value,
        public_claim_policy=row.public_claim_policy.value,
        can_satisfy_required_demands=not blocking_reasons,
        source_acquisition_capable=row.can_acquire_sources,
        source_acquisition_evidence_refs=tuple(
            row.evidence_refs if row.can_acquire_sources else ()
        ),
        fresh_current_world_evidence_allowed=source_ready,
        public_claim_evidence_allowed=(
            source_ready and row.public_claim_policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED
        ),
        supplied_evidence_only=supplied_only,
        publication_egress_allowed=False,
        publication_authority_granted=False,
        rights_evidence_refs=tuple(
            ref
            for ref in (row.projection.rights_ref if row.projection else None, row.evidence_ref)
            if ref
        ),
        privacy_redaction_evidence_refs=tuple(row.evidence_refs),
        blocking_reasons=tuple(blocking_reasons),
        warnings=("capability_inventory_fact_is_static_route_supply_not_dispatch_authority",),
        evidence_refs=tuple(
            _unique([row.evidence_ref, *row.evidence_refs, *row.witness_requirements])
        ),
    )


def _provider_gateway_supply_fact(route: PlatformCapabilityRoute) -> SdlcRouteSupplyFact:
    quota_evidence = tuple(route.freshness.evidence.quota.evidence_refs)
    blocked_reasons = _unique(
        [
            *route.blocked_reasons,
            *route.freshness.evidence.capability.blocked_reasons,
            *route.freshness.evidence.quota.blocked_reasons,
            *route.freshness.evidence.resource.blocked_reasons,
        ]
    )
    spend_posture = _provider_spend_posture(route, quota_evidence, blocked_reasons)
    provider_spend_required = route.mutability.provider_spend
    can_satisfy = (
        route.route_state is RouteState.ACTIVE
        and provider_spend_required
        and spend_posture is ProviderSpendPosture.SPEND_EVIDENCED
        and bool(quota_evidence)
    )
    evidence_refs = _unique(
        [
            f"platform-capability-registry:{route.route_id}",
            *route.quality_envelope.explicit_equivalence_records,
            *route.freshness.evidence.provider_docs.evidence_refs,
            *route.freshness.evidence.capability.evidence_refs,
            *route.freshness.evidence.resource.evidence_refs,
            *quota_evidence,
        ]
    )
    return SdlcRouteSupplyFact(
        supply_id=f"sdlc_route_supply:platform:{route.route_id}",
        origin=RouteSupplyOrigin.PLATFORM_PROVIDER_GATEWAY,
        role=RouteSupplyRole.PROVIDER_GATEWAY,
        route_ref=route.route_id,
        display_name=route.summary,
        platform_route_id=route.route_id,
        availability_state=route.route_state.value,
        authority_ceiling=route.authority_ceiling.value,
        can_satisfy_required_demands=can_satisfy,
        provider_spend_required=provider_spend_required,
        provider_spend_posture=spend_posture,
        provider_budget_evidence_refs=quota_evidence,
        paid_provider=route.paid_provider,
        paid_profile=route.paid_profile,
        capacity_pool=route.capacity_pool.value,
        routine_fallback_allowed=False,
        blocking_reasons=tuple(blocked_reasons),
        warnings=(
            "provider_gateway_supply_requires_provider_spend_authority",
            "provider_gateway_supply_is_not_routine_fallback_capacity",
        ),
        evidence_refs=tuple(evidence_refs),
        explicit_receipt_refs=tuple(route.quality_envelope.explicit_equivalence_records),
    )


def _provider_tool_role(route: ProviderToolRouteHealth) -> RouteSupplyRole:
    if route.route_family in {
        ProviderToolRouteFamily.SEARCH_PROVIDER,
        ProviderToolRouteFamily.MCP_TOOL,
    }:
        if route.source_acquisition_capability:
            return RouteSupplyRole.SOURCE_ACQUISITION
        return RouteSupplyRole.SUPPLIED_EVIDENCE_RECALL
    if route.route_family is ProviderToolRouteFamily.MODEL_PROVIDER:
        return RouteSupplyRole.SUPPLIED_EVIDENCE_RECALL
    if route.route_family is ProviderToolRouteFamily.PUBLICATION_ENDPOINT:
        return RouteSupplyRole.PUBLICATION_EGRESS
    if route.route_family in {
        ProviderToolRouteFamily.STORAGE_SYNC,
        ProviderToolRouteFamily.DOCKER_CONTAINER,
    }:
        return RouteSupplyRole.STORAGE_INFRA_CONTROL
    if route.route_family is ProviderToolRouteFamily.LOCAL_API:
        return RouteSupplyRole.TELEMETRY_RESOURCE
    return RouteSupplyRole.VERIFIER_FLOOR_CHECKING


def _inventory_row_role(row: CapabilityClassificationRow) -> RouteSupplyRole:
    if row.surface_family is SurfaceFamily.PUBLICATION_ENDPOINT:
        return RouteSupplyRole.PUBLICATION_EGRESS
    if row.surface_family is SurfaceFamily.MODEL_PROVIDER or row.supplied_evidence_only:
        return RouteSupplyRole.SUPPLIED_EVIDENCE_RECALL
    if row.can_acquire_sources or row.surface_family in {
        SurfaceFamily.SEARCH_PROVIDER,
        SurfaceFamily.BROWSER_SURFACE,
        SurfaceFamily.MCP_TOOL,
    }:
        return RouteSupplyRole.SOURCE_ACQUISITION
    if row.surface_family in {
        SurfaceFamily.AUDIO_ROUTE,
        SurfaceFamily.VIDEO_SURFACE,
        SurfaceFamily.MIDI_SURFACE,
        SurfaceFamily.DEVICE,
        SurfaceFamily.OPERATOR_APERTURE,
    }:
        return RouteSupplyRole.AVSDLC_AUDIO_TOOL
    if row.surface_family in {
        SurfaceFamily.RUNTIME_SERVICE,
        SurfaceFamily.LOCAL_API,
        SurfaceFamily.INFRASTRUCTURE,
        SurfaceFamily.COMPANION_DEVICE,
        SurfaceFamily.DESKTOP_CONTROL,
    }:
        return RouteSupplyRole.TELEMETRY_RESOURCE
    if row.surface_family in {
        SurfaceFamily.STORAGE_SYNC,
        SurfaceFamily.DOCKER_CONTAINER,
        SurfaceFamily.ARCHIVE_PROCESSOR,
        SurfaceFamily.STATE_FILE,
    }:
        return RouteSupplyRole.STORAGE_INFRA_CONTROL
    return RouteSupplyRole.VERIFIER_FLOOR_CHECKING


def _inventory_blocking_reasons(
    row: CapabilityClassificationRow,
    role: RouteSupplyRole,
) -> list[str]:
    reasons: list[str] = []
    if row.availability_state is not AvailabilityState.AVAILABLE:
        reasons.append(f"availability:{row.availability_state.value}")
    if not row.projects_recruitable_capability:
        reasons.append("not_recruitable")
    if role is RouteSupplyRole.SOURCE_ACQUISITION:
        if not row.can_acquire_sources:
            reasons.append("source_acquisition_capability_absent")
        if not row.evidence_refs:
            reasons.append("source_acquisition_evidence_absent")
    if role is RouteSupplyRole.PUBLICATION_EGRESS:
        reasons.append("publication_egress_requires_explicit_authority_receipts")
    return _unique(reasons)


def _provider_tool_blocking_reasons(
    route: ProviderToolRouteHealth,
    role: RouteSupplyRole,
) -> list[str]:
    reasons: list[str] = []
    if route.availability_state.value not in SATISFYING_AVAILABILITY_STATES:
        reasons.append(f"availability:{route.availability_state.value}")
    if route.status.value not in SATISFYING_PROVIDER_HEALTH_STATUSES:
        reasons.append(f"health_status:{route.status.value}")
    if role is RouteSupplyRole.SOURCE_ACQUISITION:
        if not route.source_acquisition_capability:
            reasons.append("source_acquisition_capability_absent")
        if not route.source_acquisition_evidence_refs:
            reasons.append("source_acquisition_evidence_absent")
    if role is RouteSupplyRole.PUBLICATION_EGRESS:
        reasons.append("publication_egress_requires_explicit_authority_receipts")
        if not route.rights_evidence_refs:
            reasons.append("publication_rights_evidence_absent")
        if not (route.privacy_evidence_refs and route.redaction_evidence_refs):
            reasons.append("publication_privacy_redaction_evidence_absent")
        if not route.public_event_refs:
            reasons.append("publication_explicit_receipts_absent")
    return _unique(reasons)


def _provider_route_mismatch_reasons(
    route: ProviderToolRouteHealth,
    inventory_row: CapabilityClassificationRow | None,
) -> list[str]:
    if inventory_row is None:
        return ["classification_row_missing"]

    reasons: list[str] = []
    if route.route_family.value != inventory_row.surface_family.value:
        reasons.append("classification_route_family_mismatch")
    if route.availability_state is not inventory_row.availability_state:
        reasons.append("classification_availability_mismatch")
    if route.source_acquisition_capability != inventory_row.can_acquire_sources:
        reasons.append("classification_source_acquisition_mismatch")
    if inventory_row.supplied_evidence_only and (
        route.supplied_evidence_mode is not SuppliedEvidenceMode.SUPPLIED_EVIDENCE_ONLY
    ):
        reasons.append("classification_supplied_evidence_mismatch")
    if route.public_claim_policy is not inventory_row.public_claim_policy:
        reasons.append("classification_public_claim_policy_mismatch")
    return reasons


def _provider_spend_posture(
    route: PlatformCapabilityRoute,
    quota_evidence: Sequence[str],
    blocked_reasons: Sequence[str],
) -> ProviderSpendPosture:
    if not route.mutability.provider_spend:
        return ProviderSpendPosture.NOT_PROVIDER_GATEWAY
    if route.capacity_pool not in {CapacityPool.API_PAID_SPEND, CapacityPool.BOOTSTRAP_BUDGET}:
        return ProviderSpendPosture.SPEND_BLOCKED
    if blocked_reasons:
        return ProviderSpendPosture.SPEND_BLOCKED
    if not quota_evidence:
        return ProviderSpendPosture.SPEND_REQUIRES_RECEIPT
    return ProviderSpendPosture.SPEND_EVIDENCED


def _outcomes_by_route(
    outcomes: Iterable[ToolProviderOutcomeEnvelope],
) -> dict[str, tuple[ToolProviderOutcomeEnvelope, ...]]:
    grouped: dict[str, list[ToolProviderOutcomeEnvelope]] = {}
    for outcome in outcomes:
        keys = {_route_key(outcome.route_ref), _route_key(outcome.route_id)}
        for key in keys:
            grouped.setdefault(key, []).append(outcome)
    return {key: tuple(value) for key, value in grouped.items()}


def _route_key(route_ref: str) -> str:
    return route_ref.removeprefix("route:")


def _unique(values: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def bridge_policy_summary(facts: Sequence[SdlcRouteSupplyFact]) -> Mapping[str, int]:
    """Return a compact summary for tests and operator receipts."""

    return {
        "total_facts": len(facts),
        "satisfying_facts": sum(fact.can_satisfy_required_demands for fact in facts),
        "held_facts": sum(not fact.can_satisfy_required_demands for fact in facts),
        "source_acquisition_facts": sum(
            fact.role is RouteSupplyRole.SOURCE_ACQUISITION for fact in facts
        ),
        "publication_egress_facts": sum(
            fact.role is RouteSupplyRole.PUBLICATION_EGRESS for fact in facts
        ),
        "provider_gateway_facts": sum(
            fact.role is RouteSupplyRole.PROVIDER_GATEWAY for fact in facts
        ),
    }


# Pydantic invokes model validators through decorator metadata. The diff-aware
# vulture gate scans production code statically, so keep direct references here
# instead of broadening scripts/vulture_whitelist.py for this bridge.
_PYDANTIC_VALIDATOR_ENTRYPOINTS = (
    SdlcRouteDemand._current_world_need_sets_fresh_requirement,
    SdlcRouteSupplyFact._satisfying_fact_obeys_role_gates,
)


__all__ = [
    "CURRENT_WORLD_SOURCE_NEEDS",
    "ProviderSpendPosture",
    "RouteSupplyAssessment",
    "RouteSupplyMatchStatus",
    "RouteSupplyOrigin",
    "RouteSupplyRole",
    "SdlcRouteDemand",
    "SdlcRouteSupplyFact",
    "SdlcToolCapabilityBridgeError",
    "assess_sdlc_route_supply",
    "bridge_policy_summary",
    "project_capability_inventory_supply_facts",
    "project_provider_gateway_supply_facts",
    "project_provider_tool_route_supply_fact",
    "project_provider_tool_route_supply_facts",
    "project_sdlc_route_supply_facts",
]
