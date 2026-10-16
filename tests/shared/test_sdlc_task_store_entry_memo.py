"""One process parses each unchanged task row once.

cc-claim resolves the task store five to six times per run, and each
resolution used to re-read and re-parse every row. The in-process entry memo
reuses a row's parsed entry while its full stat vector is unchanged, which is
the same reuse rule the frontier reconciliation already applies. These tests
pin that the memo saves the parses and never hides an edit.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import shared.sdlc_task_store as task_store
from shared.sdlc_task_store import TaskStoreError, build_task_identity_index


def _note(path: Path, task_id: str, *, status: str = "offered") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: cc-task\ntask_id: {task_id}\nstatus: {status}\n---\n\nbody\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _fresh_memo() -> None:
    task_store.clear_task_identity_entry_memo()
    yield
    task_store.clear_task_identity_entry_memo()


@pytest.fixture
def parse_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = task_store.parse_frontmatter_with_diagnostics

    def counting(text):  # type: ignore[no-untyped-def]
        calls.append(text)
        return real(text)

    monkeypatch.setattr(task_store, "parse_frontmatter_with_diagnostics", counting)
    return calls


def test_repeated_index_builds_parse_each_unchanged_row_once(
    tmp_path: Path, parse_calls: list[str]
) -> None:
    for number in range(5):
        _note(tmp_path / "active" / f"task-{number}.md", f"task-{number}")
    _note(tmp_path / "closed" / "task-done.md", "task-done", status="done")

    first = build_task_identity_index(tmp_path)
    for _ in range(4):
        again = build_task_identity_index(tmp_path)
        assert again.entries == first.entries

    assert len(parse_calls) == 6


def test_an_edit_between_builds_is_seen(tmp_path: Path) -> None:
    note = _note(tmp_path / "active" / "task-a.md", "task-a")
    before = build_task_identity_index(tmp_path)
    assert before.by_task_id["task-a"][0].task_id == "task-a"

    _note(note, "task-renamed")
    after = build_task_identity_index(tmp_path)

    assert "task-a" not in after.by_task_id
    assert after.by_task_id["task-renamed"][0].path == note.resolve()


def test_a_same_size_edit_is_seen(tmp_path: Path) -> None:
    note = _note(tmp_path / "active" / "task-a.md", "task-a", status="offered")
    before = build_task_identity_index(tmp_path)
    old = before.by_task_id["task-a"][0]
    stat = note.stat()

    _note(note, "task-b", status="offered")
    os.utime(note, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert note.stat().st_size == stat.st_size
    assert note.stat().st_mtime_ns == stat.st_mtime_ns
    after = build_task_identity_index(tmp_path)

    assert "task-a" not in after.by_task_id
    assert after.by_task_id["task-b"][0].content_sha256 != old.content_sha256


def test_unreadable_rows_are_not_memoized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _note(tmp_path / "active" / "task-a.md", "task-a")
    real = task_store._regular_file_bytes
    failures = {"left": 1}

    def flaky(path, *, reason_code):  # type: ignore[no-untyped-def]
        if failures["left"]:
            failures["left"] -= 1
            raise TaskStoreError(reason_code, "transient read failure", str(path))
        return real(path, reason_code=reason_code)

    monkeypatch.setattr(task_store, "_regular_file_bytes", flaky)
    first = build_task_identity_index(tmp_path)
    assert "task-a" not in first.by_task_id

    second = build_task_identity_index(tmp_path)
    assert second.by_task_id["task-a"][0].task_id == "task-a"


def test_a_frontier_change_during_a_build_still_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _note(tmp_path / "active" / "task-a.md", "task-a")
    build_task_identity_index(tmp_path)

    real = task_store._complete_frontier
    calls = {"count": 0}

    def drifting(vault_root):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        frontier = real(vault_root)
        if calls["count"] >= 2:
            _note(
                vault_root / "active" / f"task-new-{calls['count']}.md",
                f"task-new-{calls['count']}",
            )
            frontier = real(vault_root)
        return frontier

    monkeypatch.setattr(task_store, "_complete_frontier", drifting)
    with pytest.raises(TaskStoreError, match="task_store_frontier_changed_during_index_build"):
        build_task_identity_index(tmp_path)


def test_the_memo_stays_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(task_store, "_TASK_IDENTITY_ENTRY_MEMO_MAX", 3)
    for number in range(5):
        _note(tmp_path / "active" / f"task-{number}.md", f"task-{number}")

    build_task_identity_index(tmp_path)

    assert len(task_store._TASK_IDENTITY_ENTRY_MEMO) <= 3
