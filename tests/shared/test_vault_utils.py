"""Tests for shared.vault_utils.parse_frontmatter.

36-LOC YAML-frontmatter parser for Obsidian vault markdown files.
Untested before this commit. The function is fail-open: any parse
problem (missing file, missing/unclosed markers, invalid YAML,
non-dict YAML) returns an empty dict.
"""

from __future__ import annotations

from pathlib import Path

from shared.vault_utils import parse_frontmatter

# ── Missing / unreadable input ─────────────────────────────────────


class TestMissingInput:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert parse_frontmatter(tmp_path / "nope.md") == {}

    def test_directory_path_returns_empty(self, tmp_path: Path) -> None:
        """OSError on read_text(directory) is swallowed → {}."""
        d = tmp_path / "subdir"
        d.mkdir()
        assert parse_frontmatter(d) == {}


# ── Marker structure ──────────────────────────────────────────────


class TestMarkerStructure:
    def test_no_opening_marker_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "no-fm.md"
        path.write_text("# Just a heading\n\nbody")
        assert parse_frontmatter(path) == {}

    def test_no_closing_marker_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "open-only.md"
        path.write_text("---\nname: test\nbody starts here without closing\n")
        assert parse_frontmatter(path) == {}

    def test_empty_frontmatter_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.md"
        path.write_text("---\n---\n# body\n")
        assert parse_frontmatter(path) == {}


# ── YAML parsing ──────────────────────────────────────────────────


class TestYamlParsing:
    def test_well_formed_frontmatter(self, tmp_path: Path) -> None:
        path = tmp_path / "ok.md"
        path.write_text(
            "---\nname: alpha\npriority: p1\ntags:\n  - cc-task\n  - audio\n---\n# body\n"
        )
        result = parse_frontmatter(path)
        assert result == {
            "name": "alpha",
            "priority": "p1",
            "tags": ["cc-task", "audio"],
        }

    def test_invalid_yaml_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.md"
        path.write_text("---\n: : : : invalid\n---\n")
        assert parse_frontmatter(path) == {}

    def test_non_dict_yaml_returns_empty(self, tmp_path: Path) -> None:
        """When the YAML root is a list (or anything other than a dict),
        the function returns {} — not the raw value."""
        path = tmp_path / "list.md"
        path.write_text("---\n- one\n- two\n---\n")
        assert parse_frontmatter(path) == {}

    def test_string_yaml_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "str.md"
        path.write_text("---\njust a string\n---\n")
        assert parse_frontmatter(path) == {}


# ── Real-world shapes ─────────────────────────────────────────────


class TestRealWorldShapes:
    def test_cc_task_frontmatter_parses(self, tmp_path: Path) -> None:
        """Smoke test against the cc-task frontmatter shape used
        throughout 20-projects/hapax-cc-tasks/."""
        path = tmp_path / "cc-task.md"
        path.write_text(
            "---\n"
            "type: cc-task\n"
            "task_id: voice-output-router-semantic-api\n"
            "status: claimed\n"
            "assigned_to: beta\n"
            "wsjf: 8.0\n"
            "depends_on: []\n"
            "braid_schema: 1.1\n"
            "---\n"
            "# body\n"
        )
        result = parse_frontmatter(path)
        assert result["type"] == "cc-task"
        assert result["status"] == "claimed"
        assert result["assigned_to"] == "beta"
        assert result["wsjf"] == 8.0
        assert result["depends_on"] == []
        assert result["braid_schema"] == 1.1
