"""Tests for the axiom + pattern bundle loaders."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hapax_axioms import (
    Axiom,
    AxiomBundle,
    Pattern,
    PatternBundle,
    bundled_axioms_path,
    bundled_patterns_path,
    load_axioms,
    load_patterns,
)

CANONICAL_AXIOM_IDS = {
    "single_user",
    "executive_function",
    "management_governance",
    "interpersonal_transparency",
    "corporate_boundary",
}


def test_load_axioms_returns_validated_bundle() -> None:
    bundle = load_axioms()
    assert isinstance(bundle, AxiomBundle)
    assert bundle.schema_version
    assert bundle.snapshot_date
    assert bundle.source_repo.startswith("https://github.com/hapax-systems/")
    assert {ax.id for ax in bundle.axioms} == CANONICAL_AXIOM_IDS


def test_axiom_weights_match_constitution_snapshot() -> None:
    by_id = {ax.id: ax for ax in load_axioms().axioms}
    assert by_id["single_user"].weight == 100
    assert by_id["executive_function"].weight == 95
    assert by_id["corporate_boundary"].weight == 90
    assert by_id["interpersonal_transparency"].weight == 88
    assert by_id["management_governance"].weight == 85


def test_axiom_scope_constitutional_vs_domain() -> None:
    by_id = {ax.id: ax for ax in load_axioms().axioms}
    assert by_id["single_user"].scope == "constitutional"
    assert by_id["executive_function"].scope == "constitutional"
    assert by_id["interpersonal_transparency"].scope == "constitutional"
    assert by_id["management_governance"].scope == "domain"
    assert by_id["management_governance"].domain == "management"
    assert by_id["corporate_boundary"].scope == "domain"


def test_load_patterns_returns_validated_bundle() -> None:
    bundle = load_patterns()
    assert isinstance(bundle, PatternBundle)
    assert bundle.patterns, "expected at least one bundled pattern"
    for pat in bundle.patterns:
        assert isinstance(pat, Pattern)
        assert pat.tier == "T0"


def test_pattern_axiom_ids_subset_of_axiom_bundle() -> None:
    axiom_ids = {ax.id for ax in load_axioms().axioms}
    for pat in load_patterns().patterns:
        assert pat.axiom_id in axiom_ids, f"pattern {pat.id} cites unknown axiom {pat.axiom_id}"


def test_bundled_paths_exist() -> None:
    assert bundled_axioms_path().is_file()
    assert bundled_patterns_path().is_file()


def test_load_axioms_explicit_path(tmp_path: Path) -> None:
    yaml_doc = textwrap.dedent(
        """\
        schema_version: "1-0-0"
        source_repo: "https://example.invalid/test"
        snapshot_date: "2026-01-01"
        axioms:
          - id: test_axiom
            text: "test"
            weight: 50
            type: hardcoded
            created: "2026-01-01"
            status: active
            scope: constitutional
        """,
    )
    p = tmp_path / "ax.yaml"
    p.write_text(yaml_doc, encoding="utf-8")
    bundle = load_axioms(path=p)
    assert [ax.id for ax in bundle.axioms] == ["test_axiom"]
    assert bundle.axioms[0].weight == 50


def test_load_axioms_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_doc = textwrap.dedent(
        """\
        schema_version: "1-0-0"
        source_repo: "https://example.invalid/test"
        snapshot_date: "2026-01-01"
        axioms: []
        """,
    )
    p = tmp_path / "ax-env.yaml"
    p.write_text(yaml_doc, encoding="utf-8")
    monkeypatch.setenv("HAPAX_AXIOMS_PATH", str(p))
    bundle = load_axioms()
    assert bundle.axioms == []


def test_load_axioms_explicit_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_axioms(path=tmp_path / "does-not-exist.yaml")


def test_axiom_model_validates_weight_bounds() -> None:
    with pytest.raises(ValueError):
        Axiom(
            id="bad",
            text="x",
            weight=999,
            type="hardcoded",
            created="2026-01-01",
            status="active",
            scope="constitutional",
        )
