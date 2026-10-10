"""Merge-plane flow: is anything actually merging?

From 2026-10-06T14:43Z to 2026-10-10T07:40Z nothing merged to main. Every merge group
failed on one expired test, and the coordinator noticed after about 46 hours, because
every probe watched an item and none watched flow. This check reads two producers that
already exist and reports flow:

* the merge watcher's cursor: the newest merged-at it has seen;
* the autoqueue's per-pass report: open PRs, CI-repair holders, recent failed merge
  groups, and when it was generated.

Unknown is never healthy. A missing, unreadable or stale producer is DEGRADED.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group

MERGE_CURSOR_PATH = Path.home() / ".cache" / "hapax" / "cc-pr-merge-watcher-cursor.txt"
AUTOQUEUE_REPORT_PATH = (
    Path.home() / ".cache" / "hapax" / "orchestration" / "cc-pr-autoqueue-report.json"
)

#: The autoqueue runs every few minutes; a report older than this is not current state.
REPORT_STALE_S = 30 * 60
#: PRs waiting and merge groups failing with no merge for this long: the valve is failing.
VALVE_FAILING_S = 2 * 3600
#: PRs waiting and no merge for this long: flow has stopped, whatever the cause.
FLOW_STOPPED_S = 12 * 3600

_NAME = "flow.merge_plane"
_GROUP = "flow"


def _parse_instant(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _hours(seconds: float) -> str:
    return f"{seconds / 3600:.1f}h"


def _result(status: Status, message: str, start: float, **extra: str) -> list[CheckResult]:
    return [
        CheckResult(
            name=_NAME,
            group=_GROUP,
            status=status,
            message=message,
            duration_ms=_u._timed(start),
            **extra,
        )
    ]


@check_group("flow")
async def check_merge_flow(
    cursor_path: Path | None = None,
    report_path: Path | None = None,
    now: datetime | None = None,
) -> list[CheckResult]:
    t = time.monotonic()
    cursor_path = cursor_path or MERGE_CURSOR_PATH
    report_path = report_path or AUTOQUEUE_REPORT_PATH
    now = now or datetime.now(UTC)

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _result(
            Status.DEGRADED,
            f"flow unknown: autoqueue report unreadable ({type(exc).__name__})",
            t,
            remediation=f"check hapax-cc-pr-autoqueue.service; expected {report_path}",
        )
    generated = _parse_instant(report.get("generated_at") if isinstance(report, dict) else None)
    if generated is None:
        return _result(
            Status.DEGRADED,
            "flow unknown: autoqueue report has no generated_at",
            t,
            remediation="check hapax-cc-pr-autoqueue.service output",
        )
    report_age = (now - generated).total_seconds()
    if report_age > REPORT_STALE_S:
        return _result(
            Status.DEGRADED,
            f"flow unknown: autoqueue report is {_hours(report_age)} old",
            t,
            remediation="check the hapax-cc-pr-autoqueue timer and service; a stale report is not flow",
        )

    try:
        last_merge = _parse_instant(cursor_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return _result(
            Status.DEGRADED,
            f"flow unknown: merge-watcher cursor unreadable ({type(exc).__name__})",
            t,
            remediation=f"check hapax-cc-pr-merge-watcher.service; expected {cursor_path}",
        )
    if last_merge is None:
        return _result(
            Status.DEGRADED,
            "flow unknown: merge-watcher cursor holds no timestamp",
            t,
            remediation="check hapax-cc-pr-merge-watcher.service",
        )

    open_prs = report.get("open_pr_count")
    open_prs = open_prs if isinstance(open_prs, int) and not isinstance(open_prs, bool) else 0
    holders = report.get("active_ci_repair_task_ids") or []
    storm = report.get("storm_mode") or {}
    failed_runs = storm.get("failed_recent_merge_group_runs") or []
    since_merge = (now - last_merge).total_seconds()
    detail = (
        f"last merge {last_merge.isoformat()} ({_hours(since_merge)} ago); open PRs {open_prs}; "
        f"queued {len(report.get('queued_prs') or [])}; CI-repair holders {list(holders)}; "
        f"recent failed merge groups {len(failed_runs)}; report {generated.isoformat()}"
    )

    if open_prs > 0 and failed_runs and since_merge > VALVE_FAILING_S:
        return _result(
            Status.FAILED,
            f"merge valve failing: {len(failed_runs)} failed merge group(s), "
            f"no merge for {_hours(since_merge)}, {open_prs} open PRs",
            t,
            detail=detail,
            remediation=(
                "read the failing test: gh run list --event merge_group --workflow CI --limit 1, "
                "then gh run view <id> --log-failed"
            ),
        )
    if open_prs > 0 and since_merge > FLOW_STOPPED_S:
        return _result(
            Status.DEGRADED,
            f"flow stopped: no merge for {_hours(since_merge)} with {open_prs} open PRs",
            t,
            detail=detail,
            remediation="find the blocker: CI-repair holders, admission reasons, review dossiers",
        )
    return _result(
        Status.HEALTHY,
        f"last merge {_hours(since_merge)} ago; {open_prs} open PRs",
        t,
        detail=detail,
    )
