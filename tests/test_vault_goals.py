"""Tests for logos.data.vault_goals — Obsidian vault goal collector."""

from __future__ import annotations

import os
import time
from pathlib import Path

import yaml

from logos.data.vault_goals import collect_vault_goals


def _write_goal(tmp_path: Path, name: str, **overrides: object) -> Path:
    """Create a goal note with YAML frontmatter in tmp_path."""
    fm: dict[str, object] = {
        "type": "goal",
        "title": name.replace("-", " ").title(),
        "domain": "research",
        "status": "active",
        "priority": "P1",
        "started_at": "2026-01-15",
        "target_date": "2026-06-30",
        "sprint_measures": [],
        "depends_on": [],
        "tags": ["test"],
    }
    fm.update(overrides)
    content = (
        f"---\n{yaml.dump(fm, default_flow_style=False)}---\n\n# {fm['title']}\n\nGoal body.\n"
    )
    path = tmp_path / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return path


class TestVaultGoalsEmpty:
    def test_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        result = collect_vault_goals(vault_base=tmp_path, vault_name="Test")
        assert result == []

    def test_no_markdown_files(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("not a markdown file")
        result = collect_vault_goals(vault_base=tmp_path, vault_name="Test")
        assert result == []


class TestVaultGoalsFiltering:
    def test_non_goal_notes_ignored(self, tmp_path: Path) -> None:
        fm = {"type": "note", "title": "Just a note", "domain": "research"}
        content = f"---\n{yaml.dump(fm)}---\n\nSome note.\n"
        (tmp_path / "not-a-goal.md").write_text(content, encoding="utf-8")
        result = collect_vault_goals(vault_base=tmp_path, vault_name="Test")
        assert result == []

    def test_domain_filter(self, tmp_path: Path) -> None:
        _write_goal(tmp_path, "research-goal", domain="research")
        _write_goal(tmp_path, "studio-goal", domain="studio")
        result = collect_vault_goals(
            vault_base=tmp_path, vault_name="Test", domain_filter="research"
        )
        assert len(result) == 1
        assert result[0].domain == "research"


class TestVaultGoalsParsing:
    def test_single_goal_parsed_correctly(self, tmp_path: Path) -> None:
        _write_goal(
            tmp_path,
            "bayesian-validation",
            title="Bayesian Validation",
            domain="research",
            status="active",
            priority="P0",
            started_at="2026-03-30",
            target_date="2026-04-20",
            sprint_measures=["measure-a", "measure-b"],
            depends_on=["other-goal"],
            tags=["bayesian", "sprint"],
        )
        result = collect_vault_goals(vault_base=tmp_path, vault_name="Test")
        assert len(result) == 1
        g = result[0]
        assert g.id == "bayesian-validation"
        assert g.title == "Bayesian Validation"
        assert g.domain == "research"
        assert g.status == "active"
        assert g.priority == "P0"
        assert g.started_at == "2026-03-30"
        assert g.target_date == "2026-04-20"
        assert g.sprint_measures == ["measure-a", "measure-b"]
        assert g.depends_on == ["other-goal"]
        assert g.tags == ["bayesian", "sprint"]
        assert g.file_path == tmp_path / "bayesian-validation.md"

    def test_obsidian_uri_generated(self, tmp_path: Path) -> None:
        _write_goal(tmp_path, "my-goal")
        result = collect_vault_goals(vault_base=tmp_path, vault_name="MyVault")
        assert len(result) == 1
        assert result[0].obsidian_uri == "obsidian://open?vault=MyVault&file=my-goal"

    def test_obsidian_uri_subdirectory(self, tmp_path: Path) -> None:
        subdir = tmp_path / "goals" / "research"
        subdir.mkdir(parents=True)
        _write_goal(subdir, "deep-goal")
        # Move the file into the subdir (already there from _write_goal)
        result = collect_vault_goals(vault_base=tmp_path, vault_name="V")
        assert len(result) == 1
        assert result[0].obsidian_uri == "obsidian://open?vault=V&file=goals/research/deep-goal"


class TestVaultGoalsStaleness:
    def test_fresh_file_not_stale(self, tmp_path: Path) -> None:
        _write_goal(tmp_path, "fresh-goal", domain="research")
        result = collect_vault_goals(
            vault_base=tmp_path,
            vault_name="Test",
            staleness_days={"research": 7},
        )
        assert len(result) == 1
        assert result[0].stale is False

    def test_old_file_is_stale(self, tmp_path: Path) -> None:
        path = _write_goal(tmp_path, "old-goal", domain="research")
        # Set mtime to 30 days ago
        old_time = time.time() - (30 * 86400)
        os.utime(path, (old_time, old_time))
        result = collect_vault_goals(
            vault_base=tmp_path,
            vault_name="Test",
            staleness_days={"research": 7},
        )
        assert len(result) == 1
        assert result[0].stale is True


class TestVaultGoalsSprintProgress:
    def test_sprint_progress_computed(self, tmp_path: Path) -> None:
        _write_goal(
            tmp_path,
            "sprint-goal",
            sprint_measures=["m1", "m2", "m3"],
        )
        statuses = {"m1": "completed", "m2": "completed", "m3": "pending"}
        result = collect_vault_goals(
            vault_base=tmp_path,
            vault_name="Test",
            sprint_measure_statuses=statuses,
        )
        assert len(result) == 1
        assert abs(result[0].progress - 2.0 / 3.0) < 0.01

    def test_no_measures_progress_none(self, tmp_path: Path) -> None:
        _write_goal(tmp_path, "no-measures", sprint_measures=[])
        result = collect_vault_goals(vault_base=tmp_path, vault_name="Test")
        assert len(result) == 1
        assert result[0].progress is None


class TestVaultGoalsRobustness:
    def test_malformed_frontmatter_skipped(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad-goal.md"
        bad.write_text("---\n: : : invalid yaml\n---\n\nBody\n", encoding="utf-8")
        _write_goal(tmp_path, "good-goal")
        result = collect_vault_goals(vault_base=tmp_path, vault_name="Test")
        assert len(result) == 1
        assert result[0].id == "good-goal"

    def test_subdirectory_scanning(self, tmp_path: Path) -> None:
        subdir = tmp_path / "nested" / "deep"
        subdir.mkdir(parents=True)
        _write_goal(subdir, "nested-goal")
        _write_goal(tmp_path, "top-goal")
        result = collect_vault_goals(vault_base=tmp_path, vault_name="Test")
        assert len(result) == 2
        ids = {g.id for g in result}
        assert ids == {"nested-goal", "top-goal"}


class TestVaultGoalsSorting:
    def test_sorted_by_priority_then_mtime(self, tmp_path: Path) -> None:
        _write_goal(tmp_path, "low-priority", priority="P2")
        _write_goal(tmp_path, "high-priority", priority="P0")
        p1 = _write_goal(tmp_path, "mid-priority", priority="P1")
        # Make p1 most recently modified
        time.sleep(0.05)
        p1.write_text(p1.read_text(), encoding="utf-8")
        result = collect_vault_goals(vault_base=tmp_path, vault_name="Test")
        assert len(result) == 3
        assert result[0].priority == "P0"
        assert result[1].priority == "P1"
        assert result[2].priority == "P2"
