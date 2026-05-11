"""Tests for Unb-AIRy assertion value scoring."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agents.unb_airy.value_scorer import (
    VALUE_DIMENSIONS,
    AssertionValueScoring,
    ValueScore,
    ValueScoringError,
    _cli_main,
    apply_value_score,
    score_assertion,
    score_assertion_heuristic,
    store_score_in_frontmatter,
)
from shared.assertion_model import Assertion, AssertionType, SourceType
from shared.frontmatter import parse_frontmatter

NOW = datetime(2026, 5, 11, 3, 15, tzinfo=UTC)


def _assertion(**overrides: object) -> Assertion:
    payload = {
        "text": (
            "If compositor transitions expose witnessed frame changes, then programme "
            "assertions can ground future operator decisions because the system records evidence."
        ),
        "atomic_facts": ["transition witnessed", "operator decision evidence recorded"],
        "source_type": SourceType.MARKDOWN,
        "source_uri": "assertions/demo.md",
        "source_span": (12, 14),
        "confidence": 0.82,
        "domain": "grounding",
        "assertion_type": AssertionType.CLAIM,
        "tags": ["domain:compositor", "domain:programme"],
    }
    payload.update(overrides)
    return Assertion(**payload)


def _completion_response(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload)),
            )
        ]
    )


def test_value_score_has_exact_requested_dimensions_and_bounds() -> None:
    score = ValueScore(
        novelty=0.1,
        empirical_support=0.2,
        internal_consistency=0.3,
        generativity=0.4,
        practical_utility=0.5,
        formalization=0.6,
        cross_domain=0.7,
        explanatory_depth=0.8,
        predictive_power=0.9,
        elegance=1.0,
    )

    assert tuple(score.dimensions()) == VALUE_DIMENSIONS
    assert score.composite({"novelty": 1.0}) == 0.1
    with pytest.raises(ValidationError):
        ValueScore(
            novelty=1.2,
            empirical_support=0.2,
            internal_consistency=0.3,
            generativity=0.4,
            practical_utility=0.5,
            formalization=0.6,
            cross_domain=0.7,
            explanatory_depth=0.8,
            predictive_power=0.9,
            elegance=1.0,
        )


def test_heuristic_score_populates_assertion_score_fields() -> None:
    assertion = _assertion()

    scoring = score_assertion_heuristic(assertion, scored_at=NOW)
    scored = apply_value_score(assertion, scoring)

    assert scoring.scoring_mode == "heuristic"
    assert 0.0 <= scoring.composite <= 1.0
    assert scored.score == scoring.composite
    assert set(scored.value_scores) == set(VALUE_DIMENSIONS)
    assert scored.value_scores["empirical_support"] >= 0.7
    assert scored.value_scores["predictive_power"] > 0.3


def test_litellm_balanced_scoring_requests_json_schema_and_blends_scores() -> None:
    calls: list[dict[str, object]] = []
    llm_payload = {dimension: 0.8 for dimension in VALUE_DIMENSIONS}
    llm_payload["rationale"] = "Clear, useful, and evidence-bearing assertion."

    def fake_completion(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return _completion_response(llm_payload)

    scoring = score_assertion(
        _assertion(),
        completion_fn=fake_completion,
        scored_at=NOW,
    )

    assert scoring.scoring_mode == "hybrid"
    assert scoring.scoring_model == "claude-sonnet"
    assert scoring.rationale == "Clear, useful, and evidence-bearing assertion."
    assert len(calls) == 1
    call = calls[0]
    assert call["model"] == "claude-sonnet"
    assert call["temperature"] == 0.0
    assert call["response_format"]["type"] == "json_schema"  # type: ignore[index]
    assert "programme assertions" in call["messages"][1]["content"]  # type: ignore[index]
    assert all(0.0 <= value <= 1.0 for value in scoring.scores.dimensions().values())


def test_litellm_failure_can_fail_closed_or_use_explicit_heuristic_fallback() -> None:
    def bad_completion(**_kwargs: object) -> SimpleNamespace:
        raise RuntimeError("gateway down")

    assertion = _assertion()
    with pytest.raises(ValueScoringError):
        score_assertion(assertion, completion_fn=bad_completion)

    fallback = score_assertion(
        assertion,
        completion_fn=bad_completion,
        allow_heuristic_fallback=True,
    )
    assert fallback.scoring_mode == "heuristic_fallback"
    assert fallback.scoring_model == "claude-sonnet"
    assert fallback.composite > 0.0


def test_store_score_in_assertion_frontmatter(tmp_path: Path) -> None:
    note = tmp_path / "assertion.md"
    note.write_text(
        "---\ntype: assertion\nassertion_id: demo\n---\nBody stays intact.\n",
        encoding="utf-8",
    )
    scoring = AssertionValueScoring(
        assertion_id="demo",
        scores=ValueScore(
            novelty=0.1,
            empirical_support=0.2,
            internal_consistency=0.3,
            generativity=0.4,
            practical_utility=0.5,
            formalization=0.6,
            cross_domain=0.7,
            explanatory_depth=0.8,
            predictive_power=0.9,
            elegance=1.0,
        ),
        composite=0.55,
        weights={dimension: 0.1 for dimension in VALUE_DIMENSIONS},
        scoring_mode="hybrid",
        scoring_model="claude-sonnet",
        rationale="test rationale",
        scored_at=NOW,
    )

    assert store_score_in_frontmatter(note, scoring) is True
    assert store_score_in_frontmatter(note, scoring) is False

    frontmatter, body = parse_frontmatter(note)
    assert body == "Body stays intact.\n"
    assert frontmatter["value_score"] == 0.55
    assert frontmatter["assertion_value_score"]["dimensions"]["predictive_power"] == 0.9
    assert frontmatter["assertion_value_score"]["model"] == "claude-sonnet"


def test_cli_scores_extraction_output_without_llm(tmp_path: Path) -> None:
    input_path = tmp_path / "assertions.json"
    output_path = tmp_path / "scored.json"
    assertion = _assertion()
    input_path.write_text(
        json.dumps({"assertions": [assertion.model_dump(mode="json")]}),
        encoding="utf-8",
    )

    assert _cli_main([str(input_path), "-o", str(output_path), "--no-llm"]) == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    scored = payload["assertions"][0]
    assert scored["assertion_id"] == assertion.assertion_id
    assert isinstance(scored["score"], float)
    assert set(scored["value_scores"]) == set(VALUE_DIMENSIONS)
    assert payload["value_scoring"]["dimensions"] == list(VALUE_DIMENSIONS)
