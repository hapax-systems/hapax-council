"""Tests for scripts/migrate_native_tasks_to_vault.py.

Phase 2 of D-30 CC-task Obsidian SSOT plan. Tests the migration logic
in isolation against synthetic native task fixtures so the operator's
real ~/.claude/tasks store is never touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest  # noqa: TC002

from scripts.migrate_native_tasks_to_vault import (
    NativeTask,
    load_native_tasks,
    migrate,
    render_task_note,
    slugify,
    vault_note_path,
)


def _write_native_task(
    root: Path, list_id: str, task_id: str, *, status: str = "pending", subject: str = "Test task"
) -> None:
    """Write one synthetic native task JSON file under root/list_id/."""
    list_dir = root / list_id
    list_dir.mkdir(parents=True, exist_ok=True)
    (list_dir / f"{task_id}.json").write_text(
        json.dumps(
            {
                "id": task_id,
                "subject": subject,
                "description": f"Description for {subject}",
                "activeForm": f"Doing {subject}",
                "status": status,
                "blocks": [],
                "blockedBy": [],
            }
        )
    )


class TestSlugify:
    def test_lowercases(self) -> None:
        assert slugify("Hello World") == "hello-world"

    def test_collapses_non_alphanum(self) -> None:
        assert slugify("Hello, World!") == "hello-world"

    def test_strips_leading_trailing_hyphens(self) -> None:
        assert slugify("---hello---") == "hello"

    def test_truncates(self) -> None:
        assert len(slugify("a" * 200)) <= 50

    def test_empty_input(self) -> None:
        assert slugify("") == ""


class TestNativeTaskCompositeId:
    def test_padded_numeric_id(self) -> None:
        task = NativeTask(
            list_id="ef7bbda9-aaaa",
            raw_id="20",
            subject="x",
            description="",
            status="pending",
            blocks=[],
            blocked_by=[],
            file_mtime=0.0,
        )
        assert task.composite_id == "ef7b-020"

    def test_non_numeric_id_truncated(self) -> None:
        task = NativeTask(
            list_id="abcd1234-eeee",
            raw_id="weird-string-id",
            subject="x",
            description="",
            status="pending",
            blocks=[],
            blocked_by=[],
            file_mtime=0.0,
        )
        # Non-numeric IDs are truncated to 8 chars
        assert task.composite_id == "abcd-weird-st"


class TestStatusMapping:
    @pytest.mark.parametrize(
        "native_status,expected_vault,expected_folder",
        [
            ("pending", "offered", "active"),
            ("in_progress", "claimed", "active"),
            ("completed", "done", "closed"),
            ("cancelled", "withdrawn", "closed"),
        ],
    )
    def test_native_to_vault_status(
        self, native_status: str, expected_vault: str, expected_folder: str
    ) -> None:
        task = NativeTask(
            list_id="aaaa-bbbb",
            raw_id="1",
            subject="x",
            description="",
            status=native_status,
            blocks=[],
            blocked_by=[],
            file_mtime=0.0,
        )
        assert task.vault_status == expected_vault
        assert task.folder == expected_folder

    def test_unknown_status_falls_back_to_withdrawn(self) -> None:
        task = NativeTask(
            list_id="aaaa-bbbb",
            raw_id="1",
            subject="x",
            description="",
            status="unknown_state",
            blocks=[],
            blocked_by=[],
            file_mtime=0.0,
        )
        assert task.vault_status == "withdrawn"
        assert task.folder == "closed"


class TestLoadNativeTasks:
    def test_loads_all_status_values(self, tmp_path: Path) -> None:
        for i, status in enumerate(["pending", "in_progress", "completed", "cancelled"]):
            _write_native_task(tmp_path, "list-aaaa", str(i), status=status)
        tasks = load_native_tasks(tmp_path)
        assert len(tasks) == 4
        assert {t.status for t in tasks} == {
            "pending",
            "in_progress",
            "completed",
            "cancelled",
        }

    def test_skips_unreadable_json(self, tmp_path: Path) -> None:
        list_dir = tmp_path / "list-aaaa"
        list_dir.mkdir()
        (list_dir / "1.json").write_text("{not valid json")
        # Plus a valid one to confirm partial-recovery semantics.
        _write_native_task(tmp_path, "list-aaaa", "2")
        tasks = load_native_tasks(tmp_path)
        assert len(tasks) == 1  # only the valid task survived

    def test_empty_root_returns_empty(self, tmp_path: Path) -> None:
        assert load_native_tasks(tmp_path / "missing") == []


class TestMigrate:
    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        _write_native_task(tmp_path / "native", "list-aaaa", "1", subject="Foo")
        vault = tmp_path / "vault"
        counts = migrate(native_root=tmp_path / "native", vault_root=vault, apply=False)
        assert counts["loaded"] == 1
        assert counts["written"] == 1  # counted as "would write"
        # But nothing on disk:
        assert not (vault / "active").exists()

    def test_apply_writes_files(self, tmp_path: Path) -> None:
        _write_native_task(tmp_path / "native", "list-aaaa", "5", subject="Foo")
        _write_native_task(tmp_path / "native", "list-aaaa", "6", subject="Bar", status="completed")
        vault = tmp_path / "vault"
        counts = migrate(native_root=tmp_path / "native", vault_root=vault, apply=True)
        assert counts["written"] == 2
        active_files = list((vault / "active").glob("*.md"))
        closed_files = list((vault / "closed").glob("*.md"))
        assert len(active_files) == 1
        assert len(closed_files) == 1

    def test_idempotent_skips_existing(self, tmp_path: Path) -> None:
        _write_native_task(tmp_path / "native", "list-aaaa", "5")
        vault = tmp_path / "vault"
        # First run.
        c1 = migrate(native_root=tmp_path / "native", vault_root=vault, apply=True)
        assert c1["written"] == 1 and c1["skipped_existing"] == 0
        # Second run — same input, nothing should change.
        c2 = migrate(native_root=tmp_path / "native", vault_root=vault, apply=True)
        assert c2["written"] == 0 and c2["skipped_existing"] == 1

    def test_native_id_collision_across_lists_does_not_clobber(self, tmp_path: Path) -> None:
        """Native ID '1' exists in list A and list B; namespacing prefix
        keeps them as distinct vault notes."""
        _write_native_task(tmp_path / "native", "list-aaaa", "1", subject="Foo from A")
        _write_native_task(tmp_path / "native", "list-bbbb", "1", subject="Foo from B")
        vault = tmp_path / "vault"
        counts = migrate(native_root=tmp_path / "native", vault_root=vault, apply=True)
        assert counts["written"] == 2
        # Both files exist with distinct prefixes.
        active = sorted((vault / "active").glob("*.md"))
        assert len(active) == 2
        names = [p.name for p in active]
        assert any(n.startswith("list-001-") for n in names)


class TestRenderTaskNote:
    def test_renders_required_frontmatter_fields(self) -> None:
        task = NativeTask(
            list_id="ef7b-aaaa",
            raw_id="20",
            subject="Test subject",
            description="Some description.",
            status="pending",
            blocks=["21"],
            blocked_by=["18"],
            file_mtime=0.0,
        )
        body = render_task_note(task)
        assert "type: cc-task" in body
        assert "task_id: ef7b-020" in body
        assert "status: offered" in body
        assert "native_list: ef7b-aaaa" in body
        assert "native_id: 20" in body
        assert "blocks: " in body and '"21"' in body
        assert "depends_on: " in body and '"18"' in body
        assert "tags: [migrated-from-native]" in body
        assert "# Test subject" in body

    def test_completed_task_sets_completed_at(self) -> None:
        task = NativeTask(
            list_id="ef7b-aaaa",
            raw_id="20",
            subject="x",
            description="",
            status="completed",
            blocks=[],
            blocked_by=[],
            file_mtime=1234567890.0,
        )
        body = render_task_note(task)
        assert "completed_at: 2009-" in body  # 1234567890 = 2009-02-13


class TestVaultNotePath:
    def test_active_status_lands_in_active(self, tmp_path: Path) -> None:
        task = NativeTask(
            list_id="ef7b-aaaa",
            raw_id="20",
            subject="Hello World",
            description="",
            status="pending",
            blocks=[],
            blocked_by=[],
            file_mtime=0.0,
        )
        path = vault_note_path(tmp_path, task)
        assert path == tmp_path / "active" / "ef7b-020-hello-world.md"

    def test_closed_status_lands_in_closed(self, tmp_path: Path) -> None:
        task = NativeTask(
            list_id="ef7b-aaaa",
            raw_id="20",
            subject="Hello World",
            description="",
            status="completed",
            blocks=[],
            blocked_by=[],
            file_mtime=0.0,
        )
        path = vault_note_path(tmp_path, task)
        assert path == tmp_path / "closed" / "ef7b-020-hello-world.md"

    def test_no_subject_falls_back_to_default_slug(self, tmp_path: Path) -> None:
        task = NativeTask(
            list_id="ef7b-aaaa",
            raw_id="20",
            subject="",
            description="",
            status="pending",
            blocks=[],
            blocked_by=[],
            file_mtime=0.0,
        )
        path = vault_note_path(tmp_path, task)
        assert "no-subject" in path.name
