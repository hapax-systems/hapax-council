"""Tests for Unb-AIRy value scorer — heuristic scoring, LLM scoring, blending, CLI."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.unb_airy.value_scorer import (
    DEFAULT_VALUE_SCORE_WEIGHTS,
    SCORER_VERSION,
    VALUE_DIMENSIONS,
    ValueScore,
    ValueScoringError,
    _cli_main,
    apply_value_score,
    score_assertion,
    score_assertion_heuristic,
    score_assertions,
    store_score_in_frontmatter,
)
from shared.assertion_model import Assertion, AssertionType, SourceType


def _make_assertion(**overrides: Any) -> Assertion:
    defaults: dict[str, Any] = {
        "text": "All LLM calls must route through LiteLLM gateway.",
        "source_type": SourceType.GOVERNANCE,
        "source_uri": "axioms/registry.yaml",
        "confidence": 0.9,
        "domain": "constitutional",
        "assertion_type": AssertionType.CONSTRAINT,
        "tags": ["scope:system", "weight:100"],
    }
    defaults.update(overrides)
    return Assertion(**defaults)


def _fake_completion(**kwargs: Any) -> Any:
    score = ValueScore(
        novelty=0.4,
        empirical_support=0.7,
        internal_consistency=0.9,
        generativity=0.5,
        practical_utility=0.8,
        formalization=0.6,
        cross_domain=0.3,
        explanatory_depth=0.5,
        predictive_power=0.4,
        elegance=0.7,
    )
    payload = score.model_dump()
    payload["rationale"] = "Test rationale."
    content = json.dumps(payload)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class TestValueScore:
    def test_all_dimensions_bounded(self) -> None:
        score = ValueScore(
            novelty=0.0,
            empirical_support=1.0,
            internal_consistency=0.5,
            generativity=0.3,
            practical_utility=0.9,
            formalization=0.1,
            cross_domain=0.2,
            explanatory_depth=0.7,
            predictive_power=0.4,
            elegance=0.6,
        )
        for dim in VALUE_DIMENSIONS:
            val = getattr(score, dim)
            assert 0.0 <= val <= 1.0

    def test_dimensions_returns_all_ten(self) -> None:
        score = ValueScore(**{dim: 0.5 for dim in VALUE_DIMENSIONS})
        dims = score.dimensions()
        assert len(dims) == 10
        assert set(dims.keys()) == set(VALUE_DIMENSIONS)

    def test_composite_default_weights(self) -> None:
        score = ValueScore(**{dim: 0.5 for dim in VALUE_DIMENSIONS})
        composite = score.composite()
        assert composite == pytest.approx(0.5, abs=0.01)

    def test_composite_custom_weights(self) -> None:
        score = ValueScore(**{dim: 0.0 for dim in VALUE_DIMENSIONS})
        score = score.model_copy(update={"novelty": 1.0})
        weights = {dim: 0.0 for dim in VALUE_DIMENSIONS}
        weights["novelty"] = 1.0
        assert score.composite(weights) == pytest.approx(1.0, abs=0.01)

    def test_composite_rejects_all_zero_weights(self) -> None:
        score = ValueScore(**{dim: 0.5 for dim in VALUE_DIMENSIONS})
        with pytest.raises(ValueError, match="at least one"):
            score.composite({dim: 0.0 for dim in VALUE_DIMENSIONS})

    def test_rejects_out_of_range(self) -> None:
        with pytest.raises(Exception):
            ValueScore(**{dim: 1.5 if dim == "novelty" else 0.5 for dim in VALUE_DIMENSIONS})

    def test_rejects_negative(self) -> None:
        with pytest.raises(Exception):
            ValueScore(**{dim: -0.1 if dim == "novelty" else 0.5 for dim in VALUE_DIMENSIONS})

    def test_frozen(self) -> None:
        score = ValueScore(**{dim: 0.5 for dim in VALUE_DIMENSIONS})
        with pytest.raises(Exception):
            score.novelty = 0.9  # type: ignore[misc]


class TestHeuristicScoring:
    def test_constraint_gets_practical_utility_boost(self) -> None:
        a = _make_assertion(assertion_type=AssertionType.CONSTRAINT)
        scoring = score_assertion_heuristic(a)
        assert scoring.scores.practical_utility > 0.4

    def test_code_source_boosts_formalization(self) -> None:
        a = _make_assertion(source_type=SourceType.CODE, source_uri="shared/config.py")
        scoring = score_assertion_heuristic(a)
        assert scoring.scores.formalization > 0.4

    def test_superseded_assertion_lowers_novelty(self) -> None:
        normal = _make_assertion()
        superseded = _make_assertion(superseded_by="abc123")
        s_normal = score_assertion_heuristic(normal)
        s_superseded = score_assertion_heuristic(superseded)
        assert s_superseded.scores.novelty < s_normal.scores.novelty

    def test_empty_text_kills_consistency(self) -> None:
        a = _make_assertion(text="")
        scoring = score_assertion_heuristic(a)
        assert scoring.scores.internal_consistency == 0.0

    def test_long_text_penalizes_elegance(self) -> None:
        short = _make_assertion(text="Short assertion.")
        long_text = " ".join(["word"] * 60)
        long = _make_assertion(text=long_text)
        s_short = score_assertion_heuristic(short)
        s_long = score_assertion_heuristic(long)
        assert s_long.scores.elegance < s_short.scores.elegance

    def test_atomic_facts_boost_empirical_and_formalization(self) -> None:
        without = _make_assertion(atomic_facts=[])
        with_facts = _make_assertion(atomic_facts=["fact A", "fact B"])
        s_without = score_assertion_heuristic(without)
        s_with = score_assertion_heuristic(with_facts)
        assert s_with.scores.empirical_support > s_without.scores.empirical_support
        assert s_with.scores.formalization > s_without.scores.formalization

    def test_implication_boosts_predictive_power(self) -> None:
        a = _make_assertion(assertion_type=AssertionType.IMPLICATION)
        scoring = score_assertion_heuristic(a)
        assert scoring.scores.predictive_power > 0.3

    def test_composite_in_range(self) -> None:
        a = _make_assertion()
        scoring = score_assertion_heuristic(a)
        assert 0.0 <= scoring.composite <= 1.0

    def test_scoring_mode_is_heuristic(self) -> None:
        a = _make_assertion()
        scoring = score_assertion_heuristic(a)
        assert scoring.scoring_mode == "heuristic"
        assert scoring.scoring_model == "heuristic"

    def test_todo_in_text_penalizes_elegance(self) -> None:
        clean = _make_assertion(text="All routes must validate input.")
        dirty = _make_assertion(text="TODO validate input on all routes.")
        s_clean = score_assertion_heuristic(clean)
        s_dirty = score_assertion_heuristic(dirty)
        assert s_dirty.scores.elegance < s_clean.scores.elegance

    def test_contradiction_tag_lowers_consistency(self) -> None:
        normal = _make_assertion(tags=[])
        contradicted = _make_assertion(tags=["contradiction:detected"])
        s_normal = score_assertion_heuristic(normal)
        s_contradicted = score_assertion_heuristic(contradicted)
        assert s_contradicted.scores.internal_consistency < s_normal.scores.internal_consistency


class TestLLMScoring:
    def test_hybrid_mode_with_completion_fn(self) -> None:
        a = _make_assertion()
        scoring = score_assertion(a, completion_fn=_fake_completion, use_llm=True)
        assert scoring.scoring_mode == "hybrid"
        assert scoring.rationale == "Test rationale."

    def test_no_llm_returns_heuristic(self) -> None:
        a = _make_assertion()
        scoring = score_assertion(a, use_llm=False)
        assert scoring.scoring_mode == "heuristic"

    def test_fallback_on_failure(self) -> None:
        def _failing_completion(**kwargs: Any) -> Any:
            raise RuntimeError("LLM unavailable")

        a = _make_assertion()
        scoring = score_assertion(
            a,
            completion_fn=_failing_completion,
            use_llm=True,
            allow_heuristic_fallback=True,
        )
        assert scoring.scoring_mode == "heuristic_fallback"
        assert "LLM unavailable" in scoring.rationale

    def test_no_fallback_raises(self) -> None:
        def _failing_completion(**kwargs: Any) -> Any:
            raise RuntimeError("LLM down")

        a = _make_assertion()
        with pytest.raises(ValueScoringError, match="LLM down"):
            score_assertion(
                a,
                completion_fn=_failing_completion,
                use_llm=True,
                allow_heuristic_fallback=False,
            )

    def test_hybrid_blends_scores(self) -> None:
        a = _make_assertion()
        heuristic = score_assertion_heuristic(a)
        hybrid = score_assertion(a, completion_fn=_fake_completion, use_llm=True)
        for dim in VALUE_DIMENSIONS:
            h_val = getattr(heuristic.scores, dim)
            hybrid_val = getattr(hybrid.scores, dim)
            assert not (h_val == hybrid_val and h_val != 0.5)


class TestBatchScoring:
    def test_scores_multiple_assertions(self) -> None:
        assertions = [_make_assertion(text=f"Assertion {i}") for i in range(3)]
        results = score_assertions(assertions, use_llm=False)
        assert len(results) == 3
        for r in results:
            assert r.scoring_mode == "heuristic"

    def test_preserves_order(self) -> None:
        a1 = _make_assertion(text="First assertion")
        a2 = _make_assertion(text="Second assertion with more words to differentiate")
        results = score_assertions([a1, a2], use_llm=False)
        assert results[0].assertion_id == a1.assertion_id
        assert results[1].assertion_id == a2.assertion_id


class TestApplyValueScore:
    def test_copies_score_to_assertion(self) -> None:
        a = _make_assertion()
        scoring = score_assertion_heuristic(a)
        updated = apply_value_score(a, scoring)
        assert updated.score == scoring.composite
        assert updated.value_scores == scoring.scores.dimensions()
        assert updated.text == a.text

    def test_mismatched_id_raises(self) -> None:
        a = _make_assertion()
        scoring = score_assertion_heuristic(a)
        other = _make_assertion(text="Different assertion entirely")
        with pytest.raises(ValueError, match="does not match"):
            apply_value_score(other, scoring)


class TestFrontmatterPersistence:
    def test_frontmatter_payload_shape(self) -> None:
        a = _make_assertion()
        scoring = score_assertion_heuristic(a)
        payload = scoring.frontmatter_payload()
        assert "value_score" in payload
        assert "assertion_value_score" in payload
        details = payload["assertion_value_score"]
        assert "dimensions" in details
        assert "composite" in details
        assert "weights" in details
        assert "mode" in details
        assert details["scorer_version"] == SCORER_VERSION

    def test_store_score_updates_file(self, tmp_path: Path) -> None:
        note = tmp_path / "test_assertion.md"
        note.write_text(
            "---\nassertion_id: abc123\ntext: test\n---\nBody text.\n",
            encoding="utf-8",
        )
        a = _make_assertion()
        scoring = score_assertion_heuristic(a)
        scoring = scoring.model_copy(update={"assertion_id": "abc123"})
        result = store_score_in_frontmatter(note, scoring)
        assert result is True
        content = note.read_text()
        assert "value_score" in content

    def test_store_score_idempotent(self, tmp_path: Path) -> None:
        note = tmp_path / "test_assertion.md"
        note.write_text(
            "---\nassertion_id: abc123\ntext: test\n---\nBody text.\n",
            encoding="utf-8",
        )
        a = _make_assertion()
        scoring = score_assertion_heuristic(a)
        scoring = scoring.model_copy(update={"assertion_id": "abc123"})
        store_score_in_frontmatter(note, scoring)
        second = store_score_in_frontmatter(note, scoring)
        assert second is False


class TestCLI:
    def test_heuristic_json_output(self, tmp_path: Path) -> None:
        assertions = [_make_assertion().model_dump(mode="json")]
        input_file = tmp_path / "input.json"
        input_file.write_text(json.dumps(assertions), encoding="utf-8")
        output_file = tmp_path / "output.json"
        rc = _cli_main([str(input_file), "-o", str(output_file), "--no-llm"])
        assert rc == 0
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert "score" in data[0]
        assert "value_scores" in data[0]

    def test_wrapped_payload(self, tmp_path: Path) -> None:
        payload = {"assertions": [_make_assertion().model_dump(mode="json")], "meta": "test"}
        input_file = tmp_path / "input.json"
        input_file.write_text(json.dumps(payload), encoding="utf-8")
        output_file = tmp_path / "output.json"
        rc = _cli_main([str(input_file), "-o", str(output_file), "--no-llm"])
        assert rc == 0
        data = json.loads(output_file.read_text())
        assert isinstance(data, dict)
        assert "assertions" in data
        assert "value_scoring" in data
        assert data["value_scoring"]["scorer_version"] == SCORER_VERSION

    def test_invalid_input_returns_error(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('"not an array or object with assertions"', encoding="utf-8")
        rc = _cli_main([str(bad_file), "--no-llm"])
        assert rc == 1

    def test_stdout_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assertions = [_make_assertion().model_dump(mode="json")]
        input_file = tmp_path / "input.json"
        input_file.write_text(json.dumps(assertions), encoding="utf-8")
        rc = _cli_main([str(input_file), "--no-llm"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)


class TestWeights:
    def test_default_weights_sum_to_one(self) -> None:
        total = sum(DEFAULT_VALUE_SCORE_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_all_dimensions_have_default_weight(self) -> None:
        for dim in VALUE_DIMENSIONS:
            assert dim in DEFAULT_VALUE_SCORE_WEIGHTS
            assert DEFAULT_VALUE_SCORE_WEIGHTS[dim] > 0

    def test_ten_dimensions_defined(self) -> None:
        assert len(VALUE_DIMENSIONS) == 10
