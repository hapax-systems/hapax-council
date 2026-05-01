"""Tests for shared.modification_classifier.

85-LOC file-path classifier (AUTO_FIX / REVIEW_REQUIRED /
NEVER_MODIFY). Enforces the safety boundary: oversight systems are
never auto-modified. Untested before this commit.
"""

from __future__ import annotations

import pytest

from shared.modification_classifier import (
    CLASSIFICATION_RULES,
    ModificationClass,
    classify_diff,
    classify_path,
    classify_paths,
    has_never_modify,
)

# ── classify_path: NEVER_MODIFY paths ──────────────────────────────


class TestNeverModify:
    @pytest.mark.parametrize(
        "path",
        [
            "agents/health_monitor.py",
            "shared/alert_state.py",
            "shared/axiom_enforcement.py",
            "shared/axiom_registry.py",
            "shared/axiom_tools.py",
            "shared/config.py",
            "axioms/registry.yaml",
            "axioms/implications/single-user.yaml",
            "hooks/scripts/pii-guard.sh",
            "systemd/units/hapax-daimonion.service",
            "hapax-backup-2026-04-01.sh",
            ".github/workflows/ci.yml",
        ],
    )
    def test_oversight_paths_never_modify(self, path: str) -> None:
        assert classify_path(path) == ModificationClass.NEVER_MODIFY


# ── classify_path: REVIEW_REQUIRED paths ───────────────────────────


class TestReviewRequired:
    @pytest.mark.parametrize(
        "path",
        [
            "agents/briefing.py",  # not a NEVER_MODIFY
            "shared/cli.py",  # not a NEVER_MODIFY
            "logos/api/routes/orientation.py",
            "scripts/hapax-codex",
            "tests/shared/test_cli.py",
            "configs/litellm.yaml",
            "pyproject.toml",
        ],
    )
    def test_application_paths_review_required(self, path: str) -> None:
        assert classify_path(path) == ModificationClass.REVIEW_REQUIRED


# ── classify_path: AUTO_FIX paths ──────────────────────────────────


class TestAutoFix:
    @pytest.mark.parametrize(
        "path",
        [
            "docs/research/2026-04-24-grounding.md",
            "README.md",
            "CHANGELOG.txt",
            "notes.md",
        ],
    )
    def test_doc_paths_auto_fix(self, path: str) -> None:
        assert classify_path(path) == ModificationClass.AUTO_FIX


# ── classify_path: ordering / specificity ──────────────────────────


class TestRuleOrdering:
    def test_axiom_tools_is_never_not_review(self) -> None:
        """shared/axiom_tools.py matches NEVER_MODIFY first; the broader
        shared/* REVIEW_REQUIRED rule does not get a chance to apply."""
        assert classify_path("shared/axiom_tools.py") == ModificationClass.NEVER_MODIFY

    def test_unknown_path_defaults_to_review(self) -> None:
        """Unrecognised paths return REVIEW_REQUIRED (safe default)."""
        assert (
            classify_path("rogue/random/file.py") == ModificationClass.REVIEW_REQUIRED
        )

    def test_md_in_subdir_falls_through_to_md_pattern(self) -> None:
        """A loose .md file (no agents/shared/etc. prefix) hits the
        general *.md AUTO_FIX rule."""
        assert classify_path("loose-notes.md") == ModificationClass.AUTO_FIX


# ── classify_paths: most-restrictive-wins ──────────────────────────


class TestClassifyPaths:
    def test_empty_list_is_auto_fix(self) -> None:
        """No paths means no restrictions — auto-fix is permitted."""
        assert classify_paths([]) == ModificationClass.AUTO_FIX

    def test_returns_most_restrictive_when_mixed(self) -> None:
        paths = [
            "docs/note.md",
            "agents/briefing.py",
            "shared/config.py",  # NEVER_MODIFY
        ]
        assert classify_paths(paths) == ModificationClass.NEVER_MODIFY

    def test_review_when_all_review_or_auto(self) -> None:
        paths = ["docs/note.md", "agents/briefing.py"]
        assert classify_paths(paths) == ModificationClass.REVIEW_REQUIRED

    def test_auto_fix_when_only_docs(self) -> None:
        paths = ["docs/a.md", "docs/b.md", "README.md"]
        assert classify_paths(paths) == ModificationClass.AUTO_FIX


# ── classify_diff: parse unified diff ──────────────────────────────


class TestClassifyDiff:
    def test_extracts_paths_from_diff_headers(self) -> None:
        diff = (
            "diff --git a/agents/briefing.py b/agents/briefing.py\n"
            "index e69de29..2f4d2e4 100644\n"
            "--- a/agents/briefing.py\n"
            "+++ b/agents/briefing.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+x\n"
        )
        assert classify_diff(diff) == ModificationClass.REVIEW_REQUIRED

    def test_dev_null_paths_excluded(self) -> None:
        """A new-file diff has --- /dev/null; that's not classified."""
        diff = (
            "--- /dev/null\n"
            "+++ b/docs/new.md\n"
            "@@ -0,0 +1 @@\n"
            "+hi\n"
        )
        # The only real path is docs/new.md → auto-fix
        assert classify_diff(diff) == ModificationClass.AUTO_FIX

    def test_multifile_diff_returns_most_restrictive(self) -> None:
        diff = (
            "--- a/docs/x.md\n"
            "+++ b/docs/x.md\n"
            "--- a/shared/config.py\n"
            "+++ b/shared/config.py\n"
        )
        assert classify_diff(diff) == ModificationClass.NEVER_MODIFY

    def test_empty_diff_returns_auto_fix(self) -> None:
        """No diff headers parsed → empty path list → AUTO_FIX default."""
        assert classify_diff("") == ModificationClass.AUTO_FIX


# ── has_never_modify ──────────────────────────────────────────────


class TestHasNeverModify:
    def test_returns_only_never_paths(self) -> None:
        paths = [
            "docs/x.md",
            "shared/config.py",  # NEVER
            "agents/briefing.py",
            "axioms/registry.yaml",  # NEVER
        ]
        result = has_never_modify(paths)
        assert set(result) == {"shared/config.py", "axioms/registry.yaml"}

    def test_empty_when_none_match(self) -> None:
        assert has_never_modify(["docs/x.md", "agents/briefing.py"]) == []


# ── Constant pinning ──────────────────────────────────────────────


class TestConstants:
    def test_classification_rules_non_empty(self) -> None:
        assert len(CLASSIFICATION_RULES) > 0

    def test_class_enum_values(self) -> None:
        assert ModificationClass.AUTO_FIX.value == "auto_fix"
        assert ModificationClass.REVIEW_REQUIRED.value == "review_required"
        assert ModificationClass.NEVER_MODIFY.value == "never_modify"
