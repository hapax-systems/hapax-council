"""Pure audience projection and locked compatibility verification."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from .contract import (
    _AUTHORITY_CEILING_RANK,
    _HASH_PATTERN,
    _JSON_SAFE_INTEGER_MAX,
    _LIFECYCLE_FSM_BLIND_SPOTS,
    _LIFECYCLE_FSM_DOES_NOT_PROVE,
    _LIFECYCLE_FSM_IMPLICATIONS,
    _LIFECYCLE_FSM_MEANING,
    _LIFECYCLE_FSM_PROVES,
    _PROVENANCE_AUTHORITY_RANK,
    GENERATOR_VERSION,
    BoundaryOrientationFacet,
    CanonicalJsonObject,
    ContextAction,
    ContextBundleFsm,
    ContextBundleImpingement,
    ContextBundleOrientingSignal,
    ContextBundleProvenance,
    ContextBundleStrata,
    ContextBundleTriAudience,
    ContextBundleWire,
    ContextConfidence,
    ContextFact,
    ContextFrame,
    ContextImpingement,
    ContextPosition,
    ContextProvenance,
    ContextRelation,
    ContextScope,
    ContextState,
    DemandShapeBinding,
    DerivationRecord,
    EpistemicFlowEvent,
    FactFreshness,
    FrozenModel,
    LifecyclePossibilityFacet,
    ObservationEnvelope,
    OrientingSignal,
    PortalOffer,
    ResolutionCoordinate,
    SignalConstellation,
    SignalEstimate,
    SignalLearningReceipt,
    SignalLens,
    SourceAdmission,
    TemporalCoordinate,
    _canon_error,
    _derivation_input_authority_rank,
    _domain_hash,
    _lifecycle_stage,
    _orientation_value_evidence_refs,
    _sha256,
    _stage_operation_admission_ref,
    _stage_transition_admission_ref,
    _validate_fact_evidence_and_authority,
    _validate_fact_state_freshness,
    _validate_string_set,
    _validate_timestamp,
    _validate_wire_string,
    canonical_json_bytes,
)

PROJECTION_ALGORITHM = "hapax.sdlc-forward-cone.v1"

ENCODER_ID = "python-toon@0.1.3"

REFERENCE_TOKENIZER_ID = "hapax.ascii-lexeme.v1"

LOCKED_CONTEXT_BUNDLE_CONTRACT_SHA256 = (
    "8204a2b2804aa41ac95f75414b58fa88ae1e76a48e6ef731807f544f4148fbd9"
)


class ProjectedFact(FrozenModel):
    projection_kind: Literal["fact"]
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
        _validate_fact_state_freshness(self.freshness_state, self.state, label="projected fact")
        if self.provenance.kind == "absent" and (
            self.state.value_state != "absent" or self.freshness_state != "absent"
        ):
            raise ValueError("absent projected provenance requires an absent projected fact")
        if self.provenance.kind == "dark" and (
            self.state.value_state != "dark" or self.freshness_state != "dark"
        ):
            raise ValueError("dark projected provenance requires a dark projected fact")
        if self.state.value_state in {"absent", "dark", "hold", "refused"}:
            if self.data.canonical_json != "{}":
                raise ValueError("unavailable projected facts cannot fabricate data")
        if self.confidence.abstained and self.state.value_state == "present":
            raise ValueError("abstained projected facts cannot be present")
        if set(self.legal_next) & set(self.prohibited_next):
            raise ValueError("one projected fact cannot mark an action legal and prohibited")
        return self


class RedactedFact(FrozenModel):
    projection_kind: Literal["redacted"]
    fact_id: str
    state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator("fact_id")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @model_validator(mode="after")
    def validate_redaction(self) -> Self:
        if self.state.value_state != "dark":
            raise ValueError("a redacted fact must be explicitly dark")
        return self


class RedactedContextObject(FrozenModel):
    object_kind: Literal[
        "scope",
        "temporal",
        "resolution",
        "source_admission",
        "observation",
        "derivation",
        "relation",
        "action",
        "estimate",
        "lens",
        "constellation",
        "signal",
        "learning_receipt",
        "event",
    ]
    object_id: str
    state: ContextState
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator("object_id")
    @classmethod
    def validate_object_id(cls, value: str) -> str:
        return _validate_wire_string(value)

    @model_validator(mode="after")
    def validate_redaction(self) -> Self:
        if self.state.value_state != "dark":
            raise ValueError("a redacted context object must be explicitly dark")
        return self


class ProjectionMappingManifest(FrozenModel):
    manifest_ref: str
    manifest_hash: str = Field(pattern=_HASH_PATTERN)
    source_schema: Literal["hapax.context-frame.v1"]
    projection_schema: Literal["hapax.projection-envelope.v1"]
    field_mappings: tuple[str, ...] = Field(min_length=1)
    omitted_field_paths: tuple[str, ...] = Field(min_length=1)
    transform_refs: tuple[str, ...] = Field(min_length=1)
    reversibility: Literal["partial"]
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator("manifest_ref")
    @classmethod
    def validate_manifest_ref(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("field_mappings", "omitted_field_paths", "transform_refs")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name, allow_empty=False)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"manifest_ref", "manifest_hash"}
        )
        expected_hash = _domain_hash("hapax.projection-mapping-manifest.v1", body)
        if self.manifest_hash != expected_hash:
            raise ValueError("manifest_hash does not bind projection mapping")
        if self.manifest_ref != f"projection-mapping@sha256:{expected_hash}":
            raise ValueError("manifest_ref does not bind manifest_hash")
        return self


class ProjectionLoss(FrozenModel):
    state: Literal["partial"]
    manifest_ref: str
    manifest_hash: str = Field(pattern=_HASH_PATTERN)
    reason_codes: tuple[str, ...]

    @field_validator("manifest_ref")
    @classmethod
    def validate_manifest_ref(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("reason_codes")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name, allow_empty=False)


class ProjectionEnvelope(FrozenModel):
    """A sealed semantic view; content addressing is not producer authentication."""

    schema_id: Literal["hapax.projection-envelope.v1"] = Field(alias="schema")
    projection_ref: str
    projection_hash: str = Field(pattern=_HASH_PATTERN)
    position: ContextPosition
    demand_shape: DemandShapeBinding
    audience: Literal["operator_private", "yard_context", "hapax_substrate"]
    purpose: Literal["operation", "orientation", "lifecycle_possibility"]
    depth: Literal["immediate", "expanded", "inspectable", "raw"]
    device_class: Literal["monitor", "handheld", "compact", "accessible_linear"]
    register_mode: Literal["plain", "labeled", "formal", "raw"] = Field(alias="register")
    decoder_ref: str
    focus_ref: str
    state: ContextState
    meaning: tuple[str, ...] = Field(min_length=1)
    implications: tuple[str, ...] = Field(min_length=1)
    blind_spots: tuple[str, ...] = Field(min_length=1)
    scopes: tuple[ContextScope, ...]
    temporal_coordinates: tuple[TemporalCoordinate, ...]
    resolution_coordinates: tuple[ResolutionCoordinate, ...]
    source_admissions: tuple[SourceAdmission, ...]
    observations: tuple[ObservationEnvelope, ...]
    derivations: tuple[DerivationRecord, ...]
    events: tuple[EpistemicFlowEvent, ...]
    facts: tuple[ProjectedFact | RedactedFact, ...]
    redacted_objects: tuple[RedactedContextObject, ...]
    relations: tuple[ContextRelation, ...]
    actions: tuple[ContextAction, ...]
    impingements: tuple[ContextImpingement, ...]
    signal_estimates: tuple[SignalEstimate, ...]
    signal_lenses: tuple[SignalLens, ...]
    signal_constellations: tuple[SignalConstellation, ...]
    orienting_signals: tuple[OrientingSignal, ...]
    portal_offers: tuple[PortalOffer, ...]
    signal_learning_receipts: tuple[SignalLearningReceipt, ...]
    legal_next: tuple[str, ...]
    prohibited_next: tuple[str, ...]
    lineage_refs: tuple[str, ...] = Field(min_length=1)
    supersedes_refs: tuple[str, ...]
    producer_ref: str
    verification_scope: Literal["structure_and_content_address_only"]
    producer_verification_required: Literal[True]
    generated_at: str
    stale_after: str
    audience_policy_digest: str = Field(pattern=_HASH_PATTERN)
    mapping_manifest: ProjectionMappingManifest
    loss: ProjectionLoss
    orientation: BoundaryOrientationFacet | None
    lifecycle_possibility: LifecyclePossibilityFacet | None
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator("projection_ref", "decoder_ref", "focus_ref", "producer_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("meaning", "implications", "blind_spots", "legal_next", "prohibited_next")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(
            value,
            info.field_name,
            allow_empty=info.field_name in {"legal_next", "prohibited_next"},
        )

    @field_validator("supersedes_refs")
    @classmethod
    def validate_supersedes_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_string_set(value, "supersedes_refs")

    @field_validator("lineage_refs")
    @classmethod
    def validate_lineage_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_validate_wire_string(item) != item for item in value):
            raise ValueError("lineage_refs entries must be valid strings")
        if len(value) != len(set(value)):
            raise ValueError("lineage_refs must be unique while preserving causal order")
        return value

    @field_validator("generated_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str, info: Any) -> str:
        return _validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.generated_at >= self.stale_after:
            raise ValueError("projection generation must strictly precede its expiry")
        if self.position.demand_shape_fingerprint != self.demand_shape.fingerprint:
            raise ValueError("projection position differs from demand shape")
        full_facts = tuple(item for item in self.facts if isinstance(item, ProjectedFact))
        usable_fact_horizons = tuple(
            item.provenance.stale_after
            for item in full_facts
            if item.freshness_state in {"fresh", "aging"}
        )
        if usable_fact_horizons:
            usable_fact_horizon = min(usable_fact_horizons)
            if self.generated_at >= usable_fact_horizon:
                raise ValueError("projected fresh and aging facts require unexpired provenance")
            if self.stale_after > usable_fact_horizon:
                raise ValueError("projection expiry exceeds visible usable fact provenance")
        latest_materialization = max(
            (
                *(item.provenance.produced_at for item in full_facts),
                *(item.processing_time for item in self.temporal_coordinates),
            ),
            default=self.generated_at,
        )
        if self.generated_at < latest_materialization:
            raise ValueError("projection generation precedes its visible evidence")
        fact_ids = {item.fact_id for item in full_facts}
        focus_refs = fact_ids | {item.subject_ref for item in full_facts}
        if self.focus_ref not in focus_refs:
            raise ValueError("projection focus must resolve to a fully visible fact")
        focused_facts = tuple(
            item for item in full_facts if self.focus_ref in {item.fact_id, item.subject_ref}
        )
        considered_facts = focused_facts or full_facts
        non_present_facts = tuple(
            item for item in considered_facts if item.state.value_state != "present"
        )
        if not considered_facts:
            expected_state = ContextState(
                value_state="dark", reason_codes=("audience_context_unavailable",)
            )
        elif len(considered_facts) == 1:
            expected_state = considered_facts[0].state
        elif not non_present_facts:
            expected_state = ContextState(value_state="present", reason_codes=())
        else:
            reasons = tuple(
                sorted({reason for item in non_present_facts for reason in item.state.reason_codes})
            )
            expected_state = ContextState(
                value_state="partial",
                reason_codes=reasons or ("mixed_context_state",),
            )
        if self.state != expected_state:
            raise ValueError("projection state must derive from its visible focus facts")
        lifecycle_facts = tuple(
            item
            for item in self.facts
            if isinstance(item, ProjectedFact) and item.fact_type == "lifecycle_fsm"
        )
        if len(lifecycle_facts) != 1:
            raise ValueError(
                "canonical audience projections require one visible lifecycle_fsm fact"
            )
        _validate_projected_lifecycle_fsm_fact(lifecycle_facts[0], self.position)
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
            (
                "redacted object",
                tuple(f"{item.object_kind}:{item.object_id}" for item in self.redacted_objects),
            ),
        )
        for name, ids in keyed:
            if ids != tuple(sorted(set(ids))):
                raise ValueError(f"projection {name} ids must be sorted and unique")
        event_order = tuple(
            (item.occurred_at, item.generation, item.derivation_depth, item.event_ref)
            for item in self.events
        )
        if event_order != tuple(sorted(event_order)):
            raise ValueError("projection events must remain in canonical causal order")
        if len({item.event_id for item in self.events}) != len(self.events) or len(
            {item.event_ref for item in self.events}
        ) != len(self.events):
            raise ValueError("projection event ids and refs must be unique")
        action_by_id = {item.action_id: item for item in self.actions}
        action_ids = set(action_by_id)
        visible_object_keys = {
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
            *(
                (("orientation", self.orientation.facet_id),)
                if self.orientation is not None
                else ()
            ),
            *(
                (("lifecycle_possibility", self.lifecycle_possibility.facet_id),)
                if self.lifecycle_possibility is not None
                else ()
            ),
        }
        redacted_object_keys = {
            (item.object_kind, item.object_id) for item in self.redacted_objects
        }
        if visible_object_keys & redacted_object_keys:
            raise ValueError("one projected object cannot be both visible and redacted")
        scope_refs = {item.scope_ref for item in self.scopes}
        temporal_refs = {item.temporal_ref for item in self.temporal_coordinates}
        resolution_refs = {item.resolution_ref for item in self.resolution_coordinates}
        scope_by_ref = {item.scope_ref: item for item in self.scopes}
        temporal_by_ref = {item.temporal_ref: item for item in self.temporal_coordinates}
        resolution_by_ref = {item.resolution_ref: item for item in self.resolution_coordinates}
        admission_refs = {item.admission_ref for item in self.source_admissions}
        admission_by_ref = {item.admission_ref: item for item in self.source_admissions}
        observation_refs = {item.observation_ref for item in self.observations}
        observation_by_ref = {item.observation_ref: item for item in self.observations}
        derivation_refs = {item.derivation_ref for item in self.derivations}
        derivation_by_ref = {item.derivation_ref: item for item in self.derivations}
        estimate_refs = {item.estimate_ref for item in self.signal_estimates}
        estimate_by_ref = {item.estimate_ref: item for item in self.signal_estimates}
        lens_refs = {item.lens_ref for item in self.signal_lenses}
        lens_by_ref = {item.lens_ref: item for item in self.signal_lenses}
        constellation_refs = {item.constellation_ref for item in self.signal_constellations}
        constellation_by_ref = {item.constellation_ref: item for item in self.signal_constellations}
        for scope in self.scopes:
            if set(scope.parent_scope_refs) - scope_refs:
                raise ValueError("projection scope parents must resolve locally")
        for origin in self.scopes:
            visited: set[str] = set()
            pending = list(origin.parent_scope_refs)
            while pending:
                ref = pending.pop()
                if ref == origin.scope_ref:
                    raise ValueError("projection scope ancestry must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(scope_by_ref[ref].parent_scope_refs)
        temporal_ancestry = temporal_refs | set(self.position.receipt_lineage)
        for coordinate in self.temporal_coordinates:
            if coordinate.processing_time > self.generated_at:
                raise ValueError(
                    "projected temporal processing cannot follow projection generation"
                )
            dependencies = (*coordinate.parent_span_refs, *coordinate.correction_refs)
            if set(dependencies) - temporal_ancestry:
                raise ValueError("projection temporal ancestry must resolve locally or in receipts")
            for correction_ref in coordinate.correction_refs:
                if (
                    correction_ref in temporal_by_ref
                    and temporal_by_ref[correction_ref].processing_time
                    >= coordinate.processing_time
                ):
                    raise ValueError(
                        "projection temporal corrections must reference prior coordinates"
                    )
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
                    raise ValueError("projection temporal ancestry must be acyclic")
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
            if (
                coordinate.scope_ref not in scope_refs
                or coordinate.temporal_ref not in temporal_refs
            ):
                raise ValueError("projection resolution coordinates must resolve locally")
        for admission in self.source_admissions:
            if (
                admission.scope_ref not in scope_refs
                or admission.temporal_ref not in temporal_refs
                or admission.resolution_ref not in resolution_refs
            ):
                raise ValueError("projection source admission coordinates must resolve locally")
            admission_resolution = resolution_by_ref[admission.resolution_ref]
            if (
                admission_resolution.scope_ref != admission.scope_ref
                or admission_resolution.temporal_ref != admission.temporal_ref
            ):
                raise ValueError(
                    "projection source admission resolution differs from its coordinates"
                )
        for observation in self.observations:
            if observation.source_admission_ref not in admission_refs:
                raise ValueError("projection observations require admitted sources")
            if (
                observation.scope_ref not in scope_refs
                or observation.temporal_ref not in temporal_refs
                or observation.resolution_ref not in resolution_refs
            ):
                raise ValueError("projection observation coordinates must resolve locally")
            observation_resolution = resolution_by_ref[observation.resolution_ref]
            if (
                observation_resolution.scope_ref != observation.scope_ref
                or observation_resolution.temporal_ref != observation.temporal_ref
            ):
                raise ValueError("projection observation resolution differs from its coordinates")
            admission = admission_by_ref[observation.source_admission_ref]
            if (
                observation.scope_ref != admission.scope_ref
                or observation.temporal_ref != admission.temporal_ref
                or observation.resolution_ref != admission.resolution_ref
            ):
                raise ValueError("projection observation coordinates differ from its admission")
            if observation.authority_ceiling != admission.authority_ceiling:
                raise ValueError(
                    "projected observation authority ceiling must equal its source admission"
                )
            if (
                observation.state.value_state == "present"
                and admission.availability.value_state != "present"
            ):
                raise ValueError("projected present observations require available admissions")
            if set(observation.source_refs) - (
                observation_refs | set(self.position.receipt_lineage)
            ):
                raise ValueError(
                    "projection observation sources must resolve locally or in receipts"
                )
        for origin in self.observations:
            visited: set[str] = set()
            pending = [ref for ref in origin.source_refs if ref in observation_by_ref]
            while pending:
                ref = pending.pop()
                if ref == origin.observation_ref:
                    raise ValueError("projection observation ancestry must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(
                    parent
                    for parent in observation_by_ref[ref].source_refs
                    if parent in observation_by_ref
                )
        fact_by_id = {item.fact_id: item for item in full_facts}
        expected_derivation_outputs = fact_ids | {
            item.estimate_id for item in self.signal_estimates
        }
        output_owners: dict[str, list[str]] = {}
        for derivation in self.derivations:
            if set(derivation.input_observation_refs) - observation_refs:
                raise ValueError("projection derivation observations must resolve locally")
            if set(derivation.input_fact_refs) - fact_ids:
                raise ValueError("projection derivation facts must resolve locally")
            if derivation.state.value_state == "present" and any(
                observation_by_ref[ref].state.value_state != "present"
                for ref in derivation.input_observation_refs
            ):
                raise ValueError("projected present derivations require present observations")
            if derivation.state.value_state == "present" and any(
                fact_by_id[ref].state.value_state != "present" for ref in derivation.input_fact_refs
            ):
                raise ValueError("projected present derivations require present facts")
            if set(derivation.output_refs) - expected_derivation_outputs:
                raise ValueError("projection derivation outputs must resolve locally")
            for output_ref in derivation.output_refs:
                output_owners.setdefault(output_ref, []).append(derivation.derivation_ref)
        if set(output_owners) != expected_derivation_outputs or any(
            len(owners) != 1 for owners in output_owners.values()
        ):
            raise ValueError("every projected fact and estimate requires one derivation owner")
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
                    raise ValueError("projection derivation ancestry must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(derivation_dependencies[ref])
        event_source_universe = (
            {
                self.position.position_ref,
                f"demand-shape@sha256:{self.demand_shape.fingerprint}",
            }
            | scope_refs
            | temporal_refs
            | resolution_refs
            | admission_refs
            | observation_refs
            | derivation_refs
            | fact_ids
            | {item.relation_id for item in self.relations}
            | action_ids
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
            **{item.fact_id: item.state for item in full_facts},
            **{item.relation_id: item.state for item in self.relations},
            **{item.action_id: item.state for item in self.actions},
            **{item.impingement_id: item.state for item in self.impingements},
            **{item.estimate_ref: item.state for item in self.signal_estimates},
            **{item.constellation_ref: item.state for item in self.signal_constellations},
            **{item.signal_ref: item.state for item in self.orienting_signals},
            **{item.portal_ref: item.state for item in self.portal_offers},
            **{item.learning_ref: item.state for item in self.signal_learning_receipts},
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
            **{
                item.derivation_ref: _derivation_input_authority_rank(
                    item, observation_by_ref, fact_by_id
                )
                for item in self.derivations
            },
            **{
                item.fact_id: _PROVENANCE_AUTHORITY_RANK[item.provenance.authority_level]
                for item in full_facts
            },
        }
        event_by_ref = {item.event_ref: item for item in self.events}
        event_ancestry = set(event_by_ref) | set(self.position.receipt_lineage)
        for event in self.events:
            if event.session_ref != self.demand_shape.descriptor.session_ref:
                raise ValueError("projected event session differs from its demand shape")
            if event.task_ref != self.position.task_ref:
                raise ValueError("projected event task differs from its position")
            if event.position_ref != self.position.position_ref:
                raise ValueError("projected event position differs from its projection")
            if (
                event.scope_ref not in scope_refs
                or event.temporal_ref not in temporal_refs
                or event.resolution_ref not in resolution_refs
            ):
                raise ValueError("projected event coordinates must resolve locally")
            event_resolution = resolution_by_ref[event.resolution_ref]
            if (
                event_resolution.scope_ref != event.scope_ref
                or event_resolution.temporal_ref != event.temporal_ref
            ):
                raise ValueError("projected event resolution differs from its coordinates")
            temporal = temporal_by_ref[event.temporal_ref]
            if temporal.event_time_start != event.occurred_at:
                raise ValueError("projected event occurrence differs from its temporal coordinate")
            if temporal.valid_until != event.expires_at:
                raise ValueError("projected event expiry differs from its temporal validity")
            if set(event.source_refs) - event_source_universe:
                raise ValueError("projected event sources must resolve visibly")
            if set((*event.caused_by, *event.supersedes_refs)) - event_ancestry:
                raise ValueError("projected event ancestry must resolve visibly")
            if event.state.value_state == "present" and any(
                event_source_states[ref].value_state != "present"
                for ref in event.source_refs
                if ref in event_source_states
            ):
                raise ValueError("projected present events require present source carriers")
            if event.state.value_state == "present" and any(
                event_by_ref[ref].state.value_state != "present"
                for ref in event.caused_by
                if ref in event_by_ref
            ):
                raise ValueError("projected present events require present causal events")
            event_authority_rank = _AUTHORITY_CEILING_RANK[event.authority_ceiling]
            if any(
                event_authority_rank > event_source_authority_ranks.get(ref, 0)
                for ref in event.source_refs
            ):
                raise ValueError("projected event authority exceeds its visible evidence")
            for ancestor_ref in event.caused_by:
                if ancestor_ref not in event_by_ref:
                    continue
                ancestor = event_by_ref[ancestor_ref]
                if event_authority_rank > _AUTHORITY_CEILING_RANK[ancestor.authority_ceiling]:
                    raise ValueError("projected event authority exceeds its causal ancestry")
                ancestor_temporal = temporal_by_ref[ancestor.temporal_ref]
                if ancestor.occurred_at > event.occurred_at:
                    raise ValueError("projected causal events cannot follow their children")
                if ancestor_temporal.processing_time > temporal.processing_time:
                    raise ValueError("projected causal processing cannot follow its children")
                if ancestor.generation > event.generation:
                    raise ValueError("projected causal event generations must be nondecreasing")
                if ancestor.derivation_depth >= event.derivation_depth:
                    raise ValueError("projected causal event depth must strictly increase")
            for ancestor_ref in event.supersedes_refs:
                if ancestor_ref not in event_by_ref:
                    continue
                ancestor = event_by_ref[ancestor_ref]
                ancestor_temporal = temporal_by_ref[ancestor.temporal_ref]
                if event_authority_rank > _AUTHORITY_CEILING_RANK[ancestor.authority_ceiling]:
                    raise ValueError("projected event authority exceeds superseded ancestry")
                if (
                    ancestor.occurred_at > event.occurred_at
                    or ancestor_temporal.processing_time > temporal.processing_time
                    or ancestor.generation > event.generation
                ):
                    raise ValueError("projected superseded events cannot follow replacements")
        for origin in self.events:
            visited: set[str] = set()
            pending = [
                ref for ref in (*origin.caused_by, *origin.supersedes_refs) if ref in event_by_ref
            ]
            while pending:
                ref = pending.pop()
                if ref == origin.event_ref:
                    raise ValueError("projected event ancestry must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                parent = event_by_ref[ref]
                pending.extend(
                    ref
                    for ref in (*parent.caused_by, *parent.supersedes_refs)
                    if ref in event_by_ref
                )
        for relation in self.relations:
            if {relation.source_fact_ref, relation.target_fact_ref} - fact_ids:
                raise ValueError("projection relations must reference fully visible facts")
            if set(relation.provenance_refs) - (
                observation_refs | fact_ids | set(self.position.receipt_lineage)
            ):
                raise ValueError("projection relation provenance must resolve in visible evidence")
        position_stage = _lifecycle_stage(
            self.position.lifecycle_definition, self.position.stage_token
        )
        for action in self.actions:
            if set(action.source_fact_refs) - fact_ids:
                raise ValueError("projection actions must reference fully visible facts")
            if action.position_ref != self.position.position_ref:
                raise ValueError("projected actions must bind the exact position")
            lifecycle_guards: tuple[str, ...] = ()
            if action.action_class == "lifecycle_operation":
                assert action.lifecycle_operation is not None
                try:
                    admission = next(
                        item
                        for item in position_stage.operation_admissions
                        if item.operation == action.lifecycle_operation
                    )
                except StopIteration as exc:
                    raise ValueError(
                        "projected lifecycle operation is not admitted at this stage"
                    ) from exc
                if action.admission_ref != _stage_operation_admission_ref(
                    position_stage, action.lifecycle_operation
                ):
                    raise ValueError("projected lifecycle operation differs from its admission")
                lifecycle_guards = admission.guards
            elif action.action_class == "lifecycle_transition":
                assert action.transition_to is not None
                assert action.transition_edge is not None
                try:
                    transition = next(
                        item
                        for item in getattr(position_stage, action.transition_edge)
                        if item.to == action.transition_to
                    )
                except StopIteration as exc:
                    raise ValueError(
                        "projected lifecycle transition is not admitted at this stage"
                    ) from exc
                if action.admission_ref != _stage_transition_admission_ref(
                    position_stage,
                    action.transition_to,
                    action.transition_edge,
                ):
                    raise ValueError("projected lifecycle transition differs from its admission")
                lifecycle_guards = transition.guards
            elif any(
                item.operation == action.operation for item in position_stage.operation_admissions
            ):
                raise ValueError("lifecycle operation requires the lifecycle operation class")
            if (
                lifecycle_guards
                and tuple(item.guard for item in action.guard_evidence) != lifecycle_guards
            ):
                raise ValueError("projected lifecycle guards differ from the stage admission")
            allowed_guard_refs = fact_ids | observation_refs | set(self.position.receipt_lineage)
            if any(set(item.evidence_refs) - allowed_guard_refs for item in action.guard_evidence):
                raise ValueError("projected lifecycle guard evidence must resolve visibly")
            if any(
                ref in fact_ids and ref not in action.source_fact_refs
                for evidence in action.guard_evidence
                for ref in evidence.evidence_refs
            ):
                raise ValueError("projected lifecycle guard facts must be action source facts")
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
                        "projected satisfied guards require present, usable local evidence"
                    )
            flags = {item.name: item for item in self.position.authorized_flags}
            for evidence in action.guard_evidence:
                if not evidence.guard.endswith("_authorized"):
                    continue
                flag = flags.get(evidence.guard)
                if flag is None:
                    if evidence.disposition == "satisfied":
                        raise ValueError(
                            "a missing projected flag cannot satisfy an authority guard"
                        )
                    continue
                expected_disposition = "satisfied" if flag.authorized else "unsatisfied"
                if evidence.disposition != expected_disposition:
                    raise ValueError("projected authority guard differs from position flags")
                if flag.source_ref not in evidence.evidence_refs:
                    raise ValueError("projected authority guard must cite its flag source")
            source_facts = [fact for fact in full_facts if fact.fact_id in action.source_fact_refs]
            if action.disposition == "legal" and any(
                fact.state.value_state != "present" or fact.freshness_state == "stale"
                for fact in source_facts
            ):
                raise ValueError("projected legal actions require present, non-stale facts")
        for fact in full_facts:
            if (
                fact.scope_ref not in scope_refs
                or fact.temporal_ref not in temporal_refs
                or fact.resolution_ref not in resolution_refs
                or fact.derivation_ref not in derivation_refs
            ):
                raise ValueError("projected fact coordinates and derivation must resolve")
            fact_resolution = resolution_by_ref[fact.resolution_ref]
            if (
                fact_resolution.scope_ref != fact.scope_ref
                or fact_resolution.temporal_ref != fact.temporal_ref
            ):
                raise ValueError("projected fact resolution differs from its coordinates")
            if fact.fact_id not in derivation_by_ref[fact.derivation_ref].output_refs:
                raise ValueError("projected fact must be an output of its derivation")
            if (
                fact.state.value_state == "present"
                and derivation_by_ref[fact.derivation_ref].state.value_state != "present"
            ):
                raise ValueError("projected present facts require a present derivation")
            if fact.provenance.produced_at > self.generated_at:
                raise ValueError("projected fact provenance cannot follow projection generation")
            if (
                fact.freshness_state in {"fresh", "aging"}
                and self.generated_at >= fact.provenance.stale_after
            ):
                raise ValueError("projected fresh and aging facts require unexpired provenance")
            _validate_fact_evidence_and_authority(
                fact,
                derivation_by_ref[fact.derivation_ref],
                observation_by_ref,
                admission_by_ref,
                fact_by_id,
                self.position.receipt_lineage,
                label="projected fact",
            )
            expected_relations = tuple(
                relation.relation_id
                for relation in self.relations
                if fact.fact_id in {relation.source_fact_ref, relation.target_fact_ref}
            )
            if fact.relation_refs != expected_relations:
                raise ValueError("projected fact relation refs must match the local graph")
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
                raise ValueError("projected fact action refs must match local action dispositions")
            if fact.expected_receipt_refs != expected_receipts:
                raise ValueError("projected fact receipts must match local actions")
            allowed_supersession_refs = fact_ids | set(self.position.receipt_lineage)
            if set(fact.supersedes_refs) - allowed_supersession_refs:
                raise ValueError("projected fact supersedes refs must resolve in visible context")
            if fact.fact_id in fact.supersedes_refs:
                raise ValueError("a projected fact cannot supersede itself")
        fact_evidence_dependencies = {
            item.fact_id: {
                ref
                for ref in (
                    *item.provenance.source_refs,
                    *item.confidence.evidence_refs,
                )
                if ref in fact_by_id
            }
            for item in full_facts
        }
        for origin in full_facts:
            visited: set[str] = set()
            pending = list(fact_evidence_dependencies[origin.fact_id])
            while pending:
                ref = pending.pop()
                if ref == origin.fact_id:
                    raise ValueError("projected fact evidence ancestry must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(fact_evidence_dependencies[ref])
        for origin in full_facts:
            visited: set[str] = set()
            pending = [ref for ref in origin.supersedes_refs if ref in fact_by_id]
            while pending:
                ref = pending.pop()
                if ref == origin.fact_id:
                    raise ValueError("projected fact supersession must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(
                    parent for parent in fact_by_id[ref].supersedes_refs if parent in fact_by_id
                )
        for item in (*self.impingements, *self.orienting_signals, *self.portal_offers):
            if set(item.source_fact_refs) - fact_ids:
                raise ValueError("projection objects must reference fully visible facts")
        for estimate in self.signal_estimates:
            if estimate.position_ref != self.position.position_ref:
                raise ValueError("projected estimates must bind the exact position")
            if (
                estimate.scope_ref not in scope_refs
                or estimate.temporal_ref not in temporal_refs
                or estimate.resolution_ref not in resolution_refs
                or estimate.derivation_ref not in derivation_refs
            ):
                raise ValueError("projected estimate coordinates must resolve")
            estimate_resolution = resolution_by_ref[estimate.resolution_ref]
            if (
                estimate_resolution.scope_ref != estimate.scope_ref
                or estimate_resolution.temporal_ref != estimate.temporal_ref
            ):
                raise ValueError("projected estimate resolution differs from its coordinates")
            if set(estimate.source_fact_refs) - fact_ids:
                raise ValueError("projected estimates require visible source facts")
            if estimate.estimate_id not in derivation_by_ref[estimate.derivation_ref].output_refs:
                raise ValueError("projected estimate must be a derivation output")
            if (
                estimate.state.value_state == "present"
                and derivation_by_ref[estimate.derivation_ref].state.value_state != "present"
            ):
                raise ValueError("projected present estimates require a present derivation")
            if set(estimate.supersedes_refs) - (estimate_refs | set(self.position.receipt_lineage)):
                raise ValueError("projected estimate supersession must resolve visibly")
        for origin in self.signal_estimates:
            visited: set[str] = set()
            pending = [ref for ref in origin.supersedes_refs if ref in estimate_by_ref]
            while pending:
                ref = pending.pop()
                if ref == origin.estimate_ref:
                    raise ValueError("projected estimate supersession must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                pending.extend(
                    parent
                    for parent in estimate_by_ref[ref].supersedes_refs
                    if parent in estimate_by_ref
                )
        for lens in self.signal_lenses:
            if lens.audience != self.audience:
                raise ValueError("projected signal lens audience differs from projection")
            if set(lens.scope_selector_refs) - scope_refs:
                raise ValueError("projected lens scopes must resolve")
            if set(lens.resolution_selector_refs) - resolution_refs:
                raise ValueError("projected lens resolutions must resolve")
            allowed_constraint_refs = (
                fact_ids
                | action_ids
                | {item.impingement_id for item in self.impingements}
                | set(self.position.receipt_lineage)
            )
            if set(lens.constraint_mask_refs) - allowed_constraint_refs:
                raise ValueError("projected lens constraints must resolve visibly")
            if lens.constraint_mask_receipt_ref not in self.position.receipt_lineage:
                raise ValueError("projected lens mask receipt must resolve in position lineage")
        relation_ids = {item.relation_id for item in self.relations}
        for constellation in self.signal_constellations:
            if constellation.lens_ref not in lens_refs:
                raise ValueError("projected constellation lens must resolve")
            if (
                constellation.scope_ref not in scope_refs
                or constellation.resolution_ref not in resolution_refs
            ):
                raise ValueError("projected constellation coordinates must resolve")
            constellation_resolution = resolution_by_ref[constellation.resolution_ref]
            if constellation_resolution.scope_ref != constellation.scope_ref:
                raise ValueError("projected constellation resolution differs from its scope")
            if constellation.target_ref not in fact_ids:
                raise ValueError("projected constellation target must be visible")
            lens = lens_by_ref[constellation.lens_ref]
            if constellation.scope_ref not in lens.scope_selector_refs:
                raise ValueError("projected constellation scope is outside its lens")
            if constellation.resolution_ref not in lens.resolution_selector_refs:
                raise ValueError("projected constellation resolution is outside its lens")
            if set(constellation.member_estimate_refs) - estimate_refs:
                raise ValueError("projected constellation estimates must resolve")
            if any(
                estimate_by_ref[ref].scope_ref not in lens.scope_selector_refs
                or estimate_by_ref[ref].resolution_ref not in lens.resolution_selector_refs
                for ref in constellation.member_estimate_refs
            ):
                raise ValueError("projected constellation members are outside its lens")
            if constellation.state.value_state == "present" and any(
                estimate_by_ref[ref].state.value_state != "present"
                for ref in constellation.member_estimate_refs
            ):
                raise ValueError("projected present constellations require present estimates")
            if set(constellation.relation_refs) - relation_ids:
                raise ValueError("projected constellation relations must resolve")
            if set(constellation.uncovered_source_refs) - admission_refs:
                raise ValueError("projected constellation uncovered sources must resolve")
        axis_evidence_universe = (
            fact_ids | observation_refs | estimate_refs | set(self.position.receipt_lineage)
        )
        for signal in self.orienting_signals:
            if signal.position_ref != self.position.position_ref:
                raise ValueError("projected signals must bind the exact position")
            if set(signal.estimate_refs) - estimate_refs:
                raise ValueError("projected signal estimates must resolve")
            if (
                signal.lens_ref not in lens_refs
                or signal.constellation_ref not in constellation_refs
            ):
                raise ValueError("projected signal lens and constellation must resolve")
            constellation = constellation_by_ref[signal.constellation_ref]
            if signal.lens_ref != constellation.lens_ref:
                raise ValueError("projected signal lens differs from its constellation")
            if set(signal.estimate_refs) - set(constellation.member_estimate_refs):
                raise ValueError("projected signal estimates must be constellation members")
            estimate_fact_refs = {
                fact_ref
                for estimate_ref in signal.estimate_refs
                for fact_ref in estimate_by_ref[estimate_ref].source_fact_refs
            }
            if set(signal.source_fact_refs) - estimate_fact_refs:
                raise ValueError("projected signal facts must support its estimates")
            if set(_orientation_value_evidence_refs(signal.value_vector)) - (
                axis_evidence_universe
            ):
                raise ValueError("projected signal value evidence must resolve visibly")
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
                raise ValueError("projected present signals require present semantic dependencies")
        learning_by_ref = {item.learning_ref: item for item in self.signal_learning_receipts}
        learning_witness_states = {
            **{item.observation_ref: item.state for item in self.observations},
            **{item.fact_id: item.state for item in full_facts},
            **{item.estimate_ref: item.state for item in self.signal_estimates},
            **{item.action_id: item.state for item in self.actions},
        }
        for receipt in self.signal_learning_receipts:
            if (
                receipt.position_ref != self.position.position_ref
                or receipt.estimate_ref not in estimate_refs
                or receipt.constellation_ref not in constellation_refs
                or receipt.action_ref not in action_ids
            ):
                raise ValueError("projected learning receipt references must resolve")
            constellation = constellation_by_ref[receipt.constellation_ref]
            if receipt.estimate_ref not in constellation.member_estimate_refs:
                raise ValueError("projected learning estimate must belong to its constellation")
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
                raise ValueError("projected present learning requires present dependencies")
            allowed_learning_witnesses = (
                observation_refs | fact_ids | estimate_refs | action_ids
            ) | set(self.position.receipt_lineage)
            if set(receipt.witness_refs) - allowed_learning_witnesses:
                raise ValueError(
                    "projected learning witnesses must resolve locally or in position lineage"
                )
            if set((*receipt.correction_refs, *receipt.supersedes_refs)) - (
                set(learning_by_ref) | set(self.position.receipt_lineage)
            ):
                raise ValueError("projected learning lineage must resolve visibly")
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
                    raise ValueError("projected learning lineage must be acyclic")
                if ref in visited:
                    continue
                visited.add(ref)
                parent = learning_by_ref[ref]
                pending.extend(
                    ancestor
                    for ancestor in (*parent.correction_refs, *parent.supersedes_refs)
                    if ancestor in learning_by_ref
                )
        if any(set(item.legal_next) - action_ids for item in self.impingements):
            raise ValueError("projection impingements must reference projected actions")
        if self.position.impingement_digest != _domain_hash(
            "hapax.context-impingements.v1", self.impingements
        ):
            raise ValueError("projection impingements differ from the position commitment")
        if self.position.portal_set_digest != _domain_hash(
            "hapax.portal-set.v1", self.portal_offers
        ):
            raise ValueError("projection portals differ from the position commitment")
        signal_portals = {
            item.portal_ref for item in self.orienting_signals if item.portal_ref is not None
        }
        if signal_portals - {item.portal_ref for item in self.portal_offers}:
            raise ValueError("projection signals must reference projected portal offers")
        expected_meaning = tuple(sorted({item.meaning for item in full_facts})) or (
            "Context is unavailable under the active audience policy.",
        )
        expected_implications = tuple(
            sorted({value for item in full_facts for value in item.implications})
        ) or ("No semantic implication may be derived from unavailable context.",)
        expected_blind_spots = tuple(
            sorted({value for item in full_facts for value in item.blind_spots})
        ) or ("Audience-sealed context remains undisclosed.",)
        if self.meaning != expected_meaning:
            raise ValueError("projection meaning must derive from sealed facts")
        if self.implications != expected_implications:
            raise ValueError("projection implications must derive from sealed facts")
        if self.blind_spots != expected_blind_spots:
            raise ValueError("projection blind spots must derive from sealed facts")
        expected_legal = tuple(
            sorted(item.action_id for item in self.actions if item.disposition == "legal")
        )
        expected_prohibited = tuple(
            sorted(item.action_id for item in self.actions if item.disposition != "legal")
        )
        if self.legal_next != expected_legal or self.prohibited_next != expected_prohibited:
            raise ValueError("projection legal/prohibited action indexes must match actions")
        expected_supersedes = tuple(
            sorted({value for fact in full_facts for value in fact.supersedes_refs})
        )
        if self.supersedes_refs != expected_supersedes:
            raise ValueError("projection supersedes index must derive from visible facts")
        receipt_prefix = self.lineage_refs[: len(self.position.receipt_lineage)]
        if receipt_prefix != self.position.receipt_lineage:
            raise ValueError("projection lineage must begin with exact position receipts")
        event_lineage = self.lineage_refs[len(self.position.receipt_lineage) :]
        if event_lineage != tuple(item.event_ref for item in self.events):
            raise ValueError("projection event lineage must equal its typed visible events")
        if any(
            re.fullmatch(r"epistemic-event@sha256:[0-9a-f]{64}", ref) is None
            for ref in event_lineage
        ):
            raise ValueError("projection event lineage refs must be content addressed")
        expected_manifest = build_projection_mapping_manifest()
        if self.mapping_manifest != expected_manifest:
            raise ValueError("projection mapping manifest must be the static contract manifest")
        expected_loss = ProjectionLoss(
            state="partial",
            manifest_ref=expected_manifest.manifest_ref,
            manifest_hash=expected_manifest.manifest_hash,
            reason_codes=("audience_sealed_partial_view",),
        )
        if self.loss != expected_loss:
            raise ValueError("projection loss receipt must be constant and deny-oblivious")
        if self.purpose == "orientation":
            if self.orientation is None or self.lifecycle_possibility is not None:
                raise ValueError("orientation purpose requires only the orientation facet")
            if self.orientation.focus_ref != self.focus_ref:
                raise ValueError("orientation focus differs from projection focus")
            if self.orientation.position_ref != self.position.position_ref:
                raise ValueError("orientation position differs from projection position")
            if set(self.orientation.why_now_refs) - (fact_ids | set(self.position.receipt_lineage)):
                raise ValueError("orientation why-now refs must resolve in visible context")
            if set(self.orientation.can) - set(self.legal_next):
                raise ValueError("orientation can must be legal in this projection")
            if set(self.orientation.cannot) - set(self.prohibited_next):
                raise ValueError("orientation cannot must be prohibited in this projection")
            if self.orientation.counterfactual.action_id not in action_ids:
                raise ValueError("orientation counterfactual must reference a projected action")
        elif self.purpose == "lifecycle_possibility":
            if self.lifecycle_possibility is None or self.orientation is not None:
                raise ValueError(
                    "lifecycle_possibility purpose requires only its typed possibility facet"
                )
            if set(self.lifecycle_possibility.source_fact_refs) - fact_ids:
                raise ValueError("lifecycle possibility must reference visible facts")
            if set(self.lifecycle_possibility.lawful_next) - set(self.legal_next):
                raise ValueError("lifecycle possibility lawful next must remain visible and legal")
        elif self.orientation is not None or self.lifecycle_possibility is not None:
            raise ValueError("operation projections cannot carry orientation facets")
        visible_policy_decisions = tuple(
            sorted(
                (
                    ("position", "root", "allow"),
                    ("demand_shape", "root", "allow"),
                    *(("scope", item.scope_ref, "allow") for item in self.scopes),
                    *(
                        ("temporal", item.temporal_ref, "allow")
                        for item in self.temporal_coordinates
                    ),
                    *(
                        ("resolution", item.resolution_ref, "allow")
                        for item in self.resolution_coordinates
                    ),
                    *(
                        ("source_admission", item.admission_ref, "allow")
                        for item in self.source_admissions
                    ),
                    *(("observation", item.observation_ref, "allow") for item in self.observations),
                    *(("derivation", item.derivation_ref, "allow") for item in self.derivations),
                    *(
                        (
                            "fact",
                            item.fact_id,
                            "allow" if isinstance(item, ProjectedFact) else "redact",
                        )
                        for item in self.facts
                    ),
                    *(("relation", item.relation_id, "allow") for item in self.relations),
                    *(("action", item.action_id, "allow") for item in self.actions),
                    *(("impingement", item.impingement_id, "allow") for item in self.impingements),
                    *(("estimate", item.estimate_ref, "allow") for item in self.signal_estimates),
                    *(("lens", item.lens_ref, "allow") for item in self.signal_lenses),
                    *(
                        ("constellation", item.constellation_ref, "allow")
                        for item in self.signal_constellations
                    ),
                    *(("portal", item.portal_ref, "allow") for item in self.portal_offers),
                    *(("signal", item.signal_id, "allow") for item in self.orienting_signals),
                    *(
                        ("learning_receipt", item.learning_ref, "allow")
                        for item in self.signal_learning_receipts
                    ),
                    *(("event", item, "allow") for item in event_lineage),
                    *(
                        (item.object_kind, item.object_id, "redact")
                        for item in self.redacted_objects
                    ),
                    *(
                        (("orientation", self.orientation.facet_id, "allow"),)
                        if self.orientation is not None
                        else ()
                    ),
                    *(
                        (
                            (
                                "lifecycle_possibility",
                                self.lifecycle_possibility.facet_id,
                                "allow",
                            ),
                        )
                        if self.lifecycle_possibility is not None
                        else ()
                    ),
                )
            )
        )
        expected_policy_digest = _domain_hash(
            "hapax.projection.audience-policy.v1",
            {"audience": self.audience, "visible_decisions": visible_policy_decisions},
        )
        if self.audience_policy_digest != expected_policy_digest:
            raise ValueError("audience policy digest must bind only visible decisions")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"projection_ref", "projection_hash"}
        )
        expected_hash = _domain_hash("hapax.projection-envelope.v1", body)
        if self.projection_hash != expected_hash:
            raise ValueError("projection_hash does not bind the projection")
        if self.projection_ref != f"projection-envelope@sha256:{expected_hash}":
            raise ValueError("projection_ref does not bind projection_hash")
        return self


class TriAudienceProjectionRefs(FrozenModel):
    operator_private: str
    yard_context: str
    hapax_substrate: str

    @field_validator("operator_private", "yard_context", "hapax_substrate")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        value = _validate_wire_string(value)
        if re.fullmatch(r"projection-envelope@sha256:[0-9a-f]{64}", value) is None:
            raise ValueError("tri-audience refs must name content-addressed projections")
        return value

    @model_validator(mode="after")
    def validate_unique(self) -> Self:
        refs = (self.operator_private, self.yard_context, self.hapax_substrate)
        if len(refs) != len(set(refs)):
            raise ValueError("tri-audience projection refs must be distinct")
        return self


class ContextBundleCompatibilityProjection(FrozenModel):
    schema_id: Literal["hapax.context-bundle-v1-compatibility.v1"] = Field(alias="schema")
    compatibility_ref: str
    compatibility_hash: str = Field(pattern=_HASH_PATTERN)
    source_frame_ref: str
    source_frame_hash: str = Field(pattern=_HASH_PATTERN)
    source_projection_refs: TriAudienceProjectionRefs
    audience: Literal["operator_private"]
    state: Literal["hold"]
    compatibility_only: Literal[True]
    wire_contract_sha256: Literal[
        "8204a2b2804aa41ac95f75414b58fa88ae1e76a48e6ef731807f544f4148fbd9"
    ]
    wire: ContextBundleWire
    wire_digest: str = Field(pattern=_HASH_PATTERN)
    omitted_field_paths: tuple[str, ...] = Field(min_length=1)
    omission_digest: str = Field(pattern=_HASH_PATTERN)
    loss_state: Literal["partial"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    may_authorize: Literal[False]

    @field_validator("compatibility_ref", "source_frame_ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        return _validate_wire_string(value)

    @field_validator("omitted_field_paths", "reason_codes")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _validate_string_set(value, info.field_name, allow_empty=False)

    @model_validator(mode="after")
    def validate_compatibility(self) -> Self:
        if self.source_frame_ref != f"context-frame@sha256:{self.source_frame_hash}":
            raise ValueError("compatibility source frame ref does not bind its hash")
        if self.omitted_field_paths != _V1_OMITTED_FIELD_PATHS:
            raise ValueError("compatibility omissions must equal the exact v1 loss surface")
        if self.reason_codes != _V1_COMPATIBILITY_REASON_CODES:
            raise ValueError("compatibility reasons must equal the exact v1 reason contract")
        projection_set_hash = _domain_hash(
            "hapax.tri-audience-projection-set.v1",
            self.source_projection_refs.model_dump(mode="json"),
        )
        if self.wire.provenance.source != f"projection-set@sha256:{projection_set_hash}":
            raise ValueError("compatibility wire provenance must bind its projection refs")
        if self.wire_digest != context_bundle_digest(self.wire):
            raise ValueError("wire_digest does not bind the compatibility wire")
        expected_omission = _domain_hash(
            "hapax.context-bundle-v1.omissions.v1", self.omitted_field_paths
        )
        if self.omission_digest != expected_omission:
            raise ValueError("omission_digest does not bind omitted_field_paths")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"compatibility_ref", "compatibility_hash"},
        )
        expected_hash = _domain_hash("hapax.context-bundle-v1-compatibility.v1", body)
        if self.compatibility_hash != expected_hash:
            raise ValueError("compatibility_hash does not bind the complete wrapper")
        if self.compatibility_ref != f"context-bundle-compatibility@sha256:{expected_hash}":
            raise ValueError("compatibility_ref does not bind compatibility_hash")
        return self


def _validate_projected_lifecycle_fsm_fact(fact: ProjectedFact, position: ContextPosition) -> None:
    if fact.fact_id != f"fact:lifecycle-fsm:{position.canon_image_hash}":
        raise ValueError("projected lifecycle_fsm fact does not bind the canon image")
    if fact.data.sha256 != position.lifecycle_fsm_data_sha256:
        raise ValueError("projected lifecycle_fsm data differs from the position commitment")
    try:
        payload = json.loads(fact.data.canonical_json)
    except json.JSONDecodeError as exc:  # pragma: no cover - guarded by CanonicalJsonObject
        raise ValueError("projected lifecycle_fsm data is not JSON") from exc
    if set(payload) != {
        "schema",
        "lifecycle",
        "canon",
        "stage",
        "kernel",
        "representation",
        "what",
        "how",
        "must",
    }:
        raise ValueError("projected lifecycle_fsm data has the wrong top-level shape")
    lifecycle = payload["lifecycle"]
    canon = payload["canon"]
    stage = payload["stage"]
    kernel = payload["kernel"]
    representation = payload["representation"]
    if not all(
        isinstance(item, dict) for item in (lifecycle, canon, stage, kernel, representation)
    ):
        raise ValueError("projected lifecycle_fsm identity sections must be objects")
    if set(lifecycle) != {
        "definition_ref",
        "definition_hash",
        "lifecycle_ref",
        "profile_ref",
        "plant_type_ref",
        "unit_type_ref",
    }:
        raise ValueError("projected lifecycle_fsm lifecycle identity is incomplete")
    if set(canon) != {"id", "hash", "image_hash", "version"}:
        raise ValueError("projected lifecycle_fsm canon identity is incomplete")
    if set(stage) != {"token", "level", "projection_scope"}:
        raise ValueError("projected lifecycle_fsm stage identity is incomplete")
    if set(kernel) != {
        "name",
        "omitted_atom_ids",
        "omitted_digest",
        "distortion_class",
    }:
        raise ValueError("projected lifecycle_fsm kernel identity is incomplete")
    if set(representation) != {
        "generator_version",
        "projection_algorithm",
        "encoder_id",
        "reference_tokenizer_id",
        "reference_token_count",
    }:
        raise ValueError("projected lifecycle_fsm representation identity is incomplete")
    if payload["schema"] != "hapax.lifecycle-fsm-context.v1":
        raise ValueError("projected lifecycle_fsm schema is unsupported")
    if lifecycle["definition_ref"] != position.lifecycle_definition_ref:
        raise ValueError("projected lifecycle_fsm definition ref differs from position")
    if lifecycle["definition_hash"] != position.lifecycle_definition_hash:
        raise ValueError("projected lifecycle_fsm definition hash differs from position")
    if fact.subject_ref != lifecycle["lifecycle_ref"]:
        raise ValueError("projected lifecycle_fsm subject differs from lifecycle identity")
    if canon["id"] != position.canon_id:
        raise ValueError("projected lifecycle_fsm canon id differs from position")
    if canon["image_hash"] != position.canon_image_hash:
        raise ValueError("projected lifecycle_fsm image hash differs from position")
    if (
        isinstance(canon["version"], bool)
        or not isinstance(canon["version"], int)
        or canon["version"] != position.canon_version
    ):
        raise ValueError("projected lifecycle_fsm version differs from position")
    if (
        not all(isinstance(value, str) for value in lifecycle.values())
        or not isinstance(canon["id"], str)
        or not isinstance(canon["hash"], str)
        or not isinstance(canon["image_hash"], str)
        or not isinstance(stage["token"], str)
        or not isinstance(stage["level"], str)
        or not isinstance(kernel["name"], str)
        or not isinstance(kernel["omitted_digest"], str)
        or not isinstance(kernel["distortion_class"], str)
    ):
        raise ValueError("projected lifecycle_fsm identity values have invalid types")
    if stage["token"] != position.stage_token or stage["level"] != position.canon_level.value:
        raise ValueError("projected lifecycle_fsm stage differs from position")
    projection_scope = stage["projection_scope"]
    if (
        not isinstance(projection_scope, list)
        or not all(isinstance(item, str) for item in projection_scope)
        or projection_scope != list(dict.fromkeys(projection_scope))
        or position.stage_token not in projection_scope
    ):
        raise ValueError("projected lifecycle_fsm scope must be ordered, unique, and include stage")
    omitted_ids = kernel["omitted_atom_ids"]
    if (
        not isinstance(omitted_ids, list)
        or not all(isinstance(item, str) for item in omitted_ids)
        or omitted_ids != sorted(set(omitted_ids))
    ):
        raise ValueError("projected lifecycle_fsm omitted atoms must be sorted and unique")
    if kernel["omitted_digest"] != _sha256(canonical_json_bytes(omitted_ids)):
        raise ValueError("projected lifecycle_fsm kernel digest is invalid")
    if canon["id"] != f"coordination-canon@sha256:{canon['hash']}":
        raise ValueError("projected lifecycle_fsm canon id does not bind canon hash")
    if re.fullmatch(_HASH_PATTERN, str(canon["hash"])) is None:
        raise ValueError("projected lifecycle_fsm canon hash is invalid")
    if re.fullmatch(_HASH_PATTERN, str(kernel["omitted_digest"])) is None:
        raise ValueError("projected lifecycle_fsm omitted digest is invalid")
    if representation != {
        "generator_version": GENERATOR_VERSION,
        "projection_algorithm": PROJECTION_ALGORITHM,
        "encoder_id": ENCODER_ID,
        "reference_tokenizer_id": REFERENCE_TOKENIZER_ID,
        "reference_token_count": representation["reference_token_count"],
    }:
        raise ValueError("projected lifecycle_fsm representation contract is unsupported")
    token_count = representation["reference_token_count"]
    if (
        isinstance(token_count, bool)
        or not isinstance(token_count, int)
        or not 1 <= token_count <= _JSON_SAFE_INTEGER_MAX
    ):
        raise ValueError("projected lifecycle_fsm reference token count is invalid")
    if not all(
        isinstance(payload[stratum], str) and payload[stratum]
        for stratum in ("what", "how", "must")
    ):
        raise ValueError("projected lifecycle_fsm requires nonblank exact WHAT/HOW/MUST")
    if (
        fact.meaning != _LIFECYCLE_FSM_MEANING
        or fact.implications != _LIFECYCLE_FSM_IMPLICATIONS
        or fact.proves != _LIFECYCLE_FSM_PROVES
        or fact.does_not_prove != _LIFECYCLE_FSM_DOES_NOT_PROVE
        or fact.blind_spots != _LIFECYCLE_FSM_BLIND_SPOTS
        or fact.unit is not None
        or fact.freshness_state != "fresh"
        or fact.state.value_state != "present"
        or fact.provenance.kind != "constitutional"
        or fact.provenance.derivation != "extracted"
        or fact.provenance.authority_level != "authoritative"
        or fact.provenance.producer_ref != GENERATOR_VERSION
        or fact.provenance.generation != f"canon-version:{position.canon_version}"
        or not fact.provenance.source_refs
        or fact.confidence.word != "high"
        or fact.confidence.method != "deterministic"
        or fact.confidence.evidence_refs != fact.provenance.source_refs
        or fact.confidence.calibration_ref is not None
        or fact.confidence.calibration_metric is not None
        or fact.confidence.validity_domain_refs
        or fact.confidence.distribution_state != "not_applicable"
        or fact.confidence.abstained
        or fact.relation_refs
        or fact.legal_next
        or fact.prohibited_next
        or fact.expected_receipt_refs
        or fact.supersedes_refs
    ):
        raise ValueError("projected lifecycle_fsm semantic carrier is not exact")


def build_projection_mapping_manifest() -> ProjectionMappingManifest:
    """Return the one static, deny-oblivious frame-to-projection mapping contract."""

    source_mappings = {
        "actions": ("actions", "legal_next", "prohibited_next"),
        "air_bindings": ("audience_policy_digest", "redacted_objects"),
        "demand_shape": ("demand_shape",),
        "derivations": ("derivations",),
        "events": ("events", "lineage_refs"),
        "facts": ("blind_spots", "facts", "implications", "meaning", "state", "supersedes_refs"),
        "impingements": ("impingements",),
        "lifecycle_possibilities": ("lifecycle_possibility",),
        "may_authorize": ("may_authorize",),
        "observations": ("observations",),
        "orientation_facets": ("orientation",),
        "orienting_signals": ("orienting_signals",),
        "portal_offers": ("portal_offers",),
        "position": ("lineage_refs", "position"),
        "relations": ("relations",),
        "resolution_coordinates": ("resolution_coordinates",),
        "scopes": ("scopes",),
        "signal_constellations": ("signal_constellations",),
        "signal_estimates": ("signal_estimates",),
        "signal_learning_receipts": ("signal_learning_receipts",),
        "signal_lenses": ("signal_lenses",),
        "source_admissions": ("source_admissions",),
        "stale_after": ("stale_after",),
        "temporal_coordinates": ("temporal_coordinates",),
    }
    source_omissions = {
        "audience_policy_generation",
        "canon_image",
        "checked_at",
        "frame_hash",
        "frame_ref",
        "observed_at",
        "privacy_policy_generation",
        "schema",
        "session_ref",
    }
    introduced_projection_fields = {
        "audience": "projection-input",
        "decoder_ref": "projection-input",
        "depth": "projection-input",
        "device_class": "projection-input",
        "focus_ref": "projection-input",
        "generated_at": "projection-input",
        "loss": "constant",
        "mapping_manifest": "constant",
        "no_effect": "constant",
        "producer_ref": "projection-input",
        "producer_verification_required": "constant",
        "projection_hash": "derived",
        "projection_ref": "derived",
        "purpose": "projection-input",
        "register": "projection-input",
        "schema": "constant",
        "verification_scope": "constant",
    }
    field_mappings = (
        {
            f"/source/{source_field}->/projection/{projection_field}"
            for source_field, projection_fields in source_mappings.items()
            for projection_field in projection_fields
        }
        | {
            f"/{origin}/{projection_field}->/projection/{projection_field}"
            for projection_field, origin in introduced_projection_fields.items()
        }
        | {
            "/source/lifecycle_definition->/projection/position/lifecycle_definition",
            "/source/task_ref->/projection/position/task_ref",
        }
    )
    context_fact_fields = {field.alias or name for name, field in ContextFact.model_fields.items()}
    projected_fact_fields = {
        field.alias or name for name, field in ProjectedFact.model_fields.items()
    }
    shared_fact_fields = context_fact_fields & projected_fact_fields
    omitted_fact_fields = context_fact_fields - projected_fact_fields
    introduced_fact_fields = projected_fact_fields - context_fact_fields
    if omitted_fact_fields != {"air"} or introduced_fact_fields != {"projection_kind"}:
        raise RuntimeError("fact projection field coverage requires an explicit update")
    field_mappings |= {
        f"/source/facts/*/{field}->/projection/facts/*/{field}" for field in shared_fact_fields
    } | {
        f"/derived/projected-fact/{field}->/projection/facts/*/{field}"
        for field in introduced_fact_fields
    }
    event_fields = {field.alias or name for name, field in EpistemicFlowEvent.model_fields.items()}
    field_mappings |= {
        f"/source/events/*/{field}->/projection/events/*/{field}" for field in event_fields
    }
    nested_omissions = {
        "/source/air_bindings/*",
        *(f"/source/facts/*/{field}" for field in omitted_fact_fields),
    }
    omitted_field_paths = {
        *(f"/source/{field}" for field in source_omissions),
        *nested_omissions,
    }
    source_top_level = {
        f"/source/{field.alias or name}" for name, field in ContextFrame.model_fields.items()
    }
    covered_source_top_level = {
        mapping.split("->", 1)[0]
        for mapping in field_mappings
        if mapping.startswith("/source/") and mapping.split("->", 1)[0].count("/") == 2
    } | {path for path in omitted_field_paths if path.count("/") == 2}
    if covered_source_top_level != source_top_level:
        raise RuntimeError("projection mapping leaves source frame fields unclassified")
    projection_top_level = {
        f"/projection/{field.alias or name}"
        for name, field in ProjectionEnvelope.model_fields.items()
    }
    covered_projection_top_level = {
        mapping.split("->", 1)[1]
        for mapping in field_mappings
        if mapping.split("->", 1)[1].count("/") == 2
    }
    if covered_projection_top_level != projection_top_level:
        raise RuntimeError("projection mapping leaves projection fields without an origin")
    body = {
        "source_schema": "hapax.context-frame.v1",
        "projection_schema": "hapax.projection-envelope.v1",
        "field_mappings": tuple(sorted(field_mappings)),
        "omitted_field_paths": tuple(sorted(omitted_field_paths)),
        "transform_refs": tuple(
            sorted(
                (
                    "transform:audience-seal-before-derivation",
                    "transform:deny-omit-redact-marker",
                    "transform:typed-event-air-closure",
                    "transform:fact-air-to-audience-seal",
                    "transform:projection-local-graph",
                )
            )
        ),
        "reversibility": "partial",
        "no_effect": True,
        "may_authorize": False,
    }
    manifest_hash = _domain_hash("hapax.projection-mapping-manifest.v1", body)
    return ProjectionMappingManifest(
        **body,
        manifest_ref=f"projection-mapping@sha256:{manifest_hash}",
        manifest_hash=manifest_hash,
    )


def _projection_state(
    frame: ContextFrame,
    focus_ref: str,
    full_facts: tuple[ContextFact, ...],
) -> ContextState:
    focused = tuple(fact for fact in full_facts if focus_ref in {fact.fact_id, fact.subject_ref})
    considered = focused or full_facts
    if not considered:
        return ContextState(value_state="dark", reason_codes=("audience_context_unavailable",))
    if len(considered) == 1:
        return considered[0].state
    non_present = tuple(fact for fact in considered if fact.state.value_state != "present")
    if not non_present:
        return ContextState(value_state="present", reason_codes=())
    reasons = tuple(sorted({reason for fact in non_present for reason in fact.state.reason_codes}))
    return ContextState(value_state="partial", reason_codes=reasons or ("mixed_context_state",))


def _join_air_decisions(
    decisions: Sequence[Literal["allow", "redact", "deny"]],
) -> Literal["allow", "redact", "deny"]:
    if "deny" in decisions:
        return "deny"
    if "redact" in decisions:
        return "redact"
    return "allow"


def project_context_frame(
    frame: ContextFrame,
    *,
    audience: Literal["operator_private", "yard_context", "hapax_substrate", "public_or_air"],
    purpose: Literal["operation", "orientation", "lifecycle_possibility"],
    depth: Literal["immediate", "expanded", "inspectable", "raw"],
    device_class: Literal["monitor", "handheld", "compact", "accessible_linear"],
    register: Literal["plain", "labeled", "formal", "raw"],
    decoder_ref: str,
    focus_ref: str,
    producer_ref: str,
    generated_at: str,
    orientation_ref: str | None = None,
    lifecycle_possibility_ref: str | None = None,
) -> ProjectionEnvelope:
    """Build one deny-oblivious audience view from frame-bound carriers and policies."""

    if audience == "public_or_air":
        raise _canon_error(
            "public_projection_not_constituted",
            "retain DARK until a deny-oblivious public source receipt is constituted",
        )
    _validate_timestamp(generated_at, "generated_at")
    if generated_at < frame.checked_at or generated_at >= frame.stale_after:
        raise ValueError("projection generation must be checked_at <= generated_at < stale_after")
    air_by_key = {
        (binding.object_kind, binding.object_ref): getattr(binding.air, audience)
        for binding in frame.air_bindings
    }
    for key in (
        ("position", frame.position.position_ref),
        ("demand_shape", f"demand-shape@sha256:{frame.demand_shape.fingerprint}"),
    ):
        if air_by_key[key] != "allow":
            raise _canon_error(
                "projection_root_not_visible",
                "retain DARK until position and demand are allowed for this audience",
            )

    scope_decisions = {
        item.scope_ref: air_by_key[("scope", item.scope_ref)] for item in frame.scopes
    }
    while True:
        changed = False
        for item in frame.scopes:
            decision = _join_air_decisions(
                (
                    scope_decisions[item.scope_ref],
                    *(scope_decisions[ref] for ref in item.parent_scope_refs),
                )
            )
            if decision != scope_decisions[item.scope_ref]:
                scope_decisions[item.scope_ref] = decision
                changed = True
        if not changed:
            break
    temporal_decisions = {
        item.temporal_ref: air_by_key[("temporal", item.temporal_ref)]
        for item in frame.temporal_coordinates
    }
    while True:
        changed = False
        for item in frame.temporal_coordinates:
            decision = _join_air_decisions(
                (
                    temporal_decisions[item.temporal_ref],
                    *(
                        temporal_decisions[ref]
                        for ref in (*item.parent_span_refs, *item.correction_refs)
                        if ref in temporal_decisions
                    ),
                )
            )
            if decision != temporal_decisions[item.temporal_ref]:
                temporal_decisions[item.temporal_ref] = decision
                changed = True
        if not changed:
            break
    resolution_decisions = {
        item.resolution_ref: _join_air_decisions(
            (
                air_by_key[("resolution", item.resolution_ref)],
                scope_decisions[item.scope_ref],
                temporal_decisions[item.temporal_ref],
            )
        )
        for item in frame.resolution_coordinates
    }
    admission_decisions = {
        item.admission_ref: _join_air_decisions(
            (
                air_by_key[("source_admission", item.admission_ref)],
                scope_decisions[item.scope_ref],
                temporal_decisions[item.temporal_ref],
                resolution_decisions[item.resolution_ref],
            )
        )
        for item in frame.source_admissions
    }
    observation_decisions = {
        item.observation_ref: _join_air_decisions(
            (
                air_by_key[("observation", item.observation_ref)],
                admission_decisions[item.source_admission_ref],
                scope_decisions[item.scope_ref],
                temporal_decisions[item.temporal_ref],
                resolution_decisions[item.resolution_ref],
            )
        )
        for item in frame.observations
    }
    while True:
        changed = False
        for item in frame.observations:
            decision = _join_air_decisions(
                (
                    observation_decisions[item.observation_ref],
                    *(
                        observation_decisions[ref]
                        for ref in item.source_refs
                        if ref in observation_decisions
                    ),
                )
            )
            if decision != observation_decisions[item.observation_ref]:
                observation_decisions[item.observation_ref] = decision
                changed = True
        if not changed:
            break
    fact_decisions = {fact.fact_id: getattr(fact.air, audience) for fact in frame.facts}
    derivation_decisions = {
        item.derivation_ref: air_by_key[("derivation", item.derivation_ref)]
        for item in frame.derivations
    }
    while True:
        changed = False
        for item in frame.derivations:
            decision = _join_air_decisions(
                (
                    derivation_decisions[item.derivation_ref],
                    *(observation_decisions[ref] for ref in item.input_observation_refs),
                    *(fact_decisions[ref] for ref in item.input_fact_refs),
                )
            )
            if decision != derivation_decisions[item.derivation_ref]:
                derivation_decisions[item.derivation_ref] = decision
                changed = True
        for fact in frame.facts:
            dependency_refs = (
                *fact.provenance.source_refs,
                *fact.confidence.evidence_refs,
            )
            decision = _join_air_decisions(
                (
                    fact_decisions[fact.fact_id],
                    scope_decisions[fact.scope_ref],
                    temporal_decisions[fact.temporal_ref],
                    resolution_decisions[fact.resolution_ref],
                    derivation_decisions[fact.derivation_ref],
                    *(fact_decisions[ref] for ref in dependency_refs if ref in fact_decisions),
                    *(
                        observation_decisions[ref]
                        for ref in dependency_refs
                        if ref in observation_decisions
                    ),
                )
            )
            if decision != fact_decisions[fact.fact_id]:
                fact_decisions[fact.fact_id] = decision
                changed = True
        if not changed:
            break
    allowed_ids = {fact_id for fact_id, decision in fact_decisions.items() if decision == "allow"}
    redacted_ids = {fact_id for fact_id, decision in fact_decisions.items() if decision == "redact"}

    relation_decisions = {
        item.relation_id: _join_air_decisions(
            (
                air_by_key[("relation", item.relation_id)],
                fact_decisions[item.source_fact_ref],
                fact_decisions[item.target_fact_ref],
                *(fact_decisions[ref] for ref in item.provenance_refs if ref in fact_decisions),
                *(
                    observation_decisions[ref]
                    for ref in item.provenance_refs
                    if ref in observation_decisions
                ),
            )
        )
        for item in frame.relations
    }
    action_decisions = {
        item.action_id: _join_air_decisions(
            (
                air_by_key[("action", item.action_id)],
                *(fact_decisions[ref] for ref in item.source_fact_refs),
                *(
                    observation_decisions[ref]
                    for evidence in item.guard_evidence
                    for ref in evidence.evidence_refs
                    if ref in observation_decisions
                ),
            )
        )
        for item in frame.actions
    }
    impingement_decisions = {
        item.impingement_id: _join_air_decisions(
            (
                air_by_key[("impingement", item.impingement_id)],
                *(fact_decisions[ref] for ref in item.source_fact_refs),
                *(action_decisions[ref] for ref in item.legal_next),
            )
        )
        for item in frame.impingements
    }
    portal_decisions = {
        item.portal_ref: _join_air_decisions(
            (
                air_by_key[("portal", item.portal_ref)],
                *(fact_decisions[ref] for ref in item.source_fact_refs),
            )
        )
        for item in frame.portal_offers
    }
    if any(decision != "allow" for decision in impingement_decisions.values()) or any(
        decision != "allow" for decision in portal_decisions.values()
    ):
        raise _canon_error(
            "position_committed_context_not_visible",
            "retain DARK until every position-committed impingement and portal is visible",
        )
    estimate_decisions = {
        item.estimate_ref: _join_air_decisions(
            (
                air_by_key[("estimate", item.estimate_ref)],
                scope_decisions[item.scope_ref],
                temporal_decisions[item.temporal_ref],
                resolution_decisions[item.resolution_ref],
                derivation_decisions[item.derivation_ref],
                *(fact_decisions[ref] for ref in item.source_fact_refs),
            )
        )
        for item in frame.signal_estimates
    }
    while True:
        changed = False
        for item in frame.signal_estimates:
            decision = _join_air_decisions(
                (
                    estimate_decisions[item.estimate_ref],
                    *(
                        estimate_decisions[ref]
                        for ref in item.supersedes_refs
                        if ref in estimate_decisions
                    ),
                )
            )
            if decision != estimate_decisions[item.estimate_ref]:
                estimate_decisions[item.estimate_ref] = decision
                changed = True
        if not changed:
            break
    lens_decisions = {
        item.lens_ref: _join_air_decisions(
            (
                "allow" if item.audience == audience else "deny",
                air_by_key[("lens", item.lens_ref)],
                *(scope_decisions[ref] for ref in item.scope_selector_refs),
                *(resolution_decisions[ref] for ref in item.resolution_selector_refs),
                *(
                    fact_decisions[ref]
                    for ref in item.constraint_mask_refs
                    if ref in fact_decisions
                ),
                *(
                    action_decisions[ref]
                    for ref in item.constraint_mask_refs
                    if ref in action_decisions
                ),
                *(
                    impingement_decisions[ref]
                    for ref in item.constraint_mask_refs
                    if ref in impingement_decisions
                ),
            )
        )
        for item in frame.signal_lenses
    }
    constellation_decisions = {
        item.constellation_ref: _join_air_decisions(
            (
                air_by_key[("constellation", item.constellation_ref)],
                lens_decisions[item.lens_ref],
                scope_decisions[item.scope_ref],
                resolution_decisions[item.resolution_ref],
                fact_decisions[item.target_ref],
                *(estimate_decisions[ref] for ref in item.member_estimate_refs),
                *(relation_decisions[ref] for ref in item.relation_refs),
                *(admission_decisions[ref] for ref in item.uncovered_source_refs),
            )
        )
        for item in frame.signal_constellations
    }
    signal_decisions = {
        item.signal_id: _join_air_decisions(
            (
                air_by_key[("signal", item.signal_id)],
                *(fact_decisions[ref] for ref in item.source_fact_refs),
                *(estimate_decisions[ref] for ref in item.estimate_refs),
                *(
                    fact_decisions[ref]
                    for ref in _orientation_value_evidence_refs(item.value_vector)
                    if ref in fact_decisions
                ),
                *(
                    observation_decisions[ref]
                    for ref in _orientation_value_evidence_refs(item.value_vector)
                    if ref in observation_decisions
                ),
                *(
                    estimate_decisions[ref]
                    for ref in _orientation_value_evidence_refs(item.value_vector)
                    if ref in estimate_decisions
                ),
                lens_decisions[item.lens_ref],
                constellation_decisions[item.constellation_ref],
                *((portal_decisions[item.portal_ref],) if item.portal_ref is not None else ()),
            )
        )
        for item in frame.orienting_signals
    }
    learning_decisions = {
        item.learning_ref: _join_air_decisions(
            (
                air_by_key[("learning_receipt", item.learning_ref)],
                estimate_decisions[item.estimate_ref],
                constellation_decisions[item.constellation_ref],
                action_decisions[item.action_ref],
                *(
                    observation_decisions[ref]
                    for ref in item.witness_refs
                    if ref in observation_decisions
                ),
                *(fact_decisions[ref] for ref in item.witness_refs if ref in fact_decisions),
                *(
                    estimate_decisions[ref]
                    for ref in item.witness_refs
                    if ref in estimate_decisions
                ),
                *(action_decisions[ref] for ref in item.witness_refs if ref in action_decisions),
            )
        )
        for item in frame.signal_learning_receipts
    }
    while True:
        changed = False
        for item in frame.signal_learning_receipts:
            decision = _join_air_decisions(
                (
                    learning_decisions[item.learning_ref],
                    *(
                        learning_decisions[ref]
                        for ref in (*item.correction_refs, *item.supersedes_refs)
                        if ref in learning_decisions
                    ),
                )
            )
            if decision != learning_decisions[item.learning_ref]:
                learning_decisions[item.learning_ref] = decision
                changed = True
        if not changed:
            break

    event_id_by_ref = {event.event_ref: event.event_id for event in frame.events}
    event_source_decisions = {
        frame.position.position_ref: "allow",
        f"demand-shape@sha256:{frame.demand_shape.fingerprint}": "allow",
        **scope_decisions,
        **temporal_decisions,
        **resolution_decisions,
        **admission_decisions,
        **observation_decisions,
        **derivation_decisions,
        **fact_decisions,
        **relation_decisions,
        **action_decisions,
        **impingement_decisions,
        **estimate_decisions,
        **lens_decisions,
        **constellation_decisions,
        **{item.signal_ref: signal_decisions[item.signal_id] for item in frame.orienting_signals},
        **portal_decisions,
        **learning_decisions,
    }
    event_decisions = {
        event.event_id: _join_air_decisions(
            (
                air_by_key[("event", event.event_id)],
                scope_decisions[event.scope_ref],
                temporal_decisions[event.temporal_ref],
                resolution_decisions[event.resolution_ref],
                *(
                    event_source_decisions[ref]
                    for ref in event.source_refs
                    if ref in event_source_decisions
                ),
            )
        )
        for event in frame.events
    }
    while True:
        changed = False
        for event in frame.events:
            ancestry = (*event.caused_by, *event.supersedes_refs)
            decision = _join_air_decisions(
                (
                    event_decisions[event.event_id],
                    *(
                        event_decisions[event_id_by_ref[ref]]
                        for ref in ancestry
                        if ref in event_id_by_ref
                    ),
                )
            )
            if decision != event_decisions[event.event_id]:
                event_decisions[event.event_id] = decision
                changed = True
        if not changed:
            break

    orientation_decisions = {
        item.facet_id: _join_air_decisions(
            (
                air_by_key[("orientation", item.facet_id)],
                *(fact_decisions[ref] for ref in item.why_now_refs if ref in fact_decisions),
                *(action_decisions[ref] for ref in (*item.can, *item.cannot)),
                action_decisions[item.counterfactual.action_id],
            )
        )
        for item in frame.orientation_facets
    }
    lifecycle_decisions = {
        item.facet_id: _join_air_decisions(
            (
                air_by_key[("lifecycle_possibility", item.facet_id)],
                *(fact_decisions[ref] for ref in item.source_fact_refs),
                *(action_decisions[ref] for ref in item.lawful_next),
            )
        )
        for item in frame.lifecycle_possibilities
    }

    orientation: BoundaryOrientationFacet | None = None
    lifecycle_possibility: LifecyclePossibilityFacet | None = None
    selected_facet_decision: tuple[str, str, str] | None = None
    if purpose == "orientation":
        if orientation_ref is None or lifecycle_possibility_ref is not None:
            raise ValueError("orientation purpose requires exactly one orientation_ref")
        try:
            orientation = next(
                item for item in frame.orientation_facets if item.facet_ref == orientation_ref
            )
        except StopIteration as exc:
            raise ValueError("orientation_ref is not bound to the source frame") from exc
        if orientation_decisions[orientation.facet_id] != "allow":
            raise _canon_error(
                "orientation_not_visible",
                "retain DARK or select an orientation facet visible to this audience",
            )
        selected_facet_decision = ("orientation", orientation.facet_id, "allow")
    elif purpose == "lifecycle_possibility":
        if lifecycle_possibility_ref is None or orientation_ref is not None:
            raise ValueError(
                "lifecycle possibility purpose requires exactly one lifecycle_possibility_ref"
            )
        try:
            lifecycle_possibility = next(
                item
                for item in frame.lifecycle_possibilities
                if item.facet_ref == lifecycle_possibility_ref
            )
        except StopIteration as exc:
            raise ValueError("lifecycle possibility ref is not bound to the source frame") from exc
        if lifecycle_decisions[lifecycle_possibility.facet_id] != "allow":
            raise _canon_error(
                "lifecycle_possibility_not_visible",
                "retain DARK or select a lifecycle possibility visible to this audience",
            )
        selected_facet_decision = (
            "lifecycle_possibility",
            lifecycle_possibility.facet_id,
            "allow",
        )
    elif orientation_ref is not None or lifecycle_possibility_ref is not None:
        raise ValueError("operation purpose cannot select an orientation facet")

    scopes = tuple(item for item in frame.scopes if scope_decisions[item.scope_ref] == "allow")
    temporal_coordinates = tuple(
        item
        for item in frame.temporal_coordinates
        if temporal_decisions[item.temporal_ref] == "allow"
    )
    resolution_coordinates = tuple(
        item
        for item in frame.resolution_coordinates
        if resolution_decisions[item.resolution_ref] == "allow"
    )
    source_admissions = tuple(
        item
        for item in frame.source_admissions
        if admission_decisions[item.admission_ref] == "allow"
    )
    observations = tuple(
        item
        for item in frame.observations
        if observation_decisions[item.observation_ref] == "allow"
    )
    derivations = tuple(
        item for item in frame.derivations if derivation_decisions[item.derivation_ref] == "allow"
    )
    relations = tuple(
        item for item in frame.relations if relation_decisions[item.relation_id] == "allow"
    )
    actions = tuple(item for item in frame.actions if action_decisions[item.action_id] == "allow")
    impingements = tuple(frame.impingements)
    portals = tuple(frame.portal_offers)
    estimates = tuple(
        item for item in frame.signal_estimates if estimate_decisions[item.estimate_ref] == "allow"
    )
    lenses = tuple(item for item in frame.signal_lenses if lens_decisions[item.lens_ref] == "allow")
    constellations = tuple(
        item
        for item in frame.signal_constellations
        if constellation_decisions[item.constellation_ref] == "allow"
    )
    signals = tuple(
        item for item in frame.orienting_signals if signal_decisions[item.signal_id] == "allow"
    )
    learning_receipts = tuple(
        item
        for item in frame.signal_learning_receipts
        if learning_decisions[item.learning_ref] == "allow"
    )
    visible_events = tuple(
        item for item in frame.events if event_decisions[item.event_id] == "allow"
    )
    relation_ids = {item.relation_id for item in relations}
    action_ids = {item.action_id for item in actions}
    visible_supersession_refs = allowed_ids | set(frame.position.receipt_lineage)
    full_projected: list[ProjectedFact] = []
    raw_full: list[ContextFact] = []
    projected_facts: list[ProjectedFact | RedactedFact] = []
    for fact in frame.facts:
        if fact.fact_id in allowed_ids:
            raw_full.append(fact)
            projected = ProjectedFact(
                projection_kind="fact",
                fact_id=fact.fact_id,
                fact_type=fact.fact_type,
                subject_ref=fact.subject_ref,
                scope_ref=fact.scope_ref,
                temporal_ref=fact.temporal_ref,
                resolution_ref=fact.resolution_ref,
                derivation_ref=fact.derivation_ref,
                data=fact.data,
                unit=fact.unit,
                meaning=fact.meaning,
                implications=fact.implications,
                proves=fact.proves,
                does_not_prove=fact.does_not_prove,
                blind_spots=fact.blind_spots,
                provenance=fact.provenance,
                freshness_state=fact.freshness_state,
                confidence=fact.confidence,
                state=fact.state,
                relation_refs=tuple(ref for ref in fact.relation_refs if ref in relation_ids),
                legal_next=tuple(ref for ref in fact.legal_next if ref in action_ids),
                prohibited_next=tuple(ref for ref in fact.prohibited_next if ref in action_ids),
                expected_receipt_refs=tuple(
                    ref
                    for ref in fact.expected_receipt_refs
                    if ref in {action.expected_receipt_ref for action in actions}
                ),
                supersedes_refs=tuple(
                    ref for ref in fact.supersedes_refs if ref in visible_supersession_refs
                ),
                no_effect=True,
                may_authorize=False,
            )
            full_projected.append(projected)
            projected_facts.append(projected)
        elif fact.fact_id in redacted_ids:
            projected_facts.append(
                RedactedFact(
                    projection_kind="redacted",
                    fact_id=fact.fact_id,
                    state=ContextState(
                        value_state="dark", reason_codes=("audience_policy_redacted",)
                    ),
                    no_effect=True,
                    may_authorize=False,
                )
            )
    full_facts = tuple(raw_full)
    projection_stale_after = min(
        (
            frame.stale_after,
            *(
                fact.provenance.stale_after
                for fact in full_facts
                if fact.freshness_state in {"fresh", "aging"}
            ),
        )
    )
    if generated_at >= projection_stale_after:
        raise _canon_error(
            "projection_usable_fact_horizon_expired",
            "rebuild the frame from current fact provenance before projecting",
            projection_stale_after,
        )
    visible_focus_refs = allowed_ids | {fact.subject_ref for fact in full_facts}
    if focus_ref not in visible_focus_refs:
        raise ValueError("projection focus must resolve after the audience seal")
    meaning = tuple(sorted({fact.meaning for fact in full_facts})) or (
        "Context is unavailable under the active audience policy.",
    )
    implications = tuple(sorted({value for fact in full_facts for value in fact.implications})) or (
        "No semantic implication may be derived from unavailable context.",
    )
    blind_spots = tuple(sorted({value for fact in full_facts for value in fact.blind_spots})) or (
        "Audience-sealed context remains undisclosed.",
    )

    def redacted_object(kind: Any, object_id: str) -> RedactedContextObject:
        return RedactedContextObject(
            object_kind=kind,
            object_id=object_id,
            state=ContextState(value_state="dark", reason_codes=("audience_policy_redacted",)),
            no_effect=True,
            may_authorize=False,
        )

    redacted_objects = tuple(
        sorted(
            (
                *(
                    redacted_object("scope", item.scope_ref)
                    for item in frame.scopes
                    if scope_decisions[item.scope_ref] == "redact"
                ),
                *(
                    redacted_object("temporal", item.temporal_ref)
                    for item in frame.temporal_coordinates
                    if temporal_decisions[item.temporal_ref] == "redact"
                ),
                *(
                    redacted_object("resolution", item.resolution_ref)
                    for item in frame.resolution_coordinates
                    if resolution_decisions[item.resolution_ref] == "redact"
                ),
                *(
                    redacted_object("source_admission", item.admission_ref)
                    for item in frame.source_admissions
                    if admission_decisions[item.admission_ref] == "redact"
                ),
                *(
                    redacted_object("observation", item.observation_ref)
                    for item in frame.observations
                    if observation_decisions[item.observation_ref] == "redact"
                ),
                *(
                    redacted_object("derivation", item.derivation_ref)
                    for item in frame.derivations
                    if derivation_decisions[item.derivation_ref] == "redact"
                ),
                *(
                    redacted_object("relation", item.relation_id)
                    for item in frame.relations
                    if relation_decisions[item.relation_id] == "redact"
                ),
                *(
                    redacted_object("action", item.action_id)
                    for item in frame.actions
                    if action_decisions[item.action_id] == "redact"
                ),
                *(
                    redacted_object("estimate", item.estimate_ref)
                    for item in frame.signal_estimates
                    if estimate_decisions[item.estimate_ref] == "redact"
                ),
                *(
                    redacted_object("lens", item.lens_ref)
                    for item in frame.signal_lenses
                    if lens_decisions[item.lens_ref] == "redact"
                ),
                *(
                    redacted_object("constellation", item.constellation_ref)
                    for item in frame.signal_constellations
                    if constellation_decisions[item.constellation_ref] == "redact"
                ),
                *(
                    redacted_object("signal", item.signal_id)
                    for item in frame.orienting_signals
                    if signal_decisions[item.signal_id] == "redact"
                ),
                *(
                    redacted_object("learning_receipt", item.learning_ref)
                    for item in frame.signal_learning_receipts
                    if learning_decisions[item.learning_ref] == "redact"
                ),
                *(
                    redacted_object("event", item.event_id)
                    for item in frame.events
                    if event_decisions[item.event_id] == "redact"
                ),
            ),
            key=lambda item: (item.object_kind, item.object_id),
        )
    )
    mapping_manifest = build_projection_mapping_manifest()
    loss = ProjectionLoss(
        state="partial",
        manifest_ref=mapping_manifest.manifest_ref,
        manifest_hash=mapping_manifest.manifest_hash,
        reason_codes=("audience_sealed_partial_view",),
    )
    visible_policy_decisions = tuple(
        sorted(
            (
                ("position", "root", "allow"),
                ("demand_shape", "root", "allow"),
                *(
                    ("scope", object_id, decision)
                    for object_id, decision in scope_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("temporal", object_id, decision)
                    for object_id, decision in temporal_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("resolution", object_id, decision)
                    for object_id, decision in resolution_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("source_admission", object_id, decision)
                    for object_id, decision in admission_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("observation", object_id, decision)
                    for object_id, decision in observation_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("derivation", object_id, decision)
                    for object_id, decision in derivation_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("fact", fact_id, decision)
                    for fact_id, decision in fact_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("relation", object_id, decision)
                    for object_id, decision in relation_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("action", object_id, decision)
                    for object_id, decision in action_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("impingement", object_id, decision)
                    for object_id, decision in impingement_decisions.items()
                ),
                *(
                    ("estimate", object_id, decision)
                    for object_id, decision in estimate_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("lens", object_id, decision)
                    for object_id, decision in lens_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("constellation", object_id, decision)
                    for object_id, decision in constellation_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("portal", object_id, decision)
                    for object_id, decision in portal_decisions.items()
                ),
                *(
                    ("signal", object_id, decision)
                    for object_id, decision in signal_decisions.items()
                    if decision != "deny"
                ),
                *(
                    ("learning_receipt", object_id, decision)
                    for object_id, decision in learning_decisions.items()
                    if decision != "deny"
                ),
                *(
                    (
                        "event",
                        (
                            next(
                                event.event_ref
                                for event in frame.events
                                if event.event_id == object_id
                            )
                            if decision == "allow"
                            else object_id
                        ),
                        decision,
                    )
                    for object_id, decision in event_decisions.items()
                    if decision != "deny"
                ),
                *((selected_facet_decision,) if selected_facet_decision is not None else ()),
            )
        )
    )
    policy_digest = _domain_hash(
        "hapax.projection.audience-policy.v1",
        {"audience": audience, "visible_decisions": visible_policy_decisions},
    )
    body = {
        "schema": "hapax.projection-envelope.v1",
        "position": frame.position,
        "demand_shape": frame.demand_shape,
        "audience": audience,
        "purpose": purpose,
        "depth": depth,
        "device_class": device_class,
        "register": register,
        "decoder_ref": decoder_ref,
        "focus_ref": focus_ref,
        "state": _projection_state(frame, focus_ref, full_facts),
        "meaning": meaning,
        "implications": implications,
        "blind_spots": blind_spots,
        "scopes": scopes,
        "temporal_coordinates": temporal_coordinates,
        "resolution_coordinates": resolution_coordinates,
        "source_admissions": source_admissions,
        "observations": observations,
        "derivations": derivations,
        "events": visible_events,
        "facts": tuple(sorted(projected_facts, key=lambda item: item.fact_id)),
        "redacted_objects": redacted_objects,
        "relations": relations,
        "actions": actions,
        "impingements": impingements,
        "signal_estimates": estimates,
        "signal_lenses": lenses,
        "signal_constellations": constellations,
        "orienting_signals": signals,
        "portal_offers": portals,
        "signal_learning_receipts": learning_receipts,
        "legal_next": tuple(
            sorted(item.action_id for item in actions if item.disposition == "legal")
        ),
        "prohibited_next": tuple(
            sorted(item.action_id for item in actions if item.disposition != "legal")
        ),
        "lineage_refs": tuple(
            dict.fromkeys(
                (
                    *frame.position.receipt_lineage,
                    *(item.event_ref for item in visible_events),
                )
            )
        ),
        "supersedes_refs": tuple(
            sorted({value for fact in full_projected for value in fact.supersedes_refs})
        ),
        "producer_ref": producer_ref,
        "verification_scope": "structure_and_content_address_only",
        "producer_verification_required": True,
        "generated_at": generated_at,
        "stale_after": projection_stale_after,
        "audience_policy_digest": policy_digest,
        "mapping_manifest": mapping_manifest,
        "loss": loss,
        "orientation": orientation,
        "lifecycle_possibility": lifecycle_possibility,
        "no_effect": True,
        "may_authorize": False,
    }
    projection_hash = _domain_hash("hapax.projection-envelope.v1", body)
    return ProjectionEnvelope(
        **body,
        projection_ref=f"projection-envelope@sha256:{projection_hash}",
        projection_hash=projection_hash,
    )


def verify_projection(frame: ContextFrame, projection: ProjectionEnvelope) -> ProjectionEnvelope:
    """Rebuild an audience projection from its frame; schema validity alone is insufficient."""

    rebuilt = project_context_frame(
        frame,
        audience=projection.audience,
        purpose=projection.purpose,
        depth=projection.depth,
        device_class=projection.device_class,
        register=projection.register_mode,
        decoder_ref=projection.decoder_ref,
        focus_ref=projection.focus_ref,
        producer_ref=projection.producer_ref,
        generated_at=projection.generated_at,
        orientation_ref=(
            projection.orientation.facet_ref if projection.orientation is not None else None
        ),
        lifecycle_possibility_ref=(
            projection.lifecycle_possibility.facet_ref
            if projection.lifecycle_possibility is not None
            else None
        ),
    )
    if rebuilt != projection:
        raise ValueError("projection is not the deterministic audience seal of its frame")
    return rebuilt


def context_bundle_json_bytes(bundle: ContextBundleWire) -> bytes:
    """Return the exact canonical JSON bytes for the locked external wire."""

    return canonical_json_bytes(bundle)


def context_bundle_digest(bundle: ContextBundleWire) -> str:
    """Content identity for one exact context_bundle wire instance."""

    return _sha256(context_bundle_json_bytes(bundle))


_V1_OMITTED_FIELD_PATHS = tuple(
    sorted(
        {
            *(f"/frame/{field.alias or name}" for name, field in ContextFrame.model_fields.items()),
            *(
                f"/projections/*/{field.alias or name}"
                for name, field in ProjectionEnvelope.model_fields.items()
            ),
        }
    )
)

_V1_COMPATIBILITY_REASON_CODES = (
    "hold_no_live_actions",
    "locked_v1_has_no_rich_context_fields",
    "operator_private_compatibility_only",
    "semantic_loss_manifest_attached",
)


def _context_bundle_projection_summary(projection: ProjectionEnvelope) -> str:
    legal = ",".join(projection.legal_next) or "none"
    meaning = " | ".join(projection.meaning)
    return (
        f"state={projection.state.value_state}; focus={projection.focus_ref}; "
        f"meaning={meaning}; legal_next={legal}"
    )


def _projected_lifecycle_fsm(projection: ProjectionEnvelope) -> dict[str, str]:
    fact = next(
        item
        for item in projection.facts
        if isinstance(item, ProjectedFact) and item.fact_type == "lifecycle_fsm"
    )
    payload = json.loads(fact.data.canonical_json)
    return {key: payload[key] for key in ("what", "how", "must")}


def project_context_bundle_v1(
    frame: ContextFrame,
    *,
    operator_private: ProjectionEnvelope,
    yard_context: ProjectionEnvelope,
    hapax_substrate: ProjectionEnvelope,
) -> ContextBundleCompatibilityProjection:
    """Derive the locked seven-field wire only from three verified same-frame projections."""

    projections = (operator_private, yard_context, hapax_substrate)
    expected_audiences = ("operator_private", "yard_context", "hapax_substrate")
    for projection, expected_audience in zip(projections, expected_audiences, strict=True):
        verify_projection(frame, projection)
        if projection.audience != expected_audience:
            raise ValueError("v1 compatibility projections must use the named audience order")
    if len({projection.position.position_ref for projection in projections}) != 1:
        raise ValueError("v1 compatibility projections must share one position")
    if len({projection.demand_shape.fingerprint for projection in projections}) != 1:
        raise ValueError("v1 compatibility projections must share one demand shape")
    if len({projection.purpose for projection in projections}) != 1:
        raise ValueError("v1 compatibility projections must share one purpose")
    projected_fsms = tuple(_projected_lifecycle_fsm(projection) for projection in projections)
    if len({canonical_json_bytes(item) for item in projected_fsms}) != 1:
        raise ValueError("v1 compatibility projections must share exact WHAT/HOW/MUST")
    descriptor = operator_private.demand_shape.descriptor
    if descriptor is None:
        raise ValueError("v1 compatibility requires a complete projected demand descriptor")
    if any(projection.state.value_state in {"dark", "absent"} for projection in projections):
        freshness: Literal["live", "stale", "dark"] = "dark"
    elif any(
        projection.state.value_state == "stale" or projection.generated_at >= projection.stale_after
        for projection in projections
    ):
        freshness = "stale"
    else:
        freshness = "live"
    common_impingements = tuple(
        item
        for item in operator_private.impingements
        if item in yard_context.impingements and item in hapax_substrate.impingements
    )
    common_signals = tuple(
        item
        for item in operator_private.orienting_signals
        if item in yard_context.orienting_signals and item in hapax_substrate.orienting_signals
    )
    projection_set_body = {
        "operator_private": operator_private.projection_ref,
        "yard_context": yard_context.projection_ref,
        "hapax_substrate": hapax_substrate.projection_ref,
    }
    projection_set_hash = _domain_hash("hapax.tri-audience-projection-set.v1", projection_set_body)
    wire = ContextBundleWire(
        kind="context_bundle",
        session_ref=descriptor.session_ref,
        task_ref=operator_private.position.task_ref,
        strata=ContextBundleStrata(
            fsm=ContextBundleFsm(**projected_fsms[0]),
            impingements=tuple(
                ContextBundleImpingement(
                    kind=item.kind,
                    summary=item.summary,
                    source_ref=item.source_fact_refs[0],
                )
                for item in common_impingements
            ),
            orienting_signals=tuple(
                ContextBundleOrientingSignal(
                    kind=item.kind,
                    label=item.label,
                    portal_ref=item.portal_ref,
                )
                for item in common_signals
                if item.portal_ref is not None
            ),
        ),
        tri_audience=ContextBundleTriAudience(
            operator=_context_bundle_projection_summary(operator_private),
            crow=_context_bundle_projection_summary(yard_context),
            hapax=_context_bundle_projection_summary(hapax_substrate),
        ),
        provenance=ContextBundleProvenance(
            source=f"projection-set@sha256:{projection_set_hash}",
            observed_at=max(projection.generated_at for projection in projections),
            freshness=freshness,
        ),
        demand_shape_fingerprint=operator_private.demand_shape.fingerprint,
    )
    body = {
        "schema": "hapax.context-bundle-v1-compatibility.v1",
        "source_frame_ref": frame.frame_ref,
        "source_frame_hash": frame.frame_hash,
        "source_projection_refs": TriAudienceProjectionRefs(
            operator_private=operator_private.projection_ref,
            yard_context=yard_context.projection_ref,
            hapax_substrate=hapax_substrate.projection_ref,
        ),
        "audience": "operator_private",
        "state": "hold",
        "compatibility_only": True,
        "wire_contract_sha256": LOCKED_CONTEXT_BUNDLE_CONTRACT_SHA256,
        "wire": wire,
        "wire_digest": context_bundle_digest(wire),
        "omitted_field_paths": _V1_OMITTED_FIELD_PATHS,
        "omission_digest": _domain_hash(
            "hapax.context-bundle-v1.omissions.v1", _V1_OMITTED_FIELD_PATHS
        ),
        "loss_state": "partial",
        "reason_codes": _V1_COMPATIBILITY_REASON_CODES,
        "may_authorize": False,
    }
    compatibility_hash = _domain_hash("hapax.context-bundle-v1-compatibility.v1", body)
    return ContextBundleCompatibilityProjection(
        **body,
        compatibility_ref=f"context-bundle-compatibility@sha256:{compatibility_hash}",
        compatibility_hash=compatibility_hash,
    )


def verify_context_bundle_v1(
    frame: ContextFrame,
    compatibility: ContextBundleCompatibilityProjection,
    *,
    operator_private: ProjectionEnvelope,
    yard_context: ProjectionEnvelope,
    hapax_substrate: ProjectionEnvelope,
) -> ContextBundleCompatibilityProjection:
    """Rebuild the compatibility wrapper and its complete declared loss receipt."""

    rebuilt = project_context_bundle_v1(
        frame,
        operator_private=operator_private,
        yard_context=yard_context,
        hapax_substrate=hapax_substrate,
    )
    if rebuilt != compatibility:
        raise ValueError("context_bundle v1 wrapper is not derived from its rich source frame")
    return rebuilt
