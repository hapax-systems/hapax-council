from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import tomllib
from pathlib import Path
from types import MappingProxyType
from typing import get_args
from urllib.parse import urlsplit

import hapax.context_canon as context_canon_package
import jsonschema
import pytest
import toon
from pydantic import ValidationError

import shared.session_context_canon as canon_module
from shared.compression.registry import load_registry
from shared.coord_projection import NO_GO_BOOLEANS
from shared.sdlc_lifecycle import SDLC_STAGE_METADATA, SDLC_STAGE_METADATA_PATH
from shared.session_context_canon import (
    _REQUIRED_GROUNDING_IDS_V1,
    _REQUIRED_MUST_IDS_V1,
    CANON_BUNDLE_SCHEMA,
    CANON_IMAGE_SCHEMA,
    CANON_SCHEMA_PATH,
    CANON_SOURCE_PATH,
    LOCKED_CONTEXT_BUNDLE_CONTRACT_SHA256,
    TLA_PATH,
    AuthorizationFlag,
    BoundaryOrientationFacet,
    CanonBundle,
    CanonError,
    CanonicalDecimal,
    ContextAction,
    ContextAirBinding,
    ContextAirPolicy,
    ContextConfidence,
    ContextFact,
    ContextFrame,
    ContextImpingement,
    ContextProvenance,
    ContextRelation,
    ContextState,
    CounterfactualFacet,
    DemandShapeBinding,
    LifecycleGuardEvidence,
    LifecyclePossibilityFacet,
    OrientationValueVector,
    PortalOffer,
    ProjectedFact,
    ProjectionEnvelope,
    ProjectionLevel,
    SignalValueAxis,
    _domain_hash,
    _required_grounding_content,
    build_boundary_orientation_facet,
    build_canon_bundle,
    build_canonical_json_object,
    build_context_frame,
    build_context_position,
    build_context_scope,
    build_corpus,
    build_demand_shape_descriptor,
    build_derivation_record,
    build_epistemic_flow_event,
    build_lifecycle_fsm_fact,
    build_lifecycle_possibility_facet,
    build_observation_envelope,
    build_orienting_signal,
    build_projection_mapping_manifest,
    build_resolution_coordinate,
    build_signal_constellation,
    build_signal_estimate,
    build_signal_learning_receipt,
    build_signal_lens,
    build_source_admission,
    build_temporal_coordinate,
    bundle_json_schema_bytes,
    canonical_json_bytes,
    checked_bundle_json_schema_bytes,
    context_bundle_digest,
    context_bundle_fsm,
    context_bundle_json_bytes,
    forward_cone,
    lifecycle_operation_admission_ref,
    lifecycle_transition_admission_ref,
    load_canon_source,
    load_materialized_bundle,
    materialize_bundle,
    project_canon,
    project_context_bundle_v1,
    project_context_frame,
    verify_context_bundle_v1,
    verify_projection,
    verify_tla_topology,
)


@pytest.fixture(scope="module")
def corpus():
    return build_corpus(
        load_canon_source(),
        compression_registry=load_registry(),
    )


@pytest.fixture(scope="module")
def bundle() -> CanonBundle:
    return build_canon_bundle()


@pytest.fixture(scope="module")
def rich_context(bundle: CanonBundle) -> dict[str, object]:
    image = _image(bundle, "S6", "pi2")
    lifecycle_stage = next(
        stage for stage in bundle.lifecycle_definition.stages if stage.token == image.stage_token
    )
    descriptor = build_demand_shape_descriptor(
        session_ref="session:test",
        strategy={"mode": "contextual", "purpose": "orientation"},
        strata={
            "how": image.rendered_strata.how,
            "must": image.rendered_strata.must,
            "what": image.rendered_strata.what,
        },
        canon={
            "bundle_hash": bundle.bundle_hash,
            "bundle_ref": bundle.bundle_ref,
            "canon_id": image.canon_id,
            "image_hash": image.image_hash,
            "level": image.level.value,
            "version": image.canon_version,
        },
        position_basis={
            "legal_successors": tuple(
                sorted({edge.to for edge in (*lifecycle_stage.next, *lifecycle_stage.fall)})
            ),
            "lifecycle_definition_hash": bundle.lifecycle_definition.definition_hash,
            "lifecycle_definition_ref": bundle.lifecycle_definition.definition_ref,
            "stage_token": image.stage_token,
        },
        offered_affordances=("action:inspect", "action:execute"),
        provenance_generation="provenance:g1",
        policy_generation="policy:g1",
        audience_policy={"generation": "audience:g1"},
        kernel={"omitted_digest": image.kernel.omitted_digest},
        budget={"reference_tokens": image.reference_token_count},
    )
    demand = DemandShapeBinding(
        fingerprint=descriptor.demand_shape_fingerprint,
        descriptor=descriptor,
        state=ContextState(value_state="present", reason_codes=()),
        may_authorize=False,
    )

    estate_scope = build_context_scope(
        scope_id="scope:estate",
        scope_type_ref="scope-type:estate",
        subject_refs=("estate:appendix",),
        parent_scope_refs=(),
        environment_ref="environment:appendix",
        lifecycle_scope_ref=bundle.lifecycle_definition.lifecycle_ref,
    )
    task_scope = build_context_scope(
        scope_id="scope:task-rich",
        scope_type_ref="scope-type:task",
        subject_refs=("session:test", "task:rich"),
        parent_scope_refs=(estate_scope.scope_ref,),
        environment_ref="environment:appendix",
        lifecycle_scope_ref=bundle.lifecycle_definition.lifecycle_ref,
    )
    data_temporal = build_temporal_coordinate(
        clock_domain="clock:utc",
        event_time_start="2026-07-10T16:00:00Z",
        event_time_end="2026-07-10T16:00:00Z",
        processing_time="2026-07-10T16:01:00Z",
        valid_from="2026-07-10T16:00:00Z",
        valid_until="2026-07-10T18:00:00Z",
        window_ref="window:fixture-observation",
        scale_ref="scale:task-observation",
        tense="impression",
        watermark="2026-07-10T16:00:00Z",
        completeness=ContextState(value_state="present", reason_codes=()),
        lateness="on_time",
        parent_span_refs=(),
        correction_refs=(),
        forecast_horizon_ref=None,
    )
    observation_event_temporal = build_temporal_coordinate(
        clock_domain="clock:utc",
        event_time_start="2026-07-10T16:02:00Z",
        event_time_end="2026-07-10T16:02:00Z",
        processing_time="2026-07-10T16:02:01Z",
        valid_from="2026-07-10T16:02:00Z",
        valid_until="2026-07-10T18:00:00Z",
        window_ref="window:event-observation",
        scale_ref="scale:event",
        tense="impression",
        watermark="2026-07-10T16:02:00Z",
        completeness=ContextState(value_state="present", reason_codes=()),
        lateness="on_time",
        parent_span_refs=(data_temporal.temporal_ref,),
        correction_refs=(),
        forecast_horizon_ref=None,
    )
    derivation_event_temporal = build_temporal_coordinate(
        clock_domain="clock:utc",
        event_time_start="2026-07-10T16:03:00Z",
        event_time_end="2026-07-10T16:03:00Z",
        processing_time="2026-07-10T16:03:01Z",
        valid_from="2026-07-10T16:03:00Z",
        valid_until="2026-07-10T18:00:00Z",
        window_ref="window:event-derivation",
        scale_ref="scale:event",
        tense="impression",
        watermark="2026-07-10T16:03:00Z",
        completeness=ContextState(value_state="present", reason_codes=()),
        lateness="on_time",
        parent_span_refs=(data_temporal.temporal_ref,),
        correction_refs=(),
        forecast_horizon_ref=None,
    )
    data_resolution = build_resolution_coordinate(
        scope_ref=task_scope.scope_ref,
        temporal_ref=data_temporal.temporal_ref,
        subject_resolution_ref="subject-resolution:task",
        lifecycle_resolution_ref="lifecycle-resolution:slice",
        semantic_resolution_ref="semantic-resolution:fact",
        environment_resolution_ref="environment-resolution:host",
        aggregation_ref="aggregation:identity",
    )
    observation_event_resolution = build_resolution_coordinate(
        scope_ref=task_scope.scope_ref,
        temporal_ref=observation_event_temporal.temporal_ref,
        subject_resolution_ref="subject-resolution:event",
        lifecycle_resolution_ref="lifecycle-resolution:slice",
        semantic_resolution_ref="semantic-resolution:event",
        environment_resolution_ref="environment-resolution:host",
        aggregation_ref="aggregation:identity",
    )
    derivation_event_resolution = build_resolution_coordinate(
        scope_ref=task_scope.scope_ref,
        temporal_ref=derivation_event_temporal.temporal_ref,
        subject_resolution_ref="subject-resolution:event",
        lifecycle_resolution_ref="lifecycle-resolution:slice",
        semantic_resolution_ref="semantic-resolution:event",
        environment_resolution_ref="environment-resolution:host",
        aggregation_ref="aggregation:identity",
    )
    source_common = {
        "scope_ref": task_scope.scope_ref,
        "temporal_ref": data_temporal.temporal_ref,
        "resolution_ref": data_resolution.resolution_ref,
        "schema_ref": "schema:fixture-source-v1",
        "unit_semantics_ref": "semantics:fixture",
        "join_keys": ("session_ref", "task_ref"),
        "producer_ref": "producer:deterministic",
        "method_ref": "method:fixture",
        "verification_refs": ("receipt:source-verified",),
        "policy_refs": ("policy:fixture",),
        "consumer_contract_refs": ("consumer:context-frame",),
        "availability": ContextState(value_state="present", reason_codes=()),
        "freshness_state": "fresh",
        "cost": build_canonical_json_object({"class": "local"}),
        "latency": build_canonical_json_object({"class": "bounded"}),
        "probe_witness_refs": ("receipt:source-verified",),
    }
    constitutional_source = build_source_admission(
        admission_id="source-admission:constitution",
        source_ref="source:constitution",
        source_kind="constitutional_source",
        authority_ceiling="constitutional_evidence",
        supported_provenance_kinds=("constitutional",),
        **source_common,
    )
    observed_source = build_source_admission(
        admission_id="source-admission:estate",
        source_ref="source:estate-observation",
        source_kind="estate_observation",
        authority_ceiling="observation_only",
        supported_provenance_kinds=("observed",),
        **source_common,
    )
    private_source = build_source_admission(
        admission_id="source-admission:private-canary",
        source_ref="source:private-canary",
        source_kind="test_canary",
        authority_ceiling="observation_only",
        supported_provenance_kinds=("observed",),
        **source_common,
    )
    constitutional_observation = build_observation_envelope(
        observation_id="observation:constitution",
        source_admission_ref=constitutional_source.admission_ref,
        scope_ref=task_scope.scope_ref,
        temporal_ref=data_temporal.temporal_ref,
        resolution_ref=data_resolution.resolution_ref,
        subject_ref=bundle.lifecycle_definition.lifecycle_ref,
        payload={"source": "verified-canon"},
        producer_ref="producer:deterministic",
        method_ref="method:source-verification",
        config_ref="config:canon",
        authority_ceiling="constitutional_evidence",
        witness_refs=("receipt:source-verified",),
        source_refs=("receipt:authority",),
        state=ContextState(value_state="present", reason_codes=()),
    )
    estate_observation = build_observation_envelope(
        observation_id="observation:estate-gap",
        source_admission_ref=observed_source.admission_ref,
        scope_ref=task_scope.scope_ref,
        temporal_ref=data_temporal.temporal_ref,
        resolution_ref=data_resolution.resolution_ref,
        subject_ref="capability:execution",
        payload={"measurement": "missing"},
        producer_ref="producer:observer",
        method_ref="method:deterministic",
        config_ref="config:observer",
        authority_ceiling="observation_only",
        witness_refs=("receipt:observation",),
        source_refs=("receipt:authority",),
        state=ContextState(value_state="present", reason_codes=()),
    )
    private_observation = build_observation_envelope(
        observation_id="observation:private-canary",
        source_admission_ref=private_source.admission_ref,
        scope_ref=task_scope.scope_ref,
        temporal_ref=data_temporal.temporal_ref,
        resolution_ref=data_resolution.resolution_ref,
        subject_ref="private:canary",
        payload={"secret": "canary-a"},
        producer_ref="producer:observer",
        method_ref="method:deterministic",
        config_ref="config:observer",
        authority_ceiling="observation_only",
        witness_refs=("receipt:private-canary",),
        source_refs=("receipt:authority",),
        state=ContextState(value_state="present", reason_codes=()),
    )
    lifecycle_derivation = build_derivation_record(
        derivation_id="derivation:lifecycle",
        input_observation_refs=(constitutional_observation.observation_ref,),
        input_fact_refs=(),
        output_refs=(f"fact:lifecycle-fsm:{image.image_hash}",),
        method_ref="method:canon-materializer",
        method_version_ref="version:1",
        calibration_ref=None,
        calibration_metric=None,
        validity_domain_refs=(),
        distribution_state="not_applicable",
        abstained=False,
        air_policy_generation="audience:g1",
        state=ContextState(value_state="present", reason_codes=()),
    )
    position_derivation = build_derivation_record(
        derivation_id="derivation:position",
        input_observation_refs=(constitutional_observation.observation_ref,),
        input_fact_refs=(),
        output_refs=("fact:position",),
        method_ref="method:position-materializer",
        method_version_ref="version:1",
        calibration_ref=None,
        calibration_metric=None,
        validity_domain_refs=(),
        distribution_state="not_applicable",
        abstained=False,
        air_policy_generation="audience:g1",
        state=ContextState(value_state="present", reason_codes=()),
    )
    gap_derivation = build_derivation_record(
        derivation_id="derivation:gap",
        input_observation_refs=(estate_observation.observation_ref,),
        input_fact_refs=(),
        output_refs=("estimate:evidence-gap", "fact:capability-gap"),
        method_ref="method:gap-rule",
        method_version_ref="version:1",
        calibration_ref=None,
        calibration_metric=None,
        validity_domain_refs=(),
        distribution_state="not_applicable",
        abstained=False,
        air_policy_generation="audience:g1",
        state=ContextState(value_state="present", reason_codes=()),
    )
    private_derivation = build_derivation_record(
        derivation_id="derivation:private-canary",
        input_observation_refs=(private_observation.observation_ref,),
        input_fact_refs=(),
        output_refs=("fact:private-canary",),
        method_ref="method:canary",
        method_version_ref="version:1",
        calibration_ref=None,
        calibration_metric=None,
        validity_domain_refs=(),
        distribution_state="not_applicable",
        abstained=False,
        air_policy_generation="audience:g1",
        state=ContextState(value_state="present", reason_codes=()),
    )

    constitutional_provenance = ContextProvenance(
        kind="constitutional",
        source_refs=(constitutional_observation.observation_ref,),
        producer_ref="producer:deterministic",
        derivation="asserted",
        authority_level="authoritative",
        generation="g1",
        policy_generation="policy:g1",
        observed_at="2026-07-10T16:00:00Z",
        produced_at="2026-07-10T16:01:00Z",
        stale_after="2026-07-10T18:00:00Z",
    )
    observed_provenance = ContextProvenance(
        kind="observed",
        source_refs=(estate_observation.observation_ref,),
        producer_ref="producer:observer",
        derivation="extracted",
        authority_level="support_non_authoritative",
        generation="g1",
        policy_generation="policy:g1",
        observed_at="2026-07-10T16:00:00Z",
        produced_at="2026-07-10T16:01:00Z",
        stale_after="2026-07-10T18:00:00Z",
    )
    confidence = ContextConfidence(
        word="high",
        method="deterministic",
        evidence_refs=(estate_observation.observation_ref,),
        calibration_ref=None,
        calibration_metric=None,
        validity_domain_refs=(),
        distribution_state="not_applicable",
        abstained=False,
    )
    constitutional_confidence = confidence.model_copy(
        update={"evidence_refs": (constitutional_observation.observation_ref,)}
    )
    private_confidence = confidence.model_copy(
        update={"evidence_refs": (private_observation.observation_ref,)}
    )
    allow_all = ContextAirPolicy(
        operator_private="allow",
        yard_context="allow",
        hapax_substrate="allow",
        public_or_air="allow",
        derived_channel_sealed=True,
    )
    canary_air = ContextAirPolicy(
        operator_private="allow",
        yard_context="deny",
        hapax_substrate="redact",
        public_or_air="deny",
        derived_channel_sealed=True,
    )
    operator_signal_air = ContextAirPolicy(
        operator_private="allow",
        yard_context="redact",
        hapax_substrate="deny",
        public_or_air="deny",
        derived_channel_sealed=True,
    )
    common_receipts = ("receipt:execute", "receipt:inspect")
    lifecycle_fact = build_lifecycle_fsm_fact(
        bundle.lifecycle_definition,
        image,
        air=allow_all,
        scope_ref=task_scope.scope_ref,
        temporal_ref=data_temporal.temporal_ref,
        resolution_ref=data_resolution.resolution_ref,
        derivation_ref=lifecycle_derivation.derivation_ref,
        evidence_refs=(constitutional_observation.observation_ref,),
        observed_at="2026-07-10T16:00:00Z",
        produced_at="2026-07-10T16:05:00Z",
        stale_after="2026-07-10T18:00:00Z",
        policy_generation="audience:g1",
    )
    facts = (
        lifecycle_fact,
        ContextFact(
            fact_id="fact:capability-gap",
            fact_type="capability_gap",
            subject_ref="capability:execution",
            scope_ref=task_scope.scope_ref,
            temporal_ref=data_temporal.temporal_ref,
            resolution_ref=data_resolution.resolution_ref,
            derivation_ref=gap_derivation.derivation_ref,
            data=build_canonical_json_object({}),
            unit=None,
            meaning="Execution capability is held pending independent evidence.",
            implications=("Inspection remains legal while execution remains unavailable.",),
            proves=(),
            does_not_prove=("The capability is unsafe or permanently unavailable.",),
            blind_spots=("No fresh bounded execution measurement is present.",),
            provenance=observed_provenance,
            freshness_state="hold",
            confidence=confidence,
            air=allow_all,
            state=ContextState(
                value_state="hold", reason_codes=("independent_measurement_missing",)
            ),
            relation_refs=("relation:position-gap",),
            legal_next=(),
            prohibited_next=("action:execute",),
            expected_receipt_refs=("receipt:execute",),
            supersedes_refs=(),
            no_effect=True,
            may_authorize=False,
        ),
        ContextFact(
            fact_id="fact:position",
            fact_type="lifecycle_position",
            subject_ref="task:rich",
            scope_ref=task_scope.scope_ref,
            temporal_ref=data_temporal.temporal_ref,
            resolution_ref=data_resolution.resolution_ref,
            derivation_ref=position_derivation.derivation_ref,
            data=build_canonical_json_object({"stage": "S6"}),
            unit=None,
            meaning="The task is at implementation with scoped mutation only.",
            implications=("Every protected action must preserve the S6 position binding.",),
            proves=("The current lifecycle token is S6.",),
            does_not_prove=("Any execution lease has been issued.",),
            blind_spots=("Runtime outcome evidence is not yet due at S6.",),
            provenance=constitutional_provenance,
            freshness_state="fresh",
            confidence=constitutional_confidence,
            air=allow_all,
            state=ContextState(value_state="present", reason_codes=()),
            relation_refs=("relation:position-gap",),
            legal_next=("action:inspect",),
            prohibited_next=("action:execute",),
            expected_receipt_refs=common_receipts,
            supersedes_refs=(),
            no_effect=True,
            may_authorize=False,
        ),
        ContextFact(
            fact_id="fact:private-canary",
            fact_type="private_canary",
            subject_ref="private:canary",
            scope_ref=task_scope.scope_ref,
            temporal_ref=data_temporal.temporal_ref,
            resolution_ref=data_resolution.resolution_ref,
            derivation_ref=private_derivation.derivation_ref,
            data=build_canonical_json_object({"secret": "canary-a"}),
            unit=None,
            meaning="A private canary exists only to falsify audience leakage.",
            implications=("Denied audiences must not derive from this fact.",),
            proves=("The audience seal test has a private input.",),
            does_not_prove=("The canary is operational data.",),
            blind_spots=("The canary has no production meaning.",),
            provenance=observed_provenance.model_copy(
                update={"source_refs": (private_observation.observation_ref,)}
            ),
            freshness_state="fresh",
            confidence=private_confidence,
            air=canary_air,
            state=ContextState(value_state="present", reason_codes=()),
            relation_refs=(),
            legal_next=(),
            prohibited_next=(),
            expected_receipt_refs=(),
            supersedes_refs=(),
            no_effect=True,
            may_authorize=False,
        ),
    )
    relations = (
        ContextRelation(
            relation_id="relation:position-gap",
            source_fact_ref="fact:position",
            target_fact_ref="fact:capability-gap",
            relation_type="constrains",
            meaning="The lifecycle position keeps execution held until evidence exists.",
            provenance_refs=(constitutional_observation.observation_ref,),
            state=ContextState(value_state="present", reason_codes=()),
            may_authorize=False,
        ),
    )
    impingements = (
        ContextImpingement(
            impingement_id="impingement:measurement",
            kind="evidence_gap",
            summary="Independent execution measurement is missing.",
            source_fact_refs=("fact:capability-gap",),
            protects=("protected:independent-admission",),
            legal_next=("action:inspect",),
            state=ContextState(value_state="hold", reason_codes=("measurement_missing",)),
            may_authorize=False,
        ),
    )
    portals = (
        PortalOffer(
            portal_ref="portal:evidence",
            kind="inspection",
            purpose="inspect_evidence_gap",
            source_fact_refs=("fact:position",),
            state=ContextState(value_state="present", reason_codes=()),
            effectivity_basis=("non_mutating_pull",),
            privacy_class="operator_private",
            budget_ref="budget:inspection",
            no_effect=True,
            may_authorize=False,
        ),
    )
    position = build_context_position(
        bundle,
        image,
        task_ref="task:rich",
        authority_case="authority:fixture",
        authorized_flags=(
            AuthorizationFlag(
                name="implementation_authorized",
                authorized=True,
                source_ref="receipt:authority",
            ),
            AuthorizationFlag(
                name="source_mutation_authorized",
                authorized=False,
                source_ref="receipt:authority",
            ),
        ),
        mutation_scope_refs=("shared/session_context_canon.py",),
        claim_ref="claim:fixture",
        route_decision_ref="route:fixture",
        demand_shape=demand,
        impingements=impingements,
        portal_offers=portals,
        receipt_lineage=("receipt:authority", "receipt:constraint-mask", "receipt:exposure"),
    )
    actions = (
        ContextAction(
            action_id="action:execute",
            label="Execute bounded probe",
            disposition="unavailable",
            position_ref=position.position_ref,
            action_class="lifecycle_operation",
            operation="source_mutation",
            lifecycle_operation="source_mutation",
            transition_to=None,
            transition_edge=None,
            admission_ref=lifecycle_operation_admission_ref(
                bundle.lifecycle_definition, "S6", "source_mutation"
            ),
            guard_evidence=(
                LifecycleGuardEvidence(
                    guard="implementation_authorized",
                    disposition="satisfied",
                    evidence_refs=("receipt:authority",),
                    may_authorize=False,
                ),
                LifecycleGuardEvidence(
                    guard="mutation_in_mutation_scope_refs",
                    disposition="satisfied",
                    evidence_refs=("fact:position",),
                    may_authorize=False,
                ),
                LifecycleGuardEvidence(
                    guard="source_mutation_authorized",
                    disposition="unsatisfied",
                    evidence_refs=("receipt:authority",),
                    may_authorize=False,
                ),
                LifecycleGuardEvidence(
                    guard="stage_at_least_s6",
                    disposition="satisfied",
                    evidence_refs=("fact:position",),
                    may_authorize=False,
                ),
            ),
            source_fact_refs=("fact:capability-gap", "fact:position"),
            why="Independent measurement and an execution lease are absent.",
            predicted_effect="A bounded probe would run only after independent admission.",
            recovery="No effect has occurred; retain HOLD and gather evidence.",
            expected_receipt_ref="receipt:execute",
            state=ContextState(value_state="hold", reason_codes=("execution_lease_missing",)),
            no_effect=True,
            may_authorize=False,
        ),
        ContextAction(
            action_id="action:inspect",
            label="Inspect exact evidence gap",
            disposition="legal",
            position_ref=position.position_ref,
            action_class="inspection",
            operation="context.inspect",
            lifecycle_operation=None,
            transition_to=None,
            transition_edge=None,
            admission_ref=None,
            guard_evidence=(),
            source_fact_refs=("fact:position",),
            why="Inspection is non-mutating and supported by the current position.",
            predicted_effect="The evidence gap becomes inspectable without changing authority.",
            recovery="Dismiss the projection; authoritative state remains unchanged.",
            expected_receipt_ref="receipt:inspect",
            state=ContextState(value_state="present", reason_codes=()),
            no_effect=True,
            may_authorize=False,
        ),
    )
    estimate = build_signal_estimate(
        estimate_id="estimate:evidence-gap",
        kind="boundary_estimate",
        position_ref=position.position_ref,
        scope_ref=task_scope.scope_ref,
        temporal_ref=data_temporal.temporal_ref,
        resolution_ref=data_resolution.resolution_ref,
        source_fact_refs=("fact:capability-gap", "fact:position"),
        derivation_ref=gap_derivation.derivation_ref,
        value={"boundary": "execution_lease_missing"},
        confidence=confidence,
        state=ContextState(value_state="present", reason_codes=()),
        supersedes_refs=(),
    )
    lens = build_signal_lens(
        lens_id="lens:boundary",
        audience="operator_private",
        purpose="current_boundary_orientation",
        scope_selector_refs=(task_scope.scope_ref,),
        resolution_selector_refs=(data_resolution.resolution_ref,),
        constraint_mask_refs=("fact:position", "impingement:measurement"),
        constraint_mask_receipt_ref="receipt:constraint-mask",
        utility_weights={"boundary_visibility": "1", "why_now": "1"},
        aggregation_ref="aggregation:identity",
        omission_policy_ref="omission:deny-oblivious",
    )
    constellation = build_signal_constellation(
        constellation_id="constellation:evidence-gap",
        target_ref="fact:capability-gap",
        lens_ref=lens.lens_ref,
        scope_ref=task_scope.scope_ref,
        resolution_ref=data_resolution.resolution_ref,
        member_estimate_refs=(estimate.estimate_ref,),
        relation_refs=("relation:position-gap",),
        uncovered_source_refs=(),
        aggregation_ref="aggregation:identity",
        state=ContextState(value_state="present", reason_codes=()),
    )
    present_axis = SignalValueAxis(
        value=CanonicalDecimal(value="1", unit="relative_orientation_value"),
        state=ContextState(value_state="present", reason_codes=()),
        evidence_refs=(estimate.estimate_ref,),
        method_ref="method:deterministic-vector",
    )
    low_cost_axis = SignalValueAxis(
        value=CanonicalDecimal(value="0.1", unit="relative_orientation_value"),
        state=ContextState(value_state="present", reason_codes=()),
        evidence_refs=(estimate.estimate_ref,),
        method_ref="method:deterministic-vector",
    )
    value_vector = OrientationValueVector(
        why_now=present_axis,
        coverage_gain=present_axis,
        decision_discrimination=present_axis,
        boundary_visibility=present_axis,
        continuity_restoration=present_axis,
        capability_opportunity=present_axis,
        recovery_leverage=present_axis,
        dependency_leverage=present_axis,
        attention_cost=low_cost_axis,
        confidence=present_axis,
        authority_air_risk=low_cost_axis,
    )
    signals = (
        build_orienting_signal(
            signal_id="signal:evidence-gap",
            kind="boundary",
            label="Execution remains held",
            position_ref=position.position_ref,
            estimate_refs=(estimate.estimate_ref,),
            lens_ref=lens.lens_ref,
            constellation_ref=constellation.constellation_ref,
            value_vector=value_vector,
            source_fact_refs=("fact:position",),
            why_now="The current action would cross an unleased execution boundary.",
            does_not_prove=("The operator intends execution.",),
            uncertainty="A fresh measurement could change capability availability.",
            privacy_class="operator_private",
            portal_ref="portal:evidence",
            state=ContextState(value_state="present", reason_codes=()),
        ),
    )
    learning_receipt = build_signal_learning_receipt(
        learning_id="learning:evidence-gap",
        position_ref=position.position_ref,
        estimate_ref=estimate.estimate_ref,
        constellation_ref=constellation.constellation_ref,
        exposure_ref="exposure:fixture",
        candidate_set_ref="candidate-set:fixture",
        selection_policy_ref="selection-policy:fixture",
        selection_propensity=CanonicalDecimal(value="1", unit="probability"),
        action_ref="action:inspect",
        outcome_ref="outcome:unobserved",
        effect={"state": "unobserved"},
        cost={"state": "unobserved"},
        witness_refs=("receipt:exposure",),
        receipt_ref="receipt:learning-held",
        correction_refs=(),
        supersedes_refs=(),
        update_target_ref="learning-target:orientation-policy",
        update_applied=False,
        state=ContextState(value_state="hold", reason_codes=("outcome_unobserved",)),
    )
    observation = build_epistemic_flow_event(
        event_id="event:observation",
        kind="observation_recorded",
        session_ref="session:test",
        task_ref="task:rich",
        trace_ref="trace:fixture",
        position_ref=position.position_ref,
        scope_ref=task_scope.scope_ref,
        temporal_ref=observation_event_temporal.temporal_ref,
        resolution_ref=observation_event_resolution.resolution_ref,
        generation=1,
        subject_ref="capability:execution",
        occurred_at="2026-07-10T16:02:00Z",
        expires_at="2026-07-10T18:00:00Z",
        producer_ref="producer:observer",
        method_ref="method:deterministic",
        privacy_class="operator_private",
        authority_ceiling="observation_only",
        source_refs=(estate_observation.observation_ref,),
        caused_by=("receipt:authority",),
        supersedes_refs=(),
        derivation_depth=0,
        payload={
            "observation_ref": estate_observation.observation_ref,
            "observation_state": "measurement_missing",
        },
        state=ContextState(value_state="present", reason_codes=()),
    )
    derivation = build_epistemic_flow_event(
        event_id="event:derivation",
        kind="context_fact_derived",
        session_ref="session:test",
        task_ref="task:rich",
        trace_ref="trace:fixture",
        position_ref=position.position_ref,
        scope_ref=task_scope.scope_ref,
        temporal_ref=derivation_event_temporal.temporal_ref,
        resolution_ref=derivation_event_resolution.resolution_ref,
        generation=1,
        subject_ref="fact:capability-gap",
        occurred_at="2026-07-10T16:03:00Z",
        expires_at="2026-07-10T18:00:00Z",
        producer_ref="producer:deterministic",
        method_ref="method:rule",
        privacy_class="operator_private",
        authority_ceiling="projection_only",
        source_refs=(estate_observation.observation_ref,),
        caused_by=(observation.event_ref,),
        supersedes_refs=(),
        derivation_depth=1,
        payload={
            "derivation_ref": gap_derivation.derivation_ref,
            "fact_ref": "fact:capability-gap",
        },
        state=ContextState(value_state="present", reason_codes=()),
    )
    orientation = build_boundary_orientation_facet(
        facet_id="orientation:execution-gap",
        focus_ref="fact:capability-gap",
        position_ref=position.position_ref,
        boundary_kind="execution_lease_missing",
        why_now_refs=("fact:capability-gap",),
        protects=("protected:independent-admission",),
        can=("action:inspect",),
        cannot=("action:execute",),
        until=("valid_execution_lease_observed",),
        iff=("position_hash_matches",),
        change_authority="independent_decision",
        counterfactual=CounterfactualFacet(
            action_id="action:execute",
            predicted_state_delta=build_canonical_json_object(
                {"authority": "unchanged", "effect": "none"}
            ),
            no_effect=True,
            may_authorize=False,
        ),
    )
    lifecycle_possibility = build_lifecycle_possibility_facet(
        facet_id="lifecycle-possibility:evidence-cycle",
        candidate_ref="lifecycle-candidate:fixture",
        source_fact_refs=("fact:capability-gap",),
        why_now="A recurring evidence gap has become inspectable.",
        does_not_prove=("The operator wants a lifecycle.",),
        uncertainty="The candidate plant remains provisional.",
        alternative_dispositions=(
            "checklist_or_workflow",
            "insufficient_evidence",
            "lifecycle_candidate",
            "one_shot_task",
        ),
        unknown_fields=("measurement_threshold",),
        candidate_plant={"candidate": "evidence-cycle"},
        estimated_cost={"class": "unknown"},
        plant_gap=ContextState(value_state="partial", reason_codes=("plant_fields_missing",)),
        harness_gap=ContextState(value_state="dark", reason_codes=("harness_unbuilt",)),
        measurement_gap=ContextState(
            value_state="hold", reason_codes=("measurement_threshold_missing",)
        ),
        lawful_next=("action:inspect",),
    )
    air_bindings = (
        ContextAirBinding(object_kind="position", object_ref=position.position_ref, air=allow_all),
        ContextAirBinding(
            object_kind="demand_shape",
            object_ref=f"demand-shape@sha256:{demand.fingerprint}",
            air=allow_all,
        ),
        *(
            ContextAirBinding(object_kind="scope", object_ref=item.scope_ref, air=allow_all)
            for item in (estate_scope, task_scope)
        ),
        *(
            ContextAirBinding(object_kind="temporal", object_ref=item.temporal_ref, air=allow_all)
            for item in (
                data_temporal,
                observation_event_temporal,
                derivation_event_temporal,
            )
        ),
        *(
            ContextAirBinding(
                object_kind="resolution", object_ref=item.resolution_ref, air=allow_all
            )
            for item in (
                data_resolution,
                observation_event_resolution,
                derivation_event_resolution,
            )
        ),
        *(
            ContextAirBinding(
                object_kind="source_admission",
                object_ref=item.admission_ref,
                air=(canary_air if item is private_source else allow_all),
            )
            for item in (constitutional_source, observed_source, private_source)
        ),
        *(
            ContextAirBinding(
                object_kind="observation",
                object_ref=item.observation_ref,
                air=(canary_air if item is private_observation else allow_all),
            )
            for item in (
                constitutional_observation,
                estate_observation,
                private_observation,
            )
        ),
        *(
            ContextAirBinding(
                object_kind="derivation",
                object_ref=item.derivation_ref,
                air=(canary_air if item is private_derivation else allow_all),
            )
            for item in (
                lifecycle_derivation,
                position_derivation,
                gap_derivation,
                private_derivation,
            )
        ),
        *(
            ContextAirBinding(object_kind="relation", object_ref=item.relation_id, air=allow_all)
            for item in relations
        ),
        *(
            ContextAirBinding(object_kind="action", object_ref=item.action_id, air=allow_all)
            for item in actions
        ),
        *(
            ContextAirBinding(
                object_kind="impingement", object_ref=item.impingement_id, air=allow_all
            )
            for item in impingements
        ),
        ContextAirBinding(object_kind="estimate", object_ref=estimate.estimate_ref, air=allow_all),
        ContextAirBinding(object_kind="lens", object_ref=lens.lens_ref, air=operator_signal_air),
        ContextAirBinding(
            object_kind="constellation",
            object_ref=constellation.constellation_ref,
            air=operator_signal_air,
        ),
        *(
            ContextAirBinding(
                object_kind="signal", object_ref=item.signal_id, air=operator_signal_air
            )
            for item in signals
        ),
        *(
            ContextAirBinding(object_kind="portal", object_ref=item.portal_ref, air=allow_all)
            for item in portals
        ),
        ContextAirBinding(
            object_kind="learning_receipt",
            object_ref=learning_receipt.learning_ref,
            air=operator_signal_air,
        ),
        *(
            ContextAirBinding(object_kind="event", object_ref=item.event_id, air=allow_all)
            for item in (observation, derivation)
        ),
        ContextAirBinding(
            object_kind="orientation", object_ref=orientation.facet_id, air=allow_all
        ),
        ContextAirBinding(
            object_kind="lifecycle_possibility",
            object_ref=lifecycle_possibility.facet_id,
            air=allow_all,
        ),
    )

    def materialize_frame(
        events: tuple[EpistemicFlowEvent, ...],
        bindings: tuple[ContextAirBinding, ...],
    ) -> ContextFrame:
        return build_context_frame(
            bundle,
            image,
            position,
            session_ref="session:test",
            task_ref="task:rich",
            demand_shape=demand,
            scopes=(estate_scope, task_scope),
            temporal_coordinates=(
                data_temporal,
                observation_event_temporal,
                derivation_event_temporal,
            ),
            resolution_coordinates=(
                data_resolution,
                observation_event_resolution,
                derivation_event_resolution,
            ),
            source_admissions=(constitutional_source, observed_source, private_source),
            observations=(
                constitutional_observation,
                estate_observation,
                private_observation,
            ),
            derivations=(
                lifecycle_derivation,
                position_derivation,
                gap_derivation,
                private_derivation,
            ),
            facts=facts,
            relations=relations,
            actions=actions,
            impingements=impingements,
            signal_estimates=(estimate,),
            signal_lenses=(lens,),
            signal_constellations=(constellation,),
            orienting_signals=signals,
            portal_offers=portals,
            signal_learning_receipts=(learning_receipt,),
            events=events,
            orientation_facets=(orientation,),
            lifecycle_possibilities=(lifecycle_possibility,),
            air_bindings=bindings,
            audience_policy_generation="audience:g1",
            privacy_policy_generation="privacy:g1",
            observed_at="2026-07-10T16:00:00Z",
            checked_at="2026-07-10T16:05:00Z",
            stale_after="2026-07-10T18:00:00Z",
        )

    frame = materialize_frame((observation, derivation), air_bindings)
    projection_args = {
        "purpose": "orientation",
        "decoder_ref": "decoder:context-v1",
        "focus_ref": "fact:capability-gap",
        "producer_ref": "producer:deterministic-projector",
        "generated_at": "2026-07-10T16:06:00Z",
        "orientation_ref": orientation.facet_ref,
    }
    seed_projection = project_context_frame(
        frame,
        audience="operator_private",
        depth="immediate",
        device_class="accessible_linear",
        register="plain",
        **projection_args,
    )
    flow_specs = (
        (
            "context_frame_materialized",
            {"frame_ref": frame.frame_ref, "frame_state": "frozen"},
        ),
        (
            "projection_materialized",
            {
                "projection_ref": seed_projection.projection_ref,
                "projection_state": "audience_sealed",
            },
        ),
        (
            "orienting_signal_offered",
            {"offer_state": "offered_no_effect", "signal_ref": signals[0].signal_ref},
        ),
        (
            "portal_pull_requested",
            {"portal_ref": portals[0].portal_ref, "request_state": "requested_no_effect"},
        ),
        (
            "portal_consumed",
            {
                "consumption_receipt_ref": "portal-consumption@sha256:" + "1" * 64,
                "consumption_state": "witnessed_no_effect",
                "portal_ref": portals[0].portal_ref,
            },
        ),
        ("inquiry", {"inquiry_ref": "inquiry:fixture", "inquiry_state": "opened_no_effect"}),
        (
            "counterfactual",
            {"action_ref": "action:execute", "counterfactual_state": "previewed_no_effect"},
        ),
        (
            "intent_expressed",
            {
                "action_ref": "action:execute",
                "intent_kind": "explicit_probe_request",
                "intent_state": "expressed_not_authorized",
            },
        ),
        (
            "stipulation_recorded",
            {"stipulation_ref": "stipulation:fixture", "stipulation_state": "non_authorizing"},
        ),
        (
            "consent_recorded",
            {"consent_ref": "consent:fixture", "consent_state": "non_authorizing"},
        ),
        ("lease_referenced", {"lease_ref": "lease:absent", "lease_state": "absent"}),
        (
            "effect_observed",
            {"effect_ref": "effect:unobserved", "outcome_state": "unobserved"},
        ),
        (
            "receipt_recorded",
            {"receipt_ref": learning_receipt.receipt_ref, "receipt_state": "no_effect"},
        ),
        (
            "measurement_updated",
            {
                "learning_target_ref": learning_receipt.update_target_ref,
                "measurement_ref": "measurement:held",
                "measurement_state": "held_no_effect",
            },
        ),
    )
    flow_events: list[EpistemicFlowEvent] = []
    predecessor = derivation
    for ordinal, (kind, payload) in enumerate(flow_specs, start=2):
        held = kind in {
            "lease_referenced",
            "effect_observed",
            "receipt_recorded",
            "measurement_updated",
        }
        event = build_epistemic_flow_event(
            event_id=f"event:{kind.replace('_', '-')}",
            kind=kind,
            session_ref="session:test",
            task_ref="task:rich",
            trace_ref="trace:fixture",
            position_ref=position.position_ref,
            scope_ref=task_scope.scope_ref,
            temporal_ref=derivation_event_temporal.temporal_ref,
            resolution_ref=derivation_event_resolution.resolution_ref,
            generation=ordinal,
            subject_ref="capability:execution",
            occurred_at=derivation_event_temporal.event_time_start,
            expires_at=derivation_event_temporal.valid_until,
            producer_ref="producer:deterministic",
            method_ref="method:typed-event-braid",
            privacy_class="operator_private",
            authority_ceiling="projection_only",
            source_refs=(estate_observation.observation_ref,),
            caused_by=(predecessor.event_ref,),
            supersedes_refs=(),
            derivation_depth=ordinal,
            payload=payload,
            state=(
                ContextState(value_state="hold", reason_codes=("execution_lease_missing",))
                if held
                else ContextState(value_state="present", reason_codes=())
            ),
        )
        flow_events.append(event)
        predecessor = event
    extended_air = tuple(
        sorted(
            (
                *air_bindings,
                *(
                    ContextAirBinding(object_kind="event", object_ref=event.event_id, air=allow_all)
                    for event in flow_events
                ),
            ),
            key=lambda binding: (binding.object_kind, binding.object_ref),
        )
    )
    frame = materialize_frame((observation, derivation, *flow_events), extended_air)
    operator = project_context_frame(
        frame,
        audience="operator_private",
        depth="immediate",
        device_class="accessible_linear",
        register="plain",
        **projection_args,
    )
    yard = project_context_frame(
        frame,
        audience="yard_context",
        depth="expanded",
        device_class="monitor",
        register="labeled",
        **projection_args,
    )
    hapax = project_context_frame(
        frame,
        audience="hapax_substrate",
        depth="raw",
        device_class="compact",
        register="raw",
        **projection_args,
    )
    return {
        "bundle": bundle,
        "descriptor": descriptor,
        "demand": demand,
        "frame": frame,
        "scope": task_scope,
        "temporal": data_temporal,
        "resolution": data_resolution,
        "private_observation": private_observation,
        "estimate": estimate,
        "lens": lens,
        "constellation": constellation,
        "learning_receipt": learning_receipt,
        "orientation": orientation,
        "lifecycle_possibility": lifecycle_possibility,
        "operator": operator,
        "yard": yard,
        "hapax": hapax,
    }


def _image(bundle: CanonBundle, stage: str, level: str):
    return next(
        image
        for image in bundle.images
        if image.stage_token == stage and image.level.value == level
    )


def _ids(image) -> set[str]:
    return {
        atom.id
        for atom in (
            *image.strata.fsm.what,
            *image.strata.fsm.how,
            *image.strata.fsm.must,
        )
    }


def _rehash_image(payload: dict) -> None:
    body = {key: value for key, value in payload.items() if key != "image_hash"}
    payload["image_hash"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _rehash_bundle(payload: dict) -> None:
    body = {
        key: value for key, value in payload.items() if key not in {"bundle_ref", "bundle_hash"}
    }
    digest = _domain_hash("hapax.coordination-canon.bundle.v1", body)
    payload["bundle_hash"] = digest
    payload["bundle_ref"] = f"canon-bundle@sha256:{digest}"


def _rehash_position(payload: dict) -> None:
    body = {
        key: value for key, value in payload.items() if key not in {"position_ref", "position_hash"}
    }
    digest = _domain_hash("hapax.context-position.v1", body)
    payload["position_hash"] = digest
    payload["position_ref"] = f"context-position@sha256:{digest}"


def _rehash_frame(payload: dict) -> None:
    body = {key: value for key, value in payload.items() if key not in {"frame_ref", "frame_hash"}}
    digest = _domain_hash("hapax.context-frame.v1", body)
    payload["frame_hash"] = digest
    payload["frame_ref"] = f"context-frame@sha256:{digest}"


def _rehash_projection(payload: dict) -> None:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"projection_ref", "projection_hash"}
    }
    digest = _domain_hash("hapax.projection-envelope.v1", body)
    payload["projection_hash"] = digest
    payload["projection_ref"] = f"projection-envelope@sha256:{digest}"


def _rehash_addressed(
    payload: dict, *, domain: str, ref_field: str, hash_field: str, prefix: str
) -> None:
    body = {key for key in payload if key not in {ref_field, hash_field}}
    content = {key: payload[key] for key in body}
    digest = _domain_hash(domain, content)
    payload[hash_field] = digest
    payload[ref_field] = f"{prefix}@sha256:{digest}"


def test_source_is_typed_disjoint_and_machine_readable() -> None:
    source = load_canon_source()
    assert source.schema_id == "hapax.coordination-canon.source.v1"
    assert source.wire_contract.kind == "context_bundle"
    assert source.wire_contract.fsm_fields == ("what", "how", "must")
    assert {atom.stratum for atom in source.atoms} == {"what", "how", "must"}
    assert len({atom.id for atom in source.atoms}) == len(source.atoms)


def test_tla_is_verified_by_the_materializer() -> None:
    verify_tla_topology(TLA_PATH.read_text(encoding="utf-8"), SDLC_STAGE_METADATA)


def test_bundle_has_exact_stage_level_product_and_stable_hashes(bundle: CanonBundle) -> None:
    assert bundle.schema_id == CANON_BUNDLE_SCHEMA
    assert len(SDLC_STAGE_METADATA.tokens) == 14
    assert tuple(stage.token for stage in bundle.lifecycle_definition.stages) == (
        SDLC_STAGE_METADATA.tokens
    )
    assert len(bundle.images) == 56
    assert [(image.stage_token, image.level.value) for image in bundle.images] == [
        (token, level)
        for token in SDLC_STAGE_METADATA.tokens
        for level in ("pi0", "pi1", "pi2", "pi3")
    ]
    assert all(image.schema_id == CANON_IMAGE_SCHEMA for image in bundle.images)
    assert all(image.canon_hash == bundle.canon_hash for image in bundle.images)
    assert all(
        image.lifecycle_definition_hash == bundle.lifecycle_definition.definition_hash
        for image in bundle.images
    )
    assert tuple(item.field_path for item in bundle.lifecycle_definition.field_provenance) == tuple(
        sorted(item.field_path for item in bundle.lifecycle_definition.field_provenance)
    )
    assert {f"/stages/{token}" for token in SDLC_STAGE_METADATA.tokens} <= {
        item.field_path for item in bundle.lifecycle_definition.field_provenance
    }
    assert len({image.image_hash for image in bundle.images}) == 56


def test_repeated_build_is_byte_identical(bundle: CanonBundle) -> None:
    rebuilt = build_canon_bundle()
    assert canonical_json_bytes(rebuilt) == canonical_json_bytes(bundle)
    assert rebuilt.bundle_hash == bundle.bundle_hash
    assert rebuilt.canon_hash == bundle.canon_hash


def test_materializer_reads_source_registry_and_metadata_once(monkeypatch) -> None:
    counts = {"source": 0, "metadata": 0, "registry": 0}
    source_reader = canon_module._source_text
    metadata_parser = canon_module.parse_sdlc_stage_metadata
    registry_parser = canon_module.parse_registry

    def read_source_once(path):
        counts["source"] += 1
        return source_reader(path)

    def parse_metadata_once(raw, *, source_label):
        counts["metadata"] += 1
        return metadata_parser(raw, source_label=source_label)

    def parse_registry_once(raw):
        counts["registry"] += 1
        return registry_parser(raw)

    monkeypatch.setattr(canon_module, "_source_text", read_source_once)
    monkeypatch.setattr(canon_module, "parse_sdlc_stage_metadata", parse_metadata_once)
    monkeypatch.setattr(canon_module, "parse_registry", parse_registry_once)
    build_canon_bundle()
    assert counts == {"source": 1, "metadata": 1, "registry": 1}


def test_encoder_version_mismatch_refuses_generation(monkeypatch) -> None:
    monkeypatch.setattr(canon_module.importlib_metadata, "version", lambda _name: "0.1.4")
    with pytest.raises(CanonError, match="canon_encoder_version_mismatch"):
        build_canon_bundle()


def test_corpus_sorting_is_independent_of_source_atom_order(corpus) -> None:
    reversed_source = corpus.source.model_copy(
        update={"atoms": tuple(reversed(corpus.source.atoms))}
    )
    rebuilt = build_corpus(
        reversed_source,
        compression_registry=corpus.compression_registry,
    )
    assert rebuilt.atoms == corpus.atoms
    assert rebuilt.canon_hash == corpus.canon_hash


@pytest.mark.parametrize("atom_id", sorted(_REQUIRED_MUST_IDS_V1 | _REQUIRED_GROUNDING_IDS_V1))
def test_every_required_must_and_grounding_atom_is_individually_non_omissible(
    atom_id: str,
) -> None:
    source = load_canon_source()
    missing = source.model_copy(
        update={"atoms": tuple(atom for atom in source.atoms if atom.id != atom_id)}
    )
    with pytest.raises(ValueError, match="required (MUST|grounding) atoms are missing"):
        build_corpus(missing, compression_registry=load_registry())


@pytest.mark.parametrize("atom_id", sorted(_REQUIRED_GROUNDING_IDS_V1))
def test_every_grounding_atom_has_exact_pinned_bytes(atom_id: str) -> None:
    source = load_canon_source()
    expected = _required_grounding_content(SDLC_STAGE_METADATA)[atom_id]
    assert next(atom for atom in source.atoms if atom.id == atom_id).content == expected
    mutated = source.model_copy(
        update={
            "atoms": tuple(
                atom.model_copy(update={"content": atom.content + " drift"})
                if atom.id == atom_id
                else atom
                for atom in source.atoms
            )
        }
    )
    with pytest.raises(ValueError, match="required grounding bytes differ"):
        build_corpus(mutated, compression_registry=load_registry())


def test_authorization_vocabulary_tracks_no_go_ssot() -> None:
    expected = set(NO_GO_BOOLEANS) | {
        "decision_minting_authorized",
        "provider_spend_authorized",
    }
    content = _required_grounding_content(SDLC_STAGE_METADATA)[
        "must.grounding.authorization-vocabulary"
    ]
    assert content.split() == sorted(expected)


def test_canon_identity_refuses_wire_or_algorithm_relabeling(corpus) -> None:
    bad_wire = corpus.source.model_copy(
        update={
            "wire_contract": corpus.source.wire_contract.model_copy(update={"sha256": "f" * 64})
        }
    )
    with pytest.raises(CanonError, match="canon_source_semantic_identity_mismatch"):
        build_corpus(bad_wire, compression_registry=corpus.compression_registry)

    bad_algorithm = corpus.source.model_copy(update={"projection_algorithm": "other"})
    with pytest.raises(CanonError, match="canon_source_semantic_identity_mismatch"):
        build_corpus(bad_algorithm, compression_registry=corpus.compression_registry)


def test_every_projection_preserves_all_must_and_grounding_bytes(bundle: CanonBundle) -> None:
    baseline = _image(bundle, "S0", "pi0")
    must_bytes = canonical_json_bytes(baseline.strata.fsm.must)
    grounding_bytes = canonical_json_bytes(baseline.grounding_core)
    grounding_ids = {atom.id for atom in baseline.grounding_core}
    assert grounding_ids
    for image in bundle.images:
        assert canonical_json_bytes(image.strata.fsm.must) == must_bytes
        assert canonical_json_bytes(image.grounding_core) == grounding_bytes
        assert grounding_ids <= _ids(image)
        assert not grounding_ids.intersection(image.kernel.omitted_atom_ids)
        for atom in image.grounding_core:
            assert atom.content in image.rendered_payload


def test_every_kernel_is_the_exact_nonmandatory_complement(bundle: CanonBundle) -> None:
    full_ids = _ids(_image(bundle, "S0", "pi0"))
    must_ids = {atom.id for atom in _image(bundle, "S0", "pi0").strata.fsm.must}
    grounding_ids = {atom.id for atom in _image(bundle, "S0", "pi0").grounding_core}
    for image in bundle.images:
        assert set(image.kernel.omitted_atom_ids) == full_ids - _ids(image)
        assert not (must_ids | grounding_ids).intersection(image.kernel.omitted_atom_ids)


def test_forward_cone_uses_roles_and_never_traverses_repair_cycles(corpus) -> None:
    assert forward_cone("S8", corpus) == ("S8", "S9", "S10", "S11", "BLOCKED")
    assert forward_cone("S3_5", corpus) == (
        "S3_5",
        "S4",
        "S5",
        "S6",
        "S7",
        "S8",
        "S9",
        "S10",
        "S11",
        "BLOCKED",
    )
    assert forward_cone("BLOCKED", corpus) == ("BLOCKED",)
    assert "S0" not in forward_cone("S6", corpus)


def test_pi1_has_a_real_named_kernel(bundle: CanonBundle) -> None:
    image = _image(bundle, "S8", "pi1")
    assert image.kernel.name == "pi1-outside-forward-cone"
    assert image.kernel.omitted_atom_ids
    assert "what.stage.s0.topology" in image.kernel.omitted_atom_ids
    assert "what.stage.s8.topology" not in image.kernel.omitted_atom_ids


def test_pi2_and_pi3_have_the_promised_horizons(bundle: CanonBundle) -> None:
    pi2 = _image(bundle, "S6", "pi2")
    pi3 = _image(bundle, "S6", "pi3")
    assert "what.stage.s6.topology" in _ids(pi2)
    assert "what.stage.blocked.topology" in _ids(pi2)
    assert "what.stage.s5.topology" not in _ids(pi2)
    assert "what.stage.s6.gate" in _ids(pi3)
    assert "what.stage.s6.topology" not in _ids(pi3)
    assert pi3.kernel.distortion_class == "fsm_structure_and_procedures"


def test_projection_containment_is_monotone(bundle: CanonBundle) -> None:
    for stage in SDLC_STAGE_METADATA.tokens:
        levels = [_ids(_image(bundle, stage, level)) for level in ("pi0", "pi1", "pi2", "pi3")]
        assert levels[3] <= levels[2] <= levels[1] <= levels[0]


def test_toon_is_presentation_only_and_round_trips_losslessly(bundle: CanonBundle) -> None:
    image = _image(bundle, "S6", "pi2")
    expected = [{"id": atom.id, "content": atom.content} for atom in image.strata.fsm.what]
    assert toon.decode(image.rendered_strata.what) == expected
    assert image.reference_tokenizer_id == "hapax.ascii-lexeme.v1"
    assert image.reference_token_count > 0


def test_locked_context_bundle_fsm_fields_are_nonblank_strings(bundle: CanonBundle) -> None:
    fsm = context_bundle_fsm(_image(bundle, "S6", "pi2"))
    assert tuple(fsm) == ("what", "how", "must")
    assert all(isinstance(value, str) and value for value in fsm.values())


def test_unknown_or_lossy_compression_surface_fails_closed(corpus) -> None:
    denied = build_corpus(
        corpus.source,
        compression_registry={},
    )
    with pytest.raises(CanonError) as caught:
        project_canon(denied, "S6", ProjectionLevel.EDGE)
    assert caught.value.reason_code == "canon_compression_surface_not_lossless_only"


def test_unknown_stage_and_level_are_typed_failures(corpus) -> None:
    with pytest.raises(CanonError, match="canon_stage_unknown"):
        project_canon(corpus, "S99", "pi2")
    with pytest.raises(CanonError, match="canon_projection_level_unknown"):
        project_canon(corpus, "S6", "pi9")


def test_canonical_json_rejects_nonfinite_nonjson_and_bad_unicode() -> None:
    with pytest.raises(CanonError, match="canon_json_nonfinite_number"):
        canonical_json_bytes({"x": float("nan")})
    with pytest.raises(CanonError, match="canon_json_float_unsupported"):
        canonical_json_bytes({"x": 1.0})
    with pytest.raises(CanonError, match="canon_json_type_invalid"):
        canonical_json_bytes({"x": {"not", "json"}})
    with pytest.raises(CanonError, match="canon_json_unicode_invalid"):
        canonical_json_bytes({"x": "\ud800"})
    with pytest.raises(CanonError, match="canon_json_key_invalid"):
        canonical_json_bytes({1: "bad"})
    assert canonical_json_bytes({"x": (1 << 53) - 1})
    assert canonical_json_bytes({"x": -((1 << 53) - 1)})
    with pytest.raises(CanonError, match="canon_json_integer_out_of_range"):
        canonical_json_bytes({"x": 1 << 53})
    with pytest.raises(CanonError, match="canon_json_integer_out_of_range"):
        canonical_json_bytes({"x": -(1 << 53)})


def test_duplicate_yaml_key_and_unknown_field_fail_closed(tmp_path: Path) -> None:
    raw = CANON_SOURCE_PATH.read_text(encoding="utf-8")
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(raw.replace("canon_version: 1\n", "canon_version: 1\ncanon_version: 2\n"))
    with pytest.raises(CanonError, match="canon_source_duplicate_yaml_key"):
        load_canon_source(duplicate)

    unknown = tmp_path / "unknown.yaml"
    unknown.write_text(raw.replace("domain: sdlc\n", "domain: sdlc\nunknown: true\n"))
    with pytest.raises(CanonError, match="canon_source_schema_invalid"):
        load_canon_source(unknown)

    payload = load_canon_source().model_dump(mode="json", by_alias=True)
    payload["atoms"][0]["grounding"] = 1
    with pytest.raises(ValidationError):
        type(load_canon_source()).model_validate(payload)


def test_lifecycle_edge_classes_have_one_generic_semantics(bundle: CanonBundle) -> None:
    payload = bundle.lifecycle_definition.model_dump(mode="json", by_alias=True)
    stage = next(item for item in payload["stages"] if item["token"] == "S10")
    stage["fall"][0]["to"] = "S0"
    stage["fall"][0]["projection_role"] = "branch"
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"definition_ref", "definition_hash"}
    }
    definition_hash = _domain_hash("hapax.lifecycle-definition.v1", body)
    payload["definition_hash"] = definition_hash
    payload["definition_ref"] = f"lifecycle-definition@sha256:{definition_hash}"
    definition = type(bundle.lifecycle_definition).model_validate(payload)

    scope = canon_module._projection_scope_definition("S10", ProjectionLevel.STATE_CONE, definition)
    assert "S0" in scope


def test_missing_must_and_mutated_tla_fail_closed(tmp_path: Path) -> None:
    source = load_canon_source()
    without_must = source.model_copy(
        update={"atoms": tuple(atom for atom in source.atoms if atom.stratum != "must")}
    )
    with pytest.raises(ValidationError):
        type(source).model_validate(without_must.model_dump(mode="json"))

    mutated = TLA_PATH.read_text(encoding="utf-8").replace(
        '[] s = "S8"      -> {"S9"}', '[] s = "S8"      -> {"S10"}'
    )
    with pytest.raises(CanonError, match="canon_tla_topology_mismatch"):
        verify_tla_topology(mutated, SDLC_STAGE_METADATA)


def test_json_schema_is_generated_exactly_and_rejects_extras(bundle: CanonBundle) -> None:
    checked_in = CANON_SCHEMA_PATH.read_bytes()
    assert checked_in == bundle_json_schema_bytes()
    assert checked_bundle_json_schema_bytes() == checked_in
    schema = json.loads(checked_in)
    validator = jsonschema.Draft202012Validator(schema)
    validator.validate(bundle.model_dump(mode="json", by_alias=True))
    invalid = bundle.model_dump(mode="json", by_alias=True)
    invalid["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(invalid)


def test_epistemic_event_payload_schema_is_kind_discriminated() -> None:
    schema = json.loads(context_canon_package.carrier_json_schema_bytes())
    payload_schema = schema["$defs"]["EpistemicFlowEvent"]["properties"]["payload"]
    assert payload_schema["discriminator"]["propertyName"] == "kind"
    expected_kinds = set(get_args(context_canon_package.EpistemicEventKind))
    assert set(payload_schema["discriminator"]["mapping"]) == expected_kinds
    assert len(payload_schema["oneOf"]) == len(expected_kinds) == 20


def test_self_hashed_empty_or_truncated_bundles_are_rejected(bundle: CanonBundle) -> None:
    empty = bundle.model_dump(mode="json", by_alias=True)
    empty["images"] = []
    _rehash_bundle(empty)
    with pytest.raises(ValidationError):
        CanonBundle.model_validate(empty)

    truncated = bundle.model_dump(mode="json", by_alias=True)
    truncated["images"].pop()
    _rehash_bundle(truncated)
    with pytest.raises(ValidationError, match="lifecycle stage/level product"):
        CanonBundle.model_validate(truncated)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda image: image["rendered_strata"].update({"must": "CORRUPTED MUST"}),
        lambda image: image.update({"rendered_payload": "CORRUPTED PAYLOAD"}),
        lambda image: image.update({"reference_token_count": image["reference_token_count"] + 1}),
        lambda image: image["grounding_core"][0].update({"content": "CORRUPTED GROUNDING"}),
    ],
)
def test_self_hashed_images_cannot_contradict_typed_semantics(
    bundle: CanonBundle, mutation
) -> None:
    payload = bundle.model_dump(mode="json", by_alias=True)
    mutation(payload["images"][0])
    _rehash_image(payload["images"][0])
    _rehash_bundle(payload)
    with pytest.raises(ValidationError):
        CanonBundle.model_validate(payload)


def test_self_hashed_kernel_must_be_exact_corpus_complement(bundle: CanonBundle) -> None:
    payload = bundle.model_dump(mode="json", by_alias=True)
    image = next(
        item
        for item in payload["images"]
        if item["level"] == "pi1" and item["kernel"]["omitted_atom_ids"]
    )
    image["kernel"]["omitted_atom_ids"].pop()
    image["kernel"]["omitted_digest"] = hashlib.sha256(
        canonical_json_bytes(image["kernel"]["omitted_atom_ids"])
    ).hexdigest()
    _rehash_image(image)
    _rehash_bundle(payload)
    with pytest.raises(ValidationError, match="exact corpus complement"):
        CanonBundle.model_validate(payload)


def test_embedded_lifecycle_validation_is_global_independent(
    bundle: CanonBundle, monkeypatch
) -> None:
    payload = bundle.model_dump(mode="json", by_alias=True)
    monkeypatch.setattr(canon_module, "SDLC_STAGE_METADATA", object())
    assert CanonBundle.model_validate(payload) == bundle


def test_demand_fingerprint_binds_every_complete_axis(rich_context) -> None:
    descriptor = rich_context["descriptor"]
    assert isinstance(descriptor, canon_module.DemandShapeDescriptor)
    baseline = descriptor.demand_shape_fingerprint
    common = {
        "session_ref": "session:test",
        "strategy": {"mode": "contextual", "purpose": "orientation"},
        "strata": {"how": "h", "must": "m", "what": "w"},
        "canon": {"bundle_ref": "canon-bundle:test", "image_hash": "a" * 64},
        "position_basis": {
            "legal_successors": ["S7"],
            "lifecycle_definition_ref": "lifecycle-definition:test",
            "stage_token": "S6",
        },
        "offered_affordances": ("action:execute", "action:inspect"),
        "provenance_generation": "provenance:g1",
        "policy_generation": "policy:g1",
        "audience_policy": {"generation": "audience:g1"},
        "kernel": {"omitted_digest": "kernel"},
        "budget": {"reference_tokens": 1},
    }
    first = build_demand_shape_descriptor(**common)
    assert first.demand_shape_fingerprint != baseline
    reordered = build_demand_shape_descriptor(
        **{**common, "strategy": {"purpose": "orientation", "mode": "contextual"}}
    )
    assert reordered.demand_shape_fingerprint == first.demand_shape_fingerprint
    variants = (
        {"strategy": {"mode": "different"}},
        {"strata": {"how": "changed", "must": "m", "what": "w"}},
        {"canon": {"bundle_ref": "canon-bundle:changed", "image_hash": "b" * 64}},
        {
            "position_basis": {
                "legal_successors": ["BLOCKED", "S7"],
                "lifecycle_definition_ref": "lifecycle-definition:test",
                "stage_token": "S6",
            }
        },
        {"offered_affordances": ("action:inspect",)},
        {"provenance_generation": "provenance:g2"},
        {"policy_generation": "policy:g2"},
        {"audience_policy": {"generation": "audience:g2"}},
        {"kernel": {"omitted_digest": "changed"}},
        {"budget": {"reference_tokens": 2}},
    )
    fingerprints = {
        build_demand_shape_descriptor(**{**common, **variant}).demand_shape_fingerprint
        for variant in variants
    }
    assert len(fingerprints) == len(variants)
    assert first.demand_shape_fingerprint not in fingerprints

    payload = first.model_dump(mode="json", by_alias=True)
    strategy_only = _domain_hash(
        "hapax.demand-shape-descriptor.v1", {"strategy": payload["strategy"]}
    )
    payload["demand_shape_fingerprint"] = strategy_only
    payload["descriptor_ref"] = f"demand-shape@sha256:{strategy_only}"
    with pytest.raises(ValidationError, match="complete descriptor"):
        canon_module.DemandShapeDescriptor.model_validate(payload)


def test_portal_consumption_cannot_satisfy_must_or_source_authority() -> None:
    portal_receipt = "portal-consumption@sha256:" + "a" * 64
    with pytest.raises(ValidationError, match="cannot satisfy a guard"):
        LifecycleGuardEvidence(
            guard="source_mutation_authorized",
            disposition="satisfied",
            evidence_refs=(portal_receipt,),
            may_authorize=False,
        )
    with pytest.raises(ValidationError, match="cannot source authority"):
        AuthorizationFlag(
            name="source_mutation_authorized",
            authorized=True,
            source_ref=portal_receipt,
        )


def test_unadmitted_source_fails_closed(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["source_admissions"] = [
        item
        for item in payload["source_admissions"]
        if item["admission_id"] != "source-admission:estate"
    ]
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="admitted source"):
        ContextFrame.model_validate(payload)


def test_present_observation_requires_usable_coordinate_bound_admission(
    rich_context,
) -> None:
    frame = rich_context["frame"]
    scope = rich_context["scope"]
    temporal = rich_context["temporal"]
    resolution = rich_context["resolution"]
    assert isinstance(frame, ContextFrame)
    allow_all = next(
        item.air
        for item in frame.air_bindings
        if item.object_kind == "source_admission"
        and item.air.operator_private == "allow"
        and item.air.yard_context == "allow"
    )
    unavailable = build_source_admission(
        admission_id="source-admission:unavailable",
        source_ref="source:unavailable",
        source_kind="fixture_unavailable",
        schema_ref="schema:fixture-source-v1",
        unit_semantics_ref="semantics:fixture",
        join_keys=("session_ref", "task_ref"),
        scope_ref=scope.scope_ref,
        temporal_ref=temporal.temporal_ref,
        resolution_ref=resolution.resolution_ref,
        producer_ref="producer:deterministic",
        method_ref="method:fixture",
        verification_refs=("receipt:source-unavailable",),
        policy_refs=("policy:fixture",),
        authority_ceiling="observation_only",
        supported_provenance_kinds=("observed",),
        consumer_contract_refs=("consumer:context-frame",),
        availability=ContextState(value_state="absent", reason_codes=("source_unavailable",)),
        freshness_state="absent",
        cost=build_canonical_json_object({"class": "unknown"}),
        latency=build_canonical_json_object({"class": "unknown"}),
        probe_witness_refs=("receipt:source-unavailable",),
    )
    observation = build_observation_envelope(
        observation_id="observation:invalid-present",
        source_admission_ref=unavailable.admission_ref,
        scope_ref=scope.scope_ref,
        temporal_ref=temporal.temporal_ref,
        resolution_ref=resolution.resolution_ref,
        subject_ref="source:unavailable",
        payload={"claimed": "present"},
        producer_ref="producer:observer",
        method_ref="method:deterministic",
        config_ref="config:observer",
        authority_ceiling="observation_only",
        witness_refs=("receipt:source-unavailable",),
        source_refs=(frame.position.receipt_lineage[0],),
        state=ContextState(value_state="present", reason_codes=()),
    )
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["source_admissions"].append(unavailable.model_dump(mode="json"))
    payload["source_admissions"].sort(key=lambda item: item["admission_ref"])
    payload["observations"].append(observation.model_dump(mode="json"))
    payload["observations"].sort(key=lambda item: item["observation_ref"])
    payload["air_bindings"].extend(
        (
            ContextAirBinding(
                object_kind="source_admission",
                object_ref=unavailable.admission_ref,
                air=allow_all,
            ).model_dump(mode="json"),
            ContextAirBinding(
                object_kind="observation",
                object_ref=observation.observation_ref,
                air=allow_all,
            ).model_dump(mode="json"),
        )
    )
    payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="present observations require"):
        ContextFrame.model_validate(payload)

    mismatch = frame.model_dump(mode="json", by_alias=True)
    candidate = build_observation_envelope(
        observation_id="observation:coordinate-mismatch",
        source_admission_ref=frame.source_admissions[0].admission_ref,
        scope_ref=scope.scope_ref,
        temporal_ref=next(
            item.temporal_ref
            for item in frame.temporal_coordinates
            if item.temporal_ref != temporal.temporal_ref
        ),
        resolution_ref=resolution.resolution_ref,
        subject_ref="source:mismatch",
        payload={"claimed": "mismatch"},
        producer_ref="producer:observer",
        method_ref="method:deterministic",
        config_ref="config:observer",
        authority_ceiling="observation_only",
        witness_refs=("receipt:mismatch",),
        source_refs=(frame.position.receipt_lineage[0],),
        state=ContextState(value_state="present", reason_codes=()),
    )
    mismatch["observations"].append(candidate.model_dump(mode="json"))
    mismatch["observations"].sort(key=lambda item: item["observation_ref"])
    mismatch["air_bindings"].append(
        ContextAirBinding(
            object_kind="observation",
            object_ref=candidate.observation_ref,
            air=allow_all,
        ).model_dump(mode="json")
    )
    mismatch["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(mismatch)
    with pytest.raises(ValidationError, match="observation resolution differs"):
        ContextFrame.model_validate(mismatch)


def test_denied_observation_cannot_change_downstream_projection(rich_context) -> None:
    frame = rich_context["frame"]
    yard = rich_context["yard"]
    scope = rich_context["scope"]
    temporal = rich_context["temporal"]
    resolution = rich_context["resolution"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(yard, ProjectionEnvelope)
    private_source = next(
        item
        for item in frame.source_admissions
        if item.admission_id == "source-admission:private-canary"
    )
    private_air = next(
        item.air
        for item in frame.air_bindings
        if item.object_kind == "observation"
        and item.object_ref == rich_context["private_observation"].observation_ref
    )

    def projected(secret: str) -> ProjectionEnvelope:
        hidden = build_observation_envelope(
            observation_id="observation:unused-private",
            source_admission_ref=private_source.admission_ref,
            scope_ref=scope.scope_ref,
            temporal_ref=temporal.temporal_ref,
            resolution_ref=resolution.resolution_ref,
            subject_ref="private:unused",
            payload={"secret": secret},
            producer_ref="producer:observer",
            method_ref="method:deterministic",
            config_ref="config:observer",
            authority_ceiling="observation_only",
            witness_refs=("receipt:hidden",),
            source_refs=(frame.position.receipt_lineage[0],),
            state=ContextState(value_state="present", reason_codes=()),
        )
        payload = frame.model_dump(mode="json", by_alias=True)
        payload["observations"].append(hidden.model_dump(mode="json"))
        payload["observations"].sort(key=lambda item: item["observation_ref"])
        payload["air_bindings"].append(
            ContextAirBinding(
                object_kind="observation",
                object_ref=hidden.observation_ref,
                air=private_air,
            ).model_dump(mode="json")
        )
        payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
        _rehash_frame(payload)
        changed = ContextFrame.model_validate(payload)
        return project_context_frame(
            changed,
            audience="yard_context",
            purpose=yard.purpose,
            depth=yard.depth,
            device_class=yard.device_class,
            register=yard.register_mode,
            decoder_ref=yard.decoder_ref,
            focus_ref=yard.focus_ref,
            producer_ref=yard.producer_ref,
            generated_at=yard.generated_at,
            orientation_ref=yard.orientation.facet_ref if yard.orientation else None,
        )

    assert projected("first") == yard
    assert projected("second") == yard


def test_signal_estimate_and_attention_offer_identities_cannot_collapse(
    rich_context,
) -> None:
    frame = rich_context["frame"]
    estimate = rich_context["estimate"]
    assert isinstance(frame, ContextFrame)
    signal = frame.orienting_signals[0]
    assert estimate.estimate_ref.startswith("signal-estimate@sha256:")
    assert signal.signal_ref.startswith("orienting-signal@sha256:")
    assert estimate.estimate_ref != signal.signal_ref

    payload = frame.model_dump(mode="json", by_alias=True)
    payload["orienting_signals"][0]["estimate_refs"] = [signal.signal_ref]
    _rehash_addressed(
        payload["orienting_signals"][0],
        domain="hapax.orienting-signal.v1",
        ref_field="signal_ref",
        hash_field="signal_hash",
        prefix="orienting-signal",
    )
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="estimates must resolve"):
        ContextFrame.model_validate(payload)


def test_denied_signal_value_evidence_is_deny_oblivious(rich_context) -> None:
    frame = rich_context["frame"]
    yard = rich_context["yard"]
    private_observation = rich_context["private_observation"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(yard, ProjectionEnvelope)
    allow_all = next(item.air for item in frame.air_bindings if item.object_kind == "temporal")

    def projected(value: str) -> ProjectionEnvelope:
        payload = frame.model_dump(mode="json", by_alias=True)
        signal = payload["orienting_signals"][0]
        for axis in signal["value_vector"].values():
            axis["value"]["value"] = value
            axis["evidence_refs"] = [private_observation.observation_ref]
        _rehash_addressed(
            signal,
            domain="hapax.orienting-signal.v1",
            ref_field="signal_ref",
            hash_field="signal_hash",
            prefix="orienting-signal",
        )
        signal_binding = next(
            item
            for item in payload["air_bindings"]
            if item["object_kind"] == "signal" and item["object_ref"] == signal["signal_id"]
        )
        signal_binding["air"] = allow_all.model_dump(mode="json")
        _rehash_frame(payload)
        changed = ContextFrame.model_validate(payload)
        return project_context_frame(
            changed,
            audience="yard_context",
            purpose=yard.purpose,
            depth=yard.depth,
            device_class=yard.device_class,
            register=yard.register_mode,
            decoder_ref=yard.decoder_ref,
            focus_ref=yard.focus_ref,
            producer_ref=yard.producer_ref,
            generated_at=yard.generated_at,
            orientation_ref=yard.orientation.facet_ref if yard.orientation else None,
        )

    first = projected("0.2")
    second = projected("0.9")
    assert first == second
    assert not first.orienting_signals
    assert private_observation.observation_ref not in first.model_dump_json()


def test_uncalibrated_or_ood_model_estimates_must_abstain(rich_context) -> None:
    with pytest.raises(ValidationError, match="must abstain"):
        ContextConfidence(
            word="medium",
            method="statistical",
            evidence_refs=("evidence:test",),
            calibration_ref=None,
            calibration_metric=None,
            validity_domain_refs=("domain:test",),
            distribution_state="unknown",
            abstained=False,
        )

    estimate = rich_context["estimate"]
    body = estimate.model_dump(mode="python", exclude={"estimate_ref", "estimate_hash"})
    body["confidence"] = ContextConfidence(
        word="low",
        method="statistical",
        evidence_refs=("evidence:test",),
        calibration_ref="calibration:test",
        calibration_metric=CanonicalDecimal(value="0.1", unit="ece"),
        validity_domain_refs=("domain:test",),
        distribution_state="out_of_distribution",
        abstained=True,
    )
    body["state"] = ContextState(value_state="present", reason_codes=())
    with pytest.raises(ValidationError, match="abstained signal estimates"):
        build_signal_estimate(**body)


def test_temporal_scale_tense_and_surprise_are_independent(rich_context) -> None:
    temporal = rich_context["temporal"]
    estimate = rich_context["estimate"]
    base = temporal.model_dump(mode="python", exclude={"temporal_ref", "temporal_hash"})
    retention = build_temporal_coordinate(**{**base, "tense": "retention"})
    protention = build_temporal_coordinate(
        **{
            **base,
            "tense": "protention",
            "forecast_horizon_ref": "horizon:bounded",
        }
    )
    other_scale = build_temporal_coordinate(**{**base, "scale_ref": "scale:cross-session"})
    surprise_body = estimate.model_dump(mode="python", exclude={"estimate_ref", "estimate_hash"})
    surprise = build_signal_estimate(
        **{
            **surprise_body,
            "estimate_id": "estimate:surprise",
            "kind": "surprise",
            "value": {"posterior_delta": "0.7"},
        }
    )
    assert retention.scale_ref == protention.scale_ref == temporal.scale_ref
    assert {retention.tense, protention.tense, temporal.tense} == {
        "retention",
        "impression",
        "protention",
    }
    assert other_scale.tense == temporal.tense
    assert other_scale.scale_ref != temporal.scale_ref
    assert surprise.kind == "surprise"
    assert "surprise" not in type(temporal).model_fields


def test_temporal_ancestry_must_resolve_and_is_air_sealed(rich_context) -> None:
    frame = rich_context["frame"]
    yard = rich_context["yard"]
    temporal = rich_context["temporal"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(yard, ProjectionEnvelope)

    dangling = frame.model_dump(mode="json", by_alias=True)
    root_temporal = next(
        item for item in dangling["temporal_coordinates"] if not item["parent_span_refs"]
    )
    root_temporal["parent_span_refs"] = ["temporal-coordinate@sha256:" + "0" * 64]
    _rehash_addressed(
        root_temporal,
        domain="hapax.temporal-coordinate.v1",
        ref_field="temporal_ref",
        hash_field="temporal_hash",
        prefix="temporal-coordinate",
    )
    dangling["temporal_coordinates"].sort(key=lambda item: item["temporal_ref"])
    _rehash_frame(dangling)
    with pytest.raises(ValidationError, match="temporal ancestry"):
        ContextFrame.model_validate(dangling)

    private_air = next(
        item.air
        for item in frame.air_bindings
        if item.object_kind == "observation"
        and item.object_ref == rich_context["private_observation"].observation_ref
    )
    allow_all = next(item.air for item in frame.air_bindings if item.object_kind == "temporal")
    base = temporal.model_dump(mode="python", exclude={"temporal_ref", "temporal_hash"})

    def projected(secret: str) -> ProjectionEnvelope:
        parent = build_temporal_coordinate(
            **{
                **base,
                "window_ref": f"window:private-{secret}",
                "scale_ref": "scale:private-parent",
                "parent_span_refs": (),
            }
        )
        child = build_temporal_coordinate(
            **{
                **base,
                "window_ref": "window:private-child",
                "scale_ref": "scale:private-child",
                "parent_span_refs": (parent.temporal_ref,),
            }
        )
        payload = frame.model_dump(mode="json", by_alias=True)
        payload["temporal_coordinates"].extend(
            (parent.model_dump(mode="json"), child.model_dump(mode="json"))
        )
        payload["temporal_coordinates"].sort(key=lambda item: item["temporal_ref"])
        payload["air_bindings"].extend(
            (
                ContextAirBinding(
                    object_kind="temporal",
                    object_ref=parent.temporal_ref,
                    air=private_air,
                ).model_dump(mode="json"),
                ContextAirBinding(
                    object_kind="temporal",
                    object_ref=child.temporal_ref,
                    air=allow_all,
                ).model_dump(mode="json"),
            )
        )
        payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
        _rehash_frame(payload)
        changed = ContextFrame.model_validate(payload)
        return project_context_frame(
            changed,
            audience="yard_context",
            purpose=yard.purpose,
            depth=yard.depth,
            device_class=yard.device_class,
            register=yard.register_mode,
            decoder_ref=yard.decoder_ref,
            focus_ref=yard.focus_ref,
            producer_ref=yard.producer_ref,
            generated_at=yard.generated_at,
            orientation_ref=yard.orientation.facet_ref if yard.orientation else None,
        )

    first = projected("a")
    second = projected("b")
    assert first == second == yard
    assert "private-parent" not in first.model_dump_json()
    assert "private-child" not in first.model_dump_json()


def test_future_event_causation_fails_closed(rich_context) -> None:
    frame = rich_context["frame"]
    scope = rich_context["scope"]
    temporal = rich_context["temporal"]
    resolution = rich_context["resolution"]
    assert isinstance(frame, ContextFrame)
    later = max(frame.events, key=lambda item: item.occurred_at)
    future_caused = build_epistemic_flow_event(
        event_id="event:future-caused",
        kind="observation_recorded",
        session_ref=frame.session_ref,
        task_ref=frame.task_ref,
        trace_ref="trace:future-caused",
        position_ref=frame.position.position_ref,
        scope_ref=scope.scope_ref,
        temporal_ref=temporal.temporal_ref,
        resolution_ref=resolution.resolution_ref,
        generation=1,
        subject_ref="subject:future-caused",
        occurred_at=temporal.event_time_start,
        expires_at=temporal.valid_until,
        producer_ref="producer:observer",
        method_ref="method:deterministic",
        privacy_class="operator_private",
        authority_ceiling="projection_only",
        source_refs=(rich_context["private_observation"].observation_ref,),
        caused_by=(later.event_ref,),
        supersedes_refs=(),
        derivation_depth=1,
        payload={
            "observation_ref": rich_context["private_observation"].observation_ref,
            "observation_state": "future_cause_canary",
        },
        state=ContextState(value_state="present", reason_codes=()),
    )
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["events"].append(future_caused.model_dump(mode="json"))
    payload["events"].sort(
        key=lambda item: (
            item["occurred_at"],
            item["generation"],
            item["derivation_depth"],
            item["event_ref"],
        )
    )
    payload["air_bindings"].append(
        {
            "object_kind": "event",
            "object_ref": future_caused.event_id,
            "air": next(
                item["air"] for item in payload["air_bindings"] if item["object_kind"] == "event"
            ),
        }
    )
    payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="cannot occur after"):
        ContextFrame.model_validate(payload)


def test_event_sources_and_impingement_actions_must_resolve(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    event_payload = frame.model_dump(mode="json", by_alias=True)
    event = event_payload["events"][-1]
    event["source_refs"] = ["evidence:unknown"]
    _rehash_addressed(
        event,
        domain="hapax.epistemic-flow-event.v1",
        ref_field="event_ref",
        hash_field="event_hash",
        prefix="epistemic-event",
    )
    _rehash_frame(event_payload)
    with pytest.raises(ValidationError, match="event sources must resolve"):
        ContextFrame.model_validate(event_payload)

    impingement_payload = frame.model_dump(mode="json", by_alias=True)
    impingement_payload["impingements"][0]["legal_next"] = ["action:unknown"]
    _rehash_frame(impingement_payload)
    with pytest.raises(ValidationError, match="impingements must reference"):
        ContextFrame.model_validate(impingement_payload)


def test_event_lineage_and_learning_witnesses_follow_air_dependencies(
    rich_context,
) -> None:
    frame = rich_context["frame"]
    yard = rich_context["yard"]
    operator = rich_context["operator"]
    private_observation = rich_context["private_observation"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(yard, ProjectionEnvelope)
    assert isinstance(operator, ProjectionEnvelope)

    event_payload = frame.model_dump(mode="json", by_alias=True)
    event = event_payload["events"][-1]
    temporal_binding = next(
        item
        for item in event_payload["air_bindings"]
        if item["object_kind"] == "temporal" and item["object_ref"] == event["temporal_ref"]
    )
    temporal_binding["air"]["yard_context"] = "deny"
    _rehash_frame(event_payload)
    event_frame = ContextFrame.model_validate(event_payload)
    changed_yard = project_context_frame(
        event_frame,
        audience="yard_context",
        purpose=yard.purpose,
        depth=yard.depth,
        device_class=yard.device_class,
        register=yard.register_mode,
        decoder_ref=yard.decoder_ref,
        focus_ref=yard.focus_ref,
        producer_ref=yard.producer_ref,
        generated_at=yard.generated_at,
        orientation_ref=yard.orientation.facet_ref if yard.orientation else None,
    )
    assert event["event_ref"] not in changed_yard.lineage_refs
    assert event["temporal_ref"] not in changed_yard.model_dump_json()

    learning_payload = frame.model_dump(mode="json", by_alias=True)
    learning = learning_payload["signal_learning_receipts"][0]
    old_learning_ref = learning["learning_ref"]
    learning["witness_refs"] = [private_observation.observation_ref]
    _rehash_addressed(
        learning,
        domain="hapax.signal-learning-receipt.v1",
        ref_field="learning_ref",
        hash_field="learning_hash",
        prefix="signal-learning",
    )
    next(
        item
        for item in learning_payload["air_bindings"]
        if item["object_kind"] == "learning_receipt" and item["object_ref"] == old_learning_ref
    )["object_ref"] = learning["learning_ref"]
    private_binding = next(
        item
        for item in learning_payload["air_bindings"]
        if item["object_kind"] == "observation"
        and item["object_ref"] == private_observation.observation_ref
    )
    private_binding["air"]["operator_private"] = "deny"
    learning_payload["signal_learning_receipts"].sort(key=lambda item: item["learning_ref"])
    learning_payload["air_bindings"].sort(
        key=lambda item: (item["object_kind"], item["object_ref"])
    )
    _rehash_frame(learning_payload)
    learning_frame = ContextFrame.model_validate(learning_payload)
    changed_operator = project_context_frame(
        learning_frame,
        audience="operator_private",
        purpose=operator.purpose,
        depth=operator.depth,
        device_class=operator.device_class,
        register=operator.register_mode,
        decoder_ref=operator.decoder_ref,
        focus_ref=operator.focus_ref,
        producer_ref=operator.producer_ref,
        generated_at=operator.generated_at,
        orientation_ref=operator.orientation.facet_ref if operator.orientation else None,
    )
    assert not changed_operator.signal_learning_receipts
    assert private_observation.observation_ref not in changed_operator.model_dump_json()


def test_legal_action_must_match_exact_lifecycle_admission(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    payload = frame.model_dump(mode="json", by_alias=True)
    execute = next(item for item in payload["actions"] if item["action_id"] == "action:execute")
    execute["admission_ref"] = "lifecycle-operation-admission@sha256:" + "0" * 64
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="operation admission"):
        ContextFrame.model_validate(payload)


def test_transition_identity_includes_edge_and_legality_requires_all_guards(
    rich_context,
) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    definition = frame.lifecycle_definition
    next_blocked = lifecycle_transition_admission_ref(definition, "S6", "BLOCKED", "next")
    fall_blocked = lifecycle_transition_admission_ref(definition, "S6", "BLOCKED", "fall")
    assert next_blocked != fall_blocked

    next_s7 = next(
        item
        for item in next(stage for stage in definition.stages if stage.token == "S6").next
        if item.to == "S7"
    )
    guard_evidence = tuple(
        LifecycleGuardEvidence(
            guard=guard,
            disposition="unknown" if guard == "evidence_present" else "satisfied",
            evidence_refs=("fact:position",),
            may_authorize=False,
        )
        for guard in next_s7.guards
    )
    with pytest.raises(ValidationError, match="legality must equal"):
        ContextAction(
            action_id="action:advance-s7",
            label="Advance to verification",
            disposition="legal",
            position_ref=frame.position.position_ref,
            action_class="lifecycle_transition",
            operation="lifecycle.transition",
            lifecycle_operation=None,
            transition_to="S7",
            transition_edge="next",
            admission_ref=lifecycle_transition_admission_ref(definition, "S6", "S7", "next"),
            guard_evidence=guard_evidence,
            source_fact_refs=("fact:position",),
            why="The implementation would advance only after every guard is satisfied.",
            predicted_effect="The lifecycle would enter runtime verification.",
            recovery="Remain at S6 while any guard is unknown.",
            expected_receipt_ref="receipt:advance-s7",
            state=ContextState(value_state="present", reason_codes=()),
            no_effect=True,
            may_authorize=False,
        )


def test_lens_constraints_precede_utility_and_constellation(rich_context) -> None:
    lens = rich_context["lens"]
    body = lens.model_dump(mode="python", exclude={"lens_ref", "lens_hash"})
    body["constraint_mask_refs"] = ()
    with pytest.raises(ValidationError, match="constraint_mask_refs"):
        build_signal_lens(**body)


def test_signal_graph_rejects_mixed_lenses_and_unknown_coverage(rich_context) -> None:
    frame = rich_context["frame"]
    lens = rich_context["lens"]
    assert isinstance(frame, ContextFrame)
    alternate = build_signal_lens(
        **{
            **lens.model_dump(mode="python", exclude={"lens_ref", "lens_hash"}),
            "lens_id": "lens:alternate-boundary",
            "purpose": "alternate_boundary_orientation",
        }
    )
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["signal_lenses"].append(alternate.model_dump(mode="json"))
    payload["signal_lenses"].sort(key=lambda item: item["lens_ref"])
    payload["air_bindings"].append(
        ContextAirBinding(
            object_kind="lens",
            object_ref=alternate.lens_ref,
            air=next(item.air for item in frame.air_bindings if item.object_kind == "lens"),
        ).model_dump(mode="json")
    )
    payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    signal = payload["orienting_signals"][0]
    signal["lens_ref"] = alternate.lens_ref
    _rehash_addressed(
        signal,
        domain="hapax.orienting-signal.v1",
        ref_field="signal_ref",
        hash_field="signal_hash",
        prefix="orienting-signal",
    )
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="lens differs"):
        ContextFrame.model_validate(payload)

    unknown = frame.model_dump(mode="json", by_alias=True)
    constellation = unknown["signal_constellations"][0]
    constellation["uncovered_source_refs"] = ["source-admission@sha256:" + "0" * 64]
    constellation["loss_manifest_ref"] = canon_module.signal_constellation_loss_manifest_ref(
        target_ref=constellation["target_ref"],
        lens_ref=constellation["lens_ref"],
        scope_ref=constellation["scope_ref"],
        resolution_ref=constellation["resolution_ref"],
        member_estimate_refs=tuple(constellation["member_estimate_refs"]),
        relation_refs=tuple(constellation["relation_refs"]),
        uncovered_source_refs=tuple(constellation["uncovered_source_refs"]),
        aggregation_ref=constellation["aggregation_ref"],
    )
    _rehash_addressed(
        constellation,
        domain="hapax.signal-constellation.v1",
        ref_field="constellation_ref",
        hash_field="constellation_hash",
        prefix="signal-constellation",
    )
    _rehash_frame(unknown)
    with pytest.raises(ValidationError, match="uncovered sources"):
        ContextFrame.model_validate(unknown)


def test_projection_local_graph_rejects_rehashed_signal_forgery(rich_context) -> None:
    projection = rich_context["operator"]
    assert isinstance(projection, ProjectionEnvelope)
    payload = projection.model_dump(mode="json", by_alias=True)
    constellation = payload["signal_constellations"][0]
    constellation["uncovered_source_refs"] = ["source-admission@sha256:" + "0" * 64]
    constellation["loss_manifest_ref"] = canon_module.signal_constellation_loss_manifest_ref(
        target_ref=constellation["target_ref"],
        lens_ref=constellation["lens_ref"],
        scope_ref=constellation["scope_ref"],
        resolution_ref=constellation["resolution_ref"],
        member_estimate_refs=tuple(constellation["member_estimate_refs"]),
        relation_refs=tuple(constellation["relation_refs"]),
        uncovered_source_refs=tuple(constellation["uncovered_source_refs"]),
        aggregation_ref=constellation["aggregation_ref"],
    )
    _rehash_addressed(
        constellation,
        domain="hapax.signal-constellation.v1",
        ref_field="constellation_ref",
        hash_field="constellation_hash",
        prefix="signal-constellation",
    )
    _rehash_projection(payload)
    with pytest.raises(ValidationError, match="uncovered sources"):
        ProjectionEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("position", "exact position"),
        ("admission", "differs from its admission"),
        ("operation", "not admitted"),
    ],
)
def test_projection_lifecycle_actions_bind_full_position_law(
    rich_context, mutation: str, expected: str
) -> None:
    projection = rich_context["operator"]
    assert isinstance(projection, ProjectionEnvelope)
    payload = projection.model_dump(mode="json", by_alias=True)
    action = next(item for item in payload["actions"] if item["action_id"] == "action:execute")
    if mutation == "position":
        action["position_ref"] = "context-position@sha256:" + "0" * 64
    elif mutation == "admission":
        action["admission_ref"] = "lifecycle-operation-admission@sha256:" + "0" * 64
    else:
        action["lifecycle_operation"] = "unadmitted_operation"
        action["operation"] = "unadmitted_operation"
        action["admission_ref"] = "lifecycle-operation-admission@sha256:" + "0" * 64
    _rehash_projection(payload)
    with pytest.raises(ValidationError, match=expected):
        ProjectionEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    ("collection", "field", "value", "expected"),
    [
        ("impingements", "summary", "Forged summary", "impingements differ"),
        ("portal_offers", "purpose", "forged_purpose", "portals differ"),
    ],
)
def test_projection_position_commitments_bind_context_collections(
    rich_context, collection: str, field: str, value: str, expected: str
) -> None:
    projection = rich_context["operator"]
    assert isinstance(projection, ProjectionEnvelope)
    payload = projection.model_dump(mode="json", by_alias=True)
    payload[collection][0][field] = value
    _rehash_projection(payload)
    with pytest.raises(ValidationError, match=expected):
        ProjectionEnvelope.model_validate(payload)


@pytest.mark.parametrize("mutation", ["state", "expired", "predates_evidence"])
def test_projection_state_and_time_are_derived_not_asserted(rich_context, mutation: str) -> None:
    projection = rich_context["operator"]
    assert isinstance(projection, ProjectionEnvelope)
    payload = projection.model_dump(mode="json", by_alias=True)
    if mutation == "state":
        payload["state"] = {
            "value_state": "dark",
            "reason_codes": ["forged_projection_state"],
        }
        expected = "state must derive"
    elif mutation == "expired":
        payload["generated_at"] = payload["stale_after"]
        expected = "strictly precede"
    else:
        payload["generated_at"] = "2000-01-01T00:00:00Z"
        expected = "precedes its visible evidence"
    _rehash_projection(payload)
    with pytest.raises(ValidationError, match=expected):
        ProjectionEnvelope.model_validate(payload)


def test_learning_receipt_and_projection_loss_are_content_addressed(
    rich_context,
) -> None:
    receipt = rich_context["learning_receipt"]
    payload = receipt.model_dump(mode="json")
    payload["outcome_ref"] = "outcome:forged"
    with pytest.raises(ValidationError, match="learning_hash"):
        type(receipt).model_validate(payload)

    manifest = build_projection_mapping_manifest()
    mapped_source_paths = {
        mapping.split("->", 1)[0]
        for mapping in manifest.field_mappings
        if mapping.startswith("/source/") and mapping.split("->", 1)[0].count("/") == 2
    }
    omitted_source_paths = {path for path in manifest.omitted_field_paths if path.count("/") == 2}
    expected_source_paths = {
        f"/source/{field.alias or name}" for name, field in ContextFrame.model_fields.items()
    }
    assert mapped_source_paths | omitted_source_paths == expected_source_paths
    assert mapped_source_paths & omitted_source_paths == set()
    mapped_projection_paths = {
        mapping.split("->", 1)[1]
        for mapping in manifest.field_mappings
        if mapping.split("->", 1)[1].count("/") == 2
    }
    expected_projection_paths = {
        f"/projection/{field.alias or name}"
        for name, field in ProjectionEnvelope.model_fields.items()
    }
    assert mapped_projection_paths == expected_projection_paths
    assert "/source/facts/*/air" in manifest.omitted_field_paths
    assert {
        f"/source/facts/*/{field.alias or name}"
        for name, field in canon_module.ContextFact.model_fields.items()
    } == {
        mapping.split("->", 1)[0]
        for mapping in manifest.field_mappings
        if mapping.startswith("/source/facts/*/")
    } | {"/source/facts/*/air"}
    assert "/source/air_bindings/*" in manifest.omitted_field_paths
    event_fields = {
        field.alias or name for name, field in canon_module.EpistemicFlowEvent.model_fields.items()
    }
    assert {
        f"/source/events/*/{field}->/projection/events/*/{field}" for field in event_fields
    } <= set(manifest.field_mappings)
    assert not any(path.startswith("/source/events/*/") for path in manifest.omitted_field_paths)
    for name in ("operator", "yard", "hapax"):
        projection = rich_context[name]
        assert projection.mapping_manifest == manifest
        assert projection.loss.manifest_ref == manifest.manifest_ref
        assert projection.loss.manifest_hash == manifest.manifest_hash


def test_rehashed_frame_cross_binding_forgery_is_rejected(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["position"]["canon_id"] = "coordination-canon@sha256:" + "f" * 64
    _rehash_position(payload["position"])
    _rehash_frame(payload)
    with pytest.raises(ValidationError):
        ContextFrame.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("evidence", "named derivation inputs"),
        ("supersession", "fact supersession"),
    ],
)
def test_fact_evidence_and_supersession_must_be_acyclic(
    rich_context, mutation: str, expected: str
) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    payload = frame.model_dump(mode="json", by_alias=True)
    facts = {item["fact_id"]: item for item in payload["facts"]}
    left = facts["fact:capability-gap"]
    right = facts["fact:position"]
    if mutation == "evidence":
        left["provenance"]["source_refs"] = [right["fact_id"]]
        left["confidence"]["evidence_refs"] = [right["fact_id"]]
        right["provenance"]["source_refs"] = [left["fact_id"]]
        right["confidence"]["evidence_refs"] = [left["fact_id"]]
    else:
        left["supersedes_refs"] = [right["fact_id"]]
        right["supersedes_refs"] = [left["fact_id"]]
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match=expected):
        ContextFrame.model_validate(payload)


def test_present_facts_require_live_provenance_and_derivation(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)

    expired = frame.model_dump(mode="json", by_alias=True)
    position_fact = next(item for item in expired["facts"] if item["fact_id"] == "fact:position")
    position_fact["provenance"]["stale_after"] = expired["checked_at"]
    _rehash_frame(expired)
    with pytest.raises(ValidationError, match="unexpired provenance"):
        ContextFrame.model_validate(expired)

    held = frame.model_dump(mode="json", by_alias=True)
    derivation = next(
        item for item in held["derivations"] if "fact:position" in item["output_refs"]
    )
    old_ref = derivation["derivation_ref"]
    derivation["state"] = {
        "value_state": "hold",
        "reason_codes": ["derivation_held"],
    }
    _rehash_addressed(
        derivation,
        domain="hapax.derivation-record.v1",
        ref_field="derivation_ref",
        hash_field="derivation_hash",
        prefix="derivation-record",
    )
    next(item for item in held["facts"] if item["fact_id"] == "fact:position")["derivation_ref"] = (
        derivation["derivation_ref"]
    )
    next(
        item
        for item in held["air_bindings"]
        if item["object_kind"] == "derivation" and item["object_ref"] == old_ref
    )["object_ref"] = derivation["derivation_ref"]
    held["derivations"].sort(key=lambda item: item["derivation_ref"])
    held["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(held)
    with pytest.raises(ValidationError, match="present facts require a present derivation"):
        ContextFrame.model_validate(held)


def test_every_fact_and_estimate_has_one_derivation_owner(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    source = next(item for item in frame.derivations if "fact:position" in item.output_refs)
    duplicate = build_derivation_record(
        **{
            **source.model_dump(mode="python", exclude={"derivation_ref", "derivation_hash"}),
            "derivation_id": "derivation:duplicate-owner",
        }
    )
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["derivations"].append(duplicate.model_dump(mode="json"))
    payload["derivations"].sort(key=lambda item: item["derivation_ref"])
    payload["air_bindings"].append(
        ContextAirBinding(
            object_kind="derivation",
            object_ref=duplicate.derivation_ref,
            air=next(
                item.air
                for item in frame.air_bindings
                if item.object_kind == "derivation" and item.object_ref == source.derivation_ref
            ),
        ).model_dump(mode="json")
    )
    payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="one derivation owner"):
        ContextFrame.model_validate(payload)


def test_frame_requires_one_exact_lifecycle_fsm_fact(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["facts"] = [fact for fact in payload["facts"] if fact["fact_type"] != "lifecycle_fsm"]
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="exactly one lifecycle_fsm"):
        ContextFrame.model_validate(payload)

    payload = frame.model_dump(mode="json", by_alias=True)
    duplicate = next(
        fact.copy() for fact in payload["facts"] if fact["fact_type"] == "lifecycle_fsm"
    )
    duplicate["fact_id"] = "fact:lifecycle-fsm-duplicate"
    payload["facts"].append(duplicate)
    payload["facts"].sort(key=lambda fact: fact["fact_id"])
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="exactly one lifecycle_fsm"):
        ContextFrame.model_validate(payload)

    payload = frame.model_dump(mode="json", by_alias=True)
    lifecycle_fact = next(fact for fact in payload["facts"] if fact["fact_type"] == "lifecycle_fsm")
    changed = json.loads(lifecycle_fact["data"]["canonical_json"])
    changed["what"] += " changed"
    lifecycle_fact["data"] = build_canonical_json_object(changed).model_dump(mode="json")
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="exactly bind"):
        ContextFrame.model_validate(payload)

    payload = frame.model_dump(mode="json", by_alias=True)
    payload["position"]["lifecycle_fsm_data_sha256"] = "0" * 64
    _rehash_position(payload["position"])
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="position commitment"):
        ContextFrame.model_validate(payload)


def test_lifecycle_fsm_is_visible_and_exact_for_every_canonical_audience(
    rich_context,
) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    image = frame.canon_image
    for audience in ("operator", "yard", "hapax"):
        projection = rich_context[audience]
        assert isinstance(projection, ProjectionEnvelope)
        facts = tuple(
            fact
            for fact in projection.facts
            if isinstance(fact, ProjectedFact) and fact.fact_type == "lifecycle_fsm"
        )
        assert len(facts) == 1
        fact = facts[0]
        assert isinstance(fact, ProjectedFact)
        payload = json.loads(fact.data.canonical_json)
        assert payload["what"] == image.rendered_strata.what
        assert payload["how"] == image.rendered_strata.how
        assert payload["must"] == image.rendered_strata.must
        assert payload["stage"] == {
            "level": image.level.value,
            "projection_scope": list(image.projection_scope),
            "token": image.stage_token,
        }
        assert payload["canon"]["image_hash"] == image.image_hash
        assert payload["kernel"] == image.kernel.model_dump(mode="json")
        assert fact.no_effect is True
        assert fact.may_authorize is False

    payload = rich_context["operator"].model_dump(mode="json", by_alias=True)
    lifecycle_fact = next(fact for fact in payload["facts"] if fact["fact_type"] == "lifecycle_fsm")
    changed = json.loads(lifecycle_fact["data"]["canonical_json"])
    changed["must"] += " changed"
    lifecycle_fact["data"] = build_canonical_json_object(changed).model_dump(mode="json")
    _rehash_projection(payload)
    with pytest.raises(ValidationError, match="position commitment"):
        ProjectionEnvelope.model_validate(payload)


def test_projection_content_address_is_not_producer_authentication(rich_context) -> None:
    frame = rich_context["frame"]
    rendered = rich_context["operator"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(rendered, ProjectionEnvelope)
    operator = project_context_frame(
        frame,
        audience="operator_private",
        purpose="operation",
        depth=rendered.depth,
        device_class=rendered.device_class,
        register=rendered.register_mode,
        decoder_ref=rendered.decoder_ref,
        focus_ref=rendered.focus_ref,
        producer_ref=rendered.producer_ref,
        generated_at=rendered.generated_at,
    )
    payload = operator.model_dump(mode="json", by_alias=True)
    position_fact = next(
        fact for fact in payload["facts"] if fact.get("fact_id") == "fact:position"
    )
    changed_data = build_canonical_json_object({"stage": "S6", "self_consistent_forgery": True})
    position_fact["data"] = changed_data.model_dump(mode="json")
    _rehash_projection(payload)
    structurally_valid = ProjectionEnvelope.model_validate(payload)
    assert structurally_valid.producer_verification_required is True
    assert structurally_valid.verification_scope == "structure_and_content_address_only"
    with pytest.raises(ValueError, match="deterministic audience seal"):
        verify_projection(frame, structurally_valid)


def test_lifecycle_fsm_cannot_be_hidden_from_a_canonical_audience(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    payload = frame.model_dump(mode="json", by_alias=True)
    lifecycle_fact = next(fact for fact in payload["facts"] if fact["fact_type"] == "lifecycle_fsm")
    lifecycle_fact["air"]["yard_context"] = "deny"
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="canonical audience"):
        ContextFrame.model_validate(payload)


def test_projection_structural_integers_are_json_interoperable(rich_context) -> None:
    operator = rich_context["operator"]
    assert isinstance(operator, ProjectionEnvelope)
    payload = operator.model_dump(mode="json", by_alias=True)
    payload["position"]["canon_version"] = 1 << 53
    with pytest.raises(ValidationError, match="less than or equal"):
        ProjectionEnvelope.model_validate(payload)

    payload = operator.model_dump(mode="json", by_alias=True)
    payload["position"]["canon_version"] = "1"
    with pytest.raises(ValidationError):
        ProjectionEnvelope.model_validate(payload)

    payload = operator.model_dump(mode="json", by_alias=True)
    payload["position"]["canon_version"] = 1.0
    with pytest.raises(ValidationError):
        ProjectionEnvelope.model_validate(payload)


@pytest.mark.parametrize("malformed_path", ["projection_scope", "omitted_atom_ids"])
def test_malformed_lifecycle_fsm_arrays_fail_typed(rich_context, malformed_path) -> None:
    frame = rich_context["frame"]
    rendered = rich_context["operator"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(rendered, ProjectionEnvelope)
    projection = project_context_frame(
        frame,
        audience="operator_private",
        purpose="operation",
        depth=rendered.depth,
        device_class=rendered.device_class,
        register=rendered.register_mode,
        decoder_ref=rendered.decoder_ref,
        focus_ref=rendered.focus_ref,
        producer_ref=rendered.producer_ref,
        generated_at=rendered.generated_at,
    )
    payload = projection.model_dump(mode="json", by_alias=True)
    lifecycle_fact = next(
        fact for fact in payload["facts"] if fact.get("fact_type") == "lifecycle_fsm"
    )
    changed = json.loads(lifecycle_fact["data"]["canonical_json"])
    if malformed_path == "projection_scope":
        changed["stage"]["projection_scope"] = [{}]
    else:
        changed["kernel"]["omitted_atom_ids"] = [{}]
    changed_data = build_canonical_json_object(changed)
    lifecycle_fact["data"] = changed_data.model_dump(mode="json")
    payload["position"]["lifecycle_fsm_data_sha256"] = changed_data.sha256
    _rehash_position(payload["position"])
    _rehash_projection(payload)
    with pytest.raises(ValidationError):
        ProjectionEnvelope.model_validate(payload)


def test_projection_seals_denied_fact_before_every_derivation(rich_context) -> None:
    frame = rich_context["frame"]
    yard = rich_context["yard"]
    orientation = rich_context["orientation"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(yard, ProjectionEnvelope)
    assert isinstance(orientation, BoundaryOrientationFacet)
    payload = frame.model_dump(mode="json", by_alias=True)
    canary = next(item for item in payload["facts"] if item["fact_id"] == "fact:private-canary")
    position_fact = next(item for item in payload["facts"] if item["fact_id"] == "fact:position")
    changed = build_canonical_json_object({"secret": "canary-b"})
    canary["data"] = changed.model_dump(mode="json")
    position_fact["supersedes_refs"] = ["fact:private-canary"]
    _rehash_frame(payload)
    changed_frame = ContextFrame.model_validate(payload)
    changed_projection = project_context_frame(
        changed_frame,
        audience="yard_context",
        purpose="orientation",
        depth=yard.depth,
        device_class=yard.device_class,
        register=yard.register_mode,
        decoder_ref=yard.decoder_ref,
        focus_ref=yard.focus_ref,
        producer_ref=yard.producer_ref,
        generated_at=yard.generated_at,
        orientation_ref=orientation.facet_ref,
    )
    assert changed_projection == yard
    assert "fact:private-canary" not in canonical_json_bytes(changed_projection).decode()


def test_projection_rejects_denied_focus_and_orientation_evidence(rich_context) -> None:
    frame = rich_context["frame"]
    yard = rich_context["yard"]
    orientation = rich_context["orientation"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(yard, ProjectionEnvelope)
    assert isinstance(orientation, BoundaryOrientationFacet)
    with pytest.raises(ValueError, match="focus"):
        project_context_frame(
            frame,
            audience="yard_context",
            purpose="orientation",
            depth=yard.depth,
            device_class=yard.device_class,
            register=yard.register_mode,
            decoder_ref=yard.decoder_ref,
            focus_ref="fact:private-canary",
            producer_ref=yard.producer_ref,
            generated_at=yard.generated_at,
            orientation_ref=orientation.facet_ref,
        )
    with pytest.raises(ValueError, match="not bound"):
        project_context_frame(
            frame,
            audience="yard_context",
            purpose="orientation",
            depth=yard.depth,
            device_class=yard.device_class,
            register=yard.register_mode,
            decoder_ref=yard.decoder_ref,
            focus_ref=yard.focus_ref,
            producer_ref=yard.producer_ref,
            generated_at=yard.generated_at,
            orientation_ref="boundary-orientation@sha256:" + "0" * 64,
        )


def test_projection_event_lineage_is_air_sealed(rich_context) -> None:
    bundle = rich_context["bundle"]
    frame = rich_context["frame"]
    yard = rich_context["yard"]
    orientation = rich_context["orientation"]
    assert isinstance(bundle, CanonBundle)
    assert isinstance(frame, ContextFrame)
    assert isinstance(yard, ProjectionEnvelope)
    assert isinstance(orientation, BoundaryOrientationFacet)
    assert yard.events == frame.events
    assert yard.lineage_refs[len(frame.position.receipt_lineage) :] == tuple(
        event.event_ref for event in yard.events
    )
    denied_event = build_epistemic_flow_event(
        event_id="event:private-canary",
        kind="observation_recorded",
        session_ref=frame.session_ref,
        task_ref=frame.task_ref,
        trace_ref="trace:private-canary",
        position_ref=frame.position.position_ref,
        scope_ref=rich_context["scope"].scope_ref,
        temporal_ref=rich_context["temporal"].temporal_ref,
        resolution_ref=rich_context["resolution"].resolution_ref,
        generation=1,
        subject_ref="private:canary",
        occurred_at="2026-07-10T16:00:00Z",
        expires_at=frame.stale_after,
        producer_ref="producer:observer",
        method_ref="method:deterministic",
        privacy_class="operator_private",
        authority_ceiling="observation_only",
        source_refs=(rich_context["private_observation"].observation_ref,),
        caused_by=(frame.position.receipt_lineage[0],),
        supersedes_refs=(),
        derivation_depth=0,
        payload={
            "observation_ref": rich_context["private_observation"].observation_ref,
            "observation_state": "event_canary",
        },
        state=ContextState(value_state="present", reason_codes=()),
    )
    changed_frame = build_context_frame(
        bundle,
        frame.canon_image,
        frame.position,
        session_ref=frame.session_ref,
        task_ref=frame.task_ref,
        demand_shape=frame.demand_shape,
        scopes=frame.scopes,
        temporal_coordinates=frame.temporal_coordinates,
        resolution_coordinates=frame.resolution_coordinates,
        source_admissions=frame.source_admissions,
        observations=frame.observations,
        derivations=frame.derivations,
        facts=frame.facts,
        relations=frame.relations,
        actions=frame.actions,
        impingements=frame.impingements,
        signal_estimates=frame.signal_estimates,
        signal_lenses=frame.signal_lenses,
        signal_constellations=frame.signal_constellations,
        orienting_signals=frame.orienting_signals,
        portal_offers=frame.portal_offers,
        signal_learning_receipts=frame.signal_learning_receipts,
        events=(*frame.events, denied_event),
        orientation_facets=frame.orientation_facets,
        lifecycle_possibilities=frame.lifecycle_possibilities,
        air_bindings=(
            *frame.air_bindings,
            ContextAirBinding(
                object_kind="event",
                object_ref=denied_event.event_id,
                air=ContextAirPolicy(
                    operator_private="allow",
                    yard_context="deny",
                    hapax_substrate="allow",
                    public_or_air="deny",
                    derived_channel_sealed=True,
                ),
            ),
        ),
        audience_policy_generation=frame.audience_policy_generation,
        privacy_policy_generation=frame.privacy_policy_generation,
        observed_at=frame.observed_at,
        checked_at=frame.checked_at,
        stale_after=frame.stale_after,
    )
    projection = project_context_frame(
        changed_frame,
        audience="yard_context",
        purpose="orientation",
        depth=yard.depth,
        device_class=yard.device_class,
        register=yard.register_mode,
        decoder_ref=yard.decoder_ref,
        focus_ref=yard.focus_ref,
        producer_ref=yard.producer_ref,
        generated_at=yard.generated_at,
        orientation_ref=orientation.facet_ref,
    )
    assert projection == yard
    assert projection.events == frame.events
    assert denied_event.event_ref not in canonical_json_bytes(projection).decode()


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra"])
def test_frame_air_bindings_are_exact_total_and_unique(rich_context, mutation) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    payload = frame.model_dump(mode="json", by_alias=True)
    if mutation == "missing":
        payload["air_bindings"].pop()
    elif mutation == "duplicate":
        payload["air_bindings"].append(payload["air_bindings"][0].copy())
        payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    else:
        payload["air_bindings"].append(
            {
                "object_kind": "signal",
                "object_ref": "signal:unbound",
                "air": payload["air_bindings"][0]["air"],
            }
        )
        payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="AIR bindings"):
        ContextFrame.model_validate(payload)


def test_audience_mismatched_signal_is_denied_and_operator_signal_is_live(
    rich_context,
) -> None:
    frame = rich_context["frame"]
    yard = rich_context["yard"]
    operator = rich_context["operator"]
    orientation = rich_context["orientation"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(yard, ProjectionEnvelope)
    assert isinstance(operator, ProjectionEnvelope)
    assert isinstance(orientation, BoundaryOrientationFacet)
    assert not yard.signal_lenses
    assert not yard.signal_constellations
    assert not yard.orienting_signals
    assert all(item.object_kind != "signal" for item in yard.redacted_objects)
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["orienting_signals"][0]["label"] = "Changed private signal label"
    _rehash_addressed(
        payload["orienting_signals"][0],
        domain="hapax.orienting-signal.v1",
        ref_field="signal_ref",
        hash_field="signal_hash",
        prefix="orienting-signal",
    )
    _rehash_frame(payload)
    changed_frame = ContextFrame.model_validate(payload)
    changed_yard = project_context_frame(
        changed_frame,
        audience="yard_context",
        purpose="orientation",
        depth=yard.depth,
        device_class=yard.device_class,
        register=yard.register_mode,
        decoder_ref=yard.decoder_ref,
        focus_ref=yard.focus_ref,
        producer_ref=yard.producer_ref,
        generated_at=yard.generated_at,
        orientation_ref=orientation.facet_ref,
    )
    changed_operator = project_context_frame(
        changed_frame,
        audience="operator_private",
        purpose="orientation",
        depth=operator.depth,
        device_class=operator.device_class,
        register=operator.register_mode,
        decoder_ref=operator.decoder_ref,
        focus_ref=operator.focus_ref,
        producer_ref=operator.producer_ref,
        generated_at=operator.generated_at,
        orientation_ref=orientation.facet_ref,
    )
    assert changed_yard == yard
    assert changed_operator != operator


def test_public_projection_is_constant_typed_dark_at_gate_zero(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    with pytest.raises(CanonError) as caught:
        project_context_frame(
            frame,
            audience="public_or_air",
            purpose="operation",
            depth="immediate",
            device_class="accessible_linear",
            register="plain",
            decoder_ref="decoder:context-v1",
            focus_ref="fact:capability-gap",
            producer_ref="producer:deterministic-projector",
            generated_at="2026-07-10T16:06:00Z",
        )
    assert caught.value.reason_code == "public_projection_not_constituted"
    assert "fact:" not in str(caught.value)


@pytest.mark.parametrize("object_kind", ["impingement", "portal"])
def test_position_committed_context_cannot_be_hidden(rich_context, object_kind) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    payload = frame.model_dump(mode="json", by_alias=True)
    binding = next(item for item in payload["air_bindings"] if item["object_kind"] == object_kind)
    binding["air"]["yard_context"] = "deny"
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="position-committed"):
        ContextFrame.model_validate(payload)


def test_projection_local_graph_cannot_reference_sealed_fact(rich_context) -> None:
    yard = rich_context["yard"]
    assert isinstance(yard, ProjectionEnvelope)
    payload = yard.model_dump(mode="json", by_alias=True)
    payload["relations"][0]["target_fact_ref"] = "fact:private-canary"
    _rehash_projection(payload)
    with pytest.raises(ValidationError, match="fully visible facts"):
        ProjectionEnvelope.model_validate(payload)

    reordered = yard.model_dump(mode="json", by_alias=True)
    reordered["actions"].reverse()
    _rehash_projection(reordered)
    with pytest.raises(ValidationError, match="sorted and unique"):
        ProjectionEnvelope.model_validate(reordered)


def test_projection_events_are_locally_closed_and_air_disjoint(rich_context) -> None:
    operator = rich_context["operator"]
    assert isinstance(operator, ProjectionEnvelope)

    reordered = operator.model_dump(mode="json", by_alias=True)
    reordered["events"].reverse()
    _rehash_projection(reordered)
    with pytest.raises(ValidationError, match="canonical causal order"):
        ProjectionEnvelope.model_validate(reordered)

    wrong_task = operator.model_dump(mode="json", by_alias=True)
    wrong_task_event = wrong_task["events"][-1]
    wrong_task_event["task_ref"] = "task:forged"
    _rehash_addressed(
        wrong_task_event,
        domain="hapax.epistemic-flow-event.v1",
        ref_field="event_ref",
        hash_field="event_hash",
        prefix="epistemic-event",
    )
    _rehash_projection(wrong_task)
    with pytest.raises(ValidationError, match="event task differs"):
        ProjectionEnvelope.model_validate(wrong_task)

    unknown_source = operator.model_dump(mode="json", by_alias=True)
    unknown_source_event = unknown_source["events"][-1]
    unknown_source_event["source_refs"] = ["fact:audience-hidden"]
    _rehash_addressed(
        unknown_source_event,
        domain="hapax.epistemic-flow-event.v1",
        ref_field="event_ref",
        hash_field="event_hash",
        prefix="epistemic-event",
    )
    _rehash_projection(unknown_source)
    with pytest.raises(ValidationError, match="event sources must resolve visibly"):
        ProjectionEnvelope.model_validate(unknown_source)

    overlap = operator.model_dump(mode="json", by_alias=True)
    overlap["redacted_objects"].append(
        {
            "object_kind": "event",
            "object_id": overlap["events"][0]["event_id"],
            "state": {
                "value_state": "dark",
                "reason_codes": ["audience_policy_redacted"],
            },
            "no_effect": True,
            "may_authorize": False,
        }
    )
    overlap["redacted_objects"].sort(key=lambda item: (item["object_kind"], item["object_id"]))
    _rehash_projection(overlap)
    with pytest.raises(ValidationError, match="both visible and redacted"):
        ProjectionEnvelope.model_validate(overlap)


def test_orientation_and_lifecycle_possibility_are_typed_and_no_effect(rich_context) -> None:
    frame = rich_context["frame"]
    possibility = rich_context["lifecycle_possibility"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(possibility, LifecyclePossibilityFacet)
    projection = project_context_frame(
        frame,
        audience="operator_private",
        purpose="lifecycle_possibility",
        depth="inspectable",
        device_class="monitor",
        register="formal",
        decoder_ref="decoder:context-v1",
        focus_ref="fact:capability-gap",
        producer_ref="producer:deterministic-projector",
        generated_at="2026-07-10T16:06:00Z",
        lifecycle_possibility_ref=possibility.facet_ref,
    )
    assert projection.lifecycle_possibility == possibility
    assert possibility.lawful_next == ("action:inspect",)
    assert projection.no_effect is True
    assert projection.may_authorize is False
    with pytest.raises(ValueError, match="operation purpose"):
        project_context_frame(
            frame,
            audience="operator_private",
            purpose="operation",
            depth="inspectable",
            device_class="monitor",
            register="formal",
            decoder_ref="decoder:context-v1",
            focus_ref="fact:capability-gap",
            producer_ref="producer:deterministic-projector",
            generated_at="2026-07-10T16:06:00Z",
            lifecycle_possibility_ref=possibility.facet_ref,
        )


def test_lifecycle_possibility_is_hidden_when_its_lawful_action_is_hidden(rich_context) -> None:
    frame = rich_context["frame"]
    possibility = rich_context["lifecycle_possibility"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(possibility, LifecyclePossibilityFacet)
    inspect_action = next(item for item in frame.actions if item.action_id == "action:inspect")
    consider_action = inspect_action.model_copy(
        update={
            "action_id": "action:consider-lifecycle",
            "label": "Consider lifecycle candidate",
            "expected_receipt_ref": "receipt:consider-lifecycle",
        }
    )
    changed_possibility = build_lifecycle_possibility_facet(
        facet_id=possibility.facet_id,
        candidate_ref=possibility.candidate_ref,
        source_fact_refs=possibility.source_fact_refs,
        why_now=possibility.why_now,
        does_not_prove=possibility.does_not_prove,
        uncertainty=possibility.uncertainty,
        alternative_dispositions=possibility.alternative_dispositions,
        unknown_fields=possibility.unknown_fields,
        candidate_plant=json.loads(possibility.candidate_plant.canonical_json),
        estimated_cost=json.loads(possibility.estimated_cost.canonical_json),
        plant_gap=possibility.plant_gap,
        harness_gap=possibility.harness_gap,
        measurement_gap=possibility.measurement_gap,
        lawful_next=(consider_action.action_id,),
    )
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["actions"].append(consider_action.model_dump(mode="json"))
    payload["actions"].sort(key=lambda item: item["action_id"])
    position_fact = next(item for item in payload["facts"] if item["fact_id"] == "fact:position")
    position_fact["legal_next"].append(consider_action.action_id)
    position_fact["legal_next"].sort()
    position_fact["expected_receipt_refs"].append(consider_action.expected_receipt_ref)
    position_fact["expected_receipt_refs"].sort()
    payload["lifecycle_possibilities"] = [
        changed_possibility.model_dump(mode="json", by_alias=True)
    ]
    inspect_air = next(
        binding.air
        for binding in frame.air_bindings
        if binding.object_kind == "action" and binding.object_ref == "action:inspect"
    )
    payload["air_bindings"].append(
        ContextAirBinding(
            object_kind="action",
            object_ref=consider_action.action_id,
            air=inspect_air.model_copy(update={"yard_context": "deny"}),
        ).model_dump(mode="json")
    )
    payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(payload)
    changed_frame = ContextFrame.model_validate(payload)

    with pytest.raises(ValueError, match="lifecycle_possibility_not_visible"):
        project_context_frame(
            changed_frame,
            audience="yard_context",
            purpose="lifecycle_possibility",
            depth="inspectable",
            device_class="monitor",
            register="formal",
            decoder_ref="decoder:context-v1",
            focus_ref="fact:capability-gap",
            producer_ref="producer:deterministic-projector",
            generated_at="2026-07-10T16:06:00Z",
            lifecycle_possibility_ref=changed_possibility.facet_ref,
        )


def test_typed_no_effect_event_braid_is_complete_and_separate(rich_context) -> None:
    frame = rich_context["frame"]
    operator = rich_context["operator"]
    learning = rich_context["learning_receipt"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(operator, ProjectionEnvelope)
    kinds = tuple(event.kind for event in frame.events)
    assert kinds == (
        "observation_recorded",
        "context_fact_derived",
        "context_frame_materialized",
        "projection_materialized",
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
        "receipt_recorded",
        "measurement_updated",
    )
    assert len(set(kinds)) == len(kinds)
    assert operator.events == frame.events
    payloads = {
        event.kind: event.payload.model_dump(mode="json", exclude={"kind"})
        for event in frame.events
    }
    assert payloads["intent_expressed"]["intent_kind"] == "explicit_probe_request"
    assert payloads["lease_referenced"]["lease_state"] == "absent"
    assert payloads["effect_observed"]["outcome_state"] == "unobserved"
    assert payloads["measurement_updated"]["learning_target_ref"] == learning.update_target_ref
    assert sum("learning_target_ref" in payload for payload in payloads.values()) == 1
    assert all(event.may_authorize is False for event in frame.events)


def test_orientation_projection_reduces_acquisition_without_losing_boundary_context(
    rich_context,
) -> None:
    frame = rich_context["frame"]
    yard = rich_context["yard"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(yard, ProjectionEnvelope)
    source_objects = sum(
        len(items)
        for items in (
            frame.observations,
            frame.derivations,
            frame.facts,
            frame.signal_lenses,
            frame.signal_constellations,
            frame.orienting_signals,
            frame.signal_learning_receipts,
        )
    )
    projected_objects = sum(
        len(items)
        for items in (
            yard.observations,
            yard.derivations,
            yard.facts,
            yard.signal_lenses,
            yard.signal_constellations,
            yard.orienting_signals,
            yard.signal_learning_receipts,
        )
    )
    assert projected_objects < source_objects
    assert yard.orientation is not None
    assert yard.orientation.why_now_refs
    assert yard.orientation.until
    assert yard.orientation.iff
    assert yard.legal_next


def test_locked_v1_is_same_frame_compatibility_with_content_addressed_loss(
    rich_context,
) -> None:
    frame = rich_context["frame"]
    operator = rich_context["operator"]
    yard = rich_context["yard"]
    hapax = rich_context["hapax"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(operator, ProjectionEnvelope)
    assert isinstance(yard, ProjectionEnvelope)
    assert isinstance(hapax, ProjectionEnvelope)
    compatibility = project_context_bundle_v1(
        frame,
        operator_private=operator,
        yard_context=yard,
        hapax_substrate=hapax,
    )
    verify_context_bundle_v1(
        frame,
        compatibility,
        operator_private=operator,
        yard_context=yard,
        hapax_substrate=hapax,
    )
    payload = compatibility.wire.model_dump(mode="json")
    assert set(payload) == {
        "kind",
        "session_ref",
        "task_ref",
        "strata",
        "tri_audience",
        "provenance",
        "demand_shape_fingerprint",
    }
    assert payload["strata"]["fsm"] == context_bundle_fsm(frame.canon_image)
    assert payload["provenance"]["source"].startswith("projection-set@sha256:")
    assert payload["demand_shape_fingerprint"] == frame.demand_shape.fingerprint
    assert set(compatibility.omitted_field_paths) == {
        *(f"/frame/{field.alias or name}" for name, field in ContextFrame.model_fields.items()),
        *(
            f"/projections/*/{field.alias or name}"
            for name, field in ProjectionEnvelope.model_fields.items()
        ),
    }
    assert compatibility.loss_state == "partial"
    assert compatibility.audience == "operator_private"
    assert compatibility.state == "hold"
    assert compatibility.compatibility_only is True
    assert compatibility.compatibility_ref.endswith(compatibility.compatibility_hash)
    assert (
        context_bundle_digest(compatibility.wire)
        == hashlib.sha256(context_bundle_json_bytes(compatibility.wire)).hexdigest()
    )
    assert LOCKED_CONTEXT_BUNDLE_CONTRACT_SHA256 == (
        "8204a2b2804aa41ac95f75414b58fa88ae1e76a48e6ef731807f544f4148fbd9"
    )


def test_locked_v1_rejects_rehashed_loss_and_provenance_underclaims(
    rich_context,
) -> None:
    frame = rich_context["frame"]
    operator = rich_context["operator"]
    yard = rich_context["yard"]
    hapax = rich_context["hapax"]
    compatibility = project_context_bundle_v1(
        frame,
        operator_private=operator,
        yard_context=yard,
        hapax_substrate=hapax,
    )

    def rehash(payload: dict) -> None:
        _rehash_addressed(
            payload,
            domain="hapax.context-bundle-v1-compatibility.v1",
            ref_field="compatibility_ref",
            hash_field="compatibility_hash",
            prefix="context-bundle-compatibility",
        )

    omissions = compatibility.model_dump(mode="json", by_alias=True)
    omissions["omitted_field_paths"] = ["/forged/minimal"]
    omissions["omission_digest"] = _domain_hash(
        "hapax.context-bundle-v1.omissions.v1", tuple(omissions["omitted_field_paths"])
    )
    rehash(omissions)
    with pytest.raises(ValidationError, match="exact v1 loss surface"):
        type(compatibility).model_validate(omissions)

    reasons = compatibility.model_dump(mode="json", by_alias=True)
    reasons["reason_codes"] = ["hold_no_live_actions"]
    rehash(reasons)
    with pytest.raises(ValidationError, match="exact v1 reason contract"):
        type(compatibility).model_validate(reasons)

    provenance = compatibility.model_dump(mode="json", by_alias=True)
    provenance["source_projection_refs"]["operator_private"] = (
        "projection-envelope@sha256:" + "0" * 64
    )
    rehash(provenance)
    with pytest.raises(ValidationError, match="wire provenance must bind"):
        type(compatibility).model_validate(provenance)


def test_wife_and_chris_axes_do_not_fork_semantics(rich_context) -> None:
    frame = rich_context["frame"]
    wife = rich_context["operator"]
    orientation = rich_context["orientation"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(wife, ProjectionEnvelope)
    assert isinstance(orientation, BoundaryOrientationFacet)
    chris = project_context_frame(
        frame,
        audience="operator_private",
        purpose="orientation",
        depth="raw",
        device_class="monitor",
        register="formal",
        decoder_ref=wife.decoder_ref,
        focus_ref=wife.focus_ref,
        producer_ref=wife.producer_ref,
        generated_at=wife.generated_at,
        orientation_ref=orientation.facet_ref,
    )
    for field in (
        "position",
        "demand_shape",
        "state",
        "meaning",
        "implications",
        "blind_spots",
        "facts",
        "relations",
        "actions",
        "legal_next",
        "prohibited_next",
        "orientation",
        "loss",
    ):
        assert getattr(wife, field) == getattr(chris, field)
    assert (wife.depth, wife.device_class, wife.register_mode) != (
        chris.depth,
        chris.device_class,
        chris.register_mode,
    )


def test_fact_and_projected_fact_reject_fresh_stale_state(rich_context) -> None:
    frame = rich_context["frame"]
    operator = rich_context["operator"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(operator, ProjectionEnvelope)
    carriers = (
        next(item for item in frame.facts if item.fact_id == "fact:position"),
        next(
            item
            for item in operator.facts
            if isinstance(item, ProjectedFact) and item.fact_id == "fact:position"
        ),
    )
    for carrier in carriers:
        payload = carrier.model_dump(mode="json", by_alias=True)
        payload["freshness_state"] = "fresh"
        payload["state"] = {"value_state": "stale", "reason_codes": ["forged_stale"]}
        with pytest.raises(ValidationError, match="freshness and value state are inconsistent"):
            type(carrier).model_validate(payload)


def test_satisfied_lifecycle_guards_reject_held_local_evidence(rich_context) -> None:
    frame = rich_context["frame"]
    operator = rich_context["operator"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(operator, ProjectionEnvelope)
    for carrier, rehash, model in (
        (frame, _rehash_frame, ContextFrame),
        (operator, _rehash_projection, ProjectionEnvelope),
    ):
        payload = carrier.model_dump(mode="json", by_alias=True)
        action = next(item for item in payload["actions"] if item["action_id"] == "action:execute")
        guard = next(
            item
            for item in action["guard_evidence"]
            if item["guard"] == "mutation_in_mutation_scope_refs"
        )
        guard["evidence_refs"] = ["fact:capability-gap"]
        rehash(payload)
        with pytest.raises(ValidationError, match="satisfied.*guards require present"):
            model.model_validate(payload)


def test_learning_witness_receipts_must_be_position_lineaged(rich_context) -> None:
    frame = rich_context["frame"]
    receipt = rich_context["learning_receipt"]
    assert isinstance(frame, ContextFrame)
    receipt_payload = receipt.model_dump(mode="json", by_alias=True)
    old_ref = receipt_payload["learning_ref"]
    receipt_payload["witness_refs"] = ["receipt:unbound-private-secret"]
    _rehash_addressed(
        receipt_payload,
        domain="hapax.signal-learning-receipt.v1",
        ref_field="learning_ref",
        hash_field="learning_hash",
        prefix="signal-learning",
    )

    payload = frame.model_dump(mode="json", by_alias=True)
    payload["signal_learning_receipts"] = [receipt_payload]
    binding = next(
        item
        for item in payload["air_bindings"]
        if item["object_kind"] == "learning_receipt" and item["object_ref"] == old_ref
    )
    binding["object_ref"] = receipt_payload["learning_ref"]
    payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="position receipt lineage"):
        ContextFrame.model_validate(payload)


def test_observation_authority_must_equal_source_admission(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    base_source = next(
        item for item in frame.source_admissions if item.admission_id == "source-admission:estate"
    )
    base_values = base_source.model_dump(
        mode="python",
        exclude={
            "admission_ref",
            "admission_hash",
            "admission_id",
            "source_ref",
            "authority_ceiling",
            "no_effect",
            "may_authorize",
        },
    )
    admission = build_source_admission(
        admission_id="source-admission:authority-canary",
        source_ref="source:authority-canary",
        authority_ceiling="observation_only",
        **base_values,
    )
    observation = build_observation_envelope(
        observation_id="observation:authority-canary",
        source_admission_ref=admission.admission_ref,
        scope_ref=admission.scope_ref,
        temporal_ref=admission.temporal_ref,
        resolution_ref=admission.resolution_ref,
        subject_ref="source:authority-canary",
        payload={"canary": "authority"},
        producer_ref="producer:observer",
        method_ref="method:deterministic",
        config_ref="config:observer",
        authority_ceiling="projection_only",
        witness_refs=(frame.position.receipt_lineage[0],),
        source_refs=(frame.position.receipt_lineage[0],),
        state=ContextState(value_state="present", reason_codes=()),
    )
    source_air = next(
        item.air for item in frame.air_bindings if item.object_kind == "source_admission"
    )
    observation_air = next(
        item.air for item in frame.air_bindings if item.object_kind == "observation"
    )
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["source_admissions"].append(admission.model_dump(mode="json"))
    payload["source_admissions"].sort(key=lambda item: item["admission_ref"])
    payload["observations"].append(observation.model_dump(mode="json"))
    payload["observations"].sort(key=lambda item: item["observation_ref"])
    payload["air_bindings"].extend(
        (
            ContextAirBinding(
                object_kind="source_admission", object_ref=admission.admission_ref, air=source_air
            ).model_dump(mode="json"),
            ContextAirBinding(
                object_kind="observation",
                object_ref=observation.observation_ref,
                air=observation_air,
            ).model_dump(mode="json"),
        )
    )
    payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="authority ceiling must equal"):
        ContextFrame.model_validate(payload)


@pytest.mark.parametrize(
    ("parent_generation", "child_generation", "parent_depth", "child_depth", "error"),
    (
        (1, 1, 0, 1, None),
        (2, 1, 0, 1, "generations must be nondecreasing"),
        (1, 1, 0, 0, "derivation depth must strictly increase"),
    ),
)
def test_same_second_event_causality_uses_generation_and_depth(
    rich_context,
    parent_generation: int,
    child_generation: int,
    parent_depth: int,
    child_depth: int,
    error: str | None,
) -> None:
    frame = rich_context["frame"]
    scope = rich_context["scope"]
    temporal = rich_context["temporal"]
    resolution = rich_context["resolution"]
    suffix = f"{parent_generation}-{child_generation}-{parent_depth}-{child_depth}"
    parent = build_epistemic_flow_event(
        event_id=f"event:causal-parent:{suffix}",
        kind="observation_recorded",
        session_ref=frame.session_ref,
        task_ref=frame.task_ref,
        trace_ref=f"trace:causal:{suffix}",
        position_ref=frame.position.position_ref,
        scope_ref=scope.scope_ref,
        temporal_ref=temporal.temporal_ref,
        resolution_ref=resolution.resolution_ref,
        generation=parent_generation,
        subject_ref="fact:position",
        occurred_at=temporal.event_time_start,
        expires_at=temporal.valid_until,
        producer_ref="producer:observer",
        method_ref="method:deterministic",
        privacy_class="operator_private",
        authority_ceiling="observation_only",
        source_refs=("fact:position",),
        caused_by=(frame.position.receipt_lineage[0],),
        supersedes_refs=(),
        derivation_depth=parent_depth,
        payload={"observation_ref": "fact:position", "observation_state": "causal_parent"},
        state=ContextState(value_state="present", reason_codes=()),
    )
    child = build_epistemic_flow_event(
        event_id=f"event:causal-child:{suffix}",
        kind="context_fact_derived",
        session_ref=frame.session_ref,
        task_ref=frame.task_ref,
        trace_ref=f"trace:causal:{suffix}",
        position_ref=frame.position.position_ref,
        scope_ref=scope.scope_ref,
        temporal_ref=temporal.temporal_ref,
        resolution_ref=resolution.resolution_ref,
        generation=child_generation,
        subject_ref="fact:position",
        occurred_at=temporal.event_time_start,
        expires_at=temporal.valid_until,
        producer_ref="producer:deterministic",
        method_ref="method:rule",
        privacy_class="operator_private",
        authority_ceiling="projection_only",
        source_refs=("fact:position",),
        caused_by=(parent.event_ref,),
        supersedes_refs=(),
        derivation_depth=child_depth,
        payload={"derivation_ref": "derivation:causal-child", "fact_ref": "fact:position"},
        state=ContextState(value_state="present", reason_codes=()),
    )
    event_air = next(item.air for item in frame.air_bindings if item.object_kind == "event")
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["events"].extend((parent.model_dump(mode="json"), child.model_dump(mode="json")))
    payload["events"].sort(
        key=lambda item: (
            item["occurred_at"],
            item["generation"],
            item["derivation_depth"],
            item["event_ref"],
        )
    )
    payload["air_bindings"].extend(
        ContextAirBinding(object_kind="event", object_ref=item.event_id, air=event_air).model_dump(
            mode="json"
        )
        for item in (parent, child)
    )
    payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(payload)
    if error is None:
        ContextFrame.model_validate(payload)
    else:
        with pytest.raises(ValidationError, match=error):
            ContextFrame.model_validate(payload)


def test_source_admission_caps_supported_provenance_classes(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    source = next(
        item for item in frame.source_admissions if item.admission_id == "source-admission:estate"
    )
    values = source.model_dump(
        mode="python",
        exclude={"admission_ref", "admission_hash", "no_effect", "may_authorize"},
    )
    values["supported_provenance_kinds"] = ("constitutional",)
    with pytest.raises(ValidationError, match="constitutional authority ceiling"):
        build_source_admission(**values)


def test_provenance_kind_requires_consistent_derivation_semantics(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    fact = next(item for item in frame.facts if item.fact_id == "fact:capability-gap")
    payload = fact.provenance.model_dump(mode="json")
    payload["kind"] = "measured"
    with pytest.raises(ValidationError, match="kind and derivation semantics"):
        ContextProvenance.model_validate(payload)


def test_rehashed_fact_kind_cannot_exceed_admitted_source_classes(rich_context) -> None:
    frame = rich_context["frame"]
    operator = rich_context["operator"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(operator, ProjectionEnvelope)
    for carrier, rehash, model in (
        (frame, _rehash_frame, ContextFrame),
        (operator, _rehash_projection, ProjectionEnvelope),
    ):
        payload = carrier.model_dump(mode="json", by_alias=True)
        fact = next(item for item in payload["facts"] if item["fact_id"] == "fact:capability-gap")
        fact["provenance"]["kind"] = "constitutional"
        rehash(payload)
        with pytest.raises(ValidationError, match="provenance kind exceeds its admitted source"):
            model.model_validate(payload)


def test_stipulated_provenance_requires_typed_position_receipt(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    fact = next(item for item in frame.facts if item.fact_id == "fact:capability-gap")
    derivation = next(
        item for item in frame.derivations if item.derivation_ref == fact.derivation_ref
    )
    observation_by_ref = {item.observation_ref: item for item in frame.observations}
    admission_by_ref = {item.admission_ref: item for item in frame.source_admissions}
    source_ref = observation_by_ref[derivation.input_observation_refs[0]].source_admission_ref
    admission_by_ref[source_ref] = admission_by_ref[source_ref].model_copy(
        update={"supported_provenance_kinds": ("observed", "operator_stipulated")}
    )
    provenance = ContextProvenance(
        **fact.provenance.model_dump(
            mode="python",
            exclude={"kind", "derivation"},
        ),
        kind="operator_stipulated",
        derivation="stipulated",
    )
    stipulated = fact.model_copy(update={"provenance": provenance})
    with pytest.raises(ValueError, match="requires a typed position receipt"):
        canon_module._validate_fact_evidence_and_authority(
            stipulated,
            derivation,
            observation_by_ref,
            admission_by_ref,
            {item.fact_id: item for item in frame.facts},
            frame.position.receipt_lineage,
            label="fact",
        )


def test_fact_authority_cannot_exceed_named_derivation_inputs(rich_context) -> None:
    frame = rich_context["frame"]
    operator = rich_context["operator"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(operator, ProjectionEnvelope)
    for carrier, rehash, model in (
        (frame, _rehash_frame, ContextFrame),
        (operator, _rehash_projection, ProjectionEnvelope),
    ):
        payload = carrier.model_dump(mode="json", by_alias=True)
        fact = next(item for item in payload["facts"] if item["fact_id"] == "fact:capability-gap")
        fact["provenance"]["authority_level"] = "authoritative"
        rehash(payload)
        with pytest.raises(ValidationError, match="authority exceeds its named derivation inputs"):
            model.model_validate(payload)


def test_partial_fresh_facts_reject_dark_provenance(rich_context) -> None:
    frame = rich_context["frame"]
    operator = rich_context["operator"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(operator, ProjectionEnvelope)
    carriers = (
        next(item for item in frame.facts if item.fact_id == "fact:position"),
        next(
            item
            for item in operator.facts
            if isinstance(item, ProjectedFact) and item.fact_id == "fact:position"
        ),
    )
    for carrier in carriers:
        payload = carrier.model_dump(mode="json", by_alias=True)
        payload["state"] = {"value_state": "partial", "reason_codes": ["partial_canary"]}
        payload["freshness_state"] = "fresh"
        payload["provenance"]["kind"] = "dark"
        payload["provenance"]["authority_level"] = "projection_only"
        with pytest.raises(ValidationError, match="dark .*provenance requires"):
            type(carrier).model_validate(payload)


def test_fact_evidence_must_belong_to_its_named_derivation(rich_context) -> None:
    frame = rich_context["frame"]
    operator = rich_context["operator"]
    assert isinstance(frame, ContextFrame)
    assert isinstance(operator, ProjectionEnvelope)
    for carrier, rehash, model in (
        (frame, _rehash_frame, ContextFrame),
        (operator, _rehash_projection, ProjectionEnvelope),
    ):
        payload = carrier.model_dump(mode="json", by_alias=True)
        fact = next(item for item in payload["facts"] if item["fact_id"] == "fact:position")
        derivation = next(
            item
            for item in payload["derivations"]
            if item["derivation_ref"] == fact["derivation_ref"]
        )
        named_inputs = set(derivation["input_observation_refs"])
        unrelated = next(
            item["observation_ref"]
            for item in payload["observations"]
            if item["observation_ref"] not in named_inputs
        )
        fact["provenance"]["source_refs"] = [unrelated]
        fact["confidence"]["evidence_refs"] = [unrelated]
        rehash(payload)
        with pytest.raises(ValidationError, match="named derivation inputs"):
            model.model_validate(payload)


def test_temporal_processing_cannot_follow_frame_check(rich_context) -> None:
    frame = rich_context["frame"]
    assert isinstance(frame, ContextFrame)
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["checked_at"] = payload["observed_at"]
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="temporal processing cannot follow frame checking"):
        ContextFrame.model_validate(payload)


def test_event_authority_cannot_exceed_observation_source(rich_context) -> None:
    frame = rich_context["frame"]
    scope = rich_context["scope"]
    temporal = rich_context["temporal"]
    resolution = rich_context["resolution"]
    assert isinstance(frame, ContextFrame)
    event = build_epistemic_flow_event(
        event_id="event:authority-escalation-canary",
        kind="observation_recorded",
        session_ref=frame.session_ref,
        task_ref=frame.task_ref,
        trace_ref="trace:authority-escalation-canary",
        position_ref=frame.position.position_ref,
        scope_ref=scope.scope_ref,
        temporal_ref=temporal.temporal_ref,
        resolution_ref=resolution.resolution_ref,
        generation=2,
        subject_ref="capability:execution",
        occurred_at=temporal.event_time_start,
        expires_at=temporal.valid_until,
        producer_ref="producer:observer",
        method_ref="method:deterministic",
        privacy_class="operator_private",
        authority_ceiling="constitutional_evidence",
        source_refs=(rich_context["private_observation"].observation_ref,),
        caused_by=(frame.position.receipt_lineage[0],),
        supersedes_refs=(),
        derivation_depth=0,
        payload={
            "observation_ref": rich_context["private_observation"].observation_ref,
            "observation_state": "authority_escalation_canary",
        },
        state=ContextState(value_state="present", reason_codes=()),
    )
    event_air = next(item.air for item in frame.air_bindings if item.object_kind == "event")
    payload = frame.model_dump(mode="json", by_alias=True)
    payload["events"].append(event.model_dump(mode="json"))
    payload["events"].sort(
        key=lambda item: (
            item["occurred_at"],
            item["generation"],
            item["derivation_depth"],
            item["event_ref"],
        )
    )
    payload["air_bindings"].append(
        ContextAirBinding(
            object_kind="event",
            object_ref=event.event_id,
            air=event_air,
        ).model_dump(mode="json")
    )
    payload["air_bindings"].sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(payload)
    with pytest.raises(ValidationError, match="event authority exceeds its typed source evidence"):
        ContextFrame.model_validate(payload)


def test_materialized_bundle_round_trip_and_duplicate_key_refusal(
    tmp_path: Path, bundle: CanonBundle
) -> None:
    path = tmp_path / "bundle.json"
    written = materialize_bundle(path)
    assert written.bundle_hash == bundle.bundle_hash
    assert load_materialized_bundle(path) == bundle

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    with pytest.raises(CanonError, match="canon_bundle_duplicate_json_key"):
        load_materialized_bundle(duplicate)

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(
        json.dumps(bundle.model_dump(mode="json", by_alias=True), indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CanonError, match="canon_bundle_noncanonical_json"):
        load_materialized_bundle(noncanonical)


def test_source_hashes_bind_every_materializer_input(
    bundle: CanonBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    by_ref = {item.source_ref: item.sha256 for item in bundle.source_hashes}
    assert set(by_ref) == set(canon_module._SOURCE_HASH_REFS)
    package_payloads = canon_module._context_canon_source_payloads()
    assert set(package_payloads) == {
        *canon_module._CONTEXT_CANON_SOURCE_MODULES,
        *canon_module._CONTEXT_CANON_SOURCE_RESOURCES,
        *canon_module._CONTEXT_CANON_RUNTIME_IDENTITIES,
    }
    generator_text = Path(canon_module.__file__).read_text()
    council_payloads = canon_module._council_source_payloads(generator_text)
    assert set(council_payloads) == {
        *canon_module._COUNCIL_SOURCE_MODULES,
        *canon_module._COUNCIL_SOURCE_VALUE_REFS,
        *canon_module._COUNCIL_RUNTIME_IDENTITIES,
    }
    for source_ref, payload in {**package_payloads, **council_payloads}.items():
        assert by_ref[source_ref] == hashlib.sha256(payload.encode()).hexdigest()
    for source_ref in (
        *canon_module._CONTEXT_CANON_RUNTIME_IDENTITIES,
        *canon_module._COUNCIL_RUNTIME_IDENTITIES,
    ):
        identity = json.loads({**package_payloads, **council_payloads}[source_ref])
        assert identity["import_root"]
        assert identity["identity_schema"] == ("hapax.python-distribution.semantic-release.v1")
        assert set(identity) == {
            "distribution",
            "identity_schema",
            "import_root",
            "release_manifest_ref",
            "release_set_hash",
            "release_set_ref",
            "source_registry",
            "version",
        }
    reduced = dict(canon_module._CONTEXT_CANON_SOURCE_MODULES)
    reduced.pop(next(iter(reduced)))
    monkeypatch.setattr(canon_module, "_CONTEXT_CANON_SOURCE_MODULES", MappingProxyType(reduced))
    with pytest.raises(CanonError, match="canon_package_module_closure_mismatch"):
        canon_module._context_canon_source_payloads()
    with pytest.raises(CanonError, match="canon_council_module_closure_mismatch"):
        canon_module._council_source_payloads(generator_text + "\nfrom shared.unknown import x\n")
    assert SDLC_STAGE_METADATA_PATH.is_file()


def test_runtime_dependency_release_manifest_is_exact_uv_lock_projection() -> None:
    manifest = canon_module._load_runtime_dependency_release_manifest()
    lock = tomllib.loads((Path(__file__).parents[2] / "uv.lock").read_text())
    packages = {
        canon_module._normalized_distribution_name(item["name"]): item for item in lock["package"]
    }

    def artifact(raw) -> dict[str, object]:
        algorithm, digest = raw["hash"].split(":", 1)
        assert algorithm == "sha256"
        return {
            "filename": Path(urlsplit(raw["url"]).path).name,
            "sha256": digest,
            "size": raw["size"],
            "url": raw["url"],
        }

    for release in manifest.dependencies:
        package = packages[release.distribution]
        assert release.version == package["version"]
        assert release.source_registry == package["source"]["registry"]
        assert release.sdist.model_dump(mode="json") == artifact(package["sdist"])
        assert [item.model_dump(mode="json") for item in release.wheels] == sorted(
            (artifact(item) for item in package["wheels"]),
            key=lambda item: item["filename"],
        )
    assert "config/coordination-canon/runtime-dependency-release-set.json" in (
        canon_module._SOURCE_HASH_REFS
    )


def test_distribution_semantic_identity_still_refuses_recorded_artifact_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = canon_module.importlib_metadata.distribution("python-toon")
    tampered = tmp_path / "encoder.py"
    tampered.write_bytes(b"tampered\n")

    class TamperedDistribution:
        files = installed.files
        metadata = installed.metadata
        version = installed.version

        @staticmethod
        def locate_file(path):
            if str(path) == "toon/encoder.py":
                return tampered
            return installed.locate_file(path)

        @staticmethod
        def read_text(filename: str):
            return installed.read_text(filename)

    monkeypatch.setattr(
        canon_module.importlib_metadata,
        "distribution",
        lambda _distribution: TamperedDistribution(),
    )
    with pytest.raises(CanonError, match="canon_runtime_dependency_artifact_mismatch"):
        canon_module._runtime_dependency_record_observation(
            "python-toon",
            "0.1.3",
            "toon",
            release_manifest=canon_module._load_runtime_dependency_release_manifest(),
        )


def test_runtime_record_observation_is_non_authorizing_without_install_receipt() -> None:
    manifest = canon_module._load_runtime_dependency_release_manifest()
    observation = canon_module._runtime_dependency_record_observation(
        "python-toon", "0.1.3", "toon", release_manifest=manifest
    )
    release = next(item for item in manifest.dependencies if item.distribution == "python-toon")
    assert observation["schema"] == ("hapax.python-distribution.runtime-record-observation.v1")
    assert observation["release_set_hash"] == release.release_set_hash
    assert observation["record_self_consistent"] is True
    assert observation["import_origin_record_member"] is True
    assert observation["admission_state"] == "hold"
    assert observation["reason_codes"] == ["independent_install_receipt_missing"]
    assert observation["may_authorize"] is False


def test_semantic_bundle_never_consults_runtime_record_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse_observation(*_args, **_kwargs):
        raise AssertionError("runtime observation entered semantic materialization")

    monkeypatch.setattr(canon_module, "_runtime_dependency_record_observation", refuse_observation)
    assert build_canon_bundle().canon_hash


def test_rewritten_record_observation_remains_nonadmissible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = canon_module.importlib_metadata.distribution("python-toon")
    record_entry = next(path for path in installed.files if path.name == "RECORD")
    record_path = Path(installed.locate_file(record_entry))
    tampered = tmp_path / "encoder.py"
    tampered_bytes = b"tampered with rewritten record\n"
    tampered.write_bytes(tampered_bytes)
    encoded = base64.urlsafe_b64encode(hashlib.sha256(tampered_bytes).digest()).decode().rstrip("=")
    rewritten_record = tmp_path / "RECORD"
    rewritten_record.write_text(
        "\n".join(
            (
                f"toon/encoder.py,sha256={encoded},{len(tampered_bytes)}"
                if line.startswith("toon/encoder.py,")
                else line
            )
            for line in record_path.read_text().splitlines()
        )
        + "\n"
    )

    class RewrittenDistribution:
        files = installed.files
        metadata = installed.metadata
        version = installed.version

        @staticmethod
        def locate_file(path):
            if str(path) == record_entry.as_posix():
                return rewritten_record
            if str(path) == "toon/encoder.py":
                return tampered
            return installed.locate_file(path)

        @staticmethod
        def read_text(filename: str):
            return installed.read_text(filename)

    monkeypatch.setattr(
        canon_module.importlib_metadata,
        "distribution",
        lambda _distribution: RewrittenDistribution(),
    )
    observation = canon_module._runtime_dependency_record_observation(
        "python-toon",
        "0.1.3",
        "toon",
        release_manifest=canon_module._load_runtime_dependency_release_manifest(),
    )
    assert observation["record_self_consistent"] is True
    assert observation["admission_state"] == "hold"
    assert observation["reason_codes"] == ["independent_install_receipt_missing"]
    assert observation["may_authorize"] is False


def test_context_canon_package_reexports_are_object_identical() -> None:
    for name in context_canon_package.CONTRACT_EXPORTS:
        assert getattr(canon_module, name) is getattr(context_canon_package, name)
    assert {
        "CanonSource",
        "CanonImage",
        "CanonBundle",
        "CanonCorpus",
        "build_canon_bundle",
        "build_context_frame",
        "materialize_bundle",
    }.isdisjoint(context_canon_package.__all__)


_SHA256_TOKEN_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_CONTENT_ADDRESS_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*@sha256:[0-9a-f]{64}$")
_LIFECYCLE_FACT_RE = re.compile(r"^fact:lifecycle-fsm:[0-9a-f]{64}$")
_SUPERSESSION_LIST_KEYS = {
    "actions": "action_id",
    "derivations": "derivation_id",
    "events": "event_id",
    "facts": "fact_id",
    "impingements": "impingement_id",
    "lifecycle_possibilities": "facet_id",
    "observations": "observation_id",
    "orientation_facets": "facet_id",
    "orienting_signals": "signal_id",
    "portal_offers": "portal_id",
    "relations": "relation_id",
    "signal_constellations": "constellation_id",
    "signal_estimates": "estimate_id",
    "signal_learning_receipts": "learning_id",
    "signal_lenses": "lens_id",
    "source_admissions": "admission_id",
}


def _source_manifest(value) -> dict[str, str]:
    manifests: set[tuple[tuple[str, str], ...]] = set()

    def visit(item) -> None:
        if isinstance(item, dict):
            if isinstance(item.get("source_hashes"), list):
                manifests.add(
                    tuple(
                        sorted(
                            (entry["source_ref"], entry["sha256"])
                            for entry in item["source_hashes"]
                        )
                    )
                )
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    assert len(manifests) == 1
    return dict(next(iter(manifests)))


def _rewrite_address_view(value, address_map: dict[str, str]):
    if isinstance(value, dict):
        return {
            child_key: _rewrite_address_view(child, address_map)
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_address_view(item, address_map) for item in value]
    if isinstance(value, str):
        return _SHA256_TOKEN_RE.sub(
            lambda match: address_map.get(match.group(0), match.group(0)),
            value,
        )
    return value


def _prepare_source_supersession(
    value,
    common_source_refs: frozenset[str],
    *,
    key: str = "",
    air_sort_address_map: dict[str, str] | None = None,
    omit_air_bindings: bool = False,
):
    if isinstance(value, dict):
        prepared = {
            child_key: _prepare_source_supersession(
                child,
                common_source_refs,
                key=child_key,
                air_sort_address_map=air_sort_address_map,
                omit_air_bindings=omit_air_bindings,
            )
            for child_key, child in value.items()
            if not (omit_air_bindings and child_key == "air_bindings")
        }
        if isinstance(prepared.get("source_hashes"), list):
            prepared["source_hashes"] = sorted(
                (
                    item
                    for item in prepared["source_hashes"]
                    if item["source_ref"] in common_source_refs
                ),
                key=lambda item: item["source_ref"],
            )
        return prepared
    if isinstance(value, list):
        prepared = [
            _prepare_source_supersession(
                item,
                common_source_refs,
                key=key,
                air_sort_address_map=air_sort_address_map,
                omit_air_bindings=omit_air_bindings,
            )
            for item in value
        ]
        stable_key = _SUPERSESSION_LIST_KEYS.get(key)
        if stable_key and all(isinstance(item, dict) and stable_key in item for item in prepared):
            prepared.sort(key=lambda item: item[stable_key])
        elif key == "air_bindings":
            prepared.sort(
                key=lambda item: json.dumps(
                    _rewrite_address_view(item, air_sort_address_map or {}),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        return prepared
    return value


def _pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _address_grammar(value: str) -> str:
    if _SHA256_TOKEN_RE.fullmatch(value):
        return "bare_sha256"
    if _CONTENT_ADDRESS_RE.fullmatch(value):
        return "content_address"
    if _LIFECYCLE_FACT_RE.fullmatch(value):
        return "lifecycle_fact_address"
    raise AssertionError(f"unrecognized source-address token form: {value!r}")


def _derive_address_occurrences(frozen, current, *, path: str = "", key: str = ""):
    occurrences: list[dict[str, object]] = []

    def visit(old, new, current_path: str, current_key: str) -> None:
        if type(old) is not type(new):
            raise AssertionError(f"type drift at {current_path or '/'}")
        if isinstance(old, dict):
            if set(old) != set(new):
                raise AssertionError(f"mapping drift at {current_path or '/'}")
            for child_key in sorted(old):
                visit(
                    old[child_key],
                    new[child_key],
                    f"{current_path}/{_pointer_token(child_key)}",
                    child_key,
                )
            return
        if isinstance(old, list):
            if len(old) != len(new):
                raise AssertionError(f"list length drift at {current_path or '/'}")
            for index, (old_item, new_item) in enumerate(zip(old, new, strict=True)):
                visit(old_item, new_item, f"{current_path}/{index}", current_key)
            return
        if old == new:
            return
        if current_key == "canonical_json" and isinstance(old, str):
            visit(json.loads(old), json.loads(new), f"{current_path}#", "")
            return
        if not isinstance(old, str):
            raise AssertionError(f"non-string semantic drift at {current_path or '/'}")
        old_tokens = tuple(_SHA256_TOKEN_RE.finditer(old))
        new_tokens = tuple(_SHA256_TOKEN_RE.finditer(new))
        if (
            not old_tokens
            or len(old_tokens) != len(new_tokens)
            or _SHA256_TOKEN_RE.sub("<sha256>", old) != _SHA256_TOKEN_RE.sub("<sha256>", new)
        ):
            raise AssertionError(f"non-address string drift at {current_path or '/'}")
        old_grammar = _address_grammar(old)
        new_grammar = _address_grammar(new)
        if old_grammar != new_grammar:
            raise AssertionError(f"address grammar drift at {current_path or '/'}")
        for index, (old_match, new_match) in enumerate(zip(old_tokens, new_tokens, strict=True)):
            if old_match.group(0) != new_match.group(0):
                occurrences.append(
                    {
                        "grammar": old_grammar,
                        "new": new_match.group(0),
                        "old": old_match.group(0),
                        "path": current_path,
                        "token_index": index,
                    }
                )

    visit(frozen, current, path, key)
    return sorted(occurrences, key=lambda item: (item["path"], item["token_index"]))


def _address_map_from_occurrences(
    occurrences: list[dict[str, object]],
) -> dict[str, str]:
    address_map: dict[str, str] = {}
    occurrence_keys: set[tuple[str, int]] = set()
    for occurrence in occurrences:
        occurrence_key = (str(occurrence["path"]), int(occurrence["token_index"]))
        assert occurrence_key not in occurrence_keys
        occurrence_keys.add(occurrence_key)
        old = str(occurrence["old"])
        new = str(occurrence["new"])
        assert address_map.setdefault(old, new) == new
    assert len(set(address_map.values())) == len(address_map)
    assert set(address_map).isdisjoint(address_map.values())
    return dict(sorted(address_map.items()))


def _pointer_parent(value, pointer: str):
    assert pointer.startswith("/")
    tokens = [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]
    current = value
    for token in tokens[:-1]:
        current = current[int(token)] if isinstance(current, list) else current[token]
    final = tokens[-1]
    return current, int(final) if isinstance(current, list) else final


def _apply_address_occurrences(value, occurrences: list[dict[str, object]]):
    transformed = copy.deepcopy(value)
    consumed: set[tuple[str, int]] = set()
    for occurrence in occurrences:
        path = str(occurrence["path"])
        outer_path, separator, nested_path = path.partition("#")
        outer_parent, outer_key = _pointer_parent(transformed, outer_path)
        if separator:
            nested = json.loads(outer_parent[outer_key])
            parent, key = _pointer_parent(nested, nested_path)
        else:
            nested = None
            parent, key = outer_parent, outer_key
        current = parent[key]
        assert isinstance(current, str)
        matches = tuple(_SHA256_TOKEN_RE.finditer(current))
        token_index = int(occurrence["token_index"])
        assert token_index < len(matches)
        match = matches[token_index]
        assert match.group(0) == occurrence["old"]
        assert _address_grammar(current) == occurrence["grammar"]
        parent[key] = current[: match.start()] + str(occurrence["new"]) + current[match.end() :]
        if nested is not None:
            outer_parent[outer_key] = json.dumps(nested, sort_keys=True, separators=(",", ":"))
        occurrence_key = (path, token_index)
        assert occurrence_key not in consumed
        consumed.add(occurrence_key)
    assert len(consumed) == len(occurrences)
    return transformed


def _derive_source_supersession(frozen, current):
    frozen_manifest = _source_manifest(frozen)
    current_manifest = _source_manifest(current)
    common_source_refs = frozenset(frozen_manifest) & frozenset(current_manifest)
    preliminary_frozen = _prepare_source_supersession(
        frozen,
        common_source_refs,
        omit_air_bindings=True,
    )
    preliminary_current = _prepare_source_supersession(
        current,
        common_source_refs,
        omit_air_bindings=True,
    )
    preliminary_occurrences = _derive_address_occurrences(preliminary_frozen, preliminary_current)
    preliminary_map = _address_map_from_occurrences(preliminary_occurrences)
    prepared_frozen = _prepare_source_supersession(
        frozen,
        common_source_refs,
        air_sort_address_map=preliminary_map,
    )
    prepared_current = _prepare_source_supersession(current, common_source_refs)
    occurrences = _derive_address_occurrences(prepared_frozen, prepared_current)
    address_map = _address_map_from_occurrences(occurrences)
    assert address_map == preliminary_map
    assert _apply_address_occurrences(prepared_frozen, occurrences) == prepared_current
    added_refs = sorted(set(current_manifest) - set(frozen_manifest))
    removed_refs = sorted(set(frozen_manifest) - set(current_manifest))
    changed_paths = sorted(
        {
            *(str(occurrence["path"]) for occurrence in occurrences),
            *(f"/source_manifest/added/{_pointer_token(ref)}" for ref in added_refs),
            *(f"/source_manifest/removed/{_pointer_token(ref)}" for ref in removed_refs),
        }
    )
    return {
        "address_map": address_map,
        "changed_paths": changed_paths,
        "current_manifest": current_manifest,
        "frozen_manifest": frozen_manifest,
        "occurrences": occurrences,
    }


def _named_commitments(value, field: str) -> dict[str, str]:
    found: dict[str, str] = {}

    def visit(item, path: str = "") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                child_path = f"{path}/{_pointer_token(key)}"
                if key == field:
                    found[child_path] = child
                visit(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}/{index}")

    visit(value)
    return dict(sorted(found.items()))


def _mutate_first_named_commitment(value, field: str) -> bool:
    if isinstance(value, dict):
        if field in value:
            value[field] = "0" * 64
            return True
        return any(_mutate_first_named_commitment(child, field) for child in value.values())
    if isinstance(value, list):
        return any(_mutate_first_named_commitment(child, field) for child in value)
    return False


def test_pre_extension_checkpoint_and_source_proof_are_preserved() -> None:
    fixtures = Path(__file__).parents[2] / "packages/hapax-context-canon/tests/fixtures"
    checkpoint = fixtures / "checkpoints/pre-contract-extension-20260712"
    manifest = json.loads((checkpoint / "checkpoint-manifest.json").read_text())
    assert manifest["schema"] == "hapax.context-canon.checkpoint-manifest.v1"
    assert manifest["historical_scope"] == {
        "current_contract_compatible": False,
        "exact_bytes_preserved": True,
        "source_supersession_proof_applies_only_inside_checkpoint": True,
        "wire_schema_ids": "unreleased_gate0_v1_checkpoint",
    }
    for name, expected in manifest["files"].items():
        payload = (checkpoint / name).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    for label, expected in manifest["replay"].items():
        if label == "source_head":
            assert re.fullmatch(r"[0-9a-f]{40}", expected)
            continue
        target = checkpoint / expected["path"]
        assert target.resolve().is_relative_to(checkpoint.resolve())
        assert target.is_file() and not target.is_symlink()
        assert target.stat().st_nlink == 1
        payload = target.read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    replay_script = (checkpoint / manifest["replay"]["replay_script"]["path"]).read_text()
    assert 'lineage_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in replay_script
    assert "replay root must be disk-backed" in replay_script
    assert "mktemp -d /tmp" not in replay_script

    historical = json.loads((checkpoint / "gate0-source-supersession.json").read_text())
    assert historical["schema"] == "hapax.context-canon.source-manifest-supersession.v2"
    assert (
        historical["task_id"] == "cc-task-hapax-context-canon-contract-package-extraction-20260711"
    )
    assert historical["proof"]["address_count"] == len(historical["address_map"])
    assert historical["proof"]["changed_path_count"] == len(historical["changed_paths"])
    assert historical["proof"]["occurrence_count"] == len(historical["occurrences"])
    for name, expected in historical["frozen_fixtures"].items():
        payload = (checkpoint / name).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]

    retirement = json.loads((fixtures / "gate0-source-supersession.json").read_text())
    assert retirement["schema"] == "hapax.context-canon.source-supersession-retirement.v1"
    assert retirement["may_authorize"] is False
    for key in ("historical_receipt", "superseded_by"):
        target = fixtures / retirement[key]["path"]
        payload = target.read_bytes()
        assert len(payload) == retirement[key]["bytes"]
        assert hashlib.sha256(payload).hexdigest() == retirement[key]["sha256"]


def test_pre_observability_checkpoint_is_lossless_and_replayable() -> None:
    fixtures = Path(__file__).parents[2] / "packages/hapax-context-canon/tests/fixtures"
    checkpoint = fixtures / "checkpoints/pre-observability-extension-20260713"
    manifest = json.loads((checkpoint / "checkpoint-manifest.json").read_text())
    assert manifest["schema"] == "hapax.context-canon.checkpoint-manifest.v1"
    assert manifest["authority"] == {
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "governing_task": "cc-task-sdlc-fsm-canon-impingement-lockstep-bootstrap-20260710",
        "may_authorize": False,
        "operator_session_id": "019f47f5-9d09-7160-a9b3-4c14a6514876",
    }
    assert manifest["historical_scope"] == {
        "current_contract_compatible": True,
        "exact_bytes_preserved": True,
        "source_supersession_proof_applies_only_to_its_named_predecessor": True,
        "wire_schema_ids": "unreleased_gate0_v1_pre_observability",
    }
    for name, expected in manifest["files"].items():
        payload = (checkpoint / name).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    for label, expected in manifest["replay"].items():
        if label == "source_head":
            assert expected == "f4e97c367ec6467fc4ca516535ecc3be553cb46b"
            continue
        target = checkpoint / expected["path"]
        assert target.resolve().is_relative_to(checkpoint.resolve())
        assert target.is_file() and not target.is_symlink()
        assert target.stat().st_nlink == 1
        payload = target.read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    parent = checkpoint / manifest["lineage_parent"]["path"]
    assert parent.resolve().is_relative_to(fixtures.resolve())
    parent_payload = parent.read_bytes()
    assert len(parent_payload) == manifest["lineage_parent"]["bytes"]
    assert (
        hashlib.sha256(parent_payload).hexdigest()
        == manifest["lineage_parent"]["sha256"]
    )
    replay_script = (checkpoint / manifest["replay"]["replay_script"]["path"]).read_text()
    assert 'lineage_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in replay_script
    assert "replay root must be disk-backed" in replay_script
    assert 'PYTHONPATH="$replay_root/packages/hapax-context-canon/src:$replay_root"' in replay_script
    assert "git -C \"$replay_root\" apply --check" in replay_script
    assert "mktemp -d /tmp" not in replay_script


def test_contract_semantic_supersession_binds_current_and_predecessor(rich_context) -> None:
    fixtures = Path(__file__).parents[2] / "packages/hapax-context-canon/tests/fixtures"
    frame = rich_context["frame"]
    projections = {name: rich_context[name] for name in ("operator", "yard", "hapax")}
    compatibility = project_context_bundle_v1(
        frame,
        operator_private=rich_context["operator"],
        yard_context=rich_context["yard"],
        hapax_substrate=rich_context["hapax"],
    )
    assert (fixtures / "gate0-frame.json").read_bytes() == canonical_json_bytes(frame) + b"\n"
    assert (fixtures / "gate0-projections.json").read_bytes() == canonical_json_bytes(
        projections
    ) + b"\n"
    assert (fixtures / "gate0-compatibility.json").read_bytes() == canonical_json_bytes(
        compatibility
    ) + b"\n"

    hashes = json.loads((fixtures / "gate0-hashes.json").read_text())
    for name, expected in hashes.items():
        if name == "semantic_ids":
            continue
        payload = (fixtures / name).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    assert hashes["semantic_ids"]["frame_hash"] == frame.frame_hash
    assert hashes["semantic_ids"]["compatibility_hash"] == compatibility.compatibility_hash
    assert hashes["semantic_ids"]["projection_hashes"] == {
        name: projection.projection_hash for name, projection in projections.items()
    }

    purpose_payload = json.loads((fixtures / "gate0-purpose-projections.json").read_text())
    purpose_projections = {
        name: ProjectionEnvelope.model_validate(payload)
        for name, payload in purpose_payload.items()
    }
    assert set(purpose_projections) == {"lifecycle_possibility", "operation"}
    assert purpose_projections["lifecycle_possibility"].lifecycle_possibility is not None
    assert purpose_projections["operation"].lifecycle_possibility is None
    for projection in purpose_projections.values():
        assert verify_projection(frame, projection) == projection

    receipt = json.loads((fixtures / "gate0-contract-semantic-supersession.json").read_text())
    assert receipt["schema"] == "hapax.context-canon.contract-semantic-supersession.v1"
    assert receipt["semantics"] == {
        "changes": [
            "context exposure and external behavior are separate content-addressed non-authorizing carriers",
            "measurement application and observability invalidation are typed one-target support receipts",
            "epistemic event vocabulary records exposure and behavior without admitting action-time receipts into frozen frames",
        ],
        "historical_bytes_preserved": True,
        "historical_source_proof_preserved": True,
        "source_only_semantic_equivalence": False,
        "wire_schema_ids_retained": True,
        "wire_schema_ids_retained_basis": "unreleased_gate0_contract",
    }
    checkpoint_manifest = (
        fixtures / receipt["predecessor"]["checkpoint_manifest"]["path"]
    ).read_bytes()
    assert len(checkpoint_manifest) == receipt["predecessor"]["checkpoint_manifest"]["bytes"]
    assert (
        hashlib.sha256(checkpoint_manifest).hexdigest()
        == receipt["predecessor"]["checkpoint_manifest"]["sha256"]
    )
    for name, expected in receipt["current"]["files"].items():
        payload = (fixtures / name).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]

    predecessor_frame = json.loads(
        (
            fixtures
            / "checkpoints/pre-observability-extension-20260713/gate0-frame.json"
        ).read_text()
    )
    for field, expected in receipt["protected_commitments"].items():
        assert getattr(frame.position, field) == expected["current"]
        assert predecessor_frame["position"][field] == expected["predecessor"]
        assert expected["current"] == expected["predecessor"]
