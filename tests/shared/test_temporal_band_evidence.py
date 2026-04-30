"""Tests for temporal band evidence envelope fixtures and claim gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.temporal_band_evidence import (
    FAIL_CLOSED_POLICY,
    REQUIRED_SHM_FIXTURE_CASES,
    REQUIRED_TEMPORAL_BANDS,
    TEMPORAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS,
    TemporalBandEvidenceError,
    TemporalClaimSupportRequest,
    TemporalEvidenceEnvelope,
    evaluate_temporal_claim_support,
    load_temporal_band_evidence_fixtures,
)


def _envelope(envelope_id: str) -> TemporalEvidenceEnvelope:
    return load_temporal_band_evidence_fixtures().envelopes_by_id()[envelope_id]


def test_loader_covers_temporal_bands_shm_cases_fields_and_policy() -> None:
    fixtures = load_temporal_band_evidence_fixtures()

    assert set(fixtures.temporal_bands) == REQUIRED_TEMPORAL_BANDS
    assert set(fixtures.shm_fixture_cases) == REQUIRED_SHM_FIXTURE_CASES
    assert set(fixtures.evidence_envelope_required_fields) == set(
        TEMPORAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS
    )
    assert fixtures.fail_closed_policy == FAIL_CLOSED_POLICY
    assert {row.fixture_case for row in fixtures.shm_payload_fixtures} == (
        REQUIRED_SHM_FIXTURE_CASES
    )
    assert {envelope.temporal_band for envelope in fixtures.envelopes} >= REQUIRED_TEMPORAL_BANDS


def test_raw_xml_alone_cannot_satisfy_public_or_director_claim() -> None:
    envelope = _envelope("temporal-evidence:raw-xml.prompt-only")

    decision = evaluate_temporal_claim_support(
        envelope,
        TemporalClaimSupportRequest(
            claim_id="claim:temporal.xml.current-scene",
            claim_name="raw XML says current scene",
            claim_shape="public_live",
            public_or_director=True,
            now_wall="2026-04-30T03:40:02Z",
        ),
    )

    assert decision.allowed is False
    assert decision.status == "blocked_raw_xml_only"
    assert decision.rendered_claim_mode == "none"
    assert decision.reason_codes == ("raw_xml_without_witness_or_span_refs",)


def test_protention_cannot_satisfy_current_but_can_render_anticipatory_language() -> None:
    envelope = _envelope("temporal-evidence:protention.audio-readiness.expected")

    current = evaluate_temporal_claim_support(
        envelope,
        TemporalClaimSupportRequest(
            claim_id="claim:audio.route.current-from-protention",
            claim_name="audio route is live now from protention",
            claim_shape="present_current",
            public_or_director=True,
            now_wall="2026-04-30T03:40:02Z",
        ),
    )
    anticipatory = evaluate_temporal_claim_support(
        envelope,
        TemporalClaimSupportRequest(
            claim_id="claim:audio.route.anticipated",
            claim_name="audio route may be ready soon",
            claim_shape="anticipatory",
            public_or_director=False,
            now_wall="2026-04-30T03:40:02Z",
        ),
    )

    assert current.allowed is False
    assert current.status == "blocked_protention_current_claim"
    assert anticipatory.allowed is True
    assert anticipatory.status == "allowed_anticipatory_only"
    assert anticipatory.rendered_claim_mode == "anticipatory"
    assert set(anticipatory.required_language) == {
        "anticipatory",
        "expected_in_s",
        "must_verify_by",
    }


def test_stale_retention_requires_last_observed_age_and_window_language() -> None:
    envelope = _envelope("temporal-evidence:retention.camera-scene.stale")

    current = evaluate_temporal_claim_support(
        envelope,
        TemporalClaimSupportRequest(
            claim_id="claim:camera.scene.current-from-retention",
            claim_name="camera scene is current from retention",
            claim_shape="present_current",
            public_or_director=True,
            now_wall="2026-04-30T03:40:02Z",
        ),
    )
    no_age = evaluate_temporal_claim_support(
        envelope,
        TemporalClaimSupportRequest(
            claim_id="claim:camera.scene.last-observed-no-age",
            claim_name="camera scene was last observed",
            claim_shape="last_observed",
            public_or_director=True,
            now_wall="2026-04-30T03:40:02Z",
            includes_age_window_language=False,
        ),
    )
    with_age = evaluate_temporal_claim_support(
        envelope,
        TemporalClaimSupportRequest(
            claim_id="claim:camera.scene.last-observed-with-age",
            claim_name="camera scene was last observed",
            claim_shape="last_observed",
            public_or_director=True,
            now_wall="2026-04-30T03:40:02Z",
            includes_age_window_language=True,
        ),
    )

    assert current.allowed is False
    assert current.reason_codes == ("retention_cannot_ground_current_claim",)
    assert no_age.allowed is False
    assert no_age.status == "blocked_stale_retention_requires_age_window"
    assert with_age.allowed is True
    assert with_age.status == "allowed_last_observed_only"
    assert with_age.rendered_claim_mode == "last_observed_with_age_window"
    assert set(with_age.required_language) == {"last_observed", "age_s", "sample_window_s"}


def test_producer_failures_are_missing_data_not_positive_world_state() -> None:
    fixtures = load_temporal_band_evidence_fixtures()
    failure_refs = [
        "temporal-evidence:producer.missing",
        "temporal-evidence:producer.malformed",
        "temporal-evidence:producer.empty",
    ]

    for ref in failure_refs:
        envelope = fixtures.envelopes_by_id()[ref]
        decision = evaluate_temporal_claim_support(
            envelope,
            TemporalClaimSupportRequest(
                claim_id=f"claim:{ref.removeprefix('temporal-evidence:').replace('.', '-')}",
                claim_name="temporal bands are current despite producer failure",
                claim_shape="present_current",
                public_or_director=False,
                now_wall="2026-04-30T03:40:02Z",
            ),
        )

        assert envelope.evidence_role == "producer_failure"
        assert envelope.authority_ceiling == "no_claim"
        assert envelope.missing_data_reason
        assert envelope.witness_refs == ()
        assert envelope.span_refs == ()
        assert decision.allowed is False
        assert decision.status == "blocked_producer_failure"
        assert decision.reason_codes == ("producer_failure_is_missing_data",)


def test_expired_above_floor_posterior_cannot_satisfy_current_claim() -> None:
    envelope = _envelope("temporal-evidence:impression.expired.high-posterior")

    decision = evaluate_temporal_claim_support(
        envelope,
        TemporalClaimSupportRequest(
            claim_id="claim:camera.scene.current-expired-posterior",
            claim_name="camera scene is current despite expired posterior",
            claim_shape="present_current",
            public_or_director=True,
            now_wall="2026-04-30T03:40:02Z",
        ),
    )

    assert envelope.posterior == pytest.approx(0.97)
    assert decision.allowed is False
    assert decision.status == "blocked_expired_or_stale_current_claim"
    assert decision.reason_codes == ("freshness_expired", "validity_window_expired")


def test_surprise_can_render_mismatch_but_not_predicted_state_as_current() -> None:
    envelope = _envelope("temporal-evidence:surprise.camera-scene.mismatch")

    mismatch = evaluate_temporal_claim_support(
        envelope,
        TemporalClaimSupportRequest(
            claim_id="claim:camera.scene.mismatch",
            claim_name="camera scene mismatch detected",
            claim_shape="surprise_change",
            public_or_director=True,
            now_wall="2026-04-30T03:40:02Z",
        ),
    )
    current = evaluate_temporal_claim_support(
        envelope,
        TemporalClaimSupportRequest(
            claim_id="claim:camera.scene.current-from-surprise",
            claim_name="camera scene is current from surprise",
            claim_shape="present_current",
            public_or_director=True,
            now_wall="2026-04-30T03:40:02Z",
        ),
    )

    assert mismatch.allowed is True
    assert mismatch.rendered_claim_mode == "surprise_mismatch"
    assert current.allowed is False
    assert current.status == "blocked_temporal_band_mismatch"


def test_fixture_claim_support_examples_match_model_decisions() -> None:
    fixtures = load_temporal_band_evidence_fixtures()

    for row in fixtures.claim_support_fixtures:
        envelope = fixtures.envelopes_by_id()[row.envelope_ref]
        assert evaluate_temporal_claim_support(envelope, row.request) == row.expected


def test_mutated_producer_failure_with_witness_ref_raises() -> None:
    payload = _envelope("temporal-evidence:producer.missing").model_dump(mode="json")
    payload["witness_refs"] = ["witness:fake-positive-world-state"]

    with pytest.raises(ValueError, match="producer_failure evidence cannot carry"):
        TemporalEvidenceEnvelope.model_validate(payload)


def test_fixture_summary_mismatch_fails_closed(tmp_path: Path) -> None:
    fixtures = load_temporal_band_evidence_fixtures()
    payload = fixtures.model_dump(mode="json")
    payload["fail_closed_policy"] = {
        **payload["fail_closed_policy"],
        "raw_xml_alone_satisfies_public_or_director_claim": True,
    }

    path = tmp_path / "bad-temporal-band-evidence-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TemporalBandEvidenceError, match="fail_closed_policy"):
        load_temporal_band_evidence_fixtures(path)
