from __future__ import annotations

from shared.layout_receipt_freshness import (
    INTERVIEW_REQUIRED_WARDS,
    validate_receipt_freshness,
)


class TestReceiptFreshness:
    def test_fresh_matching_receipt_passes(self) -> None:
        result = validate_receipt_freshness(
            receipt_observed_at=100.0,
            receipt_layout="segment-detail",
            receipt_wards=("artifact-panel", "source-card"),
            current_layout="segment-detail",
            now=110.0,
        )
        assert result.ok is True
        assert result.stale is False
        assert result.layout_match is True

    def test_stale_receipt_rejected(self) -> None:
        result = validate_receipt_freshness(
            receipt_observed_at=100.0,
            receipt_layout="segment-detail",
            receipt_wards=(),
            current_layout="segment-detail",
            max_age_s=30.0,
            now=200.0,
        )
        assert result.ok is False
        assert result.stale is True
        assert "100.0s old" in result.reason

    def test_layout_mismatch_rejected(self) -> None:
        result = validate_receipt_freshness(
            receipt_observed_at=100.0,
            receipt_layout="default",
            receipt_wards=(),
            current_layout="segment-detail",
            now=105.0,
        )
        assert result.ok is False
        assert result.layout_match is False
        assert "default" in result.reason

    def test_interview_missing_wards_rejected(self) -> None:
        result = validate_receipt_freshness(
            receipt_observed_at=100.0,
            receipt_layout="segment-detail",
            receipt_wards=("question_card", "source_card"),
            current_layout="segment-detail",
            role="interview",
            now=105.0,
        )
        assert result.ok is False
        assert len(result.missing_wards) == 3
        assert "transcript_card" in result.missing_wards
        assert "answer_delta_card" in result.missing_wards
        assert "unknowns_card" in result.missing_wards

    def test_interview_all_wards_present_passes(self) -> None:
        result = validate_receipt_freshness(
            receipt_observed_at=100.0,
            receipt_layout="segment-detail",
            receipt_wards=tuple(INTERVIEW_REQUIRED_WARDS),
            current_layout="segment-detail",
            role="interview",
            now=105.0,
        )
        assert result.ok is True
        assert result.missing_wards == ()

    def test_non_interview_role_no_ward_requirement(self) -> None:
        result = validate_receipt_freshness(
            receipt_observed_at=100.0,
            receipt_layout="segment-detail",
            receipt_wards=(),
            current_layout="segment-detail",
            role="tier_list",
            now=105.0,
        )
        assert result.ok is True

    def test_receipt_age_calculated(self) -> None:
        result = validate_receipt_freshness(
            receipt_observed_at=100.0,
            receipt_layout="x",
            receipt_wards=(),
            current_layout="x",
            now=115.5,
        )
        assert result.receipt_age_s == 15.5
