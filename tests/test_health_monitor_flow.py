"""Tests for the merge-plane flow health check.

Unsafe cases come first. A missing, stale or incomplete producer must never read as
healthy, and a frozen valve must read as failed and name the failing test. The
2026-10-06 → 10-10 freeze went unnoticed for about 46 hours because nothing measured
flow.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agents.health_monitor.checks import flow
from agents.health_monitor.checks.flow import (
    FLOW_STOPPED_S,
    REPORT_STALE_S,
    VALVE_FAILING_S,
    check_merge_flow,
)
from agents.health_monitor.models import Status
from agents.health_monitor.registry import CHECK_REGISTRY

NOW = datetime(2026, 10, 10, 9, 0, 0, tzinfo=UTC)
FAILED_LOG = (
    "test-full-shard (4/4)\tUNKNOWN STEP\t2026-10-08T21:53:36Z FAILED "
    "tests/docs/test_capability_consideration_completeness_contract.py::test_waiver_hygiene"
    " - AssertionError: EXPIRED waiver\n"
    "test-full-shard (4/4)\tUNKNOWN STEP\t2026-10-08T21:53:36Z 1 failed, 10902 passed\n"
)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _report_payload(*, report_at, open_prs=195, failed_runs=None, holders=None) -> dict:
    payload = {
        "open_pr_count": open_prs,
        "queued_prs": [],
        "active_ci_repair_task_ids": holders if holders is not None else [],
        "storm_mode": {"failed_recent_merge_group_runs": failed_runs or []},
    }
    if report_at is not None:
        payload["generated_at"] = _iso(report_at)
    return payload


def _write(tmp_path: Path, *, last_merge, report, cursor_text=None) -> tuple[Path, Path]:
    cursor = tmp_path / "cursor.txt"
    report_path = tmp_path / "report.json"
    if cursor_text is not None:
        cursor.write_text(cursor_text, encoding="utf-8")
    elif last_merge is not None:
        cursor.write_text(_iso(last_merge), encoding="utf-8")
    if report is not None:
        text = report if isinstance(report, str) else json.dumps(report)
        report_path.write_text(text, encoding="utf-8")
    return cursor, report_path


def _run(tmp_path: Path, cursor: Path, report: Path, fetch=None):
    calls: list[int] = []

    def default_fetch(run_id: int) -> str:
        calls.append(run_id)
        return FAILED_LOG

    results = asyncio.run(
        check_merge_flow(
            cursor_path=cursor,
            report_path=report,
            now=NOW,
            tests_cache_path=tmp_path / "failed-tests.json",
            fetch_log=fetch or default_fetch,
        )
    )
    assert len(results) == 1
    return results[0], calls


def test_registered_in_flow_group() -> None:
    assert check_merge_flow in CHECK_REGISTRY.get("flow", [])


# ── unknown is never healthy ──────────────────────────────────────────────────


def test_missing_report_is_degraded_never_healthy(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=NOW, report=None)
    result, _ = _run(tmp_path, cursor, report)
    assert result.status is Status.DEGRADED
    assert "flow unknown" in result.message


def test_invalid_json_report_is_degraded(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=NOW, report="{not json")
    result, _ = _run(tmp_path, cursor, report)
    assert result.status is Status.DEGRADED
    assert "unreadable" in result.message


def test_non_object_report_is_degraded(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=NOW, report="[1, 2, 3]")
    result, _ = _run(tmp_path, cursor, report)
    assert result.status is Status.DEGRADED
    assert "not a JSON object" in result.message


def test_stale_report_is_degraded_never_healthy(tmp_path: Path) -> None:
    stale = NOW - timedelta(seconds=REPORT_STALE_S + 60)
    cursor, report = _write(tmp_path, last_merge=NOW, report=_report_payload(report_at=stale))
    result, _ = _run(tmp_path, cursor, report)
    assert result.status is Status.DEGRADED
    assert "old" in result.message


def test_report_without_generated_at_is_degraded(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=NOW, report=_report_payload(report_at=None))
    assert _run(tmp_path, cursor, report)[0].status is Status.DEGRADED


def test_naive_report_timestamp_is_degraded(tmp_path: Path) -> None:
    payload = _report_payload(report_at=NOW)
    payload["generated_at"] = "2026-10-10T09:00:00"
    cursor, report = _write(tmp_path, last_merge=NOW, report=payload)
    assert _run(tmp_path, cursor, report)[0].status is Status.DEGRADED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open_pr_count", None),
        ("open_pr_count", True),
        ("open_pr_count", "195"),
        ("active_ci_repair_task_ids", None),
        ("storm_mode", None),
        ("storm_mode", {"failed_recent_merge_group_runs": None}),
        ("storm_mode", {"failed_recent_merge_group_runs": "x"}),
    ],
)
def test_incomplete_report_is_degraded_never_healthy(tmp_path: Path, field, value) -> None:
    # A truncated report with a valid generated_at must not read as healthy.
    payload = _report_payload(report_at=NOW)
    if value is None and field in payload:
        del payload[field]
    else:
        payload[field] = value
    cursor, report = _write(tmp_path, last_merge=NOW - timedelta(minutes=5), report=payload)
    result, _ = _run(tmp_path, cursor, report)
    assert result.status is Status.DEGRADED
    assert "lacks" in result.message


def test_missing_cursor_is_degraded_never_healthy(tmp_path: Path) -> None:
    cursor, report = _write(tmp_path, last_merge=None, report=_report_payload(report_at=NOW))
    result, _ = _run(tmp_path, cursor, report)
    assert result.status is Status.DEGRADED
    assert "cursor" in result.message


def test_empty_cursor_is_degraded(tmp_path: Path) -> None:
    cursor, report = _write(
        tmp_path, last_merge=None, report=_report_payload(report_at=NOW), cursor_text=""
    )
    assert _run(tmp_path, cursor, report)[0].status is Status.DEGRADED


def test_naive_cursor_timestamp_is_degraded(tmp_path: Path) -> None:
    cursor, report = _write(
        tmp_path,
        last_merge=None,
        report=_report_payload(report_at=NOW),
        cursor_text="2026-10-10T08:42:38",
    )
    assert _run(tmp_path, cursor, report)[0].status is Status.DEGRADED


# ── a frozen valve fails and names the test ───────────────────────────────────


def _frozen(tmp_path: Path, run_id: int = 37848439089) -> tuple[Path, Path]:
    return _write(
        tmp_path,
        last_merge=NOW - timedelta(seconds=VALVE_FAILING_S + 600),
        report=_report_payload(
            report_at=NOW,
            failed_runs=[{"merge_group_run_id": run_id, "pr_number": 5066}],
        ),
    )


def test_frozen_valve_is_failed_and_names_the_test(tmp_path: Path) -> None:
    # The 2026-10-07 shape: merge groups failing, PRs waiting, nothing merging.
    cursor, report = _frozen(tmp_path)
    result, calls = _run(tmp_path, cursor, report)
    assert result.status is Status.FAILED
    assert "merge valve failing" in result.message
    assert "195 open PRs" in result.message
    assert (
        "tests/docs/test_capability_consideration_completeness_contract.py::test_waiver_hygiene"
        in result.message
    )
    assert calls == [37848439089]


def test_failing_test_names_are_cached_per_run(tmp_path: Path) -> None:
    cursor, report = _frozen(tmp_path)
    _, first = _run(tmp_path, cursor, report)
    result, second = _run(tmp_path, cursor, report)
    assert first == [37848439089]
    assert second == []
    assert "test_waiver_hygiene" in result.message


def test_unfetchable_names_keep_the_failed_verdict(tmp_path: Path) -> None:
    def broken(run_id: int) -> str:
        raise subprocess.CalledProcessError(1, ["gh"])

    cursor, report = _frozen(tmp_path)
    result, _ = _run(tmp_path, cursor, report, fetch=broken)
    assert result.status is Status.FAILED
    assert "failing test names unavailable" in result.message
    assert "37848439089" in result.message


def test_failed_runs_with_a_recent_merge_are_not_failed(tmp_path: Path) -> None:
    cursor, report = _write(
        tmp_path,
        last_merge=NOW - timedelta(minutes=20),
        report=_report_payload(report_at=NOW, failed_runs=[{"merge_group_run_id": 1}]),
    )
    assert _run(tmp_path, cursor, report)[0].status is Status.HEALTHY


# ── stalls and quiet periods ──────────────────────────────────────────────────


def test_long_stall_without_failures_is_degraded(tmp_path: Path) -> None:
    # Holders or admission blocks: nothing failing, nothing merging.
    cursor, report = _write(
        tmp_path,
        last_merge=NOW - timedelta(seconds=FLOW_STOPPED_S + 600),
        report=_report_payload(
            report_at=NOW, holders=["capability-consideration-waivers-20260619"]
        ),
    )
    result, _ = _run(tmp_path, cursor, report)
    assert result.status is Status.DEGRADED
    assert "flow stopped" in result.message
    assert "capability-consideration-waivers-20260619" in (result.detail or "")


def test_recent_merge_is_healthy(tmp_path: Path) -> None:
    cursor, report = _write(
        tmp_path, last_merge=NOW - timedelta(minutes=20), report=_report_payload(report_at=NOW)
    )
    result, _ = _run(tmp_path, cursor, report)
    assert result.status is Status.HEALTHY
    assert "195 open PRs" in result.message


def test_quiet_with_no_open_prs_is_healthy(tmp_path: Path) -> None:
    cursor, report = _write(
        tmp_path,
        last_merge=NOW - timedelta(days=3),
        report=_report_payload(report_at=NOW, open_prs=0),
    )
    assert _run(tmp_path, cursor, report)[0].status is Status.HEALTHY


# ── the recheck command path (`python -m agents.health_monitor --check flow`) ──


@pytest.mark.parametrize(
    ("minutes_since_merge", "failed_runs", "expected"),
    [
        (20, [], Status.HEALTHY),
        (13 * 60, [], Status.DEGRADED),
        (3 * 60, [{"merge_group_run_id": 9}], Status.FAILED),
    ],
)
def test_registry_call_with_defaults_reads_the_producer_paths(
    tmp_path: Path, monkeypatch, minutes_since_merge, failed_runs, expected
) -> None:
    # The runner behind the CLI calls each registered check with no arguments.
    now = datetime.now(UTC)
    cursor, report = _write(
        tmp_path,
        last_merge=now - timedelta(minutes=minutes_since_merge),
        report=_report_payload(report_at=now, failed_runs=failed_runs),
    )
    monkeypatch.setattr(flow, "MERGE_CURSOR_PATH", cursor)
    monkeypatch.setattr(flow, "AUTOQUEUE_REPORT_PATH", report)
    monkeypatch.setattr(flow, "FAILED_TESTS_CACHE_PATH", tmp_path / "failed-tests.json")
    monkeypatch.setattr(flow, "_fetch_failed_log", lambda run_id: FAILED_LOG)
    registered = CHECK_REGISTRY["flow"][0]
    results = asyncio.run(registered())
    assert results[0].status is expected
