"""Tests for merge queue lineage observability."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from shared.merge_queue_lineage import (
    annotate_run_counts,
    build_lineage_record,
    build_summary,
    classify_open_pr_holds,
    read_jsonl_records,
    write_jsonl_records,
)


def _run(
    *,
    run_id: int = 26062256385,
    pr_number: int = 3450,
    conclusion: str = "success",
    jobs: list[dict] | None = None,
) -> dict:
    return {
        "databaseId": run_id,
        "attempt": 1,
        "conclusion": conclusion,
        "createdAt": "2026-05-18T21:44:24Z",
        "event": "merge_group",
        "headBranch": f"gh-readonly-queue/main/pr-{pr_number}-0375eb0ea2b70e9c964e9f209c3127f237d7044b",
        "headSha": "ef27e40690b1dcdee3296810cb5ea8e0312b7de3",
        "startedAt": "2026-05-18T21:44:24Z",
        "status": "completed",
        "updatedAt": "2026-05-18T22:00:50Z",
        "url": f"https://github.test/actions/runs/{run_id}",
        "workflowName": "CI",
        "jobs": jobs or [],
    }


def _pr(*, number: int = 3450, state: str = "OPEN") -> dict:
    return {
        "number": number,
        "headRefOid": "0375eb0ea2b70e9c964e9f209c3127f237d7044b",
        "headRefName": "alpha/demo",
        "state": state,
        "mergedAt": None,
        "mergeStateStatus": "CLEAN",
        "autoMergeRequest": None,
        "isDraft": False,
        "body": "## Summary\ncc-task: demo-task\n\n## Test plan\n- [x] tests\n",
        "statusCheckRollup": [],
    }


def test_lineage_record_captures_required_fields_and_open_success_bottleneck() -> None:
    record = build_lineage_record(
        _run(jobs=[_job("test-full-shard (1/4)", "21:45:00", "21:58:00")]),
        pr_by_number={3450: _pr()},
        observed_at=datetime(2026, 5, 18, 22, 1, tzinfo=UTC),
    )

    assert record.pr_number == 3450
    assert record.pr_head_sha == "0375eb0ea2b70e9c964e9f209c3127f237d7044b"
    assert record.synthetic_queue_branch.startswith("gh-readonly-queue/main/pr-3450")
    assert record.synthetic_queue_sha == "ef27e40690b1dcdee3296810cb5ea8e0312b7de3"
    assert record.merge_group_run_id == 26062256385
    assert record.run_outcome == "success"
    assert record.queue_entry_time == datetime(2026, 5, 18, 21, 44, 24, tzinfo=UTC)
    assert record.merge_time is None
    assert record.slowest_job is not None
    assert record.slowest_job.name == "test-full-shard (1/4)"
    assert record.pr_remained_open_after_success is True
    assert record.bottleneck is not None
    assert record.bottleneck.kind == "branch_protection_check_mapping"
    assert "successful synthetic merge-group run left PR open" in record.lifecycle_reasons


def test_repeated_setup_cost_uses_step_durations() -> None:
    record = build_lineage_record(
        _run(
            jobs=[
                _job(
                    "lint",
                    "21:45:00",
                    "21:50:00",
                    steps=[
                        _step("Run actions/checkout@v6", "21:45:00", "21:46:00"),
                        _step("Install system deps", "21:46:00", "21:48:00"),
                        _step("Run uv sync --extra ci", "21:48:00", "21:50:00"),
                    ],
                )
            ]
        ),
        pr_by_number={3450: _pr(state="MERGED") | {"mergedAt": "2026-05-18T22:02:00Z"}},
        observed_at=datetime(2026, 5, 18, 22, 1, tzinfo=UTC),
    )

    assert record.setup_duration_seconds == 300
    assert record.bottleneck is not None
    assert record.bottleneck.kind == "repeated_setup_cost"


def test_summary_includes_open_pr_hold_reasons_and_repeated_successes() -> None:
    first = build_lineage_record(_run(run_id=1), pr_by_number={3450: _pr()})
    second = build_lineage_record(_run(run_id=2), pr_by_number={3450: _pr()})
    first, second = annotate_run_counts([first, second])
    open_pr = _pr() | {
        "body": "## Summary\n\n## Test plan\n- [ ] manual visual check\n",
        "statusCheckRollup": [
            {"name": "lint", "conclusion": "FAILURE", "status": "COMPLETED"},
            {"name": "CodeQL", "conclusion": "", "status": "IN_PROGRESS"},
        ],
    }

    summary = build_summary(
        [first, second],
        open_prs=[open_pr],
        observed_at=datetime(2026, 5, 18, 22, 5, tzinfo=UTC),
    )

    kinds = [reason.kind for reason in summary.current_queue_hold_reasons]
    assert "task_lifecycle_hygiene" in kinds
    assert "manual_checklist_blocker" in kinds
    assert "queue_admission" in kinds
    assert "runner_capacity" in kinds
    assert summary.repeated_successful_synthetic_prs == [3450]
    assert second.prior_merge_group_runs_for_pr == 1
    assert second.successful_merge_group_runs_for_pr == 1


def test_open_pr_hold_reason_detects_multiple_task_links() -> None:
    reasons = classify_open_pr_holds(
        _pr()
        | {
            "body": "cc-task: one\nmore text\ncc-task: two\n",
            "mergeStateStatus": "BLOCKED",
        }
    )

    assert any(reason.kind == "task_lifecycle_hygiene" for reason in reasons)
    assert any("multiple cc-tasks" in reason.reason for reason in reasons)


def test_open_pr_hold_reason_detects_linked_task_lifecycle_state() -> None:
    reasons = classify_open_pr_holds(
        _pr()
        | {
            "cc_task_id": "demo-task",
            "cc_task_status": "claimed",
        }
    )

    assert any(
        reason.kind == "task_lifecycle_hygiene" and "demo-task status is claimed" in reason.reason
        for reason in reasons
    )


def test_jsonl_writer_deduplicates_by_run_id_and_bounds(tmp_path: Path) -> None:
    path = tmp_path / "merge-queue-lineage.jsonl"
    records = [
        build_lineage_record(_run(run_id=1, pr_number=3450), pr_by_number={3450: _pr()}),
        build_lineage_record(_run(run_id=2, pr_number=3451), pr_by_number={3451: _pr(number=3451)}),
    ]
    write_jsonl_records(path, records, max_records=2)
    replacement = build_lineage_record(
        _run(run_id=2, pr_number=3451, conclusion="cancelled"),
        pr_by_number={3451: _pr(number=3451)},
    )
    extra = build_lineage_record(
        _run(run_id=3, pr_number=3452),
        pr_by_number={3452: _pr(number=3452)},
    )

    write_jsonl_records(path, [replacement, extra], max_records=2)

    raw = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [item["merge_group_run_id"] for item in raw] == [2, 3]
    assert raw[0]["run_outcome"] == "cancelled"
    assert [record.merge_group_run_id for record in read_jsonl_records(path)] == [2, 3]


def _job(
    name: str,
    started: str,
    completed: str,
    *,
    steps: list[dict] | None = None,
) -> dict:
    return {
        "name": name,
        "databaseId": 1,
        "status": "completed",
        "conclusion": "success",
        "startedAt": f"2026-05-18T{started}Z",
        "completedAt": f"2026-05-18T{completed}Z",
        "steps": steps or [],
    }


def _step(name: str, started: str, completed: str) -> dict:
    return {
        "name": name,
        "status": "completed",
        "conclusion": "success",
        "startedAt": f"2026-05-18T{started}Z",
        "completedAt": f"2026-05-18T{completed}Z",
    }
