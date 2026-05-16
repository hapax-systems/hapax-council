"""Tests for embedding-based acceptance classifier (Council IV Repair 3)."""

from __future__ import annotations

from unittest.mock import patch

from agents.hapax_daimonion.grounding_evaluator import (
    _classify_acceptance_keywords,
    classify_acceptance,
)


class TestKeywordFallback:
    def test_yeah_is_accept(self) -> None:
        label, _ = _classify_acceptance_keywords("yeah")
        assert label == "ACCEPT"

    def test_no_is_reject(self) -> None:
        label, _ = _classify_acceptance_keywords("no that's wrong")
        assert label == "REJECT"

    def test_empty_is_ignore(self) -> None:
        label, _ = _classify_acceptance_keywords("")
        assert label == "IGNORE"

    def test_what_do_you_mean_is_clarify(self) -> None:
        label, _ = _classify_acceptance_keywords("what do you mean")
        assert label == "CLARIFY"


class TestEmbeddingClassifier:
    def test_falls_back_when_embed_unavailable(self) -> None:
        with patch(
            "agents.hapax_daimonion.grounding_evaluator._get_prototype_embeddings",
            return_value=None,
        ):
            label, _ = classify_acceptance("yeah exactly")
            assert label == "ACCEPT"

    def test_empty_utterance_returns_ignore(self) -> None:
        label, _ = classify_acceptance("")
        assert label == "IGNORE"

    def test_score_map_values(self) -> None:
        _, score = _classify_acceptance_keywords("yeah")
        assert score == 1.0
        _, score = _classify_acceptance_keywords("what do you mean")
        assert score == 0.7
        _, score = _classify_acceptance_keywords("random words")
        assert score == 0.3
        _, score = _classify_acceptance_keywords("no that's wrong")
        assert score == 0.0
