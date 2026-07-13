"""CLI tests for ``scripts/hapax-merge-queue-lineage``."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-merge-queue-lineage"


def _load_lineage_module() -> ModuleType:
    name = "hapax_merge_queue_lineage_script"
    if name in sys.modules:
        return sys.modules[name]
    loader = SourceFileLoader(name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def test_collect_from_json_fixtures_writes_ledger_and_summary(tmp_path: Path) -> None:
    runs_json = tmp_path / "runs.json"
    prs_json = tmp_path / "prs.json"
    ledger = tmp_path / "merge-queue-lineage.jsonl"
    summary = tmp_path / "merge-queue-summary.json"
    vault_root = tmp_path / "hapax-cc-tasks"
    active = vault_root / "active"
    active.mkdir(parents=True)
    (active / "demo-task.md").write_text(
        """---
type: cc-task
task_id: demo-task
status: claimed
pr: 3450
assigned_to: cx-demo
---

# Demo
""",
        encoding="utf-8",
    )

    runs_json.write_text(
        json.dumps(
            [
                {
                    "databaseId": 42,
                    "attempt": 1,
                    "conclusion": "success",
                    "createdAt": "2026-05-18T21:44:24Z",
                    "event": "merge_group",
                    "headBranch": (
                        "gh-readonly-queue/main/pr-3450-0375eb0ea2b70e9c964e9f209c3127f237d7044b"
                    ),
                    "headSha": "ef27e40690b1dcdee3296810cb5ea8e0312b7de3",
                    "startedAt": "2026-05-18T21:44:24Z",
                    "status": "completed",
                    "updatedAt": "2026-05-18T22:00:50Z",
                    "workflowName": "CI",
                    "jobs": [
                        {
                            "name": "test-full-shard (1/4)",
                            "status": "completed",
                            "conclusion": "success",
                            "startedAt": "2026-05-18T21:45:00Z",
                            "completedAt": "2026-05-18T21:58:00Z",
                            "steps": [],
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    prs_json.write_text(
        json.dumps(
            [
                {
                    "number": 3450,
                    "headRefOid": "0375eb0ea2b70e9c964e9f209c3127f237d7044b",
                    "state": "OPEN",
                    "mergedAt": None,
                    "mergeStateStatus": "CLEAN",
                    "autoMergeRequest": None,
                    "isDraft": False,
                    "body": "## Summary\ncc-task: demo-task\n\n## Test plan\n- [x] tests\n",
                    "statusCheckRollup": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "collect",
            "--runs-json",
            str(runs_json),
            "--prs-json",
            str(prs_json),
            "--ledger-path",
            str(ledger),
            "--summary-path",
            str(summary),
            "--vault-root",
            str(vault_root),
            "--max-records",
            "5",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "wrote 1 record" in result.stdout
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["event"] == "merge_queue_lineage"
    assert record["pr_number"] == 3450
    summary_data = json.loads(summary.read_text(encoding="utf-8"))
    assert summary_data["event"] == "merge_queue_summary"
    assert summary_data["latest_run_id"] == 42
    assert summary_data["latest_bottleneck"]["kind"] == "branch_protection_check_mapping"
    assert any(
        reason["source"] == "cc_task_note" and "status is claimed" in reason["reason"]
        for reason in summary_data["current_queue_hold_reasons"]
    )


def test_fetch_prs_uses_rest_status_shape(tmp_path: Path, monkeypatch: Any) -> None:
    lineage = _load_lineage_module()

    class RestRunner:
        def __init__(self) -> None:
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
            **_: Any,
        ) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] != ["gh", "api", "--method", "GET", "-H"]:
                return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

            path = cmd[6]
            if path == "repos/hapax-systems/hapax-council/pulls":
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps(
                        [
                            {
                                "number": 3450,
                                "node_id": "PR_kw",
                                "title": "PR 3450",
                                "body": "body",
                                "head": {"ref": "feat/lineage", "sha": "sha-3450"},
                                "draft": False,
                                "state": "open",
                                "merged": False,
                                "merged_at": None,
                                "updated_at": "2026-05-18T22:00:00Z",
                                "html_url": (
                                    "https://github.com/hapax-systems/hapax-council/pull/3450"
                                ),
                                "mergeable_state": "clean",
                                "auto_merge": None,
                                "changed_files": 1,
                                "labels": [],
                            }
                        ]
                    ),
                    "",
                )
            if path == "repos/hapax-systems/hapax-council/pulls/3450":
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps(
                        {
                            "number": 3450,
                            "node_id": "PR_kw",
                            "title": "PR 3450",
                            "body": "body",
                            "head": {"ref": "feat/lineage", "sha": "sha-3450"},
                            "draft": False,
                            "state": "open",
                            "merged": False,
                            "merged_at": None,
                            "updated_at": "2026-05-18T22:00:00Z",
                            "html_url": (
                                "https://github.com/hapax-systems/hapax-council/pull/3450"
                            ),
                            "mergeable_state": "clean",
                            "auto_merge": None,
                            "changed_files": 1,
                            "labels": [],
                        }
                    ),
                    "",
                )
            if path == "repos/hapax-systems/hapax-council/commits/sha-3450/check-runs":
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps(
                        {
                            "check_runs": [
                                {
                                    "name": "test",
                                    "status": "completed",
                                    "conclusion": "success",
                                }
                            ]
                        }
                    ),
                    "",
                )
            if path == "repos/hapax-systems/hapax-council/commits/sha-3450/status":
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"statuses": []}), "")
            return subprocess.CompletedProcess(cmd, 1, "", f"unexpected path {path}")

    runner = RestRunner()
    monkeypatch.setattr(lineage.subprocess, "run", runner)

    rows = lineage.fetch_prs(limit=100, repo=None, pr_numbers={3450})

    assert len(rows) == 1
    assert rows[0]["state"] == "OPEN"
    assert rows[0]["mergedAt"] is None
    assert rows[0]["updatedAt"] == "2026-05-18T22:00:00Z"
    assert rows[0]["url"] == "https://github.com/hapax-systems/hapax-council/pull/3450"
    assert rows[0]["statusCheckRollup"][0]["name"] == "test"
    assert rows[0]["statusCheckRollup"][0]["conclusion"] == "SUCCESS"
    assert not any(call[:2] == ["gh", "pr"] for call in runner.calls)


def test_fetch_prs_fails_closed_when_open_pr_snapshot_is_indeterminate(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    lineage = _load_lineage_module()

    class IndeterminateRunner:
        def __call__(
            self,
            cmd: list[str],
            *,
            cwd: str | None = None,
            capture_output: bool = False,
            text: bool = False,
            check: bool = False,
            timeout: int | None = None,
            **_: Any,
        ) -> subprocess.CompletedProcess:
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
                return subprocess.CompletedProcess(cmd, 1, "", "rate limit")
            return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    monkeypatch.setattr(lineage.subprocess, "run", IndeterminateRunner())
    monkeypatch.setattr(lineage, "REPO_ROOT", tmp_path)

    try:
        lineage.fetch_prs(limit=100, repo=None, pr_numbers=set())
    except RuntimeError as exc:
        assert "open PR query indeterminate via REST" in str(exc)
    else:
        raise AssertionError("fetch_prs must not return a false-empty open PR set")
