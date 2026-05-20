"""Tests for shared.assertion_model — Unb-AIRy discursive plane data model."""

from __future__ import annotations

from pathlib import Path

from shared.assertion_model import (
    AIFNodeType,
    Assertion,
    AssertionType,
    GovernanceStatus,
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


class TestGovernanceAndAIFFields:
    def test_axioms_have_authoritative_governance_status(self) -> None:
        registry = Path("axioms/registry.yaml")
        if not registry.exists():
            return
        assertions = extract_from_axiom_registry(str(registry))
        assert len(assertions) >= 5
        assert all(a.governance_status == GovernanceStatus.AUTHORITATIVE for a in assertions)

    def test_implications_have_constitutional_governance_status(self) -> None:
        impl_dir = Path("axioms/implications")
        if not impl_dir.is_dir():
            impl_dir = Path("../hapax-constitution/axioms/implications")
        if not impl_dir.is_dir():
            return
        assertions = extract_from_implications(str(impl_dir))
        assert len(assertions) > 0
        assert all(a.governance_status == GovernanceStatus.CONSTITUTIONAL for a in assertions)

    def test_axioms_are_i_nodes(self) -> None:
        registry = Path("axioms/registry.yaml")
        if not registry.exists():
            return
        assertions = extract_from_axiom_registry(str(registry))
        assert all(a.aif_node_type == AIFNodeType.I_NODE for a in assertions)

    def test_assertion_roundtrip_serialization(self) -> None:
        a = Assertion(
            text="test roundtrip",
            source_type=SourceType.GOVERNANCE,
            source_uri="axioms/registry.yaml",
            assertion_type=AssertionType.AXIOM,
            governance_status=GovernanceStatus.AUTHORITATIVE,
            aif_node_type=AIFNodeType.I_NODE,
            confidence=0.95,
        )
        dumped = a.model_dump_json()
        restored = Assertion.model_validate_json(dumped)
        assert restored.assertion_id == a.assertion_id
        assert restored.text == a.text
        assert restored.governance_status == GovernanceStatus.AUTHORITATIVE
        assert restored.aif_node_type == AIFNodeType.I_NODE
        assert restored.confidence == 0.95

    def test_assertion_has_created_and_updated_timestamps(self) -> None:
        a = Assertion(
            text="timestamp test",
            source_type=SourceType.CODE,
            source_uri="test.py",
            assertion_type=AssertionType.FACT,
        )
        assert a.created_at is not None
        assert a.updated_at is not None
