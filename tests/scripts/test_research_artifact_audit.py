"""Tests for the research artifact disposition audit script."""

from __future__ import annotations

from pathlib import Path

from scripts.hapax_research_artifact_audit import (
    _classify_artifact,
    _parse_frontmatter,
    scan_markdown_dir,
)


def test_parse_frontmatter_with_yaml():
    content = "---\nStatus: ready\nDate: 2026-05-15\nTask: foo-bar\n---\n\n# Title"
    fm = _parse_frontmatter(content)
    assert fm["status"] == "ready"
    assert fm["date"] == "2026-05-15"
    assert fm["task"] == "foo-bar"


def test_parse_frontmatter_missing():
    content = "# Title\n\nNo frontmatter here."
    fm = _parse_frontmatter(content)
    assert fm == {}


def test_classify_fully_attributed():
    fm = {"status": "ready", "date": "2026-05-15", "task": "foo"}
    assert _classify_artifact(fm, True) == "fully-attributed"


def test_classify_no_task():
    fm = {"status": "ready", "date": "2026-05-15"}
    assert _classify_artifact(fm, True) == "attributed-no-task"


def test_classify_date_only():
    fm = {"date": "2026-05-15"}
    assert _classify_artifact(fm, True) == "date-only"


def test_classify_missing_frontmatter():
    assert _classify_artifact({}, False) == "missing-frontmatter"


def test_scan_markdown_dir(tmp_path: Path):
    (tmp_path / "good.md").write_text("---\nStatus: done\nDate: 2026-01-01\nTask: t1\n---\n# Good")
    (tmp_path / "bare.md").write_text("# No frontmatter")
    entries = scan_markdown_dir(tmp_path, "test")
    assert len(entries) == 2
    good = next(e for e in entries if e.file == "good.md")
    bare = next(e for e in entries if e.file == "bare.md")
    assert good.disposition == "fully-attributed"
    assert bare.disposition == "missing-frontmatter"
