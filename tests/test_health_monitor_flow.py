"""Tests for the merge-plane flow health check.

Unsafe cases come first. A missing or stale producer must never read as healthy,
and a frozen valve must read as failed. The 2026-10-06 → 10-10 freeze went
unnoticed for about 46 hours because nothing measured flow.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agents.health_monitor.checks.flow import (
    FLOW_STOPPED_S,
    REPORT_STALE_S,
    VALVE_FAILING_S,
    check_merge_flow,
)
from agents.health_monitor.models import Status
from agents.health_monitor.registry import CHECK_REGISTRY

NOW = datetime(2026, 10, 10, 9, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _write(
    tmp_path: Path,
    *,
    last_merge: datetime | None,
    report_at: datetime | None,
    open_prs: int = 195,
    failed_runs: list[dict] | None = None,
    holders: list[str] | None = None,
    write_report: bool = True,
    write_cursor: bool = True,
) -> tuple[Path, Path]:
    cursor = tmp_path / "cursor.txt"
    report = tmp_path / "report.json"
    if write_cursor:
        cursor.write_text(_iso(last_merge) if last_merge else "", encoding="utf-8")
    if write_report:
        payload = {
            "open_pr_count": open_prs,
            "queued_prs": [],
            "active_ci_repair_task_ids": holders or [],
            "storm_mode": {"failed_recent_merge_group_runs": failed_runs or []},
        }
        if report_at is not None:
            payload["generated_at"] = _iso(report_at)
        report.write_text(json.dumps(payload), encoding="utf-8")
    return cursor, report


def _run(cursor: Path, report: Path):
    results = asyncio.run(check_merge_flow(cursor_path=cursor, report_path=report, now=NOW))
    assert len(results) == 1
    return results[0]


def test_registered_in_flow_group() -> None:
    assert check_merge_flow in CHECK_REGISTRY.get("flow", [])


def test_missing_report_is_degraded_never_healthy(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=NOW, report_at=NOW, write_report=False)
    result = _run(cursor, report)
    assert result.status is Status.DEGRADED
    assert "flow unknown" in result.message


def test_stale_report_is_degraded_never_healthy(tmp_path: Path) -> None:
    stale = NOW - timedelta(seconds=REPORT_STALE_S + 60)
    cursor, report = _write(tmp_path, last_merge=NOW, report_at=stale)
    result = _run(cursor, report)
    assert result.status is Status.DEGRADED
    assert "old" in result.message


def test_report_without_generated_at_is_degraded(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=NOW, report_at=None)
    assert _run(cursor, report).status is Status.DEGRADED


def test_missing_cursor_is_degraded_never_healthy(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=NOW, report_at=NOW, write_cursor=False)
    result = _run(cursor, report)
    assert result.status is Status.DEGRADED
    assert "cursor" in result.message


def test_empty_cursor_is_degraded(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=None, report_at=NOW)
    assert _run(cursor, report).status is Status.DEGRADED


def test_frozen_valve_is_failed(tmp_path: Path) -> None:
    # The 2026-10-07 shape: merge groups failing, PRs waiting, nothing merging.
    cursor, report = _write(
        tmp_path,
        last_merge=NOW - timedelta(seconds=VALVE_FAILING_S + 600),
        report_at=NOW,
        failed_runs=[{"run_id": 37848439089, "head_branch": "gh-readonly-queue/main/pr-5066-x"}],
    )
    result = _run(cursor, report)
    assert result.status is Status.FAILED
    assert "merge valve failing" in result.message
    assert "195 open PRs" in result.message


def test_failed_runs_with_a_recent_merge_are_not_failed(tmp_path: Path) -> None:
    cursor, report = _write(
        tmp_path,
        last_merge=NOW - timedelta(minutes=20),
        report_at=NOW,
        failed_runs=[{"run_id": 1}],
    )
    assert _run(cursor, report).status is Status.HEALTHY


def test_long_stall_without_failures_is_degraded(tmp_path: Path) -> None:
    # Holders or admission blocks: nothing failing, nothing merging.
    cursor, report = _write(
        tmp_path,
        last_merge=NOW - timedelta(seconds=FLOW_STOPPED_S + 600),
        report_at=NOW,
        holders=["capability-consideration-waivers-20260619"],
    )
    result = _run(cursor, report)
    assert result.status is Status.DEGRADED
    assert "flow stopped" in result.message
    assert "capability-consideration-waivers-20260619" in (result.detail or "")


def test_recent_merge_is_healthy(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=NOW - timedelta(minutes=20), report_at=NOW)
    result = _run(cursor, report)
    assert result.status is Status.HEALTHY
    assert "195 open PRs" in result.message


def test_quiet_with_no_open_prs_is_healthy(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=NOW - timedelta(days=3), report_at=NOW, open_prs=0)
    assert _run(cursor, report).status is Status.HEALTHY
