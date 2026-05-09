"""Tests for ``scripts/cc-pr-merge-watcher.py`` (H9 — PR3 of cc-hygiene).

Per project convention, no shared conftest fixtures — each test builds
its own vault + cursor under ``tmp_path`` and injects a fake ``gh`` /
``cc-close`` runner into ``run_watcher()``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

# Ensure scripts/ is importable in tests.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _load_watcher_module() -> ModuleType:
    """Load ``scripts/cc-pr-merge-watcher.py`` despite the hyphenated filename."""
    if "cc_pr_merge_watcher" in sys.modules:
        return sys.modules["cc_pr_merge_watcher"]
    path = _SCRIPTS / "cc-pr-merge-watcher.py"
    spec = importlib.util.spec_from_file_location("cc_pr_merge_watcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["cc_pr_merge_watcher"] = module
    spec.loader.exec_module(module)
    return module


watcher = _load_watcher_module()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (vault / "active").mkdir(parents=True, exist_ok=True)
    (vault / "closed").mkdir(parents=True, exist_ok=True)
    return vault


def _write_note(vault: Path, *, task_id: str, pr: int | None) -> Path:
    pr_line = f"pr: {pr}" if pr is not None else "pr: null"
    note = vault / "active" / f"{task_id}-test.md"
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "x"
status: pr_open
{pr_line}
---

# {task_id}

## Session log
- fixture
"""
    )
    return note


class _FakeRunner:
    """Inject canned subprocess responses keyed by command prefix."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.gh_payload: list[dict[str, Any]] = []
        self.gh_returncode = 0
        self.cc_close_returncodes: list[int] = []  # consumed in order
        self.cc_close_invocations: list[list[str]] = []

    def __call__(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
        **_: Any,
    ) -> subprocess.CompletedProcess:
        self.calls.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=self.gh_returncode,
                stdout=json.dumps(self.gh_payload),
                stderr="",
            )
        # Anything else is cc-close.
        self.cc_close_invocations.append(list(cmd))
        rc = self.cc_close_returncodes.pop(0) if self.cc_close_returncodes else 0
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=rc,
            stdout=f"cc-close: {' '.join(cmd[1:])}\n",
            stderr="" if rc == 0 else f"cc-close error rc={rc}\n",
        )


# ---------------------------------------------------------------------------
# cursor helpers
# ---------------------------------------------------------------------------


class TestCursor:
    def test_default_cursor_when_missing(self, tmp_path: Path) -> None:
        cursor_path = tmp_path / "cursor.txt"
        result = watcher.read_cursor(cursor_path)
        # Default = ~24h ago, so result is in the past but recent.
        delta = datetime.now(UTC) - result
        assert timedelta(hours=23, minutes=59) < delta < timedelta(hours=24, minutes=1)

    def test_round_trip(self, tmp_path: Path) -> None:
        cursor_path = tmp_path / "cursor.txt"
        when = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
        watcher.write_cursor(cursor_path, when)
        assert watcher.read_cursor(cursor_path) == when

    def test_malformed_cursor_falls_back(self, tmp_path: Path) -> None:
        cursor_path = tmp_path / "cursor.txt"
        cursor_path.write_text("not-a-timestamp")
        result = watcher.read_cursor(cursor_path)
        delta = datetime.now(UTC) - result
        assert timedelta(hours=23, minutes=59) < delta < timedelta(hours=24, minutes=1)


# ---------------------------------------------------------------------------
# linked-task lookup
# ---------------------------------------------------------------------------


class TestFindLinkedTask:
    def test_finds_matching_pr(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=42)
        _write_note(vault, task_id="task-B", pr=43)
        result = watcher.find_linked_task(42, vault_root=vault)
        assert result is not None
        assert result.task_id == "task-A"
        assert result.pr_number == 42

    def test_returns_none_when_no_match(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=42)
        assert watcher.find_linked_task(999, vault_root=vault) is None

    def test_returns_none_when_active_dir_missing(self, tmp_path: Path) -> None:
        vault = tmp_path / "ghost-vault"
        # Don't create it.
        assert watcher.find_linked_task(1, vault_root=vault) is None

    def test_skips_notes_without_task_id(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        bad = vault / "active" / "noid-test.md"
        bad.write_text("---\npr: 42\n---\n# no task_id field\n")
        assert watcher.find_linked_task(42, vault_root=vault) is None


class TestDefaultRepoRoot:
    def test_prefers_explicit_cc_task_tool_repo_env(self, tmp_path: Path, monkeypatch: Any) -> None:
        tool_root = tmp_path / "active-source"
        monkeypatch.setenv("HAPAX_CC_TASK_TOOL_REPO_ROOT", str(tool_root))
        monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_WORKTREE", str(tmp_path / "other"))

        assert watcher.default_repo_root() == tool_root

    def test_falls_back_to_source_activation_worktree_env(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        active = tmp_path / "source-activation" / "worktree"
        monkeypatch.delenv("HAPAX_CC_TASK_TOOL_REPO_ROOT", raising=False)
        monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_WORKTREE", str(active))

        assert watcher.default_repo_root() == active


# ---------------------------------------------------------------------------
# fetch_merged_prs
# ---------------------------------------------------------------------------


class TestFetchMergedPRs:
    def test_parses_gh_output(self, tmp_path: Path) -> None:
        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 1, "mergedAt": "2026-04-26T12:00:00Z", "headRefName": "feat/x"},
            {"number": 2, "mergedAt": "2026-04-26T13:00:00Z", "headRefName": "feat/y"},
        ]
        merged = watcher.fetch_merged_prs(
            datetime(2026, 4, 26, 0, 0, tzinfo=UTC),
            repo_root=tmp_path,
            runner=runner,
        )
        assert [p.number for p in merged] == [1, 2]
        assert merged[0].head_branch == "feat/x"
        assert merged[1].merged_at == datetime(2026, 4, 26, 13, 0, tzinfo=UTC)

    def test_handles_gh_failure(self, tmp_path: Path) -> None:
        runner = _FakeRunner()
        runner.gh_returncode = 1
        merged = watcher.fetch_merged_prs(
            datetime(2026, 4, 26, tzinfo=UTC), repo_root=tmp_path, runner=runner
        )
        assert merged == []

    def test_skips_malformed_records(self, tmp_path: Path) -> None:
        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": "not-an-int", "mergedAt": "2026-04-26T12:00:00Z"},
            {"number": 5, "mergedAt": "garbage"},
            {"number": 6, "mergedAt": "2026-04-26T14:00:00Z", "headRefName": "ok"},
        ]
        merged = watcher.fetch_merged_prs(
            datetime(2026, 4, 26, tzinfo=UTC), repo_root=tmp_path, runner=runner
        )
        assert [p.number for p in merged] == [6]


# ---------------------------------------------------------------------------
# run_watcher: end-to-end with mocked subprocess
# ---------------------------------------------------------------------------


class TestRunWatcher:
    def test_closes_linked_pr(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=100)
        cursor = tmp_path / "cursor.txt"
        watcher.write_cursor(cursor, datetime(2026, 4, 26, 0, tzinfo=UTC))

        # The watcher needs the cc-close script to exist on disk; create
        # a dummy that succeeds (the _FakeRunner intercepts the actual call).
        cc_close = tmp_path / "scripts" / "cc-close"
        cc_close.parent.mkdir(parents=True, exist_ok=True)
        cc_close.write_text("#!/bin/sh\nexit 0\n")
        cc_close.chmod(0o755)

        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 100, "mergedAt": "2026-04-26T12:00:00Z", "headRefName": "feat/a"},
        ]

        counters = watcher.run_watcher(
            cursor_path=cursor,
            vault_root=vault,
            repo_root=tmp_path,
            runner=runner,
        )
        assert counters == {"merged": 1, "linked": 1, "closed": 1, "failed": 0, "skipped": 0}
        # cc-close was invoked with --pr 100.
        assert any(cmd[-2:] == ["--pr", "100"] for cmd in runner.cc_close_invocations), (
            runner.cc_close_invocations
        )
        # Cursor advanced.
        new_cursor = watcher.read_cursor(cursor)
        assert new_cursor == datetime(2026, 4, 26, 12, tzinfo=UTC)

    def test_skips_unlinked_prs(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        # No notes in vault — every PR is unlinked.
        cursor = tmp_path / "cursor.txt"
        watcher.write_cursor(cursor, datetime(2026, 4, 26, 0, tzinfo=UTC))

        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 100, "mergedAt": "2026-04-26T12:00:00Z", "headRefName": "feat/a"},
            {"number": 101, "mergedAt": "2026-04-26T13:00:00Z", "headRefName": "feat/b"},
        ]

        counters = watcher.run_watcher(
            cursor_path=cursor,
            vault_root=vault,
            repo_root=tmp_path,
            runner=runner,
        )
        assert counters["linked"] == 0
        assert counters["closed"] == 0
        # No cc-close invocations.
        assert not runner.cc_close_invocations
        # Cursor still advances past the unlinked PRs (no work to lose).
        new_cursor = watcher.read_cursor(cursor)
        assert new_cursor == datetime(2026, 4, 26, 13, tzinfo=UTC)

    def test_failed_close_does_not_advance_cursor_past_it(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=100)
        _write_note(vault, task_id="task-B", pr=101)
        cursor = tmp_path / "cursor.txt"
        cursor_start = datetime(2026, 4, 26, 0, tzinfo=UTC)
        watcher.write_cursor(cursor, cursor_start)

        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 100, "mergedAt": "2026-04-26T12:00:00Z", "headRefName": "feat/a"},
            {"number": 101, "mergedAt": "2026-04-26T13:00:00Z", "headRefName": "feat/b"},
        ]
        # The watcher needs the cc-close script to exist on disk; create
        # a dummy that just records its rc via the runner injection.
        cc_close = tmp_path / "scripts" / "cc-close"
        cc_close.parent.mkdir(parents=True, exist_ok=True)
        cc_close.write_text("#!/bin/sh\nexit 0\n")
        cc_close.chmod(0o755)
        # Earliest PR succeeds; later one fails.
        runner.cc_close_returncodes = [0, 1]

        counters = watcher.run_watcher(
            cursor_path=cursor,
            vault_root=vault,
            repo_root=tmp_path,
            runner=runner,
        )
        assert counters["closed"] == 1
        assert counters["failed"] == 1
        # Cursor advanced PAST the successful close (12:00) but NOT past the
        # failed close (13:00).
        new_cursor = watcher.read_cursor(cursor)
        assert new_cursor == datetime(2026, 4, 26, 12, tzinfo=UTC), new_cursor

    def test_killswitch_skips(self, tmp_path: Path, monkeypatch: Any) -> None:
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=100)
        cursor = tmp_path / "cursor.txt"
        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 100, "mergedAt": "2026-04-26T12:00:00Z", "headRefName": "x"},
        ]
        monkeypatch.setenv("HAPAX_CC_HYGIENE_OFF", "1")
        counters = watcher.run_watcher(
            cursor_path=cursor,
            vault_root=vault,
            repo_root=tmp_path,
            runner=runner,
        )
        assert counters.get("skipped") == 1
        assert counters["merged"] == 0
        assert not runner.cc_close_invocations
        # Cursor not written.
        assert not cursor.exists()

    def test_dry_run_does_not_invoke_cc_close(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=100)
        cursor = tmp_path / "cursor.txt"
        watcher.write_cursor(cursor, datetime(2026, 4, 26, 0, tzinfo=UTC))

        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 100, "mergedAt": "2026-04-26T12:00:00Z", "headRefName": "x"},
        ]
        counters = watcher.run_watcher(
            cursor_path=cursor,
            vault_root=vault,
            repo_root=tmp_path,
            dry_run=True,
            runner=runner,
        )
        assert counters["closed"] == 1  # we count the would-close
        assert not runner.cc_close_invocations  # but didn't invoke
        # Cursor not written in dry-run.
        assert watcher.read_cursor(cursor) == datetime(2026, 4, 26, 0, tzinfo=UTC)
