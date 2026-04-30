"""Control-surface route health projection for World Capability Surface rows."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.capability_classification_inventory import (
    CapabilityClassificationRow,
    load_capability_classification_inventory,
)
from shared.capability_classification_inventory import (
    SurfaceFamily as ClassificationSurfaceFamily,
)
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
CONTROL_HEALTH_FIXTURES = (
    REPO_ROOT / "config" / "world-surface-health-control-adapter-fixtures.json"
)

REQUIRED_CONTROL_ROUTE_FAMILIES = frozenset(
    {
        "midi_surface",
        "desktop_control",
        "companion_device",
        "private_device_binding",
        "blocked_hardware",
    }
)


class ControlSurfaceHealthError(ValueError):
    """Raised when control-surface health fixtures cannot project safely."""


class ControlRouteFamily(StrEnum):
    MIDI_SURFACE = "midi_surface"
    DESKTOP_CONTROL = "desktop_control"
    COMPANION_DEVICE = "companion_device"
    PRIVATE_DEVICE_BINDING = "private_device_binding"
    BLOCKED_HARDWARE = "blocked_hardware"


class ControlTargetState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    STALE = "stale"
    WRONG_ROUTE = "wrong_route"
    PRIVATE_ONLY = "private_only"
    BLOCKED = "blocked"


class CommandApplicationState(StrEnum):
    ACCEPTED = "accepted"
    NO_OP = "no_op"
    DRY_RUN = "dry_run"
    REJECTED = "rejected"
    NOT_ATTEMPTED = "not_attempted"
    UNKNOWN = "unknown"


class ReadbackPolicy(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    NOT_AVAILABLE = "not_available"
    BLOCKED = "blocked"


class ControlRouteHealth(BaseModel):
    """One control-surface route row before WCS health projection."""

    model_config = ConfigDict(extra="forbid")

    route_id: str = Field(pattern=r"^control\.[a-z0-9_.-]+$")
    display_name: str = Field(min_length=1)
    classification_row_id: str = Field(min_length=1)
    route_family: ControlRouteFamily
    status: HealthStatus
    target_ref: str = Field(min_length=1)
    expected_route_ref: str = Field(min_length=1)
    observed_route_ref: str | None = None
    target_state: ControlTargetState
    command_state: CommandApplicationState
    command_refs: list[str] = Field(default_factory=list)
    readback_policy: ReadbackPolicy
    readback_refs: list[str] = Field(default_factory=list)
    witness_refs: list[str] = Field(default_factory=list)
    grounding_gate_refs: list[str] = Field(default_factory=list)
    evidence_envelope_refs: list[str] = Field(min_length=1)
    freshness: Freshness
    confidence: float = Field(ge=0.0, le=1.0)
    authority_ceiling: AuthorityCeiling
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
    def _validate_control_route_contract(self) -> Self:
        if self.status is not HealthStatus.HEALTHY and not self.blocking_reasons:
            raise ValueError(f"{self.route_id} non-healthy control health needs blockers")
        if self.status is HealthStatus.STALE and self.freshness.state is not FreshnessState.STALE:
            raise ValueError(f"{self.route_id} stale control health requires stale freshness")
        if (
            self.status is HealthStatus.MISSING
            and self.freshness.state is not FreshnessState.MISSING
        ):
            raise ValueError(f"{self.route_id} missing control health requires missing freshness")
        if (
            self.target_state is ControlTargetState.ABSENT
            and self.command_state is CommandApplicationState.ACCEPTED
        ):
            raise ValueError(f"{self.route_id} cannot accept a command for an absent target")
        if self.target_state is ControlTargetState.ABSENT and (
            self.observed_route_ref or self.readback_refs or self.witness_refs
        ):
            raise ValueError(f"{self.route_id} absent targets cannot carry route/readback witness")
        if self.target_state is ControlTargetState.WRONG_ROUTE:
            if not self.observed_route_ref or self.observed_route_ref == self.expected_route_ref:
                raise ValueError(f"{self.route_id} wrong-route rows need a mismatched route ref")
        if self.target_state is ControlTargetState.PRESENT:
            if self.observed_route_ref != self.expected_route_ref:
                raise ValueError(f"{self.route_id} present targets must match expected route")
        if self.command_state is CommandApplicationState.ACCEPTED and not self.command_refs:
            raise ValueError(f"{self.route_id} accepted commands require command_refs")
        if self.readback_policy is ReadbackPolicy.REQUIRED and self.status is HealthStatus.HEALTHY:
            if not self.readback_refs:
                raise ValueError(f"{self.route_id} healthy required-readback rows need readback")
        if self.fallback.mode.value.startswith("no_op") and self.command_state not in {
            CommandApplicationState.NO_OP,
            CommandApplicationState.REJECTED,
            CommandApplicationState.NOT_ATTEMPTED,
        }:
            raise ValueError(f"{self.route_id} no-op fallback must not carry accepted command")
        return self

    def classification_row(self) -> CapabilityClassificationRow:
        """Return the classification inventory row used by this control route."""

        return load_capability_classification_inventory().require_row(self.classification_row_id)

    def satisfies_control_action_witness(self) -> bool:
        """Return true only for accepted, routed, fresh, witnessed control actions."""

        return (
            self.status is HealthStatus.HEALTHY
            and self.target_state is ControlTargetState.PRESENT
            and self.command_state is CommandApplicationState.ACCEPTED
            and self.observed_route_ref == self.expected_route_ref
            and self.freshness.state is FreshnessState.FRESH
            and self.witness_policy is WitnessPolicy.WITNESSED
            and bool(self.witness_refs)
            and (self.readback_policy is not ReadbackPolicy.REQUIRED or bool(self.readback_refs))
            and self.kill_switch_state.state is KillSwitchStatus.CLEAR
        )

    def to_world_surface_health_record(self) -> WorldSurfaceHealthRecord:
        """Project control health into a bounded WCS health row."""

        row = self.classification_row()
        privacy_state = self._privacy_state(row)
        private_only = (
            privacy_state is PrivacyState.PRIVATE_ONLY
            or self.public_private_posture is PublicPrivatePosture.PRIVATE_ONLY
        )
        dry_run_allowed = (
            self.public_private_posture is PublicPrivatePosture.DRY_RUN
            or self.command_state is CommandApplicationState.DRY_RUN
        )
        return WorldSurfaceHealthRecord(
            surface_id=f"{self.route_id}.health",
            surface_family=SurfaceFamily.CONTROL,
            checked_at=self.freshness.checked_at,
            status=self.status,
            health_dimensions=self._health_dimensions(row),
            source_refs=[row.evidence_ref, "config:world-surface-health-control-adapter-fixtures"],
            producer_refs=[row.producer],
            consumer_refs=row.consumer_refs,
            route_refs=[self.expected_route_ref],
            substrate_refs=row.substrate_refs,
            capability_refs=[row.surface_id, self.classification_row_id],
            evidence_envelope_refs=self.evidence_envelope_refs,
            outcome_envelope_refs=[],
            witness_refs=self.witness_refs,
            grounding_gate_refs=self.grounding_gate_refs,
            public_event_refs=[],
            freshness=self.freshness,
            confidence=self.confidence,
            authority_ceiling=self.authority_ceiling,
            privacy_state=privacy_state,
            rights_state=self._rights_state(row),
            public_private_posture=self.public_private_posture,
            public_claim_allowed=False,
            private_only=private_only,
            dry_run_allowed=dry_run_allowed,
            monetization_allowed=False,
            blocking_reasons=self.blocking_reasons,
            warnings=[
                *self.warnings,
                "control_route_health_does_not_grant_public_or_success_authority",
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

    def _health_dimensions(self, row: CapabilityClassificationRow) -> list[HealthDimension]:
        return [
            self._source_freshness_dimension(),
            self._dimension(
                HealthDimensionId.PRODUCER_EXISTS,
                self._target_presence_dimension_state(),
                True,
                [row.producer],
                "Control producer is named from the classification inventory.",
            ),
            self._dimension(
                HealthDimensionId.CONSUMER_EXISTS,
                self._target_presence_dimension_state(),
                True,
                row.consumer_refs,
                "Control consumers are explicit and do not imply command success.",
            ),
            self._dimension(
                HealthDimensionId.ROUTE_BINDING,
                self._route_binding_dimension_state(),
                True,
                [ref for ref in [self.expected_route_ref, self.observed_route_ref] if ref],
                "Expected route and observed route must match before action readiness.",
            ),
            self._dimension(
                HealthDimensionId.EXECUTION_WITNESS,
                self._execution_dimension_state(),
                True,
                self.command_refs,
                "Accepted command is visible but insufficient without target/readback witness.",
            ),
            self._dimension(
                HealthDimensionId.WORLD_WITNESS,
                self._world_witness_dimension_state(),
                True,
                self.readback_refs,
                "Readback is the control-world witness; command logs alone do not satisfy it.",
            ),
            self._dimension(
                HealthDimensionId.RENDERABILITY,
                HealthDimensionState.NOT_APPLICABLE,
                False,
                [],
                "Control route health does not assert renderability.",
            ),
            self._dimension(
                HealthDimensionId.NO_LEAK,
                self._no_leak_dimension_state(),
                True,
                [f"privacy:{row.surface_id}:{self.public_private_posture.value}"],
                "Private/control posture is explicit and cannot become public by omission.",
            ),
            self._dimension(
                HealthDimensionId.EGRESS_PUBLIC,
                HealthDimensionState.MISSING,
                True,
                [],
                "Control health cannot prove public egress.",
            ),
            self._dimension(
                HealthDimensionId.PUBLIC_EVENT_POLICY,
                HealthDimensionState.MISSING,
                True,
                [],
                "Control health cannot attach a public event policy.",
            ),
            self._dimension(
                HealthDimensionId.RIGHTS_PROVENANCE,
                HealthDimensionState.PASS,
                True,
                [f"rights:{row.surface_id}"],
                "Rights posture is inherited from the classification inventory.",
            ),
            self._dimension(
                HealthDimensionId.PRIVACY_CONSENT,
                self._privacy_dimension_state(row),
                True,
                [f"privacy:{row.surface_id}:{row.privacy_class.value}"],
                "Privacy/consent posture is inherited from the classification inventory.",
            ),
            self._dimension(
                HealthDimensionId.GROUNDING_GATE,
                self._grounding_gate_dimension_state(),
                True,
                self.grounding_gate_refs,
                "Grounding gate refs are separate from route health.",
            ),
            self._dimension(
                HealthDimensionId.CLAIM_AUTHORITY,
                self._claim_authority_dimension_state(),
                True,
                [f"authority:{self.authority_ceiling.value}", self.classification_row_id],
                "Authority ceiling is explicit; route health grants no public claim.",
            ),
            self._dimension(
                HealthDimensionId.MONETIZATION_READINESS,
                HealthDimensionState.NOT_APPLICABLE,
                False,
                [],
                "Control health carries no monetization permission.",
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
                "Kill-switch state is explicit.",
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
            "Control health freshness is bounded by route/readback witness TTL.",
        )

    def _target_presence_dimension_state(self) -> HealthDimensionState:
        if self.target_state is ControlTargetState.ABSENT:
            return HealthDimensionState.MISSING
        if self.target_state is ControlTargetState.STALE:
            return HealthDimensionState.STALE
        if self.target_state in {ControlTargetState.BLOCKED, ControlTargetState.WRONG_ROUTE}:
            return HealthDimensionState.FAIL
        return HealthDimensionState.PASS

    def _route_binding_dimension_state(self) -> HealthDimensionState:
        if self.target_state is ControlTargetState.ABSENT:
            return HealthDimensionState.MISSING
        if self.target_state is ControlTargetState.STALE:
            return HealthDimensionState.STALE
        if self.observed_route_ref != self.expected_route_ref:
            return HealthDimensionState.FAIL
        return HealthDimensionState.PASS

    def _execution_dimension_state(self) -> HealthDimensionState:
        if self.command_state is CommandApplicationState.ACCEPTED:
            return HealthDimensionState.PASS
        if self.command_state is CommandApplicationState.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        if self.command_state is CommandApplicationState.NOT_ATTEMPTED:
            return HealthDimensionState.MISSING
        return HealthDimensionState.BLOCKED

    def _world_witness_dimension_state(self) -> HealthDimensionState:
        if self.readback_policy is ReadbackPolicy.NOT_AVAILABLE:
            return HealthDimensionState.NOT_APPLICABLE
        if self.readback_policy is ReadbackPolicy.BLOCKED:
            return HealthDimensionState.BLOCKED
        if self.readback_refs:
            return HealthDimensionState.PASS
        if self.target_state is ControlTargetState.STALE:
            return HealthDimensionState.STALE
        return HealthDimensionState.MISSING

    def _no_leak_dimension_state(self) -> HealthDimensionState:
        if self.target_state in {ControlTargetState.WRONG_ROUTE, ControlTargetState.BLOCKED}:
            return HealthDimensionState.FAIL
        return HealthDimensionState.PASS

    def _privacy_dimension_state(self, row: CapabilityClassificationRow) -> HealthDimensionState:
        if self._privacy_state(row) is PrivacyState.BLOCKED:
            return HealthDimensionState.FAIL
        if self._privacy_state(row) is PrivacyState.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        return HealthDimensionState.PASS

    def _grounding_gate_dimension_state(self) -> HealthDimensionState:
        return (
            HealthDimensionState.PASS if self.grounding_gate_refs else HealthDimensionState.MISSING
        )

    def _claim_authority_dimension_state(self) -> HealthDimensionState:
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

    def _privacy_state(self, row: CapabilityClassificationRow) -> PrivacyState:
        if self.target_state is ControlTargetState.BLOCKED:
            return PrivacyState.BLOCKED
        if self.public_private_posture is PublicPrivatePosture.PRIVATE_ONLY:
            return PrivacyState.PRIVATE_ONLY
        if self.public_private_posture is PublicPrivatePosture.DRY_RUN:
            return PrivacyState.DRY_RUN
        if row.privacy_class.value in {"private", "operator_visible", "person_adjacent"}:
            return PrivacyState.PRIVATE_ONLY
        return PrivacyState.PUBLIC_SAFE

    def _rights_state(self, row: CapabilityClassificationRow) -> RightsState:
        if row.rights_class.value == "blocked":
            return RightsState.BLOCKED
        if self._privacy_state(row) is PrivacyState.PRIVATE_ONLY:
            return RightsState.PRIVATE_ONLY
        return RightsState.PUBLIC_CLEAR


class ControlRouteHealthFixtureSet(BaseModel):
    """Fixture set for control-surface route health rows."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: Literal["schemas/world-surface-health-control-adapter.schema.json"]
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    required_route_families: list[ControlRouteFamily] = Field(min_length=1)
    routes: list[ControlRouteHealth] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_fixture_contract(self) -> Self:
        route_ids = [route.route_id for route in self.routes]
        duplicate_route_ids = sorted(
            {route_id for route_id in route_ids if route_ids.count(route_id) > 1}
        )
        if duplicate_route_ids:
            raise ValueError("duplicate control route ids: " + ", ".join(duplicate_route_ids))

        family_values = {family.value for family in self.required_route_families}
        missing_families = REQUIRED_CONTROL_ROUTE_FAMILIES - family_values
        if missing_families:
            raise ValueError(
                "missing control route families: " + ", ".join(sorted(missing_families))
            )
        record_families = {route.route_family.value for route in self.routes}
        missing_record_families = REQUIRED_CONTROL_ROUTE_FAMILIES - record_families
        if missing_record_families:
            raise ValueError(
                "control routes do not cover families: "
                + ", ".join(sorted(missing_record_families))
            )

        if self.fail_closed_policy != {
            "target_absent_satisfies_action": False,
            "wrong_route_satisfies_action": False,
            "stale_binding_satisfies_action": False,
            "no_op_satisfies_success": False,
            "private_control_allows_public_claim": False,
            "route_health_grants_public_claim": False,
            "monetization_allowed_from_control_health": False,
        }:
            raise ValueError("control route fail_closed_policy must pin gates false")

        self._validate_against_capability_inventory()
        return self

    def _validate_against_capability_inventory(self) -> None:
        inventory = load_capability_classification_inventory()
        for route in self.routes:
            row = inventory.require_row(route.classification_row_id)
            _validate_route_matches_inventory(route, row)

    def to_world_surface_health_records(self) -> list[WorldSurfaceHealthRecord]:
        """Project every control route into WCS health records."""

        return [route.to_world_surface_health_record() for route in self.routes]

    def routes_by_id(self) -> dict[str, ControlRouteHealth]:
        """Return control fixture rows keyed by route id."""

        return {route.route_id: route for route in self.routes}


def _validate_route_matches_inventory(
    route: ControlRouteHealth,
    row: CapabilityClassificationRow,
) -> None:
    allowed_families = {
        ControlRouteFamily.MIDI_SURFACE: {ClassificationSurfaceFamily.MIDI_SURFACE},
        ControlRouteFamily.DESKTOP_CONTROL: {ClassificationSurfaceFamily.DESKTOP_CONTROL},
        ControlRouteFamily.COMPANION_DEVICE: {ClassificationSurfaceFamily.COMPANION_DEVICE},
        ControlRouteFamily.PRIVATE_DEVICE_BINDING: {ClassificationSurfaceFamily.DEVICE},
        ControlRouteFamily.BLOCKED_HARDWARE: {
            ClassificationSurfaceFamily.MIDI_SURFACE,
            ClassificationSurfaceFamily.DEVICE,
        },
    }
    if row.surface_family not in allowed_families[route.route_family]:
        raise ValueError(f"{route.route_id} route_family does not match classification row")
    if route.target_ref != row.concrete_interface:
        raise ValueError(f"{route.route_id} target_ref must match inventory concrete_interface")
    if route.authority_ceiling.value != row.claim_authority_ceiling.value:
        raise ValueError(f"{route.route_id} authority_ceiling does not match classification row")
    if route.expected_route_ref != f"route:{row.concrete_interface}":
        raise ValueError(f"{route.route_id} expected_route_ref must derive from inventory route")
    if row.evidence_ref not in route.evidence_envelope_refs:
        raise ValueError(f"{route.route_id} evidence_envelope_refs must include evidence_ref")


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ControlSurfaceHealthError(f"{path} did not contain a JSON object")
    return payload


def load_control_health_fixtures(
    path: Path = CONTROL_HEALTH_FIXTURES,
) -> ControlRouteHealthFixtureSet:
    """Load control-surface health fixtures, failing closed on malformed data."""

    try:
        return ControlRouteHealthFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ControlSurfaceHealthError(
            f"invalid control health fixtures at {path}: {exc}"
        ) from exc


def project_control_health_records(
    path: Path = CONTROL_HEALTH_FIXTURES,
) -> list[WorldSurfaceHealthRecord]:
    """Load and project control-surface route health fixtures into WCS rows."""

    return load_control_health_fixtures(path).to_world_surface_health_records()


__all__ = [
    "CONTROL_HEALTH_FIXTURES",
    "REQUIRED_CONTROL_ROUTE_FAMILIES",
    "CommandApplicationState",
    "ControlRouteFamily",
    "ControlRouteHealth",
    "ControlRouteHealthFixtureSet",
    "ControlSurfaceHealthError",
    "ControlTargetState",
    "ReadbackPolicy",
    "load_control_health_fixtures",
    "project_control_health_records",
]
