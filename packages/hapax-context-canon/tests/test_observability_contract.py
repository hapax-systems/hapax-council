from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import hapax.context_canon as canon

STAGE_TIMES = {
    "selected": "2026-07-12T16:00:00Z",
    "sealed": "2026-07-12T16:00:10Z",
    "rendered": "2026-07-12T16:00:20Z",
    "presented": "2026-07-12T16:00:30Z",
    "acknowledged": "2026-07-12T16:00:40Z",
}


def _address(prefix: str, value: object) -> tuple[str, str]:
    digest = hashlib.sha256(canon.canonical_json_bytes(value)).hexdigest()
    return f"{prefix}@sha256:{digest}", digest


def _domain_address(prefix: str, domain: str, value: object) -> tuple[str, str]:
    digest = hashlib.sha256(
        domain.encode("ascii") + b"\x00" + canon.canonical_json_bytes(value)
    ).hexdigest()
    return f"{prefix}@sha256:{digest}", digest


class _OutcomeFixture:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = body
        receipt_ref, receipt_hash = _domain_address(
            "outcome-receipt",
            "hapax.outcome-receipt.v1",
            body,
        )
        self.receipt_ref = receipt_ref
        self.receipt_hash = receipt_hash
        for field_name, value in body.items():
            if field_name in {"append_receipt", "event_frontier"}:
                value = SimpleNamespace(**value)  # type: ignore[arg-type]
            setattr(self, field_name if field_name != "schema" else "schema_id", value)

    def model_dump(
        self,
        *,
        mode: str,
        by_alias: bool,
        exclude: set[str],
    ) -> dict[str, object]:
        assert mode == "json" and by_alias and exclude == {"receipt_ref", "receipt_hash"}
        return self._body


def _state(value_state: str = "present", *reasons: str) -> canon.ContextState:
    return canon.ContextState(value_state=value_state, reason_codes=tuple(sorted(reasons)))


def _quantity(
    unit: str,
    value: int | None,
    *,
    value_state: str = "present",
) -> canon.ContextExposureQuantity:
    reasons = () if value_state == "present" else (f"{unit}_count_{value_state}",)
    return canon.ContextExposureQuantity(
        value=value,
        unit=unit,
        state=_state(value_state, *reasons),
        method_ref="method:fixture-counter",
    )


def _provenance(source_ref: str, *, dark: bool = False) -> canon.ContextProvenance:
    return canon.ContextProvenance(
        kind="dark" if dark else "observed",
        source_refs=(source_ref,),
        producer_ref="producer:fixture",
        derivation="asserted",
        authority_level="support_non_authoritative",
        generation="generation:fixture-1",
        policy_generation="policy:fixture-1",
        observed_at="2026-07-12T15:59:00Z",
        produced_at="2026-07-12T15:59:01Z",
        stale_after="2026-07-12T18:00:00Z",
    )


def _air(*, public_or_air: str = "deny") -> canon.ContextAirPolicy:
    return canon.ContextAirPolicy(
        operator_private="allow",
        yard_context="redact",
        hapax_substrate="redact",
        public_or_air=public_or_air,
        derived_channel_sealed=True,
    )


def _component(
    component_id: str,
    influence: canon.ContextInfluenceClass,
    *,
    dark: bool = False,
    public_allowed: bool = False,
) -> canon.ContextExposureComponent:
    source_ref, _ = _address("source-descriptor", {"component_id": component_id})
    if dark:
        return canon.build_context_exposure_component(
            component_id=component_id,
            component_kind="governed_context_atom",
            source_class="lifecycle_canon",
            source_ref=source_ref,
            content_ref=None,
            content_hash=None,
            content_address_class="none_dark",
            hash_disclosure="dark",
            provenance=_provenance(source_ref, dark=True),
            intended_influence_class=influence,
            authority_ceiling="observation_only",
            air=_air(),
            privacy_class="operator_private",
            transformation_state="unknown",
            compaction_state="unknown",
            byte_count=_quantity("byte", None, value_state="dark"),
            token_count=_quantity("token", None, value_state="dark"),
            valid_from="2026-07-12T15:59:00Z",
            valid_until="2026-07-12T18:00:00Z",
            freshness_state="dark",
            disposition="dark",
            state=_state("dark", "source_body_unavailable"),
        )
    content_ref, content_hash = _address(
        "sealed-context-object",
        {"ciphertext_object": component_id, "key_scope": "operator_private"},
    )
    return canon.build_context_exposure_component(
        component_id=component_id,
        component_kind="governed_context_atom",
        source_class="lifecycle_canon",
        source_ref=source_ref,
        content_ref=content_ref,
        content_hash=content_hash,
        content_address_class="source_local_sealed",
        hash_disclosure="sealed_only",
        provenance=_provenance(source_ref),
        intended_influence_class=influence,
        authority_ceiling="constitutional_evidence",
        air=_air(public_or_air="allow" if public_allowed else "deny"),
        privacy_class="operator_private",
        transformation_state="verbatim",
        compaction_state="none",
        byte_count=_quantity("byte", 128),
        token_count=_quantity("token", None, value_state="uncertain"),
        valid_from="2026-07-12T15:59:00Z",
        valid_until="2026-07-12T18:00:00Z",
        freshness_state="fresh",
        disposition="included",
        state=_state(),
    )


def _segment(
    stage: canon.ContextExposureStageKind,
    ordinal: int,
    component_refs: tuple[str, ...],
) -> canon.ContextExposureSegment:
    artifact_ref, artifact_hash = _address(
        f"sealed-{stage}-artifact",
        {"components": component_refs, "ordinal": ordinal, "stage": stage},
    )
    transformation_ref, _ = _address(
        "context-transform",
        {"ordinal": ordinal, "stage": stage, "version": 1},
    )
    return canon.build_context_exposure_segment(
        stage=stage,
        ordinal=ordinal,
        component_refs=component_refs,
        artifact_ref=artifact_ref,
        artifact_hash=artifact_hash,
        artifact_address_class="source_local_sealed",
        hash_disclosure="sealed_only",
        transformation_ref=transformation_ref,
        byte_count=_quantity("byte", 128 * len(component_refs)),
        token_count=_quantity("token", None, value_state="uncertain"),
        disposition="included",
        state=_state(),
    )


def _uncarried_segment(
    stage: canon.ContextExposureStageKind,
    ordinal: int,
    component_refs: tuple[str, ...],
    *,
    dark: bool,
) -> canon.ContextExposureSegment:
    transformation_ref, _ = _address(
        "context-transform",
        {"ordinal": ordinal, "stage": stage, "uncarried": True, "version": 1},
    )
    value_state = "dark" if dark else "absent"
    return canon.build_context_exposure_segment(
        stage=stage,
        ordinal=ordinal,
        component_refs=component_refs,
        artifact_ref=None,
        artifact_hash=None,
        artifact_address_class="none_dark" if dark else "none_omitted",
        hash_disclosure="dark" if dark else "redacted",
        transformation_ref=transformation_ref,
        byte_count=_quantity("byte", None, value_state=value_state),
        token_count=_quantity("token", None, value_state=value_state),
        disposition="dark" if dark else "omitted",
        state=_state(value_state, f"stage_artifact_{value_state}"),
    )


def _stage(
    stage: canon.ContextExposureStageKind,
    segments: tuple[canon.ContextExposureSegment, ...],
    *,
    uncarried: tuple[canon.ContextExposureSegment, ...] = (),
    removed: tuple[str, ...] = (),
) -> canon.ContextExposureStage:
    declared = (*segments, *uncarried)
    reasons = {
        f"stage:{stage}:segment:{segment.ordinal}:{segment.disposition}:"
        f"{segment.state.value_state}"
        for segment in declared
        if segment.disposition != "included" or segment.state.value_state != "present"
    }
    if removed:
        reasons.add(f"stage:{stage}:components_removed")
    if not reasons:
        checked_state = _state()
    elif not segments and {item.state.value_state for item in declared} == {"dark"}:
        checked_state = _state("dark", *reasons)
    elif not segments and {item.state.value_state for item in declared} == {"absent"}:
        checked_state = _state("absent", *reasons)
    else:
        checked_state = _state("partial", *reasons)
    loss_ref, _ = _address(
        "context-exposure-stage-loss",
        {"removed": removed, "stage": stage, "state": checked_state.value_state},
    )
    evidence_ref, _ = _address("carriage-evidence", {"stage": stage})
    return canon.ContextExposureStage(
        stage=stage,
        ordered_segment_refs=tuple(item.segment_ref for item in segments),
        removed_component_refs=removed,
        evidence_refs=(evidence_ref,),
        loss_manifest_ref=loss_ref,
        occurred_at=STAGE_TIMES[stage],
        checked_at="2026-07-12T16:00:50Z",
        stale_after="2026-07-12T18:00:00Z",
        state=checked_state,
    )


def _carriage(
    components: tuple[canon.ContextExposureComponent, ...],
    *,
    acknowledged_dark: bool = False,
) -> tuple[tuple[canon.ContextExposureSegment, ...], tuple[canon.ContextExposureStage, ...]]:
    included_refs = tuple(
        sorted(item.component_ref for item in components if item.disposition == "included")
    )
    all_refs = tuple(sorted(item.component_ref for item in components))
    segments_by_stage: dict[str, tuple[canon.ContextExposureSegment, ...]] = {
        "selected": tuple(
            _segment("selected", ordinal, (component_ref,))
            for ordinal, component_ref in enumerate(included_refs)
        ),
        "sealed": (_segment("sealed", 0, included_refs),),
        "rendered": (
            _segment("rendered", 0, (included_refs[0],)),
            _segment("rendered", 1, (included_refs[0],)),
            _segment("rendered", 2, (included_refs[1],)),
        ),
        "presented": (_segment("presented", 0, included_refs),),
        "acknowledged": (
            () if acknowledged_dark else (_segment("acknowledged", 0, included_refs),)
        ),
    }
    uncarried_by_stage: dict[str, tuple[canon.ContextExposureSegment, ...]] = {
        stage: () for stage in STAGE_TIMES
    }
    if acknowledged_dark:
        uncarried_by_stage["acknowledged"] = (
            _uncarried_segment("acknowledged", 0, included_refs, dark=True),
        )
    stages: list[canon.ContextExposureStage] = []
    for stage_name in STAGE_TIMES:
        stage = stage_name
        if stage == "selected":
            removed = tuple(sorted(set(all_refs) - set(included_refs)))
        elif stage == "acknowledged" and acknowledged_dark:
            removed = included_refs
        else:
            removed = ()
        stages.append(
            _stage(
                stage,  # type: ignore[arg-type]
                segments_by_stage[stage],
                uncarried=uncarried_by_stage[stage],
                removed=removed,
            )
        )
    all_segments = tuple(
        segment
        for stage in STAGE_TIMES
        for segment in (*segments_by_stage[stage], *uncarried_by_stage[stage])
    )
    return all_segments, tuple(stages)


def _build_exposure(
    *,
    acknowledged_dark: bool = False,
    include_dark_component: bool = False,
    correction_refs: tuple[str, ...] = (),
    supersedes_refs: tuple[str, ...] = (),
    audience: str = "operator_private",
    producer_verified: bool = False,
    observed_at: str = "2026-07-12T16:00:41Z",
) -> canon.ContextExposure:
    components = [
        _component(
            "what.current",
            "what",
            public_allowed=audience == "public_or_air",
        ),
        _component(
            "must.no-escape",
            "must",
            public_allowed=audience == "public_or_air",
        ),
    ]
    if include_dark_component:
        components.append(_component("orientation.private", "orientation", dark=True))
    checked_components = tuple(sorted(components, key=lambda item: item.component_ref))
    segments, stages = _carriage(checked_components, acknowledged_dark=acknowledged_dark)
    invocation_ref, invocation_hash = _address("invocation", {"id": "invocation:1"})
    served_ref, served_hash = _address("served-identity", {"leaf": "fixture"})
    demand_ref, demand_hash = _address("demand-shape", {"region": "fixture"})
    basis_ref, basis_hash = _address("measurement-basis", {"revision": 1})
    frontier_ref, frontier_hash = _address("event-frontier", {"generation": 7})
    frame_ref, frame_hash = _address("context-frame", {"generation": 7})
    selection_ref, selection_hash = _address("context-selection", {"frontier": frontier_ref})
    projection_ref, projection_hash = _address(
        "projection-envelope",
        {
            "audience": "operator_private",
            "frame": frame_ref,
            "purpose": "pre_exposure_inspection",
            "selection": selection_ref,
        },
    )
    seal_ref, seal_hash = _address(
        "audience-seal-receipt",
        {"audience": audience, "selection": selection_ref},
    )
    position_ref, _ = _address("context-position", {"stage": "S6"})
    loss_ref, _ = _address(
        "context-exposure-loss",
        {"acknowledged_dark": acknowledged_dark, "dark_component": include_dark_component},
    )
    resolution_obligation_ref, _ = _address(
        "producer-resolution-obligation",
        {"carrier": "context-exposure", "gate": "Gate0B"},
    )
    producer_verification_ref, _ = _address(
        "producer-verification-receipt",
        {"carrier": "context-exposure", "invocation_id": "invocation:1"},
    )
    state_reasons: list[str] = []
    if include_dark_component:
        state_reasons.extend(
            (
                "component:orientation.private:dark:dark",
                "stage:selected:components_removed",
                "stage:selected:partial",
            )
        )
    if acknowledged_dark:
        state_reasons.extend(
            (
                "stage:acknowledged:components_removed",
                "stage:acknowledged:dark",
                "segment:acknowledged:0:dark:dark",
            )
        )
    root_state = _state("partial", *state_reasons) if state_reasons else _state()
    return canon.build_context_exposure(
        schema="hapax.context-exposure.v1",
        invocation_id="invocation:1",
        attempt_fence=hashlib.sha256(b"attempt:1").hexdigest(),
        invocation_ref=invocation_ref,
        invocation_hash=invocation_hash,
        served_identity_ref=served_ref,
        served_identity_hash=served_hash,
        demand_shape_ref=demand_ref,
        demand_shape_fingerprint=demand_hash,
        measurement_basis_ref=basis_ref,
        measurement_basis_hash=basis_hash,
        context_frontier_ref=frontier_ref,
        context_frontier_hash=frontier_hash,
        session_ref="session:fixture",
        task_ref="task:fixture",
        trace_ref="trace:fixture",
        scope_ref="scope:fixture",
        temporal_ref="temporal:fixture",
        resolution_ref="resolution:fixture",
        position_ref=position_ref,
        frame_ref=frame_ref,
        frame_hash=frame_hash,
        selection_ref=selection_ref,
        selection_hash=selection_hash,
        pre_exposure_inspection_projection_ref=projection_ref,
        pre_exposure_inspection_projection_hash=projection_hash,
        pre_exposure_inspection_audience="operator_private",
        pre_exposure_inspection_claim_ceiling=(
            "frozen_frame_selection_only_no_actual_carriage"
        ),
        carrier_audience=audience,
        audience_seal_ref=seal_ref,
        audience_seal_hash=seal_hash,
        components=checked_components,
        segments=segments,
        stages=stages,
        loss_manifest_ref=loss_ref,
        correction_refs=correction_refs,
        supersedes_refs=supersedes_refs,
        observed_at=observed_at,
        checked_at="2026-07-12T16:00:50Z",
        stale_after="2026-07-12T18:00:00Z",
        state=root_state,
        verification_scope="structure_and_content_address_only",
        producer_verification_required=True,
        producer_resolution_obligation_ref=resolution_obligation_ref,
        producer_verification_refs=(producer_verification_ref,) if producer_verified else (),
        producer_resolution_state=(
            _state()
            if producer_verified
            else _state("hold", "gate0b_producer_resolution_required")
        ),
        authority_ceiling="observation_only",
        effective_attention_observed=False,
        causal_effect_observed=False,
    )


def _event(
    exposure: canon.ContextExposure,
    *,
    behavior: canon.CapabilityBehaviorObservation | None = None,
    event_id: str = "event:exposure",
    caused_by: tuple[str, ...] = (),
    occurred_at: str | None = None,
) -> canon.EpistemicFlowEvent:
    is_behavior = behavior is not None
    subject_ref = behavior.behavior_ref if behavior else exposure.exposure_ref
    return canon.build_epistemic_flow_event(
        event_id=event_id,
        kind="capability_behavior_observed" if is_behavior else "context_exposure_recorded",
        session_ref=exposure.session_ref,
        task_ref=exposure.task_ref,
        trace_ref=exposure.trace_ref,
        position_ref=exposure.position_ref,
        scope_ref=exposure.scope_ref,
        temporal_ref=exposure.temporal_ref,
        resolution_ref=exposure.resolution_ref,
        generation=9 if is_behavior else 8,
        subject_ref=subject_ref,
        occurred_at=occurred_at
        or ("2026-07-12T16:01:05Z" if is_behavior else "2026-07-12T16:00:45Z"),
        expires_at="2026-07-12T18:00:00Z",
        producer_ref="producer:spine-observer",
        method_ref="method:deterministic",
        privacy_class="operator_private",
        authority_ceiling="observation_only",
        source_refs=(
            (behavior.behavior_ref, exposure.exposure_ref)
            if behavior
            else (exposure.exposure_ref,)
        ),
        caused_by=caused_by,
        supersedes_refs=(),
        derivation_depth=1 if is_behavior else 0,
        payload=(
            {
                "behavior_ref": behavior.behavior_ref,
                "behavior_state": behavior.state.value_state,
            }
            if behavior
            else {
                "exposure_ref": exposure.exposure_ref,
                "exposure_state": exposure.state.value_state,
            }
        ),
        state=behavior.state if behavior else exposure.state,
    )


def _confidence(evidence_ref: str, basis_ref: str) -> canon.ContextConfidence:
    return canon.ContextConfidence(
        word="high",
        method="deterministic",
        evidence_refs=(evidence_ref,),
        calibration_ref=None,
        calibration_metric=None,
        validity_domain_refs=(basis_ref,),
        distribution_state="in_domain",
        abstained=False,
    )


def _datum(
    exposure: canon.ContextExposure,
    basis_dimension_ref: str,
    boundary_ref: str,
    *,
    ordinal: int,
    refused: bool = False,
    dark: bool = False,
) -> canon.CapabilityBehaviorDatum:
    observation_ref, observation_hash = _address(
        "external-behavior-observation",
        {"dark": dark, "ordinal": ordinal, "refused": refused},
    )
    evidence_ref, _ = _address("behavior-evidence", {"observation": observation_ref})
    if dark:
        state = _state("dark", "behavior_evidence_dark")
        freshness = "dark"
        disposition = "not_observed"
    else:
        state = _state()
        freshness = "fresh"
        disposition = "refused" if refused else "produced"
    return canon.CapabilityBehaviorDatum(
        ordinal=ordinal,
        behavior_kind="refusal" if refused else "output",
        behavior_disposition=disposition,
        demand_region_ref=exposure.demand_shape_ref,
        basis_dimension_ref=basis_dimension_ref,
        fitness_boundary_ref=boundary_ref,
        observation_ref=observation_ref,
        observation_hash=observation_hash,
        observed_value=None,
        evidence_refs=(evidence_ref,),
        does_not_prove=(
            "Context exposure caused this behavior.",
            "Hidden reasoning or attention was observed.",
        ),
        observed_at="2026-07-12T16:01:00Z",
        freshness_state=freshness,
        confidence=_confidence(evidence_ref, exposure.measurement_basis_ref),
        state=state,
    )


def _build_behavior(
    exposure: canon.ContextExposure,
    exposure_event: canon.EpistemicFlowEvent,
    *,
    refused: bool = False,
    dark: bool = False,
    correction_refs: tuple[str, ...] = (),
    producer_verified: bool = False,
    observed_at: str = "2026-07-12T16:01:00Z",
) -> canon.CapabilityBehaviorObservation:
    basis_dimension_ref, _ = _address(
        "basis-dimension",
        {"dimension": "constraint-response"},
    )
    boundary_ref, _ = _address("fitness-boundary", {"boundary": "constraint-response-v1"})
    datum = _datum(
        exposure,
        basis_dimension_ref,
        boundary_ref,
        ordinal=0,
        refused=refused,
        dark=dark,
    )
    conditions = {
        name: _address(f"{name}-condition", {"revision": 1})
        for name in ("harness", "resource", "delivery", "evaluator")
    }
    regime_ref, regime_hash = _address("capability-regime", {"id": "fixture"})
    epoch_ref, epoch_hash = _address("capability-epoch", {"id": "fixture-1"})
    event_frontier_ref, event_frontier_hash = _address(
        "event-frontier",
        {"generation": 9, "parent": exposure.context_frontier_ref},
    )
    resolution_obligation_ref, _ = _address(
        "producer-resolution-obligation",
        {"carrier": "capability-behavior", "gate": "Gate0B"},
    )
    behavior_seal_ref, behavior_seal_hash = _address(
        "audience-seal-receipt",
        {
            "audience": exposure.carrier_audience,
            "carrier": "capability-behavior",
            "exposure": exposure.exposure_ref,
        },
    )
    producer_verification_ref, _ = _address(
        "producer-verification-receipt",
        {"carrier": "capability-behavior", "invocation_id": exposure.invocation_id},
    )
    root_state = (
        _state(
            "dark",
            f"basis_dimension:{basis_dimension_ref}:dark",
            "datum:0:dark",
        )
        if dark
        else _state()
    )
    return canon.build_capability_behavior_observation(
        schema="hapax.capability-behavior-observation.v1",
        invocation_id=exposure.invocation_id,
        attempt_fence=exposure.attempt_fence,
        invocation_ref=exposure.invocation_ref,
        invocation_hash=exposure.invocation_hash,
        exposure_ref=exposure.exposure_ref,
        exposure_hash=exposure.exposure_hash,
        served_identity_ref=exposure.served_identity_ref,
        served_identity_hash=exposure.served_identity_hash,
        demand_shape_ref=exposure.demand_shape_ref,
        demand_shape_fingerprint=exposure.demand_shape_fingerprint,
        measurement_basis_ref=exposure.measurement_basis_ref,
        measurement_basis_hash=exposure.measurement_basis_hash,
        context_frontier_ref=exposure.context_frontier_ref,
        context_frontier_hash=exposure.context_frontier_hash,
        behavior_frontier_parent_ref=exposure.context_frontier_ref,
        behavior_frontier_parent_hash=exposure.context_frontier_hash,
        behavior_event_frontier_ref=event_frontier_ref,
        behavior_event_frontier_hash=event_frontier_hash,
        session_ref=exposure.session_ref,
        task_ref=exposure.task_ref,
        trace_ref=exposure.trace_ref,
        scope_ref=exposure.scope_ref,
        temporal_ref=exposure.temporal_ref,
        resolution_ref=exposure.resolution_ref,
        position_ref=exposure.position_ref,
        carrier_audience=exposure.carrier_audience,
        privacy_class="operator_private",
        air=_air(
            public_or_air=(
                "allow" if exposure.carrier_audience == "public_or_air" else "deny"
            )
        ),
        audience_seal_ref=behavior_seal_ref,
        audience_seal_hash=behavior_seal_hash,
        source_local_only=True,
        harness_condition_ref=conditions["harness"][0],
        harness_condition_hash=conditions["harness"][1],
        resource_condition_ref=conditions["resource"][0],
        resource_condition_hash=conditions["resource"][1],
        delivery_condition_ref=conditions["delivery"][0],
        delivery_condition_hash=conditions["delivery"][1],
        evaluator_condition_ref=conditions["evaluator"][0],
        evaluator_condition_hash=conditions["evaluator"][1],
        regime_ref=regime_ref,
        regime_hash=regime_hash,
        epoch_ref=epoch_ref,
        epoch_hash=epoch_hash,
        observations=(datum,),
        required_basis_dimension_refs=(basis_dimension_ref,),
        unobserved_basis_dimension_refs=(),
        dark_basis_dimension_refs=(basis_dimension_ref,) if dark else (),
        basis_coverage=canon.CanonicalDecimal(
            value="0" if dark else "1",
            unit="proportion",
        ),
        contradiction_refs=(),
        correction_refs=correction_refs,
        supersedes_refs=(),
        valid_from="2026-07-12T16:00:30Z",
        valid_until="2026-07-12T17:00:00Z",
        observed_at=observed_at,
        checked_at="2026-07-12T16:01:02Z",
        stale_after="2026-07-12T18:00:00Z",
        state=root_state,
        verification_scope="structure_and_content_address_only",
        producer_verification_required=True,
        producer_resolution_obligation_ref=resolution_obligation_ref,
        producer_verification_refs=(producer_verification_ref,) if producer_verified else (),
        producer_resolution_state=(
            _state()
            if producer_verified
            else _state("hold", "gate0b_producer_resolution_required")
        ),
        observation_plane="capability_behavior",
        correlation_only=True,
        causal_effect_claimed=False,
        authority_ceiling="observation_only",
    )


def _outcome(
    exposure: canon.ContextExposure,
    behavior: canon.CapabilityBehaviorObservation,
    *,
    committed_at: str = "2026-07-12T16:01:10.000000Z",
) -> Any:
    def address(field_name: str) -> dict[str, str]:
        ref, digest = _address(
            field_name.replace("_", "-"),
            {
                "field": field_name,
                "invocation_id": exposure.invocation_id,
                "behavior_ref": behavior.behavior_ref,
            },
        )
        return {"ref": ref, "sha256": digest}

    frontier_ref, frontier_hash = _address(
        "event-frontier",
        {"generation": 10, "parent": behavior.behavior_event_frontier_ref},
    )
    append_ref, append_hash = _address(
        "event-append-receipt",
        {"invocation_id": exposure.invocation_id, "outcome_event": "event:fixture"},
    )
    return _OutcomeFixture(
        {
            "schema": "hapax.outcome-receipt.v1",
            "execution_lease": address("execution_lease"),
            "bound_execution_call": address("bound_execution_call"),
            "effect_observation": address("effect_observation"),
            "completion_evaluation": address("completion_evaluation"),
            "outcome_readiness": address("outcome_readiness"),
            "effect_manifest": address("effect_manifest"),
            "executor_descriptor": address("executor_descriptor"),
            "executor_registry_projection": address("executor_registry_projection"),
            "executor": address("executor"),
            "observation_contract": address("observation_contract"),
            "completion_predicate": address("completion_predicate"),
            "invocation_id": exposure.invocation_id,
            "attempt_fence": exposure.attempt_fence,
            "idempotency_key": "idempotency:fixture",
            "committer": address("committer"),
            "outcome_event": address("outcome_event"),
            "committed_at": committed_at,
            "outcome": "succeeded",
            "effect_disposition": "applied",
            "closure_state": "closed",
            "append_receipt": {"ref": append_ref, "sha256": append_hash},
            "event_frontier": {"ref": frontier_ref, "sha256": frontier_hash},
            "reconciliation_contract": address("reconciliation_contract"),
            "may_authorize": False,
        }
    )


def _build_application(
    exposure: canon.ContextExposure,
    behavior: canon.CapabilityBehaviorObservation,
    outcome: Any,
    *,
    applied_at: str = "2026-07-12T16:01:11Z",
    correction_refs: tuple[str, ...] = (),
) -> canon.MeasurementApplicationReceipt:
    committer_ref, committer_hash = _address("application-committer", {"id": "fixture"})
    frontier_ref, frontier_hash = _address(
        "event-frontier",
        {"generation": 11, "parent": outcome.event_frontier.ref},
    )
    obligation_ref, _ = _address(
        "producer-resolution-obligation",
        {"carrier": "measurement-application", "gate": "Gate0B"},
    )
    verification_ref, _ = _address(
        "producer-verification-receipt",
        {"carrier": "measurement-application", "invocation": exposure.invocation_id},
    )
    boundaries = tuple(sorted({item.fitness_boundary_ref for item in behavior.observations}))
    return canon.build_measurement_application_receipt(
        schema="hapax.measurement-application-receipt.v1",
        application_id="measurement-application:capability-posterior",
        invocation_id=exposure.invocation_id,
        attempt_fence=exposure.attempt_fence,
        exposure_ref=exposure.exposure_ref,
        exposure_hash=exposure.exposure_hash,
        behavior_ref=behavior.behavior_ref,
        behavior_hash=behavior.behavior_hash,
        outcome_ref=outcome.receipt_ref,
        outcome_hash=outcome.receipt_hash,
        outcome_append_receipt_ref=outcome.append_receipt.ref,
        outcome_append_receipt_hash=outcome.append_receipt.sha256,
        committer_ref=committer_ref,
        committer_hash=committer_hash,
        application_frontier_ref=frontier_ref,
        application_frontier_hash=frontier_hash,
        measurement_basis_ref=behavior.measurement_basis_ref,
        measurement_basis_hash=behavior.measurement_basis_hash,
        fitness_boundary_refs=boundaries,
        update_target_ref="learning-target:capability-posterior",
        target_count=1,
        correction_refs=correction_refs,
        supersedes_refs=(),
        applied_at=applied_at,
        state=_state(),
        verification_scope="structure_and_content_address_only",
        producer_verification_required=True,
        producer_resolution_obligation_ref=obligation_ref,
        producer_verification_refs=(verification_ref,),
        producer_resolution_state=_state(),
    )


def _build_learning(
    exposure: canon.ContextExposure,
    behavior: canon.CapabilityBehaviorObservation,
    outcome: Any,
    application: canon.MeasurementApplicationReceipt,
    *,
    applied: bool = True,
    correction_refs: tuple[str, ...] = (),
    recorded_at: str = "2026-07-12T16:01:12Z",
) -> canon.SignalLearningReceipt:
    boundaries = tuple(sorted({item.fitness_boundary_ref for item in behavior.observations}))
    return canon.build_signal_learning_receipt(
        learning_id="learning:capability-under-context",
        position_ref=exposure.position_ref,
        estimate_ref="signal-estimate:fixture",
        constellation_ref="signal-constellation:fixture",
        exposure_ref=exposure.exposure_ref,
        behavior_ref=behavior.behavior_ref,
        measurement_basis_ref=behavior.measurement_basis_ref,
        fitness_boundary_refs=boundaries,
        candidate_set_ref="candidate-set:fixture",
        selection_policy_ref="selection-policy:fixture",
        selection_propensity=canon.CanonicalDecimal(value="1", unit="probability"),
        action_ref="action:fixture",
        outcome_ref=outcome.receipt_ref,
        effect={"claim": "association_only"},
        cost={"class": "fixture"},
        witness_refs=(behavior.behavior_ref,),
        receipt_ref=application.application_ref,
        correction_refs=correction_refs,
        supersedes_refs=(),
        update_target_ref="learning-target:capability-posterior",
        update_applied=applied,
        recorded_at=recorded_at,
        state=_state(),
    )


def _rehash(builder: Any, carrier: Any, updates: dict[str, object]) -> Any:
    payload = carrier.model_dump(mode="json", by_alias=True)
    if isinstance(carrier, canon.ContextExposure):
        identity_fields = ("exposure_ref", "exposure_hash")
    elif isinstance(carrier, canon.CapabilityBehaviorObservation):
        identity_fields = ("behavior_ref", "behavior_hash")
    elif isinstance(carrier, canon.MeasurementApplicationReceipt):
        identity_fields = ("application_ref", "application_hash")
    else:
        identity_fields = ("learning_ref", "learning_hash")
    for field_name in identity_fields:
        payload.pop(field_name, None)
    payload.update(updates)
    return builder(**payload)


def test_exposure_separates_semantic_components_from_stage_artifacts() -> None:
    exposure = _build_exposure(audience="public_or_air")
    private_exposure = _build_exposure(audience="operator_private")
    rebuilt = canon.ContextExposure.model_validate_json(
        canon.canonical_json_bytes(exposure.model_dump(mode="json", by_alias=True))
    )

    assert rebuilt == exposure
    assert exposure.selection_ref.startswith("context-selection@sha256:")
    assert exposure.pre_exposure_inspection_projection_ref.startswith(
        "projection-envelope@sha256:"
    )
    assert exposure.pre_exposure_inspection_audience == "operator_private"
    assert (
        exposure.pre_exposure_inspection_claim_ceiling
        == "frozen_frame_selection_only_no_actual_carriage"
    )
    assert exposure.carrier_audience == "public_or_air"
    assert (
        exposure.pre_exposure_inspection_projection_ref
        == private_exposure.pre_exposure_inspection_projection_ref
    )
    assert len(exposure.stages[0].ordered_segment_refs) == 2
    assert len(exposure.stages[1].ordered_segment_refs) == 1
    assert len(exposure.stages[2].ordered_segment_refs) == 3
    rendered_segments = [
        segment for segment in exposure.segments if segment.stage == "rendered"
    ]
    assert sum(
        exposure.components[0].component_ref in segment.component_refs
        for segment in rendered_segments
    ) in {1, 2}
    assert any(
        sum(component.component_ref in segment.component_refs for segment in rendered_segments)
        == 2
        for component in exposure.components
    )
    assert all(segment.byte_count.value is not None for segment in exposure.segments)
    assert all(segment.token_count.value is None for segment in exposure.segments)
    assert exposure.state == _state()
    assert exposure.no_effect and not exposure.may_authorize

    with pytest.raises(ValidationError, match="carrier AIR denial"):
        _rehash(
            canon.build_context_exposure,
            private_exposure,
            {"carrier_audience": "public_or_air"},
        )


def test_private_and_dark_components_are_identity_accounted_without_plaintext() -> None:
    exposure = _build_exposure(include_dark_component=True)
    dark = next(item for item in exposure.components if item.disposition == "dark")
    sealed = next(item for item in exposure.components if item.disposition == "included")

    assert dark.content_ref is None and dark.content_hash is None
    assert dark.content_address_class == "none_dark"
    assert dark.hash_disclosure == "dark"
    assert dark.byte_count.value is None and dark.token_count.value is None
    assert sealed.content_address_class == "source_local_sealed"
    assert sealed.hash_disclosure == "sealed_only"
    assert exposure.stages[0].removed_component_refs == (dark.component_ref,)
    assert exposure.state.value_state == "partial"

    payload = dark.model_dump(mode="json", by_alias=True)
    payload.pop("component_ref")
    payload.pop("component_hash")
    leaked_ref, leaked_hash = _address("plaintext-private-body", {"text": "private"})
    payload.update(content_ref=leaked_ref, content_hash=leaked_hash)
    with pytest.raises(ValidationError, match="DARK content cannot disclose"):
        canon.build_context_exposure_component(**payload)


def test_stage_removals_are_exact_and_root_state_is_derived() -> None:
    exposure = _build_exposure(acknowledged_dark=True)
    assert exposure.stages[-1].state.value_state == "dark"
    assert exposure.stages[-1].removed_component_refs == tuple(
        sorted(item.component_ref for item in exposure.components)
    )
    assert exposure.state == _state(
        "partial",
        "segment:acknowledged:0:dark:dark",
        "stage:acknowledged:components_removed",
        "stage:acknowledged:dark",
    )

    stages = list(exposure.stages)
    stages[-1] = stages[-1].model_copy(update={"removed_component_refs": ()})
    with pytest.raises(ValidationError, match="uncarried segment|exact prior-stage"):
        _rehash(canon.build_context_exposure, exposure, {"stages": tuple(stages)})

    with pytest.raises(ValidationError, match="component and stage-derived state"):
        _rehash(canon.build_context_exposure, exposure, {"state": _state()})

    presented_index = 3
    presented_ref = exposure.stages[presented_index].ordered_segment_refs[0]
    presented = next(item for item in exposure.segments if item.segment_ref == presented_ref)
    dark_segment = _uncarried_segment(
        "presented",
        0,
        presented.component_refs,
        dark=True,
    )
    bad_segments = tuple(
        dark_segment if item.segment_ref == presented_ref else item
        for item in exposure.segments
    )
    bad_stages = list(exposure.stages)
    bad_stages[presented_index] = bad_stages[presented_index].model_copy(
        update={"ordered_segment_refs": (dark_segment.segment_ref,)}
    )
    with pytest.raises(ValidationError, match="only every carried artifact segment"):
        _rehash(
            canon.build_context_exposure,
            exposure,
            {"segments": bad_segments, "stages": tuple(bad_stages)},
        )

    segment_payload = presented.model_dump(mode="json", by_alias=True)
    segment_payload.pop("segment_ref")
    segment_payload.pop("segment_hash")
    segment_payload["hash_disclosure"] = "audience_permitted"
    with pytest.raises(ValidationError, match="address class and hash disclosure"):
        canon.build_context_exposure_segment(**segment_payload)


def test_behavior_refusal_is_fresh_present_and_dark_is_nonnumeric() -> None:
    exposure = _build_exposure()
    exposure_event = _event(exposure)
    refusal = _build_behavior(exposure, exposure_event, refused=True)
    dark = _build_behavior(exposure, exposure_event, dark=True)

    refusal_datum = refusal.observations[0]
    assert refusal_datum.behavior_disposition == "refused"
    assert refusal_datum.freshness_state == "fresh"
    assert refusal_datum.state == _state()
    assert refusal.state == _state()
    assert "Context exposure caused this behavior." in refusal_datum.does_not_prove
    assert dark.observations[0].observed_value is None
    assert dark.basis_coverage == canon.CanonicalDecimal(value="0", unit="proportion")
    assert dark.state.value_state == "dark"
    assert refusal.source_local_only is True
    assert refusal.audience_seal_ref.startswith("audience-seal-receipt@sha256:")

    first = refusal.observations[0]
    second = _datum(
        exposure,
        first.basis_dimension_ref,
        first.fitness_boundary_ref,
        ordinal=1,
        refused=False,
    )
    sequence = _rehash(
        canon.build_capability_behavior_observation,
        refusal,
        {"observations": (first, second)},
    )
    assert len(sequence.observations) == 2
    assert sequence.observations[0].basis_dimension_ref == (
        sequence.observations[1].basis_dimension_ref
    )
    assert sequence.basis_coverage == canon.CanonicalDecimal(value="1", unit="proportion")

    duplicate_ref = first.model_copy(update={"ordinal": 1})
    with pytest.raises(ValidationError, match="unique exact observation refs"):
        _rehash(
            canon.build_capability_behavior_observation,
            refusal,
            {"observations": (first, duplicate_ref)},
        )

    with pytest.raises(ValidationError, match="mechanically derived"):
        _rehash(
            canon.build_capability_behavior_observation,
            dark,
            {"basis_coverage": canon.CanonicalDecimal(value="1", unit="proportion")},
        )

    denied_air = refusal.air.model_copy(update={"operator_private": "deny"})
    with pytest.raises(ValidationError, match="behavior AIR denies"):
        _rehash(
            canon.build_capability_behavior_observation,
            refusal,
            {"air": denied_air},
        )


def test_applied_learning_requires_exact_join_and_committed_outcome() -> None:
    exposure = _build_exposure(producer_verified=True)
    exposure_event = _event(exposure)
    behavior = _build_behavior(exposure, exposure_event, producer_verified=True)
    behavior_event = _event(exposure, behavior=behavior, event_id="event:behavior")
    outcome = _outcome(exposure, behavior)
    application = _build_application(exposure, behavior, outcome)
    learning = _build_learning(exposure, behavior, outcome, application)

    assert canon.validate_context_behavior_learning_join(
        exposure=exposure,
        behavior=behavior,
        learning=learning,
        exposure_event=exposure_event,
        behavior_event=behavior_event,
        outcome_receipt=outcome,
        application_receipt=application,
    ) == (
        exposure.exposure_ref,
        behavior.behavior_ref,
        learning.learning_ref,
        outcome.receipt_ref,
        application.application_ref,
    )

    causal_behavior_event = _event(
        exposure,
        behavior=behavior,
        event_id="event:behavior-with-causal-exposure",
        caused_by=(exposure_event.event_ref,),
    )
    with pytest.raises(ValueError, match="correlation-only behavior"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=learning,
            exposure_event=exposure_event,
            behavior_event=causal_behavior_event,
            outcome_receipt=outcome,
            application_receipt=application,
        )

    same_second_outcome = _outcome(
        exposure,
        behavior,
        committed_at="2026-07-12T16:01:00.000000Z",
    )
    same_second_application = _build_application(exposure, behavior, same_second_outcome)
    same_second_learning = _build_learning(
        exposure,
        behavior,
        same_second_outcome,
        same_second_application,
    )
    same_second_behavior_event = _event(
        exposure,
        behavior=behavior,
        event_id="event:behavior-same-second",
        occurred_at="2026-07-12T16:01:00Z",
    )
    assert canon.validate_context_behavior_learning_join(
        exposure=exposure,
        behavior=behavior,
        learning=same_second_learning,
        exposure_event=exposure_event,
        behavior_event=same_second_behavior_event,
        outcome_receipt=same_second_outcome,
        application_receipt=same_second_application,
    )[3] == same_second_outcome.receipt_ref

    fractional_outcome = _outcome(
        exposure,
        behavior,
        committed_at="2026-07-12T16:01:11.999999Z",
    )
    early_application = _build_application(
        exposure,
        behavior,
        fractional_outcome,
        applied_at="2026-07-12T16:01:11Z",
    )
    early_learning = _build_learning(
        exposure,
        behavior,
        fractional_outcome,
        early_application,
    )
    with pytest.raises(ValueError, match="exact one-target measurement application"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=early_learning,
            exposure_event=exposure_event,
            behavior_event=behavior_event,
            outcome_receipt=fractional_outcome,
            application_receipt=early_application,
        )

    whole_second_outcome = _outcome(
        exposure,
        behavior,
        committed_at="2026-07-12T16:01:10Z",
    )
    whole_second_application = _build_application(exposure, behavior, whole_second_outcome)
    whole_second_learning = _build_learning(
        exposure,
        behavior,
        whole_second_outcome,
        whole_second_application,
    )
    with pytest.raises(ValueError, match="exact complete OutcomeReceipt v1 body"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=whole_second_learning,
            exposure_event=exposure_event,
            behavior_event=behavior_event,
            outcome_receipt=whole_second_outcome,
            application_receipt=whole_second_application,
        )

    wrong_schema_outcome = _OutcomeFixture(
        {**outcome._body, "schema": "other.outcome-receipt.v1"}
    )
    wrong_schema_application = _build_application(
        exposure,
        behavior,
        wrong_schema_outcome,
    )
    wrong_schema_learning = _build_learning(
        exposure,
        behavior,
        wrong_schema_outcome,
        wrong_schema_application,
    )
    with pytest.raises(ValueError, match="exact complete OutcomeReceipt v1 body"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=wrong_schema_learning,
            exposure_event=exposure_event,
            behavior_event=behavior_event,
            outcome_receipt=wrong_schema_outcome,
            application_receipt=wrong_schema_application,
        )

    wrong_outcome = _OutcomeFixture(
        {
            **outcome._body,
            "attempt_fence": hashlib.sha256(b"other-attempt").hexdigest(),
        }
    )
    wrong_outcome_application = _build_application(exposure, behavior, wrong_outcome)
    wrong_outcome_learning = _build_learning(
        exposure,
        behavior,
        wrong_outcome,
        wrong_outcome_application,
    )
    with pytest.raises(ValueError, match="current committed outcome"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=wrong_outcome_learning,
            exposure_event=exposure_event,
            behavior_event=behavior_event,
            outcome_receipt=wrong_outcome,
            application_receipt=wrong_outcome_application,
        )

    missing_append = _OutcomeFixture(
        {
            **outcome._body,
            "append_receipt": {
                "ref": outcome.append_receipt.ref,
                "sha256": hashlib.sha256(b"wrong-append").hexdigest(),
            },
        }
    )
    with pytest.raises(ValueError, match="append receipt"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=learning,
            exposure_event=exposure_event,
            behavior_event=behavior_event,
            outcome_receipt=missing_append,
            application_receipt=application,
        )

    reduced_body = {
        key: value
        for key, value in outcome._body.items()
        if key
        in {
            "schema",
            "invocation_id",
            "attempt_fence",
            "committed_at",
            "outcome",
            "effect_disposition",
            "closure_state",
            "append_receipt",
            "event_frontier",
            "may_authorize",
        }
    }
    reduced_outcome = _OutcomeFixture(reduced_body)
    reduced_application = _build_application(exposure, behavior, reduced_outcome)
    reduced_learning = _build_learning(
        exposure,
        behavior,
        reduced_outcome,
        reduced_application,
    )
    with pytest.raises(ValueError, match="exact complete OutcomeReceipt v1 body"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=reduced_learning,
            exposure_event=exposure_event,
            behavior_event=behavior_event,
            outcome_receipt=reduced_outcome,
            application_receipt=reduced_application,
        )

    extra_body_outcome = _OutcomeFixture({**outcome._body, "unexpected": "field"})
    extra_body_application = _build_application(exposure, behavior, extra_body_outcome)
    extra_body_learning = _build_learning(
        exposure,
        behavior,
        extra_body_outcome,
        extra_body_application,
    )
    with pytest.raises(ValueError, match="exact complete OutcomeReceipt v1 body"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=extra_body_learning,
            exposure_event=exposure_event,
            behavior_event=behavior_event,
            outcome_receipt=extra_body_outcome,
            application_receipt=extra_body_application,
        )

    divergent_attributes = _OutcomeFixture(dict(outcome._body))
    divergent_attributes.attempt_fence = hashlib.sha256(b"ignored-duck-attribute").hexdigest()
    assert canon.validate_context_behavior_learning_join(
        exposure=exposure,
        behavior=behavior,
        learning=learning,
        exposure_event=exposure_event,
        behavior_event=behavior_event,
        outcome_receipt=divergent_attributes,
        application_receipt=application,
    )[3] == outcome.receipt_ref

    forged_outcome = _OutcomeFixture(dict(outcome._body))
    forged_outcome.receipt_hash = "0" * 64
    with pytest.raises(ValueError, match="self-hash"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=learning,
            exposure_event=exposure_event,
            behavior_event=behavior_event,
            outcome_receipt=forged_outcome,
            application_receipt=application,
        )

    payload = learning.model_dump(mode="json", by_alias=True)
    payload.pop("learning_ref")
    payload.pop("learning_hash")
    payload["outcome_ref"] = "outcome:legacy"
    with pytest.raises(ValidationError, match="outcome, application receipt"):
        canon.build_signal_learning_receipt(**payload)

    unrelated_application = _rehash(
        canon.build_measurement_application_receipt,
        application,
        {"application_id": "measurement-application:unrelated"},
    )
    with pytest.raises(ValueError, match="exact one-target measurement application"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=learning,
            exposure_event=exposure_event,
            behavior_event=behavior_event,
            outcome_receipt=outcome,
            application_receipt=unrelated_application,
        )

    held_application = _rehash(
        canon.build_measurement_application_receipt,
        application,
        {
            "producer_verification_refs": (),
            "producer_resolution_state": _state(
                "hold",
                "gate0b_producer_resolution_required",
            ),
        },
    )
    held_application_learning = _rehash(
        canon.build_signal_learning_receipt,
        learning,
        {"receipt_ref": held_application.application_ref},
    )
    with pytest.raises(ValueError, match="exact one-target measurement application"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=held_application_learning,
            exposure_event=exposure_event,
            behavior_event=behavior_event,
            outcome_receipt=outcome,
            application_receipt=held_application,
        )

    held_exposure = _build_exposure()
    held_exposure_event = _event(held_exposure, event_id="event:held-exposure")
    held_behavior = _build_behavior(held_exposure, held_exposure_event)
    held_behavior_event = _event(
        held_exposure,
        behavior=held_behavior,
        event_id="event:held-behavior",
    )
    held_outcome = _outcome(held_exposure, held_behavior)
    held_application = _build_application(held_exposure, held_behavior, held_outcome)
    held_learning = _build_learning(
        held_exposure,
        held_behavior,
        held_outcome,
        held_application,
    )
    with pytest.raises(ValueError, match="Gate0B-verified"):
        canon.validate_context_behavior_learning_join(
            exposure=held_exposure,
            behavior=held_behavior,
            learning=held_learning,
            exposure_event=held_exposure_event,
            behavior_event=held_behavior_event,
            outcome_receipt=held_outcome,
            application_receipt=held_application,
        )


def test_held_legacy_learning_remains_readable_but_cannot_join_as_applied() -> None:
    held = canon.build_signal_learning_receipt(
        learning_id="learning:legacy",
        position_ref="position:legacy",
        estimate_ref="estimate:legacy",
        constellation_ref="constellation:legacy",
        exposure_ref="exposure:legacy",
        candidate_set_ref="candidate-set:legacy",
        selection_policy_ref="selection-policy:legacy",
        selection_propensity=canon.CanonicalDecimal(value="1", unit="probability"),
        action_ref="action:legacy",
        outcome_ref="outcome:legacy",
        effect={"claim": "legacy-held"},
        cost={"class": "legacy"},
        witness_refs=("witness:legacy",),
        receipt_ref="receipt:legacy",
        correction_refs=(),
        supersedes_refs=(),
        update_target_ref="learning-target:legacy",
        update_applied=False,
        state=_state("hold", "legacy_receipt_held"),
    )
    payload = held.model_dump(mode="json", by_alias=True)
    assert "behavior_ref" not in payload
    assert "measurement_basis_ref" not in payload
    assert "fitness_boundary_refs" not in payload
    assert canon.SignalLearningReceipt.model_validate(payload) == held


def test_event_order_frontier_and_validity_fail_closed() -> None:
    exposure = _build_exposure(producer_verified=True)
    exposure_event = _event(exposure)
    behavior = _build_behavior(exposure, exposure_event, producer_verified=True)
    behavior_event = _event(exposure, behavior=behavior, event_id="event:behavior")
    outcome = _outcome(exposure, behavior)
    application = _build_application(exposure, behavior, outcome)
    learning = _build_learning(exposure, behavior, outcome, application)

    early = behavior_event.model_copy(
        update={"occurred_at": exposure_event.occurred_at, "generation": 8}
    )
    with pytest.raises(ValueError, match="generation and time"):
        canon.validate_context_behavior_learning_join(
            exposure=exposure,
            behavior=behavior,
            learning=learning,
            exposure_event=exposure_event,
            behavior_event=early,
            outcome_receipt=outcome,
            application_receipt=application,
        )

    behavior_payload = behavior.model_dump(mode="json", by_alias=True)
    behavior_payload.pop("behavior_ref")
    behavior_payload.pop("behavior_hash")
    behavior_payload["valid_from"] = "2026-07-12T16:01:01Z"
    with pytest.raises(ValidationError, match="validity interval"):
        canon.build_capability_behavior_observation(**behavior_payload)


def test_gate0b_can_resolve_producers_without_forking_the_carrier() -> None:
    exposure = _build_exposure()
    verification_ref, _ = _address(
        "producer-verification-receipt",
        {"carrier": exposure.exposure_ref},
    )
    verified_exposure = _rehash(
        canon.build_context_exposure,
        exposure,
        {
            "producer_verification_refs": (verification_ref,),
            "producer_resolution_state": _state(),
        },
    )
    exposure_event = _event(verified_exposure, event_id="event:verified-exposure")
    behavior = _build_behavior(verified_exposure, exposure_event)
    behavior_verification_ref, _ = _address(
        "producer-verification-receipt",
        {"carrier": behavior.behavior_ref},
    )
    verified_behavior = _rehash(
        canon.build_capability_behavior_observation,
        behavior,
        {
            "producer_verification_refs": (behavior_verification_ref,),
            "producer_resolution_state": _state(),
        },
    )

    assert verified_exposure.producer_resolution_state == _state()
    assert verified_behavior.producer_resolution_state == _state()

    with pytest.raises(ValidationError, match="derive from exact verification refs"):
        _rehash(
            canon.build_context_exposure,
            exposure,
            {"producer_resolution_state": _state()},
        )


def test_correction_invalidates_old_learning_and_allows_current_successor() -> None:
    original_exposure = _build_exposure(producer_verified=True)
    original_exposure_event = _event(original_exposure)
    original_behavior = _build_behavior(
        original_exposure,
        original_exposure_event,
        producer_verified=True,
    )
    original_outcome = _outcome(original_exposure, original_behavior)
    original_application = _build_application(
        original_exposure,
        original_behavior,
        original_outcome,
    )
    original_learning = _build_learning(
        original_exposure,
        original_behavior,
        original_outcome,
        original_application,
    )

    current_exposure = _build_exposure(
        correction_refs=(original_exposure.exposure_ref,),
        producer_verified=True,
        observed_at="2026-07-12T16:00:42Z",
    )
    current_exposure_event = _event(current_exposure, event_id="event:current-exposure")
    current_behavior = _build_behavior(
        current_exposure,
        current_exposure_event,
        correction_refs=(original_behavior.behavior_ref,),
        producer_verified=True,
        observed_at="2026-07-12T16:01:01Z",
    )
    current_behavior_event = _event(
        current_exposure,
        behavior=current_behavior,
        event_id="event:current-behavior",
    )
    current_outcome = _outcome(current_exposure, current_behavior)
    current_application = _build_application(
        current_exposure,
        current_behavior,
        current_outcome,
        applied_at="2026-07-12T16:01:13Z",
        correction_refs=(original_application.application_ref,),
    )
    current_learning = _build_learning(
        current_exposure,
        current_behavior,
        current_outcome,
        current_application,
        correction_refs=(original_learning.learning_ref,),
        recorded_at="2026-07-12T16:01:14Z",
    )
    invalidation = canon.derive_invalidated_observability_refs(
        exposures=(original_exposure, current_exposure),
        behaviors=(original_behavior, current_behavior),
        learning_receipts=(original_learning, current_learning),
        application_receipts=(original_application, current_application),
        consumer_registry_complete=True,
    )
    invalidated = invalidation.invalidated_refs

    assert original_exposure.exposure_ref in invalidated
    assert original_behavior.behavior_ref in invalidated
    assert original_learning.learning_ref in invalidated
    assert original_application.application_ref in invalidated
    assert current_exposure.exposure_ref not in invalidated
    assert current_behavior.behavior_ref not in invalidated
    assert current_learning.learning_ref not in invalidated
    assert current_application.application_ref not in invalidated
    assert invalidation.fanout_state == _state()

    assert canon.validate_context_behavior_learning_join(
        exposure=current_exposure,
        behavior=current_behavior,
        learning=current_learning,
        exposure_event=current_exposure_event,
        behavior_event=current_behavior_event,
        outcome_receipt=current_outcome,
        application_receipt=current_application,
        invalidated_refs=invalidated,
    )[2] == current_learning.learning_ref

    with pytest.raises(ValueError, match="invalidated"):
        canon.validate_context_behavior_learning_join(
            exposure=original_exposure,
            behavior=original_behavior,
            learning=original_learning,
            exposure_event=original_exposure_event,
            behavior_event=_event(
                original_exposure,
                behavior=original_behavior,
                event_id="event:original-behavior",
            ),
            outcome_receipt=original_outcome,
            application_receipt=original_application,
            invalidated_refs=invalidated,
        )

    outcome_hold = canon.derive_invalidated_observability_refs(
        exposures=(original_exposure, current_exposure),
        behaviors=(original_behavior, current_behavior),
        learning_receipts=(original_learning, current_learning),
        application_receipts=(original_application, current_application),
        outcome_correction_refs=(original_outcome.receipt_ref,),
        consumer_registry_complete=True,
    )
    assert outcome_hold.fanout_state == _state(
        "hold",
        "gate0b_outcome_correction_fanout_required",
    )

    unknown_consumer_ref, _ = _address(
        "material-consumer",
        {"consumer": "unregistered"},
    )
    consumer_hold = canon.derive_invalidated_observability_refs(
        unregistered_consumer_refs=(unknown_consumer_ref,),
    )
    assert consumer_hold.fanout_state == _state(
        "hold",
        "gate0b_unregistered_consumer_fanout_required",
    )
    with pytest.raises(ValidationError, match="fanout_state must derive"):
        canon.ObservabilityInvalidationResult.model_validate(
            {
                "invalidated_refs": (),
                "unregistered_consumer_refs": (),
                "outcome_correction_refs": (),
                "consumer_registry_complete": False,
                "fanout_state": _state(),
                "no_effect": True,
                "may_authorize": False,
            }
        )

    wrong_key_application = _rehash(
        canon.build_measurement_application_receipt,
        current_application,
        {"application_id": "measurement-application:different-logical-target"},
    )
    with pytest.raises(ValueError, match="preserve the carrier natural key"):
        canon.derive_invalidated_observability_refs(
            application_receipts=(original_application, wrong_key_application),
            consumer_registry_complete=True,
        )

    wrong_key_learning = _rehash(
        canon.build_signal_learning_receipt,
        current_learning,
        {"learning_id": "learning:different-logical-update"},
    )
    with pytest.raises(ValueError, match="preserve the carrier natural key"):
        canon.derive_invalidated_observability_refs(
            learning_receipts=(original_learning, wrong_key_learning),
            consumer_registry_complete=True,
        )

    wrong_audience_exposure = _build_exposure(
        audience="public_or_air",
        correction_refs=(original_exposure.exposure_ref,),
        producer_verified=True,
        observed_at="2026-07-12T16:00:42Z",
    )
    with pytest.raises(ValueError, match="preserve the carrier natural key"):
        canon.derive_invalidated_observability_refs(
            exposures=(original_exposure, wrong_audience_exposure),
            consumer_registry_complete=True,
        )


def test_observability_is_not_context_authority_or_a_fourth_reins_audience() -> None:
    schema = json.loads(canon.carrier_json_schema_bytes())
    behavior_properties = schema["$defs"]["CapabilityBehaviorObservation"]["properties"]
    component_properties = schema["$defs"]["ContextExposureComponent"]["properties"]
    frame_fields = set(canon.ContextFrame.model_fields)

    assert not {"context_exposure", "capability_behavior", "behavior_metrics"} & frame_fields
    assert "private_body" not in component_properties
    assert "raw_body" not in component_properties
    assert "aggregate_score" not in behavior_properties
    assert "observed_label" not in schema["$defs"]["CapabilityBehaviorDatum"]["properties"]
    assert "source_local_only" in behavior_properties
    assert "required_basis_dimension_refs" in behavior_properties
    assert "dark_basis_dimension_refs" in behavior_properties
    assert set(canon.TriAudienceProjectionRefs.model_fields) == {
        "operator_private",
        "yard_context",
        "hapax_substrate",
    }
