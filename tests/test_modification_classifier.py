"""Tests for the modification classifier."""

from __future__ import annotations

from shared.modification_classifier import (
    ModificationClass,
    classify_diff,
    classify_path,
    classify_paths,
    has_never_modify,
)


class TestClassifyPath:
    # NEVER_MODIFY paths.
    def test_health_monitor(self):
        assert classify_path("agents/health_monitor.py") == ModificationClass.NEVER_MODIFY

    def test_alert_state(self):
        assert classify_path("shared/alert_state.py") == ModificationClass.NEVER_MODIFY

    def test_axiom_enforcement(self):
        assert classify_path("shared/axiom_enforcement.py") == ModificationClass.NEVER_MODIFY

    def test_config(self):
        assert classify_path("shared/config.py") == ModificationClass.NEVER_MODIFY

    def test_axioms_dir(self):
        assert classify_path("axioms/registry.yaml") == ModificationClass.NEVER_MODIFY

    def test_hooks(self):
        assert classify_path("hooks/pre-commit") == ModificationClass.NEVER_MODIFY

    def test_systemd(self):
        assert classify_path("systemd/hapax-voice.service") == ModificationClass.NEVER_MODIFY

    def test_backup_scripts(self):
        assert classify_path("hapax-backup-local.sh") == ModificationClass.NEVER_MODIFY

    def test_github_workflows(self):
        assert classify_path(".github/workflows/ci.yml") == ModificationClass.NEVER_MODIFY

    # REVIEW_REQUIRED paths.
    def test_agent_code(self):
        assert classify_path("agents/scout.py") == ModificationClass.REVIEW_REQUIRED

    def test_shared_code(self):
        assert classify_path("shared/sdlc_github.py") == ModificationClass.REVIEW_REQUIRED

    def test_test_files(self):
        assert classify_path("tests/test_scout.py") == ModificationClass.REVIEW_REQUIRED

    def test_scripts(self):
        assert classify_path("scripts/sdlc_triage.py") == ModificationClass.REVIEW_REQUIRED

    def test_pyproject(self):
        assert classify_path("pyproject.toml") == ModificationClass.REVIEW_REQUIRED

    # AUTO_FIX paths.
    def test_docs(self):
        assert classify_path("docs/architecture.md") == ModificationClass.AUTO_FIX

    def test_readme(self):
        assert classify_path("README.md") == ModificationClass.AUTO_FIX

    def test_txt(self):
        assert classify_path("CHANGELOG.txt") == ModificationClass.AUTO_FIX


class TestClassifyPaths:
    def test_most_restrictive_wins(self):
        paths = ["docs/readme.md", "agents/scout.py", "shared/config.py"]
        assert classify_paths(paths) == ModificationClass.NEVER_MODIFY

    def test_review_beats_auto(self):
        paths = ["docs/readme.md", "agents/scout.py"]
        assert classify_paths(paths) == ModificationClass.REVIEW_REQUIRED

    def test_all_auto(self):
        paths = ["docs/readme.md", "docs/plan.md"]
        assert classify_paths(paths) == ModificationClass.AUTO_FIX

    def test_empty_paths(self):
        assert classify_paths([]) == ModificationClass.AUTO_FIX


class TestClassifyDiff:
    def test_diff_with_protected_path(self):
        diff = """\
--- a/shared/config.py
+++ b/shared/config.py
@@ -1,3 +1,4 @@
 import os
+import sys
"""
        assert classify_diff(diff) == ModificationClass.NEVER_MODIFY

    def test_diff_with_agent_code(self):
        diff = """\
--- a/agents/scout.py
+++ b/agents/scout.py
@@ -1,3 +1,4 @@
 import os
+import sys
"""
        assert classify_diff(diff) == ModificationClass.REVIEW_REQUIRED

    def test_diff_doc_only(self):
        diff = """\
--- a/docs/plan.md
+++ b/docs/plan.md
@@ -1,3 +1,4 @@
 # Plan
+New content
"""
        assert classify_diff(diff) == ModificationClass.AUTO_FIX


class TestHasNeverModify:
    def test_detects_protected(self):
        paths = ["agents/scout.py", "shared/config.py", "docs/readme.md"]
        result = has_never_modify(paths)
        assert result == ["shared/config.py"]

    def test_no_protected(self):
        paths = ["agents/scout.py", "docs/readme.md"]
        assert has_never_modify(paths) == []
