"""Tests for scripts/audit_spec_shipped_footers.py.

Auditor closes the D-31 audit-loop gap: specs lack "Shipped in"
footers. Tests verify the detection regex + age parsing + footer
rendering against synthetic fixture specs.
"""

from __future__ import annotations

from pathlib import Path

from scripts.audit_spec_shipped_footers import (
    SpecAuditEntry,
    audit_specs,
    has_shipped_footer,
    parse_spec_date,
    render_footer_suggestion,
)


def _write_spec(specs_dir: Path, name: str, body: str = "## Some content\n") -> Path:
    """Write one synthetic spec under specs_dir."""
    specs_dir.mkdir(parents=True, exist_ok=True)
    path = specs_dir / name
    path.write_text(body)
    return path


class TestParseSpecDate:
    def test_well_formed_filename(self) -> None:
        path = Path("/tmp/2026-04-18-foo-design.md")
        date_str, age = parse_spec_date(path)
        assert date_str == "2026-04-18"
        assert age >= 0  # post-2026-04-18 → non-negative

    def test_missing_date_prefix(self) -> None:
        path = Path("/tmp/no-date-here.md")
        date_str, age = parse_spec_date(path)
        assert date_str == "unknown"
        assert age == -1

    def test_invalid_date_components(self) -> None:
        path = Path("/tmp/2026-99-99-foo.md")
        date_str, _ = parse_spec_date(path)
        # Captured but invalid — age stays -1
        assert "2026-99-99" in date_str


class TestHasShippedFooter:
    def test_with_commit_sha(self, tmp_path: Path) -> None:
        path = _write_spec(
            tmp_path,
            "2026-04-18-x-design.md",
            "Body.\n\n## Shipped in\n\n- `abc123def`\n",
        )
        assert has_shipped_footer(path)

    def test_with_pr_number(self, tmp_path: Path) -> None:
        path = _write_spec(
            tmp_path,
            "2026-04-18-y-design.md",
            "Body.\n\nShipped in PR #1234.\n",
        )
        assert has_shipped_footer(path)

    def test_case_insensitive(self, tmp_path: Path) -> None:
        path = _write_spec(
            tmp_path,
            "2026-04-18-z-design.md",
            "Body. shipped in `abc1234`.\n",
        )
        assert has_shipped_footer(path)

    def test_missing_footer(self, tmp_path: Path) -> None:
        path = _write_spec(tmp_path, "2026-04-18-no-footer.md", "Just body.\n")
        assert not has_shipped_footer(path)

    def test_word_shipped_alone_does_not_count(self, tmp_path: Path) -> None:
        """Just the word 'shipped' without 'in <ref>' is not a footer."""
        path = _write_spec(
            tmp_path,
            "2026-04-18-bare-shipped.md",
            "This was shipped but the ref is elsewhere.\n",
        )
        assert not has_shipped_footer(path)


class TestAuditSpecs:
    def test_audits_all_specs(self, tmp_path: Path) -> None:
        _write_spec(tmp_path, "2026-04-18-with-footer-design.md", "## Shipped in `abc1234`")
        _write_spec(tmp_path, "2026-04-19-no-footer-design.md", "Body.")
        _write_spec(tmp_path, "2026-04-20-no-footer-design.md", "Body.")
        entries = audit_specs(tmp_path, since_days=1)  # tight window → no candidates
        assert len(entries) == 3
        with_footer = [e for e in entries if e.has_footer]
        assert len(with_footer) == 1
        assert with_footer[0].path.name == "2026-04-18-with-footer-design.md"

    def test_pattern_filter(self, tmp_path: Path) -> None:
        _write_spec(tmp_path, "2026-04-18-keep-design.md", "Body.")
        _write_spec(tmp_path, "2026-04-19-drop-design.md", "Body.")
        entries = audit_specs(tmp_path, since_days=1, pattern="keep")
        assert len(entries) == 1
        assert "keep" in entries[0].path.name

    def test_sorted_by_age_descending(self, tmp_path: Path) -> None:
        _write_spec(tmp_path, "2026-04-19-newer-design.md", "Body.")
        _write_spec(tmp_path, "2026-04-15-older-design.md", "Body.")
        entries = audit_specs(tmp_path, since_days=1)
        # Older (higher age_days) should appear first
        assert entries[0].path.name == "2026-04-15-older-design.md"
        assert entries[1].path.name == "2026-04-19-newer-design.md"

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert audit_specs(tmp_path / "missing") == []


class TestSpecAuditEntryStemWords:
    def test_strips_date_prefix(self) -> None:
        entry = SpecAuditEntry(
            path=Path("/tmp/2026-04-18-camera-naming-classification-design.md"),
            has_footer=False,
            spec_date="2026-04-18",
            age_days=2,
            candidate_commits=[],
        )
        assert "2026" not in entry.spec_stem_words
        assert "camera" in entry.spec_stem_words
        assert "naming" in entry.spec_stem_words
        assert "classification" in entry.spec_stem_words

    def test_strips_design_suffix(self) -> None:
        entry = SpecAuditEntry(
            path=Path("/tmp/2026-04-18-x-design.md"),
            has_footer=False,
            spec_date="2026-04-18",
            age_days=2,
            candidate_commits=[],
        )
        assert "design" not in entry.spec_stem_words

    def test_strips_stop_words(self) -> None:
        entry = SpecAuditEntry(
            path=Path("/tmp/2026-04-18-the-and-of-a-foo-design.md"),
            has_footer=False,
            spec_date="2026-04-18",
            age_days=2,
            candidate_commits=[],
        )
        # Stop-words filtered: "the", "and", "of", "a"
        assert "the" not in entry.spec_stem_words
        assert "and" not in entry.spec_stem_words
        assert "foo" in entry.spec_stem_words


class TestRenderFooterSuggestion:
    def test_with_candidates(self) -> None:
        entry = SpecAuditEntry(
            path=Path("/tmp/x.md"),
            has_footer=False,
            spec_date="2026-04-18",
            age_days=2,
            candidate_commits=["abc1234", "def5678"],
        )
        rendered = render_footer_suggestion(entry)
        assert "## Shipped in" in rendered
        assert "abc1234" in rendered
        assert "def5678" in rendered

    def test_without_candidates(self) -> None:
        entry = SpecAuditEntry(
            path=Path("/tmp/x.md"),
            has_footer=False,
            spec_date="2026-04-18",
            age_days=2,
            candidate_commits=[],
        )
        rendered = render_footer_suggestion(entry)
        assert "## Shipped in" in rendered
        assert "fill in manually" in rendered.lower()
