"""Typed, content-addressed context carrier contract with no execution authority."""

from __future__ import annotations

import enum
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Annotated, Any, Literal, Protocol, Self

import toon
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

GENERATOR_VERSION = "hapax.session-context-canon.v1"


AuthorityCeiling = Literal[
    "observation_only",
    "projection_only",
    "constitutional_evidence",
]


FactFreshness = Literal["fresh", "aging", "stale", "absent", "dark", "hold"]


ContextSelectionClass = Literal[
    "selected",
    "rejected",
    "redacted",
    "stale",
    "missing",
    "contradicted",
    "loss_bearing",
]


ContextSelectionRequiredness = Literal["required", "optional"]


ProvenanceAuthority = Literal[
    "authoritative",
    "support_non_authoritative",
    "projection_only",
    "fixture_only",
]


ProvenanceKind = Literal[
    "constitutional",
    "publisher_claimed",
    "observed",
    "measured",
    "derived",
    "operator_stipulated",
    "consented",
    "absent",
    "dark",
]


ProvenanceDerivation = Literal[
    "asserted",
    "extracted",
    "inferred",
    "derived",
    "inherited",
    "measured",
    "stipulated",
]


_SOURCE_PROVENANCE_KINDS: frozenset[ProvenanceKind] = frozenset(
    {
        "constitutional",
        "publisher_claimed",
        "observed",
        "measured",
        "operator_stipulated",
        "consented",
    }
)


_PROVENANCE_DERIVATIONS = MappingProxyType(
    {
        "constitutional": frozenset({"asserted", "extracted", "inherited"}),
        "publisher_claimed": frozenset({"asserted", "extracted", "inherited"}),
        "observed": frozenset({"asserted", "extracted", "inherited", "measured"}),
        "measured": frozenset({"measured"}),
        "derived": frozenset({"inferred", "derived", "inherited"}),
        "operator_stipulated": frozenset({"stipulated"}),
        "consented": frozenset({"stipulated"}),
        "absent": frozenset(
            {"asserted", "extracted", "inferred", "derived", "inherited", "measured"}
        ),
        "dark": frozenset({"asserted", "derived", "inherited"}),
    }
)


_PROVENANCE_RECEIPT_PREFIXES = MappingProxyType(
    {
        "operator_stipulated": "receipt:operator-stipulation:",
        "consented": "receipt:consent:",
    }
)


_AUTHORITY_CEILING_RANK = MappingProxyType(
    {"projection_only": 0, "observation_only": 1, "constitutional_evidence": 2}
)


_PROVENANCE_AUTHORITY_RANK = MappingProxyType(
    {"projection_only": 0, "fixture_only": 0, "support_non_authoritative": 1, "authoritative": 2}
)


_HASH_PATTERN = r"^[0-9a-f]{64}$"


_CONTENT_ADDRESS_PATTERN = re.compile(r"^[^@\s]+@sha256:([0-9a-f]{64})$")


_ATOM_ID_PATTERN = r"^(what|how|must)\.[a-z0-9][a-z0-9._-]*$"


_JSON_SAFE_INTEGER_MAX = (1 << 53) - 1
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\s]")


def _validate_content_address(ref: str, digest: str, label: str) -> None:
    match = _CONTENT_ADDRESS_PATTERN.fullmatch(ref)
    if match is None or match.group(1) != digest:
        raise ValueError(f"{label} ref does not bind its sha256")


_LIFECYCLE_FSM_MEANING = "The active lifecycle's exact WHAT/HOW/MUST canon and projection boundary."


_LIFECYCLE_FSM_IMPLICATIONS = (
    "Every contextualized action remains bound to this exact lifecycle and canon image.",
)


_LIFECYCLE_FSM_PROVES = (
    "The projection carries the exact lifecycle WHAT/HOW/MUST image named by its hash.",
)


_LIFECYCLE_FSM_DOES_NOT_PROVE = ("Any action is authorized, leased, or effective.",)


_LIFECYCLE_FSM_BLIND_SPOTS = (
    "Runtime evidence beyond the named lifecycle canon image is not represented here.",
)


class CanonError(ValueError):
    """Typed fail-closed canon source, projection, or artifact error."""

    def __init__(self, reason_code: str, *, detail: str = "", repair_action: str) -> None:
        self.reason_code = reason_code
        self.detail = detail
        self.repair_action = repair_action
        suffix = f":{detail}" if detail else ""
        super().__init__(f"{reason_code}{suffix}; repair={repair_action}")


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ProjectionLevel(enum.StrEnum):
    FULL = "pi0"
    STATE_CONE = "pi1"
    EDGE = "pi2"
    GATE_MINIMAL = "pi3"


class _LifecycleCanonAtomCarrier(FrozenModel):
    id: str = Field(pattern=_ATOM_ID_PATTERN)
    ordinal: int = Field(ge=0, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    stratum: Literal["what", "how", "must"]
    content: str
    grounding: bool = Field(strict=True)
    applies_to: tuple[str, ...]
    source_refs: tuple[str, ...]

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value or value != value.strip() or not value.isascii():
            raise ValueError("canon atom content must be nonblank, edge-trimmed ASCII")
        return value

    @field_validator("applies_to", "source_refs")
    @classmethod
    def validate_string_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item or item != item.strip() for item in value):
            raise ValueError("canon atom list entries must be nonblank without edge whitespace")
        if len(value) != len(set(value)):
            raise ValueError("canon atom list entries must be unique")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if not self.id.startswith(f"{self.stratum}."):
            raise ValueError("canon atom id prefix must match stratum")
        if "*" in self.applies_to and self.applies_to != ("*",):
            raise ValueError("global applicability cannot be mixed with stage tokens")
        if self.stratum == "must" and self.applies_to != ("*",):
            raise ValueError("MUST atoms must apply identically to every stage")
        return self


class _LifecycleCanonSourceHashCarrier(FrozenModel):
    source_ref: str
    sha256: str = Field(pattern=_HASH_PATTERN)


class _LifecycleFsmStrataCarrier(FrozenModel):
    what: tuple[_LifecycleCanonAtomCarrier, ...] = Field(min_length=1)
    how: tuple[_LifecycleCanonAtomCarrier, ...] = Field(min_length=1)
    must: tuple[_LifecycleCanonAtomCarrier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        seen: set[str] = set()
        for stratum, atoms in (("what", self.what), ("how", self.how), ("must", self.must)):
            for atom in atoms:
                if atom.stratum != stratum or atom.id in seen:
                    raise ValueError("canon atoms must form one exact WHAT/HOW/MUST partition")
                seen.add(atom.id)
        return self


class _LifecycleStrataEnvelopeCarrier(FrozenModel):
    fsm: _LifecycleFsmStrataCarrier


class _LifecycleRenderedFsmCarrier(FrozenModel):
    what: str
    how: str
    must: str


class _LifecycleCanonKernelCarrier(FrozenModel):
    name: str
    omitted_atom_ids: tuple[str, ...]
    omitted_digest: str = Field(pattern=_HASH_PATTERN)
    distortion_class: Literal[
        "none",
        "outside_forward_cone",
        "multi_step_lookahead",
        "fsm_structure_and_procedures",
    ]

    @model_validator(mode="after")
    def validate_kernel(self) -> Self:
        if self.omitted_atom_ids != tuple(sorted(set(self.omitted_atom_ids))):
            raise ValueError("omitted_atom_ids must be sorted and unique")
        expected = _sha256(canonical_json_bytes(list(self.omitted_atom_ids)))
        if self.omitted_digest != expected:
            raise ValueError("omitted_digest does not bind omitted_atom_ids")
        return self


class LifecycleCanonImageCarrier(FrozenModel):
    """Exact canon-image wire carrier; Council retains semantic membership proof."""

    schema_id: Literal["hapax.coordination-canon.image.v1"] = Field(alias="schema")
    canon_version: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    generator_version: Literal["hapax.session-context-canon.v1"]
    projection_algorithm: Literal["hapax.sdlc-forward-cone.v1"]
    encoder_id: Literal["python-toon@0.1.3"]
    reference_tokenizer_id: Literal["hapax.ascii-lexeme.v1"]
    reference_token_count: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    stage_token: str
    level: ProjectionLevel
    projection_scope: tuple[str, ...] = Field(min_length=1)
    source_hashes: tuple[_LifecycleCanonSourceHashCarrier, ...] = Field(min_length=1)
    lifecycle_definition_hash: str = Field(pattern=_HASH_PATTERN)
    canon_hash: str = Field(pattern=_HASH_PATTERN)
    canon_id: str
    strata: _LifecycleStrataEnvelopeCarrier
    grounding_core: tuple[_LifecycleCanonAtomCarrier, ...] = Field(min_length=1)
    kernel: _LifecycleCanonKernelCarrier
    rendered_strata: _LifecycleRenderedFsmCarrier
    rendered_payload: str
    image_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_carrier(self) -> Self:
        if self.canon_id != f"coordination-canon@sha256:{self.canon_hash}":
            raise ValueError("canon_id does not bind canon_hash")
        grounding = tuple(
            sorted(
                (
                    atom
                    for atom in (
                        *self.strata.fsm.what,
                        *self.strata.fsm.how,
                        *self.strata.fsm.must,
                    )
                    if atom.grounding
                ),
                key=lambda atom: (atom.ordinal, atom.id),
            )
        )
        if grounding != self.grounding_core:
            raise ValueError("grounding_core does not match carrier grounding atoms")
        source_refs = tuple(item.source_ref for item in self.source_hashes)
        if source_refs != tuple(sorted(set(source_refs))):
            raise ValueError("source_hashes must be sorted and unique by logical source ref")
        if self.stage_token not in self.projection_scope:
            raise ValueError("projection_scope must include the image stage")
        if self.projection_scope != tuple(dict.fromkeys(self.projection_scope)):
            raise ValueError("projection_scope must be ordered and unique")
        expected_rendered = _LifecycleRenderedFsmCarrier(
            what=_render_canon_stratum(self.strata.fsm.what),
            how=_render_canon_stratum(self.strata.fsm.how),
            must=_render_canon_stratum(self.strata.fsm.must),
        )
        if self.rendered_strata.model_dump(mode="json") != expected_rendered.model_dump(
            mode="json"
        ):
            raise ValueError("rendered_strata do not bind typed WHAT/HOW/MUST strata")
        expected_payload = (
            f"FSM WHAT\n{expected_rendered.what}\n"
            f"FSM HOW\n{expected_rendered.how}\n"
            f"FSM MUST\n{expected_rendered.must}"
        )
        if self.rendered_payload != expected_payload:
            raise ValueError("rendered_payload does not bind rendered_strata")
        if self.reference_token_count != reference_token_count(expected_payload):
            raise ValueError("reference_token_count does not bind rendered_payload")
        body = self.model_dump(mode="json", by_alias=True, exclude={"image_hash"})
        if self.image_hash != _sha256(canonical_json_bytes(body)):
            raise ValueError("image_hash does not bind the carrier body")
        return self


class ContextBundleFsm(FrozenModel):
    what: str
    how: str
    must: str

    @field_validator("what", "how", "must")
    @classmethod
    def validate_stratum(cls, value: str) -> str:
        return _validate_wire_string(value)


class ContextBundleImpingement(FrozenModel):
    kind: str
    summary: str
    source_ref: str

    @field_validator("kind", "summary", "source_ref")
    @classmethod
    def validate_value(cls, value: str) -> str:
        return _validate_wire_string(value)


class ContextBundleOrientingSignal(FrozenModel):
    kind: str
    label: str
    portal_ref: str

    @field_validator("kind", "label", "portal_ref")
    @classmethod
    def validate_value(cls, value: str) -> str:
        return _validate_wire_string(value)


class ContextBundleStrata(FrozenModel):
    fsm: ContextBundleFsm
    impingements: tuple[ContextBundleImpingement, ...]
    orienting_signals: tuple[ContextBundleOrientingSignal, ...]


class ContextBundleTriAudience(FrozenModel):
    operator: str
    crow: str
    hapax: str

    @field_validator("operator", "crow", "hapax")
    @classmethod
    def validate_projection(cls, value: str) -> str:
        return _validate_wire_string(value)


class ContextBundleProvenance(FrozenModel):
    source: str
    observed_at: str
    freshness: Literal["live", "stale", "dark"]

    @field_validator("source", "observed_at")
    @classmethod
    def validate_value(cls, value: str) -> str:
        return _validate_wire_string(value)

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        try:
            observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("observed_at must be an ISO 8601 timestamp") from exc
        if observed.tzinfo is None:
            raise ValueError("observed_at requires a timezone")
        return self


class ContextBundleWire(FrozenModel):
    kind: Literal["context_bundle"]
    session_ref: str
    task_ref: str
    strata: ContextBundleStrata
    tri_audience: ContextBundleTriAudience
    provenance: ContextBundleProvenance
    demand_shape_fingerprint: str = Field(pattern=_HASH_PATTERN)

    @field_validator("session_ref", "task_ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        return _validate_wire_string(value)


_CANONICAL_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_OUTCOME_RECEIPT_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
)


def _validate_timestamp(value: str, field_name: str) -> str:
    if _CANONICAL_TIMESTAMP_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be canonical UTC RFC3339 at whole-second precision")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a real UTC timestamp") from exc
    return value


def _parse_outcome_receipt_timestamp(value: str, field_name: str) -> datetime:
    """Parse the shared OutcomeReceipt timestamp without widening carrier timestamp law."""

    if _OUTCOME_RECEIPT_TIMESTAMP_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be canonical UTC RFC3339 with microseconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a real UTC timestamp") from exc


def _validate_string_set(
    value: tuple[str, ...], field_name: str, *, allow_empty: bool = True
) -> tuple[str, ...]:
    if not allow_empty and not value:
        raise ValueError(f"{field_name} must not be empty")
    if any(_validate_wire_string(item) != item for item in value):
        raise ValueError(f"{field_name} entries must be valid strings")
    if value != tuple(sorted(set(value))):
        raise ValueError(f"{field_name} must be sorted and unique")
    return value


class LifecycleTransition(FrozenModel):
    to: str
    projection_role: Literal["advance", "branch", "repair"]
    authority_capability: str
    guards: tuple[str, ...] = Field(min_length=1)
    actions: tuple[str, ...] = Field(min_length=1)
    enforcement: Literal["declared", "enforced"]
    enforcement_ref: str | None

    @field_validator("to", "authority_capability", "enforcement_ref")
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator("guards", "actions")
    @classmethod
    def validate_string_tuple(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name, allow_empty=False)

    @model_validator(mode="after")
    def validate_enforcement(self) -> Self:
        if (self.enforcement == "enforced") != (self.enforcement_ref is not None):
            raise ValueError("enforced transitions require exactly one enforcement_ref")
        return self


class LifecycleOperationAdmission(FrozenModel):
    operation: str
    authority_capability: str
    guards: tuple[str, ...] = Field(min_length=1)
    actions: tuple[str, ...] = Field(min_length=1)
    enforcement: Literal["declared", "enforced"]
    enforcement_ref: str | None

    @field_validator("operation", "authority_capability", "enforcement_ref")
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator("guards", "actions")
    @classmethod
    def validate_string_tuple(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name, allow_empty=False)

    @model_validator(mode="after")
    def validate_enforcement(self) -> Self:
        if (self.enforcement == "enforced") != (self.enforcement_ref is not None):
            raise ValueError("enforced admissions require exactly one enforcement_ref")
        return self


class LifecycleStageDefinition(FrozenModel):
    token: str
    display_alias: str
    aliases: tuple[str, ...]
    deprecated_aliases: tuple[str, ...]
    label: str
    terminal: bool = Field(strict=True)
    blocked: bool = Field(strict=True)
    deliverable_id: str
    required_fields: tuple[str, ...] = Field(min_length=1)
    operation_admissions: tuple[LifecycleOperationAdmission, ...]
    next: tuple[LifecycleTransition, ...]
    fall: tuple[LifecycleTransition, ...]

    @field_validator("token", "display_alias", "label", "deliverable_id")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("aliases", "deprecated_aliases", "required_fields")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value, info.field_name, allow_empty=info.field_name != "required_fields"
        )

    @model_validator(mode="after")
    def validate_stage(self) -> Self:
        if self.terminal and self.blocked:
            raise ValueError("one lifecycle stage cannot be terminal and blocked")
        for edge_class in (self.next, self.fall):
            destinations = tuple(edge.to for edge in edge_class)
            if len(destinations) != len(set(destinations)):
                raise ValueError("lifecycle edges must have unique destinations per edge class")
        admissions = tuple(item.operation for item in self.operation_admissions)
        if len(admissions) != len(set(admissions)):
            raise ValueError("lifecycle operation admissions must be unique")
        return self


class LifecycleFieldProvenance(FrozenModel):
    field_path: str
    kind: Literal["observed", "proposed", "stipulated", "derived", "absent"]
    source_refs: tuple[str, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...]
    may_authorize: Literal[False]

    @field_validator("field_path")
    @classmethod
    def validate_field_path(cls, value: str) -> str:
        value = _validate_wire_string(value)
        if not value.startswith("/"):
            raise ValueError("lifecycle field provenance requires a JSON-pointer-like path")
        return value

    @field_validator("source_refs", "reason_codes")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value, info.field_name, allow_empty=info.field_name == "reason_codes"
        )

    @model_validator(mode="after")
    def validate_absence(self) -> Self:
        if (self.kind == "absent") != bool(self.reason_codes):
            raise ValueError("absent lifecycle fields require reasons; present fields do not")
        return self


class LifecycleDefinition(FrozenModel):
    schema_id: Literal["hapax.lifecycle-definition.v1"] = Field(alias="schema")
    definition_ref: str
    lifecycle_ref: str
    generation: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    profile_ref: str
    spine_ref: str
    plant_type_ref: str
    unit_type_ref: str
    initial_stage: str
    terminal_stages: tuple[str, ...] = Field(min_length=1)
    blocked_stages: tuple[str, ...] = Field(min_length=1)
    freeze_pivot: str
    question_refs: tuple[str, ...] = Field(min_length=1)
    obligation_refs: tuple[str, ...] = Field(min_length=1)
    instrument_refs: tuple[str, ...] = Field(min_length=1)
    sufficiency_predicates: tuple[str, ...] = Field(min_length=1)
    terminal_conditions: tuple[str, ...] = Field(min_length=1)
    migration_refs: tuple[str, ...]
    recovery_refs: tuple[str, ...] = Field(min_length=1)
    source_ref: str
    source_hash: str = Field(pattern=_HASH_PATTERN)
    field_provenance: tuple[LifecycleFieldProvenance, ...] = Field(min_length=1)
    stages: tuple[LifecycleStageDefinition, ...] = Field(min_length=1)
    definition_hash: str = Field(pattern=_HASH_PATTERN)
    may_authorize: Literal[False]

    @field_validator(
        "definition_ref",
        "lifecycle_ref",
        "profile_ref",
        "spine_ref",
        "plant_type_ref",
        "unit_type_ref",
        "initial_stage",
        "freeze_pivot",
        "source_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator(
        "question_refs",
        "obligation_refs",
        "instrument_refs",
        "sufficiency_predicates",
        "terminal_conditions",
        "migration_refs",
        "recovery_refs",
    )
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value,
            info.field_name,
            allow_empty=info.field_name == "migration_refs",
        )

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        tokens = tuple(stage.token for stage in self.stages)
        if len(tokens) != len(set(tokens)):
            raise ValueError("lifecycle stage tokens must be unique")
        if self.initial_stage not in tokens or self.freeze_pivot not in tokens:
            raise ValueError("lifecycle initial stage and freeze pivot must exist")
        terminals = tuple(stage.token for stage in self.stages if stage.terminal)
        blocked = tuple(stage.token for stage in self.stages if stage.blocked)
        if self.terminal_stages != terminals or self.blocked_stages != blocked:
            raise ValueError("terminal and blocked stage indexes must match lifecycle rows")
        by_token = {stage.token: stage for stage in self.stages}
        for stage in self.stages:
            for edge in (*stage.next, *stage.fall):
                if edge.to not in by_token:
                    raise ValueError("lifecycle transition target must exist")
        provenance_paths = tuple(item.field_path for item in self.field_provenance)
        expected_paths = tuple(
            sorted(
                {
                    "/blocked_stages",
                    "/freeze_pivot",
                    "/generation",
                    "/initial_stage",
                    "/instrument_refs",
                    "/lifecycle_ref",
                    "/may_authorize",
                    "/migration_refs",
                    "/obligation_refs",
                    "/plant_type_ref",
                    "/profile_ref",
                    "/question_refs",
                    "/recovery_refs",
                    "/source_hash",
                    "/source_ref",
                    "/spine_ref",
                    "/sufficiency_predicates",
                    "/terminal_conditions",
                    "/terminal_stages",
                    "/unit_type_ref",
                    *(f"/stages/{stage.token}" for stage in self.stages),
                }
            )
        )
        if provenance_paths != expected_paths:
            raise ValueError("field_provenance must cover every lifecycle definition field")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"definition_ref", "definition_hash"}
        )
        expected_hash = _domain_hash("hapax.lifecycle-definition.v1", body)
        if self.definition_hash != expected_hash:
            raise ValueError("definition_hash does not bind the lifecycle definition")
        if self.definition_ref != f"lifecycle-definition@sha256:{expected_hash}":
            raise ValueError("definition_ref does not bind definition_hash")
        return self


class CanonicalJsonObject(FrozenModel):
    canonical_json: str
    sha256: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_object(self) -> Self:
        def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"canonical JSON contains duplicate key: {key}")
                result[key] = value
            return result

        try:
            parsed = json.loads(self.canonical_json, object_pairs_hook=unique_pairs)
        except json.JSONDecodeError as exc:
            raise ValueError("canonical_json must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("canonical_json must encode one JSON object")
        expected = canonical_json_bytes(parsed)
        if self.canonical_json != expected.decode("utf-8"):
            raise ValueError("canonical_json must use the contract canonical encoding")
        if self.sha256 != _sha256(expected):
            raise ValueError("canonical JSON sha256 does not bind canonical_json")
        return self


class DemandShapeDescriptor(FrozenModel):
    schema_id: Literal["hapax.demand-shape-descriptor.v1"] = Field(alias="schema")
    descriptor_ref: str
    session_ref: str
    strategy: CanonicalJsonObject
    strata: CanonicalJsonObject
    canon: CanonicalJsonObject
    position_basis: CanonicalJsonObject
    offered_affordances: tuple[str, ...]
    provenance_generation: str
    policy_generation: str
    audience_policy: CanonicalJsonObject
    kernel: CanonicalJsonObject
    budget: CanonicalJsonObject
    demand_shape_fingerprint: str = Field(pattern=_HASH_PATTERN)
    may_authorize: Literal[False]

    @field_validator("descriptor_ref", "session_ref", "provenance_generation", "policy_generation")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("offered_affordances")
    @classmethod
    def validate_affordances(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_string_set(value, "offered_affordances")

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"descriptor_ref", "demand_shape_fingerprint"},
        )
        expected_hash = _domain_hash("hapax.demand-shape-descriptor.v1", body)
        if self.demand_shape_fingerprint != expected_hash:
            raise ValueError("demand_shape_fingerprint does not bind the complete descriptor")
        if self.descriptor_ref != f"demand-shape@sha256:{expected_hash}":
            raise ValueError("descriptor_ref does not bind demand_shape_fingerprint")
        return self


class ContextState(FrozenModel):
    value_state: Literal[
        "present", "partial", "absent", "dark", "hold", "stale", "refused", "uncertain"
    ]
    reason_codes: tuple[str, ...]

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_string_set(value, "reason_codes")

    @model_validator(mode="after")
    def validate_reasons(self) -> Self:
        if (self.value_state == "present") == bool(self.reason_codes):
            raise ValueError("present has no reason codes; every non-present state requires them")
        return self


def _validate_fact_state_freshness(
    freshness_state: FactFreshness,
    state: ContextState,
    *,
    label: str,
) -> None:
    allowed_states = {
        "fresh": frozenset({"present", "partial", "uncertain"}),
        "aging": frozenset({"present", "partial", "uncertain"}),
        "stale": frozenset({"partial", "uncertain", "stale"}),
        "absent": frozenset({"absent"}),
        "dark": frozenset({"dark"}),
        "hold": frozenset({"hold", "refused"}),
    }[freshness_state]
    if state.value_state not in allowed_states:
        raise ValueError(
            f"{label} freshness and value state are inconsistent: "
            f"{freshness_state} cannot carry {state.value_state}"
        )


class CanonicalDecimal(FrozenModel):
    value: str
    unit: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        value = _validate_wire_string(value)
        if re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is None:
            raise ValueError("canonical decimals must use plain base-10 notation")
        try:
            Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("canonical decimal is invalid") from exc
        return value

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        return _validate_wire_string(value)


class ContextScope(FrozenModel):
    scope_ref: str
    scope_hash: str = Field(pattern=_HASH_PATTERN)
    scope_id: str
    scope_type_ref: str
    subject_refs: tuple[str, ...] = Field(min_length=1)
    parent_scope_refs: tuple[str, ...]
    environment_ref: str
    lifecycle_scope_ref: str
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "scope_ref", "scope_id", "scope_type_ref", "environment_ref", "lifecycle_scope_ref"
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("subject_refs", "parent_scope_refs")
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value, info.field_name, allow_empty=info.field_name == "parent_scope_refs"
        )

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.scope_ref in self.parent_scope_refs:
            raise ValueError("a context scope cannot parent itself")
        body = self.model_dump(mode="json", by_alias=True, exclude={"scope_ref", "scope_hash"})
        expected_hash = _domain_hash("hapax.context-scope.v1", body)
        if self.scope_hash != expected_hash:
            raise ValueError("scope_hash does not bind the context scope")
        if self.scope_ref != f"context-scope@sha256:{expected_hash}":
            raise ValueError("scope_ref does not bind scope_hash")
        return self


class TemporalCoordinate(FrozenModel):
    temporal_ref: str
    temporal_hash: str = Field(pattern=_HASH_PATTERN)
    clock_domain: str
    event_time_start: str
    event_time_end: str
    processing_time: str
    valid_from: str
    valid_until: str
    window_ref: str
    scale_ref: str
    tense: Literal["retention", "impression", "protention", "not_applicable"]
    watermark: str | None
    completeness: ContextState
    lateness: Literal["on_time", "late", "corrected", "unknown", "not_applicable"]
    parent_span_refs: tuple[str, ...]
    correction_refs: tuple[str, ...]
    forecast_horizon_ref: str | None
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "temporal_ref",
        "clock_domain",
        "window_ref",
        "scale_ref",
        "watermark",
        "forecast_horizon_ref",
    )
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator(
        "event_time_start",
        "event_time_end",
        "processing_time",
        "valid_from",
        "valid_until",
    )
    @classmethod
    def validate_timestamp(cls, value: str, info: Any) -> str:
        return _validate_timestamp(value, info.field_name)

    @field_validator("parent_span_refs", "correction_refs")
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name)

    @model_validator(mode="after")
    def validate_coordinate(self) -> Self:
        if not (self.event_time_start <= self.event_time_end <= self.processing_time):
            raise ValueError("temporal event time must precede processing time")
        if self.valid_from > self.valid_until:
            raise ValueError("temporal validity interval is reversed")
        if self.watermark is not None:
            _validate_timestamp(self.watermark, "watermark")
            if self.watermark > self.processing_time:
                raise ValueError("temporal watermark cannot follow processing time")
        if (self.tense == "protention") != (self.forecast_horizon_ref is not None):
            raise ValueError("only protention carries a forecast horizon")
        if self.lateness == "corrected" and not self.correction_refs:
            raise ValueError("corrected temporal coordinates require correction refs")
        if self.temporal_ref in {*self.parent_span_refs, *self.correction_refs}:
            raise ValueError("a temporal coordinate cannot parent or correct itself")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"temporal_ref", "temporal_hash"}
        )
        expected_hash = _domain_hash("hapax.temporal-coordinate.v1", body)
        if self.temporal_hash != expected_hash:
            raise ValueError("temporal_hash does not bind the coordinate")
        if self.temporal_ref != f"temporal-coordinate@sha256:{expected_hash}":
            raise ValueError("temporal_ref does not bind temporal_hash")
        return self


class ResolutionCoordinate(FrozenModel):
    resolution_ref: str
    resolution_hash: str = Field(pattern=_HASH_PATTERN)
    scope_ref: str
    temporal_ref: str
    subject_resolution_ref: str
    lifecycle_resolution_ref: str
    semantic_resolution_ref: str
    environment_resolution_ref: str
    aggregation_ref: str
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "resolution_ref",
        "scope_ref",
        "temporal_ref",
        "subject_resolution_ref",
        "lifecycle_resolution_ref",
        "semantic_resolution_ref",
        "environment_resolution_ref",
        "aggregation_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"resolution_ref", "resolution_hash"}
        )
        expected_hash = _domain_hash("hapax.resolution-coordinate.v1", body)
        if self.resolution_hash != expected_hash:
            raise ValueError("resolution_hash does not bind the coordinate")
        if self.resolution_ref != f"resolution-coordinate@sha256:{expected_hash}":
            raise ValueError("resolution_ref does not bind resolution_hash")
        return self


class DemandShapeBinding(FrozenModel):
    fingerprint: str = Field(pattern=_HASH_PATTERN)
    descriptor: DemandShapeDescriptor | None
    state: ContextState
    may_authorize: Literal[False]

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.descriptor is not None:
            if self.fingerprint != self.descriptor.demand_shape_fingerprint:
                raise ValueError("demand binding differs from its descriptor")
            if self.state.value_state != "present":
                raise ValueError("a complete demand descriptor must be present")
        elif self.state.value_state not in {"partial", "absent", "dark"}:
            raise ValueError("a missing demand descriptor must be partial, absent, or dark")
        return self


class ContextConfidence(FrozenModel):
    word: Literal["high", "medium", "low", "absent"]
    method: Literal[
        "deterministic", "statistical", "llm_review", "human_asserted", "inherited", "absent"
    ]
    evidence_refs: tuple[str, ...]
    calibration_ref: str | None
    calibration_metric: CanonicalDecimal | None
    validity_domain_refs: tuple[str, ...]
    distribution_state: Literal["in_domain", "out_of_distribution", "unknown", "not_applicable"]
    abstained: bool = Field(strict=True)

    @field_validator("calibration_ref")
    @classmethod
    def validate_calibration_ref(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator("evidence_refs", "validity_domain_refs")
    @classmethod
    def validate_evidence_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name)

    @model_validator(mode="after")
    def validate_absence(self) -> Self:
        absent = self.word == "absent" or self.method == "absent"
        if absent != (self.word == "absent" and self.method == "absent"):
            raise ValueError("confidence word and method must agree on absence")
        if absent == bool(self.evidence_refs):
            raise ValueError("absent confidence has no evidence; non-absent confidence requires it")
        if (self.calibration_ref is None) != (self.calibration_metric is None):
            raise ValueError("calibration ref and metric must be jointly present or absent")
        model_derived = self.method in {"statistical", "llm_review"}
        if (
            model_derived
            and (self.calibration_ref is None or self.distribution_state != "in_domain")
            and not self.abstained
        ):
            raise ValueError("uncalibrated or out-of-domain model confidence must abstain")
        if self.abstained and self.word == "high":
            raise ValueError("abstention cannot carry high confidence")
        if self.distribution_state == "not_applicable" and self.validity_domain_refs:
            raise ValueError("not-applicable distribution state has no validity domain")
        if self.distribution_state != "not_applicable" and not self.validity_domain_refs:
            raise ValueError("distribution-aware confidence requires a validity domain")
        return self


class SourceAdmission(FrozenModel):
    admission_ref: str
    admission_hash: str = Field(pattern=_HASH_PATTERN)
    admission_id: str
    source_ref: str
    source_kind: str
    schema_ref: str
    unit_semantics_ref: str
    join_keys: tuple[str, ...] = Field(min_length=1)
    scope_ref: str
    temporal_ref: str
    resolution_ref: str
    producer_ref: str
    method_ref: str
    verification_refs: tuple[str, ...] = Field(min_length=1)
    policy_refs: tuple[str, ...] = Field(min_length=1)
    authority_ceiling: AuthorityCeiling
    supported_provenance_kinds: tuple[ProvenanceKind, ...] = Field(min_length=1)
    consumer_contract_refs: tuple[str, ...] = Field(min_length=1)
    availability: ContextState
    freshness_state: FactFreshness
    cost: CanonicalJsonObject
    latency: CanonicalJsonObject
    probe_witness_refs: tuple[str, ...]
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "admission_ref",
        "admission_id",
        "source_ref",
        "source_kind",
        "schema_ref",
        "unit_semantics_ref",
        "scope_ref",
        "temporal_ref",
        "resolution_ref",
        "producer_ref",
        "method_ref",
        "authority_ceiling",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator(
        "join_keys",
        "verification_refs",
        "policy_refs",
        "supported_provenance_kinds",
        "consumer_contract_refs",
        "probe_witness_refs",
    )
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value, info.field_name, allow_empty=info.field_name == "probe_witness_refs"
        )

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        presently_available = self.availability.value_state == "present"
        presently_usable = self.freshness_state in {"fresh", "aging"}
        if presently_available != presently_usable:
            raise ValueError("source availability and freshness must agree on present usability")
        unsupported_kinds = set(self.supported_provenance_kinds) - _SOURCE_PROVENANCE_KINDS
        if unsupported_kinds:
            raise ValueError("source admissions can support only direct provenance kinds")
        if (
            "constitutional" in self.supported_provenance_kinds
            and self.authority_ceiling != "constitutional_evidence"
        ):
            raise ValueError(
                "constitutional provenance support requires a constitutional authority ceiling"
            )
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"admission_ref", "admission_hash"}
        )
        expected_hash = _domain_hash("hapax.source-admission.v1", body)
        if self.admission_hash != expected_hash:
            raise ValueError("admission_hash does not bind the source admission")
        if self.admission_ref != f"source-admission@sha256:{expected_hash}":
            raise ValueError("admission_ref does not bind admission_hash")
        return self


class ObservationEnvelope(FrozenModel):
    observation_ref: str
    observation_hash: str = Field(pattern=_HASH_PATTERN)
    observation_id: str
    source_admission_ref: str
    scope_ref: str
    temporal_ref: str
    resolution_ref: str
    subject_ref: str
    payload: CanonicalJsonObject
    producer_ref: str
    method_ref: str
    config_ref: str
    authority_ceiling: AuthorityCeiling
    witness_refs: tuple[str, ...] = Field(min_length=1)
    source_refs: tuple[str, ...]
    state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "observation_ref",
        "observation_id",
        "source_admission_ref",
        "scope_ref",
        "temporal_ref",
        "resolution_ref",
        "subject_ref",
        "producer_ref",
        "method_ref",
        "config_ref",
        "authority_ceiling",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("witness_refs", "source_refs")
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value, info.field_name, allow_empty=info.field_name == "source_refs"
        )

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"observation_ref", "observation_hash"}
        )
        expected_hash = _domain_hash("hapax.observation-envelope.v1", body)
        if self.observation_hash != expected_hash:
            raise ValueError("observation_hash does not bind the observation")
        if self.observation_ref != f"observation-envelope@sha256:{expected_hash}":
            raise ValueError("observation_ref does not bind observation_hash")
        return self


class DerivationRecord(FrozenModel):
    derivation_ref: str
    derivation_hash: str = Field(pattern=_HASH_PATTERN)
    derivation_id: str
    input_observation_refs: tuple[str, ...]
    input_fact_refs: tuple[str, ...]
    output_refs: tuple[str, ...] = Field(min_length=1)
    method_ref: str
    method_version_ref: str
    calibration_ref: str | None
    calibration_metric: CanonicalDecimal | None
    validity_domain_refs: tuple[str, ...]
    distribution_state: Literal["in_domain", "out_of_distribution", "unknown", "not_applicable"]
    abstained: bool = Field(strict=True)
    air_policy_generation: str
    state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "derivation_ref",
        "derivation_id",
        "method_ref",
        "method_version_ref",
        "calibration_ref",
        "air_policy_generation",
    )
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator(
        "input_observation_refs", "input_fact_refs", "output_refs", "validity_domain_refs"
    )
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value,
            info.field_name,
            allow_empty=info.field_name
            in {"input_observation_refs", "input_fact_refs", "validity_domain_refs"},
        )

    @model_validator(mode="after")
    def validate_derivation(self) -> Self:
        if not self.input_observation_refs and not self.input_fact_refs:
            raise ValueError("derivation records require at least one input")
        if (self.calibration_ref is None) != (self.calibration_metric is None):
            raise ValueError("derivation calibration ref and metric must be jointly present")
        if self.distribution_state in {"out_of_distribution", "unknown"} and not self.abstained:
            raise ValueError("unknown or out-of-domain derivations must abstain")
        if self.abstained and self.state.value_state == "present":
            raise ValueError("abstained derivations cannot be present")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"derivation_ref", "derivation_hash"}
        )
        expected_hash = _domain_hash("hapax.derivation-record.v1", body)
        if self.derivation_hash != expected_hash:
            raise ValueError("derivation_hash does not bind the derivation")
        if self.derivation_ref != f"derivation-record@sha256:{expected_hash}":
            raise ValueError("derivation_ref does not bind derivation_hash")
        return self


class ContextProvenance(FrozenModel):
    kind: ProvenanceKind
    source_refs: tuple[str, ...] = Field(min_length=1)
    producer_ref: str
    derivation: ProvenanceDerivation
    authority_level: ProvenanceAuthority
    generation: str
    policy_generation: str
    observed_at: str
    produced_at: str
    stale_after: str

    @field_validator("producer_ref", "generation", "policy_generation")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("source_refs")
    @classmethod
    def validate_source_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_string_set(value, "source_refs", allow_empty=False)

    @field_validator("observed_at", "produced_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str, info: Any) -> str:
        return _validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if not (self.observed_at <= self.produced_at <= self.stale_after):
            raise ValueError("provenance timestamps must be observed <= produced <= stale_after")
        if self.derivation not in _PROVENANCE_DERIVATIONS[self.kind]:
            raise ValueError("provenance kind and derivation semantics are inconsistent")
        if self.kind in {"publisher_claimed", "derived", "absent", "dark"}:
            if self.authority_level == "authoritative":
                raise ValueError(
                    "support, derived, absent, and dark provenance cannot be authoritative"
                )
        return self


class ContextAirPolicy(FrozenModel):
    operator_private: Literal["allow", "redact", "deny"]
    yard_context: Literal["allow", "redact", "deny"]
    hapax_substrate: Literal["allow", "redact", "deny"]
    public_or_air: Literal["allow", "redact", "deny"]
    derived_channel_sealed: Literal[True]


class ContextAirBinding(FrozenModel):
    object_kind: Literal[
        "position",
        "demand_shape",
        "scope",
        "temporal",
        "resolution",
        "source_admission",
        "observation",
        "derivation",
        "relation",
        "action",
        "impingement",
        "estimate",
        "lens",
        "constellation",
        "signal",
        "portal",
        "learning_receipt",
        "event",
        "orientation",
        "lifecycle_possibility",
    ]
    object_ref: str
    air: ContextAirPolicy

    @field_validator("object_ref")
    @classmethod
    def validate_object_ref(cls, value: str) -> str:
        return _validate_wire_string(value)


class ContextFact(FrozenModel):
    fact_id: str
    fact_type: str
    subject_ref: str
    scope_ref: str
    temporal_ref: str
    resolution_ref: str
    derivation_ref: str
    data: CanonicalJsonObject
    unit: str | None
    meaning: str
    implications: tuple[str, ...] = Field(min_length=1)
    proves: tuple[str, ...]
    does_not_prove: tuple[str, ...] = Field(min_length=1)
    blind_spots: tuple[str, ...] = Field(min_length=1)
    provenance: ContextProvenance
    freshness_state: FactFreshness
    confidence: ContextConfidence
    air: ContextAirPolicy
    state: ContextState
    relation_refs: tuple[str, ...]
    legal_next: tuple[str, ...]
    prohibited_next: tuple[str, ...]
    expected_receipt_refs: tuple[str, ...]
    supersedes_refs: tuple[str, ...]
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "fact_id",
        "fact_type",
        "subject_ref",
        "scope_ref",
        "temporal_ref",
        "resolution_ref",
        "derivation_ref",
        "meaning",
        "unit",
    )
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator(
        "implications",
        "proves",
        "does_not_prove",
        "blind_spots",
        "relation_refs",
        "legal_next",
        "prohibited_next",
        "expected_receipt_refs",
        "supersedes_refs",
    )
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value,
            info.field_name,
            allow_empty=info.field_name
            in {
                "proves",
                "relation_refs",
                "legal_next",
                "prohibited_next",
                "expected_receipt_refs",
                "supersedes_refs",
            },
        )

    @model_validator(mode="after")
    def validate_fact(self) -> Self:
        _validate_fact_state_freshness(self.freshness_state, self.state, label="fact")
        if self.provenance.kind == "absent" and (
            self.state.value_state != "absent" or self.freshness_state != "absent"
        ):
            raise ValueError("absent fact provenance requires an absent fact carrier")
        if self.provenance.kind == "dark" and (
            self.state.value_state != "dark" or self.freshness_state != "dark"
        ):
            raise ValueError("dark fact provenance requires a dark fact carrier")
        if self.state.value_state in {"absent", "dark", "hold", "refused"}:
            if self.data.canonical_json != "{}":
                raise ValueError("absent, dark, held, and refused facts cannot fabricate data")
        if self.confidence.abstained and self.state.value_state == "present":
            raise ValueError("abstained facts cannot be present")
        if set(self.legal_next) & set(self.prohibited_next):
            raise ValueError("one fact cannot mark an action both legal and prohibited")
        return self


class ContextRelation(FrozenModel):
    relation_id: str
    source_fact_ref: str
    target_fact_ref: str
    relation_type: str
    meaning: str
    provenance_refs: tuple[str, ...] = Field(min_length=1)
    state: ContextState
    may_authorize: Literal[False]

    @field_validator(
        "relation_id", "source_fact_ref", "target_fact_ref", "relation_type", "meaning"
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("provenance_refs")
    @classmethod
    def validate_provenance_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_string_set(value, "provenance_refs", allow_empty=False)


class LifecycleGuardEvidence(FrozenModel):
    guard: str
    disposition: Literal["satisfied", "unsatisfied", "unknown"]
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    may_authorize: Literal[False]

    @field_validator("guard")
    @classmethod
    def validate_guard(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        checked = _validate_string_set(value, "evidence_refs", allow_empty=False)
        if any(ref.startswith("portal-consumption@sha256:") for ref in checked):
            raise ValueError(
                "portal consumption is offer-plane evidence and cannot satisfy a guard"
            )
        return checked


class ContextAction(FrozenModel):
    action_id: str
    label: str
    disposition: Literal["legal", "prohibited", "unavailable"]
    position_ref: str
    action_class: str
    operation: str
    lifecycle_operation: str | None
    transition_to: str | None
    transition_edge: Literal["next", "fall"] | None
    admission_ref: str | None
    guard_evidence: tuple[LifecycleGuardEvidence, ...]
    source_fact_refs: tuple[str, ...] = Field(min_length=1)
    why: str
    predicted_effect: str
    recovery: str
    expected_receipt_ref: str
    state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "action_id",
        "label",
        "position_ref",
        "action_class",
        "operation",
        "lifecycle_operation",
        "transition_to",
        "admission_ref",
        "why",
        "predicted_effect",
        "recovery",
        "expected_receipt_ref",
    )
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator("source_fact_refs")
    @classmethod
    def validate_source_fact_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_string_set(value, "source_fact_refs", allow_empty=False)

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.disposition == "legal" and self.state.value_state != "present":
            raise ValueError("a legal action must be presently supported")
        if self.disposition != "legal" and self.state.value_state == "present":
            raise ValueError("prohibited and unavailable actions require a non-present state")
        guard_names = tuple(item.guard for item in self.guard_evidence)
        if guard_names != tuple(sorted(set(guard_names))):
            raise ValueError("lifecycle guard evidence must be sorted and unique")
        if self.action_class == "lifecycle_operation":
            if (
                self.lifecycle_operation is None
                or self.operation != self.lifecycle_operation
                or self.transition_to is not None
                or self.transition_edge is not None
                or self.admission_ref is None
            ):
                raise ValueError("lifecycle operations require only operation and admission refs")
        elif self.action_class == "lifecycle_transition":
            if (
                self.operation != "lifecycle.transition"
                or self.transition_to is None
                or self.transition_edge is None
                or self.lifecycle_operation is not None
                or self.admission_ref is None
            ):
                raise ValueError("lifecycle transitions require target, edge, and admission refs")
        elif self.operation == "lifecycle.transition":
            raise ValueError("lifecycle.transition requires the lifecycle transition class")
        elif any(
            value is not None
            for value in (
                self.lifecycle_operation,
                self.transition_to,
                self.transition_edge,
                self.admission_ref,
            )
        ):
            raise ValueError("non-lifecycle actions cannot carry lifecycle admission fields")
        if self.action_class not in {"lifecycle_operation", "lifecycle_transition"}:
            if self.guard_evidence:
                raise ValueError("non-lifecycle actions cannot carry lifecycle guard evidence")
        else:
            if not self.guard_evidence:
                raise ValueError("lifecycle actions require typed guard evidence")
            all_satisfied = all(item.disposition == "satisfied" for item in self.guard_evidence)
            if (self.disposition == "legal") != all_satisfied:
                raise ValueError("lifecycle action legality must equal declared guard satisfaction")
        return self


class ContextImpingement(FrozenModel):
    impingement_id: str
    kind: str
    summary: str
    source_fact_refs: tuple[str, ...] = Field(min_length=1)
    protects: tuple[str, ...] = Field(min_length=1)
    legal_next: tuple[str, ...]
    state: ContextState
    may_authorize: Literal[False]

    @field_validator("impingement_id", "kind", "summary")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("source_fact_refs", "protects", "legal_next")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value, info.field_name, allow_empty=info.field_name == "legal_next"
        )


class SignalValueAxis(FrozenModel):
    value: CanonicalDecimal | None
    state: ContextState
    evidence_refs: tuple[str, ...]
    method_ref: str

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_string_set(value, "evidence_refs")

    @field_validator("method_ref")
    @classmethod
    def validate_method_ref(cls, value: str) -> str:
        return _validate_wire_string(value)

    @model_validator(mode="after")
    def validate_axis(self) -> Self:
        if (self.state.value_state == "present") != (self.value is not None):
            raise ValueError("present signal-value axes require a value; unavailable axes omit it")
        if self.value is not None and not self.evidence_refs:
            raise ValueError("scored signal-value axes require evidence refs")
        return self


class OrientationValueVector(FrozenModel):
    why_now: SignalValueAxis
    coverage_gain: SignalValueAxis
    decision_discrimination: SignalValueAxis
    boundary_visibility: SignalValueAxis
    continuity_restoration: SignalValueAxis
    capability_opportunity: SignalValueAxis
    recovery_leverage: SignalValueAxis
    dependency_leverage: SignalValueAxis
    attention_cost: SignalValueAxis
    confidence: SignalValueAxis
    authority_air_risk: SignalValueAxis


def _orientation_value_axes(
    vector: OrientationValueVector,
) -> tuple[SignalValueAxis, ...]:
    return tuple(getattr(vector, field_name) for field_name in OrientationValueVector.model_fields)


def _orientation_value_evidence_refs(
    vector: OrientationValueVector,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                evidence_ref
                for axis in _orientation_value_axes(vector)
                for evidence_ref in axis.evidence_refs
            }
        )
    )


class SignalEstimate(FrozenModel):
    estimate_ref: str
    estimate_hash: str = Field(pattern=_HASH_PATTERN)
    estimate_id: str
    kind: str
    position_ref: str
    scope_ref: str
    temporal_ref: str
    resolution_ref: str
    source_fact_refs: tuple[str, ...] = Field(min_length=1)
    derivation_ref: str
    value: CanonicalJsonObject
    confidence: ContextConfidence
    state: ContextState
    supersedes_refs: tuple[str, ...]
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "estimate_ref",
        "estimate_id",
        "kind",
        "position_ref",
        "scope_ref",
        "temporal_ref",
        "resolution_ref",
        "derivation_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("source_fact_refs", "supersedes_refs")
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value, info.field_name, allow_empty=info.field_name == "supersedes_refs"
        )

    @model_validator(mode="after")
    def validate_estimate(self) -> Self:
        if self.confidence.abstained and self.state.value_state == "present":
            raise ValueError("abstained signal estimates cannot be present")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"estimate_ref", "estimate_hash"}
        )
        expected_hash = _domain_hash("hapax.signal-estimate.v1", body)
        if self.estimate_hash != expected_hash:
            raise ValueError("estimate_hash does not bind the signal estimate")
        if self.estimate_ref != f"signal-estimate@sha256:{expected_hash}":
            raise ValueError("estimate_ref does not bind estimate_hash")
        return self


class SignalLens(FrozenModel):
    lens_ref: str
    lens_hash: str = Field(pattern=_HASH_PATTERN)
    lens_id: str
    audience: Literal["operator_private", "yard_context", "hapax_substrate"]
    purpose: str
    scope_selector_refs: tuple[str, ...] = Field(min_length=1)
    resolution_selector_refs: tuple[str, ...] = Field(min_length=1)
    constraint_mask_refs: tuple[str, ...] = Field(min_length=1)
    constraint_mask_receipt_ref: str
    utility_weights: CanonicalJsonObject
    aggregation_ref: str
    omission_policy_ref: str
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "lens_ref",
        "lens_id",
        "purpose",
        "constraint_mask_receipt_ref",
        "aggregation_ref",
        "omission_policy_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("scope_selector_refs", "resolution_selector_refs", "constraint_mask_refs")
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name, allow_empty=False)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        body = self.model_dump(mode="json", by_alias=True, exclude={"lens_ref", "lens_hash"})
        expected_hash = _domain_hash("hapax.signal-lens.v1", body)
        if self.lens_hash != expected_hash:
            raise ValueError("lens_hash does not bind the signal lens")
        if self.lens_ref != f"signal-lens@sha256:{expected_hash}":
            raise ValueError("lens_ref does not bind lens_hash")
        return self


class SignalConstellation(FrozenModel):
    constellation_ref: str
    constellation_hash: str = Field(pattern=_HASH_PATTERN)
    constellation_id: str
    target_ref: str
    lens_ref: str
    scope_ref: str
    resolution_ref: str
    member_estimate_refs: tuple[str, ...] = Field(min_length=1)
    relation_refs: tuple[str, ...]
    uncovered_source_refs: tuple[str, ...]
    aggregation_ref: str
    loss_manifest_ref: str
    state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "constellation_ref",
        "constellation_id",
        "target_ref",
        "lens_ref",
        "scope_ref",
        "resolution_ref",
        "aggregation_ref",
        "loss_manifest_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("member_estimate_refs", "relation_refs", "uncovered_source_refs")
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value,
            info.field_name,
            allow_empty=info.field_name in {"relation_refs", "uncovered_source_refs"},
        )

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected_loss_ref = signal_constellation_loss_manifest_ref(
            target_ref=self.target_ref,
            lens_ref=self.lens_ref,
            scope_ref=self.scope_ref,
            resolution_ref=self.resolution_ref,
            member_estimate_refs=self.member_estimate_refs,
            relation_refs=self.relation_refs,
            uncovered_source_refs=self.uncovered_source_refs,
            aggregation_ref=self.aggregation_ref,
        )
        if self.loss_manifest_ref != expected_loss_ref:
            raise ValueError("signal constellation loss manifest must bind its exact coverage")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"constellation_ref", "constellation_hash"}
        )
        expected_hash = _domain_hash("hapax.signal-constellation.v1", body)
        if self.constellation_hash != expected_hash:
            raise ValueError("constellation_hash does not bind the signal constellation")
        if self.constellation_ref != f"signal-constellation@sha256:{expected_hash}":
            raise ValueError("constellation_ref does not bind constellation_hash")
        return self


def signal_constellation_loss_manifest_ref(
    *,
    target_ref: str,
    lens_ref: str,
    scope_ref: str,
    resolution_ref: str,
    member_estimate_refs: tuple[str, ...],
    relation_refs: tuple[str, ...],
    uncovered_source_refs: tuple[str, ...],
    aggregation_ref: str,
) -> str:
    body = {
        "target_ref": target_ref,
        "lens_ref": lens_ref,
        "scope_ref": scope_ref,
        "resolution_ref": resolution_ref,
        "member_estimate_refs": member_estimate_refs,
        "relation_refs": relation_refs,
        "uncovered_source_refs": uncovered_source_refs,
        "aggregation_ref": aggregation_ref,
    }
    digest = _domain_hash("hapax.signal-constellation-loss-manifest.v1", body)
    return f"signal-constellation-loss@sha256:{digest}"


ContextExposureStageKind = Literal[
    "selected",
    "sealed",
    "rendered",
    "presented",
    "acknowledged",
]


_CONTEXT_EXPOSURE_STAGE_ORDER: tuple[ContextExposureStageKind, ...] = (
    "selected",
    "sealed",
    "rendered",
    "presented",
    "acknowledged",
)


ContextExposureDisposition = Literal["included", "omitted", "truncated", "dark"]


ContextInfluenceClass = Literal[
    "what",
    "how",
    "must",
    "impingement",
    "orientation",
    "operator_input",
    "retrieval",
    "tool",
    "memory",
    "environment",
    "generation_control",
    "other",
]


ContextSourceClass = Literal[
    "operator_input",
    "system_instruction",
    "task_specification",
    "lifecycle_canon",
    "impingement",
    "orientation",
    "retrieved_evidence",
    "tool_result",
    "memory",
    "environment",
    "prior_interaction",
    "capability_metadata",
    "other",
]


class ContextExposureQuantity(FrozenModel):
    """A measured size or an explicit unknown; unknown never becomes numeric zero."""

    value: int | None = Field(default=None, ge=0, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    unit: Literal["byte", "token"]
    state: ContextState
    method_ref: str

    @field_validator("method_ref")
    @classmethod
    def validate_method_ref(cls, value: str) -> str:
        return _validate_wire_string(value)

    @model_validator(mode="after")
    def validate_quantity(self) -> Self:
        if (self.state.value_state == "present") != (self.value is not None):
            raise ValueError(
                "present exposure quantities require a value; unavailable values omit it"
            )
        return self


class ContextExposureComponent(FrozenModel):
    """Semantic context member whose private body remains in its sealed source container."""

    component_ref: str
    component_hash: str = Field(pattern=_HASH_PATTERN)
    component_id: str
    component_kind: str
    source_class: ContextSourceClass
    source_ref: str
    content_ref: str | None
    content_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)
    content_address_class: Literal[
        "source_local_sealed",
        "audience_scoped_digest",
        "none_dark",
    ]
    hash_disclosure: Literal["sealed_only", "audience_permitted", "redacted", "dark"]
    provenance: ContextProvenance
    intended_influence_class: ContextInfluenceClass
    authority_ceiling: AuthorityCeiling
    air: ContextAirPolicy
    privacy_class: str
    transformation_state: Literal[
        "verbatim",
        "derived",
        "redacted",
        "summarized",
        "compacted",
        "unknown",
        "not_applicable",
    ]
    compaction_state: Literal["none", "lossless", "lossy", "unknown"]
    byte_count: ContextExposureQuantity
    token_count: ContextExposureQuantity
    valid_from: str
    valid_until: str
    freshness_state: FactFreshness
    disposition: ContextExposureDisposition
    state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "component_ref",
        "component_id",
        "component_kind",
        "source_ref",
        "content_ref",
        "privacy_class",
    )
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def validate_timestamp(cls, value: str, info: Any) -> str:
        return _validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def validate_component(self) -> Self:
        if _CONTENT_ADDRESS_PATTERN.fullmatch(self.source_ref) is None:
            raise ValueError("component source_ref must identify a content-addressed descriptor")
        if (self.content_ref is None) != (self.content_hash is None):
            raise ValueError("component content ref and hash must be jointly present or absent")
        if self.content_ref is not None and self.content_hash is not None:
            _validate_content_address(self.content_ref, self.content_hash, "component content")
        if self.valid_from > self.valid_until:
            raise ValueError("component validity interval is reversed")
        if self.content_address_class == "none_dark":
            if self.content_ref is not None or self.hash_disclosure != "dark":
                raise ValueError("DARK content cannot disclose a plaintext-derived address")
        elif self.content_ref is None:
            raise ValueError("sealed or audience-scoped component content requires an address")
        if self.content_address_class == "source_local_sealed" and self.hash_disclosure not in {
            "sealed_only",
            "redacted",
        }:
            raise ValueError("source-local sealed content cannot expose a reusable plaintext hash")
        if self.content_address_class == "audience_scoped_digest" and self.hash_disclosure not in {
            "audience_permitted",
            "redacted",
        }:
            raise ValueError("audience-scoped content requires a permitted or redacted digest")
        if self.disposition == "dark":
            if (
                self.content_address_class != "none_dark"
                or self.provenance.kind != "dark"
                or self.state.value_state != "dark"
            ):
                raise ValueError("DARK components require dark provenance, state, and no address")
        elif self.disposition == "included":
            if self.content_ref is None or self.state.value_state != "present":
                raise ValueError("included components require present sealed or scoped content")
        elif self.state.value_state == "present":
            raise ValueError("omitted or truncated components must disclose a non-present state")
        _validate_fact_state_freshness(
            self.freshness_state,
            self.state,
            label="context exposure component",
        )
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"component_ref", "component_hash"}
        )
        expected_hash = _domain_hash("hapax.context-exposure-component.v1", body)
        if self.component_hash != expected_hash:
            raise ValueError("component_hash does not bind the complete component")
        if self.component_ref != f"context-exposure-component@sha256:{expected_hash}":
            raise ValueError("component_ref does not bind component_hash")
        return self


class ContextExposureSegment(FrozenModel):
    """One stage-local artifact segment derived from one or more semantic components."""

    segment_ref: str
    segment_hash: str = Field(pattern=_HASH_PATTERN)
    stage: ContextExposureStageKind
    ordinal: int = Field(ge=0, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    component_refs: tuple[str, ...] = Field(min_length=1)
    artifact_ref: str | None
    artifact_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)
    artifact_address_class: Literal[
        "source_local_sealed",
        "audience_scoped_digest",
        "none_omitted",
        "none_dark",
    ]
    hash_disclosure: Literal["sealed_only", "audience_permitted", "redacted", "dark"]
    transformation_ref: str
    byte_count: ContextExposureQuantity
    token_count: ContextExposureQuantity
    disposition: ContextExposureDisposition
    state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator("segment_ref", "artifact_ref", "transformation_ref")
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator("component_refs")
    @classmethod
    def validate_component_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        checked = _validate_string_set(value, "component_refs", allow_empty=False)
        if any(not ref.startswith("context-exposure-component@sha256:") for ref in checked):
            raise ValueError("segment component refs must be exact component addresses")
        return checked

    @model_validator(mode="after")
    def validate_segment(self) -> Self:
        if (self.artifact_ref is None) != (self.artifact_hash is None):
            raise ValueError("segment artifact ref and hash must be jointly present or absent")
        if self.artifact_ref is not None and self.artifact_hash is not None:
            _validate_content_address(self.artifact_ref, self.artifact_hash, "segment artifact")
        if _CONTENT_ADDRESS_PATTERN.fullmatch(self.transformation_ref) is None:
            raise ValueError("segment transformation_ref must be content-addressed")
        address_disclosure_pairs = {
            "source_local_sealed": {"sealed_only", "redacted"},
            "audience_scoped_digest": {"audience_permitted", "redacted"},
            "none_omitted": {"redacted"},
            "none_dark": {"dark"},
        }
        if self.hash_disclosure not in address_disclosure_pairs[self.artifact_address_class]:
            raise ValueError("segment address class and hash disclosure are inconsistent")
        no_artifact_class = self.artifact_address_class in {"none_omitted", "none_dark"}
        if no_artifact_class != (self.artifact_ref is None):
            raise ValueError("segment address class must agree with artifact presence")
        if self.disposition == "dark":
            if (
                self.artifact_ref is not None
                or self.artifact_address_class != "none_dark"
                or self.hash_disclosure != "dark"
                or self.state.value_state != "dark"
                or self.byte_count.state.value_state != "dark"
                or self.token_count.state.value_state != "dark"
            ):
                raise ValueError("DARK segments cannot disclose an artifact")
        elif self.disposition == "omitted":
            if (
                self.artifact_ref is not None
                or self.artifact_address_class != "none_omitted"
                or self.state.value_state != "absent"
            ):
                raise ValueError("omitted segments cannot claim a presented artifact")
        elif self.artifact_ref is None:
            raise ValueError("included or truncated segments require a sealed or scoped artifact")
        if self.disposition == "included" and self.state.value_state != "present":
            raise ValueError("included segments require present stage-local evidence")
        if self.disposition == "truncated" and self.state.value_state == "present":
            raise ValueError("truncated segments must disclose a non-present state")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"segment_ref", "segment_hash"}
        )
        expected_hash = _domain_hash("hapax.context-exposure-segment.v1", body)
        if self.segment_hash != expected_hash:
            raise ValueError("segment_hash does not bind the complete segment")
        if self.segment_ref != f"context-exposure-segment@sha256:{expected_hash}":
            raise ValueError("segment_ref does not bind segment_hash")
        return self


class ContextExposureStage(FrozenModel):
    """One timed carriage stage with exact ordered stage-local artifact segments."""

    stage: ContextExposureStageKind
    ordered_segment_refs: tuple[str, ...]
    removed_component_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    loss_manifest_ref: str
    occurred_at: str
    checked_at: str
    stale_after: str
    state: ContextState

    @field_validator("loss_manifest_ref")
    @classmethod
    def validate_loss_ref(cls, value: str) -> str:
        value = _validate_wire_string(value)
        if _CONTENT_ADDRESS_PATTERN.fullmatch(value) is None:
            raise ValueError("loss_manifest_ref must be content-addressed")
        return value

    @field_validator("ordered_segment_refs")
    @classmethod
    def validate_ordered_segments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("ordered_segment_refs must be unique without changing order")
        for ref in value:
            if not _validate_wire_string(ref).startswith("context-exposure-segment@sha256:"):
                raise ValueError("ordered_segment_refs must use exact segment addresses")
        return value

    @field_validator("removed_component_refs", "evidence_refs")
    @classmethod
    def validate_ref_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        checked = _validate_string_set(
            value,
            info.field_name,
            allow_empty=info.field_name == "removed_component_refs",
        )
        if info.field_name == "removed_component_refs" and any(
            not ref.startswith("context-exposure-component@sha256:") for ref in checked
        ):
            raise ValueError("removed_component_refs must use exact component addresses")
        return checked

    @field_validator("occurred_at", "checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str, info: Any) -> str:
        return _validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def validate_stage(self) -> Self:
        if not self.occurred_at <= self.checked_at < self.stale_after:
            raise ValueError("stage timestamps must satisfy occurred <= checked < stale")
        if self.state.value_state == "present":
            if not self.ordered_segment_refs:
                raise ValueError("present exposure stages require ordered artifact segments")
            if self.removed_component_refs:
                raise ValueError("a loss-bearing exposure stage cannot be present")
        elif self.state.value_state == "dark":
            if self.ordered_segment_refs:
                raise ValueError("DARK exposure stages cannot claim known artifact segments")
        return self


def _derived_context_exposure_state(
    components: Sequence[ContextExposureComponent],
    segments: Sequence[ContextExposureSegment],
    stages: Sequence[ContextExposureStage],
) -> ContextState:
    reasons: set[str] = set()
    child_states: list[str] = []
    for component in components:
        child_states.append(component.state.value_state)
        if component.disposition != "included" or component.state.value_state != "present":
            reasons.add(
                f"component:{component.component_id}:{component.disposition}:"
                f"{component.state.value_state}"
            )
    for segment in segments:
        child_states.append(segment.state.value_state)
        if segment.disposition != "included" or segment.state.value_state != "present":
            reasons.add(
                f"segment:{segment.stage}:{segment.ordinal}:{segment.disposition}:"
                f"{segment.state.value_state}"
            )
    for stage in stages:
        child_states.append(stage.state.value_state)
        if stage.state.value_state != "present":
            reasons.add(f"stage:{stage.stage}:{stage.state.value_state}")
        if stage.removed_component_refs:
            reasons.add(f"stage:{stage.stage}:components_removed")
    if not reasons:
        return ContextState(value_state="present", reason_codes=())
    if "refused" in child_states:
        value_state = "refused"
    elif "hold" in child_states:
        value_state = "hold"
    elif child_states and set(child_states) == {"dark"}:
        value_state = "dark"
    elif child_states and set(child_states) == {"absent"}:
        value_state = "absent"
    else:
        value_state = "partial"
    return ContextState(value_state=value_state, reason_codes=tuple(sorted(reasons)))


def _derived_context_exposure_stage_state(
    stage: ContextExposureStage,
    stage_segments: Sequence[ContextExposureSegment],
) -> ContextState:
    reasons = {
        f"stage:{stage.stage}:segment:{segment.ordinal}:{segment.disposition}:"
        f"{segment.state.value_state}"
        for segment in stage_segments
        if segment.disposition != "included" or segment.state.value_state != "present"
    }
    if stage.removed_component_refs:
        reasons.add(f"stage:{stage.stage}:components_removed")
    if not reasons:
        return ContextState(value_state="present", reason_codes=())
    segment_states = {segment.state.value_state for segment in stage_segments}
    carried = [
        segment
        for segment in stage_segments
        if segment.disposition in {"included", "truncated"}
        and segment.artifact_ref is not None
    ]
    if "refused" in segment_states:
        value_state = "refused"
    elif "hold" in segment_states:
        value_state = "hold"
    elif not carried and segment_states == {"dark"}:
        value_state = "dark"
    elif not carried and segment_states == {"absent"}:
        value_state = "absent"
    else:
        value_state = "partial"
    return ContextState(value_state=value_state, reason_codes=tuple(sorted(reasons)))


class ContextExposure(FrozenModel):
    """Spine-owned evidence of exact context carriage, never attention or causal effect.

    The embedded pre-exposure inspection projection covers only the frozen frame and selection.
    A later Reins projection of this completed exposure remains external to avoid a hash cycle.
    Neither projection, the carrier, nor an acknowledgement proves attention or authority.
    """

    schema_id: Literal["hapax.context-exposure.v1"] = Field(alias="schema")
    exposure_ref: str
    exposure_hash: str = Field(pattern=_HASH_PATTERN)
    invocation_id: str
    attempt_fence: str = Field(pattern=_HASH_PATTERN)
    invocation_ref: str
    invocation_hash: str = Field(pattern=_HASH_PATTERN)
    served_identity_ref: str
    served_identity_hash: str = Field(pattern=_HASH_PATTERN)
    demand_shape_ref: str
    demand_shape_fingerprint: str = Field(pattern=_HASH_PATTERN)
    measurement_basis_ref: str
    measurement_basis_hash: str = Field(pattern=_HASH_PATTERN)
    context_frontier_ref: str
    context_frontier_hash: str = Field(pattern=_HASH_PATTERN)
    session_ref: str
    task_ref: str
    trace_ref: str
    scope_ref: str
    temporal_ref: str
    resolution_ref: str
    position_ref: str
    frame_ref: str
    frame_hash: str = Field(pattern=_HASH_PATTERN)
    selection_ref: str
    selection_hash: str = Field(pattern=_HASH_PATTERN)
    pre_exposure_inspection_projection_ref: str
    pre_exposure_inspection_projection_hash: str = Field(pattern=_HASH_PATTERN)
    pre_exposure_inspection_audience: Literal["operator_private"]
    pre_exposure_inspection_claim_ceiling: Literal[
        "frozen_frame_selection_only_no_actual_carriage"
    ]
    carrier_audience: Literal[
        "operator_private",
        "yard_context",
        "hapax_substrate",
        "public_or_air",
    ]
    audience_seal_ref: str
    audience_seal_hash: str = Field(pattern=_HASH_PATTERN)
    components: tuple[ContextExposureComponent, ...] = Field(min_length=1)
    segments: tuple[ContextExposureSegment, ...] = Field(min_length=1)
    stages: tuple[ContextExposureStage, ...] = Field(min_length=5, max_length=5)
    loss_manifest_ref: str
    correction_refs: tuple[str, ...]
    supersedes_refs: tuple[str, ...]
    observed_at: str
    checked_at: str
    stale_after: str
    state: ContextState
    verification_scope: Literal["structure_and_content_address_only"]
    producer_verification_required: Literal[True]
    producer_resolution_obligation_ref: str
    producer_verification_refs: tuple[str, ...]
    producer_resolution_state: ContextState
    authority_ceiling: Literal["observation_only"]
    effective_attention_observed: Literal[False]
    causal_effect_observed: Literal[False]
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "exposure_ref",
        "invocation_id",
        "invocation_ref",
        "served_identity_ref",
        "demand_shape_ref",
        "measurement_basis_ref",
        "context_frontier_ref",
        "session_ref",
        "task_ref",
        "trace_ref",
        "scope_ref",
        "temporal_ref",
        "resolution_ref",
        "position_ref",
        "frame_ref",
        "selection_ref",
        "pre_exposure_inspection_projection_ref",
        "audience_seal_ref",
        "loss_manifest_ref",
        "producer_resolution_obligation_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("producer_verification_refs", "correction_refs", "supersedes_refs")
    @classmethod
    def validate_ref_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name)

    @field_validator("observed_at", "checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str, info: Any) -> str:
        return _validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def validate_exposure(self) -> Self:
        addressed = (
            (self.invocation_ref, self.invocation_hash, "invocation"),
            (self.served_identity_ref, self.served_identity_hash, "served identity"),
            (self.measurement_basis_ref, self.measurement_basis_hash, "measurement basis"),
            (self.context_frontier_ref, self.context_frontier_hash, "context frontier"),
            (self.frame_ref, self.frame_hash, "context frame"),
            (self.selection_ref, self.selection_hash, "context selection"),
            (
                self.pre_exposure_inspection_projection_ref,
                self.pre_exposure_inspection_projection_hash,
                "audience-sealed pre-exposure inspection projection",
            ),
            (self.audience_seal_ref, self.audience_seal_hash, "audience seal"),
        )
        for ref, digest, label in addressed:
            _validate_content_address(ref, digest, label)
        if self.demand_shape_ref != (
            f"demand-shape@sha256:{self.demand_shape_fingerprint}"
        ):
            raise ValueError("demand_shape_ref does not bind demand_shape_fingerprint")
        if _CONTENT_ADDRESS_PATTERN.fullmatch(self.position_ref) is None:
            raise ValueError("position_ref must be content-addressed")
        if _CONTENT_ADDRESS_PATTERN.fullmatch(self.loss_manifest_ref) is None:
            raise ValueError("loss_manifest_ref must be content-addressed")
        if _CONTENT_ADDRESS_PATTERN.fullmatch(self.producer_resolution_obligation_ref) is None:
            raise ValueError("producer resolution obligation must be content-addressed")
        if any(
            _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None
            for ref in self.producer_verification_refs
        ):
            raise ValueError("producer verification refs must be exact content addresses")
        expected_resolution_state = (
            ContextState(value_state="present", reason_codes=())
            if self.producer_verification_refs
            else ContextState(
                value_state="hold",
                reason_codes=("gate0b_producer_resolution_required",),
            )
        )
        if self.producer_resolution_state != expected_resolution_state:
            raise ValueError("producer resolution state must derive from exact verification refs")
        if not self.selection_ref.startswith("context-selection@sha256:"):
            raise ValueError("selection_ref must bind the exact ContextSelection")
        if not self.pre_exposure_inspection_projection_ref.startswith(
            "projection-envelope@sha256:"
        ):
            raise ValueError(
                "pre_exposure_inspection_projection_ref must bind a ProjectionEnvelope"
            )
        if not self.observed_at <= self.checked_at < self.stale_after:
            raise ValueError("exposure timestamps must satisfy observed <= checked < stale")
        if tuple(stage.stage for stage in self.stages) != _CONTEXT_EXPOSURE_STAGE_ORDER:
            raise ValueError("context exposure stages must use the exact carriage order")
        if tuple(stage.occurred_at for stage in self.stages) != tuple(
            sorted(stage.occurred_at for stage in self.stages)
        ):
            raise ValueError("exposure stage occurrence times must be ordered")
        if self.stages[-1].occurred_at > self.observed_at:
            raise ValueError("exposure observation cannot predate its final carriage stage")
        component_refs = tuple(item.component_ref for item in self.components)
        if component_refs != tuple(sorted(set(component_refs))):
            raise ValueError("exposure components must be sorted and unique by component_ref")
        component_ref_set = set(component_refs)
        segment_refs = tuple(item.segment_ref for item in self.segments)
        if len(segment_refs) != len(set(segment_refs)):
            raise ValueError("exposure segments must be unique by segment_ref")
        segment_by_ref = {item.segment_ref: item for item in self.segments}
        if any(set(item.component_refs) - component_ref_set for item in self.segments):
            raise ValueError("every segment component must resolve in the exposure")
        carried_segment_refs = {
            segment.segment_ref
            for segment in self.segments
            if segment.disposition in {"included", "truncated"}
            and segment.artifact_ref is not None
        }
        ordered_segment_refs = {
            ref for stage in self.stages for ref in stage.ordered_segment_refs
        }
        if ordered_segment_refs != carried_segment_refs:
            raise ValueError("only every carried artifact segment may occur in stage order")
        stage_components: list[set[str]] = []
        for stage in self.stages:
            if set(stage.ordered_segment_refs) - set(segment_refs):
                raise ValueError("every stage segment must resolve in the exposure")
            if set(stage.removed_component_refs) - component_ref_set:
                raise ValueError("every removed component must resolve in the exposure")
            stage_segments = tuple(segment_by_ref[ref] for ref in stage.ordered_segment_refs)
            declared_stage_segments = tuple(
                segment for segment in self.segments if segment.stage == stage.stage
            )
            if any(segment.stage != stage.stage for segment in stage_segments):
                raise ValueError("stage segment identity must match its carriage stage")
            if len({segment.ordinal for segment in declared_stage_segments}) != len(
                declared_stage_segments
            ):
                raise ValueError("all stage-local segment ordinals must be unique")
            if tuple(segment.ordinal for segment in stage_segments) != tuple(
                range(len(stage_segments))
            ):
                raise ValueError("stage segment ordinals must be contiguous in rendered order")
            if any(
                segment.disposition not in {"included", "truncated"}
                or segment.artifact_ref is None
                for segment in stage_segments
            ):
                raise ValueError(
                    "ordered carriage may contain only included or truncated artifacts"
                )
            flattened_components = tuple(
                component_ref
                for segment in stage_segments
                for component_ref in segment.component_refs
            )
            current_components = set(flattened_components)
            if current_components & set(stage.removed_component_refs):
                raise ValueError("a stage cannot carry and remove the same semantic component")
            uncarried_segments = tuple(
                segment
                for segment in declared_stage_segments
                if segment.segment_ref not in stage.ordered_segment_refs
            )
            if any(
                segment.disposition not in {"omitted", "dark"}
                or segment.artifact_ref is not None
                for segment in uncarried_segments
            ):
                raise ValueError(
                    "uncarried stage segments must be explicit omitted or DARK evidence"
                )
            if any(
                set(segment.component_refs) - set(stage.removed_component_refs)
                for segment in uncarried_segments
            ):
                raise ValueError(
                    "uncarried segment components must resolve as exact stage removals"
                )
            derived_stage_state = _derived_context_exposure_stage_state(
                stage,
                declared_stage_segments,
            )
            if stage.state != derived_stage_state:
                raise ValueError("stage state must derive from resolved segments and removals")
            stage_components.append(current_components)
        selected_removed = component_ref_set - stage_components[0]
        if set(self.stages[0].removed_component_refs) != selected_removed:
            raise ValueError(
                "selected stage removals must equal all declared but unselected components"
            )
        for index, stage in enumerate(self.stages[1:], start=1):
            if stage_components[index] - stage_components[index - 1]:
                raise ValueError("later stages cannot introduce unselected semantic components")
            removed = stage_components[index - 1] - stage_components[index]
            if set(stage.removed_component_refs) != removed:
                raise ValueError(
                    "stage removals must equal the exact prior-stage minus current-stage set"
                )
        presented_components = stage_components[_CONTEXT_EXPOSURE_STAGE_ORDER.index("presented")]
        for component in self.components:
            presented = component.component_ref in presented_components
            if component.disposition in {"included", "truncated"} and not presented:
                raise ValueError("included or truncated components must reach presentation")
            if component.disposition in {"omitted", "dark"} and presented:
                raise ValueError("omitted or DARK components cannot appear in presentation")
            if presented:
                audience_permission = getattr(component.air, self.carrier_audience)
                redacted_or_truncated = (
                    component.transformation_state == "redacted"
                    or component.disposition == "truncated"
                )
                if audience_permission == "deny":
                    raise ValueError("carrier AIR denial cannot reach context presentation")
                if redacted_or_truncated and audience_permission not in {"allow", "redact"}:
                    raise ValueError("redacted or truncated presentation requires AIR permission")
                if not redacted_or_truncated and audience_permission != "allow":
                    raise ValueError("included presentation requires carrier-audience AIR allow")
        derived_state = _derived_context_exposure_state(
            self.components,
            self.segments,
            self.stages,
        )
        if self.state != derived_state:
            raise ValueError("exposure state must equal its component and stage-derived state")
        for ref in (*self.correction_refs, *self.supersedes_refs):
            if (
                not ref.startswith("context-exposure@sha256:")
                or _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None
            ):
                raise ValueError("exposure correction lineage must use context-exposure refs")
        if self.exposure_ref in {*self.correction_refs, *self.supersedes_refs}:
            raise ValueError("an exposure cannot correct or supersede itself")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"exposure_ref", "exposure_hash"}
        )
        expected_hash = _domain_hash("hapax.context-exposure.v1", body)
        if self.exposure_hash != expected_hash:
            raise ValueError("exposure_hash does not bind the complete exposure")
        if self.exposure_ref != f"context-exposure@sha256:{expected_hash}":
            raise ValueError("exposure_ref does not bind exposure_hash")
        return self


class CapabilityBehaviorDatum(FrozenModel):
    """One external behavior coordinate; refusal is a value, never a failed observation."""

    ordinal: int = Field(ge=0, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    behavior_kind: Literal[
        "output",
        "tool_call",
        "artifact",
        "gate_attempt",
        "refusal",
        "resource_use",
        "other_external",
    ]
    behavior_disposition: Literal[
        "produced",
        "refused",
        "attempted",
        "failed",
        "abstained",
        "not_observed",
    ]
    demand_region_ref: str
    basis_dimension_ref: str
    fitness_boundary_ref: str
    observation_ref: str
    observation_hash: str = Field(pattern=_HASH_PATTERN)
    observed_value: CanonicalDecimal | None
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    does_not_prove: tuple[str, ...] = Field(min_length=1)
    observed_at: str
    freshness_state: FactFreshness
    confidence: ContextConfidence
    state: ContextState

    @field_validator(
        "demand_region_ref",
        "basis_dimension_ref",
        "fitness_boundary_ref",
        "observation_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("evidence_refs", "does_not_prove")
    @classmethod
    def validate_ref_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        checked = _validate_string_set(value, info.field_name, allow_empty=False)
        if info.field_name == "evidence_refs" and any(
            _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None for ref in checked
        ):
            raise ValueError("behavior evidence refs must be content-addressed")
        return checked

    @field_validator("observed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _validate_timestamp(value, "observed_at")

    @model_validator(mode="after")
    def validate_datum(self) -> Self:
        _validate_content_address(self.observation_ref, self.observation_hash, "behavior datum")
        for field_name in ("demand_region_ref", "basis_dimension_ref", "fitness_boundary_ref"):
            if _CONTENT_ADDRESS_PATTERN.fullmatch(getattr(self, field_name)) is None:
                raise ValueError(f"{field_name} must be content-addressed")
        _validate_fact_state_freshness(self.freshness_state, self.state, label="behavior datum")
        if self.state.value_state == "dark" and self.observed_value is not None:
            raise ValueError("DARK behavior cannot be coerced into a numeric value")
        if self.behavior_disposition == "refused" and self.state.value_state != "present":
            raise ValueError("a fresh observed refusal is present behavior evidence")
        return self


class CapabilityBehaviorObservation(FrozenModel):
    """Vector-valued capability behavior conditioned on, but not attributed to, its envelope.

    Harness, resource, delivery, and evaluator refs are stratification conditions. This carrier
    never infers their health, combines them into capability behavior, or claims causation.
    """

    schema_id: Literal["hapax.capability-behavior-observation.v1"] = Field(alias="schema")
    behavior_ref: str
    behavior_hash: str = Field(pattern=_HASH_PATTERN)
    invocation_id: str
    attempt_fence: str = Field(pattern=_HASH_PATTERN)
    invocation_ref: str
    invocation_hash: str = Field(pattern=_HASH_PATTERN)
    exposure_ref: str
    exposure_hash: str = Field(pattern=_HASH_PATTERN)
    served_identity_ref: str
    served_identity_hash: str = Field(pattern=_HASH_PATTERN)
    demand_shape_ref: str
    demand_shape_fingerprint: str = Field(pattern=_HASH_PATTERN)
    measurement_basis_ref: str
    measurement_basis_hash: str = Field(pattern=_HASH_PATTERN)
    context_frontier_ref: str
    context_frontier_hash: str = Field(pattern=_HASH_PATTERN)
    behavior_frontier_parent_ref: str
    behavior_frontier_parent_hash: str = Field(pattern=_HASH_PATTERN)
    behavior_event_frontier_ref: str
    behavior_event_frontier_hash: str = Field(pattern=_HASH_PATTERN)
    session_ref: str
    task_ref: str
    trace_ref: str
    scope_ref: str
    temporal_ref: str
    resolution_ref: str
    position_ref: str
    carrier_audience: Literal[
        "operator_private",
        "yard_context",
        "hapax_substrate",
        "public_or_air",
    ]
    privacy_class: str
    air: ContextAirPolicy
    audience_seal_ref: str
    audience_seal_hash: str = Field(pattern=_HASH_PATTERN)
    source_local_only: Literal[True]
    harness_condition_ref: str
    harness_condition_hash: str = Field(pattern=_HASH_PATTERN)
    resource_condition_ref: str
    resource_condition_hash: str = Field(pattern=_HASH_PATTERN)
    delivery_condition_ref: str
    delivery_condition_hash: str = Field(pattern=_HASH_PATTERN)
    evaluator_condition_ref: str
    evaluator_condition_hash: str = Field(pattern=_HASH_PATTERN)
    regime_ref: str
    regime_hash: str = Field(pattern=_HASH_PATTERN)
    epoch_ref: str
    epoch_hash: str = Field(pattern=_HASH_PATTERN)
    observations: tuple[CapabilityBehaviorDatum, ...] = Field(min_length=1)
    required_basis_dimension_refs: tuple[str, ...] = Field(min_length=1)
    unobserved_basis_dimension_refs: tuple[str, ...]
    dark_basis_dimension_refs: tuple[str, ...]
    basis_coverage: CanonicalDecimal
    contradiction_refs: tuple[str, ...]
    correction_refs: tuple[str, ...]
    supersedes_refs: tuple[str, ...]
    valid_from: str
    valid_until: str
    observed_at: str
    checked_at: str
    stale_after: str
    state: ContextState
    verification_scope: Literal["structure_and_content_address_only"]
    producer_verification_required: Literal[True]
    producer_resolution_obligation_ref: str
    producer_verification_refs: tuple[str, ...]
    producer_resolution_state: ContextState
    observation_plane: Literal["capability_behavior"]
    correlation_only: Literal[True]
    causal_effect_claimed: Literal[False]
    authority_ceiling: Literal["observation_only"]
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "behavior_ref",
        "invocation_id",
        "invocation_ref",
        "exposure_ref",
        "served_identity_ref",
        "demand_shape_ref",
        "measurement_basis_ref",
        "context_frontier_ref",
        "behavior_frontier_parent_ref",
        "behavior_event_frontier_ref",
        "session_ref",
        "task_ref",
        "trace_ref",
        "scope_ref",
        "temporal_ref",
        "resolution_ref",
        "position_ref",
        "privacy_class",
        "audience_seal_ref",
        "harness_condition_ref",
        "resource_condition_ref",
        "delivery_condition_ref",
        "evaluator_condition_ref",
        "regime_ref",
        "epoch_ref",
        "producer_resolution_obligation_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator(
        "required_basis_dimension_refs",
        "unobserved_basis_dimension_refs",
        "dark_basis_dimension_refs",
        "producer_verification_refs",
        "contradiction_refs",
        "correction_refs",
        "supersedes_refs",
    )
    @classmethod
    def validate_ref_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name)

    @field_validator("valid_from", "valid_until", "observed_at", "checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str, info: Any) -> str:
        return _validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def validate_behavior(self) -> Self:
        addressed = (
            (self.invocation_ref, self.invocation_hash, "invocation"),
            (self.exposure_ref, self.exposure_hash, "context exposure"),
            (self.served_identity_ref, self.served_identity_hash, "served identity"),
            (self.measurement_basis_ref, self.measurement_basis_hash, "measurement basis"),
            (self.context_frontier_ref, self.context_frontier_hash, "context frontier"),
            (self.audience_seal_ref, self.audience_seal_hash, "behavior audience seal"),
            (
                self.behavior_frontier_parent_ref,
                self.behavior_frontier_parent_hash,
                "behavior frontier parent",
            ),
            (
                self.behavior_event_frontier_ref,
                self.behavior_event_frontier_hash,
                "behavior event frontier",
            ),
            (self.harness_condition_ref, self.harness_condition_hash, "harness condition"),
            (self.resource_condition_ref, self.resource_condition_hash, "resource condition"),
            (self.delivery_condition_ref, self.delivery_condition_hash, "delivery condition"),
            (self.evaluator_condition_ref, self.evaluator_condition_hash, "evaluator condition"),
            (self.regime_ref, self.regime_hash, "regime"),
            (self.epoch_ref, self.epoch_hash, "epoch"),
        )
        for ref, digest, label in addressed:
            _validate_content_address(ref, digest, label)
        if not self.exposure_ref.startswith("context-exposure@sha256:"):
            raise ValueError("behavior observation requires an exact context exposure ref")
        if (
            self.behavior_frontier_parent_ref != self.context_frontier_ref
            or self.behavior_frontier_parent_hash != self.context_frontier_hash
        ):
            raise ValueError("behavior frontier must name the frozen context frontier as parent")
        if self.behavior_event_frontier_ref == self.context_frontier_ref:
            raise ValueError("behavior evidence requires a later descendant event frontier")
        if self.demand_shape_ref != (
            f"demand-shape@sha256:{self.demand_shape_fingerprint}"
        ):
            raise ValueError("demand_shape_ref does not bind demand_shape_fingerprint")
        if _CONTENT_ADDRESS_PATTERN.fullmatch(self.position_ref) is None:
            raise ValueError("behavior position_ref must be content-addressed")
        if getattr(self.air, self.carrier_audience) == "deny":
            raise ValueError("behavior AIR denies its carrier audience")
        if _CONTENT_ADDRESS_PATTERN.fullmatch(self.producer_resolution_obligation_ref) is None:
            raise ValueError("producer resolution obligation must be content-addressed")
        if any(
            _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None
            for ref in self.producer_verification_refs
        ):
            raise ValueError("producer verification refs must be exact content addresses")
        expected_resolution_state = (
            ContextState(value_state="present", reason_codes=())
            if self.producer_verification_refs
            else ContextState(
                value_state="hold",
                reason_codes=("gate0b_producer_resolution_required",),
            )
        )
        if self.producer_resolution_state != expected_resolution_state:
            raise ValueError("producer resolution state must derive from exact verification refs")
        ordinals = tuple(item.ordinal for item in self.observations)
        if ordinals != tuple(range(len(self.observations))):
            raise ValueError("behavior observations must have contiguous ordered ordinals")
        if any(item.observed_at > self.observed_at for item in self.observations):
            raise ValueError("behavior observation cannot predate its component data")
        if not self.valid_from <= self.observed_at <= self.valid_until:
            raise ValueError("behavior observation must fall within its validity interval")
        if not self.observed_at <= self.checked_at < self.stale_after:
            raise ValueError("behavior timestamps must satisfy observed <= checked < stale")
        if any(item.demand_region_ref != self.demand_shape_ref for item in self.observations):
            raise ValueError("behavior coordinates must bind the exact demand region")
        observation_refs = tuple(item.observation_ref for item in self.observations)
        if len(observation_refs) != len(set(observation_refs)):
            raise ValueError("behavior observations require unique exact observation refs")
        covered_dimensions = {
            item.basis_dimension_ref
            for item in self.observations
            if item.state.value_state in {"present", "partial", "uncertain"}
        }
        datum_unobserved = {
            item.basis_dimension_ref
            for item in self.observations
            if item.state.value_state not in {"present", "partial", "uncertain", "dark"}
        }
        datum_dark = {
            item.basis_dimension_ref
            for item in self.observations
            if item.state.value_state == "dark"
        }
        required_dimensions = set(self.required_basis_dimension_refs)
        unobserved_dimensions = set(self.unobserved_basis_dimension_refs)
        dark_dimensions = set(self.dark_basis_dimension_refs)
        if unobserved_dimensions & dark_dimensions:
            raise ValueError("a basis dimension cannot be both unobserved and DARK")
        if covered_dimensions & (unobserved_dimensions | dark_dimensions):
            raise ValueError("observed basis dimensions cannot also be unavailable")
        if not datum_unobserved.issubset(
            unobserved_dimensions | covered_dimensions
        ) or not datum_dark.issubset(dark_dimensions | covered_dimensions):
            raise ValueError("non-present behavior data must resolve to its unavailable basis set")
        if (
            covered_dimensions | unobserved_dimensions | dark_dimensions
        ) != required_dimensions:
            raise ValueError("observed, unobserved, and DARK dimensions must partition the basis")
        if any(
            _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None
            for ref in (
                *self.required_basis_dimension_refs,
                *self.unobserved_basis_dimension_refs,
                *self.dark_basis_dimension_refs,
            )
        ):
            raise ValueError("basis dimension manifests require exact content addresses")
        if self.basis_coverage.unit != "proportion":
            raise ValueError("basis coverage must use proportion units")
        coverage = Decimal(self.basis_coverage.value)
        derived_coverage = Decimal(len(covered_dimensions)) / Decimal(
            len(self.required_basis_dimension_refs)
        )
        if coverage != derived_coverage:
            raise ValueError("basis coverage must be mechanically derived from the basis partition")
        if any(
            _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None for ref in self.contradiction_refs
        ):
            raise ValueError("behavior contradiction refs must be content-addressed")
        root_reasons = {
            f"basis_dimension:{ref}:unobserved" for ref in self.unobserved_basis_dimension_refs
        } | {f"basis_dimension:{ref}:dark" for ref in self.dark_basis_dimension_refs}
        root_reasons.update(
            f"datum:{item.ordinal}:{item.state.value_state}"
            for item in self.observations
            if item.state.value_state != "present"
        )
        if self.contradiction_refs:
            root_reasons.add("behavior:contradicted")
        if not root_reasons:
            derived_state = ContextState(value_state="present", reason_codes=())
        elif self.contradiction_refs:
            derived_state = ContextState(
                value_state="uncertain",
                reason_codes=tuple(sorted(root_reasons)),
            )
        elif dark_dimensions == required_dimensions:
            derived_state = ContextState(
                value_state="dark",
                reason_codes=tuple(sorted(root_reasons)),
            )
        else:
            derived_state = ContextState(
                value_state="partial",
                reason_codes=tuple(sorted(root_reasons)),
            )
        if self.state != derived_state:
            raise ValueError("behavior state must be mechanically derived from basis evidence")
        for ref in (*self.correction_refs, *self.supersedes_refs):
            if (
                not ref.startswith("capability-behavior-observation@sha256:")
                or _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None
            ):
                raise ValueError(
                    "behavior correction lineage must use capability-behavior-observation refs"
                )
        if self.behavior_ref in {*self.correction_refs, *self.supersedes_refs}:
            raise ValueError("a behavior observation cannot correct or supersede itself")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"behavior_ref", "behavior_hash"}
        )
        expected_hash = _domain_hash("hapax.capability-behavior-observation.v1", body)
        if self.behavior_hash != expected_hash:
            raise ValueError("behavior_hash does not bind the complete behavior observation")
        if self.behavior_ref != (
            f"capability-behavior-observation@sha256:{expected_hash}"
        ):
            raise ValueError("behavior_ref does not bind behavior_hash")
        return self


class SignalLearningReceipt(FrozenModel):
    learning_ref: str
    learning_hash: str = Field(pattern=_HASH_PATTERN)
    learning_id: str
    position_ref: str
    estimate_ref: str
    constellation_ref: str
    exposure_ref: str
    behavior_ref: str | None = Field(default=None, exclude_if=lambda value: value is None)
    measurement_basis_ref: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    fitness_boundary_refs: tuple[str, ...] = Field(
        default=(),
        exclude_if=lambda value: not value,
    )
    candidate_set_ref: str
    selection_policy_ref: str
    selection_propensity: CanonicalDecimal
    action_ref: str
    outcome_ref: str
    effect: CanonicalJsonObject
    cost: CanonicalJsonObject
    witness_refs: tuple[str, ...] = Field(min_length=1)
    receipt_ref: str
    correction_refs: tuple[str, ...]
    supersedes_refs: tuple[str, ...]
    update_target_ref: str
    update_applied: bool = Field(strict=True)
    recorded_at: str | None = Field(default=None, exclude_if=lambda value: value is None)
    state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "learning_ref",
        "learning_id",
        "position_ref",
        "estimate_ref",
        "constellation_ref",
        "exposure_ref",
        "behavior_ref",
        "measurement_basis_ref",
        "candidate_set_ref",
        "selection_policy_ref",
        "action_ref",
        "outcome_ref",
        "receipt_ref",
        "update_target_ref",
    )
    @classmethod
    def validate_string(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator("recorded_at")
    @classmethod
    def validate_timestamp(cls, value: str | None) -> str | None:
        return None if value is None else _validate_timestamp(value, "recorded_at")

    @field_validator(
        "fitness_boundary_refs",
        "witness_refs",
        "correction_refs",
        "supersedes_refs",
    )
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value,
            info.field_name,
            allow_empty=info.field_name
            in {"fitness_boundary_refs", "correction_refs", "supersedes_refs"},
        )

    @model_validator(mode="after")
    def validate_learning(self) -> Self:
        semantic_namespaces = {
            "candidate_set_ref": "candidate-set:",
            "selection_policy_ref": "selection-policy:",
            "update_target_ref": "learning-target:",
        }
        for field_name, prefix in semantic_namespaces.items():
            if not getattr(self, field_name).startswith(prefix):
                raise ValueError(f"{field_name} must use the typed {prefix} namespace")
        legacy_or_exact_exposure = self.exposure_ref.startswith("exposure:") or (
            self.exposure_ref.startswith("context-exposure@sha256:")
            and _CONTENT_ADDRESS_PATTERN.fullmatch(self.exposure_ref) is not None
        )
        if not legacy_or_exact_exposure:
            raise ValueError("exposure_ref must use the held legacy or exact exposure namespace")
        exact_behavior = (
            self.behavior_ref is not None
            and self.behavior_ref.startswith("capability-behavior-observation@sha256:")
            and _CONTENT_ADDRESS_PATTERN.fullmatch(self.behavior_ref) is not None
        )
        exact_basis = (
            self.measurement_basis_ref is not None
            and self.measurement_basis_ref.startswith("measurement-basis@sha256:")
            and _CONTENT_ADDRESS_PATTERN.fullmatch(self.measurement_basis_ref) is not None
        )
        exact_boundaries = bool(self.fitness_boundary_refs) and all(
            ref.startswith("fitness-boundary@sha256:")
            and _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is not None
            for ref in self.fitness_boundary_refs
        )
        exact_outcome = self.outcome_ref.startswith("outcome-receipt@sha256:") and (
            _CONTENT_ADDRESS_PATTERN.fullmatch(self.outcome_ref) is not None
        )
        exact_application = self.receipt_ref.startswith(
            "measurement-application-receipt@sha256:"
        ) and (_CONTENT_ADDRESS_PATTERN.fullmatch(self.receipt_ref) is not None)
        if self.update_applied and (
            not self.exposure_ref.startswith("context-exposure@sha256:")
            or not exact_behavior
            or not exact_basis
            or not exact_boundaries
            or not exact_outcome
            or not exact_application
            or self.recorded_at is None
        ):
            raise ValueError(
                "an applied learning update requires exact exposure, behavior, basis, "
                "fitness boundaries, outcome, application receipt, and recording time"
            )
        if not self.update_applied and not (
            self.outcome_ref.startswith("outcome:") or exact_outcome
        ):
            raise ValueError("held learning outcome must use a typed legacy or exact receipt ref")
        if not self.update_applied and not (
            self.receipt_ref.startswith("receipt:") or exact_application
        ):
            raise ValueError("held learning receipt must use a legacy or exact application ref")
        if self.behavior_ref is not None and not exact_behavior:
            raise ValueError("behavior_ref must be an exact behavior observation address")
        if self.measurement_basis_ref is not None and not exact_basis:
            raise ValueError("measurement_basis_ref must be an exact basis address")
        if self.fitness_boundary_refs and not exact_boundaries:
            raise ValueError("fitness_boundary_refs must be exact boundary addresses")
        if self.selection_propensity.unit != "probability":
            raise ValueError("selection propensity must use probability units")
        propensity = Decimal(self.selection_propensity.value)
        if not Decimal("0") <= propensity <= Decimal("1"):
            raise ValueError("selection propensity must be within the unit interval")
        if self.update_applied and self.state.value_state != "present":
            raise ValueError("an applied learning update requires a present receipt")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"learning_ref", "learning_hash"}
        )
        expected_hash = _domain_hash("hapax.signal-learning-receipt.v1", body)
        if self.learning_hash != expected_hash:
            raise ValueError("learning_hash does not bind the learning receipt")
        if self.learning_ref != f"signal-learning@sha256:{expected_hash}":
            raise ValueError("learning_ref does not bind learning_hash")
        return self


class MeasurementApplicationReceipt(FrozenModel):
    """No-effect evidence of one exact measurement update applied to one target."""

    schema_id: Literal["hapax.measurement-application-receipt.v1"] = Field(alias="schema")
    application_ref: str
    application_hash: str = Field(pattern=_HASH_PATTERN)
    application_id: str
    invocation_id: str
    attempt_fence: str = Field(pattern=_HASH_PATTERN)
    exposure_ref: str
    exposure_hash: str = Field(pattern=_HASH_PATTERN)
    behavior_ref: str
    behavior_hash: str = Field(pattern=_HASH_PATTERN)
    outcome_ref: str
    outcome_hash: str = Field(pattern=_HASH_PATTERN)
    outcome_append_receipt_ref: str
    outcome_append_receipt_hash: str = Field(pattern=_HASH_PATTERN)
    committer_ref: str
    committer_hash: str = Field(pattern=_HASH_PATTERN)
    application_frontier_ref: str
    application_frontier_hash: str = Field(pattern=_HASH_PATTERN)
    measurement_basis_ref: str
    measurement_basis_hash: str = Field(pattern=_HASH_PATTERN)
    fitness_boundary_refs: tuple[str, ...] = Field(min_length=1)
    update_target_ref: str
    target_count: Literal[1]
    correction_refs: tuple[str, ...]
    supersedes_refs: tuple[str, ...]
    applied_at: str
    state: ContextState
    verification_scope: Literal["structure_and_content_address_only"]
    producer_verification_required: Literal[True]
    producer_resolution_obligation_ref: str
    producer_verification_refs: tuple[str, ...]
    producer_resolution_state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "application_ref",
        "application_id",
        "invocation_id",
        "exposure_ref",
        "behavior_ref",
        "outcome_ref",
        "outcome_append_receipt_ref",
        "committer_ref",
        "application_frontier_ref",
        "measurement_basis_ref",
        "update_target_ref",
        "producer_resolution_obligation_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator(
        "fitness_boundary_refs",
        "producer_verification_refs",
        "correction_refs",
        "supersedes_refs",
    )
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value,
            info.field_name,
            allow_empty=info.field_name
            in {"producer_verification_refs", "correction_refs", "supersedes_refs"},
        )

    @field_validator("applied_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _validate_timestamp(value, "applied_at")

    @model_validator(mode="after")
    def validate_application(self) -> Self:
        addressed = (
            (self.exposure_ref, self.exposure_hash, "application exposure"),
            (self.behavior_ref, self.behavior_hash, "application behavior"),
            (self.outcome_ref, self.outcome_hash, "application outcome"),
            (
                self.outcome_append_receipt_ref,
                self.outcome_append_receipt_hash,
                "application outcome append receipt",
            ),
            (self.committer_ref, self.committer_hash, "application committer"),
            (
                self.application_frontier_ref,
                self.application_frontier_hash,
                "application event frontier",
            ),
            (
                self.measurement_basis_ref,
                self.measurement_basis_hash,
                "application measurement basis",
            ),
        )
        for ref, digest, label in addressed:
            _validate_content_address(ref, digest, label)
        required_prefixes = (
            (self.exposure_ref, "context-exposure@sha256:"),
            (self.behavior_ref, "capability-behavior-observation@sha256:"),
            (self.outcome_ref, "outcome-receipt@sha256:"),
            (self.outcome_append_receipt_ref, "event-append-receipt@sha256:"),
            (self.measurement_basis_ref, "measurement-basis@sha256:"),
        )
        if any(not ref.startswith(prefix) for ref, prefix in required_prefixes):
            raise ValueError("measurement application requires exact typed evidence refs")
        if not self.update_target_ref.startswith("learning-target:"):
            raise ValueError("measurement application requires one typed update target")
        if _CONTENT_ADDRESS_PATTERN.fullmatch(self.producer_resolution_obligation_ref) is None:
            raise ValueError("application producer resolution obligation must be exact")
        if any(
            _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None
            for ref in self.producer_verification_refs
        ):
            raise ValueError("application producer verification refs must be exact")
        expected_resolution_state = (
            ContextState(value_state="present", reason_codes=())
            if self.producer_verification_refs
            else ContextState(
                value_state="hold",
                reason_codes=("gate0b_producer_resolution_required",),
            )
        )
        if self.producer_resolution_state != expected_resolution_state:
            raise ValueError("application producer state must derive from verification refs")
        if any(
            not ref.startswith("fitness-boundary@sha256:")
            or _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None
            for ref in self.fitness_boundary_refs
        ):
            raise ValueError("measurement application boundaries must be exact addresses")
        for ref in (*self.correction_refs, *self.supersedes_refs):
            if (
                not ref.startswith("measurement-application-receipt@sha256:")
                or _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None
            ):
                raise ValueError("application lineage requires exact application receipt refs")
        if self.application_ref in {*self.correction_refs, *self.supersedes_refs}:
            raise ValueError("an application receipt cannot correct or supersede itself")
        if self.state.value_state != "present":
            raise ValueError("a recorded measurement application must be present")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"application_ref", "application_hash"},
        )
        expected_hash = _domain_hash("hapax.measurement-application-receipt.v1", body)
        if self.application_hash != expected_hash:
            raise ValueError("application_hash does not bind the application receipt")
        if self.application_ref != (
            f"measurement-application-receipt@sha256:{expected_hash}"
        ):
            raise ValueError("application_ref does not bind application_hash")
        return self


class _OutcomeReceiptContentAddress(FrozenModel):
    """Exact local mirror of shared.execution_admission.ContentAddress."""

    ref: str
    sha256: str = Field(pattern=_HASH_PATTERN)

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        return _validate_wire_string(value)


class _OutcomeReceiptBody(FrozenModel):
    """Exact aliased body of shared.execution_admission.OutcomeReceipt v1."""

    schema_id: Literal["hapax.outcome-receipt.v1"] = Field(alias="schema")
    execution_lease: _OutcomeReceiptContentAddress
    bound_execution_call: _OutcomeReceiptContentAddress
    effect_observation: _OutcomeReceiptContentAddress
    completion_evaluation: _OutcomeReceiptContentAddress
    outcome_readiness: _OutcomeReceiptContentAddress
    effect_manifest: _OutcomeReceiptContentAddress
    executor_descriptor: _OutcomeReceiptContentAddress
    executor_registry_projection: _OutcomeReceiptContentAddress
    executor: _OutcomeReceiptContentAddress
    observation_contract: _OutcomeReceiptContentAddress
    completion_predicate: _OutcomeReceiptContentAddress
    invocation_id: str
    attempt_fence: str = Field(pattern=_HASH_PATTERN)
    idempotency_key: str
    committer: _OutcomeReceiptContentAddress
    append_receipt: _OutcomeReceiptContentAddress
    outcome_event: _OutcomeReceiptContentAddress
    event_frontier: _OutcomeReceiptContentAddress
    outcome: Literal["succeeded", "failed", "indeterminate"]
    effect_disposition: Literal[
        "applied",
        "not_applied",
        "partial",
        "not_applicable",
        "unknown",
    ]
    closure_state: Literal["closed", "open"]
    reconciliation_contract: _OutcomeReceiptContentAddress
    committed_at: str
    may_authorize: Literal[False]

    @field_validator("invocation_id", "idempotency_key")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("committed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        _parse_outcome_receipt_timestamp(value, "committed_at")
        return value

    @model_validator(mode="after")
    def validate_closure(self) -> Self:
        open_loop = self.outcome == "indeterminate" or self.effect_disposition in {
            "partial",
            "unknown",
        }
        if (self.closure_state == "open") != open_loop:
            raise ValueError("outcome receipt closure differs from its semantic evidence")
        return self


class CommittedOutcomeReceiptLike(Protocol):
    """Minimum typed surface accepted by the pure observability join."""

    receipt_ref: str
    receipt_hash: str

    def model_dump(
        self,
        *,
        mode: Literal["json"],
        by_alias: bool,
        exclude: set[str],
    ) -> Mapping[str, Any]: ...


def _validated_committed_outcome_receipt(
    outcome_receipt: CommittedOutcomeReceiptLike,
) -> _OutcomeReceiptBody:
    """Validate the exact private OutcomeReceipt v1 body and its domain address."""

    raw_body = outcome_receipt.model_dump(
        mode="json",
        by_alias=True,
        exclude={"receipt_ref", "receipt_hash"},
    )
    try:
        outcome = _OutcomeReceiptBody.model_validate(raw_body)
    except ValidationError as exc:
        raise ValueError(
            "applied learning requires the exact complete OutcomeReceipt v1 body"
        ) from exc
    body = outcome.model_dump(mode="json", by_alias=True)
    expected_hash = _domain_hash("hapax.outcome-receipt.v1", body)
    if (
        outcome_receipt.receipt_hash != expected_hash
        or outcome_receipt.receipt_ref != f"outcome-receipt@sha256:{expected_hash}"
    ):
        raise ValueError("OutcomeReceipt self-hash does not bind its complete canonical body")
    _validate_content_address(
        outcome_receipt.receipt_ref,
        outcome_receipt.receipt_hash,
        "committed outcome receipt",
    )
    return outcome


def _observability_fanout_state(
    *,
    consumer_registry_complete: bool,
    unregistered_consumer_refs: Sequence[str],
    outcome_correction_refs: Sequence[str],
) -> ContextState:
    reasons: set[str] = set()
    if not consumer_registry_complete or unregistered_consumer_refs:
        reasons.add("gate0b_unregistered_consumer_fanout_required")
    if outcome_correction_refs:
        reasons.add("gate0b_outcome_correction_fanout_required")
    return (
        ContextState(value_state="hold", reason_codes=tuple(sorted(reasons)))
        if reasons
        else ContextState(value_state="present", reason_codes=())
    )


class ObservabilityInvalidationResult(FrozenModel):
    invalidated_refs: tuple[str, ...]
    unregistered_consumer_refs: tuple[str, ...]
    outcome_correction_refs: tuple[str, ...]
    consumer_registry_complete: bool = Field(strict=True)
    fanout_state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "invalidated_refs",
        "unregistered_consumer_refs",
        "outcome_correction_refs",
    )
    @classmethod
    def validate_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        checked = _validate_string_set(value, info.field_name)
        if any(_CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None for ref in checked):
            raise ValueError("invalidation result refs must be exact content addresses")
        return checked

    @model_validator(mode="after")
    def validate_fanout_state(self) -> Self:
        expected = _observability_fanout_state(
            consumer_registry_complete=self.consumer_registry_complete,
            unregistered_consumer_refs=self.unregistered_consumer_refs,
            outcome_correction_refs=self.outcome_correction_refs,
        )
        if self.fanout_state != expected:
            raise ValueError("fanout_state must derive from registry and correction coverage")
        return self


def derive_invalidated_observability_refs(
    *,
    exposures: Sequence[ContextExposure] = (),
    behaviors: Sequence[CapabilityBehaviorObservation] = (),
    learning_receipts: Sequence[SignalLearningReceipt] = (),
    application_receipts: Sequence[MeasurementApplicationReceipt] = (),
    unregistered_consumer_refs: Sequence[str] = (),
    outcome_correction_refs: Sequence[str] = (),
    consumer_registry_complete: bool = False,
) -> ObservabilityInvalidationResult:
    """Validate registered correction lineage and derive bounded downstream invalidation."""

    carrier_groups: tuple[
        tuple[
            Sequence[
                ContextExposure
                | CapabilityBehaviorObservation
                | SignalLearningReceipt
                | MeasurementApplicationReceipt
            ],
            str,
        ],
        ...,
    ] = (
        (exposures, "exposure_ref"),
        (behaviors, "behavior_ref"),
        (learning_receipts, "learning_ref"),
        (application_receipts, "application_ref"),
    )

    def natural_key(carrier: Any) -> tuple[str, ...]:
        if isinstance(carrier, ContextExposure):
            return (
                carrier.invocation_id,
                carrier.attempt_fence,
                carrier.session_ref,
                carrier.task_ref,
                carrier.carrier_audience,
            )
        if isinstance(carrier, CapabilityBehaviorObservation):
            return (
                carrier.invocation_id,
                carrier.attempt_fence,
                carrier.session_ref,
                carrier.task_ref,
                carrier.measurement_basis_ref,
                carrier.carrier_audience,
            )
        if isinstance(carrier, SignalLearningReceipt):
            return (carrier.learning_id, carrier.update_target_ref, carrier.position_ref)
        return (
            carrier.application_id,
            carrier.invocation_id,
            carrier.attempt_fence,
            carrier.update_target_ref,
        )

    def lineage_time(carrier: Any) -> str | None:
        if isinstance(carrier, ContextExposure):
            return carrier.observed_at
        if isinstance(carrier, CapabilityBehaviorObservation):
            return carrier.observed_at
        if isinstance(carrier, SignalLearningReceipt):
            return carrier.recorded_at
        return carrier.applied_at

    invalidated: set[str] = set()
    correction_edges: dict[str, set[str]] = {}
    for carriers, ref_field in carrier_groups:
        carrier_by_ref = {getattr(carrier, ref_field): carrier for carrier in carriers}
        if len(carrier_by_ref) != len(carriers):
            raise ValueError("correction registry cannot contain duplicate carrier identities")
        for carrier in carriers:
            current_ref = getattr(carrier, ref_field)
            for prior_ref in (*carrier.correction_refs, *carrier.supersedes_refs):
                prior = carrier_by_ref.get(prior_ref)
                if prior is None:
                    raise ValueError(
                        "correction lineage must resolve within its supplied carrier set"
                    )
                current_time = lineage_time(carrier)
                prior_time = lineage_time(prior)
                if natural_key(carrier) != natural_key(prior):
                    raise ValueError("correction lineage must preserve the carrier natural key")
                if current_time is None or prior_time is None or current_time <= prior_time:
                    raise ValueError(
                        "correction successor must have a strictly later recorded time"
                    )
                correction_edges.setdefault(current_ref, set()).add(prior_ref)
                invalidated.add(prior_ref)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(ref: str) -> None:
        if ref in visiting:
            raise ValueError("correction lineage cannot contain a cycle")
        if ref in visited:
            return
        visiting.add(ref)
        for prior_ref in correction_edges.get(ref, set()):
            visit(prior_ref)
        visiting.remove(ref)
        visited.add(ref)

    for ref in correction_edges:
        visit(ref)

    checked_outcome_corrections = _validate_string_set(
        tuple(outcome_correction_refs),
        "outcome_correction_refs",
    )
    if any(
        not ref.startswith("outcome-receipt@sha256:")
        or _CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None
        for ref in checked_outcome_corrections
    ):
        raise ValueError("outcome correction refs must be exact OutcomeReceipt addresses")
    invalidated.update(checked_outcome_corrections)

    changed = True
    while changed:
        changed = False
        for behavior in behaviors:
            if behavior.exposure_ref in invalidated and behavior.behavior_ref not in invalidated:
                invalidated.add(behavior.behavior_ref)
                changed = True
        for receipt in learning_receipts:
            if (
                receipt.exposure_ref in invalidated
                or (receipt.behavior_ref is not None and receipt.behavior_ref in invalidated)
                or receipt.outcome_ref in invalidated
            ):
                if receipt.learning_ref not in invalidated:
                    invalidated.add(receipt.learning_ref)
                    changed = True
        for application in application_receipts:
            associated_learning_invalid = any(
                learning.receipt_ref == application.application_ref
                and learning.learning_ref in invalidated
                for learning in learning_receipts
            )
            if (
                application.exposure_ref in invalidated
                or application.behavior_ref in invalidated
                or application.outcome_ref in invalidated
                or associated_learning_invalid
            ) and application.application_ref not in invalidated:
                invalidated.add(application.application_ref)
                changed = True

    checked_unregistered = _validate_string_set(
        tuple(unregistered_consumer_refs),
        "unregistered_consumer_refs",
    )
    if any(_CONTENT_ADDRESS_PATTERN.fullmatch(ref) is None for ref in checked_unregistered):
        raise ValueError("unregistered consumer refs must be exact content addresses")
    fanout_state = _observability_fanout_state(
        consumer_registry_complete=consumer_registry_complete,
        unregistered_consumer_refs=checked_unregistered,
        outcome_correction_refs=checked_outcome_corrections,
    )
    return ObservabilityInvalidationResult(
        invalidated_refs=tuple(sorted(invalidated)),
        unregistered_consumer_refs=checked_unregistered,
        outcome_correction_refs=checked_outcome_corrections,
        consumer_registry_complete=consumer_registry_complete,
        fanout_state=fanout_state,
        no_effect=True,
        may_authorize=False,
    )


def validate_context_behavior_learning_join(
    *,
    exposure: ContextExposure,
    behavior: CapabilityBehaviorObservation,
    learning: SignalLearningReceipt,
    exposure_event: EpistemicFlowEvent,
    behavior_event: EpistemicFlowEvent,
    outcome_receipt: CommittedOutcomeReceiptLike,
    application_receipt: MeasurementApplicationReceipt,
    invalidated_refs: Sequence[str] = (),
) -> tuple[str, str, str, str, str]:
    """Validate the minimum no-effect exposure-to-learning evidence chain.

    This function validates structural identities and chronology only. It does not authenticate
    named producers, prove frontier ancestry, attribute causality, apply a learning update,
    change policy, admit an action, or authorize execution.
    """

    invalidated = set(_validate_string_set(tuple(invalidated_refs), "invalidated_refs"))
    joined_refs = {
        exposure.exposure_ref,
        behavior.behavior_ref,
        learning.learning_ref,
        outcome_receipt.receipt_ref,
        application_receipt.application_ref,
    }
    if joined_refs & invalidated:
        raise ValueError("an invalidated exposure, behavior, learning, or outcome cannot join")
    if (
        exposure.producer_resolution_state.value_state != "present"
        or behavior.producer_resolution_state.value_state != "present"
        or not exposure.producer_verification_refs
        or not behavior.producer_verification_refs
    ):
        raise ValueError("applied learning requires Gate0B-verified exposure and behavior")

    exact_identity_pairs = (
        (behavior.invocation_id, exposure.invocation_id, "invocation id"),
        (behavior.attempt_fence, exposure.attempt_fence, "attempt fence"),
        (behavior.invocation_ref, exposure.invocation_ref, "invocation"),
        (behavior.served_identity_ref, exposure.served_identity_ref, "served identity"),
        (behavior.demand_shape_ref, exposure.demand_shape_ref, "demand shape"),
        (
            behavior.measurement_basis_ref,
            exposure.measurement_basis_ref,
            "measurement basis",
        ),
        (behavior.context_frontier_ref, exposure.context_frontier_ref, "context frontier"),
        (behavior.session_ref, exposure.session_ref, "session"),
        (behavior.task_ref, exposure.task_ref, "task"),
        (behavior.trace_ref, exposure.trace_ref, "trace"),
        (behavior.scope_ref, exposure.scope_ref, "scope"),
        (behavior.temporal_ref, exposure.temporal_ref, "temporal coordinate"),
        (behavior.resolution_ref, exposure.resolution_ref, "resolution coordinate"),
        (behavior.position_ref, exposure.position_ref, "lifecycle position"),
    )
    if behavior.exposure_ref != exposure.exposure_ref or (
        behavior.exposure_hash != exposure.exposure_hash
    ):
        raise ValueError("behavior must bind the exact context exposure")
    for observed, expected, label in exact_identity_pairs:
        if observed != expected:
            raise ValueError(f"behavior and exposure disagree on {label}")
    exact_hash_pairs = (
        (behavior.invocation_hash, exposure.invocation_hash, "invocation"),
        (behavior.served_identity_hash, exposure.served_identity_hash, "served identity"),
        (
            behavior.demand_shape_fingerprint,
            exposure.demand_shape_fingerprint,
            "demand shape",
        ),
        (
            behavior.measurement_basis_hash,
            exposure.measurement_basis_hash,
            "measurement basis",
        ),
        (behavior.context_frontier_hash, exposure.context_frontier_hash, "context frontier"),
    )
    for observed, expected, label in exact_hash_pairs:
        if observed != expected:
            raise ValueError(f"behavior and exposure disagree on {label} hash")
    if (
        behavior.behavior_frontier_parent_ref != exposure.context_frontier_ref
        or behavior.behavior_frontier_parent_hash != exposure.context_frontier_hash
        or behavior.behavior_event_frontier_ref == exposure.context_frontier_ref
    ):
        raise ValueError("behavior must descend from, not reuse, the frozen context frontier")

    presented_at = exposure.stages[
        _CONTEXT_EXPOSURE_STAGE_ORDER.index("presented")
    ].occurred_at
    if any(item.observed_at < presented_at for item in behavior.observations):
        raise ValueError("behavior evidence cannot predate context presentation")
    if any(
        not behavior.valid_from <= item.observed_at <= behavior.valid_until
        for item in behavior.observations
    ):
        raise ValueError("behavior datum lies outside the behavior validity interval")

    event_identity = (
        "session_ref",
        "task_ref",
        "trace_ref",
        "position_ref",
        "scope_ref",
        "temporal_ref",
        "resolution_ref",
    )
    for field_name in event_identity:
        expected = getattr(exposure, field_name)
        if getattr(exposure_event, field_name) != expected or (
            getattr(behavior_event, field_name) != expected
        ):
            raise ValueError(f"observability events disagree on {field_name}")
    if (
        exposure_event.kind != "context_exposure_recorded"
        or exposure_event.subject_ref != exposure.exposure_ref
        or getattr(exposure_event.payload, "exposure_ref", None) != exposure.exposure_ref
        or getattr(exposure_event.payload, "exposure_state", None)
        != exposure.state.value_state
        or exposure.exposure_ref not in exposure_event.source_refs
    ):
        raise ValueError("exposure event does not exactly record the joined exposure")
    if (
        behavior_event.kind != "capability_behavior_observed"
        or behavior_event.subject_ref != behavior.behavior_ref
        or getattr(behavior_event.payload, "behavior_ref", None) != behavior.behavior_ref
        or getattr(behavior_event.payload, "behavior_state", None)
        != behavior.state.value_state
        or behavior.behavior_ref not in behavior_event.source_refs
        or exposure.exposure_ref not in behavior_event.source_refs
    ):
        raise ValueError("behavior event does not exactly record the joined behavior")
    if exposure_event.event_ref in behavior_event.caused_by:
        raise ValueError(
            "correlation-only behavior cannot place the exposure event in causal ancestry"
        )
    if exposure_event.generation >= behavior_event.generation or (
        exposure_event.occurred_at >= behavior_event.occurred_at
    ):
        raise ValueError("behavior event generation and time must follow exposure recording")
    if not exposure.observed_at <= exposure_event.occurred_at <= min(
        item.observed_at for item in behavior.observations
    ):
        raise ValueError("exposure recording must precede the externally observed behavior")
    if behavior_event.occurred_at < behavior.observed_at:
        raise ValueError("behavior event cannot predate its complete observation")

    expected_boundaries = tuple(
        sorted({item.fitness_boundary_ref for item in behavior.observations})
    )
    if (
        learning.exposure_ref != exposure.exposure_ref
        or learning.behavior_ref != behavior.behavior_ref
        or learning.measurement_basis_ref != behavior.measurement_basis_ref
        or learning.fitness_boundary_refs != expected_boundaries
    ):
        raise ValueError("learning must bind exact exposure, behavior, basis, and boundaries")
    if behavior.behavior_ref not in learning.witness_refs:
        raise ValueError("learning witnesses must include the exact behavior observation")
    if learning.position_ref != exposure.position_ref:
        raise ValueError("learning receipt must bind the same lifecycle position")
    if not learning.update_applied:
        raise ValueError("the applied-learning join cannot apply a held legacy receipt")
    outcome = _validated_committed_outcome_receipt(outcome_receipt)
    _validate_content_address(
        outcome.event_frontier.ref,
        outcome.event_frontier.sha256,
        "outcome event frontier",
    )
    _validate_content_address(
        outcome.append_receipt.ref,
        outcome.append_receipt.sha256,
        "outcome event append receipt",
    )
    if not outcome_receipt.receipt_ref.startswith("outcome-receipt@sha256:"):
        raise ValueError("applied learning requires a typed committed outcome receipt")
    if not outcome.append_receipt.ref.startswith("event-append-receipt@sha256:"):
        raise ValueError("applied learning requires the exact outcome event append receipt")
    outcome_committed_at = _parse_outcome_receipt_timestamp(
        outcome.committed_at,
        "committed_at",
    )
    behavior_observed_at = datetime.strptime(
        behavior.observed_at,
        "%Y-%m-%dT%H:%M:%SZ",
    ).replace(tzinfo=UTC)
    if (
        learning.outcome_ref != outcome_receipt.receipt_ref
        or outcome.invocation_id != exposure.invocation_id
        or outcome.attempt_fence != exposure.attempt_fence
        or outcome.outcome == "indeterminate"
        or outcome.effect_disposition in {"partial", "unknown"}
        or outcome.closure_state != "closed"
        or outcome.event_frontier.ref == behavior.behavior_event_frontier_ref
        or outcome.may_authorize
        or outcome_committed_at < behavior_observed_at
    ):
        raise ValueError("applied learning does not bind a current committed outcome")
    expected_boundaries = tuple(
        sorted({item.fitness_boundary_ref for item in behavior.observations})
    )
    if (
        learning.receipt_ref != application_receipt.application_ref
        or application_receipt.invocation_id != exposure.invocation_id
        or application_receipt.attempt_fence != exposure.attempt_fence
        or application_receipt.exposure_ref != exposure.exposure_ref
        or application_receipt.exposure_hash != exposure.exposure_hash
        or application_receipt.behavior_ref != behavior.behavior_ref
        or application_receipt.behavior_hash != behavior.behavior_hash
        or application_receipt.outcome_ref != outcome_receipt.receipt_ref
        or application_receipt.outcome_hash != outcome_receipt.receipt_hash
        or application_receipt.outcome_append_receipt_ref
        != outcome.append_receipt.ref
        or application_receipt.outcome_append_receipt_hash
        != outcome.append_receipt.sha256
        or application_receipt.measurement_basis_ref != behavior.measurement_basis_ref
        or application_receipt.measurement_basis_hash != behavior.measurement_basis_hash
        or application_receipt.fitness_boundary_refs != expected_boundaries
        or application_receipt.update_target_ref != learning.update_target_ref
        or not application_receipt.producer_verification_refs
        or application_receipt.producer_resolution_state.value_state != "present"
        or application_receipt.application_frontier_ref
        == outcome.event_frontier.ref
        or datetime.strptime(
            application_receipt.applied_at,
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=UTC)
        < outcome_committed_at
        or learning.recorded_at is None
        or learning.recorded_at < application_receipt.applied_at
    ):
        raise ValueError("learning does not bind the exact one-target measurement application")
    return (
        exposure.exposure_ref,
        behavior.behavior_ref,
        learning.learning_ref,
        outcome_receipt.receipt_ref,
        application_receipt.application_ref,
    )


class OrientingSignal(FrozenModel):
    signal_ref: str
    signal_hash: str = Field(pattern=_HASH_PATTERN)
    signal_id: str
    kind: str
    label: str
    position_ref: str
    estimate_refs: tuple[str, ...] = Field(min_length=1)
    lens_ref: str
    constellation_ref: str
    value_vector: OrientationValueVector
    source_fact_refs: tuple[str, ...] = Field(min_length=1)
    why_now: str
    does_not_prove: tuple[str, ...] = Field(min_length=1)
    uncertainty: str
    privacy_class: str
    portal_ref: str | None
    state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "signal_ref",
        "signal_id",
        "kind",
        "label",
        "position_ref",
        "lens_ref",
        "constellation_ref",
        "why_now",
        "uncertainty",
        "privacy_class",
        "portal_ref",
    )
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator("estimate_refs", "source_fact_refs", "does_not_prove")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name, allow_empty=False)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        body = self.model_dump(mode="json", by_alias=True, exclude={"signal_ref", "signal_hash"})
        expected_hash = _domain_hash("hapax.orienting-signal.v1", body)
        if self.signal_hash != expected_hash:
            raise ValueError("signal_hash does not bind the attention offer")
        if self.signal_ref != f"orienting-signal@sha256:{expected_hash}":
            raise ValueError("signal_ref does not bind signal_hash")
        return self


class PortalOffer(FrozenModel):
    portal_ref: str
    kind: str
    purpose: str
    source_fact_refs: tuple[str, ...] = Field(min_length=1)
    state: ContextState
    effectivity_basis: tuple[str, ...] = Field(min_length=1)
    privacy_class: str
    budget_ref: str
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator("portal_ref", "kind", "purpose", "privacy_class", "budget_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("source_fact_refs", "effectivity_basis")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name, allow_empty=False)


_EPISTEMIC_EVENT_PAYLOAD_FIELDS: dict[str, tuple[str, ...]] = {
    "observation_recorded": ("observation_ref", "observation_state"),
    "context_fact_derived": ("derivation_ref", "fact_ref"),
    "context_frame_materialized": ("frame_ref", "frame_state"),
    "projection_materialized": ("projection_ref", "projection_state"),
    "context_exposure_recorded": ("exposure_ref", "exposure_state"),
    "capability_behavior_observed": ("behavior_ref", "behavior_state"),
    "orienting_signal_offered": ("offer_state", "signal_ref"),
    "portal_pull_requested": ("portal_ref", "request_state"),
    "portal_consumed": ("consumption_receipt_ref", "consumption_state", "portal_ref"),
    "inquiry": ("inquiry_ref", "inquiry_state"),
    "counterfactual": ("action_ref", "counterfactual_state"),
    "intent_expressed": ("action_ref", "intent_kind", "intent_state"),
    "stipulation_recorded": ("stipulation_ref", "stipulation_state"),
    "consent_recorded": ("consent_ref", "consent_state"),
    "lease_referenced": ("lease_ref", "lease_state"),
    "effect_observed": ("effect_ref", "outcome_state"),
    "measurement_updated": ("learning_target_ref", "measurement_ref", "measurement_state"),
    "receipt_recorded": ("receipt_ref", "receipt_state"),
    "correction": ("corrected_ref", "correction_ref"),
    "supersession": ("superseded_ref", "superseding_ref"),
}


EpistemicEventKind = Literal[
    "observation_recorded",
    "context_fact_derived",
    "context_frame_materialized",
    "projection_materialized",
    "context_exposure_recorded",
    "capability_behavior_observed",
    "orienting_signal_offered",
    "portal_pull_requested",
    "portal_consumed",
    "inquiry",
    "counterfactual",
    "intent_expressed",
    "stipulation_recorded",
    "consent_recorded",
    "lease_referenced",
    "effect_observed",
    "measurement_updated",
    "receipt_recorded",
    "correction",
    "supersession",
]


class _EpistemicEventPayload(FrozenModel):
    @field_validator("*", check_fields=False)
    @classmethod
    def validate_payload_value(cls, value: str) -> str:
        return _validate_wire_string(value)


class ObservationRecordedPayload(_EpistemicEventPayload):
    kind: Literal["observation_recorded"]
    observation_ref: str
    observation_state: str


class ContextFactDerivedPayload(_EpistemicEventPayload):
    kind: Literal["context_fact_derived"]
    derivation_ref: str
    fact_ref: str


class ContextFrameMaterializedPayload(_EpistemicEventPayload):
    kind: Literal["context_frame_materialized"]
    frame_ref: str
    frame_state: str


class ProjectionMaterializedPayload(_EpistemicEventPayload):
    kind: Literal["projection_materialized"]
    projection_ref: str
    projection_state: str


class ContextExposureRecordedPayload(_EpistemicEventPayload):
    kind: Literal["context_exposure_recorded"]
    exposure_ref: str
    exposure_state: str


class CapabilityBehaviorObservedPayload(_EpistemicEventPayload):
    kind: Literal["capability_behavior_observed"]
    behavior_ref: str
    behavior_state: str


class OrientingSignalOfferedPayload(_EpistemicEventPayload):
    kind: Literal["orienting_signal_offered"]
    offer_state: str
    signal_ref: str


class PortalPullRequestedPayload(_EpistemicEventPayload):
    kind: Literal["portal_pull_requested"]
    portal_ref: str
    request_state: str


class PortalConsumedPayload(_EpistemicEventPayload):
    kind: Literal["portal_consumed"]
    consumption_receipt_ref: str
    consumption_state: str
    portal_ref: str


class InquiryPayload(_EpistemicEventPayload):
    kind: Literal["inquiry"]
    inquiry_ref: str
    inquiry_state: str


class CounterfactualPayload(_EpistemicEventPayload):
    kind: Literal["counterfactual"]
    action_ref: str
    counterfactual_state: str


class IntentExpressedPayload(_EpistemicEventPayload):
    kind: Literal["intent_expressed"]
    action_ref: str
    intent_kind: str
    intent_state: str


class StipulationRecordedPayload(_EpistemicEventPayload):
    kind: Literal["stipulation_recorded"]
    stipulation_ref: str
    stipulation_state: str


class ConsentRecordedPayload(_EpistemicEventPayload):
    kind: Literal["consent_recorded"]
    consent_ref: str
    consent_state: str


class LeaseReferencedPayload(_EpistemicEventPayload):
    kind: Literal["lease_referenced"]
    lease_ref: str
    lease_state: str


class EffectObservedPayload(_EpistemicEventPayload):
    kind: Literal["effect_observed"]
    effect_ref: str
    outcome_state: str


class MeasurementUpdatedPayload(_EpistemicEventPayload):
    kind: Literal["measurement_updated"]
    learning_target_ref: str
    measurement_ref: str
    measurement_state: str


class ReceiptRecordedPayload(_EpistemicEventPayload):
    kind: Literal["receipt_recorded"]
    receipt_ref: str
    receipt_state: str


class CorrectionPayload(_EpistemicEventPayload):
    kind: Literal["correction"]
    corrected_ref: str
    correction_ref: str


class SupersessionPayload(_EpistemicEventPayload):
    kind: Literal["supersession"]
    superseded_ref: str
    superseding_ref: str


EpistemicEventPayload = Annotated[
    ObservationRecordedPayload
    | ContextFactDerivedPayload
    | ContextFrameMaterializedPayload
    | ProjectionMaterializedPayload
    | ContextExposureRecordedPayload
    | CapabilityBehaviorObservedPayload
    | OrientingSignalOfferedPayload
    | PortalPullRequestedPayload
    | PortalConsumedPayload
    | InquiryPayload
    | CounterfactualPayload
    | IntentExpressedPayload
    | StipulationRecordedPayload
    | ConsentRecordedPayload
    | LeaseReferencedPayload
    | EffectObservedPayload
    | MeasurementUpdatedPayload
    | ReceiptRecordedPayload
    | CorrectionPayload
    | SupersessionPayload,
    Field(discriminator="kind"),
]


class EpistemicFlowEvent(FrozenModel):
    event_ref: str
    event_hash: str = Field(pattern=_HASH_PATTERN)
    event_id: str
    kind: EpistemicEventKind
    session_ref: str
    task_ref: str
    trace_ref: str
    position_ref: str
    scope_ref: str
    temporal_ref: str
    resolution_ref: str
    generation: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    subject_ref: str
    occurred_at: str
    expires_at: str
    producer_ref: str
    method_ref: str
    privacy_class: str
    authority_ceiling: AuthorityCeiling
    source_refs: tuple[str, ...] = Field(min_length=1)
    caused_by: tuple[str, ...]
    supersedes_refs: tuple[str, ...]
    derivation_depth: int = Field(ge=0, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    payload: EpistemicEventPayload
    state: ContextState
    may_authorize: Literal[False]

    @field_validator(
        "event_ref",
        "event_id",
        "session_ref",
        "trace_ref",
        "position_ref",
        "scope_ref",
        "temporal_ref",
        "resolution_ref",
        "subject_ref",
        "producer_ref",
        "method_ref",
        "privacy_class",
        "authority_ceiling",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("source_refs", "caused_by", "supersedes_refs")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value, info.field_name, allow_empty=info.field_name != "source_refs"
        )

    @field_validator("occurred_at", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: str, info: Any) -> str:
        return _validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if self.occurred_at > self.expires_at:
            raise ValueError("event expiry must not precede occurrence")
        if self.payload.kind != self.kind:
            raise ValueError("epistemic event kind must equal its typed payload kind")
        body = self.model_dump(mode="json", by_alias=True, exclude={"event_ref", "event_hash"})
        expected_hash = _domain_hash("hapax.epistemic-flow-event.v1", body)
        if self.event_hash != expected_hash:
            raise ValueError("event_hash does not bind the event")
        if self.event_ref != f"epistemic-event@sha256:{expected_hash}":
            raise ValueError("event_ref does not bind event_hash")
        return self


class AuthorizationFlag(FrozenModel):
    name: str
    authorized: bool = Field(strict=True)
    source_ref: str

    @field_validator("name", "source_ref")
    @classmethod
    def validate_string(cls, value: str, info: Any) -> str:
        checked = _validate_wire_string(value)
        if info.field_name == "source_ref" and checked.startswith("portal-consumption@sha256:"):
            raise ValueError(
                "portal consumption is offer-plane evidence and cannot source authority"
            )
        return checked


class ContextPosition(FrozenModel):
    position_ref: str
    position_hash: str = Field(pattern=_HASH_PATTERN)
    task_ref: str
    stage_token: str
    lifecycle_definition: LifecycleDefinition
    legal_successors: tuple[str, ...]
    authority_case: str
    authorized_flags: tuple[AuthorizationFlag, ...]
    mutation_scope_refs: tuple[str, ...]
    claim_ref: str
    route_decision_ref: str
    canon_bundle_ref: str
    canon_bundle_hash: str = Field(pattern=_HASH_PATTERN)
    canon_id: str
    canon_image_hash: str = Field(pattern=_HASH_PATTERN)
    lifecycle_fsm_data_sha256: str = Field(pattern=_HASH_PATTERN)
    canon_version: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    canon_level: ProjectionLevel
    lifecycle_definition_ref: str
    lifecycle_definition_hash: str = Field(pattern=_HASH_PATTERN)
    demand_shape_fingerprint: str = Field(pattern=_HASH_PATTERN)
    effective_constraint_digest: str = Field(pattern=_HASH_PATTERN)
    impingement_digest: str = Field(pattern=_HASH_PATTERN)
    portal_set_digest: str = Field(pattern=_HASH_PATTERN)
    receipt_lineage: tuple[str, ...] = Field(min_length=1)
    may_authorize: Literal[False]

    @field_validator(
        "position_ref",
        "task_ref",
        "stage_token",
        "authority_case",
        "claim_ref",
        "route_decision_ref",
        "canon_bundle_ref",
        "canon_id",
        "lifecycle_definition_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("legal_successors", "mutation_scope_refs")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name)

    @field_validator("receipt_lineage")
    @classmethod
    def validate_receipt_lineage(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_validate_wire_string(item) != item for item in value):
            raise ValueError("receipt_lineage entries must be valid strings")
        return value

    @model_validator(mode="after")
    def validate_position(self) -> Self:
        if (
            self.lifecycle_definition.definition_ref != self.lifecycle_definition_ref
            or self.lifecycle_definition.definition_hash != self.lifecycle_definition_hash
        ):
            raise ValueError("position lifecycle definition differs from its definition commitment")
        lifecycle_stage = _lifecycle_stage(self.lifecycle_definition, self.stage_token)
        expected_successors = tuple(
            sorted({edge.to for edge in (*lifecycle_stage.next, *lifecycle_stage.fall)})
        )
        if self.legal_successors != expected_successors:
            raise ValueError("position legal successors differ from its lifecycle stage")
        flag_names = tuple(item.name for item in self.authorized_flags)
        if flag_names != tuple(sorted(set(flag_names))):
            raise ValueError("authorization flags must be sorted and unique by name")
        if len(self.receipt_lineage) != len(set(self.receipt_lineage)):
            raise ValueError("receipt_lineage cannot contain duplicates")
        if self.canon_bundle_ref != f"canon-bundle@sha256:{self.canon_bundle_hash}":
            raise ValueError("canon_bundle_ref does not bind canon_bundle_hash")
        constraint_body = {
            "authority_case": self.authority_case,
            "authorized_flags": self.authorized_flags,
            "mutation_scope_refs": self.mutation_scope_refs,
        }
        expected_constraint_digest = _domain_hash("hapax.effective-constraints.v1", constraint_body)
        if self.effective_constraint_digest != expected_constraint_digest:
            raise ValueError("effective_constraint_digest does not bind the exact constraints")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"position_ref", "position_hash"}
        )
        expected_hash = _domain_hash("hapax.context-position.v1", body)
        if self.position_hash != expected_hash:
            raise ValueError("position_hash does not bind the context position")
        if self.position_ref != f"context-position@sha256:{expected_hash}":
            raise ValueError("position_ref does not bind position_hash")
        return self


_CONTEXT_SELECTION_PRIMARY_CLASSES = frozenset({"selected", "rejected", "redacted", "missing"})


class ContextSelectionEntry(FrozenModel):
    """One audience-sealed fact disposition with its local WHY and requiredness."""

    fact_ref: str
    requiredness: ContextSelectionRequiredness
    classes: tuple[ContextSelectionClass, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...]

    @field_validator("fact_ref")
    @classmethod
    def validate_fact_ref(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("classes", "reason_codes")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value,
            info.field_name,
            allow_empty=info.field_name == "reason_codes",
        )

    @model_validator(mode="after")
    def validate_classification(self) -> Self:
        classes = set(self.classes)
        if len(classes & _CONTEXT_SELECTION_PRIMARY_CLASSES) != 1:
            raise ValueError("selection entries require exactly one primary disposition")
        if "missing" in classes and classes & {"stale", "contradicted"}:
            raise ValueError("missing selection entries cannot also be stale or contradicted")
        clean = self.classes == ("selected",)
        if clean == bool(self.reason_codes):
            raise ValueError("non-clean selection entries require WHY; clean selections have none")
        return self


def _context_selection_state(
    entries: Sequence[ContextSelectionEntry],
) -> ContextState:
    blocking_classes = {
        selection_class
        for entry in entries
        if entry.requiredness == "required"
        for selection_class in entry.classes
        if selection_class != "selected"
    }
    if not blocking_classes:
        return ContextState(value_state="present", reason_codes=())
    return ContextState(
        value_state="hold",
        reason_codes=tuple(
            sorted(f"required_context_{selection_class}" for selection_class in blocking_classes)
        ),
    )


class ContextSelection(FrozenModel):
    """Audience-sealed support selection; it records loss and can only HOLD."""

    schema_id: Literal["hapax.context-selection.v1"] = Field(alias="schema")
    selection_ref: str
    selection_hash: str = Field(pattern=_HASH_PATTERN)
    position_ref: str
    position_hash: str = Field(pattern=_HASH_PATTERN)
    fact_frontier_ref: str
    fact_frontier_hash: str = Field(pattern=_HASH_PATTERN)
    frontier_fact_refs: tuple[str, ...] = Field(min_length=1)
    event_frontier_refs: tuple[str, ...] = Field(min_length=1)
    audience: Literal["operator_private", "yard_context", "hapax_substrate", "public_or_air"]
    audience_seal_receipt_ref: str
    audience_seal_receipt_hash: str = Field(pattern=_HASH_PATTERN)
    audience_policy_generation: str
    privacy_policy_generation: str
    selection_policy_ref: str
    selection_policy_hash: str = Field(pattern=_HASH_PATTERN)
    selection_policy_generation: str
    entries: tuple[ContextSelectionEntry, ...] = Field(min_length=1)
    state: ContextState
    checked_at: str
    stale_after: str
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "selection_ref",
        "position_ref",
        "fact_frontier_ref",
        "audience_seal_receipt_ref",
        "audience_policy_generation",
        "privacy_policy_generation",
        "selection_policy_ref",
        "selection_policy_generation",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("frontier_fact_refs", "event_frontier_refs")
    @classmethod
    def validate_frontier_refs(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name, allow_empty=False)

    @field_validator("checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str, info: Any) -> str:
        return _validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.checked_at >= self.stale_after:
            raise ValueError("context selection checking must strictly precede expiry")
        addressed = (
            (self.position_ref, self.position_hash, "context position"),
            (self.fact_frontier_ref, self.fact_frontier_hash, "fact frontier"),
            (
                self.audience_seal_receipt_ref,
                self.audience_seal_receipt_hash,
                "audience seal receipt",
            ),
            (self.selection_policy_ref, self.selection_policy_hash, "selection policy"),
        )
        for ref, digest, label in addressed:
            if not ref.endswith(f"@sha256:{digest}"):
                raise ValueError(f"{label} ref does not bind its hash")
        entry_refs = tuple(entry.fact_ref for entry in self.entries)
        if entry_refs != tuple(sorted(set(entry_refs))):
            raise ValueError("context selection entries must be sorted and unique by fact_ref")
        frontier_refs = set(self.frontier_fact_refs)
        classified_frontier_refs = {
            entry.fact_ref for entry in self.entries if "missing" not in entry.classes
        }
        missing_refs = {entry.fact_ref for entry in self.entries if "missing" in entry.classes}
        if classified_frontier_refs != frontier_refs or missing_refs & frontier_refs:
            raise ValueError(
                "context selection entries must exactly classify the fact frontier and missing set"
            )
        expected_state = _context_selection_state(self.entries)
        if self.state != expected_state:
            raise ValueError("context selection state must derive exactly from required entries")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"selection_ref", "selection_hash"}
        )
        expected_hash = _domain_hash("hapax.context-selection.v1", body)
        if self.selection_hash != expected_hash:
            raise ValueError("selection_hash does not bind the context selection")
        if self.selection_ref != f"context-selection@sha256:{expected_hash}":
            raise ValueError("selection_ref does not bind selection_hash")
        return self


def _derivation_input_authority_rank(
    derivation: DerivationRecord,
    observation_by_ref: Mapping[str, ObservationEnvelope],
    fact_by_id: Mapping[str, Any],
) -> int:
    ranks = [
        *(
            _AUTHORITY_CEILING_RANK[observation_by_ref[ref].authority_ceiling]
            for ref in derivation.input_observation_refs
        ),
        *(
            _PROVENANCE_AUTHORITY_RANK[fact_by_id[ref].provenance.authority_level]
            for ref in derivation.input_fact_refs
        ),
    ]
    if not ranks:
        raise ValueError("derivation authority requires at least one typed input")
    return min(ranks)


def _validate_fact_evidence_and_authority(
    fact: Any,
    derivation: DerivationRecord,
    observation_by_ref: Mapping[str, ObservationEnvelope],
    admission_by_ref: Mapping[str, SourceAdmission],
    fact_by_id: Mapping[str, Any],
    receipt_lineage: tuple[str, ...],
    *,
    label: str,
) -> None:
    derivation_inputs = set(
        (*derivation.input_observation_refs, *derivation.input_fact_refs, *receipt_lineage)
    )
    provenance_refs = set(fact.provenance.source_refs)
    confidence_refs = set(fact.confidence.evidence_refs)
    if provenance_refs - derivation_inputs:
        raise ValueError(f"{label} provenance must cite its named derivation inputs")
    if confidence_refs - derivation_inputs:
        raise ValueError(f"{label} confidence must cite its named derivation inputs")
    if fact.provenance.kind in _SOURCE_PROVENANCE_KINDS and (
        any(
            fact.provenance.kind
            not in admission_by_ref[
                observation_by_ref[ref].source_admission_ref
            ].supported_provenance_kinds
            for ref in derivation.input_observation_refs
        )
        or any(
            fact_by_id[ref].provenance.kind != fact.provenance.kind
            for ref in derivation.input_fact_refs
        )
    ):
        raise ValueError(f"{label} provenance kind exceeds its admitted source classes")
    receipt_prefix = _PROVENANCE_RECEIPT_PREFIXES.get(fact.provenance.kind)
    if receipt_prefix is not None and not (
        any(ref in receipt_lineage and ref.startswith(receipt_prefix) for ref in provenance_refs)
        or any(
            fact_by_id[ref].provenance.kind == fact.provenance.kind
            for ref in derivation.input_fact_refs
        )
    ):
        raise ValueError(f"{label} provenance kind requires a typed position receipt")
    if fact.state.value_state == "present":
        local_evidence_refs = provenance_refs | confidence_refs
        if any(
            observation_by_ref[ref].state.value_state != "present"
            for ref in local_evidence_refs
            if ref in observation_by_ref
        ):
            raise ValueError(f"present {label}s require present observation evidence")
        if any(
            fact_by_id[ref].state.value_state != "present"
            or fact_by_id[ref].freshness_state not in {"fresh", "aging"}
            for ref in local_evidence_refs
            if ref in fact_by_id
        ):
            raise ValueError(f"present {label}s require present, usable fact evidence")
    if _PROVENANCE_AUTHORITY_RANK[fact.provenance.authority_level] > (
        _derivation_input_authority_rank(derivation, observation_by_ref, fact_by_id)
    ):
        raise ValueError(f"{label} authority exceeds its named derivation inputs")


class ContextFrame(FrozenModel):
    schema_id: Literal["hapax.context-frame.v1"] = Field(alias="schema")
    frame_ref: str
    frame_hash: str = Field(pattern=_HASH_PATTERN)
    session_ref: str
    task_ref: str
    lifecycle_definition: LifecycleDefinition
    canon_image: LifecycleCanonImageCarrier
    demand_shape: DemandShapeBinding
    position: ContextPosition
    scopes: tuple[ContextScope, ...] = Field(min_length=1)
    temporal_coordinates: tuple[TemporalCoordinate, ...] = Field(min_length=1)
    resolution_coordinates: tuple[ResolutionCoordinate, ...] = Field(min_length=1)
    source_admissions: tuple[SourceAdmission, ...] = Field(min_length=1)
    observations: tuple[ObservationEnvelope, ...] = Field(min_length=1)
    derivations: tuple[DerivationRecord, ...] = Field(min_length=1)
    facts: tuple[ContextFact, ...] = Field(min_length=1)
    relations: tuple[ContextRelation, ...]
    actions: tuple[ContextAction, ...]
    impingements: tuple[ContextImpingement, ...]
    signal_estimates: tuple[SignalEstimate, ...] = Field(min_length=1)
    signal_lenses: tuple[SignalLens, ...] = Field(min_length=1)
    signal_constellations: tuple[SignalConstellation, ...] = Field(min_length=1)
    orienting_signals: tuple[OrientingSignal, ...]
    portal_offers: tuple[PortalOffer, ...]
    signal_learning_receipts: tuple[SignalLearningReceipt, ...]
    events: tuple[EpistemicFlowEvent, ...] = Field(min_length=1)
    orientation_facets: tuple[BoundaryOrientationFacet, ...]
    lifecycle_possibilities: tuple[LifecyclePossibilityFacet, ...]
    air_bindings: tuple[ContextAirBinding, ...] = Field(min_length=2)
    audience_policy_generation: str
    privacy_policy_generation: str
    observed_at: str
    checked_at: str
    stale_after: str
    may_authorize: Literal[False]

    @field_validator(
        "frame_ref",
        "session_ref",
        "task_ref",
        "audience_policy_generation",
        "privacy_policy_generation",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("observed_at", "checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str, info: Any) -> str:
        return _validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def validate_frame(self) -> Self:
        if not (self.observed_at <= self.checked_at <= self.stale_after):
            raise ValueError("frame timestamps must be observed <= checked <= stale_after")
        keyed = (
            ("scope", tuple(item.scope_ref for item in self.scopes)),
            (
                "temporal coordinate",
                tuple(item.temporal_ref for item in self.temporal_coordinates),
            ),
            (
                "resolution coordinate",
                tuple(item.resolution_ref for item in self.resolution_coordinates),
            ),
            (
                "source admission",
                tuple(item.admission_ref for item in self.source_admissions),
            ),
            (
                "observation",
                tuple(item.observation_ref for item in self.observations),
            ),
            ("derivation", tuple(item.derivation_ref for item in self.derivations)),
            ("fact", tuple(item.fact_id for item in self.facts)),
            ("relation", tuple(item.relation_id for item in self.relations)),
            ("action", tuple(item.action_id for item in self.actions)),
            ("impingement", tuple(item.impingement_id for item in self.impingements)),
            ("estimate", tuple(item.estimate_ref for item in self.signal_estimates)),
            ("lens", tuple(item.lens_ref for item in self.signal_lenses)),
            (
                "constellation",
                tuple(item.constellation_ref for item in self.signal_constellations),
            ),
            ("signal", tuple(item.signal_id for item in self.orienting_signals)),
            ("portal", tuple(item.portal_ref for item in self.portal_offers)),
            (
                "learning receipt",
                tuple(item.learning_ref for item in self.signal_learning_receipts),
            ),
            ("orientation", tuple(item.facet_id for item in self.orientation_facets)),
            (
                "lifecycle possibility",
                tuple(item.facet_id for item in self.lifecycle_possibilities),
            ),
        )
        for name, ids in keyed:
            if ids != tuple(sorted(set(ids))):
                raise ValueError(f"context {name} ids must be sorted and unique")
        event_order = tuple(
            (item.occurred_at, item.generation, item.derivation_depth, item.event_ref)
            for item in self.events
        )
        if event_order != tuple(sorted(set(event_order))):
            raise ValueError("context events must be chronologically ordered and unique")
        event_ids = tuple(item.event_id for item in self.events)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("context event ids must be unique")
        scope_refs = {item.scope_ref for item in self.scopes}
        temporal_refs = {item.temporal_ref for item in self.temporal_coordinates}
        resolution_refs = {item.resolution_ref for item in self.resolution_coordinates}
        temporal_by_ref = {item.temporal_ref: item for item in self.temporal_coordinates}
        resolution_by_ref = {item.resolution_ref: item for item in self.resolution_coordinates}
        admission_refs = {item.admission_ref for item in self.source_admissions}
        admission_by_ref = {item.admission_ref: item for item in self.source_admissions}
        observation_refs = {item.observation_ref for item in self.observations}
        derivation_refs = {item.derivation_ref for item in self.derivations}
        estimate_refs = {item.estimate_ref for item in self.signal_estimates}
        lens_refs = {item.lens_ref for item in self.signal_lenses}
        constellation_refs = {item.constellation_ref for item in self.signal_constellations}
        for scope in self.scopes:
            if set(scope.parent_scope_refs) - scope_refs:
                raise ValueError("context scope parents must resolve in the frame")
        scope_by_ref = {item.scope_ref: item for item in self.scopes}
        for origin in self.scopes:
            visited: set[str] = set()
            pending = list(origin.parent_scope_refs)
            while pending:
                ref = pending.pop()
                if ref == origin.scope_ref:
                    raise ValueError("context scope ancestry must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(scope_by_ref[ref].parent_scope_refs)
        temporal_ancestry = temporal_refs | set(self.position.receipt_lineage)
        for coordinate in self.temporal_coordinates:
            if coordinate.processing_time > self.checked_at:
                raise ValueError("temporal processing cannot follow frame checking")
            dependencies = (*coordinate.parent_span_refs, *coordinate.correction_refs)
            if set(dependencies) - temporal_ancestry:
                raise ValueError("temporal ancestry must resolve in the frame or receipt lineage")
            for correction_ref in coordinate.correction_refs:
                if (
                    correction_ref in temporal_by_ref
                    and temporal_by_ref[correction_ref].processing_time
                    >= coordinate.processing_time
                ):
                    raise ValueError("temporal corrections must reference prior coordinates")
        for origin in self.temporal_coordinates:
            visited: set[str] = set()
            pending = [
                ref
                for ref in (*origin.parent_span_refs, *origin.correction_refs)
                if ref in temporal_by_ref
            ]
            while pending:
                ref = pending.pop()
                if ref == origin.temporal_ref:
                    raise ValueError("temporal ancestry must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                parent = temporal_by_ref[ref]
                pending.extend(
                    dependency
                    for dependency in (*parent.parent_span_refs, *parent.correction_refs)
                    if dependency in temporal_by_ref
                )
        for coordinate in self.resolution_coordinates:
            if coordinate.scope_ref not in scope_refs:
                raise ValueError("resolution scope must resolve in the frame")
            if coordinate.temporal_ref not in temporal_refs:
                raise ValueError("resolution temporal coordinate must resolve in the frame")
        for admission in self.source_admissions:
            if admission.scope_ref not in scope_refs:
                raise ValueError("source admission scope must resolve in the frame")
            if admission.temporal_ref not in temporal_refs:
                raise ValueError("source admission temporal coordinate must resolve in the frame")
            if admission.resolution_ref not in resolution_refs:
                raise ValueError("source admission resolution must resolve in the frame")
            admission_resolution = resolution_by_ref[admission.resolution_ref]
            if (
                admission_resolution.scope_ref != admission.scope_ref
                or admission_resolution.temporal_ref != admission.temporal_ref
            ):
                raise ValueError(
                    "source admission resolution differs from its scope or temporal coordinate"
                )
        for observation in self.observations:
            if observation.source_admission_ref not in admission_refs:
                raise ValueError("observations require an admitted source")
            if observation.scope_ref not in scope_refs:
                raise ValueError("observation scope must resolve in the frame")
            if observation.temporal_ref not in temporal_refs:
                raise ValueError("observation temporal coordinate must resolve in the frame")
            if observation.resolution_ref not in resolution_refs:
                raise ValueError("observation resolution must resolve in the frame")
            observation_resolution = resolution_by_ref[observation.resolution_ref]
            if (
                observation_resolution.scope_ref != observation.scope_ref
                or observation_resolution.temporal_ref != observation.temporal_ref
            ):
                raise ValueError(
                    "observation resolution differs from its scope or temporal coordinate"
                )
            admission = admission_by_ref[observation.source_admission_ref]
            if (
                observation.scope_ref != admission.scope_ref
                or observation.temporal_ref != admission.temporal_ref
                or observation.resolution_ref != admission.resolution_ref
            ):
                raise ValueError("observation coordinates differ from its source admission")
            if observation.authority_ceiling != admission.authority_ceiling:
                raise ValueError(
                    "observation authority ceiling must equal its source admission ceiling"
                )
            if (
                observation.state.value_state == "present"
                and admission.availability.value_state != "present"
            ):
                raise ValueError(
                    "present observations require a presently available source admission"
                )
            if set(observation.source_refs) - (
                observation_refs | set(self.position.receipt_lineage)
            ):
                raise ValueError("observation sources must resolve in the frame or receipts")
            if observation.observation_ref in observation.source_refs:
                raise ValueError("an observation cannot source itself")
        observation_by_ref = {item.observation_ref: item for item in self.observations}
        for origin in self.observations:
            visited: set[str] = set()
            pending = [ref for ref in origin.source_refs if ref in observation_by_ref]
            while pending:
                ref = pending.pop()
                if ref == origin.observation_ref:
                    raise ValueError("observation ancestry must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(
                    parent
                    for parent in observation_by_ref[ref].source_refs
                    if parent in observation_by_ref
                )
        fact_set = {fact.fact_id for fact in self.facts}
        lifecycle_facts = tuple(fact for fact in self.facts if fact.fact_type == "lifecycle_fsm")
        if len(lifecycle_facts) != 1:
            raise ValueError("context frame requires exactly one lifecycle_fsm fact")
        expected_derivation_outputs = fact_set | {
            item.estimate_id for item in self.signal_estimates
        }
        output_owners: dict[str, list[str]] = {}
        fact_by_id = {item.fact_id: item for item in self.facts}
        for derivation in self.derivations:
            if set(derivation.input_observation_refs) - observation_refs:
                raise ValueError("derivation observation inputs must resolve in the frame")
            if set(derivation.input_fact_refs) - fact_set:
                raise ValueError("derivation fact inputs must resolve in the frame")
            if derivation.state.value_state == "present" and any(
                observation_by_ref[ref].state.value_state != "present"
                for ref in derivation.input_observation_refs
            ):
                raise ValueError("present derivations require present observation inputs")
            if derivation.state.value_state == "present" and any(
                fact_by_id[ref].state.value_state != "present" for ref in derivation.input_fact_refs
            ):
                raise ValueError("present derivations require present fact inputs")
            if set(derivation.output_refs) - expected_derivation_outputs:
                raise ValueError("derivation outputs must resolve in the frame")
            for output_ref in derivation.output_refs:
                output_owners.setdefault(output_ref, []).append(derivation.derivation_ref)
        if set(output_owners) != expected_derivation_outputs or any(
            len(owners) != 1 for owners in output_owners.values()
        ):
            raise ValueError("every fact and estimate requires one derivation owner")
        derivation_by_ref = {item.derivation_ref: item for item in self.derivations}
        for fact in self.facts:
            if fact.scope_ref not in scope_refs:
                raise ValueError("fact scope must resolve in the frame")
            if fact.temporal_ref not in temporal_refs:
                raise ValueError("fact temporal coordinate must resolve in the frame")
            if fact.resolution_ref not in resolution_refs:
                raise ValueError("fact resolution must resolve in the frame")
            if (
                resolution_by_ref[fact.resolution_ref].scope_ref != fact.scope_ref
                or resolution_by_ref[fact.resolution_ref].temporal_ref != fact.temporal_ref
            ):
                raise ValueError("fact resolution differs from its scope or temporal coordinate")
            if fact.derivation_ref not in derivation_refs:
                raise ValueError("fact derivation must resolve in the frame")
            if fact.fact_id not in derivation_by_ref[fact.derivation_ref].output_refs:
                raise ValueError("fact is not an output of its named derivation")
            if (
                fact.state.value_state == "present"
                and derivation_by_ref[fact.derivation_ref].state.value_state != "present"
            ):
                raise ValueError("present facts require a present derivation")
            if fact.provenance.produced_at > self.checked_at:
                raise ValueError("fact provenance cannot be produced after frame checking")
            if (
                fact.freshness_state in {"fresh", "aging"}
                and self.checked_at >= fact.provenance.stale_after
            ):
                raise ValueError("fresh and aging facts require unexpired provenance")
            _validate_fact_evidence_and_authority(
                fact,
                derivation_by_ref[fact.derivation_ref],
                observation_by_ref,
                admission_by_ref,
                fact_by_id,
                self.position.receipt_lineage,
                label="fact",
            )
        fact_evidence_dependencies = {
            item.fact_id: {
                ref
                for ref in (
                    *item.provenance.source_refs,
                    *item.confidence.evidence_refs,
                )
                if ref in fact_by_id
            }
            for item in self.facts
        }
        for origin in self.facts:
            visited: set[str] = set()
            pending = list(fact_evidence_dependencies[origin.fact_id])
            while pending:
                ref = pending.pop()
                if ref == origin.fact_id:
                    raise ValueError("fact evidence ancestry must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(fact_evidence_dependencies[ref])
        derivation_dependencies = {
            item.derivation_ref: {fact_by_id[ref].derivation_ref for ref in item.input_fact_refs}
            for item in self.derivations
        }
        for origin in self.derivations:
            visited: set[str] = set()
            pending = list(derivation_dependencies[origin.derivation_ref])
            while pending:
                ref = pending.pop()
                if ref == origin.derivation_ref:
                    raise ValueError("derivation ancestry must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(derivation_dependencies[ref])
        lifecycle_fact = lifecycle_facts[0]
        expected_lifecycle_fact = build_lifecycle_fsm_fact(
            self.lifecycle_definition,
            self.canon_image,
            air=lifecycle_fact.air,
            scope_ref=lifecycle_fact.scope_ref,
            temporal_ref=lifecycle_fact.temporal_ref,
            resolution_ref=lifecycle_fact.resolution_ref,
            derivation_ref=lifecycle_fact.derivation_ref,
            evidence_refs=lifecycle_fact.provenance.source_refs,
            observed_at=self.observed_at,
            produced_at=self.checked_at,
            stale_after=self.stale_after,
            policy_generation=self.audience_policy_generation,
        )
        if lifecycle_fact != expected_lifecycle_fact:
            raise ValueError("lifecycle_fsm fact must exactly bind this frame's canon image")
        if lifecycle_fact.data.sha256 != self.position.lifecycle_fsm_data_sha256:
            raise ValueError("lifecycle_fsm fact differs from the position commitment")
        if {
            lifecycle_fact.air.operator_private,
            lifecycle_fact.air.yard_context,
            lifecycle_fact.air.hapax_substrate,
        } != {"allow"}:
            raise ValueError("lifecycle_fsm must remain visible to every canonical audience")
        for relation in self.relations:
            if {relation.source_fact_ref, relation.target_fact_ref} - fact_set:
                raise ValueError("context relations must reference frame facts")
            if set(relation.provenance_refs) - (
                observation_refs | fact_set | set(self.position.receipt_lineage)
            ):
                raise ValueError("context relation provenance must resolve to admitted evidence")
        for action in self.actions:
            if set(action.source_fact_refs) - fact_set:
                raise ValueError("context actions must reference frame facts")
            if action.position_ref != self.position.position_ref:
                raise ValueError("context actions must bind the exact frame position")
            lifecycle_guards: tuple[str, ...] = ()
            if action.action_class == "lifecycle_operation":
                assert action.lifecycle_operation is not None
                try:
                    admission = next(
                        item
                        for item in _lifecycle_stage(
                            self.lifecycle_definition, self.position.stage_token
                        ).operation_admissions
                        if item.operation == action.lifecycle_operation
                    )
                except StopIteration as exc:
                    raise ValueError(
                        "lifecycle operation is not admitted at the current stage"
                    ) from exc
                expected_admission_ref = lifecycle_operation_admission_ref(
                    self.lifecycle_definition,
                    self.position.stage_token,
                    action.lifecycle_operation,
                )
                if action.admission_ref != expected_admission_ref:
                    raise ValueError("context action differs from lifecycle operation admission")
                lifecycle_guards = admission.guards
            elif action.action_class == "lifecycle_transition":
                assert action.transition_to is not None
                assert action.transition_edge is not None
                try:
                    transition = next(
                        item
                        for item in getattr(
                            _lifecycle_stage(self.lifecycle_definition, self.position.stage_token),
                            action.transition_edge,
                        )
                        if item.to == action.transition_to
                    )
                except StopIteration as exc:
                    raise ValueError(
                        "lifecycle transition is not admitted at the current stage"
                    ) from exc
                expected_admission_ref = lifecycle_transition_admission_ref(
                    self.lifecycle_definition,
                    self.position.stage_token,
                    action.transition_to,
                    action.transition_edge,
                )
                if action.admission_ref != expected_admission_ref:
                    raise ValueError("context action differs from lifecycle transition admission")
                lifecycle_guards = transition.guards
            elif any(
                item.operation == action.operation
                for item in _lifecycle_stage(
                    self.lifecycle_definition, self.position.stage_token
                ).operation_admissions
            ):
                raise ValueError("lifecycle operation requires the lifecycle operation class")
            if lifecycle_guards:
                guard_by_name = {item.guard: item for item in action.guard_evidence}
                if tuple(guard_by_name) != lifecycle_guards:
                    raise ValueError(
                        "lifecycle action guard evidence must exactly cover its admission"
                    )
                allowed_guard_refs = (
                    fact_set | observation_refs | set(self.position.receipt_lineage)
                )
                if any(
                    set(item.evidence_refs) - allowed_guard_refs for item in action.guard_evidence
                ):
                    raise ValueError(
                        "lifecycle guard evidence must resolve to admitted frame evidence"
                    )
                if any(
                    ref in fact_set and ref not in action.source_fact_refs
                    for item in action.guard_evidence
                    for ref in item.evidence_refs
                ):
                    raise ValueError(
                        "lifecycle guard fact evidence must be declared as action source facts"
                    )
                for evidence in action.guard_evidence:
                    if evidence.disposition != "satisfied":
                        continue
                    if any(
                        (
                            ref in observation_by_ref
                            and observation_by_ref[ref].state.value_state != "present"
                        )
                        or (
                            ref in fact_by_id
                            and (
                                fact_by_id[ref].state.value_state != "present"
                                or fact_by_id[ref].freshness_state not in {"fresh", "aging"}
                            )
                        )
                        for ref in evidence.evidence_refs
                    ):
                        raise ValueError(
                            "satisfied lifecycle guards require present, usable local evidence"
                        )
                flags = {item.name: item for item in self.position.authorized_flags}
                for guard, evidence in guard_by_name.items():
                    if not guard.endswith("_authorized"):
                        continue
                    if guard not in flags:
                        if evidence.disposition == "satisfied":
                            raise ValueError(
                                "a missing position flag cannot satisfy an authority guard"
                            )
                        continue
                    flag = flags[guard]
                    expected_disposition = "satisfied" if flag.authorized else "unsatisfied"
                    if evidence.disposition != expected_disposition:
                        raise ValueError(
                            "lifecycle authority guard evidence differs from position flags"
                        )
                    if flag.source_ref not in evidence.evidence_refs:
                        raise ValueError(
                            "lifecycle authority guard evidence must cite its flag source"
                        )
                all_satisfied = all(
                    item.disposition == "satisfied" for item in action.guard_evidence
                )
                if (action.disposition == "legal") != all_satisfied:
                    raise ValueError(
                        "lifecycle action legality must equal exact guard satisfaction"
                    )
            source_facts = [fact for fact in self.facts if fact.fact_id in action.source_fact_refs]
            if action.disposition == "legal" and any(
                fact.state.value_state != "present" or fact.freshness_state == "stale"
                for fact in source_facts
            ):
                raise ValueError("legal actions require present, non-stale source facts")
        action_by_id = {action.action_id: action for action in self.actions}
        if any(set(item.legal_next) - set(action_by_id) for item in self.impingements):
            raise ValueError("context impingements must reference frame actions")
        for fact in self.facts:
            expected_relations = tuple(
                relation.relation_id
                for relation in self.relations
                if fact.fact_id in {relation.source_fact_ref, relation.target_fact_ref}
            )
            if fact.relation_refs != expected_relations:
                raise ValueError("fact relation_refs must match the frame relation graph")
            related_actions = tuple(
                action for action in self.actions if fact.fact_id in action.source_fact_refs
            )
            expected_legal = tuple(
                action.action_id for action in related_actions if action.disposition == "legal"
            )
            expected_prohibited = tuple(
                action.action_id for action in related_actions if action.disposition != "legal"
            )
            expected_receipts = tuple(
                sorted({action.expected_receipt_ref for action in related_actions})
            )
            if fact.legal_next != expected_legal or fact.prohibited_next != expected_prohibited:
                raise ValueError("fact action refs must match frame action dispositions")
            if fact.expected_receipt_refs != expected_receipts:
                raise ValueError("fact expected receipts must match frame actions")
            allowed_supersession_refs = fact_set | set(self.position.receipt_lineage)
            if set(fact.supersedes_refs) - allowed_supersession_refs:
                raise ValueError("fact supersedes refs must resolve in frame or receipt lineage")
            if fact.fact_id in fact.supersedes_refs:
                raise ValueError("a fact cannot supersede itself")
        for origin in self.facts:
            visited: set[str] = set()
            pending = [ref for ref in origin.supersedes_refs if ref in fact_by_id]
            while pending:
                ref = pending.pop()
                if ref == origin.fact_id:
                    raise ValueError("fact supersession must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(
                    parent for parent in fact_by_id[ref].supersedes_refs if parent in fact_by_id
                )
        for item in (*self.impingements, *self.orienting_signals, *self.portal_offers):
            if set(item.source_fact_refs) - fact_set:
                raise ValueError("context object must reference frame facts")
        for estimate in self.signal_estimates:
            if estimate.position_ref != self.position.position_ref:
                raise ValueError("signal estimates must bind the exact frame position")
            if estimate.scope_ref not in scope_refs:
                raise ValueError("signal estimate scope must resolve in the frame")
            if estimate.temporal_ref not in temporal_refs:
                raise ValueError("signal estimate temporal coordinate must resolve")
            if estimate.resolution_ref not in resolution_refs:
                raise ValueError("signal estimate resolution must resolve")
            if (
                resolution_by_ref[estimate.resolution_ref].scope_ref != estimate.scope_ref
                or resolution_by_ref[estimate.resolution_ref].temporal_ref != estimate.temporal_ref
            ):
                raise ValueError(
                    "signal estimate resolution differs from scope or temporal coordinate"
                )
            if set(estimate.source_fact_refs) - fact_set:
                raise ValueError("signal estimates must reference frame facts")
            if estimate.derivation_ref not in derivation_refs:
                raise ValueError("signal estimate derivation must resolve")
            if estimate.estimate_id not in derivation_by_ref[estimate.derivation_ref].output_refs:
                raise ValueError("signal estimate is not an output of its derivation")
            if (
                estimate.state.value_state == "present"
                and derivation_by_ref[estimate.derivation_ref].state.value_state != "present"
            ):
                raise ValueError("present signal estimates require a present derivation")
            if set(estimate.supersedes_refs) - (estimate_refs | set(self.position.receipt_lineage)):
                raise ValueError("signal estimate supersession must resolve in frame or receipts")
            if estimate.estimate_ref in estimate.supersedes_refs:
                raise ValueError("a signal estimate cannot supersede itself")
        estimate_by_ref = {item.estimate_ref: item for item in self.signal_estimates}
        for origin in self.signal_estimates:
            visited: set[str] = set()
            pending = [ref for ref in origin.supersedes_refs if ref in estimate_by_ref]
            while pending:
                ref = pending.pop()
                if ref == origin.estimate_ref:
                    raise ValueError("signal estimate supersession must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(
                    parent
                    for parent in estimate_by_ref[ref].supersedes_refs
                    if parent in estimate_by_ref
                )
        relation_refs = {item.relation_id for item in self.relations}
        allowed_constraint_refs = (
            fact_set
            | {item.action_id for item in self.actions}
            | {item.impingement_id for item in self.impingements}
            | set(self.position.receipt_lineage)
        )
        for lens in self.signal_lenses:
            if set(lens.scope_selector_refs) - scope_refs:
                raise ValueError("signal lens scope selectors must resolve")
            if set(lens.resolution_selector_refs) - resolution_refs:
                raise ValueError("signal lens resolution selectors must resolve")
            if set(lens.constraint_mask_refs) - allowed_constraint_refs:
                raise ValueError("signal lens constraint mask must resolve before utility")
            if lens.constraint_mask_receipt_ref not in self.position.receipt_lineage:
                raise ValueError(
                    "signal lens constraint mask receipt must resolve in position lineage"
                )
        for constellation in self.signal_constellations:
            if constellation.lens_ref not in lens_refs:
                raise ValueError("signal constellation lens must resolve")
            if constellation.scope_ref not in scope_refs:
                raise ValueError("signal constellation scope must resolve")
            if constellation.resolution_ref not in resolution_refs:
                raise ValueError("signal constellation resolution must resolve")
            if constellation.target_ref not in fact_set:
                raise ValueError("signal constellation target must resolve to a frame fact")
            constellation_lens = next(
                item for item in self.signal_lenses if item.lens_ref == constellation.lens_ref
            )
            constellation_resolution = resolution_by_ref[constellation.resolution_ref]
            if constellation_resolution.scope_ref != constellation.scope_ref:
                raise ValueError("signal constellation resolution differs from its scope")
            if constellation.scope_ref not in constellation_lens.scope_selector_refs:
                raise ValueError("signal constellation scope is outside its lens")
            if constellation.resolution_ref not in constellation_lens.resolution_selector_refs:
                raise ValueError("signal constellation resolution is outside its lens")
            if set(constellation.member_estimate_refs) - estimate_refs:
                raise ValueError("signal constellation members must resolve")
            if any(
                estimate_by_ref[ref].scope_ref not in constellation_lens.scope_selector_refs
                or estimate_by_ref[ref].resolution_ref
                not in constellation_lens.resolution_selector_refs
                for ref in constellation.member_estimate_refs
            ):
                raise ValueError("signal constellation members are outside its lens")
            if constellation.state.value_state == "present" and any(
                estimate_by_ref[ref].state.value_state != "present"
                for ref in constellation.member_estimate_refs
            ):
                raise ValueError("present signal constellations require present member estimates")
            if set(constellation.relation_refs) - relation_refs:
                raise ValueError("signal constellation relations must resolve")
            if set(constellation.uncovered_source_refs) - admission_refs:
                raise ValueError(
                    "signal constellation uncovered sources must resolve to admissions"
                )
        constellation_by_ref = {item.constellation_ref: item for item in self.signal_constellations}
        axis_evidence_universe = (
            fact_set | observation_refs | estimate_refs | set(self.position.receipt_lineage)
        )
        for signal in self.orienting_signals:
            if signal.position_ref != self.position.position_ref:
                raise ValueError("orienting signals must bind the exact frame position")
            if set(signal.estimate_refs) - estimate_refs:
                raise ValueError("orienting signal estimates must resolve")
            if signal.lens_ref not in lens_refs:
                raise ValueError("orienting signal lens must resolve")
            if signal.constellation_ref not in constellation_refs:
                raise ValueError("orienting signal constellation must resolve")
            constellation = constellation_by_ref[signal.constellation_ref]
            if signal.lens_ref != constellation.lens_ref:
                raise ValueError("orienting signal lens differs from its constellation")
            if set(signal.estimate_refs) - set(constellation.member_estimate_refs):
                raise ValueError("orienting signal estimates must be constellation members")
            estimate_fact_refs = {
                fact_ref
                for estimate_ref in signal.estimate_refs
                for fact_ref in estimate_by_ref[estimate_ref].source_fact_refs
            }
            if set(signal.source_fact_refs) - estimate_fact_refs:
                raise ValueError("orienting signal facts must support its named estimates")
            if set(_orientation_value_evidence_refs(signal.value_vector)) - (
                axis_evidence_universe
            ):
                raise ValueError("signal value evidence must resolve to admitted frame evidence")
            if signal.state.value_state == "present" and (
                constellation.state.value_state != "present"
                or any(
                    estimate_by_ref[ref].state.value_state != "present"
                    for ref in signal.estimate_refs
                )
                or any(
                    fact_by_id[ref].state.value_state != "present"
                    for ref in signal.source_fact_refs
                )
            ):
                raise ValueError("present orienting signals require present semantic dependencies")
        action_refs = {item.action_id for item in self.actions}
        learning_witness_states = {
            **{item.observation_ref: item.state for item in self.observations},
            **{item.fact_id: item.state for item in self.facts},
            **{item.estimate_ref: item.state for item in self.signal_estimates},
            **{item.action_id: item.state for item in self.actions},
        }
        for receipt in self.signal_learning_receipts:
            if receipt.position_ref != self.position.position_ref:
                raise ValueError("learning receipts must bind the exact frame position")
            if receipt.estimate_ref not in estimate_refs:
                raise ValueError("learning receipt estimate must resolve")
            if receipt.constellation_ref not in constellation_refs:
                raise ValueError("learning receipt constellation must resolve")
            if receipt.action_ref not in action_refs:
                raise ValueError("learning receipt action must resolve")
            allowed_learning_witnesses = (
                observation_refs | fact_set | estimate_refs | action_refs
            ) | set(self.position.receipt_lineage)
            if set(receipt.witness_refs) - allowed_learning_witnesses:
                raise ValueError(
                    "learning witnesses must resolve locally or in the position receipt lineage"
                )
            constellation = constellation_by_ref[receipt.constellation_ref]
            if receipt.estimate_ref not in constellation.member_estimate_refs:
                raise ValueError("learning receipt estimate must belong to its constellation")
            if receipt.state.value_state == "present" and (
                estimate_by_ref[receipt.estimate_ref].state.value_state != "present"
                or constellation.state.value_state != "present"
                or action_by_id[receipt.action_ref].state.value_state != "present"
                or any(
                    learning_witness_states[ref].value_state != "present"
                    for ref in receipt.witness_refs
                    if ref in learning_witness_states
                )
            ):
                raise ValueError("present learning receipts require present semantic dependencies")
            allowed_learning_lineage = {
                item.learning_ref for item in self.signal_learning_receipts
            } | set(self.position.receipt_lineage)
            if set((*receipt.correction_refs, *receipt.supersedes_refs)) - (
                allowed_learning_lineage
            ):
                raise ValueError(
                    "learning correction and supersession must resolve in frame or receipts"
                )
            if receipt.learning_ref in {
                *receipt.correction_refs,
                *receipt.supersedes_refs,
            }:
                raise ValueError("a learning receipt cannot correct or supersede itself")
        learning_by_ref = {item.learning_ref: item for item in self.signal_learning_receipts}
        for origin in self.signal_learning_receipts:
            visited: set[str] = set()
            pending = [
                ref
                for ref in (*origin.correction_refs, *origin.supersedes_refs)
                if ref in learning_by_ref
            ]
            while pending:
                ref = pending.pop()
                if ref == origin.learning_ref:
                    raise ValueError("learning receipt lineage must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                parent = learning_by_ref[ref]
                pending.extend(
                    ancestor
                    for ancestor in (*parent.correction_refs, *parent.supersedes_refs)
                    if ancestor in learning_by_ref
                )
        signal_portals = {
            signal.portal_ref for signal in self.orienting_signals if signal.portal_ref is not None
        }
        portal_refs = {portal.portal_ref for portal in self.portal_offers}
        if signal_portals - portal_refs:
            raise ValueError("orienting signals must reference declared portal offers")
        event_refs = {event.event_ref for event in self.events}
        event_ancestry = event_refs | set(self.position.receipt_lineage)
        event_source_universe = (
            {self.position.position_ref, f"demand-shape@sha256:{self.demand_shape.fingerprint}"}
            | scope_refs
            | temporal_refs
            | resolution_refs
            | admission_refs
            | observation_refs
            | derivation_refs
            | fact_set
            | relation_refs
            | action_refs
            | {item.impingement_id for item in self.impingements}
            | estimate_refs
            | lens_refs
            | constellation_refs
            | {item.signal_ref for item in self.orienting_signals}
            | {item.portal_ref for item in self.portal_offers}
            | {item.learning_ref for item in self.signal_learning_receipts}
            | set(self.position.receipt_lineage)
        )
        event_source_states = {
            f"demand-shape@sha256:{self.demand_shape.fingerprint}": self.demand_shape.state,
            **{item.temporal_ref: item.completeness for item in self.temporal_coordinates},
            **{item.admission_ref: item.availability for item in self.source_admissions},
            **{item.observation_ref: item.state for item in self.observations},
            **{item.derivation_ref: item.state for item in self.derivations},
            **{item.fact_id: item.state for item in self.facts},
            **{item.relation_id: item.state for item in self.relations},
            **{item.action_id: item.state for item in self.actions},
            **{item.impingement_id: item.state for item in self.impingements},
            **{item.estimate_ref: item.state for item in self.signal_estimates},
            **{item.constellation_ref: item.state for item in self.signal_constellations},
            **{item.signal_ref: item.state for item in self.orienting_signals},
            **{item.portal_ref: item.state for item in self.portal_offers},
            **{item.learning_ref: item.state for item in self.signal_learning_receipts},
        }
        derivation_authority_ranks = {
            item.derivation_ref: _derivation_input_authority_rank(
                item, observation_by_ref, fact_by_id
            )
            for item in self.derivations
        }
        event_source_authority_ranks = {
            **{
                item.admission_ref: _AUTHORITY_CEILING_RANK[item.authority_ceiling]
                for item in self.source_admissions
            },
            **{
                item.observation_ref: _AUTHORITY_CEILING_RANK[item.authority_ceiling]
                for item in self.observations
            },
            **derivation_authority_ranks,
            **{
                item.fact_id: _PROVENANCE_AUTHORITY_RANK[item.provenance.authority_level]
                for item in self.facts
            },
        }
        event_by_ref = {event.event_ref: event for event in self.events}
        for event in self.events:
            if set(event.source_refs) - event_source_universe:
                raise ValueError("event sources must resolve to typed frame evidence or receipts")
            if event.state.value_state == "present" and any(
                event_source_states[ref].value_state != "present"
                for ref in event.source_refs
                if ref in event_source_states
            ):
                raise ValueError("present events require present source carriers")
            if event.state.value_state == "present" and any(
                event_by_ref[ref].state.value_state != "present"
                for ref in event.caused_by
                if ref in event_by_ref
            ):
                raise ValueError("present events require present causal events")
            event_authority_rank = _AUTHORITY_CEILING_RANK[event.authority_ceiling]
            if any(
                event_authority_rank > event_source_authority_ranks.get(ref, 0)
                for ref in event.source_refs
            ):
                raise ValueError("event authority exceeds its typed source evidence")
            if set((*event.caused_by, *event.supersedes_refs)) - event_ancestry:
                raise ValueError("event ancestry must resolve in the frame or receipt lineage")
            if event.session_ref != self.session_ref or event.task_ref != self.task_ref:
                raise ValueError("event session/task identity differs from its frame")
            if event.position_ref != self.position.position_ref:
                raise ValueError("event position differs from its frame")
            if event.scope_ref not in scope_refs:
                raise ValueError("event scope must resolve in its frame")
            if event.temporal_ref not in temporal_refs:
                raise ValueError("event temporal coordinate must resolve in its frame")
            if event.resolution_ref not in resolution_refs:
                raise ValueError("event resolution must resolve in its frame")
            event_resolution = next(
                item
                for item in self.resolution_coordinates
                if item.resolution_ref == event.resolution_ref
            )
            if (
                event_resolution.scope_ref != event.scope_ref
                or event_resolution.temporal_ref != event.temporal_ref
            ):
                raise ValueError("event resolution differs from its scope or temporal coordinate")
            temporal = next(
                item
                for item in self.temporal_coordinates
                if item.temporal_ref == event.temporal_ref
            )
            if temporal.event_time_start != event.occurred_at:
                raise ValueError("event occurrence differs from its temporal coordinate")
            if temporal.valid_until != event.expires_at:
                raise ValueError("event expiry differs from its temporal validity")
            for ancestor_ref in event.caused_by:
                if ancestor_ref not in event_by_ref:
                    continue
                ancestor = event_by_ref[ancestor_ref]
                if event_authority_rank > _AUTHORITY_CEILING_RANK[ancestor.authority_ceiling]:
                    raise ValueError("event authority exceeds its causal ancestry")
                ancestor_temporal = temporal_by_ref[ancestor.temporal_ref]
                if ancestor.occurred_at > event.occurred_at:
                    raise ValueError("causal events cannot occur after their children")
                if ancestor_temporal.processing_time > temporal.processing_time:
                    raise ValueError("causal events cannot be processed after their children")
                if ancestor.generation > event.generation:
                    raise ValueError("causal event generations must be nondecreasing")
                if ancestor.derivation_depth >= event.derivation_depth:
                    raise ValueError("causal event derivation depth must strictly increase")
            for ancestor_ref in event.supersedes_refs:
                if ancestor_ref not in event_by_ref:
                    continue
                ancestor = event_by_ref[ancestor_ref]
                if event_authority_rank > _AUTHORITY_CEILING_RANK[ancestor.authority_ceiling]:
                    raise ValueError("event authority exceeds its superseded ancestry")
                ancestor_temporal = temporal_by_ref[ancestor.temporal_ref]
                if (
                    ancestor.occurred_at > event.occurred_at
                    or ancestor_temporal.processing_time > temporal.processing_time
                    or ancestor.generation > event.generation
                ):
                    raise ValueError("superseded events must not follow their replacements")
        for origin in self.events:
            visited: set[str] = set()
            pending = [
                ref for ref in (*origin.caused_by, *origin.supersedes_refs) if ref in event_by_ref
            ]
            while pending:
                ref = pending.pop()
                if ref == origin.event_ref:
                    raise ValueError("event causation and supersession must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                parent = event_by_ref[ref]
                pending.extend(
                    ancestor_ref
                    for ancestor_ref in (*parent.caused_by, *parent.supersedes_refs)
                    if ancestor_ref in event_by_ref
                )
        visible_focus_refs = fact_set | {fact.subject_ref for fact in self.facts}
        for facet in self.orientation_facets:
            if facet.focus_ref not in visible_focus_refs:
                raise ValueError("orientation focus must resolve in frame facts")
            if facet.position_ref != self.position.position_ref:
                raise ValueError("orientation position differs from its frame")
            if set(facet.why_now_refs) - (fact_set | set(self.position.receipt_lineage)):
                raise ValueError("orientation why-now refs must resolve in its frame")
            if set((*facet.can, *facet.cannot, facet.counterfactual.action_id)) - set(action_by_id):
                raise ValueError("orientation actions must resolve in its frame")
            if any(action_by_id[action_id].disposition != "legal" for action_id in facet.can):
                raise ValueError("orientation can must reference legal actions")
            if any(action_by_id[action_id].disposition == "legal" for action_id in facet.cannot):
                raise ValueError("orientation cannot must reference non-legal actions")
        for facet in self.lifecycle_possibilities:
            if set(facet.source_fact_refs) - fact_set:
                raise ValueError("lifecycle possibility refs must resolve in its frame")
            if set(facet.lawful_next) - {
                action.action_id for action in self.actions if action.disposition == "legal"
            }:
                raise ValueError("lifecycle possibility lawful next must remain a legal action")
        air_keys = tuple((binding.object_kind, binding.object_ref) for binding in self.air_bindings)
        if air_keys != tuple(sorted(set(air_keys))):
            raise ValueError("context AIR bindings must be sorted and unique")
        expected_air_keys = {
            ("position", self.position.position_ref),
            ("demand_shape", f"demand-shape@sha256:{self.demand_shape.fingerprint}"),
            *(("scope", item.scope_ref) for item in self.scopes),
            *(("temporal", item.temporal_ref) for item in self.temporal_coordinates),
            *(("resolution", item.resolution_ref) for item in self.resolution_coordinates),
            *(("source_admission", item.admission_ref) for item in self.source_admissions),
            *(("observation", item.observation_ref) for item in self.observations),
            *(("derivation", item.derivation_ref) for item in self.derivations),
            *(("relation", item.relation_id) for item in self.relations),
            *(("action", item.action_id) for item in self.actions),
            *(("impingement", item.impingement_id) for item in self.impingements),
            *(("estimate", item.estimate_ref) for item in self.signal_estimates),
            *(("lens", item.lens_ref) for item in self.signal_lenses),
            *(("constellation", item.constellation_ref) for item in self.signal_constellations),
            *(("signal", item.signal_id) for item in self.orienting_signals),
            *(("portal", item.portal_ref) for item in self.portal_offers),
            *(("learning_receipt", item.learning_ref) for item in self.signal_learning_receipts),
            *(("event", item.event_id) for item in self.events),
            *(("orientation", item.facet_id) for item in self.orientation_facets),
            *(("lifecycle_possibility", item.facet_id) for item in self.lifecycle_possibilities),
        }
        if set(air_keys) != expected_air_keys:
            raise ValueError("context AIR bindings must cover every projected object exactly")
        air_by_key = {
            (binding.object_kind, binding.object_ref): binding.air for binding in self.air_bindings
        }
        for key in (
            ("position", self.position.position_ref),
            ("demand_shape", f"demand-shape@sha256:{self.demand_shape.fingerprint}"),
        ):
            policy = air_by_key[key]
            if {
                policy.operator_private,
                policy.yard_context,
                policy.hapax_substrate,
            } != {"allow"}:
                raise ValueError(
                    "position and demand shape must remain visible to canonical audiences"
                )
        fact_by_id = {fact.fact_id: fact for fact in self.facts}
        committed_objects = (
            *(
                ("impingement", item.impingement_id, item.source_fact_refs)
                for item in self.impingements
            ),
            *(("portal", item.portal_ref, item.source_fact_refs) for item in self.portal_offers),
        )
        for kind, object_ref, source_refs in committed_objects:
            policy = air_by_key[(kind, object_ref)]
            for audience in ("operator_private", "yard_context", "hapax_substrate"):
                if getattr(policy, audience) != "allow" or any(
                    getattr(fact_by_id[fact_ref].air, audience) != "allow"
                    for fact_ref in source_refs
                ):
                    raise ValueError(
                        "position-committed impingements and portals must be visible "
                        "to canonical audiences"
                    )
        if self.task_ref != self.position.task_ref:
            raise ValueError("frame task_ref differs from position")
        if self.position.stage_token != self.canon_image.stage_token:
            raise ValueError("frame position differs from canon image stage")
        if self.position.lifecycle_definition != self.lifecycle_definition:
            raise ValueError("frame position lifecycle definition differs from frame definition")
        if self.position.legal_successors != _lifecycle_legal_successors(
            self.lifecycle_definition, self.position.stage_token
        ):
            raise ValueError("frame legal successors differ from lifecycle definition")
        if self.position.canon_id != self.canon_image.canon_id:
            raise ValueError("frame position differs from canon identity")
        if self.position.canon_image_hash != self.canon_image.image_hash:
            raise ValueError("frame position differs from canon image hash")
        if self.position.canon_version != self.canon_image.canon_version:
            raise ValueError("frame position differs from canon version")
        if self.position.canon_level != self.canon_image.level:
            raise ValueError("frame position differs from canon level")
        if self.canon_image.lifecycle_definition_hash != self.lifecycle_definition.definition_hash:
            raise ValueError("canon image differs from lifecycle definition")
        if self.position.lifecycle_definition_ref != self.lifecycle_definition.definition_ref:
            raise ValueError("frame position differs from lifecycle definition")
        if self.position.lifecycle_definition_hash != self.lifecycle_definition.definition_hash:
            raise ValueError("frame position differs from lifecycle definition hash")
        if self.position.demand_shape_fingerprint != self.demand_shape.fingerprint:
            raise ValueError("frame position differs from demand shape")
        if self.demand_shape.descriptor is not None:
            if self.demand_shape.descriptor.session_ref != self.session_ref:
                raise ValueError("demand descriptor session differs from frame session")
            descriptor = self.demand_shape.descriptor
            expected_canon = build_canonical_json_object(
                {
                    "bundle_hash": self.position.canon_bundle_hash,
                    "bundle_ref": self.position.canon_bundle_ref,
                    "canon_id": self.position.canon_id,
                    "image_hash": self.position.canon_image_hash,
                    "level": self.position.canon_level.value,
                    "version": self.position.canon_version,
                }
            )
            if descriptor.canon != expected_canon:
                raise ValueError("demand descriptor canon differs from frame position")
            expected_position_basis = build_canonical_json_object(
                {
                    "legal_successors": self.position.legal_successors,
                    "lifecycle_definition_hash": self.position.lifecycle_definition_hash,
                    "lifecycle_definition_ref": self.position.lifecycle_definition_ref,
                    "stage_token": self.position.stage_token,
                }
            )
            if descriptor.position_basis != expected_position_basis:
                raise ValueError("demand descriptor position basis differs from frame position")
        expected_impingement_digest = _domain_hash(
            "hapax.context-impingements.v1", self.impingements
        )
        if self.position.impingement_digest != expected_impingement_digest:
            raise ValueError("position impingement digest differs from frame impingements")
        expected_portal_digest = _domain_hash("hapax.portal-set.v1", self.portal_offers)
        if self.position.portal_set_digest != expected_portal_digest:
            raise ValueError("position portal digest differs from frame portal set")
        body = self.model_dump(mode="json", by_alias=True, exclude={"frame_ref", "frame_hash"})
        expected_hash = _domain_hash("hapax.context-frame.v1", body)
        if self.frame_hash != expected_hash:
            raise ValueError("frame_hash does not bind the context frame")
        if self.frame_ref != f"context-frame@sha256:{expected_hash}":
            raise ValueError("frame_ref does not bind frame_hash")
        return self


class CounterfactualFacet(FrozenModel):
    action_id: str
    predicted_state_delta: CanonicalJsonObject
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator("action_id")
    @classmethod
    def validate_action_id(cls, value: str) -> str:
        return _validate_wire_string(value)


class BoundaryOrientationFacet(FrozenModel):
    facet_id: str
    facet_ref: str
    facet_hash: str = Field(pattern=_HASH_PATTERN)
    focus_ref: str
    position_ref: str
    boundary_kind: Literal[
        "evidence_unknown",
        "authority_prohibition",
        "capability_unavailable",
        "consent_missing",
        "execution_lease_missing",
        "predicate_conditional",
        "lifecycle_deferred",
        "execution_failed",
        "disclosure_dark",
    ]
    why_now_refs: tuple[str, ...] = Field(min_length=1)
    protects: tuple[str, ...] = Field(min_length=1)
    can: tuple[str, ...]
    cannot: tuple[str, ...]
    until: tuple[str, ...] = Field(min_length=1)
    iff: tuple[str, ...] = Field(min_length=1)
    change_authority: Literal[
        "operator_stipulation", "independent_decision", "evidence", "immutable_current_law"
    ]
    counterfactual: CounterfactualFacet
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator("facet_id", "facet_ref", "focus_ref", "position_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("why_now_refs", "protects", "can", "cannot", "until", "iff")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value,
            info.field_name,
            allow_empty=info.field_name in {"can", "cannot"},
        )

    @model_validator(mode="after")
    def validate_possibilities(self) -> Self:
        if set(self.can) & set(self.cannot):
            raise ValueError("orientation can and cannot sets must be disjoint")
        body = self.model_dump(mode="json", by_alias=True, exclude={"facet_ref", "facet_hash"})
        expected_hash = _domain_hash("hapax.boundary-orientation-facet.v1", body)
        if self.facet_hash != expected_hash:
            raise ValueError("orientation facet_hash does not bind the facet")
        if self.facet_ref != f"boundary-orientation@sha256:{expected_hash}":
            raise ValueError("orientation facet_ref does not bind facet_hash")
        return self


class LifecyclePossibilityFacet(FrozenModel):
    facet_id: str
    facet_ref: str
    facet_hash: str = Field(pattern=_HASH_PATTERN)
    candidate_ref: str
    source_fact_refs: tuple[str, ...] = Field(min_length=1)
    why_now: str
    does_not_prove: tuple[str, ...] = Field(min_length=1)
    uncertainty: str
    alternative_dispositions: tuple[
        Literal[
            "one_shot_task",
            "checklist_or_workflow",
            "lifecycle_candidate",
            "insufficient_evidence",
        ],
        ...,
    ] = Field(min_length=1)
    unknown_fields: tuple[str, ...]
    candidate_plant: CanonicalJsonObject
    estimated_cost: CanonicalJsonObject
    plant_gap: ContextState
    harness_gap: ContextState
    measurement_gap: ContextState
    lawful_next: tuple[str, ...] = Field(min_length=1)
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator("facet_id", "facet_ref", "candidate_ref", "why_now", "uncertainty")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("source_fact_refs", "does_not_prove", "unknown_fields", "lawful_next")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value, info.field_name, allow_empty=info.field_name == "unknown_fields"
        )

    @field_validator("alternative_dispositions")
    @classmethod
    def validate_dispositions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("alternative_dispositions must be sorted and unique")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        body = self.model_dump(mode="json", by_alias=True, exclude={"facet_ref", "facet_hash"})
        expected_hash = _domain_hash("hapax.lifecycle-possibility-facet.v1", body)
        if self.facet_hash != expected_hash:
            raise ValueError("lifecycle possibility facet_hash does not bind the facet")
        if self.facet_ref != f"lifecycle-possibility@sha256:{expected_hash}":
            raise ValueError("lifecycle possibility facet_ref does not bind facet_hash")
        return self


def _canon_error(reason: str, repair: str, detail: str = "") -> CanonError:
    return CanonError(reason, detail=detail, repair_action=repair)


def _validate_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not -_JSON_SAFE_INTEGER_MAX <= value <= _JSON_SAFE_INTEGER_MAX:
            raise _canon_error(
                "canon_json_integer_out_of_range",
                "use an interoperable JSON integer between -(2^53-1) and 2^53-1",
                path,
            )
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _canon_error(
                "canon_json_nonfinite_number", "replace NaN or infinity with a finite value", path
            )
        raise _canon_error(
            "canon_json_float_unsupported",
            "encode decimal quantities as explicitly typed canonical strings",
            path,
        )
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise _canon_error(
                "canon_json_unicode_invalid", "replace unpaired Unicode surrogates", path
            ) from exc
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise _canon_error(
                    "canon_json_key_invalid", "use string mapping keys", f"{path}.{key!r}"
                )
            _validate_json_value(child, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        for index, child in enumerate(value):
            _validate_json_value(child, f"{path}[{index}]")
        return
    raise _canon_error(
        "canon_json_type_invalid",
        "use only JSON null, booleans, numbers, strings, arrays, and objects",
        f"{path}:{type(value).__name__}",
    )


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize_json_value(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, enum.Enum):
        return _normalize_json_value(value.value)
    if isinstance(value, Mapping):
        return {key: _normalize_json_value(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_normalize_json_value(child) for child in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return the strict, path-independent canonical semantic JSON encoding."""

    value = _normalize_json_value(value)
    _validate_json_value(value)
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise _canon_error(
            "canon_json_serialization_failed", "repair the value to the JSON data model"
        ) from exc
    return rendered.encode("ascii")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _render_canon_stratum(atoms: Sequence[_LifecycleCanonAtomCarrier]) -> str:
    return toon.encode([{"id": atom.id, "content": atom.content} for atom in atoms])


def reference_token_count(text: str) -> int:
    """Count the locked ASCII lexemes used by canon image commitments."""

    if not text or not text.isascii():
        raise _canon_error(
            "canon_reference_tokenizer_input_invalid",
            "render nonempty ASCII canon content before reference tokenization",
        )
    return len(_ASCII_TOKEN_RE.findall(text))


def _domain_hash(domain: str, value: Any) -> str:
    """Hash one canonical semantic body with an explicit cross-type domain."""

    return _sha256(domain.encode("ascii") + b"\x00" + canonical_json_bytes(value))


def _validate_wire_string(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("wire strings must be nonblank without edge whitespace")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("wire strings must be valid UTF-8") from exc
    return value


def _lifecycle_stage(definition: LifecycleDefinition, stage_token: str) -> LifecycleStageDefinition:
    try:
        return next(stage for stage in definition.stages if stage.token == stage_token)
    except StopIteration as exc:
        raise ValueError(f"unknown lifecycle stage: {stage_token}") from exc


def _lifecycle_legal_successors(
    definition: LifecycleDefinition, stage_token: str
) -> tuple[str, ...]:
    stage = _lifecycle_stage(definition, stage_token)
    return tuple(sorted({edge.to for edge in (*stage.next, *stage.fall)}))


def lifecycle_operation_admission_ref(
    definition: LifecycleDefinition, stage_token: str, operation: str
) -> str:
    stage = _lifecycle_stage(definition, stage_token)
    return _stage_operation_admission_ref(stage, operation)


def _stage_operation_admission_ref(stage: LifecycleStageDefinition, operation: str) -> str:
    try:
        admission = next(item for item in stage.operation_admissions if item.operation == operation)
    except StopIteration as exc:
        raise ValueError("lifecycle operation is not admitted at the current stage") from exc
    digest = _domain_hash(
        "hapax.lifecycle-operation-admission.v1",
        {"stage_token": stage.token, "admission": admission},
    )
    return f"lifecycle-operation-admission@sha256:{digest}"


def lifecycle_transition_admission_ref(
    definition: LifecycleDefinition,
    stage_token: str,
    transition_to: str,
    transition_edge: Literal["next", "fall"],
) -> str:
    stage = _lifecycle_stage(definition, stage_token)
    return _stage_transition_admission_ref(stage, transition_to, transition_edge)


def _stage_transition_admission_ref(
    stage: LifecycleStageDefinition,
    transition_to: str,
    transition_edge: Literal["next", "fall"],
) -> str:
    try:
        transition = next(
            item for item in getattr(stage, transition_edge) if item.to == transition_to
        )
    except StopIteration as exc:
        raise ValueError("lifecycle transition is not admitted at the current stage") from exc
    digest = _domain_hash(
        "hapax.lifecycle-transition-admission.v1",
        {
            "stage_token": stage.token,
            "transition_edge": transition_edge,
            "transition": transition,
        },
    )
    return f"lifecycle-transition-admission@sha256:{digest}"


def build_canonical_json_object(value: Mapping[str, Any]) -> CanonicalJsonObject:
    """Freeze one JSON object as canonical immutable text plus its byte digest."""

    payload = canonical_json_bytes(value)
    return CanonicalJsonObject(
        canonical_json=payload.decode("ascii"),
        sha256=_sha256(payload),
    )


def _lifecycle_fsm_context_payload(
    lifecycle_definition: LifecycleDefinition, image: LifecycleCanonImageCarrier
) -> dict[str, Any]:
    if image.lifecycle_definition_hash != lifecycle_definition.definition_hash:
        raise ValueError("lifecycle_fsm image differs from its lifecycle definition")
    return {
        "schema": "hapax.lifecycle-fsm-context.v1",
        "lifecycle": {
            "definition_ref": lifecycle_definition.definition_ref,
            "definition_hash": lifecycle_definition.definition_hash,
            "lifecycle_ref": lifecycle_definition.lifecycle_ref,
            "profile_ref": lifecycle_definition.profile_ref,
            "plant_type_ref": lifecycle_definition.plant_type_ref,
            "unit_type_ref": lifecycle_definition.unit_type_ref,
        },
        "canon": {
            "id": image.canon_id,
            "hash": image.canon_hash,
            "image_hash": image.image_hash,
            "version": image.canon_version,
        },
        "stage": {
            "token": image.stage_token,
            "level": image.level.value,
            "projection_scope": image.projection_scope,
        },
        "kernel": image.kernel.model_dump(mode="json"),
        "representation": {
            "generator_version": image.generator_version,
            "projection_algorithm": image.projection_algorithm,
            "encoder_id": image.encoder_id,
            "reference_tokenizer_id": image.reference_tokenizer_id,
            "reference_token_count": image.reference_token_count,
        },
        "what": image.rendered_strata.what,
        "how": image.rendered_strata.how,
        "must": image.rendered_strata.must,
    }


def build_lifecycle_fsm_fact(
    lifecycle_definition: LifecycleDefinition,
    image: LifecycleCanonImageCarrier,
    *,
    air: ContextAirPolicy,
    scope_ref: str,
    temporal_ref: str,
    resolution_ref: str,
    derivation_ref: str,
    evidence_refs: Sequence[str],
    observed_at: str,
    produced_at: str,
    stale_after: str,
    policy_generation: str,
) -> ContextFact:
    """Build the sole exact, non-authorizing lifecycle context carrier for a frame."""

    if {air.operator_private, air.yard_context, air.hapax_substrate} != {"allow"}:
        raise ValueError("lifecycle_fsm AIR must allow every canonical audience")
    source_refs = tuple(sorted(set(evidence_refs)))
    if not source_refs:
        raise ValueError("lifecycle_fsm requires admitted evidence refs")
    return ContextFact(
        fact_id=f"fact:lifecycle-fsm:{image.image_hash}",
        fact_type="lifecycle_fsm",
        subject_ref=lifecycle_definition.lifecycle_ref,
        scope_ref=scope_ref,
        temporal_ref=temporal_ref,
        resolution_ref=resolution_ref,
        derivation_ref=derivation_ref,
        data=build_canonical_json_object(
            _lifecycle_fsm_context_payload(lifecycle_definition, image)
        ),
        unit=None,
        meaning=_LIFECYCLE_FSM_MEANING,
        implications=_LIFECYCLE_FSM_IMPLICATIONS,
        proves=_LIFECYCLE_FSM_PROVES,
        does_not_prove=_LIFECYCLE_FSM_DOES_NOT_PROVE,
        blind_spots=_LIFECYCLE_FSM_BLIND_SPOTS,
        provenance=ContextProvenance(
            kind="constitutional",
            source_refs=source_refs,
            producer_ref=GENERATOR_VERSION,
            derivation="extracted",
            authority_level="authoritative",
            generation=f"canon-version:{image.canon_version}",
            policy_generation=policy_generation,
            observed_at=observed_at,
            produced_at=produced_at,
            stale_after=stale_after,
        ),
        freshness_state="fresh",
        confidence=ContextConfidence(
            word="high",
            method="deterministic",
            evidence_refs=source_refs,
            calibration_ref=None,
            calibration_metric=None,
            validity_domain_refs=(),
            distribution_state="not_applicable",
            abstained=False,
        ),
        air=air,
        state=ContextState(value_state="present", reason_codes=()),
        relation_refs=(),
        legal_next=(),
        prohibited_next=(),
        expected_receipt_refs=(),
        supersedes_refs=(),
        no_effect=True,
        may_authorize=False,
    )


def build_boundary_orientation_facet(
    *,
    facet_id: str,
    focus_ref: str,
    position_ref: str,
    boundary_kind: str,
    why_now_refs: Sequence[str],
    protects: Sequence[str],
    can: Sequence[str],
    cannot: Sequence[str],
    until: Sequence[str],
    iff: Sequence[str],
    change_authority: str,
    counterfactual: CounterfactualFacet,
) -> BoundaryOrientationFacet:
    """Build one content-addressed orientation facet for later audience selection."""

    body = {
        "facet_id": facet_id,
        "focus_ref": focus_ref,
        "position_ref": position_ref,
        "boundary_kind": boundary_kind,
        "why_now_refs": tuple(sorted(set(why_now_refs))),
        "protects": tuple(sorted(set(protects))),
        "can": tuple(sorted(set(can))),
        "cannot": tuple(sorted(set(cannot))),
        "until": tuple(sorted(set(until))),
        "iff": tuple(sorted(set(iff))),
        "change_authority": change_authority,
        "counterfactual": counterfactual,
        "no_effect": True,
        "may_authorize": False,
    }
    facet_hash = _domain_hash("hapax.boundary-orientation-facet.v1", body)
    return BoundaryOrientationFacet(
        **body,
        facet_ref=f"boundary-orientation@sha256:{facet_hash}",
        facet_hash=facet_hash,
    )


def build_lifecycle_possibility_facet(
    *,
    facet_id: str,
    candidate_ref: str,
    source_fact_refs: Sequence[str],
    why_now: str,
    does_not_prove: Sequence[str],
    uncertainty: str,
    alternative_dispositions: Sequence[str],
    unknown_fields: Sequence[str],
    candidate_plant: Mapping[str, Any],
    estimated_cost: Mapping[str, Any],
    plant_gap: ContextState,
    harness_gap: ContextState,
    measurement_gap: ContextState,
    lawful_next: Sequence[str],
) -> LifecyclePossibilityFacet:
    """Build one content-addressed, non-authorizing lifecycle opportunity facet."""

    body = {
        "facet_id": facet_id,
        "candidate_ref": candidate_ref,
        "source_fact_refs": tuple(sorted(set(source_fact_refs))),
        "why_now": why_now,
        "does_not_prove": tuple(sorted(set(does_not_prove))),
        "uncertainty": uncertainty,
        "alternative_dispositions": tuple(sorted(set(alternative_dispositions))),
        "unknown_fields": tuple(sorted(set(unknown_fields))),
        "candidate_plant": build_canonical_json_object(candidate_plant),
        "estimated_cost": build_canonical_json_object(estimated_cost),
        "plant_gap": plant_gap,
        "harness_gap": harness_gap,
        "measurement_gap": measurement_gap,
        "lawful_next": tuple(sorted(set(lawful_next))),
        "no_effect": True,
        "may_authorize": False,
    }
    facet_hash = _domain_hash("hapax.lifecycle-possibility-facet.v1", body)
    return LifecyclePossibilityFacet(
        **body,
        facet_ref=f"lifecycle-possibility@sha256:{facet_hash}",
        facet_hash=facet_hash,
    )


def _build_addressed_carrier(
    model: type[BaseModel],
    *,
    domain: str,
    ref_prefix: str,
    ref_field: str,
    hash_field: str,
    body: Mapping[str, Any],
) -> Any:
    digest = _domain_hash(domain, body)
    return model.model_validate(
        {
            **body,
            ref_field: f"{ref_prefix}@sha256:{digest}",
            hash_field: digest,
        }
    )


def _normalized_carrier_body(
    values: Mapping[str, Any], *, tuple_fields: Sequence[str] = ()
) -> dict[str, Any]:
    body = dict(values)
    for field in tuple_fields:
        if field in body:
            body[field] = tuple(sorted(set(body[field])))
    body["no_effect"] = True
    body["may_authorize"] = False
    return body


def build_context_selection(
    position: ContextPosition,
    *,
    fact_frontier_ref: str,
    fact_frontier_hash: str,
    frontier_fact_refs: Sequence[str],
    event_frontier_refs: Sequence[str],
    audience: Literal["operator_private", "yard_context", "hapax_substrate", "public_or_air"],
    audience_seal_receipt_ref: str,
    audience_seal_receipt_hash: str,
    audience_policy_generation: str,
    privacy_policy_generation: str,
    selection_policy_ref: str,
    selection_policy_hash: str,
    selection_policy_generation: str,
    entries: Sequence[ContextSelectionEntry | Mapping[str, Any]],
    checked_at: str,
    stale_after: str,
) -> ContextSelection:
    """Build one support-only selection; required loss derives an explicit HOLD."""

    normalized_entries = tuple(
        sorted(
            (
                entry
                if isinstance(entry, ContextSelectionEntry)
                else ContextSelectionEntry.model_validate(entry)
                for entry in entries
            ),
            key=lambda entry: entry.fact_ref,
        )
    )
    body = {
        "schema": "hapax.context-selection.v1",
        "position_ref": position.position_ref,
        "position_hash": position.position_hash,
        "fact_frontier_ref": fact_frontier_ref,
        "fact_frontier_hash": fact_frontier_hash,
        "frontier_fact_refs": tuple(sorted(set(frontier_fact_refs))),
        "event_frontier_refs": tuple(sorted(set(event_frontier_refs))),
        "audience": audience,
        "audience_seal_receipt_ref": audience_seal_receipt_ref,
        "audience_seal_receipt_hash": audience_seal_receipt_hash,
        "audience_policy_generation": audience_policy_generation,
        "privacy_policy_generation": privacy_policy_generation,
        "selection_policy_ref": selection_policy_ref,
        "selection_policy_hash": selection_policy_hash,
        "selection_policy_generation": selection_policy_generation,
        "entries": normalized_entries,
        "state": _context_selection_state(normalized_entries),
        "checked_at": checked_at,
        "stale_after": stale_after,
        "no_effect": True,
        "may_authorize": False,
    }
    return _build_addressed_carrier(
        ContextSelection,
        domain="hapax.context-selection.v1",
        ref_prefix="context-selection",
        ref_field="selection_ref",
        hash_field="selection_hash",
        body=body,
    )


def build_context_scope(**values: Any) -> ContextScope:
    body = _normalized_carrier_body(values, tuple_fields=("subject_refs", "parent_scope_refs"))
    return _build_addressed_carrier(
        ContextScope,
        domain="hapax.context-scope.v1",
        ref_prefix="context-scope",
        ref_field="scope_ref",
        hash_field="scope_hash",
        body=body,
    )


def build_temporal_coordinate(**values: Any) -> TemporalCoordinate:
    body = _normalized_carrier_body(values, tuple_fields=("parent_span_refs", "correction_refs"))
    return _build_addressed_carrier(
        TemporalCoordinate,
        domain="hapax.temporal-coordinate.v1",
        ref_prefix="temporal-coordinate",
        ref_field="temporal_ref",
        hash_field="temporal_hash",
        body=body,
    )


def build_resolution_coordinate(**values: Any) -> ResolutionCoordinate:
    body = _normalized_carrier_body(values)
    return _build_addressed_carrier(
        ResolutionCoordinate,
        domain="hapax.resolution-coordinate.v1",
        ref_prefix="resolution-coordinate",
        ref_field="resolution_ref",
        hash_field="resolution_hash",
        body=body,
    )


def build_source_admission(**values: Any) -> SourceAdmission:
    body = _normalized_carrier_body(
        values,
        tuple_fields=(
            "join_keys",
            "verification_refs",
            "policy_refs",
            "supported_provenance_kinds",
            "consumer_contract_refs",
            "probe_witness_refs",
        ),
    )
    return _build_addressed_carrier(
        SourceAdmission,
        domain="hapax.source-admission.v1",
        ref_prefix="source-admission",
        ref_field="admission_ref",
        hash_field="admission_hash",
        body=body,
    )


def build_observation_envelope(**values: Any) -> ObservationEnvelope:
    body = _normalized_carrier_body(values, tuple_fields=("witness_refs", "source_refs"))
    if isinstance(body.get("payload"), Mapping):
        body["payload"] = build_canonical_json_object(body["payload"])
    return _build_addressed_carrier(
        ObservationEnvelope,
        domain="hapax.observation-envelope.v1",
        ref_prefix="observation-envelope",
        ref_field="observation_ref",
        hash_field="observation_hash",
        body=body,
    )


def build_derivation_record(**values: Any) -> DerivationRecord:
    body = _normalized_carrier_body(
        values,
        tuple_fields=(
            "input_observation_refs",
            "input_fact_refs",
            "output_refs",
            "validity_domain_refs",
        ),
    )
    return _build_addressed_carrier(
        DerivationRecord,
        domain="hapax.derivation-record.v1",
        ref_prefix="derivation-record",
        ref_field="derivation_ref",
        hash_field="derivation_hash",
        body=body,
    )


def build_signal_estimate(**values: Any) -> SignalEstimate:
    body = _normalized_carrier_body(values, tuple_fields=("source_fact_refs", "supersedes_refs"))
    if isinstance(body.get("value"), Mapping):
        body["value"] = build_canonical_json_object(body["value"])
    return _build_addressed_carrier(
        SignalEstimate,
        domain="hapax.signal-estimate.v1",
        ref_prefix="signal-estimate",
        ref_field="estimate_ref",
        hash_field="estimate_hash",
        body=body,
    )


def build_signal_lens(**values: Any) -> SignalLens:
    body = _normalized_carrier_body(
        values,
        tuple_fields=(
            "scope_selector_refs",
            "resolution_selector_refs",
            "constraint_mask_refs",
        ),
    )
    if isinstance(body.get("utility_weights"), Mapping):
        body["utility_weights"] = build_canonical_json_object(body["utility_weights"])
    return _build_addressed_carrier(
        SignalLens,
        domain="hapax.signal-lens.v1",
        ref_prefix="signal-lens",
        ref_field="lens_ref",
        hash_field="lens_hash",
        body=body,
    )


def build_signal_constellation(**values: Any) -> SignalConstellation:
    if "loss_manifest_ref" not in values:
        values = {
            **values,
            "loss_manifest_ref": signal_constellation_loss_manifest_ref(
                target_ref=values["target_ref"],
                lens_ref=values["lens_ref"],
                scope_ref=values["scope_ref"],
                resolution_ref=values["resolution_ref"],
                member_estimate_refs=tuple(sorted(set(values["member_estimate_refs"]))),
                relation_refs=tuple(sorted(set(values["relation_refs"]))),
                uncovered_source_refs=tuple(sorted(set(values["uncovered_source_refs"]))),
                aggregation_ref=values["aggregation_ref"],
            ),
        }
    body = _normalized_carrier_body(
        values,
        tuple_fields=(
            "member_estimate_refs",
            "relation_refs",
            "uncovered_source_refs",
        ),
    )
    return _build_addressed_carrier(
        SignalConstellation,
        domain="hapax.signal-constellation.v1",
        ref_prefix="signal-constellation",
        ref_field="constellation_ref",
        hash_field="constellation_hash",
        body=body,
    )


def build_context_exposure_component(**values: Any) -> ContextExposureComponent:
    body = _normalized_carrier_body(values)
    return _build_addressed_carrier(
        ContextExposureComponent,
        domain="hapax.context-exposure-component.v1",
        ref_prefix="context-exposure-component",
        ref_field="component_ref",
        hash_field="component_hash",
        body=body,
    )


def build_context_exposure_segment(**values: Any) -> ContextExposureSegment:
    body = _normalized_carrier_body(values, tuple_fields=("component_refs",))
    return _build_addressed_carrier(
        ContextExposureSegment,
        domain="hapax.context-exposure-segment.v1",
        ref_prefix="context-exposure-segment",
        ref_field="segment_ref",
        hash_field="segment_hash",
        body=body,
    )


def build_context_exposure(**values: Any) -> ContextExposure:
    body = _normalized_carrier_body(
        values,
        tuple_fields=(
            "producer_verification_refs",
            "correction_refs",
            "supersedes_refs",
        ),
    )
    for field in ("components", "segments", "stages"):
        if field in values:
            body[field] = tuple(values[field])
    return _build_addressed_carrier(
        ContextExposure,
        domain="hapax.context-exposure.v1",
        ref_prefix="context-exposure",
        ref_field="exposure_ref",
        hash_field="exposure_hash",
        body=body,
    )


def build_capability_behavior_observation(**values: Any) -> CapabilityBehaviorObservation:
    body = _normalized_carrier_body(
        values,
        tuple_fields=(
            "producer_verification_refs",
            "contradiction_refs",
            "correction_refs",
            "supersedes_refs",
        ),
    )
    if "observations" in values:
        body["observations"] = tuple(values["observations"])
    return _build_addressed_carrier(
        CapabilityBehaviorObservation,
        domain="hapax.capability-behavior-observation.v1",
        ref_prefix="capability-behavior-observation",
        ref_field="behavior_ref",
        hash_field="behavior_hash",
        body=body,
    )


def build_signal_learning_receipt(**values: Any) -> SignalLearningReceipt:
    body = _normalized_carrier_body(
        values,
        tuple_fields=(
            "fitness_boundary_refs",
            "witness_refs",
            "correction_refs",
            "supersedes_refs",
        ),
    )
    for field in ("effect", "cost"):
        if isinstance(body.get(field), Mapping):
            body[field] = build_canonical_json_object(body[field])
    return _build_addressed_carrier(
        SignalLearningReceipt,
        domain="hapax.signal-learning-receipt.v1",
        ref_prefix="signal-learning",
        ref_field="learning_ref",
        hash_field="learning_hash",
        body=body,
    )


def build_measurement_application_receipt(
    **values: Any,
) -> MeasurementApplicationReceipt:
    body = _normalized_carrier_body(
        values,
        tuple_fields=(
            "fitness_boundary_refs",
            "producer_verification_refs",
            "correction_refs",
            "supersedes_refs",
        ),
    )
    return _build_addressed_carrier(
        MeasurementApplicationReceipt,
        domain="hapax.measurement-application-receipt.v1",
        ref_prefix="measurement-application-receipt",
        ref_field="application_ref",
        hash_field="application_hash",
        body=body,
    )


def build_orienting_signal(**values: Any) -> OrientingSignal:
    body = _normalized_carrier_body(
        values,
        tuple_fields=("estimate_refs", "source_fact_refs", "does_not_prove"),
    )
    return _build_addressed_carrier(
        OrientingSignal,
        domain="hapax.orienting-signal.v1",
        ref_prefix="orienting-signal",
        ref_field="signal_ref",
        hash_field="signal_hash",
        body=body,
    )


def build_demand_shape_descriptor(
    *,
    session_ref: str,
    strategy: Mapping[str, Any],
    strata: Mapping[str, Any],
    canon: Mapping[str, Any],
    position_basis: Mapping[str, Any],
    offered_affordances: Sequence[str],
    provenance_generation: str,
    policy_generation: str,
    audience_policy: Mapping[str, Any],
    kernel: Mapping[str, Any],
    budget: Mapping[str, Any],
) -> DemandShapeDescriptor:
    """Build the complete demand fingerprint; callers never supply its digest."""

    body = {
        "schema": "hapax.demand-shape-descriptor.v1",
        "session_ref": session_ref,
        "strategy": build_canonical_json_object(strategy),
        "strata": build_canonical_json_object(strata),
        "canon": build_canonical_json_object(canon),
        "position_basis": build_canonical_json_object(position_basis),
        "offered_affordances": tuple(sorted(set(offered_affordances))),
        "provenance_generation": provenance_generation,
        "policy_generation": policy_generation,
        "audience_policy": build_canonical_json_object(audience_policy),
        "kernel": build_canonical_json_object(kernel),
        "budget": build_canonical_json_object(budget),
        "may_authorize": False,
    }
    fingerprint = _domain_hash("hapax.demand-shape-descriptor.v1", body)
    return DemandShapeDescriptor(
        **body,
        descriptor_ref=f"demand-shape@sha256:{fingerprint}",
        demand_shape_fingerprint=fingerprint,
    )


def build_epistemic_flow_event(
    *,
    event_id: str,
    kind: EpistemicEventKind,
    session_ref: str,
    task_ref: str,
    trace_ref: str,
    position_ref: str,
    scope_ref: str,
    temporal_ref: str,
    resolution_ref: str,
    generation: int,
    subject_ref: str,
    occurred_at: str,
    expires_at: str,
    producer_ref: str,
    method_ref: str,
    privacy_class: str,
    authority_ceiling: AuthorityCeiling,
    source_refs: Sequence[str],
    caused_by: Sequence[str],
    supersedes_refs: Sequence[str],
    derivation_depth: int,
    payload: Mapping[str, Any],
    state: ContextState,
) -> EpistemicFlowEvent:
    """Build one content-addressed, permanently non-authorizing causal event."""

    expected_payload_fields = _EPISTEMIC_EVENT_PAYLOAD_FIELDS.get(kind)
    if expected_payload_fields is None:
        raise ValueError("unsupported epistemic event kind")
    if tuple(sorted(payload)) != expected_payload_fields:
        raise ValueError(f"{kind} payload must contain exactly {expected_payload_fields}")
    body = {
        "event_id": event_id,
        "kind": kind,
        "session_ref": session_ref,
        "task_ref": task_ref,
        "trace_ref": trace_ref,
        "position_ref": position_ref,
        "scope_ref": scope_ref,
        "temporal_ref": temporal_ref,
        "resolution_ref": resolution_ref,
        "generation": generation,
        "subject_ref": subject_ref,
        "occurred_at": occurred_at,
        "expires_at": expires_at,
        "producer_ref": producer_ref,
        "method_ref": method_ref,
        "privacy_class": privacy_class,
        "authority_ceiling": authority_ceiling,
        "source_refs": tuple(sorted(set(source_refs))),
        "caused_by": tuple(sorted(set(caused_by))),
        "supersedes_refs": tuple(sorted(set(supersedes_refs))),
        "derivation_depth": derivation_depth,
        "payload": {"kind": kind, **payload},
        "state": state,
        "may_authorize": False,
    }
    event_hash = _domain_hash("hapax.epistemic-flow-event.v1", body)
    return EpistemicFlowEvent(
        **body,
        event_ref=f"epistemic-event@sha256:{event_hash}",
        event_hash=event_hash,
    )


ContextFrame.model_rebuild()
