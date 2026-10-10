"""Merge-plane flow: is anything actually merging?

From 2026-10-06T14:43Z to 2026-10-10T07:40Z nothing merged to main. Every merge group
failed on one expired test, and the coordinator noticed after about 46 hours, because
every probe watched an item and none watched flow. This check reads two producers that
already exist and reports flow:

* the merge watcher's cursor: the newest merged-at it has seen;
* the autoqueue's per-pass report. The verdict reads ``generated_at``, ``open_pr_count``,
  ``active_ci_repair_task_ids`` and ``storm_mode.failed_recent_merge_group_runs``; the
  detail line also shows ``queued_prs``.

Unknown is never healthy. A missing, unreadable, stale or incomplete producer is
DEGRADED. When the valve is failing, the check names the failing tests: it reads each
failed run's log once (through the gh-shaped binary, ``HAPAX_GH_BIN``) and caches the
``FAILED <nodeid>`` lines by run id.

Recheck from a shell with the existing health-monitor CLI. The verdict is the
report's ``overall_status``::

    uv run python -m agents.health_monitor --check flow --json
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group

MERGE_CURSOR_PATH = Path.home() / ".cache" / "hapax" / "cc-pr-merge-watcher-cursor.txt"
AUTOQUEUE_REPORT_PATH = (
    Path.home() / ".cache" / "hapax" / "orchestration" / "cc-pr-autoqueue-report.json"
)
FAILED_TESTS_CACHE_PATH = (
    Path.home() / ".cache" / "hapax" / "orchestration" / "flow-failed-tests.json"
)
REPO = "hapax-systems/hapax-council"

#: The autoqueue runs every few minutes; a report older than this is not current state.
REPORT_STALE_S = 30 * 60
#: PRs waiting and merge groups failing with no merge for this long: the valve is failing.
VALVE_FAILING_S = 2 * 3600
#: PRs waiting and no merge for this long: flow has stopped, whatever the cause.
FLOW_STOPPED_S = 12 * 3600
#: Failing tests named per failed run; the log fetch is bounded.
MAX_TESTS_NAMED = 5
LOG_FETCH_TIMEOUT_S = 30

_NAME = "flow.merge_plane"
_GROUP = "flow"
_FAILED_NODE_RE = re.compile(r"FAILED (tests/\S+?)(?: - |\s|$)")

LogFetcher = Callable[[int], str]


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


def _fetch_failed_log(run_id: int) -> str:
    gh = os.environ.get("HAPAX_GH_BIN") or "gh"
    completed = subprocess.run(
        [gh, "run", "view", str(run_id), "--repo", REPO, "--log-failed"],
        capture_output=True,
        text=True,
        timeout=LOG_FETCH_TIMEOUT_S,
        check=True,
    )
    return completed.stdout


def failing_tests(run_id: int, cache_path: Path, fetch: LogFetcher) -> list[str] | None:
    """The failing test node ids for one run, from the cache or one log fetch.

    Returns None when the names cannot be obtained. Absent names never soften the verdict.
    """
    key = str(run_id)
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    cached = cache.get(key)
    if isinstance(cached, dict) and isinstance(cached.get("tests"), list):
        return [str(name) for name in cached["tests"]]
    try:
        log = fetch(run_id)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    names: list[str] = []
    for match in _FAILED_NODE_RE.finditer(log):
        if match.group(1) not in names:
            names.append(match.group(1))
        if len(names) >= MAX_TESTS_NAMED:
            break
    cache[key] = {"tests": names, "fetched_at": datetime.now(UTC).isoformat()}
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_name(cache_path.name + ".tmp")
        tmp.write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")
        tmp.replace(cache_path)
    except OSError:
        pass  # the names were obtained; a cache that cannot be written only costs a refetch
    return names


def _run_id(run: object) -> int | None:
    if not isinstance(run, dict):
        return None
    for key in ("merge_group_run_id", "run_id", "id"):
        value = run.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


@check_group("flow")
async def check_merge_flow(
    cursor_path: Path | None = None,
    report_path: Path | None = None,
    now: datetime | None = None,
    tests_cache_path: Path | None = None,
    fetch_log: LogFetcher | None = None,
) -> list[CheckResult]:
    t = time.monotonic()
    cursor_path = cursor_path or MERGE_CURSOR_PATH
    report_path = report_path or AUTOQUEUE_REPORT_PATH
    tests_cache_path = tests_cache_path or FAILED_TESTS_CACHE_PATH
    fetch_log = fetch_log or _fetch_failed_log
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
    if not isinstance(report, dict):
        return _result(
            Status.DEGRADED,
            "flow unknown: autoqueue report is not a JSON object",
            t,
            remediation="check hapax-cc-pr-autoqueue.service output",
        )
    generated = _parse_instant(report.get("generated_at"))
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

    open_prs = report.get("open_pr_count")
    holders = report.get("active_ci_repair_task_ids")
    storm = report.get("storm_mode")
    failed_runs = storm.get("failed_recent_merge_group_runs") if isinstance(storm, dict) else None
    missing = [
        name
        for name, ok in (
            ("open_pr_count", isinstance(open_prs, int) and not isinstance(open_prs, bool)),
            ("active_ci_repair_task_ids", isinstance(holders, list)),
            ("storm_mode.failed_recent_merge_group_runs", isinstance(failed_runs, list)),
        )
        if not ok
    ]
    if missing:
        return _result(
            Status.DEGRADED,
            f"flow unknown: autoqueue report lacks {', '.join(missing)}",
            t,
            remediation="check hapax-cc-pr-autoqueue.service output; an incomplete report is not flow",
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

    queued = report.get("queued_prs")
    since_merge = (now - last_merge).total_seconds()
    detail = (
        f"last merge {last_merge.isoformat()} ({_hours(since_merge)} ago); open PRs {open_prs}; "
        f"queued {len(queued) if isinstance(queued, list) else '?'}; CI-repair holders {holders}; "
        f"recent failed merge groups {len(failed_runs)}; report {generated.isoformat()}"
    )

    if open_prs > 0 and failed_runs and since_merge > VALVE_FAILING_S:
        named: list[str] = []
        unavailable: list[int] = []
        for run in failed_runs:
            run_id = _run_id(run)
            if run_id is None:
                continue
            tests = failing_tests(run_id, tests_cache_path, fetch_log)
            if tests is None:
                unavailable.append(run_id)
                continue
            named.extend(name for name in tests if name not in named)
        if named:
            tests_text = "failing: " + ", ".join(named[:MAX_TESTS_NAMED])
        else:
            tests_text = "failing test names unavailable" + (
                f" (log fetch failed for run {', '.join(str(r) for r in unavailable)})"
                if unavailable
                else ""
            )
        return _result(
            Status.FAILED,
            f"merge valve failing: {len(failed_runs)} failed merge group(s), "
            f"no merge for {_hours(since_merge)}, {open_prs} open PRs; {tests_text}",
            t,
            detail=detail,
            remediation=(
                "repair the named test on main, or read it: gh run list --event merge_group "
                "--workflow CI --limit 1, then gh run view <id> --log-failed"
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
