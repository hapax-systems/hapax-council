"""Tests for multimodal environmental evidence envelopes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.multimodal_environmental_evidence_envelope import (
    FAIL_CLOSED_POLICY,
    MULTIMODAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS,
    REQUIRED_FIXTURE_CASES,
    REQUIRED_SOURCE_CLASSES,
    ClaimShape,
    ClaimSupportStatus,
    MultimodalClaimSupportRequest,
    MultimodalEnvironmentalEvidenceEnvelope,
    MultimodalEnvironmentalEvidenceError,
    evaluate_multimodal_claim_support,
    load_multimodal_environmental_evidence_fixtures,
)
from shared.perceptual_field_grounding_registry import default_registry


def _envelope(envelope_id: str) -> MultimodalEnvironmentalEvidenceEnvelope:
    return load_multimodal_environmental_evidence_fixtures().envelopes_by_id()[envelope_id]


def _request(
    claim_shape: ClaimShape,
    *,
    claim_id: str = "claim:test.current",
    public_or_director: bool = True,
    includes_age_window_language: bool = False,
) -> MultimodalClaimSupportRequest:
    return MultimodalClaimSupportRequest(
        claim_id=claim_id,
        claim_name="test claim",
        claim_shape=claim_shape,
        public_or_director=public_or_director,
        now="2026-05-11T09:00:02Z",
        includes_age_window_language=includes_age_window_language,
    )


def test_loader_covers_required_source_classes_fixture_cases_fields_and_policy() -> None:
    fixtures = load_multimodal_environmental_evidence_fixtures()

    assert {source_class.value for source_class in fixtures.required_source_classes} == (
        REQUIRED_SOURCE_CLASSES
    )
    assert set(fixtures.required_fixture_cases) == REQUIRED_FIXTURE_CASES
    assert set(fixtures.evidence_envelope_required_fields) == set(
        MULTIMODAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS
    )
    assert fixtures.fail_closed_policy == FAIL_CLOSED_POLICY
    assert {row.source_class.value for row in fixtures.envelopes} >= REQUIRED_SOURCE_CLASSES
    assert {row.fixture_case for row in fixtures.envelopes} >= REQUIRED_FIXTURE_CASES


def test_required_fields_include_acceptance_contract_axes() -> None:
    required = set(MULTIMODAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS)
    acceptance_fields = {
        "source_family",
        "source_class",
        "observed_at",
        "valid_until",
        "raw_refs",
        "transform_chain",
        "aperture_id",
        "camera_role",
        "confidence",
        "uncertainty",
        "privacy_state",
        "rights_state",
        "witness_kind",
        "claim_authority_ceiling",
    }

    assert acceptance_fields <= required


def test_fixture_claim_support_examples_match_model_decisions() -> None:
    fixtures = load_multimodal_environmental_evidence_fixtures()

    for row in fixtures.claim_support_fixtures:
        envelope = fixtures.envelopes_by_id()[row.envelope_ref]
        assert evaluate_multimodal_claim_support(envelope, row.request) == row.expected


@pytest.mark.parametrize(
    ("envelope_id", "expected_status"),
    [
        ("multimodal-evidence:raw-camera.brio.stale", ClaimSupportStatus.BLOCKED_STALE_OR_EXPIRED),
        (
            "multimodal-evidence:raw-camera.overhead.missing",
            ClaimSupportStatus.BLOCKED_MISSING_OR_BLANK,
        ),
        (
            "multimodal-evidence:livestream.composed.blank",
            ClaimSupportStatus.BLOCKED_MISSING_OR_BLANK,
        ),
        (
            "multimodal-evidence:camera-ir.contradictory",
            ClaimSupportStatus.BLOCKED_CONTRADICTORY,
        ),
    ],
)
def test_stale_missing_blank_and_contradictory_evidence_do_not_ground_current_claims(
    envelope_id: str,
    expected_status: ClaimSupportStatus,
) -> None:
    decision = evaluate_multimodal_claim_support(
        _envelope(envelope_id),
        _request(ClaimShape.PRESENT_CURRENT),
    )

    assert not decision.allowed
    assert decision.status is expected_status
    assert decision.rendered_claim_mode == "none"


def test_fresh_raw_camera_can_ground_private_current_but_not_public_live_claim() -> None:
    envelope = _envelope("multimodal-evidence:raw-camera.brio.fresh")

    private_current = evaluate_multimodal_claim_support(
        envelope,
        _request(
            ClaimShape.PRESENT_CURRENT,
            claim_id="claim:camera.private-current",
            public_or_director=False,
        ),
    )
    public_live = evaluate_multimodal_claim_support(
        envelope,
        _request(ClaimShape.PUBLIC_LIVE, claim_id="claim:camera.public-live"),
    )

    assert private_current.allowed
    assert private_current.rendered_claim_mode == "present_current"
    assert not public_live.allowed
    assert public_live.status is ClaimSupportStatus.BLOCKED_PUBLIC_GATE
    assert "authority_private_evidence_bound" in public_live.reason_codes
    assert "public_event_refs_missing" in public_live.reason_codes


def test_undertrained_ir_no_detection_is_neutral_not_negative_absence() -> None:
    envelope = _envelope("multimodal-evidence:ir.desk.no-detection-undertrained")

    decision = evaluate_multimodal_claim_support(
        envelope,
        _request(
            ClaimShape.ABSENCE,
            claim_id="claim:ir.undertrained-absence",
            public_or_director=False,
        ),
    )

    assert envelope.observation_polarity == "neutral"
    assert not decision.allowed
    assert decision.status is ClaimSupportStatus.BLOCKED_NEUTRAL_IR_NO_DETECTION

    payload = envelope.model_dump(mode="json")
    payload["observation_polarity"] = "negative"
    with pytest.raises(ValueError, match="undertrained IR no-detection"):
        MultimodalEnvironmentalEvidenceEnvelope.model_validate(payload)


def test_scene_classifier_fallback_zero_confidence_cannot_ground_claims() -> None:
    envelope = _envelope("multimodal-evidence:classifier.scene.fallback-zero")

    decision = evaluate_multimodal_claim_support(
        envelope,
        _request(ClaimShape.PRESENT_CURRENT, claim_id="claim:classifier.fallback-current"),
    )

    assert envelope.scene_classifier_fallback is True
    assert envelope.confidence == 0.0
    assert not decision.allowed
    assert decision.status is ClaimSupportStatus.BLOCKED_CLASSIFIER_FALLBACK

    payload = envelope.model_dump(mode="json")
    payload["claim_authority_ceiling"] = "public_gate_required"
    payload["privacy_state"] = "public_safe"
    payload["rights_state"] = "public_clear"
    payload["public_event_refs"] = ["public-event:bad"]
    with pytest.raises(ValueError, match="zero-confidence classifier fallback"):
        MultimodalEnvironmentalEvidenceEnvelope.model_validate(payload)


def test_synthetic_and_render_state_sources_remain_diagnostic_or_render_only() -> None:
    synthetic = _envelope("multimodal-evidence:synthetic.audit.marker")
    homage = _envelope("multimodal-evidence:homage.render.state")
    ward = _envelope("multimodal-evidence:ward.decorative.render-state")

    synthetic_public = evaluate_multimodal_claim_support(
        synthetic,
        _request(ClaimShape.PUBLIC_LIVE, claim_id="claim:synthetic.public"),
    )
    homage_fact = evaluate_multimodal_claim_support(
        homage,
        _request(
            ClaimShape.PRESENT_CURRENT,
            claim_id="claim:homage.factual",
            public_or_director=False,
        ),
    )
    homage_render = evaluate_multimodal_claim_support(
        homage,
        _request(
            ClaimShape.RENDER_STATE,
            claim_id="claim:homage.render",
            public_or_director=False,
        ),
    )
    ward_public = evaluate_multimodal_claim_support(
        ward,
        _request(ClaimShape.PUBLIC_LIVE, claim_id="claim:ward.public"),
    )

    assert not synthetic_public.allowed
    assert synthetic_public.status is ClaimSupportStatus.BLOCKED_SYNTHETIC_ONLY
    assert not homage_fact.allowed
    assert homage_fact.status is ClaimSupportStatus.BLOCKED_RENDER_STATE_NOT_FACTUAL
    assert homage_render.allowed
    assert homage_render.rendered_claim_mode == "render_state_only"
    assert not ward_public.allowed
    assert ward_public.status is ClaimSupportStatus.BLOCKED_RENDER_STATE_NOT_FACTUAL


def test_archive_only_and_public_reembed_have_bounded_public_language() -> None:
    archive = _envelope("multimodal-evidence:archive.replay.window")
    public_reembed = _envelope("multimodal-evidence:public.reembed.clip")

    archive_live = evaluate_multimodal_claim_support(
        archive,
        _request(ClaimShape.PUBLIC_LIVE, claim_id="claim:archive.live"),
    )
    archive_last_observed = evaluate_multimodal_claim_support(
        archive,
        _request(
            ClaimShape.LAST_OBSERVED,
            claim_id="claim:archive.last",
            includes_age_window_language=True,
        ),
    )
    reembed_live = evaluate_multimodal_claim_support(
        public_reembed,
        _request(ClaimShape.PUBLIC_LIVE, claim_id="claim:reembed.live"),
    )
    reembed_refs = evaluate_multimodal_claim_support(
        public_reembed,
        _request(ClaimShape.PUBLIC_REEMBED, claim_id="claim:reembed.refs"),
    )

    assert not archive_live.allowed
    assert archive_live.status is ClaimSupportStatus.BLOCKED_ARCHIVE_NOT_LIVE
    assert archive_last_observed.allowed
    assert set(archive_last_observed.required_language) == {"last_observed", "age_s", "valid_until"}
    assert not reembed_live.allowed
    assert reembed_live.status is ClaimSupportStatus.BLOCKED_PUBLIC_REEMBED_NOT_LIVE_SCENE
    assert reembed_refs.allowed
    assert reembed_refs.rendered_claim_mode == "public_reembed_refs_only"


def test_perceptual_field_keys_map_to_registry_rows_before_claim_use() -> None:
    registry = default_registry()
    by_path = registry.by_key_path()
    fixtures = load_multimodal_environmental_evidence_fixtures()
    keys = {row.perceptual_field_key for row in fixtures.envelopes if row.perceptual_field_key}

    assert keys <= set(by_path)
    assert by_path["camera.classifications"].public_safe() is False
    assert "public-broadcast" not in by_path["camera.classifications"].allowed_consumers
    assert by_path["homage.active_artefact"].prompt_rendering == "render-with-age-and-window"
    assert by_path["stream.egress"].public_safe()


def test_fixture_set_policy_mismatch_fails_closed(tmp_path: Path) -> None:
    fixtures = load_multimodal_environmental_evidence_fixtures()
    payload = fixtures.model_dump(mode="json")
    payload["fail_closed_policy"]["raw_camera_implies_public_claim"] = True

    path = tmp_path / "bad-multimodal-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MultimodalEnvironmentalEvidenceError, match="fail_closed_policy"):
        load_multimodal_environmental_evidence_fixtures(path)
