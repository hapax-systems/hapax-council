from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agents.epistemic_calibrator import (
    AXIS_SCORES,
    BaselineScorerOutput,
    CalibrationScore,
    LLMScoringUnavailable,
    OverclaimSpan,
    axis_scores_for_text,
    baseline_output_for_record,
    score_text_baseline,
    score_text_with_llm_non_authoritative,
    source_text_hash,
)


def test_contract_models_validate_bounds_and_hashes() -> None:
    with pytest.raises(ValidationError):
        OverclaimSpan(start=8, end=3, text="always", category="false_universal")

    with pytest.raises(ValidationError):
        CalibrationScore(
            confidence_float=1.2,
            hedge_density=0.0,
            quantifier_precision=0.5,
            rigidity_score=0.0,
            source_text_hash="not-a-sha",
        )

    score = CalibrationScore(
        confidence_float=0.5,
        hedge_density=0.1,
        quantifier_precision=0.6,
        rigidity_score=0.2,
        source_text_hash="a" * 64,
    )

    assert score.source_text_hash == "a" * 64


def test_baseline_scoring_is_deterministic_and_flags_overclaims() -> None:
    text = (
        "The report may support a bounded claim because a measurement receipt cites n=12 "
        "samples. It never proves complete safety for every deployment."
    )

    first = score_text_baseline(text)
    second = score_text_baseline(text)

    assert first == second
    assert first.source_text_hash == source_text_hash(text)
    assert first.hedge_density > 0
    assert first.quantifier_precision > 0.0
    assert first.rigidity_score > 0
    assert {span.category for span in first.overclaim_flags} >= {"false_universal"}


def test_axis_scores_are_bounded_validation_axes() -> None:
    text = "Maybe 3/5 samples support the claim, with the source report attached."
    axis_scores = axis_scores_for_text(text)

    assert set(axis_scores) == set(AXIS_SCORES)
    assert all(1.0 <= score <= 5.0 for score in axis_scores.values())


def test_baseline_output_matches_validation_row_contract() -> None:
    text = "The test report cites sha256 evidence for 4 measured cases and scoped limits."
    record = {
        "id": "eqi-v0-fixture-001",
        "excerpt": text,
        "excerpt_hash": source_text_hash(text),
    }
    output = baseline_output_for_record(
        record,
        manifest_hash="b" * 64,
        scored_at=datetime(2026, 5, 20, 17, 30, tzinfo=UTC),
    )
    dumped = output.model_dump(mode="json")

    assert isinstance(output, BaselineScorerOutput)
    assert dumped["manifest_id"] == record["id"]
    assert dumped["source_text_hash"] == record["excerpt_hash"]
    assert dumped["scorer"] == "epistemic_calibrator_baseline_v0"
    assert dumped["authority_level"] == "support_non_authoritative"
    assert set(dumped["axis_scores"]) == set(AXIS_SCORES)


def test_llm_path_fails_closed_without_litellm_client() -> None:
    with pytest.raises(LLMScoringUnavailable):
        score_text_with_llm_non_authoritative("score this text")
