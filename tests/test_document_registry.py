"""Tests for shared/document_registry.py — registry loading and validation."""

from __future__ import annotations

import textwrap
from pathlib import Path

from shared.document_registry import (
    Archetype,
    CoverageRule,
    DocumentRegistry,
    MutualAwarenessRule,
    RepoDeclaration,
    load_registry,
)

MINIMAL_YAML = textwrap.dedent("""\
    version: 1
    archetypes:
      project-context:
        description: "Per-repo context"
        required_sections: ["## Project Memory"]
        composite: true
    repos:
      test-repo:
        path: ~/projects/test-repo
        required_docs:
          - path: CLAUDE.md
            archetype: project-context
    coverage_rules:
      - ci_type: agent
        reference_doc: "~/projects/test/system-context.md"
        match_by: name
        severity: medium
        description: "test rule"
    mutual_awareness:
      - type: repo_registry
        description: "test awareness"
        registry_doc: "~/projects/test/CLAUDE.md"
        registry_section: "## Related Repos"
        severity: medium
""")


def test_load_registry_from_string():
    reg = load_registry(yaml_content=MINIMAL_YAML)
    assert isinstance(reg, DocumentRegistry)
    assert reg.version == 1


def test_archetypes_parsed():
    reg = load_registry(yaml_content=MINIMAL_YAML)
    assert "project-context" in reg.archetypes
    arch = reg.archetypes["project-context"]
    assert isinstance(arch, Archetype)
    assert arch.required_sections == ["## Project Memory"]
    assert arch.composite is True


def test_repos_parsed():
    reg = load_registry(yaml_content=MINIMAL_YAML)
    assert "test-repo" in reg.repos
    repo = reg.repos["test-repo"]
    assert isinstance(repo, RepoDeclaration)
    assert repo.path == "~/projects/test-repo"
    assert len(repo.required_docs) == 1
    assert repo.required_docs[0]["archetype"] == "project-context"


def test_coverage_rules_parsed():
    reg = load_registry(yaml_content=MINIMAL_YAML)
    assert len(reg.coverage_rules) == 1
    rule = reg.coverage_rules[0]
    assert isinstance(rule, CoverageRule)
    assert rule.ci_type == "agent"
    assert rule.severity == "medium"


def test_mutual_awareness_parsed():
    reg = load_registry(yaml_content=MINIMAL_YAML)
    assert len(reg.mutual_awareness) == 1
    ma = reg.mutual_awareness[0]
    assert isinstance(ma, MutualAwarenessRule)
    assert ma.type == "repo_registry"


def test_load_registry_from_file(tmp_path):
    p = tmp_path / "registry.yaml"
    p.write_text(MINIMAL_YAML)
    reg = load_registry(path=p)
    assert reg.version == 1
    assert "project-context" in reg.archetypes


def test_load_registry_missing_file():
    reg = load_registry(path=Path("/nonexistent/registry.yaml"))
    assert reg is None


def test_load_registry_invalid_yaml():
    reg = load_registry(yaml_content="[unterminated: {bad")
    assert reg is None
