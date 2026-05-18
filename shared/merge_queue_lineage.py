"""Merge queue lineage and bottleneck observability.

The data written by this module is intentionally file-native JSON so
autoqueue, Obsidian dashboards, and terminal tools can read the same durable
ledger without needing a service.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

BottleneckKind = Literal[
    "queue_admission",
    "shard_long_pole",
    "repeated_setup_cost",
    "stale_synthetic_run",
    "branch_protection_check_mapping",
    "task_lifecycle_hygiene",
    "manual_checklist_blocker",
    "runner_capacity",
]

DEFAULT_TRACE_DIR = Path(os.path.expanduser("~/.cache/hapax/post-merge-traces"))
DEFAULT_LEDGER_PATH = DEFAULT_TRACE_DIR / "merge-queue-lineage.jsonl"
DEFAULT_SUMMARY_PATH = DEFAULT_TRACE_DIR / "merge-queue-summary.json"
DEFAULT_MAX_RECORDS = 200

_PR_BRANCH_RE = re.compile(r"(?:^|/)pr-(?P<number>\d+)-(?P<sha>[0-9a-f]{7,40})(?:$|[^0-9a-f])")
_PR_TITLE_RE = re.compile(r"(?:PR|pull request)\s*#?(?P<number>\d+)", flags=re.IGNORECASE)
_ISSUE_REF_RE = re.compile(r"(?<![A-Za-z0-9_-])#(?P<number>\d+)(?![A-Za-z0-9_-])")
_TASK_REF_RE = re.compile(
    r"(?:task_id\s*[:=]\s*|cc-task\s*[:=]\s*|hapax-cc-tasks/active/)"
    r"(?P<task>[A-Za-z0-9._-]+)",
    flags=re.IGNORECASE,
)
_UNCHECKED_BOX_RE = re.compile(r"^\s*[-*]\s+\[\s\]\s+(.+)$", flags=re.MULTILINE)

_SETUP_STEP_KEYWORDS = (
    "actions/checkout",
    "set up",
    "setup",
    "install ",
    "sync uv",
    "uv sync",
    "pango",
    "font",
    "system deps",
    "pnpm install",
)
_TEST_STEP_KEYWORDS = ("pytest", "full pytest", "run tests", "run full pytest shard")
_SHARD_JOB_RE = re.compile(r"(?:test-full-shard|shard\s*\(\d+/\d+\)|pytest)", re.IGNORECASE)


class StepDuration(BaseModel):
    """One GitHub Actions step duration."""

    name: str
    status: str | None = None
    conclusion: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: int | None = None


class JobDuration(BaseModel):
    """One GitHub Actions job duration."""

    name: str
    database_id: int | None = None
    status: str | None = None
    conclusion: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: int | None = None
    setup_duration_seconds: int = 0
    test_duration_seconds: int = 0
    steps: list[StepDuration] = Field(default_factory=list)


class BottleneckClassification(BaseModel):
    """Normalized bottleneck label plus the evidence that selected it."""

    kind: BottleneckKind
    reason: str
    evidence: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class QueueHoldReason(BaseModel):
    """Dashboard/autoqueue-readable hold reason."""

    pr_number: int | None = None
    kind: BottleneckKind
    reason: str
    source: str
    run_id: int | None = None
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class MergeQueueLineageRecord(BaseModel):
    """One durable merge queue lineage ledger row."""

    schema_version: int = 1
    event: Literal["merge_queue_lineage"] = "merge_queue_lineage"
    observed_at: datetime
    pr_number: int | None = None
    pr_head_sha: str | None = None
    synthetic_queue_branch: str | None = None
    synthetic_queue_sha: str | None = None
    merge_group_run_id: int
    run_attempt: int | None = None
    workflow_name: str | None = None
    run_url: str | None = None
    run_status: str | None = None
    run_conclusion: str | None = None
    run_outcome: str
    queue_entry_time: datetime | None = None
    run_started_at: datetime | None = None
    run_completed_at: datetime | None = None
    queue_hold_seconds: int | None = None
    merge_time: datetime | None = None
    job_durations: list[JobDuration] = Field(default_factory=list)
    slowest_job: JobDuration | None = None
    setup_duration_seconds: int = 0
    test_duration_seconds: int = 0
    cancellation_requeue_reason: str | None = None
    pr_remained_open_after_success: bool | None = None
    bottleneck: BottleneckClassification | None = None
    lifecycle_reasons: list[str] = Field(default_factory=list)
    prior_merge_group_runs_for_pr: int = 0
    successful_merge_group_runs_for_pr: int = 0


class MergeQueueSummary(BaseModel):
    """Dashboard/autoqueue-readable merge queue state."""

    schema_version: int = 1
    event: Literal["merge_queue_summary"] = "merge_queue_summary"
    observed_at: datetime
    records_considered: int
    latest_run_id: int | None = None
    latest_pr_number: int | None = None
    latest_run_outcome: str | None = None
    latest_bottleneck: BottleneckClassification | None = None
    bottleneck_counts: dict[str, int] = Field(default_factory=dict)
    current_queue_hold_reasons: list[QueueHoldReason] = Field(default_factory=list)
    repeated_successful_synthetic_prs: list[int] = Field(default_factory=list)
    stale_synthetic_run_ids: list[int] = Field(default_factory=list)
    slowest_recent_job: JobDuration | None = None


def parse_datetime(value: Any) -> datetime | None:
    """Parse GitHub-style timestamps, treating empty and zero dates as absent."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    raw = str(value)
    if raw.startswith("0001-01-01"):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _duration_seconds(started_at: datetime | None, completed_at: datetime | None) -> int | None:
    if started_at is None or completed_at is None:
        return None
    return max(0, int((completed_at - started_at).total_seconds()))


def _is_setup_step(name: str) -> bool:
    lower = name.lower()
    return any(keyword in lower for keyword in _SETUP_STEP_KEYWORDS)


def _is_test_step(name: str) -> bool:
    lower = name.lower()
    return any(keyword in lower for keyword in _TEST_STEP_KEYWORDS)


def _run_outcome(status: str | None, conclusion: str | None) -> str:
    if status == "completed":
        return conclusion or "completed"
    return status or conclusion or "unknown"


def pr_number_from_run(run: dict[str, Any]) -> int | None:
    """Extract a PR number from merge queue branch/title metadata."""
    branch = str(run.get("headBranch") or run.get("head_branch") or "")
    if match := _PR_BRANCH_RE.search(branch):
        return int(match.group("number"))
    for field in ("displayTitle", "display_title", "name", "workflowName", "workflow_name"):
        value = str(run.get(field) or "")
        if match := _PR_TITLE_RE.search(value):
            return int(match.group("number"))
        if match := _ISSUE_REF_RE.search(value):
            return int(match.group("number"))
    return None


def pr_head_sha_from_queue_branch(branch: str | None) -> str | None:
    """Extract the PR head SHA suffix from GitHub's readonly queue branch."""
    if not branch:
        return None
    if match := _PR_BRANCH_RE.search(branch):
        return match.group("sha")
    return None


def normalize_job(raw: dict[str, Any]) -> JobDuration:
    """Normalize a ``gh run view --json jobs`` job object."""
    started_at = parse_datetime(raw.get("startedAt") or raw.get("started_at"))
    completed_at = parse_datetime(raw.get("completedAt") or raw.get("completed_at"))
    steps: list[StepDuration] = []
    setup_seconds = 0
    test_seconds = 0
    for item in raw.get("steps") or []:
        step_started = parse_datetime(item.get("startedAt") or item.get("started_at"))
        step_completed = parse_datetime(item.get("completedAt") or item.get("completed_at"))
        duration = _duration_seconds(step_started, step_completed)
        step = StepDuration(
            name=str(item.get("name") or ""),
            status=item.get("status"),
            conclusion=item.get("conclusion"),
            started_at=step_started,
            completed_at=step_completed,
            duration_seconds=duration,
        )
        steps.append(step)
        if duration is None:
            continue
        if _is_setup_step(step.name):
            setup_seconds += duration
        if _is_test_step(step.name):
            test_seconds += duration
    return JobDuration(
        name=str(raw.get("name") or ""),
        database_id=raw.get("databaseId") or raw.get("database_id"),
        status=raw.get("status"),
        conclusion=raw.get("conclusion"),
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=_duration_seconds(started_at, completed_at),
        setup_duration_seconds=setup_seconds,
        test_duration_seconds=test_seconds,
        steps=steps,
    )


def classify_open_pr_holds(pr: dict[str, Any]) -> list[QueueHoldReason]:
    """Classify current open-PR admission blockers into explicit hold reasons."""
    number = _safe_int(pr.get("number"))
    body = str(pr.get("body") or "")
    reasons: list[QueueHoldReason] = []

    if pr.get("isDraft") is True:
        reasons.append(
            QueueHoldReason(
                pr_number=number,
                kind="queue_admission",
                reason="PR is draft",
                source="pr_state",
            )
        )

    task_refs = [match.group("task") for match in _TASK_REF_RE.finditer(body)]
    task_id = _blank_to_none(pr.get("cc_task_id"))
    task_status = _blank_to_none(pr.get("cc_task_status"))
    if task_status is not None and task_status not in {"pr_open", "done"}:
        reasons.append(
            QueueHoldReason(
                pr_number=number,
                kind="task_lifecycle_hygiene",
                reason=f"cc-task {task_id or '-'} status is {task_status}, not pr_open",
                source="cc_task_note",
                details={"task_status": task_status, "task_id": task_id},
            )
        )

    if not task_refs:
        reasons.append(
            QueueHoldReason(
                pr_number=number,
                kind="task_lifecycle_hygiene",
                reason="PR body has no cc-task link",
                source="pr_body",
            )
        )
    elif len(set(task_refs)) > 1:
        reasons.append(
            QueueHoldReason(
                pr_number=number,
                kind="task_lifecycle_hygiene",
                reason="PR body links multiple cc-tasks",
                source="pr_body",
                details={"task_link_count": len(set(task_refs))},
            )
        )

    unchecked = _UNCHECKED_BOX_RE.findall(body)
    if unchecked:
        reasons.append(
            QueueHoldReason(
                pr_number=number,
                kind="manual_checklist_blocker",
                reason=f"PR body has {len(unchecked)} unchecked checklist item(s)",
                source="pr_body",
                details={"unchecked_count": len(unchecked)},
            )
        )

    failed = _check_names(pr, failed=True)
    if failed:
        reasons.append(
            QueueHoldReason(
                pr_number=number,
                kind="queue_admission",
                reason=f"failed check(s): {', '.join(failed[:4])}",
                source="statusCheckRollup",
                details={"failed_count": len(failed)},
            )
        )

    pending = _check_names(pr, pending=True)
    if pending:
        reasons.append(
            QueueHoldReason(
                pr_number=number,
                kind="runner_capacity",
                reason=f"check(s) still pending: {', '.join(pending[:4])}",
                source="statusCheckRollup",
                details={"pending_count": len(pending)},
            )
        )

    merge_state = str(pr.get("mergeStateStatus") or "")
    if merge_state == "BLOCKED" and not failed and not pending:
        reasons.append(
            QueueHoldReason(
                pr_number=number,
                kind="branch_protection_check_mapping",
                reason="GitHub reports mergeStateStatus BLOCKED despite no failed/pending checks",
                source="mergeStateStatus",
            )
        )
    elif merge_state == "BEHIND":
        reasons.append(
            QueueHoldReason(
                pr_number=number,
                kind="queue_admission",
                reason="PR branch is behind base",
                source="mergeStateStatus",
            )
        )

    if pr.get("autoMergeRequest") is None and merge_state in {"CLEAN", "HAS_HOOKS"}:
        reasons.append(
            QueueHoldReason(
                pr_number=number,
                kind="queue_admission",
                reason="clean PR has no auto-merge request",
                source="autoMergeRequest",
            )
        )
    return reasons


def build_lineage_record(
    run: dict[str, Any],
    *,
    pr_by_number: dict[int, dict[str, Any]] | None = None,
    observed_at: datetime | None = None,
) -> MergeQueueLineageRecord:
    """Build one lineage ledger record from GitHub run and PR JSON."""
    observed_at = observed_at or datetime.now(UTC)
    pr_by_number = pr_by_number or {}
    pr_number = pr_number_from_run(run)
    pr = pr_by_number.get(pr_number or -1, {})
    synthetic_branch = run.get("headBranch") or run.get("head_branch")
    synthetic_sha = run.get("headSha") or run.get("head_sha")
    pr_head_sha = pr.get("headRefOid") or pr.get("head_ref_oid")
    pr_head_sha = pr_head_sha or pr_head_sha_from_queue_branch(str(synthetic_branch or ""))

    queue_entry_time = parse_datetime(run.get("createdAt") or run.get("created_at"))
    started_at = parse_datetime(run.get("startedAt") or run.get("started_at"))
    completed_at = parse_datetime(run.get("updatedAt") or run.get("updated_at"))
    status = _blank_to_none(run.get("status"))
    conclusion = _blank_to_none(run.get("conclusion"))
    outcome = _run_outcome(status, conclusion)
    jobs = [normalize_job(job) for job in run.get("jobs") or []]
    slowest_job = max(
        (job for job in jobs if job.duration_seconds is not None),
        key=lambda job: job.duration_seconds or 0,
        default=None,
    )
    setup_seconds = sum(job.setup_duration_seconds for job in jobs)
    test_seconds = sum(job.test_duration_seconds for job in jobs)
    merge_time = parse_datetime(pr.get("mergedAt") or pr.get("merged_at"))
    remained_open = None
    if conclusion == "success":
        remained_open = str(pr.get("state") or "").upper() == "OPEN" and merge_time is None

    lifecycle_reasons = [reason.reason for reason in classify_open_pr_holds(pr)] if pr else []
    if conclusion == "success" and remained_open:
        lifecycle_reasons.append("successful synthetic merge-group run left PR open")
    if conclusion == "cancelled":
        lifecycle_reasons.append("synthetic merge-group run was cancelled before completion")

    record = MergeQueueLineageRecord(
        observed_at=observed_at,
        pr_number=pr_number,
        pr_head_sha=pr_head_sha,
        synthetic_queue_branch=synthetic_branch,
        synthetic_queue_sha=synthetic_sha,
        merge_group_run_id=int(run.get("databaseId") or run.get("database_id") or run.get("id")),
        run_attempt=_safe_int(run.get("attempt") or run.get("runAttempt")),
        workflow_name=run.get("workflowName") or run.get("workflow_name") or run.get("name"),
        run_url=run.get("url"),
        run_status=status,
        run_conclusion=conclusion,
        run_outcome=outcome,
        queue_entry_time=queue_entry_time,
        run_started_at=started_at,
        run_completed_at=completed_at,
        queue_hold_seconds=_queue_hold_seconds(queue_entry_time, started_at, observed_at, status),
        merge_time=merge_time,
        job_durations=jobs,
        slowest_job=slowest_job,
        setup_duration_seconds=setup_seconds,
        test_duration_seconds=test_seconds,
        cancellation_requeue_reason=_cancellation_reason(conclusion),
        pr_remained_open_after_success=remained_open,
        lifecycle_reasons=lifecycle_reasons,
    )
    return record.model_copy(update={"bottleneck": classify_record_bottleneck(record)})


def annotate_run_counts(
    records: list[MergeQueueLineageRecord],
) -> list[MergeQueueLineageRecord]:
    """Fill per-PR prior/successful merge-group counts for a batch."""
    by_pr: dict[int, list[MergeQueueLineageRecord]] = defaultdict(list)
    for record in records:
        if record.pr_number is not None:
            by_pr[record.pr_number].append(record)

    counts_by_run: dict[int, tuple[int, int]] = {}
    for pr_records in by_pr.values():
        ordered = sorted(pr_records, key=lambda item: item.queue_entry_time or item.observed_at)
        prior = 0
        successes = 0
        for record in ordered:
            counts_by_run[record.merge_group_run_id] = (prior, successes)
            prior += 1
            if record.run_conclusion == "success":
                successes += 1

    out: list[MergeQueueLineageRecord] = []
    for record in records:
        prior, successes = counts_by_run.get(record.merge_group_run_id, (0, 0))
        out.append(
            record.model_copy(
                update={
                    "prior_merge_group_runs_for_pr": prior,
                    "successful_merge_group_runs_for_pr": successes,
                }
            )
        )
    return out


def classify_record_bottleneck(record: MergeQueueLineageRecord) -> BottleneckClassification | None:
    """Classify the primary bottleneck for one merge-group run."""
    if record.run_conclusion == "cancelled":
        return BottleneckClassification(
            kind="stale_synthetic_run",
            reason="merge-group run cancelled before completion",
            evidence={"run_id": record.merge_group_run_id, "pr_number": record.pr_number},
        )
    if record.pr_remained_open_after_success:
        return BottleneckClassification(
            kind="branch_protection_check_mapping",
            reason="successful synthetic merge-group run did not merge or close the PR",
            evidence={"run_id": record.merge_group_run_id, "pr_number": record.pr_number},
        )
    if record.queue_hold_seconds is not None and record.queue_hold_seconds >= 600:
        return BottleneckClassification(
            kind="runner_capacity",
            reason="merge-group run waited at least 10 minutes before job start",
            evidence={
                "run_id": record.merge_group_run_id,
                "queue_hold_seconds": record.queue_hold_seconds,
            },
        )
    if record.setup_duration_seconds >= 180:
        return BottleneckClassification(
            kind="repeated_setup_cost",
            reason="merge-group jobs spent at least 3 minutes in repeated setup steps",
            evidence={
                "run_id": record.merge_group_run_id,
                "setup_duration_seconds": record.setup_duration_seconds,
            },
        )
    if (
        record.slowest_job is not None
        and record.slowest_job.duration_seconds is not None
        and record.slowest_job.duration_seconds >= 600
        and _SHARD_JOB_RE.search(record.slowest_job.name)
    ):
        return BottleneckClassification(
            kind="shard_long_pole",
            reason="slowest merge-group pytest shard dominates run wall time",
            evidence={
                "run_id": record.merge_group_run_id,
                "slowest_job": record.slowest_job.name,
                "slowest_job_seconds": record.slowest_job.duration_seconds,
            },
        )
    if record.run_status in {"queued", "waiting", "requested"}:
        return BottleneckClassification(
            kind="runner_capacity",
            reason=f"merge-group run is still {record.run_status}",
            evidence={"run_id": record.merge_group_run_id},
        )
    return None


def build_summary(
    records: list[MergeQueueLineageRecord],
    *,
    open_prs: list[dict[str, Any]] | None = None,
    observed_at: datetime | None = None,
) -> MergeQueueSummary:
    """Build a compact summary for autoqueue/dashboard consumers."""
    observed_at = observed_at or datetime.now(UTC)
    ordered = sorted(records, key=lambda item: item.queue_entry_time or item.observed_at)
    latest = ordered[-1] if ordered else None
    bottlenecks = [record.bottleneck for record in ordered if record.bottleneck is not None]
    counts = Counter(item.kind for item in bottlenecks)
    run_hold_reasons: list[QueueHoldReason] = []
    for record in ordered:
        if record.bottleneck is None:
            continue
        run_hold_reasons.append(
            QueueHoldReason(
                pr_number=record.pr_number,
                kind=record.bottleneck.kind,
                reason=record.bottleneck.reason,
                source="merge_group_run",
                run_id=record.merge_group_run_id,
                details=record.bottleneck.evidence,
            )
        )
    open_pr_hold_reasons: list[QueueHoldReason] = []
    for pr in open_prs or []:
        open_pr_hold_reasons.extend(classify_open_pr_holds(pr))
    hold_reasons = [*open_pr_hold_reasons, *run_hold_reasons]

    successful_by_pr: dict[int, int] = defaultdict(int)
    for record in ordered:
        if record.pr_number is not None and record.run_conclusion == "success":
            successful_by_pr[record.pr_number] += 1

    slowest = max(
        (record.slowest_job for record in ordered if record.slowest_job is not None),
        key=lambda job: job.duration_seconds or 0,
        default=None,
    )
    return MergeQueueSummary(
        observed_at=observed_at,
        records_considered=len(records),
        latest_run_id=latest.merge_group_run_id if latest else None,
        latest_pr_number=latest.pr_number if latest else None,
        latest_run_outcome=latest.run_outcome if latest else None,
        latest_bottleneck=latest.bottleneck if latest else None,
        bottleneck_counts=dict(sorted(counts.items())),
        current_queue_hold_reasons=hold_reasons[:30],
        repeated_successful_synthetic_prs=sorted(
            pr for pr, count in successful_by_pr.items() if count > 1
        ),
        stale_synthetic_run_ids=[
            record.merge_group_run_id
            for record in ordered
            if record.bottleneck is not None and record.bottleneck.kind == "stale_synthetic_run"
        ],
        slowest_recent_job=slowest,
    )


def read_jsonl_records(path: Path) -> list[MergeQueueLineageRecord]:
    """Read existing lineage records, skipping malformed rows."""
    if not path.exists():
        return []
    records: list[MergeQueueLineageRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(MergeQueueLineageRecord.model_validate_json(line))
        except ValueError:
            continue
    return records


def write_jsonl_records(
    path: Path,
    records: list[MergeQueueLineageRecord],
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> None:
    """Merge records into a bounded JSONL ledger, keyed by run id."""
    max_records = max(1, max_records)
    merged: dict[int, MergeQueueLineageRecord] = {
        record.merge_group_run_id: record for record in read_jsonl_records(path)
    }
    for record in records:
        merged[record.merge_group_run_id] = record
    kept = sorted(
        merged.values(),
        key=lambda item: item.queue_entry_time or item.observed_at,
    )[-max_records:]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(
            json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n" for record in kept
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def write_summary(path: Path, summary: MergeQueueSummary) -> None:
    """Write the dashboard summary atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def load_summary(path: Path = DEFAULT_SUMMARY_PATH) -> MergeQueueSummary | None:
    """Load a dashboard summary if one exists."""
    if not path.exists():
        return None
    try:
        return MergeQueueSummary.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _check_names(pr: dict[str, Any], *, failed: bool = False, pending: bool = False) -> list[str]:
    names: list[str] = []
    for check in pr.get("statusCheckRollup") or []:
        name = str(check.get("name") or check.get("context") or "unknown")
        conclusion = str(check.get("conclusion") or check.get("state") or "").upper()
        status = str(check.get("status") or "").upper()
        if failed and conclusion in {"FAILURE", "ACTION_REQUIRED", "TIMED_OUT", "CANCELLED"}:
            names.append(name)
        if pending and (
            status in {"IN_PROGRESS", "QUEUED", "REQUESTED", "PENDING"} or not conclusion
        ):
            names.append(name)
    return names


def _queue_hold_seconds(
    queue_entry_time: datetime | None,
    started_at: datetime | None,
    observed_at: datetime,
    status: str | None,
) -> int | None:
    if queue_entry_time is None:
        return None
    end = started_at
    if end is None and status in {"queued", "waiting", "requested"}:
        end = observed_at
    return _duration_seconds(queue_entry_time, end)


def _cancellation_reason(conclusion: str | None) -> str | None:
    if conclusion != "cancelled":
        return None
    return "cancelled; likely stale synthetic queue branch or concurrency requeue"


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _blank_to_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


__all__ = [
    "DEFAULT_LEDGER_PATH",
    "DEFAULT_MAX_RECORDS",
    "DEFAULT_SUMMARY_PATH",
    "BottleneckClassification",
    "JobDuration",
    "MergeQueueLineageRecord",
    "MergeQueueSummary",
    "QueueHoldReason",
    "StepDuration",
    "annotate_run_counts",
    "build_lineage_record",
    "build_summary",
    "classify_open_pr_holds",
    "classify_record_bottleneck",
    "load_summary",
    "normalize_job",
    "pr_head_sha_from_queue_branch",
    "pr_number_from_run",
    "read_jsonl_records",
    "write_jsonl_records",
    "write_summary",
]
