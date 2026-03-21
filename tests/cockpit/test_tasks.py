"""Tests for cockpit/data/tasks.py — task management via filesystem-as-bus."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from cockpit.data.tasks import (
    Task,
    _parse_task,
    collect_tasks,
    create_task,
    get_task,
    save_task,
    update_task_status,
)


def _make_task_file(tmpdir: Path, task_id: str, **overrides) -> Path:
    fm = {
        "id": task_id,
        "title": overrides.get("title", f"Task {task_id}"),
        "status": overrides.get("status", "pending"),
        "priority": overrides.get("priority", "medium"),
        "created": overrides.get("created", "2026-03-21"),
        "updated": overrides.get("updated", "2026-03-21T12:00:00+00:00"),
    }
    for k, v in overrides.items():
        if k not in fm:
            fm[k] = v
    content = "---\n" + yaml.dump(fm, default_flow_style=False) + "---\n"
    path = tmpdir / f"{task_id}.md"
    path.write_text(content)
    return path


class TestParseTask:
    def test_valid_task(self, tmp_path):
        path = _make_task_file(tmp_path, "test-1", title="Test Task", priority="high")
        task = _parse_task(path)
        assert task is not None
        assert task.id == "test-1"
        assert task.title == "Test Task"
        assert task.priority == "high"

    def test_missing_frontmatter(self, tmp_path):
        path = tmp_path / "bad.md"
        path.write_text("No frontmatter here")
        assert _parse_task(path) is None

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "bad.md"
        path.write_text("---\n: invalid: yaml: [[\n---\n")
        assert _parse_task(path) is None


class TestCollectTasks:
    def test_empty_directory(self, tmp_path):
        with patch("cockpit.data.tasks._TASKS_DIR", tmp_path):
            snapshot = collect_tasks()
            assert snapshot.tasks == []
            assert snapshot.pending_count == 0

    def test_multiple_tasks(self, tmp_path):
        _make_task_file(tmp_path, "t1", status="pending")
        _make_task_file(tmp_path, "t2", status="active")
        _make_task_file(tmp_path, "t3", status="done")
        _make_task_file(tmp_path, "t4", status="blocked")
        with patch("cockpit.data.tasks._TASKS_DIR", tmp_path):
            snapshot = collect_tasks()
            assert len(snapshot.tasks) == 4
            assert snapshot.pending_count == 1
            assert snapshot.active_count == 1
            assert snapshot.done_count == 1
            assert snapshot.blocked_count == 1


class TestSaveAndGetTask:
    def test_round_trip(self, tmp_path):
        with patch("cockpit.data.tasks._TASKS_DIR", tmp_path):
            task = Task(
                id="round-trip", title="Round Trip Test", status="active",
                priority="high", created="2026-03-21", updated="2026-03-21T12:00:00+00:00",
                phase="B", tags=["grounding", "data-collection"], github_issue=42,
            )
            save_task(task)
            loaded = get_task("round-trip")
            assert loaded is not None
            assert loaded.title == "Round Trip Test"
            assert loaded.status == "active"
            assert loaded.phase == "B"
            assert loaded.tags == ["grounding", "data-collection"]
            assert loaded.github_issue == 42


class TestCreateTask:
    def test_creates_file(self, tmp_path):
        with patch("cockpit.data.tasks._TASKS_DIR", tmp_path):
            task = create_task("Run session 14", priority="high", phase="B")
            assert task.id == "run-session-14"
            assert task.status == "pending"
            assert task.priority == "high"
            assert (tmp_path / "run-session-14.md").exists()


class TestUpdateStatus:
    def test_updates_status(self, tmp_path):
        _make_task_file(tmp_path, "update-me", status="pending")
        with patch("cockpit.data.tasks._TASKS_DIR", tmp_path):
            task = update_task_status("update-me", "active")
            assert task is not None
            assert task.status == "active"
            reloaded = get_task("update-me")
            assert reloaded is not None
            assert reloaded.status == "active"

    def test_invalid_status_returns_none(self, tmp_path):
        _make_task_file(tmp_path, "bad-status", status="pending")
        with patch("cockpit.data.tasks._TASKS_DIR", tmp_path):
            assert update_task_status("bad-status", "invalid") is None

    def test_missing_task_returns_none(self, tmp_path):
        with patch("cockpit.data.tasks._TASKS_DIR", tmp_path):
            assert update_task_status("nonexistent", "active") is None
