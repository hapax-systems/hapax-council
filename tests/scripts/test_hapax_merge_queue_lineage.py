"""CLI tests for ``scripts/hapax-merge-queue-lineage``."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-merge-queue-lineage"


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
