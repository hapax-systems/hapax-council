"""Tests for the YouTube packaging claim policy.

Verifies the cc-task `youtube-packaging-claim-policy` acceptance.
"""

from __future__ import annotations

import pytest

from shared.youtube_packaging_claim_policy import (
    CORRECTION_LANGUAGE_TEMPLATES,
    REFUSAL_LANGUAGE_TEMPLATES,
    BlockedClaimReason,
    ClaimClass,
    PackagingClaim,
    PackagingPayload,
    evaluate_payload,
)


def test_claim_classes_enum_has_all_required_values():
    expected = {
        "descriptive",
        "liveness",
        "run_result",
        "refusal",
        "correction",
        "archive",
        "monetization",
    }
    assert {c.value for c in ClaimClass} == expected


def test_claim_with_descriptive_class_does_not_require_public_event_ref():
    claim = PackagingClaim(
        text="A studio recording session",
        claim_class=ClaimClass.DESCRIPTIVE,
    )
    assert claim.public_event_ref is None


def test_claim_with_liveness_class_requires_public_event_ref():
    with pytest.raises(ValueError):
        PackagingClaim(
            text="Live now on the channel",
            claim_class=ClaimClass.LIVENESS,
        )


def test_claim_with_run_result_class_requires_public_event_ref():
    with pytest.raises(ValueError):
        PackagingClaim(
            text="Programme outcome was successful",
            claim_class=ClaimClass.RUN_RESULT,
        )


def test_claim_with_archive_class_with_public_event_ref():
    claim = PackagingClaim(
        text="Archived broadcast available",
        claim_class=ClaimClass.ARCHIVE,
        public_event_ref="public-event:abcd123",
    )
    assert claim.public_event_ref == "public-event:abcd123"


def test_evaluate_payload_passes_neutral_descriptive_text():
    payload = PackagingPayload(
        field_kind="title",
        field_text="Studio session — research notes from a quiet afternoon",
    )
    verdict = evaluate_payload(payload)
    assert verdict.allowed is True


def test_evaluate_payload_blocks_expert_verdict_framing():
    payload = PackagingPayload(
        field_kind="description",
        field_text="As the expert says, this approach is best",
    )
    verdict = evaluate_payload(payload)
    assert verdict.allowed is False
    assert BlockedClaimReason.EXPERT_VERDICT_FRAMING in verdict.blockers


def test_evaluate_payload_blocks_unsupported_superlative():
    payload = PackagingPayload(
        field_kind="title",
        field_text="The greatest livestream of all time",
    )
    verdict = evaluate_payload(payload)
    assert verdict.allowed is False
    assert BlockedClaimReason.UNSUPPORTED_SUPERLATIVE in verdict.blockers


def test_evaluate_payload_blocks_rights_risky_media_claim():
    payload = PackagingPayload(
        field_kind="description",
        field_text="Soundtrack by Brian Eno",
    )
    verdict = evaluate_payload(payload)
    assert verdict.allowed is False
    assert BlockedClaimReason.RIGHTS_RISKY_MEDIA_CLAIM in verdict.blockers


def test_evaluate_payload_blocks_trend_as_truth_claim():
    payload = PackagingPayload(
        field_kind="title",
        field_text="Going viral proves it works",
    )
    verdict = evaluate_payload(payload)
    assert verdict.allowed is False
    assert BlockedClaimReason.TREND_AS_TRUTH_CLAIM in verdict.blockers


def test_evaluate_payload_accepts_claim_with_public_event_ref():
    claim = PackagingClaim(
        text="Programme run completed",
        claim_class=ClaimClass.RUN_RESULT,
        public_event_ref="public-event:run-001",
    )
    payload = PackagingPayload(
        field_kind="description",
        field_text="Programme run completed at 2026-05-02T10:00Z",
        claims=(claim,),
    )
    verdict = evaluate_payload(payload)
    assert verdict.allowed is True


def test_evaluate_payload_aggregates_multiple_blockers():
    payload = PackagingPayload(
        field_kind="title",
        field_text="As the expert says, the greatest livestream of all time",
    )
    verdict = evaluate_payload(payload)
    assert verdict.allowed is False
    assert BlockedClaimReason.EXPERT_VERDICT_FRAMING in verdict.blockers
    assert BlockedClaimReason.UNSUPPORTED_SUPERLATIVE in verdict.blockers


def test_refusal_language_templates_present():
    expected_keys = {
        "in_person_event_refused",
        "platform_partnership_refused",
        "interview_request_refused",
        "expert_panel_refused",
    }
    assert expected_keys.issubset(REFUSAL_LANGUAGE_TEMPLATES.keys())


def test_correction_language_templates_present():
    expected_keys = {
        "claim_corrected",
        "duration_corrected",
        "attribution_corrected",
    }
    assert expected_keys.issubset(CORRECTION_LANGUAGE_TEMPLATES.keys())
    for value in CORRECTION_LANGUAGE_TEMPLATES.values():
        assert "{" in value


def test_payload_field_kinds_cover_all_youtube_packaging_surfaces():
    expected_kinds = {
        "title",
        "description",
        "thumbnail_text",
        "chapter",
        "caption",
        "shorts_caption",
        "channel_section",
    }
    for kind in expected_kinds:
        payload = PackagingPayload(field_kind=kind, field_text="ok")
        assert payload.field_kind == kind
