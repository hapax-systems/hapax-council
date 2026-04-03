"""Tests for shared/registry_checks.py — document registry enforcement."""

from __future__ import annotations

import textwrap
from unittest.mock import patch

import pytest

from agents.drift_detector import DriftItem
from shared.document_registry import load_registry
from shared.registry_checks import (
    check_archetype_sections,
    check_coverage_rules,
    check_document_registry,
    check_mutual_awareness,
    check_required_docs,
)

REGISTRY_YAML = textwrap.dedent("""\
    version: 1
    archetypes:
      project-context:
        description: "Per-repo context"
        required_sections: ["## Project Memory", "## Conventions"]
        composite: true
    repos:
      test-repo:
        path: {tmpdir}/test-repo
        required_docs:
          - path: CLAUDE.md
            archetype: project-context
          - path: README.md
            archetype: project-context
    coverage_rules:
      - ci_type: agent
        reference_doc: "{tmpdir}/system-context.md"
        reference_section: "## Agents"
        match_by: name
        severity: medium
        description: "agents in system-context"
    mutual_awareness:
      - type: repo_registry
        description: "repos in registry"
        registry_doc: "{tmpdir}/registry-doc.md"
        registry_section: "## Related Repos"
        severity: medium
      - type: spec_reference
        description: "repos reference hapaxromana"
        target_phrase: "hapaxromana"
        severity: low
      - type: byte_identical
        description: "boundary must match"
        docs:
          - "{tmpdir}/boundary-a.md"
          - "{tmpdir}/boundary-b.md"
        severity: high
""")


@pytest.fixture
def registry_env(tmp_path):
    """Set up a minimal filesystem for registry checks."""
    # Create repo with CLAUDE.md (has Project Memory but no Conventions)
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("# Test\n\n## Project Memory\nStuff here\n")
    # README.md missing — should be detected

    # System-context doc with one agent listed
    (tmp_path / "system-context.md").write_text("# System\n\n## Agents\n| briefing | yes |\n")

    # Registry doc for mutual awareness
    (tmp_path / "registry-doc.md").write_text("# Main\n\n## Related Repos\n| test-repo | desc |\n")

    # Boundary docs — different content
    (tmp_path / "boundary-a.md").write_text("Version A content")
    (tmp_path / "boundary-b.md").write_text("Version B content")

    yaml_text = REGISTRY_YAML.replace("{tmpdir}", str(tmp_path))
    reg = load_registry(yaml_content=yaml_text)
    return reg, tmp_path


class TestCheckRequiredDocs:
    def test_detects_missing_doc(self, registry_env):
        reg, tmp_path = registry_env
        items = check_required_docs(reg)
        missing = [i for i in items if i.category == "missing-required-doc"]
        assert len(missing) == 1
        assert "README.md" in missing[0].doc_file

    def test_existing_doc_no_drift(self, registry_env):
        reg, tmp_path = registry_env
        # Create the missing README
        (tmp_path / "test-repo" / "README.md").write_text(
            "# Readme\n\n## Project Memory\n\n## Conventions\n"
        )
        items = check_required_docs(reg)
        missing = [i for i in items if i.category == "missing-required-doc"]
        assert len(missing) == 0


class TestCheckArchetypeSections:
    def test_detects_missing_section(self, registry_env):
        reg, tmp_path = registry_env
        items = check_archetype_sections(reg)
        missing = [i for i in items if i.category == "missing-section"]
        # CLAUDE.md has ## Project Memory but not ## Conventions
        assert any("Conventions" in i.reality for i in missing)

    def test_all_sections_present(self, registry_env):
        reg, tmp_path = registry_env
        (tmp_path / "test-repo" / "CLAUDE.md").write_text(
            "# Test\n\n## Project Memory\nstuff\n\n## Conventions\nmore stuff\n"
        )
        items = check_archetype_sections(reg)
        missing = [i for i in items if "test-repo/CLAUDE.md" in i.doc_file]
        assert len(missing) == 0


class TestCheckCoverageRules:
    def test_detects_undocumented_agent(self, registry_env):
        reg, tmp_path = registry_env
        # briefing is documented, drift-detector is not
        agents = ["briefing", "drift-detector"]
        items = check_coverage_rules(reg, discovered_cis={"agent": agents})
        gaps = [i for i in items if i.category == "coverage-gap"]
        assert any("drift-detector" in i.reality for i in gaps)
        assert not any("briefing" in i.reality for i in gaps)

    def test_no_gaps_when_all_documented(self, registry_env):
        reg, tmp_path = registry_env
        agents = ["briefing"]
        items = check_coverage_rules(reg, discovered_cis={"agent": agents})
        gaps = [i for i in items if i.category == "coverage-gap"]
        assert len(gaps) == 0

    def test_exclude_patterns_skip_matching_cis(self, registry_env):
        reg, tmp_path = registry_env
        # Add exclude_patterns to the coverage rule
        reg.coverage_rules[0].exclude_patterns = ["*-sync", "demo*"]
        agents = ["briefing", "chrome-sync", "gdrive-sync", "demo", "demo-eval"]
        items = check_coverage_rules(reg, discovered_cis={"agent": agents})
        gaps = [i for i in items if i.category == "coverage-gap"]
        # chrome-sync, gdrive-sync excluded by *-sync; demo, demo-eval excluded by demo*
        # briefing is in the doc → 0 gaps
        assert len(gaps) == 0

    def test_exclude_patterns_only_skip_matches(self, registry_env):
        reg, tmp_path = registry_env
        reg.coverage_rules[0].exclude_patterns = ["*-sync"]
        agents = ["briefing", "chrome-sync", "drift-detector"]
        items = check_coverage_rules(reg, discovered_cis={"agent": agents})
        gaps = [i for i in items if i.category == "coverage-gap"]
        # chrome-sync excluded, briefing in doc, drift-detector not excluded and not in doc
        assert len(gaps) == 1
        assert "drift-detector" in gaps[0].reality


class TestCheckMutualAwareness:
    def test_byte_identical_mismatch(self, registry_env):
        reg, tmp_path = registry_env
        items = check_mutual_awareness(reg)
        boundary = [i for i in items if i.category == "boundary-mismatch"]
        assert len(boundary) == 1
        assert boundary[0].severity == "high"

    def test_byte_identical_match(self, registry_env):
        reg, tmp_path = registry_env
        (tmp_path / "boundary-b.md").write_text("Version A content")
        items = check_mutual_awareness(reg)
        boundary = [i for i in items if i.category == "boundary-mismatch"]
        assert len(boundary) == 0

    def test_spec_reference_gap(self, registry_env):
        reg, tmp_path = registry_env
        # CLAUDE.md doesn't mention hapaxromana
        items = check_mutual_awareness(reg, known_repos={"test-repo": tmp_path / "test-repo"})
        spec_gaps = [i for i in items if i.category == "spec-reference-gap"]
        assert len(spec_gaps) == 1


class TestCheckDocumentRegistryIntegration:
    @patch("shared.registry_checks.discover_agents", return_value=["briefing", "drift-detector"])
    @patch("shared.registry_checks.discover_timers", return_value=[])
    @patch("shared.registry_checks.discover_services", return_value=[])
    @patch("shared.registry_checks.discover_repos", return_value=["test-repo"])
    @patch("shared.registry_checks.discover_mcp_servers", return_value=[])
    def test_full_check(
        self, mock_mcp, mock_repos, mock_svcs, mock_timers, mock_agents, registry_env
    ):
        reg, tmp_path = registry_env
        items = check_document_registry(registry=reg)
        assert isinstance(items, list)
        assert all(isinstance(i, DriftItem) for i in items)
        # Should find: missing README, missing Conventions section,
        # drift-detector coverage gap, boundary mismatch, spec reference gap
        categories = {i.category for i in items}
        assert "missing-required-doc" in categories
        assert "coverage-gap" in categories
        assert "boundary-mismatch" in categories
