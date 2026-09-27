"""Tests for shared.prose_assertion_extractor."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared.assertion_model import AssertionType, GovernanceStatus, SourceType
from shared.prose_assertion_extractor import (
    ProcessedState,
    extract_from_claude_md,
    extract_from_directory,
    extract_from_directory_resumable,
    extract_from_memory_file,
    extract_from_obsidian_note,
    extract_from_relay_artifact,
)


def _write_md(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestClaudeMdExtraction:
    def test_alias_uses_canonical_provenance(self, tmp_path: Path) -> None:
        canonical = _write_md(tmp_path, "AGENTS.md", "MUST preserve canonical policy.\n")
        alias = tmp_path / "CLAUDE.md"
        alias.symlink_to("AGENTS.md")

        canonical_results = extract_from_claude_md(canonical)
        alias_results = extract_from_claude_md(alias)

        assert len(alias_results) == 1
        assert alias_results[0].source_uri == str(canonical.resolve())
        assert alias_results[0].assertion_id == canonical_results[0].assertion_id

    def test_must_directive(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "CLAUDE.md",
            "# Rules\n\n- Tests MUST pass before merging.\n",
        )
        results = extract_from_claude_md(p)
        assert len(results) == 1
        assert "MUST" in results[0].text
        assert results[0].source_type == SourceType.MARKDOWN
        assert results[0].assertion_type == AssertionType.CONSTRAINT
        assert results[0].provenance.extraction_method == "prose_claude_md_deontic"
        assert "keyword:MUST" in results[0].tags

    def test_never_directive(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "CLAUDE.md",
            "NEVER push directly to main.\n",
        )
        results = extract_from_claude_md(p)
        assert len(results) == 1
        assert "NEVER" in results[0].text
        assert "keyword:NEVER" in results[0].tags

    def test_always_directive(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "CLAUDE.md",
            "- ALWAYS run tests before committing.\n",
        )
        results = extract_from_claude_md(p)
        assert len(results) == 1
        assert "ALWAYS" in results[0].text

    def test_mandatory_directive(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "CLAUDE.md",
            "Code review is MANDATORY for all PRs.\n",
        )
        results = extract_from_claude_md(p)
        assert len(results) == 1
        assert "MANDATORY" in results[0].text

    def test_protected_directive(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "CLAUDE.md",
            "## Audio Routing — PROTECTED INVARIANTS\n",
        )
        results = extract_from_claude_md(p)
        assert len(results) == 1
        assert "PROTECTED" in results[0].text

    def test_multiple_directives(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "CLAUDE.md",
            "- MUST validate input.\n- NEVER skip tests.\n- ALWAYS log errors.\n",
        )
        results = extract_from_claude_md(p)
        assert len(results) == 3

    def test_no_directives(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "CLAUDE.md",
            "# Project\n\nThis is a normal project.\n",
        )
        results = extract_from_claude_md(p)
        assert len(results) == 0

    def test_lowercase_ignored(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "CLAUDE.md",
            "You must do this.\n",
        )
        results = extract_from_claude_md(p)
        assert len(results) == 0

    def test_confidence(self, tmp_path: Path) -> None:
        p = _write_md(tmp_path, "CLAUDE.md", "MUST validate.\n")
        results = extract_from_claude_md(p)
        assert results[0].confidence == 0.85

    def test_frontmatter_skipped(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "CLAUDE.md",
            "---\ntitle: MUST not extract this\n---\n\nMUST extract this.\n",
        )
        results = extract_from_claude_md(p)
        assert len(results) == 1
        assert "extract this" in results[0].text
        assert "title" not in results[0].text

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        p = tmp_path / "missing.md"
        assert extract_from_claude_md(p) == []

    def test_source_span_set(self, tmp_path: Path) -> None:
        p = _write_md(tmp_path, "CLAUDE.md", "line one\nMUST do something.\n")
        results = extract_from_claude_md(p)
        assert results[0].source_span is not None
        assert results[0].source_span[0] >= 1

    def test_whitespace_normalized(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "CLAUDE.md",
            "-  MUST   validate    input   carefully.\n",
        )
        results = extract_from_claude_md(p)
        assert "  " not in results[0].text


class TestMemoryExtraction:
    def test_feedback_memory(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "feedback_testing.md",
            "---\nname: testing\ndescription: Always run tests\ntype: feedback\n---\n\n"
            "Always run tests before committing.\n\n"
            "**Why:** Broken commits waste CI time.\n\n"
            "**How to apply:** Run pytest before git commit.\n",
        )
        results = extract_from_memory_file(p)
        assert len(results) == 3

        rule = results[0]
        assert rule.assertion_type == AssertionType.PREFERENCE
        assert rule.source_type == SourceType.MEMORY
        assert "Always run tests" in rule.text
        assert rule.confidence == 0.9
        assert "memory_name:testing" in rule.tags

        why = results[1]
        assert why.assertion_type == AssertionType.FACT
        assert "CI time" in why.text
        assert "section:why" in why.tags

        how = results[2]
        assert how.assertion_type == AssertionType.CONSTRAINT
        assert "pytest" in how.text
        assert "section:how_to_apply" in how.tags

    def test_non_feedback_type_skipped(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "user_role.md",
            "---\nname: role\ndescription: User role\ntype: user\n---\n\n"
            "The user is a developer.\n",
        )
        results = extract_from_memory_file(p)
        assert len(results) == 0

    def test_no_frontmatter_skipped(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "random.md",
            "Some random markdown content.\n",
        )
        results = extract_from_memory_file(p)
        assert len(results) == 0

    def test_empty_body_skipped(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "feedback_empty.md",
            "---\nname: empty\ndescription: Empty\ntype: feedback\n---\n",
        )
        results = extract_from_memory_file(p)
        assert len(results) == 0

    def test_rule_only_no_why_how(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "feedback_simple.md",
            "---\nname: simple\ndescription: Simple rule\ntype: feedback\n---\n\n"
            "Do not use mocks in integration tests.\n",
        )
        results = extract_from_memory_file(p)
        assert len(results) == 1
        assert results[0].assertion_type == AssertionType.PREFERENCE

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        p = tmp_path / "missing.md"
        assert extract_from_memory_file(p) == []

    def test_description_in_tags(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "feedback_desc.md",
            "---\nname: desc_test\ndescription: Check descriptions\ntype: feedback\n---\n\n"
            "Some rule.\n",
        )
        results = extract_from_memory_file(p)
        assert any("description:" in t for t in results[0].tags)

    def test_extraction_method(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "feedback_method.md",
            "---\nname: method\ndescription: Method test\ntype: feedback\n---\n\nThe rule.\n",
        )
        results = extract_from_memory_file(p)
        assert results[0].provenance.extraction_method == "prose_memory_feedback"


class TestRelayExtraction:
    def test_decision_section(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "relay-artifact.md",
            "# Some Research\n\n"
            "Background info here.\n\n"
            "## 5. Decision — CONSOLIDATE-FIRST\n\n"
            "Reason: the two parallel modules are both live. "
            "Consolidation must happen before the flip.\n\n"
            "## 6. Next steps\n\nDo the thing.\n",
        )
        results = extract_from_relay_artifact(p)
        assert len(results) == 1
        assert results[0].assertion_type == AssertionType.DECISION
        assert "consolidation" in results[0].text.lower()
        assert results[0].confidence == 0.85
        assert "section_type:decision" in results[0].tags

    def test_finding_section(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "research.md",
            "# Report\n\n## Finding\n\nThe system processes 500 requests per second under load.\n",
        )
        results = extract_from_relay_artifact(p)
        assert len(results) == 1
        assert results[0].assertion_type == AssertionType.CLAIM
        assert results[0].confidence == 0.75

    def test_claim_section(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "analysis.md",
            "# Analysis\n\n"
            "### Claim: Architecture is sound\n\n"
            "The architecture satisfies all requirements from the spec.\n",
        )
        results = extract_from_relay_artifact(p)
        assert len(results) == 1
        assert results[0].assertion_type == AssertionType.CLAIM

    def test_ship_spec_section(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "ship.md",
            "# Work\n\n"
            "## SHIP spec (after consolidation)\n\n"
            "Delete duplicates and update imports across the codebase.\n",
        )
        results = extract_from_relay_artifact(p)
        assert len(results) == 1
        assert results[0].assertion_type == AssertionType.DECISION

    def test_conclusion_section(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "report.md",
            "# Study\n\n## Conclusion\n\nThe hypothesis is supported by the evidence gathered.\n",
        )
        results = extract_from_relay_artifact(p)
        assert len(results) == 1
        assert results[0].assertion_type == AssertionType.DECISION

    def test_multiple_sections(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "multi.md",
            "# Report\n\n"
            "## Finding\n\nSignificant result from the experiment.\n\n"
            "## Decision\n\nProceed with option A based on findings.\n",
        )
        results = extract_from_relay_artifact(p)
        assert len(results) == 2

    def test_no_matching_sections(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "normal.md",
            "# Guide\n\n## Setup\n\nInstall dependencies.\n\n## Usage\n\nRun the app.\n",
        )
        results = extract_from_relay_artifact(p)
        assert len(results) == 0

    def test_empty_section_skipped(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "empty-decision.md",
            "# Work\n\n## Decision\n\n## Next\n\nSomething else.\n",
        )
        results = extract_from_relay_artifact(p)
        assert len(results) == 0

    def test_short_section_skipped(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "short.md",
            "# Work\n\n## Decision\n\nToo short\n",
        )
        results = extract_from_relay_artifact(p)
        assert len(results) == 0

    def test_frontmatter_not_extracted(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "with-fm.md",
            "---\ntitle: Decision about things\n---\n\n"
            "# Report\n\n## Finding\n\nThe actual finding is in the body.\n",
        )
        results = extract_from_relay_artifact(p)
        assert len(results) == 1
        assert "actual finding" in results[0].text

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        p = tmp_path / "missing.md"
        assert extract_from_relay_artifact(p) == []

    def test_source_span_set(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "span.md",
            "# Title\n\n## Decision\n\nThis is the decision text for the project.\n",
        )
        results = extract_from_relay_artifact(p)
        assert results[0].source_span is not None
        assert results[0].source_span[0] >= 1


class TestDirectoryExtraction:
    @pytest.mark.parametrize("resumable", [False, True])
    def test_authored_instruction_coverage(self, tmp_path: Path, resumable: bool) -> None:
        policies = {
            "council/AGENTS.md": "MUST preserve repository authority.",
            "council/config/agent-instructions/AGENTS.md": "NEVER bypass shared policy.",
            "council/config/agent-instructions/native/claude.md": "MUST retain native hooks.",
            "council/config/agent-instructions/native/grok.md": "MUST observe native limits.",
            "council/docs/runbooks/council-domain-context.md": "ALWAYS preserve domain rules.",
            "council/nested/AGENTS.md": "MUST observe nested scope.",
            "agents-only/AGENTS.md": "MUST include AGENTS-only repositories.",
            "legacy/CLAUDE.md": "MUST include legacy repositories.",
        }
        excluded = (
            "council/README.md",
            "council/docs/ordinary.md",
            "council/docs/runbooks/evidence/generated.md",
            "council/config/agent-instructions/evidence/generated.md",
            "council/config/agent-instructions/native/evidence/generated.md",
        )
        for relative, text in policies.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        for relative in excluded:
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("MUST NOT become an instruction assertion.\n", encoding="utf-8")
        (tmp_path / "council/CLAUDE.md").symlink_to("AGENTS.md")
        (tmp_path / "council/config/agent-instructions/native/alias.md").symlink_to("claude.md")

        reader = extract_from_directory_resumable if resumable else extract_from_directory
        results = reader(tmp_path, source_kind="claude_md")

        assert len(results) == len(policies)
        assert {result.source_uri: result.text for result in results} == {
            str((tmp_path / relative).resolve()): text for relative, text in policies.items()
        }
        assert all(result.governance_status == GovernanceStatus.AUTHORITATIVE for result in results)
        assert all(result.assertion_type == AssertionType.CONSTRAINT for result in results)

        if resumable:
            assert reader(tmp_path, source_kind="claude_md") == []
            state = ProcessedState(tmp_path / ".prose-extractor-processed.json")
            assert all(state.is_processed(tmp_path / relative) for relative in policies)
            assert not state.is_processed(tmp_path / "council/CLAUDE.md")
            assert all(not state.is_processed(tmp_path / relative) for relative in excluded)

            canonical = tmp_path / "council/AGENTS.md"
            modified = canonical.stat().st_mtime + 5
            canonical.write_text("MUST preserve revised repository authority.\n", encoding="utf-8")
            os.utime(canonical, (modified, modified))
            updated = reader(tmp_path, source_kind="claude_md")
            assert len(updated) == 1
            assert updated[0].source_uri == str(canonical.resolve())
            assert updated[0].text == "MUST preserve revised repository authority."
            assert reader(tmp_path, source_kind="claude_md") == []

    def test_claude_md_directory(self, tmp_path: Path) -> None:
        _write_md(tmp_path, "CLAUDE.md", "MUST validate.\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        _write_md(sub, "CLAUDE.md", "NEVER skip tests.\n")

        results = extract_from_directory(tmp_path, source_kind="claude_md")
        assert len(results) == 2

    def test_memory_directory(self, tmp_path: Path) -> None:
        _write_md(
            tmp_path,
            "feedback_a.md",
            "---\nname: a\ndescription: A\ntype: feedback\n---\n\nRule A.\n",
        )
        _write_md(
            tmp_path,
            "feedback_b.md",
            "---\nname: b\ndescription: B\ntype: feedback\n---\n\nRule B.\n",
        )
        _write_md(
            tmp_path,
            "user_c.md",
            "---\nname: c\ndescription: C\ntype: user\n---\n\nNot feedback.\n",
        )

        results = extract_from_directory(tmp_path, source_kind="memory")
        assert len(results) == 2

    def test_memory_directory_skips_memory_md(self, tmp_path: Path) -> None:
        _write_md(tmp_path, "MEMORY.md", "# Index\n- [A](a.md)\n")
        _write_md(
            tmp_path,
            "feedback_a.md",
            "---\nname: a\ndescription: A\ntype: feedback\n---\n\nRule A.\n",
        )
        results = extract_from_directory(tmp_path, source_kind="memory")
        assert len(results) == 1

    def test_relay_directory(self, tmp_path: Path) -> None:
        _write_md(
            tmp_path,
            "artifact.md",
            "# Report\n\n## Decision\n\nProceed with the implementation plan.\n",
        )
        results = extract_from_directory(tmp_path, source_kind="relay")
        assert len(results) == 1


class TestAssertionIdDeterminism:
    def test_ids_are_deterministic(self, tmp_path: Path) -> None:
        p = _write_md(tmp_path, "CLAUDE.md", "MUST validate input.\n")
        r1 = extract_from_claude_md(p)
        r2 = extract_from_claude_md(p)
        assert r1[0].assertion_id == r2[0].assertion_id
        assert len(r1[0].assertion_id) == 16

    def test_different_sources_different_ids(self, tmp_path: Path) -> None:
        p1 = _write_md(tmp_path, "CLAUDE.md", "MUST validate input.\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        p2 = _write_md(sub, "CLAUDE.md", "MUST validate input.\n")
        r1 = extract_from_claude_md(p1)
        r2 = extract_from_claude_md(p2)
        assert r1[0].assertion_id != r2[0].assertion_id


class TestGovernanceStatusOnClaudeMd:
    def test_claude_md_has_authoritative_governance(self, tmp_path: Path) -> None:
        p = _write_md(tmp_path, "CLAUDE.md", "MUST validate input.\n")
        results = extract_from_claude_md(p)
        assert results[0].governance_status == GovernanceStatus.AUTHORITATIVE


class TestObsidianExtraction:
    def test_deontic_extraction(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "note.md",
            "---\ntype: goal\n---\n\n# Goal\n\nMUST ship by Friday.\n",
        )
        results = extract_from_obsidian_note(p)
        assert len(results) == 1
        assert "MUST" in results[0].text
        assert results[0].governance_status == GovernanceStatus.DERIVED
        assert "vault_type:goal" in results[0].tags

    def test_decision_section(self, tmp_path: Path) -> None:
        p = _write_md(
            tmp_path,
            "research.md",
            "# Research\n\n## Decision\n\nProceed with the consolidated approach.\n",
        )
        results = extract_from_obsidian_note(p)
        assert any(r.assertion_type == AssertionType.DECISION for r in results)

    def test_no_extraction_from_plain_note(self, tmp_path: Path) -> None:
        p = _write_md(tmp_path, "daily.md", "# Daily Note\n\nHad coffee.\n")
        results = extract_from_obsidian_note(p)
        assert len(results) == 0


class TestResumableExtraction:
    def test_skips_already_processed(self, tmp_path: Path) -> None:
        _write_md(tmp_path, "a.md", "MUST do A.\n")
        _write_md(tmp_path, "b.md", "MUST do B.\n")
        r1 = extract_from_directory_resumable(tmp_path, source_kind="obsidian")
        assert len(r1) == 2
        r2 = extract_from_directory_resumable(tmp_path, source_kind="obsidian")
        assert len(r2) == 0

    def test_reprocesses_modified_file(self, tmp_path: Path) -> None:
        p = _write_md(tmp_path, "a.md", "MUST do A.\n")
        extract_from_directory_resumable(tmp_path, source_kind="obsidian")
        import time

        time.sleep(0.05)
        p.write_text("MUST do A v2.\nNEVER skip B.\n")
        r2 = extract_from_directory_resumable(tmp_path, source_kind="obsidian")
        assert len(r2) == 2

    def test_state_persists(self, tmp_path: Path) -> None:
        _write_md(tmp_path, "a.md", "MUST do A.\n")
        extract_from_directory_resumable(tmp_path, source_kind="obsidian")
        state = ProcessedState(tmp_path / ".prose-extractor-processed.json")
        assert state.is_processed(tmp_path / "a.md")
