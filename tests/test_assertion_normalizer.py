"""Tests for shared.assertion_normalizer — Phase 3 normalization and dedup."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch

import pytest

from shared.assertion_model import Assertion, AssertionType, SourceType
from shared.assertion_normalizer import (
    DuplicateGroup,
    EntailmentResult,
    apply_entailments,
    cosine_similarity,
    find_duplicate_groups,
    find_entailment_candidates,
    merge_duplicates,
    normalize_assertion,
    normalize_text,
    parse_nli_response,
    run_normalization_pipeline,
)

# ── Text Normalization ───────────────────────────────────────────────────────


class TestNormalizeText:
    def test_lowercase(self) -> None:
        assert normalize_text("Tests MUST Pass") == "tests must pass"

    def test_strip_whitespace(self) -> None:
        assert normalize_text("  hello world  ") == "hello world"

    def test_collapse_internal_whitespace(self) -> None:
        assert normalize_text("tests   must    pass") == "tests must pass"

    def test_strip_trailing_punctuation(self) -> None:
        assert normalize_text("no direct push.") == "no direct push"
        assert normalize_text("always PR;") == "always pr"
        assert normalize_text("keep it clean,") == "keep it clean"

    def test_strip_bullet_prefix(self) -> None:
        assert normalize_text("- Tests must pass") == "tests must pass"
        assert normalize_text("* Never push") == "never push"
        assert normalize_text("• Always lint") == "always lint"

    def test_normalize_unicode_quotes(self) -> None:
        assert normalize_text("don’t do this") == "don't do this"
        assert normalize_text("“hello”") == '"hello"'

    def test_normalize_dashes(self) -> None:
        assert normalize_text("pre—condition") == "pre--condition"
        assert normalize_text("pre–condition") == "pre-condition"

    def test_tabs_and_newlines(self) -> None:
        assert normalize_text("line one\n\tline two") == "line one line two"

    def test_empty_string(self) -> None:
        assert normalize_text("") == ""

    def test_already_normalized(self) -> None:
        assert normalize_text("already clean") == "already clean"


class TestNormalizeAssertion:
    def _make_assertion(self, text: str, confidence: float = 0.9) -> Assertion:
        return Assertion(
            text=text,
            source_type=SourceType.CODE,
            source_uri="/test.py",
            confidence=confidence,
            assertion_type=AssertionType.CONSTRAINT,
        )

    def test_normalizes_text(self) -> None:
        a = self._make_assertion("  Tests MUST pass.  ")
        result = normalize_assertion(a)
        assert result.text == "tests must pass"

    def test_preserves_id(self) -> None:
        a = self._make_assertion("Tests MUST Pass")
        result = normalize_assertion(a)
        assert result.assertion_id == a.assertion_id

    def test_returns_same_if_unchanged(self) -> None:
        a = self._make_assertion("already clean")
        result = normalize_assertion(a)
        assert result is a


# ── Cosine Similarity ────────────────────────────────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self) -> None:
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert cosine_similarity(a, b) == 0.0

    def test_known_value(self) -> None:
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        expected = (4 + 10 + 18) / (math.sqrt(14) * math.sqrt(77))
        assert cosine_similarity(a, b) == pytest.approx(expected)


# ── Duplicate Detection ──────────────────────────────────────────────────────


def _make_assertions(n: int, confidence: float = 0.9) -> list[Assertion]:
    return [
        Assertion(
            text=f"assertion {i}",
            source_type=SourceType.CODE,
            source_uri=f"/test_{i}.py",
            confidence=confidence,
            assertion_type=AssertionType.CONSTRAINT,
        )
        for i in range(n)
    ]


class TestFindDuplicateGroups:
    def test_no_duplicates(self) -> None:
        assertions = _make_assertions(3)
        embeddings = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        groups = find_duplicate_groups(assertions, embeddings)
        assert groups == []

    def test_exact_duplicates(self) -> None:
        assertions = _make_assertions(3)
        embeddings = [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        groups = find_duplicate_groups(assertions, embeddings)
        assert len(groups) == 1
        assert groups[0].canonical == 0
        assert groups[0].duplicates == [1]
        assert groups[0].similarities[0] == pytest.approx(1.0)

    def test_above_threshold(self) -> None:
        assertions = _make_assertions(2)
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.99, 0.14, 0.0]  # cosine ~ 0.99
        embeddings = [v1, v2]
        groups = find_duplicate_groups(assertions, embeddings, threshold=0.9)
        assert len(groups) == 1

    def test_below_threshold(self) -> None:
        assertions = _make_assertions(2)
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.7, 0.7, 0.0]  # cosine ~ 0.707
        embeddings = [v1, v2]
        groups = find_duplicate_groups(assertions, embeddings, threshold=0.85)
        assert groups == []

    def test_multiple_groups(self) -> None:
        assertions = _make_assertions(4)
        embeddings = [
            [1.0, 0.0, 0.0],
            [1.0, 0.01, 0.0],  # near-duplicate of 0
            [0.0, 1.0, 0.0],
            [0.0, 1.0, 0.01],  # near-duplicate of 2
        ]
        groups = find_duplicate_groups(assertions, embeddings, threshold=0.99)
        assert len(groups) == 2

    def test_mismatched_lengths(self) -> None:
        assertions = _make_assertions(2)
        embeddings = [[1.0, 0.0]]
        with pytest.raises(ValueError, match="same length"):
            find_duplicate_groups(assertions, embeddings)


# ── NLI Response Parsing ─────────────────────────────────────────────────────


class TestParseNliResponse:
    def test_entailment(self) -> None:
        label, conf = parse_nli_response("entailment 0.9")
        assert label == "entailment"
        assert conf == pytest.approx(0.9)

    def test_contradiction(self) -> None:
        label, conf = parse_nli_response("contradiction 0.85")
        assert label == "contradiction"
        assert conf == pytest.approx(0.85)

    def test_neutral(self) -> None:
        label, conf = parse_nli_response("neutral 0.7")
        assert label == "neutral"
        assert conf == pytest.approx(0.7)

    def test_verbose_response(self) -> None:
        label, conf = parse_nli_response("The relationship is entailment with confidence 0.8")
        assert label == "entailment"
        assert conf == pytest.approx(0.8)

    def test_no_confidence(self) -> None:
        label, conf = parse_nli_response("entailment")
        assert label == "entailment"
        assert conf == 0.5

    def test_unrecognized_defaults_neutral(self) -> None:
        label, conf = parse_nli_response("I don't know")
        assert label == "neutral"
        assert conf == 0.5


# ── Entailment Candidates ────────────────────────────────────────────────────


class TestFindEntailmentCandidates:
    def test_finds_candidates_in_range(self) -> None:
        assertions = _make_assertions(3)
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.8, 0.6, 0.0]  # cosine ~ 0.8 with v1
        v3 = [0.0, 1.0, 0.0]  # cosine ~ 0.0 with v1
        embeddings = [v1, v2, v3]
        candidates = find_entailment_candidates(
            assertions, embeddings, similarity_floor=0.7, similarity_ceiling=0.85
        )
        assert (0, 1) in candidates
        assert (0, 2) not in candidates

    def test_excludes_above_ceiling(self) -> None:
        assertions = _make_assertions(2)
        embeddings = [[1.0, 0.0], [1.0, 0.0]]  # identical = 1.0
        candidates = find_entailment_candidates(
            assertions, embeddings, similarity_floor=0.7, similarity_ceiling=0.85
        )
        assert candidates == []

    def test_excludes_below_floor(self) -> None:
        assertions = _make_assertions(2)
        embeddings = [[1.0, 0.0], [0.0, 1.0]]  # orthogonal = 0.0
        candidates = find_entailment_candidates(
            assertions, embeddings, similarity_floor=0.7, similarity_ceiling=0.85
        )
        assert candidates == []


# ── Merge Strategy ───────────────────────────────────────────────────────────


class TestMergeDuplicates:
    def test_keeps_highest_confidence(self) -> None:
        assertions = [
            Assertion(
                text="test",
                source_type=SourceType.CODE,
                source_uri="/a.py",
                confidence=0.7,
                assertion_type=AssertionType.CONSTRAINT,
            ),
            Assertion(
                text="test",
                source_type=SourceType.CODE,
                source_uri="/b.py",
                confidence=0.9,
                assertion_type=AssertionType.CONSTRAINT,
            ),
        ]
        groups = [DuplicateGroup(canonical=0, duplicates=[1], similarities=[1.0])]
        result = merge_duplicates(assertions, groups)
        # Index 1 has higher confidence, so index 0 gets superseded
        assert result[0].superseded_by == assertions[1].assertion_id
        assert result[1].superseded_by is None

    def test_records_modification_history(self) -> None:
        assertions = [
            Assertion(
                text="test a",
                source_type=SourceType.CODE,
                source_uri="/a.py",
                confidence=0.9,
                assertion_type=AssertionType.CONSTRAINT,
            ),
            Assertion(
                text="test b",
                source_type=SourceType.CODE,
                source_uri="/b.py",
                confidence=0.7,
                assertion_type=AssertionType.CONSTRAINT,
            ),
        ]
        groups = [DuplicateGroup(canonical=0, duplicates=[1], similarities=[0.9])]
        result = merge_duplicates(assertions, groups)
        history = result[1].provenance.modification_history
        assert len(history) == 1
        assert history[0]["action"] == "superseded_by_dedup"

    def test_no_groups_returns_unchanged(self) -> None:
        assertions = _make_assertions(3)
        result = merge_duplicates(assertions, [])
        for orig, merged in zip(assertions, result, strict=True):
            assert merged.assertion_id == orig.assertion_id
            assert merged.superseded_by is None


# ── Entailment Application ───────────────────────────────────────────────────


class TestApplyEntailments:
    def test_entailment_supersedes(self) -> None:
        assertions = _make_assertions(2)
        entailments = [
            EntailmentResult(premise_idx=0, hypothesis_idx=1, label="entailment", confidence=0.9)
        ]
        result = apply_entailments(assertions, entailments)
        assert result[1].superseded_by == assertions[0].assertion_id
        assert result[0].superseded_by is None

    def test_contradiction_adds_tags(self) -> None:
        assertions = _make_assertions(2)
        entailments = [
            EntailmentResult(premise_idx=0, hypothesis_idx=1, label="contradiction", confidence=0.8)
        ]
        result = apply_entailments(assertions, entailments)
        assert result[0].superseded_by is None
        assert result[1].superseded_by is None
        assert f"contradicts:{assertions[0].assertion_id}" in result[1].tags
        assert f"contradicts:{assertions[1].assertion_id}" in result[0].tags

    def test_skips_already_superseded(self) -> None:
        assertions = _make_assertions(2)
        assertions[1] = assertions[1].model_copy(update={"superseded_by": "existing_id"})
        entailments = [
            EntailmentResult(premise_idx=0, hypothesis_idx=1, label="entailment", confidence=0.9)
        ]
        result = apply_entailments(assertions, entailments)
        assert result[1].superseded_by == "existing_id"


# ── Full Pipeline ────────────────────────────────────────────────────────────


class TestRunNormalizationPipeline:
    @pytest.mark.asyncio
    async def test_dedup_only(self) -> None:
        assertions = [
            Assertion(
                text="Tests MUST pass.",
                source_type=SourceType.CODE,
                source_uri="/a.py",
                confidence=0.9,
                assertion_type=AssertionType.CONSTRAINT,
            ),
            Assertion(
                text="tests must pass",
                source_type=SourceType.CODE,
                source_uri="/b.py",
                confidence=0.7,
                assertion_type=AssertionType.CONSTRAINT,
            ),
            Assertion(
                text="never push directly",
                source_type=SourceType.MARKDOWN,
                source_uri="/c.md",
                confidence=0.85,
                assertion_type=AssertionType.CONSTRAINT,
            ),
        ]
        # First two are identical after normalization — give them identical embeddings
        embeddings = [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

        result = await run_normalization_pipeline(assertions, embeddings, skip_nli=True)
        assert result.total_input == 3
        assert result.total_superseded == 1
        assert len(result.duplicate_groups) == 1
        # Higher confidence wins
        superseded = [a for a in result.assertions if a.superseded_by is not None]
        assert len(superseded) == 1
        assert superseded[0].confidence == 0.7

    @pytest.mark.asyncio
    async def test_with_nli(self) -> None:
        assertions = _make_assertions(3)
        # Embeddings: 0 and 1 are in NLI range (0.7-0.85), 2 is far
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.8, 0.6, 0.0]  # cosine with v1 ~ 0.8
        v3 = [0.0, 0.0, 1.0]
        embeddings = [v1, v2, v3]

        with patch(
            "shared.assertion_normalizer.classify_entailment_batch",
            new_callable=AsyncMock,
            return_value=[("entailment", 0.9)],
        ):
            result = await run_normalization_pipeline(assertions, embeddings, skip_nli=False)
        assert result.total_superseded == 1
        assert len(result.entailments) == 1
