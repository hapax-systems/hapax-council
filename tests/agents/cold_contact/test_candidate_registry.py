"""Tests for ``agents.cold_contact.candidate_registry``."""

from __future__ import annotations

from pathlib import Path

from agents.cold_contact.candidate_registry import (
    AUDIENCE_VECTORS,
    CandidateEntry,
    load_candidate_registry,
)

_SAMPLE_YAML = """\
candidates:
  - name: "Wendy Chun"
    orcid: "0000-0001-2345-6789"
    audience_vectors: ["critical-ai", "infrastructure-studies"]
    topic_relevance: ["governance", "anti-anthropomorphization"]
  - name: "Yuk Hui"
    orcid: "0000-0002-3456-7890"
    audience_vectors: ["philosophy-of-tech"]
    topic_relevance: ["constitutional-design"]
"""


class TestCandidateEntry:
    def test_minimal_construction(self) -> None:
        entry = CandidateEntry(
            name="x",
            orcid="0000-0001-2345-6789",
            audience_vectors=[],
            topic_relevance=[],
        )
        assert entry.name == "x"

    def test_orcid_normalization_strips_url_prefix(self) -> None:
        entry = CandidateEntry(
            name="x",
            orcid="https://orcid.org/0000-0001-2345-6789",
            audience_vectors=[],
            topic_relevance=[],
        )
        assert entry.orcid == "0000-0001-2345-6789"

    def test_invalid_audience_vector_rejected(self) -> None:
        import pydantic  # noqa: TC002 — runtime fixture marker

        try:
            CandidateEntry(
                name="x",
                orcid="0000-0001-2345-6789",
                audience_vectors=["not-a-real-vector"],
                topic_relevance=[],
            )
        except pydantic.ValidationError:
            return
        raise AssertionError("Expected validation error on unknown audience vector")

    def test_known_audience_vector_accepted(self) -> None:
        entry = CandidateEntry(
            name="x",
            orcid="0000-0001-2345-6789",
            audience_vectors=["critical-ai"],
            topic_relevance=[],
        )
        assert "critical-ai" in entry.audience_vectors


class TestLoadCandidateRegistry:
    def test_loads_two_candidates(self, tmp_path: Path) -> None:
        path = tmp_path / "candidates.yaml"
        path.write_text(_SAMPLE_YAML)
        candidates = load_candidate_registry(path=path)
        assert len(candidates) == 2
        names = {c.name for c in candidates}
        assert names == {"Wendy Chun", "Yuk Hui"}

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        candidates = load_candidate_registry(path=tmp_path / "missing.yaml")
        assert candidates == []

    def test_empty_yaml_returns_empty_list(self, tmp_path: Path) -> None:
        path = tmp_path / "candidates.yaml"
        path.write_text("")
        candidates = load_candidate_registry(path=path)
        assert candidates == []

    def test_yaml_without_candidates_key_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "candidates.yaml"
        path.write_text("other_key: value\n")
        candidates = load_candidate_registry(path=path)
        assert candidates == []


class TestAudienceVectorsConstant:
    def test_contains_drop_2_required_vectors(self) -> None:
        # Drop 2 specifies these 16 audience vectors
        required = {
            "4e-cognition",
            "active-inference",
            "critical-ai",
            "infrastructure-studies",
            "philosophy-of-tech",
            "sound-art",
            "demoscene",
            "permacomputing",
            "crit-code-studies",
            "posthumanism",
            "ai-personhood-law",
            "practice-as-research",
            "listservs",
            "ai-consciousness",
        }
        for vector in required:
            assert vector in AUDIENCE_VECTORS, f"missing audience vector: {vector}"
        assert len(AUDIENCE_VECTORS) >= 14
