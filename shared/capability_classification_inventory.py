"""System-wide capability classification seed inventory.

This module is the census layer between runtime surfaces and semantic
recruitment.  It does not run probes and it does not mutate routing; it admits
seed rows through ``SemanticRecruitmentRow`` so downstream WCS/director slices
can reason about available, stale, blocked, and decommissioned surfaces without
inventing a parallel ontology.
"""

from __future__ import annotations

import ast
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Self, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.semantic_recruitment import (
    AuthorityCeiling,
    CapabilityProjection,
    ClaimType,
    ConsentLabel,
    ContentRisk,
    Direction,
    DispatchContract,
    DomainTag,
    EffectType,
    FamilyTag,
    LatencyClass,
    LifecycleState,
    Medium,
    MonetizationRisk,
    OutcomeLearningPolicy,
    PrivacyLabel,
    Realm,
    RelationPredicate,
    RightsLabel,
    SemanticDescription,
    SemanticKind,
    SemanticLevel,
    SemanticRecruitmentRow,
    SemanticRelation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_CLASSIFICATION_INVENTORY = (
    REPO_ROOT / "config" / "capability-classification-inventory.json"
)


class CapabilityClassificationError(ValueError):
    """Raised when capability classification inventory rows fail closed."""


class SurfaceFamily(StrEnum):
    AFFORDANCE_RECORD = "affordance_record"
    TOOL_SCHEMA = "tool_schema"
    MCP_TOOL = "mcp_tool"
    BROWSER_SURFACE = "browser_surface"
    FILE = "file"
    OBSIDIAN_NOTE = "obsidian_note"
    COMMAND_OUTPUT = "command_output"
    RUNTIME_SERVICE = "runtime_service"
    STATE_FILE = "state_file"
    DEVICE = "device"
    AUDIO_ROUTE = "audio_route"
    VIDEO_SURFACE = "video_surface"
    MIDI_SURFACE = "midi_surface"
    DESKTOP_CONTROL = "desktop_control"
    OPERATOR_APERTURE = "operator_aperture"
    COMPANION_DEVICE = "companion_device"
    LOCAL_API = "local_api"
    DOCKER_CONTAINER = "docker_container"
    MODEL_PROVIDER = "model_provider"
    SEARCH_PROVIDER = "search_provider"
    PUBLICATION_ENDPOINT = "publication_endpoint"
    ARCHIVE_PROCESSOR = "archive_processor"
    STORAGE_SYNC = "storage_sync"
    PUBLIC_EVENT = "public_event"
    GOVERNANCE_SURFACE = "governance_surface"
    INFRASTRUCTURE = "infrastructure"


class AvailabilityState(StrEnum):
    AVAILABLE = "available"
    PRIVATE_ONLY = "private_only"
    STALE = "stale"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"
    DECOMMISSIONED = "decommissioned"


class AvailabilityProbeKind(StrEnum):
    STATIC_RECORD = "static_record"
    IMPORT_SYMBOL = "import_symbol"
    STATE_MTIME = "state_mtime"
    DEVICE_PRESENT = "device_present"
    ROUTE_WITNESS = "route_witness"
    FRAME_WITNESS = "frame_witness"
    HEALTH_ENDPOINT = "health_endpoint"
    CONTAINER_HEALTH = "container_health"
    REMOTE_QUERY = "remote_query"
    OPERATOR_GATE = "operator_gate"
    DECOMMISSION_EVIDENCE = "decommission_evidence"


class PublicClaimPolicy(StrEnum):
    NO_PUBLIC_CLAIM = "no_public_claim"
    EVIDENCE_BOUND_ONLY = "evidence_bound_only"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class KillSwitchBehavior(StrEnum):
    HARD_BLOCK = "hard_block"
    PRIVATE_ONLY = "private_only"
    STALE_BADGE = "stale_badge"
    DEGRADE_STATUS = "degrade_status"
    REPLACEMENT_ONLY = "replacement_only"


class FallbackPolicy(StrEnum):
    FAIL_CLOSED = "fail_closed"
    USE_REPLACEMENT_ROW = "use_replacement_row"
    PRIVATE_MONITOR_ONLY = "private_monitor_only"
    STALE_CONTEXT_ONLY = "stale_context_only"
    SUPPLIED_EVIDENCE_ONLY = "supplied_evidence_only"


class MissingRecordAction(StrEnum):
    NONE = "none"
    ADAPT_EXISTING_RECORD = "adapt_existing_record"
    ADD_TOOL_AFFORDANCE = "add_tool_affordance"
    KEEP_BLOCKED = "keep_blocked"
    REPLACED_BY_ROW = "replaced_by_row"


class AvailabilityProbe(BaseModel):
    """Deterministic witness contract for one classification row."""

    model_config = ConfigDict(extra="forbid")

    probe_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    kind: AvailabilityProbeKind
    expected_state: AvailabilityState
    witness_ref: str = Field(min_length=1)
    stale_after_s: int | None = Field(default=None, ge=0)
    notes: str = ""

    @model_validator(mode="after")
    def _freshness_probe_has_ttl(self) -> Self:
        if self.kind in {AvailabilityProbeKind.STATE_MTIME, AvailabilityProbeKind.REMOTE_QUERY}:
            if self.stale_after_s is None:
                raise ValueError("state and remote freshness probes require stale_after_s")
        return self


class CapabilityClassificationRow(SemanticRecruitmentRow):
    """A concrete system surface admitted through the semantic ontology."""

    freshness_ttl_s: int | None = Field(ge=0)
    classification_id: str = Field(pattern=r"^classification\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    surface_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    surface_family: SurfaceFamily
    gibson_verb: str = Field(min_length=1)
    semantic_description: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    consumer_refs: list[str] = Field(min_length=1)
    concrete_interface: str = Field(min_length=1)
    availability_probe: AvailabilityProbe
    availability_state: AvailabilityState
    state_ref: str | None = None
    evidence_ref: str = Field(min_length=1)
    privacy_class: PrivacyLabel
    rights_class: RightsLabel
    consent_policy: ConsentLabel
    claim_authority_ceiling: AuthorityCeiling
    can_acquire_sources: bool = False
    supplied_evidence_only: bool = False
    public_claim_policy: PublicClaimPolicy
    kill_switch_behavior: KillSwitchBehavior
    fallback_policy: FallbackPolicy
    degraded_reason: str | None = None
    witness_requirements: list[str] = Field(min_length=1)
    recruitment_family: str = Field(min_length=1)
    existing_record_refs: list[str] = Field(default_factory=list)
    missing_record_action: MissingRecordAction

    @model_validator(mode="after")
    def _validate_classification_contract(self) -> Self:
        if self.semantic_description != self.primary_description:
            raise ValueError("semantic_description must mirror the primary semantic row text")
        if self.gibson_verb.lower() != self.primary_description.split()[0].lower():
            raise ValueError("gibson_verb must mirror the primary semantic row verb")
        if self.concrete_interface not in self.concrete_interfaces:
            raise ValueError("concrete_interface must be present in semantic concrete_interfaces")
        if self.state_ref and self.state_ref not in self.state_refs:
            raise ValueError("state_ref must be present in semantic state_refs")
        if self.evidence_ref not in self.evidence_refs:
            raise ValueError("evidence_ref must be present in semantic evidence_refs")
        if self.availability_probe.expected_state is not self.availability_state:
            raise ValueError("availability_probe expected_state must match availability_state")
        if self.freshness_ttl_s != self.availability_probe.stale_after_s:
            raise ValueError("freshness_ttl_s must mirror the availability probe stale_after_s")
        if self.privacy_class is not self.privacy_label:
            raise ValueError("privacy_class must mirror semantic privacy_label")
        if self.rights_class is not self.rights_label:
            raise ValueError("rights_class must mirror semantic rights_label")
        if self.consent_policy is not self.consent_label:
            raise ValueError("consent_policy must mirror semantic consent_label")
        if self.claim_authority_ceiling is not self.authority_ceiling:
            raise ValueError("claim_authority_ceiling must mirror semantic authority_ceiling")
        if self.can_acquire_sources and self.supplied_evidence_only:
            raise ValueError("source acquisition and supplied-evidence-only are mutually exclusive")
        if self.public_claim_policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED:
            if ClaimType.PUBLIC_CLAIM not in self.claim_types_allowed:
                raise ValueError("public claim rows must allow public_claim")
        else:
            if ClaimType.PUBLIC_CLAIM in self.claim_types_allowed:
                raise ValueError("non-public rows must not allow public_claim")
        if self.availability_state in {
            AvailabilityState.BLOCKED,
            AvailabilityState.UNAVAILABLE,
            AvailabilityState.DECOMMISSIONED,
            AvailabilityState.STALE,
        }:
            if not self.degraded_reason:
                raise ValueError(
                    "blocked, unavailable, stale, and decommissioned rows need a reason"
                )
            if self.projects_recruitable_capability:
                raise ValueError("unavailable rows cannot project recruitable capabilities")
        if self.recruitable and not self.witness_contract_id:
            raise ValueError("recruitable classification rows require a witness contract")
        if self.witness_contract_id and self.witness_contract_id not in self.witness_requirements:
            raise ValueError("witness_requirements must include witness_contract_id")
        if not any(tag.family == self.recruitment_family for tag in self.family_tags):
            raise ValueError("recruitment_family must be present in semantic family tags")
        return self

    def director_snapshot_payload(self) -> dict[str, Any]:
        """Return the compact read model used by WCS/director snapshot fixtures."""

        return {
            "classification_id": self.classification_id,
            "row_id": self.row_id,
            "surface_family": self.surface_family.value,
            "display_name": self.display_name,
            "availability_state": self.availability_state.value,
            "realm": self.realm.value,
            "direction": self.direction.value,
            "recruitable": self.projects_recruitable_capability,
            "public_claim_policy": self.public_claim_policy.value,
            "authority_ceiling": self.authority_ceiling.value,
            "freshness_ttl_s": self.freshness_ttl_s,
            "evidence_ref": self.evidence_ref,
            "witness_requirements": list(self.witness_requirements),
            "fallback_policy": self.fallback_policy.value,
            "replacement_row_id": self.replacement_row_id,
        }


class CapabilityClassificationInventory(BaseModel):
    """Seed bundle for the first system-wide semantic classification sweep."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = Field(default=None, alias="$schema")
    schema_version: int = Field(default=1, ge=1)
    generated_from: list[str] = Field(min_length=1)
    rows: list[CapabilityClassificationRow] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_inventory_contract(self) -> Self:
        row_ids = [row.row_id for row in self.rows]
        duplicate_row_ids = sorted({row_id for row_id in row_ids if row_ids.count(row_id) > 1})
        if duplicate_row_ids:
            raise ValueError("duplicate semantic row ids: " + ", ".join(duplicate_row_ids))

        classification_ids = [row.classification_id for row in self.rows]
        duplicate_classification_ids = sorted(
            {
                classification_id
                for classification_id in classification_ids
                if classification_ids.count(classification_id) > 1
            }
        )
        if duplicate_classification_ids:
            raise ValueError(
                "duplicate classification ids: " + ", ".join(duplicate_classification_ids)
            )

        row_id_set = set(row_ids)
        missing_replacements = sorted(
            row.replacement_row_id
            for row in self.rows
            if row.replacement_row_id and row.replacement_row_id not in row_id_set
        )
        if missing_replacements:
            raise ValueError(
                "replacement rows missing from inventory: " + ", ".join(missing_replacements)
            )

        family_values = {row.surface_family for row in self.rows}
        missing_families = REQUIRED_SEED_FAMILIES - family_values
        if missing_families:
            missing = ", ".join(sorted(family.value for family in missing_families))
            raise ValueError(f"inventory missing required seed families: {missing}")

        return self

    def by_id(self) -> dict[str, CapabilityClassificationRow]:
        """Return classification rows keyed by semantic row id."""

        return {row.row_id: row for row in self.rows}

    def require_row(self, row_id: str) -> CapabilityClassificationRow:
        """Return one row or raise a fail-closed lookup error."""

        row = self.by_id().get(row_id)
        if row is None:
            raise KeyError(f"unknown capability classification row: {row_id}")
        return row

    def rows_for_family(self, family: SurfaceFamily) -> list[CapabilityClassificationRow]:
        """Return rows in one surface family."""

        return [row for row in self.rows if row.surface_family is family]

    def rows_for_availability(
        self, availability_state: AvailabilityState
    ) -> list[CapabilityClassificationRow]:
        """Return rows with one availability posture."""

        return [row for row in self.rows if row.availability_state is availability_state]

    def available_rows(self) -> list[CapabilityClassificationRow]:
        """Return rows that may project into recruitable capability records."""

        return [row for row in self.rows if row.projects_recruitable_capability]

    def director_snapshot_rows(self) -> list[dict[str, Any]]:
        """Return a deterministic compact snapshot for director/WCS consumers."""

        return [row.director_snapshot_payload() for row in self.rows]

    def wcs_projection_payloads(self) -> dict[str, dict[str, Any]]:
        """Return Qdrant-compatible payloads for currently recruitable rows."""

        return {row.row_id: row.to_qdrant_payload() for row in self.available_rows()}


REQUIRED_SEED_FAMILIES: frozenset[SurfaceFamily] = frozenset(SurfaceFamily)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CapabilityClassificationError(f"{path} did not contain a JSON object")
    return payload


def load_capability_classification_inventory(
    path: Path = CAPABILITY_CLASSIFICATION_INVENTORY,
) -> CapabilityClassificationInventory:
    """Load classification inventory fixtures, failing closed on malformed data."""

    try:
        return CapabilityClassificationInventory.model_validate(_load_json_object(path))
    except (OSError, ValidationError) as exc:
        raise CapabilityClassificationError(
            f"invalid capability classification inventory: {path}"
        ) from exc


def capability_classification_rows_by_id(
    path: Path = CAPABILITY_CLASSIFICATION_INVENTORY,
) -> dict[str, CapabilityClassificationRow]:
    """Return inventory rows keyed by semantic row id."""

    return load_capability_classification_inventory(path).by_id()


def daimonion_exposed_tool_schema_names() -> set[str]:
    """Return tool names exposed to daimonion conversations."""

    standard = _function_schema_names_from_module(
        REPO_ROOT / "agents" / "hapax_daimonion" / "tools.py", "TOOL_SCHEMAS"
    )
    desktop = _function_schema_names_from_module(
        REPO_ROOT / "agents" / "hapax_daimonion" / "desktop_tools.py", "DESKTOP_TOOL_SCHEMAS"
    )
    phone = _phone_tool_definition_names(
        REPO_ROOT / "agents" / "hapax_daimonion" / "phone_tools.py"
    ) - {"send_sms"}
    return standard | desktop | phone


def daimonion_tool_affordance_names() -> set[str]:
    """Return the daimonion tool affordance names indexed for recruitment."""

    from agents.hapax_daimonion.tool_affordances import TOOL_AFFORDANCES

    return {name for name, _description in TOOL_AFFORDANCES}


def validate_daimonion_tool_affordance_parity() -> None:
    """Fail closed if exposed daimonion schemas drift from recruitment affordances."""

    schemas = daimonion_exposed_tool_schema_names()
    affordances = daimonion_tool_affordance_names()
    missing = sorted(schemas - affordances)
    extra = sorted(affordances - schemas)
    if missing or extra:
        message = []
        if missing:
            message.append("missing affordances: " + ", ".join(missing))
        if extra:
            message.append("extra affordances: " + ", ".join(extra))
        raise CapabilityClassificationError("; ".join(message))


def _function_schema_names_from_module(path: Path, list_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    schema_vars: dict[str, str] = {}

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        target = node.targets[0].id
        if not isinstance(node.value, ast.Call):
            continue
        if not _call_name_matches(node.value.func, "FunctionSchema"):
            continue
        for keyword in node.value.keywords:
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    schema_vars[target] = keyword.value.value

    for node in tree.body:
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
        if not isinstance(target, ast.Name) or target.id != list_name:
            continue
        value = node.value
        if not isinstance(value, ast.List):
            raise CapabilityClassificationError(f"{path}:{list_name} is not a static list")
        names: set[str] = set()
        for item in value.elts:
            if not isinstance(item, ast.Name):
                raise CapabilityClassificationError(
                    f"{path}:{list_name} contains non-name schema entry"
                )
            try:
                names.add(schema_vars[item.id])
            except KeyError as exc:
                raise CapabilityClassificationError(
                    f"{path}:{list_name} references unknown schema variable {item.id}"
                ) from exc
        return names

    raise CapabilityClassificationError(f"{path} does not define {list_name}")


def _call_name_matches(func: ast.expr, name: str) -> bool:
    if isinstance(func, ast.Name):
        return func.id == name
    if isinstance(func, ast.Attribute):
        return func.attr == name
    return False


def _phone_tool_definition_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "PHONE_TOOL_DEFINITIONS"
            for target in node.targets
        ):
            continue
        definitions = ast.literal_eval(node.value)
        return {
            definition["function"]["name"]
            for definition in definitions
            if definition["type"] == "function"
        }
    raise CapabilityClassificationError(f"{path} does not define PHONE_TOOL_DEFINITIONS")


def build_seed_inventory() -> CapabilityClassificationInventory:
    """Build the canonical first sweep fixture from existing registry evidence."""

    from agents.hapax_daimonion.tool_affordances import TOOL_AFFORDANCES
    from shared.affordance_registry import ALL_AFFORDANCES
    from shared.compositional_affordances import COMPOSITIONAL_CAPABILITIES
    from shared.voice_tier import TIER_NAMES, TIER_RISK_REASONS, VoiceTier, tier_capability_record

    affordance_record = _require_record(ALL_AFFORDANCES, "env.weather_conditions")
    compositional_record = _require_record(
        COMPOSITIONAL_CAPABILITIES, "cam.hero.overhead.hardware-active"
    )
    tool_descriptions = dict(TOOL_AFFORDANCES)

    rows = [
        _capability_record_row(
            record=affordance_record,
            classification_id="classification.affordance.env.weather_conditions",
            row_id="capability.affordance.env_weather_conditions",
            surface_id="affordance:env.weather_conditions",
            display_name="Weather conditions affordance",
            surface_family=SurfaceFamily.AFFORDANCE_RECORD,
            realm=Realm.HYBRID,
            direction=Direction.OBSERVE,
            effect_type=EffectType.SENSE,
            medium=Medium.DATA,
            producer="shared.affordance_registry.ALL_AFFORDANCES",
            consumer_refs=["consumer:affordance_pipeline"],
            concrete_interface="python:shared.affordance_registry.ALL_AFFORDANCES",
            availability_probe=AvailabilityProbe(
                probe_id="probe.affordance.env_weather_conditions",
                kind=AvailabilityProbeKind.IMPORT_SYMBOL,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="import:shared.affordance_registry.ALL_AFFORDANCES",
                stale_after_s=900,
            ),
            privacy_class=PrivacyLabel.PUBLIC_SAFE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="static_affordance",
            public_claim_policy=PublicClaimPolicy.EVIDENCE_BOUND_ONLY,
            can_acquire_sources=True,
            existing_record_refs=["capability_record:env.weather_conditions"],
            witness_contract_id="witness.affordance.env_weather_conditions.imported",
            projection_name="env.weather_conditions",
            evidence_ref="repo:shared.affordance_registry.ALL_AFFORDANCES",
        ),
        _capability_record_row(
            record=compositional_record,
            classification_id="classification.compositional.cam_hero_overhead_hardware_active",
            row_id="capability.compositional.cam_hero_overhead_hardware_active",
            surface_id="affordance:cam.hero.overhead.hardware-active",
            display_name="Overhead hardware hero camera move",
            surface_family=SurfaceFamily.OPERATOR_APERTURE,
            realm=Realm.LOCAL,
            direction=Direction.EXPRESS,
            effect_type=EffectType.COMPOSE,
            medium=Medium.VISUAL,
            semantic_description=(
                "Compose the overhead hardware view when studio attention belongs to physical "
                "instruments and workspace activity."
            ),
            producer="shared.compositional_affordances.COMPOSITIONAL_CAPABILITIES",
            consumer_refs=["consumer:studio_compositor.compositional_consumer"],
            concrete_interface="python:shared.compositional_affordances.COMPOSITIONAL_CAPABILITIES",
            availability_probe=AvailabilityProbe(
                probe_id="probe.compositional.cam_hero_overhead_hardware_active",
                kind=AvailabilityProbeKind.IMPORT_SYMBOL,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="import:shared.compositional_affordances.COMPOSITIONAL_CAPABILITIES",
                stale_after_s=60,
            ),
            privacy_class=PrivacyLabel.PUBLIC_BROADCAST,
            consent_policy=ConsentLabel.PUBLIC_BROADCAST,
            recruitment_family="compositional_affordance",
            public_claim_policy=PublicClaimPolicy.PUBLIC_GATE_REQUIRED,
            existing_record_refs=["capability_record:cam.hero.overhead.hardware-active"],
            witness_contract_id="witness.video.overhead_hero_frame",
            projection_name="compositor.cam_hero_overhead_hardware_active",
            evidence_ref="repo:shared.compositional_affordances.COMPOSITIONAL_CAPABILITIES",
        ),
        _row(
            classification_id="classification.tool.query_person_details",
            row_id="capability.tool.query_person_details",
            surface_id="tool_schema:query_person_details",
            display_name="Person detail scene query",
            surface_family=SurfaceFamily.TOOL_SCHEMA,
            realm=Realm.LOCAL,
            direction=Direction.OBSERVE,
            effect_type=EffectType.SENSE,
            medium=Medium.VISUAL,
            semantic_description=tool_descriptions["query_person_details"],
            producer="agents.hapax_daimonion.tools.TOOL_SCHEMAS",
            consumer_refs=["consumer:hapax_daimonion.tool_recruitment"],
            concrete_interface="function_schema:query_person_details",
            availability_probe=AvailabilityProbe(
                probe_id="probe.tool.query_person_details",
                kind=AvailabilityProbeKind.IMPORT_SYMBOL,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="import:agents.hapax_daimonion.tools.TOOL_SCHEMAS",
                stale_after_s=5,
            ),
            privacy_class=PrivacyLabel.PERSON_ADJACENT,
            consent_policy=ConsentLabel.PERSON_ADJACENT,
            recruitment_family="tool_schema",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            kill_switch_behavior=KillSwitchBehavior.PRIVATE_ONLY,
            fallback_policy=FallbackPolicy.FAIL_CLOSED,
            existing_record_refs=["tool_affordance:query_person_details"],
            missing_record_action=MissingRecordAction.ADD_TOOL_AFFORDANCE,
            witness_contract_id="witness.tool.query_person_details.scene_snapshot",
            projection_name="tool.query_person_details",
            consent_person_id="guest",
            consent_data_category="presence",
        ),
        _row(
            classification_id="classification.tool.query_object_motion",
            row_id="capability.tool.query_object_motion",
            surface_id="tool_schema:query_object_motion",
            display_name="Object motion scene query",
            surface_family=SurfaceFamily.TOOL_SCHEMA,
            realm=Realm.LOCAL,
            direction=Direction.OBSERVE,
            effect_type=EffectType.SENSE,
            medium=Medium.VISUAL,
            semantic_description=tool_descriptions["query_object_motion"],
            producer="agents.hapax_daimonion.tools.TOOL_SCHEMAS",
            consumer_refs=["consumer:hapax_daimonion.tool_recruitment"],
            concrete_interface="function_schema:query_object_motion",
            availability_probe=AvailabilityProbe(
                probe_id="probe.tool.query_object_motion",
                kind=AvailabilityProbeKind.IMPORT_SYMBOL,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="import:agents.hapax_daimonion.tools.TOOL_SCHEMAS",
                stale_after_s=5,
            ),
            privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="tool_schema",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            kill_switch_behavior=KillSwitchBehavior.PRIVATE_ONLY,
            fallback_policy=FallbackPolicy.FAIL_CLOSED,
            existing_record_refs=["tool_affordance:query_object_motion"],
            missing_record_action=MissingRecordAction.ADD_TOOL_AFFORDANCE,
            witness_contract_id="witness.tool.query_object_motion.scene_snapshot",
            projection_name="tool.query_object_motion",
        ),
        _row(
            classification_id="classification.tool.query_scene_state",
            row_id="capability.tool.query_scene_state",
            surface_id="tool_schema:query_scene_state",
            display_name="Scene state query",
            surface_family=SurfaceFamily.TOOL_SCHEMA,
            realm=Realm.LOCAL,
            direction=Direction.OBSERVE,
            effect_type=EffectType.SENSE,
            medium=Medium.VISUAL,
            semantic_description=tool_descriptions["query_scene_state"],
            producer="agents.hapax_daimonion.tools.TOOL_SCHEMAS",
            consumer_refs=["consumer:hapax_daimonion.tool_recruitment"],
            concrete_interface="function_schema:query_scene_state",
            availability_probe=AvailabilityProbe(
                probe_id="probe.tool.query_scene_state",
                kind=AvailabilityProbeKind.IMPORT_SYMBOL,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="import:agents.hapax_daimonion.tools.TOOL_SCHEMAS",
                stale_after_s=5,
            ),
            privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="tool_schema",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            kill_switch_behavior=KillSwitchBehavior.PRIVATE_ONLY,
            fallback_policy=FallbackPolicy.FAIL_CLOSED,
            existing_record_refs=["tool_affordance:query_scene_state"],
            missing_record_action=MissingRecordAction.ADD_TOOL_AFFORDANCE,
            witness_contract_id="witness.tool.query_scene_state.scene_snapshot",
            projection_name="tool.query_scene_state",
        ),
        _row(
            classification_id="classification.mcp.context7_docs",
            row_id="capability.mcp.context7_docs",
            surface_id="mcp:context7.query_docs",
            display_name="Context7 documentation retrieval",
            surface_family=SurfaceFamily.MCP_TOOL,
            realm=Realm.REMOTE,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.TEXTUAL,
            semantic_description=(
                "Retrieve governed documentation examples for library questions while preserving "
                "source attribution and version context."
            ),
            producer="mcp.context7.query_docs",
            consumer_refs=["consumer:codex_research_context"],
            concrete_interface="mcp:context7.query_docs",
            availability_probe=AvailabilityProbe(
                probe_id="probe.mcp.context7_docs",
                kind=AvailabilityProbeKind.REMOTE_QUERY,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="mcp:context7.query_docs.self_check",
                stale_after_s=1800,
            ),
            privacy_class=PrivacyLabel.PUBLIC_SAFE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="remote_documentation",
            public_claim_policy=PublicClaimPolicy.EVIDENCE_BOUND_ONLY,
            can_acquire_sources=True,
            existing_record_refs=["mcp_tool:context7.query_docs"],
            witness_contract_id="witness.mcp.context7.cited_result",
            projection_name="mcp.context7_docs",
        ),
        _row(
            classification_id="classification.browser.playwright_state",
            row_id="capability.browser.playwright_state",
            surface_id="browser_surface:playwright.current_page",
            display_name="Playwright browser read state",
            surface_family=SurfaceFamily.BROWSER_SURFACE,
            realm=Realm.HYBRID,
            direction=Direction.OBSERVE,
            effect_type=EffectType.SENSE,
            medium=Medium.TEXTUAL,
            semantic_description=(
                "Observe current browser page state as source-conditioned evidence with URL, "
                "snapshot, freshness, and tool-error witnesses."
            ),
            producer="mcp.playwright.browser_snapshot",
            consumer_refs=["consumer:codex_research_context", "consumer:wcs_browser_file_surface"],
            concrete_interface="mcp:playwright.browser_snapshot",
            availability_probe=AvailabilityProbe(
                probe_id="probe.browser.playwright_state",
                kind=AvailabilityProbeKind.REMOTE_QUERY,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="mcp:playwright.browser_snapshot.result",
                stale_after_s=300,
            ),
            privacy_class=PrivacyLabel.PUBLIC_SAFE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="browser_state_read",
            public_claim_policy=PublicClaimPolicy.PUBLIC_GATE_REQUIRED,
            can_acquire_sources=True,
            existing_record_refs=["mcp_tool:playwright.browser_snapshot"],
            witness_contract_id="witness.browser.playwright_snapshot_cited",
            projection_name="browser.playwright_state",
        ),
        _row(
            classification_id="classification.file.local_repo_read",
            row_id="capability.file.local_repo_read",
            surface_id="file:local_repo_read",
            display_name="Local repository file read",
            surface_family=SurfaceFamily.FILE,
            realm=Realm.LOCAL,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.TEXTUAL,
            semantic_description=(
                "Recall local repository files as supplied evidence only when path, hash, "
                "mtime, and privacy classification are captured."
            ),
            producer="filesystem",
            consumer_refs=["consumer:codex_research_context", "consumer:wcs_browser_file_surface"],
            concrete_interface="file:repo",
            availability_probe=AvailabilityProbe(
                probe_id="probe.file.local_repo_read",
                kind=AvailabilityProbeKind.STATE_MTIME,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="file:repo:path_hash_mtime",
                stale_after_s=900,
            ),
            privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="local_file_read",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            supplied_evidence_only=True,
            existing_record_refs=["wcs:file.obsidian_vault"],
            witness_contract_id="witness.file.local_repo_path_hash_mtime",
            projection_name="file.local_repo_read",
        ),
        _row(
            classification_id="classification.obsidian.vault_note_read",
            row_id="capability.obsidian.vault_note_read",
            surface_id="obsidian_note:vault_note_read",
            display_name="Obsidian vault note read",
            surface_family=SurfaceFamily.OBSIDIAN_NOTE,
            realm=Realm.LOCAL,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.TEXTUAL,
            semantic_description=(
                "Recall Obsidian task and research notes as private supplied evidence with "
                "path, hash, mtime, and vault privacy witnesses."
            ),
            producer="obsidian_vault",
            consumer_refs=["consumer:codex_research_context", "consumer:wcs_browser_file_surface"],
            concrete_interface="obsidian:vault_path",
            availability_probe=AvailabilityProbe(
                probe_id="probe.obsidian.vault_note_read",
                kind=AvailabilityProbeKind.STATE_MTIME,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="obsidian:vault_path_hash_mtime",
                stale_after_s=900,
            ),
            privacy_class=PrivacyLabel.PRIVATE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="obsidian_note_read",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            supplied_evidence_only=True,
            existing_record_refs=["wcs:file.obsidian_vault"],
            witness_contract_id="witness.obsidian.vault_note_path_hash_mtime",
            projection_name="obsidian.vault_note_read",
        ),
        _row(
            classification_id="classification.command.output_reference",
            row_id="capability.command.output_reference",
            surface_id="command_output:local_command",
            display_name="Local command output reference",
            surface_family=SurfaceFamily.COMMAND_OUTPUT,
            realm=Realm.LOCAL,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.TEXTUAL,
            semantic_description=(
                "Recall command output as execution evidence only when command, exit status, "
                "captured output reference, and replay hash are preserved."
            ),
            producer="codex.exec_command",
            consumer_refs=["consumer:codex_research_context", "consumer:wcs_browser_file_surface"],
            concrete_interface="command:local_shell_output",
            availability_probe=AvailabilityProbe(
                probe_id="probe.command.output_reference",
                kind=AvailabilityProbeKind.STATIC_RECORD,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="command:output_ref_hash_exit_status",
                stale_after_s=None,
            ),
            privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="command_output_reference",
            public_claim_policy=PublicClaimPolicy.EVIDENCE_BOUND_ONLY,
            existing_record_refs=["wcs:browser.mcp_tool_read"],
            witness_contract_id="witness.command.output_ref_hash_exit_status",
            projection_name="command.output_reference",
        ),
        _row(
            classification_id="classification.runtime.logos_api_health",
            row_id="capability.runtime.logos_api_health",
            surface_id="service:logos-api",
            display_name="Logos local health surface",
            surface_family=SurfaceFamily.RUNTIME_SERVICE,
            realm=Realm.LOCAL,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.DATA,
            semantic_description=(
                "Recall local orientation and health state for grounded operator context and "
                "status-aware decisions."
            ),
            producer="systemd:user:logos-api.service",
            consumer_refs=["consumer:orientation_panel", "consumer:mcp_hapax_status"],
            concrete_interface="systemd:user:logos-api.service",
            availability_probe=AvailabilityProbe(
                probe_id="probe.runtime.logos_health",
                kind=AvailabilityProbeKind.HEALTH_ENDPOINT,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="http:127.0.0.1:8051/health",
                stale_after_s=30,
            ),
            privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="local_service",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            existing_record_refs=["systemd:logos-api.service"],
            witness_contract_id="witness.runtime.logos_health_ok",
            projection_name="runtime.logos_health",
        ),
        _row(
            classification_id="classification.state.vision_classifications_stale",
            row_id="state.vision.classifications_stale",
            surface_id="shm:hapax-vision/classifications.json",
            display_name="Stale vision classifications",
            surface_family=SurfaceFamily.STATE_FILE,
            realm=Realm.LOCAL,
            direction=Direction.OBSERVE,
            effect_type=EffectType.SENSE,
            medium=Medium.DATA,
            semantic_description=(
                "Observe prior scene classification state only as stale context until a fresh "
                "vision witness appears."
            ),
            producer="visual-layer-aggregator",
            consumer_refs=["consumer:wcs_snapshot", "consumer:director_snapshot"],
            concrete_interface="shm:hapax-vision/classifications.json",
            availability_probe=AvailabilityProbe(
                probe_id="probe.state.vision_classifications_stale",
                kind=AvailabilityProbeKind.STATE_MTIME,
                expected_state=AvailabilityState.STALE,
                witness_ref="mtime:shm:hapax-vision/classifications.json",
                stale_after_s=5,
            ),
            availability_state=AvailabilityState.STALE,
            lifecycle=LifecycleState.STALE,
            recruitable=False,
            privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="runtime_state",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            kill_switch_behavior=KillSwitchBehavior.STALE_BADGE,
            fallback_policy=FallbackPolicy.STALE_CONTEXT_ONLY,
            degraded_reason="state file is useful only with a fresh modification-time witness",
            existing_record_refs=["state:/dev/shm/hapax-vision/classifications.json"],
            projection_name=None,
            witness_contract_id=None,
            kind={SemanticKind.STATE, SemanticKind.SUBSTRATE, SemanticKind.REPRESENTATION},
        ),
        _row(
            classification_id="classification.device.camera_overhead_brio",
            row_id="capability.device.camera_overhead_brio",
            surface_id="device:camera.overhead_brio",
            display_name="Overhead Brio camera",
            surface_family=SurfaceFamily.DEVICE,
            realm=Realm.LOCAL,
            direction=Direction.OBSERVE,
            effect_type=EffectType.SENSE,
            medium=Medium.VISUAL,
            semantic_description=(
                "Observe the overhead hardware workspace from a fixed perspective for studio "
                "object and activity evidence."
            ),
            producer="studio-person-detector.service",
            consumer_refs=["consumer:studio_compositor", "consumer:visual_layer_aggregator"],
            concrete_interface="video4linux:overhead-brio",
            availability_probe=AvailabilityProbe(
                probe_id="probe.device.camera_overhead_brio",
                kind=AvailabilityProbeKind.DEVICE_PRESENT,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="device:video4linux:overhead-brio",
                stale_after_s=2,
            ),
            privacy_class=PrivacyLabel.PERSON_ADJACENT,
            consent_policy=ConsentLabel.PERSON_ADJACENT,
            recruitment_family="camera_perception",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            existing_record_refs=["device:overhead-brio"],
            witness_contract_id="witness.device.camera_frame_current",
            projection_name="device.camera_overhead_brio",
            consent_person_id="guest",
            consent_data_category="video",
        ),
        _row(
            classification_id="classification.audio.l12_raw_hardware",
            row_id="capability.audio.l12_raw_hardware",
            surface_id="audio_route:l12.raw_hardware",
            display_name="L-12 raw hardware route",
            surface_family=SurfaceFamily.AUDIO_ROUTE,
            realm=Realm.LOCAL,
            direction=Direction.ROUTE,
            effect_type=EffectType.MODULATE,
            medium=Medium.AUDITORY,
            semantic_description=(
                "Route raw mixer audio into private monitoring so hardware state can be "
                "checked before broadcast use."
            ),
            producer="audio-topology-inspector",
            consumer_refs=["consumer:audio_router"],
            concrete_interface="pipewire:l12.raw_hardware",
            availability_probe=AvailabilityProbe(
                probe_id="probe.audio.l12_raw_hardware",
                kind=AvailabilityProbeKind.ROUTE_WITNESS,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="witness:audio.l12_forward_invariant",
                stale_after_s=2,
            ),
            privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="audio_route",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            kill_switch_behavior=KillSwitchBehavior.PRIVATE_ONLY,
            fallback_policy=FallbackPolicy.PRIVATE_MONITOR_ONLY,
            existing_record_refs=["audio_route:l12.raw_hardware"],
            witness_contract_id="witness.audio.l12_forward_invariant",
            projection_name="audio.l12_raw_hardware",
        ),
        _row(
            classification_id="classification.audio.broadcast_master_normalized",
            row_id="capability.audio.broadcast_master_normalized",
            surface_id="audio_route:broadcast.master.normalized",
            display_name="Normalized broadcast master",
            surface_family=SurfaceFamily.AUDIO_ROUTE,
            realm=Realm.LOCAL,
            direction=Direction.ROUTE,
            effect_type=EffectType.MODULATE,
            medium=Medium.AUDITORY,
            semantic_description=(
                "Route normalized programme audio to the public mix only after loudness and "
                "leak witnesses pass."
            ),
            producer="broadcast-audio-health",
            consumer_refs=["consumer:studio_compositor", "consumer:obs_output"],
            concrete_interface="pipewire:broadcast.master.normalized",
            availability_probe=AvailabilityProbe(
                probe_id="probe.audio.broadcast_master_normalized",
                kind=AvailabilityProbeKind.ROUTE_WITNESS,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="witness:audio.broadcast_loudness_safe",
                stale_after_s=2,
            ),
            privacy_class=PrivacyLabel.PUBLIC_BROADCAST,
            consent_policy=ConsentLabel.PUBLIC_BROADCAST,
            recruitment_family="audio_route",
            public_claim_policy=PublicClaimPolicy.PUBLIC_GATE_REQUIRED,
            existing_record_refs=["audio_route:broadcast.master.normalized"],
            witness_contract_id="witness.audio.broadcast_loudness_safe",
            projection_name="audio.broadcast_master_normalized",
        ),
        _row(
            classification_id="classification.audio.obs_broadcast_remap",
            row_id="capability.audio.obs_broadcast_remap",
            surface_id="audio_route:obs.broadcast_remap",
            display_name="OBS broadcast remap",
            surface_family=SurfaceFamily.AUDIO_ROUTE,
            realm=Realm.LOCAL,
            direction=Direction.ROUTE,
            effect_type=EffectType.MODULATE,
            medium=Medium.AUDITORY,
            semantic_description=(
                "Route remapped broadcast audio away from raw devices when stream egress "
                "requires the safe mix."
            ),
            producer="audio-router-policy",
            consumer_refs=["consumer:obs_output", "consumer:studio_compositor"],
            concrete_interface="pipewire:obs.broadcast_remap",
            availability_probe=AvailabilityProbe(
                probe_id="probe.audio.obs_broadcast_remap",
                kind=AvailabilityProbeKind.ROUTE_WITNESS,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="witness:audio.obs_remap_not_raw",
                stale_after_s=2,
            ),
            privacy_class=PrivacyLabel.PUBLIC_BROADCAST,
            consent_policy=ConsentLabel.PUBLIC_BROADCAST,
            recruitment_family="audio_route",
            public_claim_policy=PublicClaimPolicy.PUBLIC_GATE_REQUIRED,
            existing_record_refs=["audio_route:obs.broadcast_remap"],
            witness_contract_id="witness.audio.obs_remap_not_raw",
            projection_name="audio.obs_broadcast_remap",
        ),
        _row(
            classification_id="classification.video.studio_composed_frame",
            row_id="capability.visual.logos_api_frame_surface",
            surface_id="video_surface:studio_compositor.composed_frame",
            display_name="Composed studio frame",
            surface_family=SurfaceFamily.VIDEO_SURFACE,
            realm=Realm.LOCAL,
            direction=Direction.EXPRESS,
            effect_type=EffectType.COMPOSE,
            medium=Medium.VISUAL,
            semantic_description=(
                "Compose the current studio frame for public viewing only after visual "
                "freshness and source witnesses pass."
            ),
            producer="studio-compositor.service",
            consumer_refs=["consumer:livestream_output", "consumer:director_snapshot"],
            concrete_interface="http:127.0.0.1:8051/api/logos/frame",
            availability_probe=AvailabilityProbe(
                probe_id="probe.video.studio_composed_frame",
                kind=AvailabilityProbeKind.FRAME_WITNESS,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="witness:video.composed_frame_nonblank",
                stale_after_s=2,
            ),
            privacy_class=PrivacyLabel.PUBLIC_BROADCAST,
            consent_policy=ConsentLabel.PUBLIC_BROADCAST,
            recruitment_family="video_surface",
            public_claim_policy=PublicClaimPolicy.PUBLIC_GATE_REQUIRED,
            existing_record_refs=["surface:studio_compositor.composed_frame"],
            witness_contract_id="witness.video.composed_frame_nonblank",
            projection_name="visual.logos_api_frame_surface",
        ),
        _row(
            classification_id="classification.midi.s4_clock_transport",
            row_id="capability.midi.s4_clock_transport",
            surface_id="midi_surface:s4.clock_transport",
            display_name="S-4 clock and transport",
            surface_family=SurfaceFamily.MIDI_SURFACE,
            realm=Realm.LOCAL,
            direction=Direction.EXPRESS,
            effect_type=EffectType.MODULATE,
            medium=Medium.AUDITORY,
            semantic_description=(
                "Modulate hardware timing and transport so sonic gestures remain aligned with "
                "programme rhythm."
            ),
            producer="agents.hapax_daimonion.s4_midi",
            consumer_refs=["consumer:vocal_chain", "consumer:vinyl_chain"],
            concrete_interface="midi:torso_s4",
            availability_probe=AvailabilityProbe(
                probe_id="probe.midi.s4_clock_transport",
                kind=AvailabilityProbeKind.ROUTE_WITNESS,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="witness:midi.s4_clock_seen",
                stale_after_s=10,
            ),
            privacy_class=PrivacyLabel.PUBLIC_SAFE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="midi_expression",
            public_claim_policy=PublicClaimPolicy.EVIDENCE_BOUND_ONLY,
            existing_record_refs=["midi_surface:s4.clock_transport"],
            witness_contract_id="witness.midi.s4_clock_seen",
            projection_name="midi.s4_clock_transport",
        ),
        _row(
            classification_id="classification.desktop.hyprland_focus",
            row_id="capability.desktop.hyprland_focus",
            surface_id="desktop_control:hyprland.focus_window",
            display_name="Hyprland focus control",
            surface_family=SurfaceFamily.DESKTOP_CONTROL,
            realm=Realm.LOCAL,
            direction=Direction.ACT,
            effect_type=EffectType.ACT,
            medium=Medium.CONTROL,
            semantic_description=(
                "Act on the focused workspace only after operator-facing command gates keep "
                "desktop changes reversible."
            ),
            producer="agents.hapax_daimonion.desktop_tools",
            consumer_refs=["consumer:operator_desktop"],
            concrete_interface="hyprctl:dispatch:focuswindow",
            availability_probe=AvailabilityProbe(
                probe_id="probe.desktop.hyprland_focus",
                kind=AvailabilityProbeKind.OPERATOR_GATE,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="witness:desktop.command_noop_or_confirmed",
                stale_after_s=5,
            ),
            privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="desktop_control",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            kill_switch_behavior=KillSwitchBehavior.HARD_BLOCK,
            fallback_policy=FallbackPolicy.FAIL_CLOSED,
            existing_record_refs=["tool_affordance:focus_window"],
            witness_contract_id="witness.desktop.command_noop_or_confirmed",
            projection_name="desktop.hyprland_focus",
        ),
        _row(
            classification_id="classification.companion.phone_awareness",
            row_id="capability.companion.phone_awareness",
            surface_id="companion_device:phone.awareness",
            display_name="Phone awareness payload",
            surface_family=SurfaceFamily.COMPANION_DEVICE,
            realm=Realm.LOCAL,
            direction=Direction.OBSERVE,
            effect_type=EffectType.SENSE,
            medium=Medium.DATA,
            semantic_description=(
                "Observe paired phone context as private operator state for interruption and "
                "mobile-awareness decisions."
            ),
            producer="agents.hapax_daimonion.backends.phone_awareness",
            consumer_refs=["consumer:engagement_governor", "consumer:presence_model"],
            concrete_interface="kdeconnect:phone_awareness",
            availability_probe=AvailabilityProbe(
                probe_id="probe.companion.phone_awareness",
                kind=AvailabilityProbeKind.STATE_MTIME,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="state:phone_kde_connected",
                stale_after_s=120,
            ),
            privacy_class=PrivacyLabel.PRIVATE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="companion_state",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            kill_switch_behavior=KillSwitchBehavior.PRIVATE_ONLY,
            fallback_policy=FallbackPolicy.FAIL_CLOSED,
            existing_record_refs=["backend:phone_awareness"],
            witness_contract_id="witness.companion.phone_fresh",
            projection_name="companion.phone_awareness",
        ),
        _row(
            classification_id="classification.local_api.orientation",
            row_id="capability.local_api.orientation",
            surface_id="local_api:logos.orientation",
            display_name="Local orientation endpoint",
            surface_family=SurfaceFamily.LOCAL_API,
            realm=Realm.LOCAL,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.DATA,
            semantic_description=(
                "Recall local orientation state for dashboard and assistant context without "
                "expanding public claims."
            ),
            producer="logos-api.service",
            consumer_refs=["consumer:obsidian_plugin", "consumer:hapax_mcp"],
            concrete_interface="http:127.0.0.1:8051/api/orientation",
            availability_probe=AvailabilityProbe(
                probe_id="probe.local_api.orientation",
                kind=AvailabilityProbeKind.HEALTH_ENDPOINT,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="http:127.0.0.1:8051/api/orientation",
                stale_after_s=300,
            ),
            privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="local_api",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            existing_record_refs=["route:logos.orientation"],
            witness_contract_id="witness.local_api.orientation_ok",
            projection_name="local_api.orientation",
        ),
        _row(
            classification_id="classification.container.vector_memory",
            row_id="capability.container.vector_memory",
            surface_id="docker_container:qdrant",
            display_name="Vector memory container",
            surface_family=SurfaceFamily.DOCKER_CONTAINER,
            realm=Realm.LOCAL,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.DATA,
            semantic_description=(
                "Recall embedded memory neighborhoods for capability matching and grounded "
                "context retrieval."
            ),
            producer="docker-compose:qdrant",
            consumer_refs=["consumer:affordance_pipeline", "consumer:rag_ingest"],
            concrete_interface="docker:qdrant",
            availability_probe=AvailabilityProbe(
                probe_id="probe.container.vector_memory",
                kind=AvailabilityProbeKind.CONTAINER_HEALTH,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="container:qdrant:healthy",
                stale_after_s=30,
            ),
            privacy_class=PrivacyLabel.PRIVATE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="local_infrastructure",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            existing_record_refs=["container:qdrant"],
            witness_contract_id="witness.container.vector_memory_healthy",
            projection_name="container.vector_memory",
        ),
        _row(
            classification_id="classification.model.litellm_supplied_evidence",
            row_id="capability.model.litellm_supplied_evidence",
            surface_id="model_provider:litellm.supplied_evidence",
            display_name="LiteLLM supplied-evidence reasoning",
            surface_family=SurfaceFamily.MODEL_PROVIDER,
            realm=Realm.HYBRID,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.TEXTUAL,
            semantic_description=(
                "Recall supplied evidence through model reasoning without treating generated "
                "text as a source acquisition route."
            ),
            producer="litellm-gateway",
            consumer_refs=["consumer:content_grounding", "consumer:daimonion_reasoning"],
            concrete_interface="provider:litellm:reasoning",
            availability_probe=AvailabilityProbe(
                probe_id="probe.model.litellm_supplied_evidence",
                kind=AvailabilityProbeKind.REMOTE_QUERY,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="provider:litellm:health",
                stale_after_s=60,
            ),
            privacy_class=PrivacyLabel.PRIVATE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="model_provider",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            supplied_evidence_only=True,
            existing_record_refs=["provider:litellm"],
            witness_contract_id="witness.model.litellm_health",
            projection_name="model.litellm_supplied_evidence",
        ),
        _row(
            classification_id="classification.search.tavily_source_acquisition",
            row_id="capability.search.tavily_source_acquisition",
            surface_id="search_provider:tavily",
            display_name="Tavily source acquisition",
            surface_family=SurfaceFamily.SEARCH_PROVIDER,
            realm=Realm.REMOTE,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.TEXTUAL,
            semantic_description=(
                "Retrieve public source candidates for current claims with citation freshness "
                "and acquisition evidence."
            ),
            producer="mcp.tavily.search",
            consumer_refs=["consumer:grounding_provider_router"],
            concrete_interface="mcp:tavily.search",
            availability_probe=AvailabilityProbe(
                probe_id="probe.search.tavily_source_acquisition",
                kind=AvailabilityProbeKind.REMOTE_QUERY,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="provider:tavily:cited_result",
                stale_after_s=900,
            ),
            privacy_class=PrivacyLabel.PUBLIC_SAFE,
            consent_policy=ConsentLabel.PUBLIC_BROADCAST,
            recruitment_family="source_acquisition",
            public_claim_policy=PublicClaimPolicy.PUBLIC_GATE_REQUIRED,
            can_acquire_sources=True,
            existing_record_refs=["provider:tavily"],
            witness_contract_id="witness.search.cited_result",
            projection_name="search.tavily_source_acquisition",
        ),
        _row(
            classification_id="classification.publication.youtube_live",
            row_id="capability.publication.youtube_live",
            surface_id="publication_endpoint:youtube.live",
            display_name="YouTube live publication",
            surface_family=SurfaceFamily.PUBLICATION_ENDPOINT,
            realm=Realm.REMOTE,
            direction=Direction.COMMUNICATE,
            effect_type=EffectType.COMMUNICATE,
            medium=Medium.VISUAL,
            semantic_description=(
                "Communicate witnessed programme output to public viewers only when rights and "
                "egress gates pass."
            ),
            producer="youtube.live.integration",
            consumer_refs=["consumer:studio_compositor", "consumer:content_programme_runner"],
            concrete_interface="provider:youtube.live",
            availability_probe=AvailabilityProbe(
                probe_id="probe.publication.youtube_live",
                kind=AvailabilityProbeKind.REMOTE_QUERY,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="provider:youtube.live.broadcast_eligible",
                stale_after_s=60,
            ),
            privacy_class=PrivacyLabel.PUBLIC_BROADCAST,
            consent_policy=ConsentLabel.PUBLIC_BROADCAST,
            recruitment_family="publication_endpoint",
            public_claim_policy=PublicClaimPolicy.PUBLIC_GATE_REQUIRED,
            existing_record_refs=["provider:youtube.live"],
            witness_contract_id="witness.publication.youtube_egress_safe",
            projection_name="publication.youtube_live",
        ),
        _row(
            classification_id="classification.archive.video_processor",
            row_id="capability.archive.video_processor",
            surface_id="archive_processor:video_processor",
            display_name="Video archive processor",
            surface_family=SurfaceFamily.ARCHIVE_PROCESSOR,
            realm=Realm.LOCAL,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.VISUAL,
            semantic_description=(
                "Recall archived visual windows as evidence priors without converting them into "
                "public truth."
            ),
            producer="video-processor.timer",
            consumer_refs=["consumer:rag_ingest", "consumer:director_memory"],
            concrete_interface="systemd:user:video-processor.timer",
            availability_probe=AvailabilityProbe(
                probe_id="probe.archive.video_processor",
                kind=AvailabilityProbeKind.STATE_MTIME,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="archive:video_processor:last_success",
                stale_after_s=86400,
            ),
            privacy_class=PrivacyLabel.PRIVATE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="archive_processor",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            supplied_evidence_only=True,
            existing_record_refs=["timer:video-processor"],
            witness_contract_id="witness.archive.video_processor_recent",
            projection_name="archive.video_processor",
        ),
        _row(
            classification_id="classification.storage.backblaze_restic_sync",
            row_id="capability.storage.backblaze_restic_sync",
            surface_id="storage_sync:backblaze.restic",
            display_name="Backblaze restic storage sync",
            surface_family=SurfaceFamily.STORAGE_SYNC,
            realm=Realm.REMOTE,
            direction=Direction.ACT,
            effect_type=EffectType.ACT,
            medium=Medium.DATA,
            semantic_description=(
                "Act on encrypted backup transfer state for durability without exposing private "
                "contents."
            ),
            producer="restic-rclone-backup.timer",
            consumer_refs=["consumer:system_health"],
            concrete_interface="provider:backblaze.restic",
            availability_probe=AvailabilityProbe(
                probe_id="probe.storage.backblaze_restic_sync",
                kind=AvailabilityProbeKind.REMOTE_QUERY,
                expected_state=AvailabilityState.PRIVATE_ONLY,
                witness_ref="backup:restic:last_success",
                stale_after_s=86400,
            ),
            privacy_class=PrivacyLabel.PRIVATE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="storage_sync",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            existing_record_refs=["provider:backblaze", "tool:restic"],
            witness_contract_id="witness.storage.backup_recent",
            projection_name="storage.backblaze_restic_sync",
        ),
        _row(
            classification_id="classification.public_event.github_pr",
            row_id="capability.public_event.github_pr",
            surface_id="public_event:github.pull_request",
            display_name="GitHub pull request public event",
            surface_family=SurfaceFamily.PUBLIC_EVENT,
            realm=Realm.REMOTE,
            direction=Direction.COMMUNICATE,
            effect_type=EffectType.COMMUNICATE,
            medium=Medium.TEXTUAL,
            semantic_description=(
                "Communicate code-change evidence to repository review surfaces with explicit "
                "provenance and status witnesses."
            ),
            producer="github.pr.workflow",
            consumer_refs=["consumer:sdlc_pipeline", "consumer:operator_review"],
            concrete_interface="provider:github.pull_request",
            availability_probe=AvailabilityProbe(
                probe_id="probe.public_event.github_pr",
                kind=AvailabilityProbeKind.REMOTE_QUERY,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="provider:github.pull_request.status",
                stale_after_s=300,
            ),
            privacy_class=PrivacyLabel.PUBLIC_SAFE,
            consent_policy=ConsentLabel.PUBLIC_BROADCAST,
            recruitment_family="public_event",
            public_claim_policy=PublicClaimPolicy.PUBLIC_GATE_REQUIRED,
            existing_record_refs=["provider:github.pull_request"],
            witness_contract_id="witness.public_event.github_status",
            projection_name="public_event.github_pr",
        ),
        _row(
            classification_id="classification.governance.orcid_identity",
            row_id="capability.governance.orcid_identity",
            surface_id="governance_surface:orcid.identity",
            display_name="ORCID identity provenance",
            surface_family=SurfaceFamily.GOVERNANCE_SURFACE,
            realm=Realm.REMOTE,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.TEXTUAL,
            semantic_description=(
                "Recall scholarly identity provenance for formal records without broadening "
                "personal-state disclosure."
            ),
            producer="shared.orcid",
            consumer_refs=["consumer:research_artifact_packaging"],
            concrete_interface="provider:orcid.identity",
            availability_probe=AvailabilityProbe(
                probe_id="probe.governance.orcid_identity",
                kind=AvailabilityProbeKind.REMOTE_QUERY,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="provider:orcid.identity.profile",
                stale_after_s=86400,
            ),
            privacy_class=PrivacyLabel.PUBLIC_SAFE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="identity_provenance",
            public_claim_policy=PublicClaimPolicy.EVIDENCE_BOUND_ONLY,
            existing_record_refs=["provider:orcid"],
            witness_contract_id="witness.governance.orcid_profile",
            projection_name="governance.orcid_identity",
        ),
        _row(
            classification_id="classification.infrastructure.prometheus_telemetry",
            row_id="capability.infrastructure.prometheus_telemetry",
            surface_id="infrastructure:prometheus",
            display_name="Prometheus telemetry",
            surface_family=SurfaceFamily.INFRASTRUCTURE,
            realm=Realm.LOCAL,
            direction=Direction.RECALL,
            effect_type=EffectType.RECALL,
            medium=Medium.DATA,
            semantic_description=(
                "Recall local telemetry trends for system health decisions without treating "
                "metrics as public claims."
            ),
            producer="docker-compose:prometheus",
            consumer_refs=["consumer:health_monitor", "consumer:mesh_health"],
            concrete_interface="docker:prometheus",
            availability_probe=AvailabilityProbe(
                probe_id="probe.infrastructure.prometheus_telemetry",
                kind=AvailabilityProbeKind.CONTAINER_HEALTH,
                expected_state=AvailabilityState.AVAILABLE,
                witness_ref="container:prometheus:healthy",
                stale_after_s=60,
            ),
            privacy_class=PrivacyLabel.PRIVATE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="telemetry",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            existing_record_refs=["container:prometheus"],
            witness_contract_id="witness.infrastructure.prometheus_healthy",
            projection_name="infrastructure.prometheus_telemetry",
        ),
        _row(
            classification_id="classification.remote.soundcloud_unavailable",
            row_id="provider.soundcloud.publication_unavailable",
            surface_id="publication_endpoint:soundcloud",
            display_name="SoundCloud publication unavailable",
            surface_family=SurfaceFamily.PUBLICATION_ENDPOINT,
            realm=Realm.REMOTE,
            direction=Direction.COMMUNICATE,
            effect_type=EffectType.COMMUNICATE,
            medium=Medium.AUDITORY,
            semantic_description=(
                "Communicate audio releases only after provider credentials and rights evidence "
                "are freshly witnessed."
            ),
            producer="soundcloud.publisher",
            consumer_refs=["consumer:content_programme_runner"],
            concrete_interface="provider:soundcloud.upload",
            availability_probe=AvailabilityProbe(
                probe_id="probe.remote.soundcloud_unavailable",
                kind=AvailabilityProbeKind.REMOTE_QUERY,
                expected_state=AvailabilityState.UNAVAILABLE,
                witness_ref="provider:soundcloud.credentials_missing",
                stale_after_s=3600,
            ),
            availability_state=AvailabilityState.UNAVAILABLE,
            lifecycle=LifecycleState.BLOCKED,
            recruitable=False,
            privacy_class=PrivacyLabel.PUBLIC_SAFE,
            consent_policy=ConsentLabel.PUBLIC_BROADCAST,
            recruitment_family="publication_endpoint",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            kill_switch_behavior=KillSwitchBehavior.HARD_BLOCK,
            fallback_policy=FallbackPolicy.FAIL_CLOSED,
            degraded_reason="publication credentials and rights witness are not available",
            existing_record_refs=["provider:soundcloud"],
            projection_name=None,
            witness_contract_id=None,
        ),
        _row(
            classification_id="classification.surface.tauri_logos_decommissioned",
            row_id="surface.tauri_logos.decommissioned_frame_server",
            surface_id="video_surface:tauri_logos.frame_server",
            display_name="Decommissioned Tauri frame server",
            surface_family=SurfaceFamily.VIDEO_SURFACE,
            realm=Realm.LOCAL,
            direction=Direction.EXPRESS,
            effect_type=EffectType.COMPOSE,
            medium=Medium.VISUAL,
            semantic_description=(
                "Observe former visual frame surface only as a blocked replacement cue for "
                "current studio surfaces."
            ),
            producer="tauri-logos.decommissioned",
            consumer_refs=["consumer:wcs_snapshot", "consumer:director_snapshot"],
            concrete_interface="tauri:hapax-logos-frame-server",
            availability_probe=AvailabilityProbe(
                probe_id="probe.surface.tauri_logos_decommissioned",
                kind=AvailabilityProbeKind.DECOMMISSION_EVIDENCE,
                expected_state=AvailabilityState.DECOMMISSIONED,
                witness_ref="task:tauri-logos-decommission-enforcement",
                stale_after_s=None,
            ),
            availability_state=AvailabilityState.DECOMMISSIONED,
            lifecycle=LifecycleState.DECOMMISSIONED,
            recruitable=False,
            privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
            consent_policy=ConsentLabel.OPERATOR_SELF,
            recruitment_family="video_surface",
            public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
            kill_switch_behavior=KillSwitchBehavior.REPLACEMENT_ONLY,
            fallback_policy=FallbackPolicy.USE_REPLACEMENT_ROW,
            degraded_reason="surface is decommissioned and must be replaced by the current frame row",
            existing_record_refs=["surface:tauri_logos.frame_server"],
            missing_record_action=MissingRecordAction.REPLACED_BY_ROW,
            projection_name=None,
            witness_contract_id=None,
            replacement_row_id="capability.visual.logos_api_frame_surface",
            blocked_reason="Tauri visual path is decommissioned; use the current studio frame row.",
            aliases=[],
        ),
    ]

    rows.extend(_voice_tier_rows(VoiceTier, TIER_NAMES, TIER_RISK_REASONS, tier_capability_record))
    rows.append(_vocal_chain_row())
    rows.append(_vinyl_chain_row())

    return CapabilityClassificationInventory(
        **{
            "$schema": "../schemas/capability-classification-inventory.schema.json",
            "schema_version": 1,
            "generated_from": [
                "vault-spec:capability-semantic-classification-inventory",
                "vault-audit:capability-semantic-classification-system-scour",
                "repo:shared.semantic_recruitment.SemanticRecruitmentRow",
            ],
            "rows": rows,
        }
    )


def _require_record(records: list[Any], name: str) -> Any:
    for record in records:
        if record.name == name:
            return record
    raise CapabilityClassificationError(f"missing existing capability record: {name}")


def _capability_record_row(
    *,
    record: Any,
    classification_id: str,
    row_id: str,
    surface_id: str,
    display_name: str,
    surface_family: SurfaceFamily,
    realm: Realm,
    direction: Direction,
    effect_type: EffectType,
    medium: Medium,
    producer: str,
    consumer_refs: list[str],
    concrete_interface: str,
    availability_probe: AvailabilityProbe,
    privacy_class: PrivacyLabel,
    consent_policy: ConsentLabel,
    recruitment_family: str,
    public_claim_policy: PublicClaimPolicy,
    existing_record_refs: list[str],
    witness_contract_id: str,
    projection_name: str,
    evidence_ref: str,
    semantic_description: str | None = None,
    can_acquire_sources: bool = False,
) -> CapabilityClassificationRow:
    operational = record.operational
    rights_label = RightsLabel.OPERATOR_OWNED
    if operational.rights_ref and "platform" in operational.rights_ref:
        rights_label = RightsLabel.PLATFORM_CLEARED
    return _row(
        classification_id=classification_id,
        row_id=row_id,
        surface_id=surface_id,
        display_name=display_name,
        surface_family=surface_family,
        realm=realm,
        direction=direction,
        effect_type=effect_type,
        medium=medium,
        semantic_description=semantic_description or record.description,
        producer=producer,
        consumer_refs=consumer_refs,
        concrete_interface=concrete_interface,
        availability_probe=availability_probe,
        privacy_class=privacy_class,
        consent_policy=consent_policy,
        rights_class=rights_label,
        content_risk=ContentRisk(operational.content_risk)
        if operational.content_risk != "unknown"
        else ContentRisk.TIER_0_OWNED,
        monetization_risk=MonetizationRisk(operational.monetization_risk)
        if operational.monetization_risk != "unknown"
        else MonetizationRisk.NONE,
        recruitment_family=recruitment_family,
        public_claim_policy=public_claim_policy,
        can_acquire_sources=can_acquire_sources,
        existing_record_refs=existing_record_refs,
        witness_contract_id=witness_contract_id,
        projection_name=projection_name,
        evidence_ref=evidence_ref,
        projection_daemon=record.daemon,
    )


def _voice_tier_rows(
    voice_tier_enum: Any,
    tier_names: dict[Any, str],
    tier_risk_reasons: dict[Any, str],
    tier_capability_record_fn: Any,
) -> list[CapabilityClassificationRow]:
    rows: list[CapabilityClassificationRow] = []
    for tier in voice_tier_enum:
        record = tier_capability_record_fn(tier)
        canonical = tier_names[tier].replace("-", "_")
        high_risk = record.operational.monetization_risk == "high"
        rows.append(
            _row(
                classification_id=f"classification.voice_tier.{canonical}",
                row_id=f"capability.voice_tier.{canonical}",
                surface_id=f"midi_surface:voice_tier.{canonical}",
                display_name=f"Voice tier {tier.value} {tier_names[tier]}",
                surface_family=SurfaceFamily.MIDI_SURFACE,
                realm=Realm.LOCAL,
                direction=Direction.EXPRESS,
                effect_type=EffectType.MODULATE,
                medium=Medium.AUDITORY,
                semantic_description=(
                    f"Express speech in the {tier_names[tier]} register while preserving "
                    "intelligibility floor and monetization ceiling."
                ),
                producer="shared.voice_tier.tier_capability_record",
                consumer_refs=["consumer:affordance_pipeline", "consumer:audio_router"],
                concrete_interface=f"voice_tier:{canonical}",
                availability_probe=AvailabilityProbe(
                    probe_id=f"probe.voice_tier.{canonical}",
                    kind=AvailabilityProbeKind.IMPORT_SYMBOL,
                    expected_state=AvailabilityState.BLOCKED
                    if high_risk
                    else AvailabilityState.AVAILABLE,
                    witness_ref=f"record:voice.tier.{canonical}",
                    stale_after_s=15 if high_risk else 60,
                ),
                availability_state=AvailabilityState.BLOCKED
                if high_risk
                else AvailabilityState.AVAILABLE,
                lifecycle=LifecycleState.BLOCKED if high_risk else LifecycleState.ACTIVE,
                recruitable=not high_risk,
                privacy_class=PrivacyLabel.PUBLIC_SAFE,
                consent_policy=ConsentLabel.OPERATOR_SELF,
                rights_class=RightsLabel.OPERATOR_OWNED,
                content_risk=ContentRisk.TIER_0_OWNED,
                monetization_risk=MonetizationRisk(record.operational.monetization_risk),
                recruitment_family="voice_tier",
                public_claim_policy=PublicClaimPolicy.EVIDENCE_BOUND_ONLY
                if not high_risk
                else PublicClaimPolicy.NO_PUBLIC_CLAIM,
                kill_switch_behavior=KillSwitchBehavior.HARD_BLOCK
                if high_risk
                else KillSwitchBehavior.DEGRADE_STATUS,
                fallback_policy=FallbackPolicy.FAIL_CLOSED,
                degraded_reason=tier_risk_reasons.get(tier) or None,
                existing_record_refs=[f"capability_record:voice.tier.{canonical}"],
                missing_record_action=MissingRecordAction.KEEP_BLOCKED
                if high_risk
                else MissingRecordAction.ADAPT_EXISTING_RECORD,
                witness_contract_id=None
                if high_risk
                else f"witness.voice_tier.{canonical}.intelligibility",
                projection_name=None if high_risk else f"voice.tier.{canonical}",
                evidence_ref="repo:shared.voice_tier.tier_capability_record",
            )
        )
    return rows


def _vocal_chain_row() -> CapabilityClassificationRow:
    return _row(
        classification_id="classification.vocal_chain.intensity",
        row_id="capability.vocal_chain.intensity",
        surface_id="midi_surface:vocal_chain.intensity",
        display_name="Vocal chain intensity dimension",
        surface_family=SurfaceFamily.MIDI_SURFACE,
        realm=Realm.LOCAL,
        direction=Direction.EXPRESS,
        effect_type=EffectType.MODULATE,
        medium=Medium.AUDITORY,
        semantic_description=(
            "Modulate speech intensity through the vocal chain while preserving intelligibility "
            "and programme ceilings."
        ),
        producer="agents.hapax_daimonion.vocal_chain.VOCAL_CHAIN_RECORDS",
        consumer_refs=["consumer:affordance_pipeline", "consumer:vocal_chain"],
        concrete_interface="midi:vocal_chain.intensity",
        availability_probe=AvailabilityProbe(
            probe_id="probe.vocal_chain.intensity",
            kind=AvailabilityProbeKind.IMPORT_SYMBOL,
            expected_state=AvailabilityState.AVAILABLE,
            witness_ref="record:vocal_chain.intensity",
            stale_after_s=60,
        ),
        privacy_class=PrivacyLabel.PUBLIC_SAFE,
        consent_policy=ConsentLabel.OPERATOR_SELF,
        recruitment_family="vocal_chain",
        public_claim_policy=PublicClaimPolicy.EVIDENCE_BOUND_ONLY,
        existing_record_refs=["capability_record:vocal_chain.intensity"],
        witness_contract_id="witness.vocal_chain.dimension_bound",
        projection_name="vocal_chain.intensity",
    )


def _vinyl_chain_row() -> CapabilityClassificationRow:
    return _row(
        classification_id="classification.vinyl_chain.granular_wash",
        row_id="capability.vinyl_chain.granular_wash",
        surface_id="midi_surface:vinyl_chain.granular_wash",
        display_name="Vinyl granular wash mode",
        surface_family=SurfaceFamily.MIDI_SURFACE,
        realm=Realm.LOCAL,
        direction=Direction.EXPRESS,
        effect_type=EffectType.MODULATE,
        medium=Medium.AUDITORY,
        semantic_description=(
            "Modulate vinyl source into granular texture only inside private or explicitly "
            "unlocked programme contexts."
        ),
        producer="agents.hapax_daimonion.vinyl_chain.VINYL_CHAIN_RECORDS",
        consumer_refs=["consumer:affordance_pipeline", "consumer:audio_router"],
        concrete_interface="midi:vinyl_chain.granular_wash",
        availability_probe=AvailabilityProbe(
            probe_id="probe.vinyl_chain.granular_wash",
            kind=AvailabilityProbeKind.OPERATOR_GATE,
            expected_state=AvailabilityState.PRIVATE_ONLY,
            witness_ref="programme:monetization_opt_in:mode_d_granular_wash",
            stale_after_s=60,
        ),
        privacy_class=PrivacyLabel.OPERATOR_VISIBLE,
        consent_policy=ConsentLabel.OPERATOR_SELF,
        rights_class=RightsLabel.THIRD_PARTY_UNCLEAR,
        content_risk=ContentRisk.TIER_3_UNCERTAIN,
        monetization_risk=MonetizationRisk.MEDIUM,
        recruitment_family="vinyl_chain",
        public_claim_policy=PublicClaimPolicy.NO_PUBLIC_CLAIM,
        kill_switch_behavior=KillSwitchBehavior.PRIVATE_ONLY,
        fallback_policy=FallbackPolicy.FAIL_CLOSED,
        existing_record_refs=["capability_record:vinyl_source.granular_wash"],
        witness_contract_id="witness.vinyl_chain.programme_opt_in",
        projection_name="vinyl_chain.granular_wash",
    )


def _row(
    *,
    classification_id: str,
    row_id: str,
    surface_id: str,
    display_name: str,
    surface_family: SurfaceFamily,
    realm: Realm,
    direction: Direction,
    effect_type: EffectType,
    medium: Medium,
    semantic_description: str,
    producer: str,
    consumer_refs: list[str],
    concrete_interface: str,
    availability_probe: AvailabilityProbe,
    privacy_class: PrivacyLabel,
    consent_policy: ConsentLabel,
    recruitment_family: str,
    public_claim_policy: PublicClaimPolicy,
    evidence_ref: str = "repo:capability-classification-inventory",
    availability_state: AvailabilityState | None = None,
    lifecycle: LifecycleState | None = None,
    recruitable: bool = True,
    kind: set[SemanticKind] | None = None,
    abstraction_level: SemanticLevel = SemanticLevel.L2,
    rights_class: RightsLabel = RightsLabel.OPERATOR_OWNED,
    content_risk: ContentRisk = ContentRisk.TIER_0_OWNED,
    monetization_risk: MonetizationRisk = MonetizationRisk.NONE,
    kill_switch_behavior: KillSwitchBehavior = KillSwitchBehavior.DEGRADE_STATUS,
    fallback_policy: FallbackPolicy = FallbackPolicy.FAIL_CLOSED,
    degraded_reason: str | None = None,
    can_acquire_sources: bool = False,
    supplied_evidence_only: bool = False,
    existing_record_refs: list[str] | None = None,
    missing_record_action: MissingRecordAction = MissingRecordAction.ADAPT_EXISTING_RECORD,
    witness_contract_id: str | None = None,
    projection_name: str | None = None,
    projection_daemon: str = "capability_classification_inventory",
    consent_person_id: str | None = None,
    consent_data_category: str | None = None,
    replacement_row_id: str | None = None,
    blocked_reason: str | None = None,
    aliases: list[dict[str, str]] | None = None,
) -> CapabilityClassificationRow:
    state = availability_state or availability_probe.expected_state
    row_lifecycle = lifecycle or _lifecycle_for_state(state)
    row_kind = kind or {SemanticKind.CAPABILITY, SemanticKind.AFFORDANCE, SemanticKind.SUBSTRATE}
    projection = None
    if recruitable and projection_name is not None:
        projection = CapabilityProjection(
            capability_name=projection_name,
            daemon=projection_daemon,
            requires_gpu=medium in {Medium.VISUAL, Medium.AUDITORY}
            and surface_family
            in {SurfaceFamily.VIDEO_SURFACE, SurfaceFamily.AUDIO_ROUTE, SurfaceFamily.MIDI_SURFACE},
            requires_network=realm in {Realm.REMOTE, Realm.HYBRID},
            latency_class=LatencyClass.FAST,
            persistence="state" if surface_family is SurfaceFamily.STATE_FILE else "none",
            priority_floor=False,
            public_capable=public_claim_policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED,
            consent_person_id=consent_person_id,
            consent_data_category=consent_data_category,
            rights_ref=f"rights:{surface_id}",
            provenance_ref=f"provenance:{surface_id}",
        )

    claim_types = _claim_types_for(public_claim_policy, direction)
    authority = _authority_for_policy(public_claim_policy)
    required_clearance = (
        ConsentLabel.PUBLIC_BROADCAST
        if public_claim_policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED
        else consent_policy
    )
    witness_requirements = (
        [witness_contract_id] if witness_contract_id else [f"witness.not_recruitable.{row_id}"]
    )
    interface_refs = [concrete_interface]
    state_surface_families = {
        SurfaceFamily.STATE_FILE,
        SurfaceFamily.FILE,
        SurfaceFamily.OBSIDIAN_NOTE,
        SurfaceFamily.COMMAND_OUTPUT,
        SurfaceFamily.BROWSER_SURFACE,
    }
    state_refs = [surface_id] if surface_family in state_surface_families else []
    if surface_family in state_surface_families:
        state_ref = surface_id
    else:
        state_ref = None

    return CapabilityClassificationRow(
        classification_id=classification_id,
        surface_id=surface_id,
        display_name=display_name,
        surface_family=surface_family,
        gibson_verb=semantic_description.split()[0],
        semantic_description=semantic_description,
        producer=producer,
        consumer_refs=consumer_refs,
        concrete_interface=concrete_interface,
        availability_probe=availability_probe,
        availability_state=state,
        state_ref=state_ref,
        evidence_ref=evidence_ref,
        privacy_class=privacy_class,
        rights_class=rights_class,
        consent_policy=consent_policy,
        claim_authority_ceiling=authority,
        can_acquire_sources=can_acquire_sources,
        supplied_evidence_only=supplied_evidence_only,
        public_claim_policy=public_claim_policy,
        kill_switch_behavior=kill_switch_behavior,
        fallback_policy=fallback_policy,
        degraded_reason=degraded_reason,
        witness_requirements=witness_requirements,
        recruitment_family=recruitment_family,
        existing_record_refs=existing_record_refs or [],
        missing_record_action=missing_record_action,
        row_id=row_id,
        semantic_version=1,
        relatum_id=surface_id,
        kind=row_kind,
        abstraction_level=abstraction_level,
        recruitable=recruitable,
        catalog_only=False,
        lifecycle=row_lifecycle,
        core_substrate_instance=False,
        semantic_descriptions=[SemanticDescription(text=semantic_description)],
        domain_tags=[
            DomainTag(domain=_domain_for_family(surface_family), subdomain=recruitment_family)
        ],
        family_tags=[
            FamilyTag(
                family=recruitment_family,
                intent_binding=_intent_binding_for_family(recruitment_family),
                dispatch_required=False,
            )
        ],
        direction=direction,
        effect_type=effect_type,
        realm=realm,
        medium=medium,
        submedium=surface_family.value,
        latency=LatencyClass.FAST,
        underlying_entity_refs=[surface_id],
        process_refs=[producer],
        state_refs=state_refs,
        substrate_refs=[f"substrate:{surface_family.value}"],
        provider_refs=[producer] if realm in {Realm.REMOTE, Realm.HYBRID} else [],
        concrete_interfaces=interface_refs,
        relations=[
            SemanticRelation(
                predicate=RelationPredicate.REALIZES,
                target_ref=f"affordance:{recruitment_family}",
                evidence_ref=evidence_ref,
            ),
            SemanticRelation(
                predicate=RelationPredicate.WITNESSES,
                target_ref=availability_probe.witness_ref,
                evidence_ref=evidence_ref,
            ),
        ],
        availability_predicate=availability_probe.witness_ref,
        freshness_ttl_s=availability_probe.stale_after_s,
        evidence_refs=[evidence_ref],
        witness_contract_id=witness_contract_id,
        authority_ceiling=authority,
        claim_types_allowed=claim_types,
        privacy_label=privacy_class,
        consent_label=consent_policy,
        required_clearance=required_clearance,
        rights_label=rights_class,
        content_risk=content_risk,
        monetization_risk=monetization_risk,
        governance_risk_reasons=[degraded_reason] if degraded_reason else [],
        dispatch_contract=DispatchContract(
            intent_family=_intent_binding_for_family(recruitment_family),
            route_by_family_only=False,
            notes="Seed inventory row; downstream consumers still route through WCS.",
        ),
        outcome_learning_policy=_outcome_policy_for(public_claim_policy, recruitable),
        projection=projection,
        aliases=cast("Any", aliases or []),
        supersedes=[],
        replacement_row_id=replacement_row_id,
        blocked_reason=blocked_reason,
    )


def _lifecycle_for_state(state: AvailabilityState) -> LifecycleState:
    if state in {AvailabilityState.AVAILABLE, AvailabilityState.PRIVATE_ONLY}:
        return LifecycleState.ACTIVE
    if state is AvailabilityState.STALE:
        return LifecycleState.STALE
    if state is AvailabilityState.DEGRADED:
        return LifecycleState.DEGRADED
    if state is AvailabilityState.DECOMMISSIONED:
        return LifecycleState.DECOMMISSIONED
    return LifecycleState.BLOCKED


def _claim_types_for(policy: PublicClaimPolicy, direction: Direction) -> set[ClaimType]:
    if policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED:
        return {
            ClaimType.INTERNAL_OBSERVATION,
            ClaimType.EVIDENCE_BOUND_CLAIM,
            ClaimType.PUBLIC_CLAIM,
        }
    if policy is PublicClaimPolicy.EVIDENCE_BOUND_ONLY:
        return {ClaimType.INTERNAL_OBSERVATION, ClaimType.EVIDENCE_BOUND_CLAIM}
    if direction in {Direction.ACT, Direction.ROUTE, Direction.COMMUNICATE}:
        return {ClaimType.PRIVATE_ACTION}
    return {ClaimType.INTERNAL_OBSERVATION}


def _authority_for_policy(policy: PublicClaimPolicy) -> AuthorityCeiling:
    if policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED:
        return AuthorityCeiling.PUBLIC_GATE_REQUIRED
    if policy is PublicClaimPolicy.EVIDENCE_BOUND_ONLY:
        return AuthorityCeiling.EVIDENCE_BOUND
    return AuthorityCeiling.INTERNAL_ONLY


def _outcome_policy_for(policy: PublicClaimPolicy, recruitable: bool) -> OutcomeLearningPolicy:
    if not recruitable:
        return OutcomeLearningPolicy.DISABLED
    if policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED:
        return OutcomeLearningPolicy.PUBLIC_WITNESS_REQUIRED
    return OutcomeLearningPolicy.PRIVATE_WITNESS_REQUIRED


def _domain_for_family(family: SurfaceFamily) -> str:
    if family in {
        SurfaceFamily.AUDIO_ROUTE,
        SurfaceFamily.MIDI_SURFACE,
        SurfaceFamily.VIDEO_SURFACE,
        SurfaceFamily.OPERATOR_APERTURE,
        SurfaceFamily.PUBLICATION_ENDPOINT,
        SurfaceFamily.PUBLIC_EVENT,
    }:
        return "studio"
    if family in {
        SurfaceFamily.MODEL_PROVIDER,
        SurfaceFamily.SEARCH_PROVIDER,
        SurfaceFamily.MCP_TOOL,
        SurfaceFamily.BROWSER_SURFACE,
        SurfaceFamily.FILE,
        SurfaceFamily.OBSIDIAN_NOTE,
        SurfaceFamily.COMMAND_OUTPUT,
    }:
        return "knowledge"
    if family in {
        SurfaceFamily.RUNTIME_SERVICE,
        SurfaceFamily.LOCAL_API,
        SurfaceFamily.DOCKER_CONTAINER,
        SurfaceFamily.INFRASTRUCTURE,
    }:
        return "system"
    if family is SurfaceFamily.COMPANION_DEVICE:
        return "operator_state"
    return "capability"


def _intent_binding_for_family(family: str) -> str:
    return f"capability_classification.{family}"
