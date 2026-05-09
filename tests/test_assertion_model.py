"""Tests for shared.assertion_model — Unb-AIRy discursive plane data model."""

from __future__ import annotations

from pathlib import Path

from shared.assertion_model import (
    Assertion,
    AssertionType,
    ProvenanceRecord,
    SourceType,
    extract_from_axiom_registry,
    extract_from_implications,
)


class TestAssertionModel:
    def test_assertion_generates_id(self) -> None:
        a = Assertion(
            text="test assertion",
            source_type=SourceType.CODE,
            source_uri="test.py",
            assertion_type=AssertionType.FACT,
        )
        assert a.assertion_id
        assert len(a.assertion_id) == 16

    def test_same_content_same_id(self) -> None:
        a1 = Assertion(
            text="test",
            source_type=SourceType.CODE,
            source_uri="a.py",
            assertion_type=AssertionType.FACT,
        )
        a2 = Assertion(
            text="test",
            source_type=SourceType.CODE,
            source_uri="a.py",
            assertion_type=AssertionType.FACT,
        )
        assert a1.assertion_id == a2.assertion_id

    def test_different_content_different_id(self) -> None:
        a1 = Assertion(
            text="alpha",
            source_type=SourceType.CODE,
            source_uri="a.py",
            assertion_type=AssertionType.FACT,
        )
        a2 = Assertion(
            text="beta",
            source_type=SourceType.CODE,
            source_uri="a.py",
            assertion_type=AssertionType.FACT,
        )
        assert a1.assertion_id != a2.assertion_id

    def test_provenance_has_timestamp(self) -> None:
        p = ProvenanceRecord()
        assert p.extracted_at is not None

    def test_assertion_types_cover_taxonomy(self) -> None:
        expected = {
            "axiom",
            "implication",
            "invariant",
            "constraint",
            "preference",
            "fact",
            "goal",
            "decision",
            "claim",
            "corollary",
        }
        actual = {t.value for t in AssertionType}
        assert expected == actual

    def test_source_types_cover_corpus(self) -> None:
        expected = {
            "code",
            "config",
            "markdown",
            "governance",
            "commit",
            "pr",
            "memory",
            "relay",
            "task",
            "request",
        }
        actual = {t.value for t in SourceType}
        assert expected == actual


class TestAxiomExtraction:
    def test_extracts_from_registry(self) -> None:
        registry = Path("axioms/registry.yaml")
        if not registry.exists():
            return
        assertions = extract_from_axiom_registry(str(registry))
        assert len(assertions) >= 5
        assert all(a.assertion_type == AssertionType.AXIOM for a in assertions)
        assert all(a.source_type == SourceType.GOVERNANCE for a in assertions)
        assert all(a.domain == "constitutional" for a in assertions)

    def test_axioms_have_weight_tags(self) -> None:
        registry = Path("axioms/registry.yaml")
        if not registry.exists():
            return
        assertions = extract_from_axiom_registry(str(registry))
        for a in assertions:
            weight_tags = [t for t in a.tags if t.startswith("weight:")]
            assert len(weight_tags) == 1

    def test_returns_empty_for_missing_file(self) -> None:
        assertions = extract_from_axiom_registry("/nonexistent/path.yaml")
        assert assertions == []


class TestImplicationExtraction:
    def test_extracts_from_implications_dir(self) -> None:
        impl_dir = Path("axioms/implications")
        if not impl_dir.is_dir():
            impl_dir = Path("../hapax-constitution/axioms/implications")
        if not impl_dir.is_dir():
            return
        assertions = extract_from_implications(str(impl_dir))
        assert len(assertions) > 0
        assert all(a.assertion_type == AssertionType.IMPLICATION for a in assertions)

    def test_returns_empty_for_missing_dir(self) -> None:
        assertions = extract_from_implications("/nonexistent/dir")
        assert assertions == []
