"""Formal semantic recruitment row contract.

The rows in this module are a schema discipline for WCS-backed recruitment.
They do not seed the full runtime inventory and they do not alter live
AffordancePipeline behavior. Downstream registry sweep tasks can admit concrete
surfaces through this contract, then project valid rows into CapabilityRecord
and Qdrant payloads.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.affordance import (
    CapabilityRecord,
    OperationalProperties,
)
from shared.affordance import (
    ContentRisk as AffordanceContentRisk,
)
from shared.affordance import (
    MonetizationRisk as AffordanceMonetizationRisk,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_RECRUITMENT_FIXTURES = REPO_ROOT / "config" / "semantic-recruitment-fixtures.json"

DESCRIPTION_WORD_RANGE = range(8, 41)
GIBSON_VERBS = frozenset(
    {
        "act",
        "communicate",
        "compose",
        "express",
        "maintain",
        "modulate",
        "observe",
        "recall",
        "regulate",
        "retrieve",
        "route",
        "sense",
        "witness",
    }
)
FORBIDDEN_DESCRIPTION_TERMS = frozenset(
    {
        "api",
        "call",
        "cli",
        "context7",
        "docker",
        "localhost",
        "mcp",
        "pipewire",
        "port",
        "qdrant",
        "service",
        "systemd",
        "tavily",
        "tool",
        "wireplumber",
        "yaml",
    }
)
PATH_LIKE_PATTERN = re.compile(r"(/[\w.-]+)|(\b[a-z_][\w-]*\.(py|json|yaml|yml|service|timer)\b)")


class SemanticRecruitmentError(ValueError):
    """Raised when semantic recruitment rows cannot be loaded or projected."""


class SemanticKind(StrEnum):
    ENTITY = "Entity"
    PROCESS = "Process"
    STATE = "State"
    EVENT = "Event"
    SIGNAL = "Signal"
    CAPABILITY = "Capability"
    AFFORDANCE = "Affordance"
    SUBSTRATE = "Substrate"
    REPRESENTATION = "Representation"
    CONSTRAINT = "Constraint"


class SemanticLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class LifecycleState(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    STALE = "stale"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    DECOMMISSIONED = "decommissioned"
    SUPERSEDED = "superseded"
    CATALOG_ONLY = "catalog_only"


class Direction(StrEnum):
    OBSERVE = "observe"
    EXPRESS = "express"
    ACT = "act"
    ROUTE = "route"
    RECALL = "recall"
    COMMUNICATE = "communicate"
    REGULATE = "regulate"


class EffectType(StrEnum):
    SENSE = "sense"
    EXPRESS = "express"
    RECALL = "recall"
    ACT = "act"
    COMMUNICATE = "communicate"
    REGULATE = "regulate"
    COMPOSE = "compose"
    MODULATE = "modulate"


class Realm(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"
    HYBRID = "hybrid"


class Medium(StrEnum):
    VISUAL = "visual"
    AUDITORY = "auditory"
    TEXTUAL = "textual"
    HAPTIC = "haptic"
    NOTIFICATION = "notification"
    CONTROL = "control"
    DATA = "data"


class LatencyClass(StrEnum):
    REALTIME = "realtime"
    FAST = "fast"
    SLOW = "slow"
    ASYNC = "async"


class RelationPredicate(StrEnum):
    REALIZES = "realizes"
    IN_DOMAIN = "in_domain"
    IN_FAMILY = "in_family"
    IMPLEMENTED_BY = "implemented_by"
    OBSERVES = "observes"
    EMITS = "emits"
    MODULATES = "modulates"
    COMPOSES_INTO = "composes_into"
    REQUIRES = "requires"
    VETOES = "vetoes"
    BIASES = "biases"
    PROVIDES_EVIDENCE_FOR = "provides_evidence_for"
    CLAIMS_ABOUT = "claims_about"
    WITNESSES = "witnesses"
    DECOMMISSIONS = "decommissions"
    SUPERSEDES = "supersedes"


class PrivacyLabel(StrEnum):
    PRIVATE = "private"
    OPERATOR_VISIBLE = "operator_visible"
    PERSON_ADJACENT = "person_adjacent"
    PUBLIC_SAFE = "public_safe"
    PUBLIC_BROADCAST = "public_broadcast"


class ConsentLabel(StrEnum):
    NONE = "none"
    OPERATOR_SELF = "operator_self"
    PERSON_ADJACENT = "person_adjacent"
    IDENTIFIABLE_PERSON = "identifiable_person"
    PUBLIC_BROADCAST = "public_broadcast"


class RightsLabel(StrEnum):
    UNKNOWN = "unknown"
    OPERATOR_OWNED = "operator_owned"
    PLATFORM_CLEARED = "platform_cleared"
    PERMISSIONED = "permissioned"
    THIRD_PARTY_UNCLEAR = "third_party_unclear"
    BLOCKED = "blocked"


class ContentRisk(StrEnum):
    UNKNOWN = "unknown"
    TIER_0_OWNED = "tier_0_owned"
    TIER_1_PLATFORM_CLEARED = "tier_1_platform_cleared"
    TIER_2_PROVENANCE_KNOWN = "tier_2_provenance_known"
    TIER_3_UNCERTAIN = "tier_3_uncertain"
    TIER_4_RISKY = "tier_4_risky"


class MonetizationRisk(StrEnum):
    UNKNOWN = "unknown"
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AuthorityCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    INTERNAL_ONLY = "internal_only"
    SPECULATIVE = "speculative"
    EVIDENCE_BOUND = "evidence_bound"
    POSTERIOR_BOUND = "posterior_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class ClaimType(StrEnum):
    NO_CLAIM = "no_claim"
    INTERNAL_OBSERVATION = "internal_observation"
    PRIVATE_ACTION = "private_action"
    EVIDENCE_BOUND_CLAIM = "evidence_bound_claim"
    PUBLIC_CLAIM = "public_claim"


class OutcomeLearningPolicy(StrEnum):
    DISABLED = "disabled"
    PRIVATE_WITNESS_REQUIRED = "private_witness_required"
    PUBLIC_WITNESS_REQUIRED = "public_witness_required"


class MigrationState(StrEnum):
    ALIAS = "alias"
    RENAMED = "renamed"
    SUPERSEDED = "superseded"
    DECOMMISSIONED = "decommissioned"


class SplitMergeDecisionKind(StrEnum):
    SPLIT = "split"
    MERGE = "merge"


CONSENT_ORDER: Mapping[ConsentLabel, int] = {
    ConsentLabel.NONE: 0,
    ConsentLabel.OPERATOR_SELF: 1,
    ConsentLabel.PERSON_ADJACENT: 2,
    ConsentLabel.IDENTIFIABLE_PERSON: 3,
    ConsentLabel.PUBLIC_BROADCAST: 4,
}
INTERPERSONAL_CONSENT_LABELS = frozenset(
    {
        ConsentLabel.PERSON_ADJACENT,
        ConsentLabel.IDENTIFIABLE_PERSON,
    }
)
CONTENT_RISK_ORDER: Mapping[ContentRisk, int] = {
    ContentRisk.TIER_0_OWNED: 0,
    ContentRisk.TIER_1_PLATFORM_CLEARED: 1,
    ContentRisk.TIER_2_PROVENANCE_KNOWN: 2,
    ContentRisk.TIER_3_UNCERTAIN: 3,
    ContentRisk.TIER_4_RISKY: 4,
    ContentRisk.UNKNOWN: 5,
}
MONETIZATION_RISK_ORDER: Mapping[MonetizationRisk, int] = {
    MonetizationRisk.NONE: 0,
    MonetizationRisk.LOW: 1,
    MonetizationRisk.MEDIUM: 2,
    MonetizationRisk.HIGH: 3,
    MonetizationRisk.UNKNOWN: 4,
}
AUTHORITY_ORDER: Mapping[AuthorityCeiling, int] = {
    AuthorityCeiling.NO_CLAIM: 0,
    AuthorityCeiling.INTERNAL_ONLY: 1,
    AuthorityCeiling.SPECULATIVE: 2,
    AuthorityCeiling.EVIDENCE_BOUND: 3,
    AuthorityCeiling.POSTERIOR_BOUND: 4,
    AuthorityCeiling.PUBLIC_GATE_REQUIRED: 5,
}


def lattice_allows[T](label: T, clearance: T, order: Mapping[T, int]) -> bool:
    """Return True when ``clearance`` is at least as strong as ``label``."""

    return order[label] <= order[clearance]


def _unique_values(values: Iterable[str]) -> bool:
    value_list = list(values)
    return len(value_list) == len(set(value_list))


def _description_word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text))


class DomainTag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1)
    subdomain: str | None = None

    @property
    def key(self) -> str:
        return f"{self.domain}.{self.subdomain}" if self.subdomain else self.domain


class FamilyTag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str = Field(min_length=1)
    intent_binding: str | None = None
    dispatch_required: bool = False

    @property
    def key(self) -> str:
        return f"{self.family}:{self.intent_binding}" if self.intent_binding else self.family


class SemanticDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal[SemanticLevel.L2] = SemanticLevel.L2
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_basic_level_affordance_text(self) -> Self:
        words = _description_word_count(self.text)
        if words not in DESCRIPTION_WORD_RANGE:
            raise ValueError("semantic description must be 8-40 words")

        first_word = re.match(r"\s*([A-Za-z]+)", self.text)
        if first_word is None or first_word.group(1).lower() not in GIBSON_VERBS:
            allowed = ", ".join(sorted(GIBSON_VERBS))
            raise ValueError(f"semantic description must start with a Gibson verb: {allowed}")

        lower = self.text.lower()
        forbidden = sorted(term for term in FORBIDDEN_DESCRIPTION_TERMS if term in lower.split())
        if forbidden:
            raise ValueError(
                "semantic description contains implementation terms: " + ", ".join(forbidden)
            )
        if PATH_LIKE_PATTERN.search(self.text):
            raise ValueError("semantic description must not contain paths or implementation files")
        return self


class SemanticRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predicate: RelationPredicate
    target_ref: str = Field(min_length=1)
    evidence_ref: str | None = None
    weight: float | None = Field(default=None, ge=-1.0, le=1.0)


class DispatchContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_family: str | None = None
    route_by_family_only: bool = False
    notes: str = ""


class CapabilityProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_name: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    daemon: str = Field(min_length=1)
    requires_gpu: bool = False
    requires_network: bool = False
    latency_class: LatencyClass = LatencyClass.FAST
    persistence: str = "none"
    priority_floor: bool = False
    public_capable: bool = False
    consent_person_id: str | None = None
    consent_data_category: str | None = None
    rights_ref: str | None = None
    provenance_ref: str | None = None


class AliasMigration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str = Field(min_length=1)
    state: MigrationState
    reason: str = Field(min_length=1)


class SemanticRecruitmentRow(BaseModel):
    """Canonical WCS/classification row for semantic recruitment discipline."""

    model_config = ConfigDict(extra="forbid")

    row_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    semantic_version: Literal[1] = 1
    relatum_id: str = Field(min_length=1)
    kind: set[SemanticKind] = Field(min_length=1)
    abstraction_level: SemanticLevel
    recruitable: bool
    catalog_only: bool = False
    lifecycle: LifecycleState
    core_substrate_instance: bool = False
    semantic_descriptions: list[SemanticDescription] = Field(min_length=1)
    domain_tags: list[DomainTag] = Field(min_length=1)
    family_tags: list[FamilyTag] = Field(min_length=1)
    direction: Direction
    effect_type: EffectType
    realm: Realm
    medium: Medium
    submedium: str | None = None
    latency: LatencyClass
    underlying_entity_refs: list[str] = Field(default_factory=list)
    process_refs: list[str] = Field(default_factory=list)
    state_refs: list[str] = Field(default_factory=list)
    substrate_refs: list[str] = Field(default_factory=list)
    provider_refs: list[str] = Field(default_factory=list)
    concrete_interfaces: list[str] = Field(default_factory=list)
    relations: list[SemanticRelation] = Field(min_length=1)
    availability_predicate: str | None = None
    freshness_ttl_s: int | None = Field(default=None, ge=0)
    evidence_refs: list[str] = Field(default_factory=list)
    witness_contract_id: str | None
    authority_ceiling: AuthorityCeiling
    claim_types_allowed: set[ClaimType]
    privacy_label: PrivacyLabel
    consent_label: ConsentLabel
    required_clearance: ConsentLabel
    rights_label: RightsLabel
    content_risk: ContentRisk
    monetization_risk: MonetizationRisk
    governance_risk_reasons: list[str] = Field(default_factory=list)
    dispatch_contract: DispatchContract = Field(default_factory=DispatchContract)
    outcome_learning_policy: OutcomeLearningPolicy
    projection: CapabilityProjection | None
    aliases: list[AliasMigration]
    supersedes: list[str] = Field(default_factory=list)
    replacement_row_id: str | None = None
    blocked_reason: str | None = None

    @model_validator(mode="after")
    def _validate_row_contract(self) -> Self:
        self._validate_unique_set_like_fields()
        self._validate_kind_and_lifecycle()
        self._validate_governance_lattices()
        self._validate_projection_contract()
        return self

    @property
    def primary_description(self) -> str:
        """Return the L2 text that should be embedded in recruitment."""

        return self.semantic_descriptions[0].text

    @property
    def projects_recruitable_capability(self) -> bool:
        """Whether this row may project into live CapabilityRecord/Qdrant form."""

        return (
            self.recruitable
            and self.lifecycle in {LifecycleState.ACTIVE, LifecycleState.DEGRADED}
            and not self.catalog_only
            and self.projection is not None
        )

    def to_capability_record(self) -> CapabilityRecord:
        """Project this canonical row into the legacy recruitment record."""

        if not self.projects_recruitable_capability or self.projection is None:
            raise SemanticRecruitmentError(
                f"row cannot project recruitable capability: {self.row_id}"
            )

        return CapabilityRecord(
            name=self.projection.capability_name,
            description=self.primary_description,
            daemon=self.projection.daemon,
            operational=OperationalProperties(
                requires_gpu=self.projection.requires_gpu,
                requires_network=self.projection.requires_network,
                latency_class=self.projection.latency_class.value,
                persistence=self.projection.persistence,
                medium=self.medium.value,
                consent_required=self.consent_label in INTERPERSONAL_CONSENT_LABELS,
                consent_person_id=self.projection.consent_person_id,
                consent_data_category=self.projection.consent_data_category,
                priority_floor=self.projection.priority_floor,
                public_capable=self.projection.public_capable,
                monetization_risk=cast("AffordanceMonetizationRisk", self.monetization_risk.value),
                risk_reason="; ".join(self.governance_risk_reasons) or None,
                content_risk=cast("AffordanceContentRisk", self.content_risk.value),
                content_risk_reason="; ".join(self.governance_risk_reasons) or None,
                rights_ref=self.projection.rights_ref,
                provenance_ref=self.projection.provenance_ref,
                evidence_refs=tuple(self.evidence_refs),
            ),
        )

    def to_qdrant_payload(
        self, activation_summary: Mapping[str, float | int] | None = None
    ) -> dict[str, Any]:
        """Project this row into a deterministic Qdrant payload contract."""

        record = self.to_capability_record()
        operational = record.operational
        return {
            "capability_name": record.name,
            "description": record.description,
            "daemon": record.daemon,
            "requires_gpu": operational.requires_gpu,
            "latency_class": operational.latency_class,
            "consent_required": operational.consent_required,
            "consent_person_id": operational.consent_person_id,
            "consent_data_category": operational.consent_data_category,
            "priority_floor": operational.priority_floor,
            "medium": operational.medium,
            "public_capable": operational.public_capable,
            "monetization_risk": operational.monetization_risk,
            "risk_reason": operational.risk_reason,
            "content_risk": operational.content_risk,
            "content_risk_reason": operational.content_risk_reason,
            "rights_ref": operational.rights_ref,
            "provenance_ref": operational.provenance_ref,
            "evidence_refs": list(operational.evidence_refs),
            "activation_summary": dict(activation_summary or {}),
            "available": self.lifecycle is LifecycleState.ACTIVE,
            "wcs_row_id": self.row_id,
            "semantic_version": self.semantic_version,
            "relatum_id": self.relatum_id,
            "kind": sorted(kind.value for kind in self.kind),
            "abstraction_level": self.abstraction_level.value,
            "domain_tags": [tag.model_dump(mode="json") for tag in self.domain_tags],
            "family_tags": [tag.model_dump(mode="json") for tag in self.family_tags],
            "direction": self.direction.value,
            "effect_type": self.effect_type.value,
            "realm": self.realm.value,
            "submedium": self.submedium,
            "lifecycle": self.lifecycle.value,
            "authority_ceiling": self.authority_ceiling.value,
            "claim_types_allowed": sorted(claim.value for claim in self.claim_types_allowed),
            "privacy_label": self.privacy_label.value,
            "consent_label": self.consent_label.value,
            "required_clearance": self.required_clearance.value,
            "rights_label": self.rights_label.value,
            "witness_contract_id": self.witness_contract_id,
            "outcome_learning_policy": self.outcome_learning_policy.value,
            "aliases": [alias.model_dump(mode="json") for alias in self.aliases],
            "relation_predicates": sorted(
                {relation.predicate.value for relation in self.relations}
            ),
        }

    def _validate_unique_set_like_fields(self) -> None:
        field_values = {
            "underlying_entity_refs": self.underlying_entity_refs,
            "process_refs": self.process_refs,
            "state_refs": self.state_refs,
            "substrate_refs": self.substrate_refs,
            "provider_refs": self.provider_refs,
            "concrete_interfaces": self.concrete_interfaces,
            "evidence_refs": self.evidence_refs,
            "supersedes": self.supersedes,
            "aliases": [alias.alias for alias in self.aliases],
            "domain_tags": [tag.key for tag in self.domain_tags],
            "family_tags": [tag.key for tag in self.family_tags],
        }
        duplicates = [name for name, values in field_values.items() if not _unique_values(values)]
        if duplicates:
            raise ValueError(f"duplicate values in row fields: {', '.join(sorted(duplicates))}")

    def _validate_kind_and_lifecycle(self) -> None:
        if self.catalog_only and self.recruitable:
            raise ValueError("catalog-only rows cannot be recruitable")
        if self.core_substrate_instance:
            if SemanticKind.SUBSTRATE not in self.kind:
                raise ValueError("core substrate instance rows must include Substrate kind")
            if SemanticKind.CAPABILITY in self.kind or self.recruitable:
                raise ValueError("core substrate instances cannot be recruitable capabilities")
        if self.recruitable:
            required_kinds = {SemanticKind.CAPABILITY, SemanticKind.AFFORDANCE}
            if not required_kinds <= self.kind:
                raise ValueError("recruitable rows must include Capability and Affordance kinds")
            if self.lifecycle in {
                LifecycleState.BLOCKED,
                LifecycleState.DECOMMISSIONED,
                LifecycleState.SUPERSEDED,
                LifecycleState.CATALOG_ONLY,
            }:
                raise ValueError("blocked/decommissioned/catalog-only rows cannot be recruitable")
            if not self.witness_contract_id:
                raise ValueError("recruitable rows require a witness contract id")
            if not self.evidence_refs:
                raise ValueError("recruitable rows require evidence refs")
        if self.lifecycle in {LifecycleState.DECOMMISSIONED, LifecycleState.SUPERSEDED}:
            if self.recruitable:
                raise ValueError("decommissioned or superseded rows cannot be recruitable")
            if not self.replacement_row_id:
                raise ValueError("decommissioned or superseded rows require a replacement row id")
            if not self.blocked_reason:
                raise ValueError("decommissioned or superseded rows require a blocked reason")

    def _validate_governance_lattices(self) -> None:
        if not lattice_allows(self.consent_label, self.required_clearance, CONSENT_ORDER):
            raise ValueError("required clearance is weaker than the row consent label")
        if self.content_risk is ContentRisk.TIER_4_RISKY and self.recruitable:
            raise ValueError("tier_4 content risk cannot be recruitable")
        if self.monetization_risk is MonetizationRisk.HIGH and self.recruitable:
            raise ValueError("high monetization risk cannot be recruitable")
        if self.recruitable and self.content_risk is ContentRisk.UNKNOWN:
            raise ValueError("recruitable rows require explicit content risk")
        if self.recruitable and self.monetization_risk is MonetizationRisk.UNKNOWN:
            raise ValueError("recruitable rows require explicit monetization risk")
        if self.recruitable and self.rights_label in {RightsLabel.UNKNOWN, RightsLabel.BLOCKED}:
            raise ValueError("recruitable rows require explicit non-blocked rights label")
        if ClaimType.PUBLIC_CLAIM in self.claim_types_allowed:
            if self.authority_ceiling is not AuthorityCeiling.PUBLIC_GATE_REQUIRED:
                raise ValueError("public-claim rows require public_gate_required authority ceiling")
            if self.required_clearance is not ConsentLabel.PUBLIC_BROADCAST:
                raise ValueError("public-claim rows require public broadcast clearance")
            if not self.witness_contract_id or not self.evidence_refs:
                raise ValueError("public-claim rows require witness and evidence refs")
        if ClaimType.EVIDENCE_BOUND_CLAIM in self.claim_types_allowed:
            if (
                AUTHORITY_ORDER[self.authority_ceiling]
                < AUTHORITY_ORDER[AuthorityCeiling.EVIDENCE_BOUND]
            ):
                raise ValueError(
                    "evidence-bound claims require evidence_bound authority or stronger"
                )

    def _validate_projection_contract(self) -> None:
        if self.recruitable and self.projection is None:
            raise ValueError("recruitable rows require projection metadata")
        if self.projection is not None:
            if (
                self.projection.public_capable
                and ClaimType.PUBLIC_CLAIM not in self.claim_types_allowed
            ):
                raise ValueError("public-capable projection requires public_claim permission")
            if self.projection.public_capable and (
                not self.projection.rights_ref or not self.projection.provenance_ref
            ):
                raise ValueError("public-capable projection requires rights and provenance refs")
            if self.projects_recruitable_capability and (
                self.consent_label in INTERPERSONAL_CONSENT_LABELS
            ):
                if (
                    not self.projection.consent_person_id
                    or not self.projection.consent_data_category
                ):
                    raise ValueError(
                        "interpersonal consent projections require consent_person_id "
                        "and consent_data_category"
                    )
        if self.dispatch_contract.route_by_family_only:
            if not any(tag.dispatch_required for tag in self.family_tags):
                raise ValueError("family-only routing requires a structured dispatch family tag")
            if not self.dispatch_contract.intent_family:
                raise ValueError("family-only routing requires an explicit intent family")


class SplitMergeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    decision: SplitMergeDecisionKind
    row_ids: list[str] = Field(min_length=1)
    canonical_row_id: str | None = None
    dimensions: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_decision_shape(self) -> Self:
        if not _unique_values(self.row_ids):
            raise ValueError("split/merge decision row ids must be unique")
        if self.decision is SplitMergeDecisionKind.SPLIT and len(self.row_ids) < 2:
            raise ValueError("split decisions require at least two rows")
        if self.decision is SplitMergeDecisionKind.MERGE:
            if self.canonical_row_id is None:
                raise ValueError("merge decisions require canonical_row_id")
            if self.canonical_row_id not in self.row_ids:
                raise ValueError("canonical_row_id must be one of row_ids")
        return self


class SemanticRecruitmentFixtureSet(BaseModel):
    """Fixture bundle for the first semantic-recruitment contract slice."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = Field(default=None, alias="$schema")
    schema_version: Literal[1] = 1
    generated_from: list[str] = Field(min_length=1)
    rows: list[SemanticRecruitmentRow] = Field(min_length=1)
    split_merge_decisions: list[SplitMergeDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_fixture_contract(self) -> Self:
        row_ids = [row.row_id for row in self.rows]
        duplicates = sorted({row_id for row_id in row_ids if row_ids.count(row_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate semantic recruitment row ids: {', '.join(duplicates)}")

        row_id_set = set(row_ids)
        missing_replacements = sorted(
            row.replacement_row_id
            for row in self.rows
            if row.replacement_row_id and row.replacement_row_id not in row_id_set
        )
        if missing_replacements:
            raise ValueError(
                "replacement rows missing from fixture set: " + ", ".join(missing_replacements)
            )

        decision_refs = {
            row_id for decision in self.split_merge_decisions for row_id in decision.row_ids
        }
        missing_decision_refs = sorted(decision_refs - row_id_set)
        if missing_decision_refs:
            raise ValueError(
                "split/merge decisions reference unknown rows: " + ", ".join(missing_decision_refs)
            )
        return self

    def by_id(self) -> dict[str, SemanticRecruitmentRow]:
        """Return rows keyed by row id."""

        return {row.row_id: row for row in self.rows}

    def require_row(self, row_id: str) -> SemanticRecruitmentRow:
        """Return one row or raise a fail-closed lookup error."""

        row = self.by_id().get(row_id)
        if row is None:
            raise KeyError(f"unknown semantic recruitment row: {row_id}")
        return row

    def recruitable_rows(self) -> list[SemanticRecruitmentRow]:
        """Return rows that can project into recruitable capabilities."""

        return [row for row in self.rows if row.projects_recruitable_capability]

    def qdrant_payloads_for_single_indexing(self) -> dict[str, dict[str, Any]]:
        """Projection contract for one-row-at-a-time indexing paths."""

        return {row.row_id: row.to_qdrant_payload() for row in self.recruitable_rows()}

    def qdrant_payloads_for_batch_indexing(self) -> dict[str, dict[str, Any]]:
        """Projection contract for batch indexing paths."""

        return {row.row_id: payload for row, payload in _batch_project(self.recruitable_rows())}


def _batch_project(
    rows: list[SemanticRecruitmentRow],
) -> list[tuple[SemanticRecruitmentRow, dict[str, Any]]]:
    return [(row, row.to_qdrant_payload()) for row in rows]


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SemanticRecruitmentError(f"{path} did not contain a JSON object")
    return payload


def load_semantic_recruitment_fixture_set(
    path: Path = SEMANTIC_RECRUITMENT_FIXTURES,
) -> SemanticRecruitmentFixtureSet:
    """Load semantic recruitment fixtures, failing closed on malformed data."""

    try:
        return SemanticRecruitmentFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise SemanticRecruitmentError(
            f"invalid semantic recruitment fixtures at {path}: {exc}"
        ) from exc


def semantic_recruitment_rows_by_id(
    path: Path = SEMANTIC_RECRUITMENT_FIXTURES,
) -> dict[str, SemanticRecruitmentRow]:
    """Convenience read access for downstream registry sweep tasks."""

    return load_semantic_recruitment_fixture_set(path).by_id()


__all__ = [
    "AUTHORITY_ORDER",
    "CONSENT_ORDER",
    "CONTENT_RISK_ORDER",
    "INTERPERSONAL_CONSENT_LABELS",
    "MONETIZATION_RISK_ORDER",
    "AliasMigration",
    "AuthorityCeiling",
    "CapabilityProjection",
    "ClaimType",
    "ConsentLabel",
    "ContentRisk",
    "Direction",
    "DispatchContract",
    "DomainTag",
    "EffectType",
    "FamilyTag",
    "LifecycleState",
    "Medium",
    "MigrationState",
    "MonetizationRisk",
    "OutcomeLearningPolicy",
    "PrivacyLabel",
    "Realm",
    "RelationPredicate",
    "RightsLabel",
    "SEMANTIC_RECRUITMENT_FIXTURES",
    "SemanticDescription",
    "SemanticKind",
    "SemanticLevel",
    "SemanticRecruitmentError",
    "SemanticRecruitmentFixtureSet",
    "SemanticRecruitmentRow",
    "SemanticRelation",
    "SplitMergeDecision",
    "SplitMergeDecisionKind",
    "lattice_allows",
    "load_semantic_recruitment_fixture_set",
    "semantic_recruitment_rows_by_id",
]
