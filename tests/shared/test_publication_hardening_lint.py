"""Tests for publication hardening lint — Vale style + heading hierarchy."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from shared.publication_hardening.lint import (
    check_heading_hierarchy,
    lint_file,
    run_vale,
)

TESTS_DIR = Path(__file__).resolve().parent.parent
VALE_DIR = TESTS_DIR / "vale"
REPO_ROOT = TESTS_DIR.parent
VALE_INI = REPO_ROOT / ".vale.ini"

requires_vale = pytest.mark.skipif(
    shutil.which("vale") is None,
    reason="vale binary not installed",
)


class TestHeadingHierarchy:
    def test_valid_hierarchy(self, tmp_path: Path) -> None:
        doc = tmp_path / "good.md"
        doc.write_text("# H1\n\n## H2\n\n### H3\n\n#### H4\n")
        assert check_heading_hierarchy(doc) == []

    def test_skip_h2_to_h4(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.md"
        doc.write_text("# H1\n\n## H2\n\n#### Skipped H4\n")
        findings = check_heading_hierarchy(doc)
        assert len(findings) == 1
        assert findings[0].level == "error"
        assert findings[0].rule == "Hapax.HeadingHierarchy"
        assert "h2 to h4" in findings[0].message

    def test_skip_h1_to_h3(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.md"
        doc.write_text("# Title\n\n### Skipped\n")
        findings = check_heading_hierarchy(doc)
        assert len(findings) == 1
        assert "h1 to h3" in findings[0].message

    def test_skip_h1_to_h4(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.md"
        doc.write_text("# Title\n\n#### Deep Skip\n")
        findings = check_heading_hierarchy(doc)
        assert len(findings) == 1
        assert "h1 to h4" in findings[0].message

    def test_multiple_skips(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.md"
        doc.write_text("# Title\n\n### Skip 1\n\n##### Skip 2\n")
        findings = check_heading_hierarchy(doc)
        assert len(findings) == 2

    def test_h2_start_no_skip(self, tmp_path: Path) -> None:
        doc = tmp_path / "good.md"
        doc.write_text("## Section\n\n### Subsection\n")
        assert check_heading_hierarchy(doc) == []

    def test_decrease_not_flagged(self, tmp_path: Path) -> None:
        doc = tmp_path / "good.md"
        doc.write_text("# Title\n\n## Section\n\n### Sub\n\n## Back to H2\n")
        assert check_heading_hierarchy(doc) == []


@requires_vale
class TestValeIntegration:
    def test_sample_pass_clean(self) -> None:
        sample = VALE_DIR / "sample_pass.md"
        if not sample.exists():
            return
        findings = run_vale(sample, config=VALE_INI)
        errors = [f for f in findings if f.level == "error"]
        assert errors == [], f"Pass sample should have no errors: {errors}"

    def test_sample_fail_has_errors(self) -> None:
        sample = VALE_DIR / "sample_fail.md"
        if not sample.exists():
            return
        findings = run_vale(sample, config=VALE_INI)
        errors = [f for f in findings if f.level == "error"]
        assert len(errors) > 0, "Fail sample should have errors"

    def test_banned_terms_caught(self, tmp_path: Path) -> None:
        doc = tmp_path / "banned.md"
        doc.write_text("# Test\n\nWe leverage synergies to utilize best practices.\n")
        findings = run_vale(doc, config=VALE_INI)
        rules = {f.rule for f in findings}
        assert "Hapax.BannedTerms" in rules

    def test_clean_text_passes(self, tmp_path: Path) -> None:
        doc = tmp_path / "clean.md"
        doc.write_text("# Test\n\nThis is a short, clear sentence. It explains something simply.\n")
        findings = run_vale(doc, config=VALE_INI)
        errors = [f for f in findings if f.level == "error"]
        assert errors == []


@requires_vale
class TestLintFile:
    def test_combines_vale_and_heading_checks(self, tmp_path: Path) -> None:
        doc = tmp_path / "combined.md"
        doc.write_text("# Title\n\n#### Skip\n\nWe leverage synergies.\n")
        findings = lint_file(doc, config=VALE_INI)
        rules = {f.rule for f in findings}
        assert "Hapax.HeadingHierarchy" in rules

    def test_clean_file_no_findings(self, tmp_path: Path) -> None:
        doc = tmp_path / "clean.md"
        doc.write_text("# Title\n\n## Section\n\nClear, simple text.\n")
        findings = lint_file(doc, config=VALE_INI)
        errors = [f for f in findings if f.level == "error"]
        assert errors == []
