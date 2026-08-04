"""Tests for ``scripts/cc-pr-merge-watcher.py`` (H9 — PR3 of cc-hygiene).

Per project convention, no shared conftest fixtures — each test builds
its own vault + cursor under ``tmp_path`` and injects a fake ``gh`` /
``cc-close`` runner into ``run_watcher()``.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

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


def _api_fields(cmd: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    index = 0
    while index < len(cmd):
        if cmd[index] == "-f" and index + 1 < len(cmd) and "=" in cmd[index + 1]:
            key, value = cmd[index + 1].split("=", 1)
            out[key] = value
            index += 2
            continue
        index += 1
    return out


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (vault / "active").mkdir(parents=True, exist_ok=True)
    (vault / "closed").mkdir(parents=True, exist_ok=True)
    return vault


def _write_note(vault: Path, *, task_id: str, pr: int | None, extra_frontmatter: str = "") -> Path:
    pr_line = f"pr: {pr}" if pr is not None else "pr: null"
    if extra_frontmatter:
        pr_line = f"{pr_line}\n{extra_frontmatter}"
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


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _init_activation_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "source-activation" / "worktree"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "cc-pr-merge-watcher@example.invalid")
    _git(repo, "config", "user.name", "cc pr merge watcher tests")
    (repo / "README.md").write_text("release one\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "release one")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", sha)
    return repo, sha


def _write_activation_current(current_path: Path, repo: Path, active_head: str) -> None:
    current_path.parent.mkdir(parents=True, exist_ok=True)
    current_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_source_head": active_head,
                "active_source_path": str(repo),
                "origin_main_sha": active_head,
            }
        ),
        encoding="utf-8",
    )


class _FakeRunner:
    """Inject canned subprocess responses keyed by command prefix."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.gh_payload: list[dict[str, Any]] = []
        self.gh_returncode = 0
        self.cc_close_returncodes: list[int] = []  # consumed in order
        self.cc_close_invocations: list[list[str]] = []
        self.cc_close_envs: list[dict[str, str]] = []

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
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
            path = cmd[6]
            if path == "search/issues":
                payload = {"items": [{"number": item["number"]} for item in self.gh_payload]}
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=self.gh_returncode,
                    stdout=json.dumps(payload),
                    stderr="",
                )
            pull_match = re.fullmatch(r"repos/hapax-systems/hapax-council/pulls/(\d+)", path)
            if pull_match:
                number = int(pull_match.group(1))

                def _item_number(item: dict[str, Any]) -> int | None:
                    try:
                        return int(item.get("number", -1))
                    except (TypeError, ValueError):
                        return None

                payload = next(
                    (item for item in self.gh_payload if _item_number(item) == number),
                    None,
                )
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0 if payload is not None and self.gh_returncode == 0 else 1,
                    stdout=json.dumps(payload or {}),
                    stderr="",
                )
            if path == "repos/hapax-systems/hapax-council/pulls":
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=self.gh_returncode,
                    stdout=json.dumps(self.gh_payload),
                    stderr="",
                )
        # Anything else is cc-close.
        self.cc_close_invocations.append(list(cmd))
        self.cc_close_envs.append(dict(env or {}))
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

    def test_finds_all_matching_tasks(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=42)
        _write_note(vault, task_id="task-B", pr=42)
        tasks = watcher.find_linked_tasks(42, vault_root=vault)
        assert [task.task_id for task in tasks] == ["task-A", "task-B"]

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


class TestSourceActivationFreshness:
    def test_source_activation_current_head_matches_origin_main(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        repo, active_head = _init_activation_repo(tmp_path)
        current = tmp_path / "source-activation" / "current.json"
        _write_activation_current(current, repo, active_head)
        monkeypatch.setenv("HAPAX_SOURCE_ACTIVATION_CURRENT", str(current))
        monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_WORKTREE", str(repo))

        watcher.assert_source_activation_fresh(repo)

    def test_source_activation_stale_origin_main_blocks_before_close(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        repo, active_head = _init_activation_repo(tmp_path)
        (repo / "README.md").write_text("release two\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-m", "release two")
        origin_main = _git(repo, "rev-parse", "HEAD")
        _git(repo, "update-ref", "refs/remotes/origin/main", origin_main)
        _git(repo, "checkout", "--detach", active_head)
        current = tmp_path / "source-activation" / "current.json"
        _write_activation_current(current, repo, active_head)
        monkeypatch.setenv("HAPAX_SOURCE_ACTIVATION_CURRENT", str(current))
        monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_WORKTREE", str(repo))

        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=100)
        cursor = tmp_path / "cursor.txt"
        cursor_start = datetime(2026, 4, 26, 0, tzinfo=UTC)
        watcher.write_cursor(cursor, cursor_start)
        cc_close = repo / "scripts" / "cc-close"
        cc_close.parent.mkdir(parents=True, exist_ok=True)
        cc_close.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        cc_close.chmod(0o755)
        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 100, "mergedAt": "2026-04-26T12:00:00Z", "headRefName": "feat/a"},
        ]

        with pytest.raises(watcher.SourceActivationFreshnessError, match="lags origin/main"):
            watcher.run_watcher(
                cursor_path=cursor,
                vault_root=vault,
                repo_root=repo,
                runner=runner,
            )

        assert not runner.calls
        assert not runner.cc_close_invocations
        assert watcher.read_cursor(cursor) == cursor_start

    def test_source_activation_freshness_block_alert_is_rate_limited(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        sent: list[dict[str, Any]] = []

        def fake_send_notification(**kwargs: Any) -> None:
            sent.append(kwargs)

        monkeypatch.setattr("shared.notify.send_notification", fake_send_notification)
        error = watcher.SourceActivationFreshnessError(
            "active_source_head abc lags origin/main def"
        )
        alert_path = tmp_path / "alert.json"
        now = datetime(2026, 7, 9, 17, 30, tzinfo=UTC)

        first = watcher.alert_source_activation_freshness_blocked(
            error,
            repo_root=tmp_path,
            alert_path=alert_path,
            now=now,
        )
        second = watcher.alert_source_activation_freshness_blocked(
            error,
            repo_root=tmp_path,
            alert_path=alert_path,
            now=now + timedelta(minutes=1),
        )

        assert first is True
        assert second is False
        assert len(sent) == 1
        assert sent[0]["title"] == "cc-pr-merge-watcher source stale"
        assert "hapax-post-merge-deploy.service" in sent[0]["message"]
        assert "hapax-cc-pr-merge-watcher.timer" in sent[0]["message"]


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
        assert any(call[6] == "search/issues" for call in runner.calls)

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

    def test_skips_closed_unmerged_and_old_merged_rows(self, tmp_path: Path) -> None:
        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 7, "mergedAt": None, "headRefName": "closed/no-merge"},
            {"number": 8, "mergedAt": "2026-04-26T11:00:00Z", "headRefName": "old/merge"},
            {"number": 9, "mergedAt": "2026-04-26T13:00:00Z", "headRefName": "new/merge"},
        ]

        merged = watcher.fetch_merged_prs(
            datetime(2026, 4, 26, 12, tzinfo=UTC), repo_root=tmp_path, runner=runner
        )

        assert [p.number for p in merged] == [9]


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
        assert counters == {
            "merged": 1,
            "linked": 1,
            "opted_out": 0,
            "closed": 1,
            "failed": 0,
            "skipped": 0,
        }
        # cc-close was invoked with --pr 100.
        assert any(
            cmd[-3:] == ["--pr", "100", "--retroactive"] for cmd in runner.cc_close_invocations
        ), runner.cc_close_invocations
        # The merge is authoritative: cc-close runs with the pre-merge AC + receipt
        # gates skipped so a merged-PR task drains regardless of pre-merge bookkeeping,
        # BUT the PR-merge evidence gate stays ON (the merge is still verified).
        assert runner.cc_close_envs[-1]["HAPAX_CC_TASK_CLOSURE_GATE_OFF"] == "1"
        assert runner.cc_close_envs[-1]["HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF"] == "1"
        assert "HAPAX_PR_MERGE_GATE_OFF" not in runner.cc_close_envs[-1]
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

    def test_failed_close_blocks_later_unlinked_cursor_advance(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=100)
        cursor = tmp_path / "cursor.txt"
        cursor_start = datetime(2026, 4, 26, 0, tzinfo=UTC)
        watcher.write_cursor(cursor, cursor_start)

        cc_close = tmp_path / "scripts" / "cc-close"
        cc_close.parent.mkdir(parents=True, exist_ok=True)
        cc_close.write_text("#!/bin/sh\nexit 0\n")
        cc_close.chmod(0o755)

        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 100, "mergedAt": "2026-04-26T12:00:00Z", "headRefName": "feat/a"},
            {"number": 101, "mergedAt": "2026-04-26T13:00:00Z", "headRefName": "feat/b"},
        ]
        runner.cc_close_returncodes = [1]

        counters = watcher.run_watcher(
            cursor_path=cursor,
            vault_root=vault,
            repo_root=tmp_path,
            runner=runner,
        )
        assert counters["failed"] == 1
        assert counters["closed"] == 0
        assert watcher.read_cursor(cursor) == cursor_start

    def test_closes_all_tasks_linked_to_one_pr(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=100)
        _write_note(vault, task_id="task-B", pr=100)
        cursor = tmp_path / "cursor.txt"
        watcher.write_cursor(cursor, datetime(2026, 4, 26, 0, tzinfo=UTC))

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
        assert counters == {
            "merged": 1,
            "linked": 2,
            "opted_out": 0,
            "closed": 2,
            "failed": 0,
            "skipped": 0,
        }
        assert [cmd[1] for cmd in runner.cc_close_invocations] == ["task-A", "task-B"]

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


# ---------------------------------------------------------------------------
# close_on_pr_merge: false — multi-PR lane opt-out
# ---------------------------------------------------------------------------


class TestCloseOnPrMergeOptOut:
    def test_opt_out_note_is_not_closed(self, tmp_path: Path, caplog: Any) -> None:
        """A note declaring close_on_pr_merge: false is skipped with an info log."""
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=100, extra_frontmatter="close_on_pr_merge: false")
        cursor = tmp_path / "cursor.txt"
        watcher.write_cursor(cursor, datetime(2026, 4, 26, 0, tzinfo=UTC))
        _make_cc_close(tmp_path)

        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 100, "mergedAt": "2026-04-26T12:00:00Z", "headRefName": "feat/a"},
        ]

        with caplog.at_level(logging.INFO, logger="cc-pr-merge-watcher"):
            counters = watcher.run_watcher(
                cursor_path=cursor,
                vault_root=vault,
                repo_root=tmp_path,
                runner=runner,
            )
        assert counters["linked"] == 0
        assert counters["opted_out"] == 1
        assert counters["closed"] == 0
        assert counters["failed"] == 0
        assert not runner.cc_close_invocations
        assert (
            "task task-A declares close_on_pr_merge: false — lane owner closes explicitly"
            in caplog.text
        )
        assert "has 1 linked cc-task(s) opted out of auto-close" in caplog.text
        # The skip is intentional, not a failure: the cursor still advances.
        assert watcher.read_cursor(cursor) == datetime(2026, 4, 26, 12, tzinfo=UTC)

    def test_body_only_mention_does_not_opt_out(self, tmp_path: Path) -> None:
        """The opt-out is a FRONTMATTER contract: a body/session-log line quoting
        `close_on_pr_merge: false` must not skip the close (parser scoped to the
        leading --- block; fail-safe default preserved)."""
        vault = _make_vault(tmp_path)
        note = _write_note(vault, task_id="task-A", pr=100)
        body_mention = note.read_text() + "\n- note: set close_on_pr_merge: false next time\n"
        note.write_text(body_mention)
        assert not watcher.declines_close_on_pr_merge(body_mention)
        cursor = tmp_path / "cursor.txt"
        watcher.write_cursor(cursor, datetime(2026, 4, 26, 0, tzinfo=UTC))
        _make_cc_close(tmp_path)

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
        assert counters == {
            "merged": 1,
            "linked": 1,
            "opted_out": 0,
            "closed": 1,
            "failed": 0,
            "skipped": 0,
        }

    def test_crlf_frontmatter_still_opts_out(self, tmp_path: Path) -> None:
        """A CRLF-checked-out note must not silently lose the opt-out: the failure
        direction of a parse miss is the lane-killing auto-close."""
        vault = _make_vault(tmp_path)
        note = _write_note(
            vault, task_id="task-A", pr=100, extra_frontmatter="close_on_pr_merge: false"
        )
        note.write_text(note.read_text().replace("\n", "\r\n"))
        assert watcher.declines_close_on_pr_merge(note.read_text())

    def test_yaml_equivalent_false_spellings_opt_out(self) -> None:
        """A YAML-dumper round-trip may re-serialize false as no/off/quoted forms, and a
        lane owner may append a YAML comment; all of those keep the opt-out. Explicit
        true-ish values (or the field's absence) keep the auto-close default."""
        for spelling in (
            "false",
            "no",
            "off",
            '"false"',
            "'false'",
            "FALSE",
            "No",
            "false  # lane owner closes explicitly",
            '"off" # reason',
        ):
            text = f"---\nclose_on_pr_merge: {spelling}\n---\nbody\n"
            assert watcher.declines_close_on_pr_merge(text), spelling
        for spelling in ("true", "yes", "on", '"true"', "'yes'", "TRUE # note"):
            text = f"---\nclose_on_pr_merge: {spelling}\n---\nbody\n"
            assert not watcher.declines_close_on_pr_merge(text), spelling

    def test_malformed_opt_out_fails_closed_toward_not_closing(self, caplog: Any) -> None:
        """A present-but-unreadable value is an ATTEMPTED opt-out: the watcher must not
        proceed to cc-close on it — it declines the close and warns."""
        for spelling in ('"false', "false'", "\"false'", "0", "falsey", "flase"):
            text = f"---\nclose_on_pr_merge: {spelling}\n---\nbody\n"
            with caplog.at_level(logging.WARNING, logger="cc-pr-merge-watcher"):
                assert watcher.declines_close_on_pr_merge(text), spelling
            # two fail-closed paths, one direction: an unreadable VALUE inside parsed
            # frontmatter, or frontmatter that fails to parse while mentioning the field
            assert "unreadable value" in caplog.text or "failed to parse" in caplog.text
            caplog.clear()

    def test_note_with_explicit_true_value_still_closes(self, tmp_path: Path) -> None:
        """An explicit true-ish value keeps the auto-close default."""
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=100, extra_frontmatter="close_on_pr_merge: true")
        cursor = tmp_path / "cursor.txt"
        watcher.write_cursor(cursor, datetime(2026, 4, 26, 0, tzinfo=UTC))
        _make_cc_close(tmp_path)

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
        assert counters == {
            "merged": 1,
            "linked": 1,
            "opted_out": 0,
            "closed": 1,
            "failed": 0,
            "skipped": 0,
        }
        assert any(
            cmd[-3:] == ["--pr", "100", "--retroactive"] for cmd in runner.cc_close_invocations
        ), runner.cc_close_invocations

    def test_mixed_lane_only_non_opt_out_note_closes(self, tmp_path: Path, caplog: Any) -> None:
        vault = _make_vault(tmp_path)
        _write_note(vault, task_id="task-A", pr=100, extra_frontmatter="close_on_pr_merge: false")
        _write_note(vault, task_id="task-B", pr=100)
        cursor = tmp_path / "cursor.txt"
        watcher.write_cursor(cursor, datetime(2026, 4, 26, 0, tzinfo=UTC))
        _make_cc_close(tmp_path)

        runner = _FakeRunner()
        runner.gh_payload = [
            {"number": 100, "mergedAt": "2026-04-26T12:00:00Z", "headRefName": "feat/a"},
        ]

        with caplog.at_level(logging.INFO, logger="cc-pr-merge-watcher"):
            counters = watcher.run_watcher(
                cursor_path=cursor,
                vault_root=vault,
                repo_root=tmp_path,
                runner=runner,
            )
        assert counters["closed"] == 1
        assert counters["opted_out"] == 1
        assert [cmd[1] for cmd in runner.cc_close_invocations] == ["task-B"]
        assert "has 1 linked cc-task(s) opted out of auto-close" in caplog.text

    def test_reconcile_skips_opt_out_note(self, tmp_path: Path, caplog: Any) -> None:
        """The stale-state reconciler honors the opt-out too (same class of close)."""
        vault = _make_vault(tmp_path)
        note = _write_reconcile_note(
            vault, task_id="task-A", pr=100, extra_frontmatter="close_on_pr_merge: false"
        )
        _make_cc_close(tmp_path)
        runner = _ReconcileRunner()
        runner.pr_states = {"100": "MERGED"}

        with caplog.at_level(logging.INFO, logger="cc-pr-merge-watcher"):
            counters = watcher.reconcile_stale_pr_states(
                vault_root=vault, repo_root=tmp_path, runner=runner
            )

        assert counters["closed"] == 0
        assert not runner.cc_close_invocations
        assert (
            "task task-A declares close_on_pr_merge: false — lane owner closes explicitly"
            in caplog.text
        )
        assert "status: pr_open" in note.read_text()


# ---------------------------------------------------------------------------
# reconcile_stale_pr_states: cursor-window-INDEPENDENT self-heal
#
# The cursor loop (run_watcher) only sees PRs merged after the cursor. A task
# whose PR merged outside that window (cursor advanced past it, or a restart
# reset the window) never self-heals there. reconcile_stale_pr_states scans
# EVERY active pr_open/merge_queue note and reconciles against the live PR
# state — so a merged-but-missed PR auto-closes, a closed PR blocks, and a
# pr:null note is repaired from its branch.
# ---------------------------------------------------------------------------


def _write_reconcile_note(
    vault: Path,
    *,
    task_id: str,
    status: str = "pr_open",
    pr: int | None = None,
    branch: str | None = None,
    extra_frontmatter: str = "",
) -> Path:
    pr_line = f"pr: {pr}" if pr is not None else "pr: null"
    if extra_frontmatter:
        pr_line = f"{pr_line}\n{extra_frontmatter}"
    branch_line = f"branch: {branch}" if branch is not None else "branch: null"
    note = vault / "active" / f"{task_id}-test.md"
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "x"
status: {status}
{branch_line}
{pr_line}
blocked_reason: null
---

# {task_id}

## Session log
- fixture
"""
    )
    return note


class _ReconcileRunner:
    """Inject REST PR state/head lookup + cc-close responses."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.pr_states: dict[str, str] = {}  # pr_num -> OPEN|CLOSED|MERGED
        self.pr_view_returncode = 0
        self.head_prs: dict[str, list[dict[str, Any]]] = {}  # branch -> REST pull rows
        self.cc_close_returncodes: list[int] = []
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
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
            path = cmd[6]
            pull_match = re.fullmatch(r"repos/hapax-systems/hapax-council/pulls/(\d+)", path)
            if pull_match:
                pr_num = pull_match.group(1)
                state = self.pr_states.get(pr_num, "OPEN")
                payload = {
                    "number": int(pr_num),
                    "state": "closed" if state in {"CLOSED", "MERGED"} else "open",
                    "merged": state == "MERGED",
                    "merged_at": "2026-07-05T00:00:00Z" if state == "MERGED" else None,
                    "draft": False,
                }
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=self.pr_view_returncode,
                    stdout=json.dumps(payload),
                    stderr="",
                )
            if path == "repos/hapax-systems/hapax-council/pulls":
                fields = _api_fields(cmd)
                head = fields.get("head", "").split(":", 1)[-1]
                rows: list[dict[str, Any]] = []
                for item in self.head_prs.get(head, []):
                    state = str(item.get("state") or "OPEN")
                    rows.append(
                        {
                            "number": item.get("number"),
                            "state": "closed" if state in {"CLOSED", "MERGED"} else "open",
                            "merged": state == "MERGED",
                            "merged_at": "2026-07-05T00:00:00Z" if state == "MERGED" else None,
                            "draft": False,
                        }
                    )
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=json.dumps(rows), stderr=""
                )
        # cc-close
        self.cc_close_invocations.append(list(cmd))
        rc = self.cc_close_returncodes.pop(0) if self.cc_close_returncodes else 0
        return subprocess.CompletedProcess(args=cmd, returncode=rc, stdout="closed\n", stderr="")


def _make_cc_close(tmp_path: Path) -> None:
    cc_close = tmp_path / "scripts" / "cc-close"
    cc_close.parent.mkdir(parents=True, exist_ok=True)
    cc_close.write_text("#!/bin/sh\nexit 0\n")
    cc_close.chmod(0o755)


class TestReconcileMerged:
    def test_merged_pr_auto_closes(self, tmp_path: Path) -> None:
        """A pr_open task whose PR is MERGED (missed by the cursor) self-closes."""
        vault = _make_vault(tmp_path)
        _write_reconcile_note(vault, task_id="task-A", pr=100)
        _make_cc_close(tmp_path)
        runner = _ReconcileRunner()
        runner.pr_states = {"100": "MERGED"}

        counters = watcher.reconcile_stale_pr_states(
            vault_root=vault, repo_root=tmp_path, runner=runner
        )

        assert counters["closed"] == 1
        assert any(
            cmd[-3:] == ["--pr", "100", "--retroactive"] for cmd in runner.cc_close_invocations
        ), runner.cc_close_invocations

    def test_merged_pr_close_failure_is_not_fatal(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_reconcile_note(vault, task_id="task-A", pr=100)
        _make_cc_close(tmp_path)
        runner = _ReconcileRunner()
        runner.pr_states = {"100": "MERGED"}
        runner.cc_close_returncodes = [1]  # cc-close fails

        counters = watcher.reconcile_stale_pr_states(
            vault_root=vault, repo_root=tmp_path, runner=runner
        )

        assert counters["closed"] == 0  # failed close is not counted

    def test_merged_dry_run_does_not_close(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_reconcile_note(vault, task_id="task-A", pr=100)
        _make_cc_close(tmp_path)
        runner = _ReconcileRunner()
        runner.pr_states = {"100": "MERGED"}

        counters = watcher.reconcile_stale_pr_states(
            vault_root=vault, repo_root=tmp_path, dry_run=True, runner=runner
        )

        assert counters["closed"] == 1  # counts the would-close
        assert not runner.cc_close_invocations  # but never invokes it

    def test_closed_pr_still_blocks(self, tmp_path: Path) -> None:
        """Regression: a CLOSED (unmerged) PR continues to block the task."""
        vault = _make_vault(tmp_path)
        note = _write_reconcile_note(vault, task_id="task-A", pr=100)
        runner = _ReconcileRunner()
        runner.pr_states = {"100": "CLOSED"}

        counters = watcher.reconcile_stale_pr_states(
            vault_root=vault, repo_root=tmp_path, runner=runner
        )

        assert counters["stale"] == 1
        assert counters["closed"] == 0
        text = note.read_text()
        assert "status: blocked" in text
        assert "closed without merge" in text

    def test_open_pr_is_left_alone(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        note = _write_reconcile_note(vault, task_id="task-A", pr=100)
        runner = _ReconcileRunner()
        runner.pr_states = {"100": "OPEN"}

        counters = watcher.reconcile_stale_pr_states(
            vault_root=vault, repo_root=tmp_path, runner=runner
        )

        assert counters["closed"] == 0
        assert counters["stale"] == 0
        assert "status: pr_open" in note.read_text()


class TestReconcilePrNullRepair:
    def test_pr_null_with_branch_rederives_and_closes_merged(self, tmp_path: Path) -> None:
        """pr:null + pr_open re-derives the PR from branch; a merged one closes."""
        vault = _make_vault(tmp_path)
        note = _write_reconcile_note(vault, task_id="task-A", pr=None, branch="epsilon/foo")
        _make_cc_close(tmp_path)
        runner = _ReconcileRunner()
        runner.head_prs = {"epsilon/foo": [{"number": 207, "state": "MERGED"}]}

        counters = watcher.reconcile_stale_pr_states(
            vault_root=vault, repo_root=tmp_path, runner=runner
        )

        assert counters["repaired"] == 1
        assert counters["closed"] == 1
        # The re-derived PR number was written back into the note.
        assert "pr: 207" in note.read_text()
        assert any(
            cmd[-3:] == ["--pr", "207", "--retroactive"] for cmd in runner.cc_close_invocations
        ), runner.cc_close_invocations

    def test_pr_null_dry_run_respects_opt_out(self, tmp_path: Path, caplog: Any) -> None:
        vault = _make_vault(tmp_path)
        note = _write_reconcile_note(
            vault,
            task_id="task-A",
            pr=None,
            branch="epsilon/foo",
            extra_frontmatter="close_on_pr_merge: false",
        )
        runner = _ReconcileRunner()
        runner.head_prs = {"epsilon/foo": [{"number": 207, "state": "MERGED"}]}

        with caplog.at_level(logging.INFO, logger="cc-pr-merge-watcher"):
            counters = watcher.reconcile_stale_pr_states(
                vault_root=vault,
                repo_root=tmp_path,
                dry_run=True,
                runner=runner,
            )

        assert counters["repaired"] == 1
        assert counters["closed"] == 0
        assert "pr: null" in note.read_text()
        assert "declares close_on_pr_merge: false" in caplog.text
        assert not runner.cc_close_invocations

    def test_pr_null_with_branch_no_pr_blocks(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        note = _write_reconcile_note(vault, task_id="task-A", pr=None, branch="epsilon/foo")
        runner = _ReconcileRunner()
        runner.head_prs = {"epsilon/foo": []}  # no PR for this branch

        counters = watcher.reconcile_stale_pr_states(
            vault_root=vault, repo_root=tmp_path, runner=runner
        )

        assert counters["stale"] == 1
        text = note.read_text()
        assert "status: blocked" in text
        assert "epsilon/foo" in text

    def test_pr_null_without_branch_blocks(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        note = _write_reconcile_note(vault, task_id="task-A", pr=None, branch=None)
        runner = _ReconcileRunner()

        counters = watcher.reconcile_stale_pr_states(
            vault_root=vault, repo_root=tmp_path, runner=runner
        )

        assert counters["stale"] == 1
        assert "status: blocked" in note.read_text()
        # Did not even attempt a gh lookup (no branch to look up).
        assert not any(cmd[:3] == ["gh", "pr", "list"] for cmd in runner.calls)


# ---------------------------------------------------------------------------
# G5 stuck-PR alerter
# ---------------------------------------------------------------------------


class _StuckRunner:
    """Canned REST status responses plus GraphQL merge-queue entries."""

    def __init__(self, open_prs: list[dict[str, Any]], queued: tuple[int, ...] = ()) -> None:
        self.open_prs = open_prs
        self.queued = list(queued)
        self.calls: list[list[str]] = []

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
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
            path = cmd[6]
            if path == "repos/o/r/pulls":
                payload = [
                    {
                        "number": pr["number"],
                        "title": f"PR {pr['number']}",
                        "head": {"ref": pr.get("headRefName"), "sha": f"sha-{pr['number']}"},
                        "draft": pr.get("isDraft", False),
                        "auto_merge": pr.get("autoMergeRequest"),
                        "state": "open",
                    }
                    for pr in self.open_prs
                ]
                return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
            pull_match = re.fullmatch(r"repos/o/r/pulls/(\d+)", path)
            if pull_match:
                number = int(pull_match.group(1))
                pr = next((item for item in self.open_prs if item["number"] == number), None)
                if pr is None:
                    return subprocess.CompletedProcess(cmd, 1, "", "PR not found")
                payload = {
                    "number": number,
                    "title": f"PR {number}",
                    "head": {"ref": pr.get("headRefName"), "sha": f"sha-{number}"},
                    "draft": pr.get("isDraft", False),
                    "auto_merge": pr.get("autoMergeRequest"),
                    "mergeable_state": "clean",
                    "state": "open",
                }
                return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
            check_match = re.fullmatch(r"repos/o/r/commits/sha-(\d+)/check-runs", path)
            if check_match:
                number = int(check_match.group(1))
                pr = next((item for item in self.open_prs if item["number"] == number), None)
                rollup = pr.get("statusCheckRollup", []) if pr else []
                payload = {
                    "check_runs": [
                        {
                            "name": check.get("name") or check.get("context"),
                            "status": str(
                                check.get("status")
                                or ("completed" if check.get("conclusion") else "in_progress")
                            ).lower(),
                            "conclusion": str(check.get("conclusion")).lower()
                            if check.get("conclusion") is not None
                            else None,
                        }
                        for check in rollup
                    ]
                }
                return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
            if re.fullmatch(r"repos/o/r/commits/sha-\d+/status", path):
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"statuses": []}), "")
        if cmd[:3] == ["gh", "api", "rate_limit"]:
            payload = {"resources": {"graphql": {"remaining": 1000, "reset": 1893456000}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "api", "graphql"]:
            nodes = [{"pullRequest": {"number": n}} for n in self.queued]
            payload = {"data": {"repository": {"mergeQueue": {"entries": {"nodes": nodes}}}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")


def _open_pr(
    number: int,
    *,
    armed: bool = True,
    checks: list[dict[str, Any]] | None = None,
    draft: bool = False,
    branch: str | None = None,
) -> dict[str, Any]:
    rollup = (
        checks
        if checks is not None
        else [{"name": c, "conclusion": "SUCCESS"} for c in watcher.REQUIRED_QUEUE_CHECKS]
    )
    return {
        "number": number,
        "headRefName": branch or f"feat/{number}",
        "isDraft": draft,
        "autoMergeRequest": {"enabledAt": "now"} if armed else None,
        "statusCheckRollup": rollup,
    }


class TestStuckPRAlerter:
    def test_armed_green_not_queued_is_stuck(self, tmp_path: Path) -> None:
        runner = _StuckRunner([_open_pr(70)], queued=())
        stuck = watcher.detect_stuck_prs(repo="o/r", repo_root=tmp_path, runner=runner)
        assert [s.number for s in stuck] == [70]
        assert stuck[0].head_branch == "feat/70"

    def test_queued_pr_is_not_stuck(self, tmp_path: Path) -> None:
        runner = _StuckRunner([_open_pr(71)], queued=(71,))
        assert watcher.detect_stuck_prs(repo="o/r", repo_root=tmp_path, runner=runner) == []

    def test_unarmed_pr_is_not_stuck(self, tmp_path: Path) -> None:
        runner = _StuckRunner([_open_pr(72, armed=False)], queued=())
        assert watcher.detect_stuck_prs(repo="o/r", repo_root=tmp_path, runner=runner) == []

    def test_pending_required_check_is_not_stuck(self, tmp_path: Path) -> None:
        checks = [{"name": c, "conclusion": "SUCCESS"} for c in watcher.REQUIRED_QUEUE_CHECKS[:-1]]
        checks.append({"name": watcher.REQUIRED_QUEUE_CHECKS[-1], "conclusion": None})
        runner = _StuckRunner([_open_pr(73, checks=checks)], queued=())
        assert watcher.detect_stuck_prs(repo="o/r", repo_root=tmp_path, runner=runner) == []

    def test_failed_required_check_is_not_stuck(self, tmp_path: Path) -> None:
        checks = [{"name": c, "conclusion": "SUCCESS"} for c in watcher.REQUIRED_QUEUE_CHECKS[:-1]]
        checks.append({"name": watcher.REQUIRED_QUEUE_CHECKS[-1], "conclusion": "FAILURE"})
        runner = _StuckRunner([_open_pr(74, checks=checks)], queued=())
        assert watcher.detect_stuck_prs(repo="o/r", repo_root=tmp_path, runner=runner) == []

    def test_graphql_backoff_does_not_report_stuck(self, tmp_path: Path) -> None:
        class _LowGraphQLRunner(_StuckRunner):
            def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
                if cmd[:3] == ["gh", "api", "rate_limit"]:
                    self.calls.append(list(cmd))
                    payload = {"resources": {"graphql": {"remaining": 0, "reset": 1893456000}}}
                    return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
                return super().__call__(cmd, **kwargs)

        runner = _LowGraphQLRunner([_open_pr(75)], queued=())

        assert watcher.detect_stuck_prs(repo="o/r", repo_root=tmp_path, runner=runner) == []
        assert not any(call[:3] == ["gh", "api", "graphql"] for call in runner.calls)

    def test_draft_pr_is_skipped(self, tmp_path: Path) -> None:
        runner = _StuckRunner([_open_pr(75, draft=True)], queued=())
        assert watcher.detect_stuck_prs(repo="o/r", repo_root=tmp_path, runner=runner) == []

    def test_alert_dry_run_counts_without_notifying(self, tmp_path: Path) -> None:
        runner = _StuckRunner([_open_pr(76)], queued=())
        count = watcher.alert_stuck_prs(repo="o/r", repo_root=tmp_path, runner=runner, dry_run=True)
        assert count == 1
