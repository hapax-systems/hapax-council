"""World Capability Surface registry seed loader.

The seed registry is a typed declaration of known world surfaces. It is not a
runtime witness. Static rows therefore default to blocked/private/dry-run states
and downstream consumers must supply fresh evidence before treating a surface as
live, witnessed, public-safe, or monetizable.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
WORLD_CAPABILITY_REGISTRY = REPO_ROOT / "config" / "world-capability-registry.json"

REQUIRED_SURFACE_DOMAINS = frozenset(
    {
        "audio",
        "camera",
        "archive",
        "public_aperture",
        "file_obsidian",
        "browser_mcp",
        "music_midi",
        "mobile_watch",
    }
)

REQUIRED_EVIDENCE_FIELDS = frozenset(
    {
        "capability_id",
        "contract_id",
        "substrate_refs",
        "grounding_role",
        "producer",
        "source_items",
        "observation_items",
        "claim_items",
        "citations",
        "provenance",
        "freshness",
        "rights_state",
        "privacy_state",
        "gate_refs",
        "refusal_or_uncertainty",
        "tool_errors",
        "raw_source_hashes",
        "replay_refs",
        "witness_refs",
    }
)


class WCSRegistryError(ValueError):
    """Raised when the WCS registry cannot be loaded safely."""


class Direction(StrEnum):
    OBSERVE = "observe"
    EXPRESS = "express"
    ACT = "act"
    ROUTE = "route"
    RECALL = "recall"
    COMMUNICATE = "communicate"
    REGULATE = "regulate"


class GroundingStatus(StrEnum):
    NON_GROUNDING = "non_grounding"
    GROUNDING_CANDIDATE = "grounding_candidate"
    GROUNDING_REQUIRED = "grounding_required"
    PUBLIC_CLAIM_BEARING = "public_claim_bearing"


class GroundingRole(StrEnum):
    RAW_OBSERVATION = "raw_observation"
    DERIVED_OBSERVATION = "derived_observation"
    SOURCE_ACQUIRING_PROVIDER = "source_acquiring_provider"
    SUPPLIED_EVIDENCE_GENERATOR = "supplied_evidence_generator"
    NON_GROUNDING_REASONER = "non_grounding_reasoner"
    EXPRESSION_ONLY = "expression_only"
    ACTION_ONLY = "action_only"
    GOVERNANCE_REFUSAL = "governance_refusal"


class AuthorityCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    INTERNAL_ONLY = "internal_only"
    SPECULATIVE = "speculative"
    EVIDENCE_BOUND = "evidence_bound"
    POSTERIOR_BOUND = "posterior_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class EvidenceClass(StrEnum):
    ROUTE_BINDING = "route_binding"
    SIGNAL_PRESENCE = "signal_presence"
    NONBLANK_FRAME = "nonblank_frame"
    FRESH_STATE_FILE = "fresh_state_file"
    SOURCE_ITEM = "source_item"
    CITATION = "citation"
    HASH = "hash"
    MTIME = "mtime"
    TOOL_RESPONSE = "tool_response"
    TOOL_ERROR = "tool_error"
    EGRESS_ACCEPTANCE = "egress_acceptance"
    PUBLIC_URL = "public_url"
    RIGHTS_MANIFEST = "rights_manifest"
    PRIVACY_POLICY = "privacy_policy"
    GROUNDING_GATE_RESULT = "grounding_gate_result"
    PROGRAMME_BOUNDARY_EVENT = "programme_boundary_event"
    PUBLIC_EVENT_REF = "public_event_ref"
    OPERATOR_ACTION = "operator_action"
    INFERRED_CONTEXT = "inferred_context"


class PublicPrivatePosture(StrEnum):
    PRIVATE = "private"
    DRY_RUN = "dry_run"
    PUBLIC_LIVE = "public_live"
    ARCHIVE = "archive"
    DISABLED = "disabled"


class AvailabilityState(StrEnum):
    UNAVAILABLE = "unavailable"
    DORMANT = "dormant"
    DRY_RUN = "dry_run"
    PRIVATE = "private"
    MOUNTED = "mounted"
    DEGRADED = "degraded"
    PUBLIC_LIVE = "public_live"
    ARCHIVE_ONLY = "archive_only"
    BLOCKED = "blocked"


class FallbackMode(StrEnum):
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


class EvidenceEnvelopeRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_fields: list[str] = Field(min_length=1)
    required_evidence_classes: list[EvidenceClass] = Field(min_length=1)
    inferred_context_satisfies_witness: Literal[False] = False
    missing_evidence_state: Literal["blocked", "unavailable", "dry_run", "private_only"]

    @model_validator(mode="after")
    def _requires_core_fields(self) -> Self:
        missing = REQUIRED_EVIDENCE_FIELDS - set(self.required_fields)
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"evidence envelope missing required fields: {missing_text}")
        return self


class WitnessRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    witness_id: str
    evidence_classes: list[EvidenceClass] = Field(min_length=1)
    required_for: list[str] = Field(min_length=1)
    freshness_ttl_s: int | None = Field(default=None, ge=0)
    description: str

    @model_validator(mode="after")
    def _inferred_context_is_not_a_witness(self) -> Self:
        if EvidenceClass.INFERRED_CONTEXT in self.evidence_classes:
            raise ValueError("inferred_context cannot satisfy a WCS witness requirement")
        return self


class PublicClaimPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_private: bool
    claim_dry_run: bool
    claim_public_live: bool
    claim_archive: bool
    claim_monetizable: bool
    requires_egress_public_claim: bool
    requires_audio_safe: bool
    requires_grounding_gate: bool
    requires_rights_manifest: bool
    requires_privacy_public_safe: bool
    requires_provenance: bool
    requires_operator_action: bool
    allowed_surface_refs: list[str] = Field(default_factory=list)
    denied_surface_refs: list[str] = Field(default_factory=list)


class FallbackPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: FallbackMode
    reason_code: str
    reason: str


class WorldCapabilityRecord(BaseModel):
    """Typed seed row for one recruitable world capability surface."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    capability_id: str
    capability_name: str
    description: str
    daemon: str
    realm: str
    domain: str
    direction: Direction
    intent_family: str
    recruitment_family: str
    surface_refs: list[str] = Field(min_length=1)
    substrate_refs: list[str] = Field(min_length=1)
    lane_refs: list[str] = Field(default_factory=list)
    route_refs: list[str] = Field(default_factory=list)
    producer: str
    consumer_refs: list[str] = Field(default_factory=list)
    grounding_role: GroundingRole
    authority_ceiling: AuthorityCeiling
    grounding_status: GroundingStatus
    freshness_ttl_s: int | None = Field(default=None, ge=0)
    availability_state: AvailabilityState
    evidence_envelope_requirements: EvidenceEnvelopeRequirements
    witness_requirements: list[WitnessRequirement] = Field(default_factory=list)
    public_claim_policy: PublicClaimPolicy
    public_private_posture: list[PublicPrivatePosture] = Field(min_length=1)
    blocked_reasons: list[str] = Field(min_length=1)
    fallback: FallbackPolicy
    health_signal: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _fail_closed_static_seed(self) -> Self:
        if self.availability_state is AvailabilityState.PUBLIC_LIVE:
            raise ValueError("static WCS seed records cannot default to public_live")
        if self.public_claim_policy.claim_public_live:
            raise ValueError("static WCS seed records cannot claim public-live readiness")
        if self.public_claim_policy.claim_monetizable:
            raise ValueError("static WCS seed records cannot claim monetization readiness")
        if self.grounding_status is GroundingStatus.PUBLIC_CLAIM_BEARING:
            if not self.witness_requirements:
                raise ValueError("public-claim-bearing records require witnesses")
            if not self.public_claim_policy.requires_grounding_gate:
                raise ValueError("public-claim-bearing records require grounding gate policy")
        return self


class WorldCapabilityRegistry(BaseModel):
    """Typed WCS registry read model for downstream consumers."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = Field(default=None, alias="$schema")
    schema_version: Literal[1] = 1
    generated_from: list[str] = Field(min_length=1)
    records: list[WorldCapabilityRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_registry(self) -> Self:
        ids = [record.capability_id for record in self.records]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicate WCS capability ids: {', '.join(duplicates)}")

        domains = {record.domain for record in self.records}
        missing_domains = REQUIRED_SURFACE_DOMAINS - domains
        if missing_domains:
            missing_text = ", ".join(sorted(missing_domains))
            raise ValueError(f"missing required WCS seed domains: {missing_text}")
        return self

    def by_id(self) -> dict[str, WorldCapabilityRecord]:
        """Return records keyed by capability id."""

        return {record.capability_id: record for record in self.records}

    def get(self, capability_id: str) -> WorldCapabilityRecord | None:
        """Return one record, or None for unknown ids."""

        return self.by_id().get(capability_id)

    def require(self, capability_id: str) -> WorldCapabilityRecord:
        """Return one record or raise a fail-closed lookup error."""

        record = self.get(capability_id)
        if record is None:
            raise KeyError(f"unknown WCS capability: {capability_id}")
        return record

    def records_for_domain(self, domain: str) -> list[WorldCapabilityRecord]:
        """Return records for a seed domain such as audio or browser_mcp."""

        return [record for record in self.records if record.domain == domain]

    def records_for_surface_ref(self, surface_ref: str) -> list[WorldCapabilityRecord]:
        """Return records whose surface/substrate/lane/route refs include a value."""

        matches: list[WorldCapabilityRecord] = []
        for record in self.records:
            refs = (
                set(record.surface_refs)
                | set(record.substrate_refs)
                | set(record.lane_refs)
                | set(record.route_refs)
            )
            if surface_ref in refs:
                matches.append(record)
        return matches

    def blocked_reason_codes(self) -> list[str]:
        """Return all blocked reason codes present in the seed registry."""

        reasons = {reason for record in self.records for reason in record.blocked_reasons}
        return sorted(reasons)

    def public_claim_allowed(
        self,
        capability_id: str,
        readiness: Mapping[str, bool] | None = None,
    ) -> bool:
        """Fail-closed public-live claim gate for downstream smoke checks.

        Unknown capability ids, missing readiness state, blocked records,
        non-public policies, and non-public availability states all return
        False. The seed registry is intentionally expected to return False for
        every seeded capability until runtime witness tasks supply live state.
        """

        record = self.get(capability_id)
        if record is None:
            return False
        if record.availability_state is not AvailabilityState.PUBLIC_LIVE:
            return False
        if record.blocked_reasons:
            return False
        if not record.public_claim_policy.claim_public_live:
            return False

        readiness_state = readiness or {}
        required_readiness = _required_readiness_keys(record)
        return all(readiness_state.get(key) is True for key in required_readiness)


def _required_readiness_keys(record: WorldCapabilityRecord) -> list[str]:
    policy = record.public_claim_policy
    prefix = f"wcs.{record.capability_id}"
    required: list[str] = [f"{prefix}.witness_fresh"]
    if policy.requires_egress_public_claim:
        required.append(f"{prefix}.egress_public_claim")
    if policy.requires_audio_safe:
        required.append(f"{prefix}.audio_safe")
    if policy.requires_grounding_gate:
        required.append(f"{prefix}.grounding_gate")
    if policy.requires_rights_manifest:
        required.append(f"{prefix}.rights_manifest")
    if policy.requires_privacy_public_safe:
        required.append(f"{prefix}.privacy_public_safe")
    if policy.requires_provenance:
        required.append(f"{prefix}.provenance")
    if policy.requires_operator_action:
        required.append(f"{prefix}.operator_action")
    return required


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise WCSRegistryError(f"{path} did not contain a JSON object")
    return payload


def load_world_capability_registry(
    path: Path = WORLD_CAPABILITY_REGISTRY,
) -> WorldCapabilityRegistry:
    """Load the WCS seed registry, failing closed on malformed data."""

    try:
        return WorldCapabilityRegistry.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise WCSRegistryError(f"invalid WCS registry at {path}: {exc}") from exc


def world_capabilities_by_id(
    path: Path = WORLD_CAPABILITY_REGISTRY,
) -> dict[str, WorldCapabilityRecord]:
    """Convenience read access for downstream director/scheduler/scrim tasks."""

    return load_world_capability_registry(path).by_id()


__all__ = [
    "AuthorityCeiling",
    "AvailabilityState",
    "Direction",
    "EvidenceClass",
    "EvidenceEnvelopeRequirements",
    "FallbackMode",
    "FallbackPolicy",
    "GroundingRole",
    "GroundingStatus",
    "PublicClaimPolicy",
    "PublicPrivatePosture",
    "REQUIRED_EVIDENCE_FIELDS",
    "REQUIRED_SURFACE_DOMAINS",
    "WCSRegistryError",
    "WORLD_CAPABILITY_REGISTRY",
    "WitnessRequirement",
    "WorldCapabilityRecord",
    "WorldCapabilityRegistry",
    "load_world_capability_registry",
    "world_capabilities_by_id",
]
