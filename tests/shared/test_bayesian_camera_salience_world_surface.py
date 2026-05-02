"""Tests for the Bayesian camera salience WCS broker contract."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from pydantic import ValidationError

from shared.bayesian_camera_salience_world_surface import (
    FAIL_CLOSED_POLICY,
    REQUIRED_APERTURE_KINDS,
    REQUIRED_CONSUMERS,
    REQUIRED_EVIDENCE_CLASSES,
    CameraObservationEnvelope,
    CameraSalienceBroker,
    CameraSalienceQuery,
    ClaimAuthorityCeiling,
    EvidenceClass,
    ImageAttachmentMode,
    ObservationAperture,
    ProducerKind,
    adapt_cross_camera_tracklet,
    adapt_ir_presence_observation,
    adapt_vision_backend_observation,
    load_camera_salience_fixtures,
)


def _fixtures():
    return load_camera_salience_fixtures()


def _query(*evidence_classes: EvidenceClass) -> CameraSalienceQuery:
    base = _fixtures().query_by_id("camera-salience-query:director.public-summary")
    if not evidence_classes:
        return base
    return base.model_copy(update={"evidence_classes": evidence_classes})


def _observation(evidence_class: EvidenceClass) -> CameraObservationEnvelope:
    return next(
        observation
        for observation in _fixtures().observations
        if observation.evidence_class is evidence_class
    )


def _aperture(aperture_id: str) -> ObservationAperture:
    return next(
        aperture for aperture in _fixtures().apertures if aperture.aperture_id == aperture_id
    )


def _posterior(bundle, hypothesis: str):
    return next(row for row in bundle.posterior_summary if row.hypothesis == hypothesis)


def test_fixture_loader_covers_apertures_evidence_consumers_and_fail_closed_policy() -> None:
    fixtures = _fixtures()

    assert {kind.value for kind in fixtures.required_aperture_kinds} == REQUIRED_APERTURE_KINDS
    assert {klass.value for klass in fixtures.required_evidence_classes} == (
        REQUIRED_EVIDENCE_CLASSES
    )
    assert {consumer.value for consumer in fixtures.required_consumers} == REQUIRED_CONSUMERS
    assert {aperture.kind.value for aperture in fixtures.apertures} >= REQUIRED_APERTURE_KINDS
    assert {observation.evidence_class.value for observation in fixtures.observations} >= (
        REQUIRED_EVIDENCE_CLASSES
    )
    assert fixtures.fail_closed_policy == FAIL_CLOSED_POLICY


def test_broker_returns_ranked_posteriors_evidence_refs_and_public_safe_image_policy() -> None:
    bundle = (
        _fixtures()
        .broker()
        .evaluate(
            _query(),
            generated_at="2026-05-02T14:01:00Z",
        )
    )

    assert bundle.ranked_observations
    assert bundle.evidence_refs
    assert bundle.public_claim_ceiling in {
        ClaimAuthorityCeiling.PUBLIC_GATE_REQUIRED,
        ClaimAuthorityCeiling.NO_CLAIM,
    }
    assert bundle.image_attachment_policy.mode is ImageAttachmentMode.OMIT
    assert "public_claim_queries_receive_refs_not_images" in (
        bundle.image_attachment_policy.blocked_reasons
    )
    assert all(
        row.value_of_information.selected and row.value_of_information.expected_value > 0
        for row in bundle.ranked_observations
    )


def test_existing_vision_backend_outputs_are_adapted_without_second_classifier() -> None:
    aperture = _aperture("aperture:studio-rgb.brio-operator")

    envelope = adapt_vision_backend_observation(
        aperture=aperture,
        envelope_id="camera-observation:adapter.vision.frame",
        evidence_class=EvidenceClass.FRAME,
        observed_at="2026-05-02T14:02:00Z",
        semantic_labels=("operator_at_desk",),
        confidence=0.8,
        evidence_ref="camera-evidence:adapter.vision.operator-attention",
        hypothesis="operator_attention_desk",
        likelihood=0.78,
        span_ref="span:adapter:vision:frame",
        witness_ref="witness:adapter:vision",
        source_ref="vision-backend:camera-classifications:brio-operator",
        observed_age_s=1,
    )

    assert envelope.producer is ProducerKind.VISION_BACKEND
    assert envelope.classification_public_claim_allowed is False
    assert "VisionBackend" in aperture.producer_refs[0]

    payload = envelope.model_dump(mode="json")
    payload["producer"] = "parallel_vision_stack"
    with pytest.raises(ValidationError, match="parallel vision stack"):
        CameraObservationEnvelope.model_validate(payload)


def test_cross_camera_tracklets_expose_topology_delta_similarity_and_uncertainty() -> None:
    aperture = _aperture("aperture:studio-rgb.brio-operator")
    envelope = adapt_cross_camera_tracklet(
        aperture=aperture,
        envelope_id="camera-observation:adapter.cross-camera.tracklet",
        observed_at="2026-05-02T14:02:10Z",
        evidence_ref="camera-evidence:adapter.cross-camera.tracklet",
        hypothesis="operator_present",
        confidence=0.77,
        span_ref="span:adapter:cross-camera:tracklet",
        witness_ref="witness:adapter:cross-camera",
        source_ref="cross-camera:merge-suggestion:operator",
        topology_path="brio-operator>c920-desk",
        time_delta_s=2.8,
        similarity=0.77,
        uncertainty=0.23,
        observed_age_s=1,
    )
    metadata = envelope.evidence_rows[0].metadata

    assert metadata["topology_path"] == "brio-operator>c920-desk"
    assert metadata["time_delta_s"] == 2.8
    assert metadata["similarity"] == 0.77
    assert metadata["uncertainty"] == 0.23


def test_ir_evidence_participates_in_same_posterior_model_as_rgb() -> None:
    ir_aperture = _aperture("aperture:studio-ir.noir-desk")
    envelope = adapt_ir_presence_observation(
        aperture=ir_aperture,
        envelope_id="camera-observation:adapter.ir.hands",
        observed_at="2026-05-02T14:02:20Z",
        confidence=0.86,
        evidence_ref="camera-evidence:adapter.ir.hands",
        hypothesis="hands_on_instrument_or_controller",
        likelihood=0.84,
        span_ref="span:adapter:ir:hands",
        witness_ref="witness:adapter:ir",
        source_ref="ir-presence:desk-hand-zone",
        observed_age_s=1,
    )
    bundle = CameraSalienceBroker((ir_aperture,), (envelope,)).evaluate(
        _query(EvidenceClass.IR_PRESENCE),
        generated_at="2026-05-02T14:02:30Z",
    )

    posterior = _posterior(bundle, "hands_on_instrument_or_controller")
    assert posterior.supporting_evidence_refs == ("camera-evidence:adapter.ir.hands",)
    assert bundle.ranked_observations[0].evidence_class is EvidenceClass.IR_PRESENCE


def test_stale_observations_are_reported_but_do_not_affect_current_salience() -> None:
    payload = _observation(EvidenceClass.FRAME).model_dump(mode="json")
    payload["observation_state"] = "stale"
    cast("dict[str, Any]", payload["freshness"])["state"] = "stale"
    payload["blocked_reasons"] = ["stale_evidence"]
    payload["stale_refs"] = ["stale-ref:brio-operator-frame"]

    stale = CameraObservationEnvelope.model_validate(payload)
    broker = CameraSalienceBroker((_aperture("aperture:studio-rgb.brio-operator"),), (stale,))
    bundle = broker.evaluate(
        _query(EvidenceClass.FRAME),
        generated_at="2026-05-02T14:03:00Z",
    )

    assert bundle.ranked_observations == ()
    assert bundle.posterior_summary == ()
    assert "stale-ref:brio-operator-frame" in bundle.blocked_or_stale_refs
    assert bundle.public_claim_ceiling is ClaimAuthorityCeiling.NO_CLAIM


def test_unknown_evidence_is_uncertainty_not_absence_or_public_claim() -> None:
    payload = _observation(EvidenceClass.FRAME).model_dump(mode="json")
    payload["observation_state"] = "unknown"
    cast("dict[str, Any]", payload["freshness"])["state"] = "unknown"
    payload["blocked_reasons"] = ["unknown_evidence"]

    unknown = CameraObservationEnvelope.model_validate(payload)
    broker = CameraSalienceBroker((_aperture("aperture:studio-rgb.brio-operator"),), (unknown,))
    bundle = broker.evaluate(
        _query(EvidenceClass.FRAME),
        generated_at="2026-05-02T14:03:10Z",
    )

    assert bundle.ranked_observations == ()
    assert bundle.uncertainty == 1.0
    assert any("unknown_evidence" in ref for ref in bundle.blocked_or_stale_refs)
    assert bundle.public_claim_policy.public_truth_allowed is False


def test_low_confidence_and_low_voi_cases_return_no_op() -> None:
    low_confidence = deepcopy(_observation(EvidenceClass.FRAME).model_dump(mode="json"))
    low_confidence["confidence"] = 0.08
    low_confidence["evidence_rows"][0]["confidence"] = 0.08
    low = CameraObservationEnvelope.model_validate(low_confidence)

    bundle = CameraSalienceBroker(
        (_aperture("aperture:studio-rgb.brio-operator"),), (low,)
    ).evaluate(
        _query(EvidenceClass.FRAME),
        generated_at="2026-05-02T14:03:20Z",
    )
    assert bundle.ranked_observations == ()
    assert "camera-evidence:frame.brio-operator.operator-attention:low_confidence" in (
        bundle.blocked_or_stale_refs
    )

    costly_query = _query(EvidenceClass.ARCHIVE_WINDOW).model_copy(
        update={"min_expected_value": 0.80, "time_budget_ms": 50}
    )
    costly_bundle = (
        _fixtures()
        .broker()
        .evaluate(
            costly_query,
            generated_at="2026-05-02T14:03:30Z",
        )
    )
    assert costly_bundle.ranked_observations == ()
    assert costly_bundle.recommended_next_probe == "no_op:expected_value_below_cost"


def test_ir_rgb_disagreement_yields_uncertainty_rather_than_false_absence() -> None:
    ir = _observation(EvidenceClass.IR_PRESENCE)
    negative_payload = _observation(EvidenceClass.FRAME).model_dump(mode="json")
    negative_payload["observation_state"] = "negative"
    negative_payload["negative_evidence_refs"] = ["negative:rgb:hand-zone-not-visible"]
    negative_payload["evidence_rows"][0]["hypothesis"] = "hands_on_instrument_or_controller"
    negative_payload["evidence_rows"][0]["likelihood"] = 0.75
    negative_payload["evidence_rows"][0]["supports_hypothesis"] = False
    negative_payload["evidence_rows"][0]["observation_state"] = "negative"
    negative_payload["evidence_rows"][0]["evidence_ref"] = "camera-evidence:rgb.negative.hands"

    negative_rgb = CameraObservationEnvelope.model_validate(negative_payload)
    broker = CameraSalienceBroker(
        (
            _aperture("aperture:studio-rgb.brio-operator"),
            _aperture("aperture:studio-ir.noir-desk"),
        ),
        (ir, negative_rgb),
    )
    bundle = broker.evaluate(
        _query(EvidenceClass.IR_PRESENCE, EvidenceClass.FRAME),
        generated_at="2026-05-02T14:03:40Z",
    )
    posterior = _posterior(bundle, "hands_on_instrument_or_controller")

    assert posterior.supporting_evidence_refs
    assert posterior.contradicting_evidence_refs == ("camera-evidence:rgb.negative.hands",)
    assert posterior.uncertainty >= 0.55
    assert posterior.posterior > 0.35


def test_livestream_composed_frame_is_compared_with_physical_studio_evidence() -> None:
    bundle = (
        _fixtures()
        .broker()
        .evaluate(
            _query(EvidenceClass.FRAME, EvidenceClass.COMPOSED_LIVESTREAM),
            generated_at="2026-05-02T14:03:50Z",
        )
    )

    mismatch = _posterior(bundle, "livestream_viewer_visible_mismatch")
    assert mismatch.supporting_evidence_refs == (
        "camera-evidence:livestream.composed.viewer-mismatch",
    )
    projection = bundle.to_director_world_surface_projection()
    assert projection["public_truth_allowed"] is False
    assert any(
        row["hypothesis"] == "livestream_viewer_visible_mismatch" for row in projection["ranked"]
    )


def test_public_claim_false_prevention_for_labels_captions_titles_and_director_success() -> None:
    bundle = (
        _fixtures()
        .broker()
        .evaluate(
            _query(),
            generated_at="2026-05-02T14:04:00Z",
        )
    )
    policy = bundle.public_claim_policy
    payload = bundle.to_wcs_projection_payload()

    assert policy.public_truth_allowed is False
    assert policy.public_clip_label_allowed is False
    assert policy.public_caption_allowed is False
    assert policy.public_title_allowed is False
    assert policy.director_success_allowed is False
    assert payload["claim_authorizations"] == {
        "public_truth": False,
        "public_clip_label": False,
        "public_caption": False,
        "public_title": False,
        "director_success": False,
    }
    assert "classification_alone_cannot_authorize_public_truth" in policy.blocked_reasons
