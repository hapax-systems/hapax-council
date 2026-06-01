#!/usr/bin/env python3
"""cc-pr-autoqueue — governed PR auto-queue reconciler.

The merge queue should not depend on a human/session remembering to run
``gh pr merge`` after a governed PR is ready. This reconciler scans open PRs,
matches each PR to a cc-task in the local Obsidian vault, and ARMS auto-merge
only when Hapax governance and GitHub protection state both pass.

Arm-only (task reform-native-merge-queue): the sole positive GitHub mutation is
one idempotent ``gh pr merge --auto --squash``. GitHub's native merge queue then
owns batching, speculative ``gh-readonly-queue`` branches, auto-rebase, and
bisect-on-failure — this script no longer issues a direct ``--merge`` or manages
the queue itself, which previously raced GitHub's own batching and stranded PRs.

Usage::

    uv run python scripts/cc-pr-autoqueue.py
    uv run python scripts/cc-pr-autoqueue.py --apply
    HAPAX_CC_PR_AUTOQUEUE_OFF=1 uv run python scripts/cc-pr-autoqueue.py --apply

Default mode is a dry-run report. ``--apply`` performs the GitHub mutation.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.merge_queue_lineage import (  # noqa: E402
    DEFAULT_LEDGER_PATH,
    DEFAULT_QUARANTINE_PATH,
    FleetThrottlePolicy,
    ThrottleDecision,
    active_quarantined_pr_numbers,
    bisection_plan_for_failed_runs,
    decide_fleet_throttle,
    read_jsonl_records,
    read_quarantine,
    recommend_max_entries_to_build,
    reconcile_flake_quarantines,
    write_quarantine,
)
from shared.release_gate import evaluate_avsdlc_release_gate  # noqa: E402
from shared.sdlc_lifecycle import (  # noqa: E402
    TASK_MERGE_READY_STATUSES,
    apply_release_auto_arm,
    assess_release_auto_arm,
    task_closure_validity,
)

LOG = logging.getLogger("cc-pr-autoqueue")

DEFAULT_REPO = "hapax-systems/hapax-council"
DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
KILLSWITCH_ENVS = ("HAPAX_CC_PR_AUTOQUEUE_OFF", "HAPAX_CC_HYGIENE_OFF")

PASS_STATES = {"SUCCESS", "SKIPPED", "NEUTRAL"}
FAIL_STATES = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
DIRTY_MERGE_STATES = {"DIRTY"}
UNCHECKED_PR_CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[\s\]\s+(?P<text>.+?)\s*$")
NON_BLOCKING_CHECKBOX_RE = re.compile(
    r"\b(optional|non[-_\s]?blocking|informational|follow[-_\s]?up|stretch)\b",
    re.IGNORECASE,
)
# Sourced from the canonical SSOT so the autoqueue and the cc-task gate agree on
# the ready family (shared/sdlc_lifecycle.py TASK_MERGE_READY_STATUSES). The two
# fulfilling-closed states stay admissible for closeout reconciliation.
ACTIVE_READY_STATUSES = set(TASK_MERGE_READY_STATUSES) | {"done", "completed"}
ACTIVE_WORK_STATUSES = ACTIVE_READY_STATUSES | {"claimed", "in_progress"}
CLOSED_READY_STATUSES = {"done", "completed", "complete", "closed", "fulfilled"}
HOLD_LABEL_RE = re.compile(
    r"(?:^|[-_\s])(hold|do[-_\s]?not[-_\s]?merge|manual[-_\s]?merge|blocked|wip)(?:$|[-_\s])",
    re.IGNORECASE,
)
DEFAULT_REQUIRED_CHECKS = ("lint", "test", "typecheck", "web-build", "vscode-build")
AUTOQUEUE_ADMISSION_CONTEXT = "hapax/autoqueue-admission"
AUTOQUEUE_IGNORED_CHECK_CONTEXTS = {AUTOQUEUE_ADMISSION_CONTEXT, "pr-admission"}
CI_REPAIR_KINDS = {"cicd-speedup", "ci-repair", "ci-speedup", "merge-queue-repair"}
CI_REPAIR_TAGS = {"cicd", "ci", "autoqueue"}
INDEPENDENT_QUEUE_ADMISSION = {"independent", "independent_route"}
# Open-PR COUNT is advisory-only — it raises a "busy" signal but NEVER freezes
# admission (FM-3). The only freeze is failure-RATE based (decide_fleet_throttle).
# The old ``*_STORM_OPEN_PR_THRESHOLD`` naming implied a count freeze that no
# longer exists; the advisory name is canonical, the storm alias is deprecated.
DEFAULT_ADVISORY_OPEN_PR_COUNT = 8
DEFAULT_STORM_OPEN_PR_THRESHOLD = DEFAULT_ADVISORY_OPEN_PR_COUNT  # deprecated alias
DEFAULT_STORM_FAILED_MERGE_GROUP_THRESHOLD = 1
DEFAULT_STORM_RECENT_RUN_LIMIT = 20
STORM_MAX_ENTRIES_TO_BUILD = 1
STEADY_MAX_ENTRIES_TO_BUILD = 6
FAILED_MERGE_GROUP_CONCLUSIONS = {"failure", "timed_out", "startup_failure", "cancelled"}

# Shared-file epic serialization — single-lane affinity (CASE-SBCL-CLOG-COORD-001).
# The CLOG/Trainyard cockpit epic is a parallel dependency DAG whose branches all
# mutate one shared file (src/dashboard.lisp); two lanes editing it concurrently
# merge-conflict by construction (dependency closure alone does not serialize the
# siblings). A task joins a serialized epic via an explicit ``epic_serialize``
# frontmatter field OR by its ``parent_spec`` basename matching the registry
# below — so an existing epic is covered without editing every member note. The
# autoqueue then holds admission of an epic PR while a sibling epic task is
# concurrently in flight in a DIFFERENT lane (the actual hazard); same-lane serial
# work is never held, and a deterministic lowest-PR tiebreak keeps two
# different-lane epic PRs from dead-holding each other.
SHARED_FILE_EPIC_PARENT_SPECS: dict[str, str] = {
    # parent_spec basename -> serialized-epic id (the shared file it contends on).
    #
    # Emptied 2026-06-01 (task reform-native-merge-queue): the native GitHub merge
    # queue serializes shared-file contention through its speculative
    # gh-readonly-queue branches (auto-rebase + bisect-on-failure), so a
    # pre-admission affinity hold is no longer needed to keep two different-lane
    # epic PRs from merge-conflicting. Re-add an entry here only to re-enable the
    # local pre-queue hold for a specific shared-file epic.
}
EPIC_INFLIGHT_STATUSES = frozenset(
    {"claimed", "in_progress", "pr_open", "in_review", "merge_queue", "ready_for_merge"}
)
EPIC_UNASSIGNED_LANES = {"unassigned", "null", "none", "~", ""}


def default_repo_root() -> Path:
    raw = (
        os.environ.get("HAPAX_CC_TASK_TOOL_REPO_ROOT")
        or os.environ.get("HAPAX_SOURCE_ACTIVATE_WORKTREE")
        or str(Path.home() / ".cache" / "hapax" / "source-activation" / "worktree")
    )
    return Path(raw).expanduser()


@dataclass(frozen=True)
class CheckSummary:
    passed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def has_pending(self) -> bool:
        return bool(self.pending)

    @property
    def observed(self) -> set[str]:
        return set(self.passed) | set(self.pending) | set(self.failed)


@dataclass(frozen=True)
class PullRequest:
    number: int
    node_id: str | None
    title: str
    head_ref: str
    head_sha: str | None
    body: str
    is_draft: bool
    merge_state_status: str
    labels: tuple[str, ...]
    review_decision: str | None
    auto_merge_enabled: bool
    check_summary: CheckSummary


@dataclass(frozen=True)
class TaskNote:
    task_id: str
    path: Path
    folder: str
    status: str
    pr: int | None
    branch: str | None
    authority_case: str | None
    parent_spec: str | None
    route_metadata_schema: int | None
    priority: str | None
    kind: str | None
    tags: tuple[str, ...] = ()
    queue_admission: str | None = None
    assigned_to: str | None = None
    lane_affinity: str | None = None
    epic_serialize: str | None = None
    frontmatter: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    pr: PullRequest
    action: str
    task: TaskNote | None = None
    tasks: tuple[TaskNote, ...] = ()
    reasons: tuple[str, ...] = ()
    auto_arm: bool = False

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "pr": self.pr.number,
            "title": self.pr.title,
            "head_ref": self.pr.head_ref,
            "action": self.action,
        }
        if self.task is not None:
            out["task_id"] = self.task.task_id
            out["task_path"] = str(self.task.path)
            out["task_status"] = self.task.status
        if len(self.tasks) > 1:
            out["task_ids"] = [task.task_id for task in self.tasks]
            out["task_paths"] = [str(task.path) for task in self.tasks]
        if self.reasons:
            out["reasons"] = list(self.reasons)
        if self.auto_arm:
            out["auto_arm"] = True
        return out


@dataclass(frozen=True)
class StormMode:
    active: bool
    reasons: tuple[str, ...]
    open_pr_count: int
    queued_pr_count: int
    blocked_queued_pr_count: int
    blocked_queued_prs: tuple[dict[str, Any], ...]
    failed_recent_merge_group_runs: tuple[dict[str, Any], ...]
    recommended_max_entries_to_build: int
    recommended_throttle_state: str
    failure_rate: float
    failure_rate_samples: int
    rate_frozen: bool
    recommended_bisections: tuple[dict[str, Any], ...] = ()

    def as_dict(self, *, repo: str) -> dict[str, Any]:
        return {
            "active": self.active,
            "mode": "rate_freeze" if self.active else self.recommended_throttle_state,
            "reasons": list(self.reasons),
            "open_pr_count": self.open_pr_count,
            "queued_pr_count": self.queued_pr_count,
            "blocked_queued_pr_count": self.blocked_queued_pr_count,
            "blocked_queued_prs": list(self.blocked_queued_prs),
            "failed_recent_merge_group_run_count": len(self.failed_recent_merge_group_runs),
            "failed_recent_merge_group_runs": list(self.failed_recent_merge_group_runs),
            "recommended_bisections": list(self.recommended_bisections),
            "failure_rate": self.failure_rate,
            "failure_rate_samples": self.failure_rate_samples,
            "rate_frozen": self.rate_frozen,
            "recommended_throttle": {
                "state": self.recommended_throttle_state,
                "max_entries_to_build": self.recommended_max_entries_to_build,
                "mutation_performed": False,
                "coordinator_action": self._coordinator_action(repo=repo),
            },
        }

    def _coordinator_action(self, *, repo: str) -> dict[str, Any] | None:
        if not self.active:
            return None
        return {
            "reason": "failure-rate freeze is non-mutating; ruleset updates replace live rule definitions",
            "api": {
                "method": "PATCH",
                "path": f"/repos/{repo}/rulesets/<ruleset_id>",
                "payload_patch": {
                    "rules": [
                        {
                            "type": "merge_queue",
                            "parameters": {
                                "max_entries_to_build": self.recommended_max_entries_to_build,
                            },
                        }
                    ]
                },
            },
            "risks": [
                "fetch the current ruleset first and patch the full existing payload",
                "do not remove required checks, required reviews, or branch protection rules",
                "restore steady-state max_entries_to_build only after the failure rate clears",
            ],
        }


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    return text


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(text for item in value if (text := _scalar(item)))
    text = _scalar(value)
    return (text,) if text else ()


def _check_name(item: dict[str, Any]) -> str:
    return (
        _scalar(item.get("name"))
        or _scalar(item.get("context"))
        or _scalar(item.get("workflowName"))
        or _scalar(
            (item.get("app") or {}).get("name") if isinstance(item.get("app"), dict) else None
        )
        or "unnamed-check"
    )


def summarize_checks(items: list[dict[str, Any]]) -> CheckSummary:
    passed: list[str] = []
    pending: list[str] = []
    failed: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            pending.append("malformed-check")
            continue
        name = _check_name(item)
        if name in AUTOQUEUE_IGNORED_CHECK_CONTEXTS:
            continue
        raw_state = item.get("conclusion") or item.get("state") or item.get("status")
        state = str(raw_state or "").upper()
        if state in PASS_STATES:
            passed.append(name)
        elif state in FAIL_STATES:
            failed.append(name)
        else:
            pending.append(name)
    return CheckSummary(passed=passed, pending=pending, failed=failed)


def _labels_from_payload(item: dict[str, Any]) -> tuple[str, ...]:
    labels = item.get("labels") or []
    out: list[str] = []
    if isinstance(labels, list):
        for label in labels:
            if isinstance(label, dict):
                name = _scalar(label.get("name"))
            else:
                name = _scalar(label)
            if name:
                out.append(name)
    return tuple(out)


def _parse_pr(item: dict[str, Any]) -> PullRequest | None:
    try:
        number = int(item["number"])
    except (KeyError, TypeError, ValueError):
        return None
    return PullRequest(
        number=number,
        node_id=_scalar(item.get("id")),
        title=_scalar(item.get("title")) or "",
        head_ref=_scalar(item.get("headRefName")) or "",
        body=str(item.get("body") or ""),
        is_draft=bool(item.get("isDraft")),
        head_sha=_scalar(item.get("headRefOid")),
        merge_state_status=str(item.get("mergeStateStatus") or "").upper(),
        labels=_labels_from_payload(item),
        review_decision=_scalar(item.get("reviewDecision")),
        auto_merge_enabled=bool(item.get("autoMergeRequest")),
        check_summary=summarize_checks(item.get("statusCheckRollup") or []),
    )


def fetch_open_prs(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    limit: int = 100,
    runner: Any = None,
) -> list[PullRequest]:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        str(limit),
        "--json",
        ",".join(
            [
                "number",
                "id",
                "title",
                "body",
                "headRefName",
                "headRefOid",
                "isDraft",
                "mergeStateStatus",
                "labels",
                "reviewDecision",
                "autoMergeRequest",
                "statusCheckRollup",
            ]
        ),
    ]
    proc = runner(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        LOG.error("gh pr list failed (rc=%d): %s", proc.returncode, proc.stderr.strip())
        return []
    try:
        raw = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        LOG.error("gh pr list emitted non-JSON: %s", exc)
        return []
    if not isinstance(raw, list):
        LOG.error("gh pr list emitted %s, expected list", type(raw).__name__)
        return []
    prs: list[PullRequest] = []
    for item in raw:
        if isinstance(item, dict):
            pr = _parse_pr(item)
            if pr is not None:
                prs.append(pr)
    return prs


def fetch_merge_queue_pr_numbers(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
) -> set[int]:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    owner, name = repo.split("/", 1)
    query = (
        "query($owner:String!,$repo:String!){repository(owner:$owner,name:$repo){"
        "mergeQueue{entries(first:100){nodes{pullRequest{number}}}}}}"
    )
    cmd = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={query}",
        "-f",
        f"owner={owner}",
        "-f",
        f"repo={name}",
    ]
    proc = runner(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        LOG.error("gh merge queue query failed (rc=%d): %s", proc.returncode, proc.stderr.strip())
        return set()
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        LOG.error("gh merge queue query emitted non-JSON: %s", exc)
        return set()
    nodes = (
        payload.get("data", {})
        .get("repository", {})
        .get("mergeQueue", {})
        .get("entries", {})
        .get("nodes", [])
    )
    queued: set[int] = set()
    if isinstance(nodes, list):
        for node in nodes:
            try:
                number = int(node["pullRequest"]["number"])
            except (KeyError, TypeError, ValueError):
                continue
            queued.add(number)
    return queued


def _frontmatter(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        parsed = yaml.safe_load(text[3:end].strip()) or {}
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def load_task_notes(vault_root: Path = DEFAULT_VAULT_ROOT) -> list[TaskNote]:
    notes: list[TaskNote] = []
    for folder in ("active", "closed"):
        root = vault_root / folder
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            fm = _frontmatter(path)
            if not fm or fm.get("type") != "cc-task":
                continue
            task_id = _scalar(fm.get("task_id"))
            if not task_id:
                continue
            notes.append(
                TaskNote(
                    task_id=task_id,
                    path=path,
                    folder=folder,
                    status=(_scalar(fm.get("status")) or "").lower(),
                    pr=_int_or_none(fm.get("pr")),
                    branch=_scalar(fm.get("branch")),
                    authority_case=_scalar(fm.get("authority_case") or fm.get("case_id")),
                    parent_spec=_scalar(fm.get("parent_spec")),
                    route_metadata_schema=_int_or_none(fm.get("route_metadata_schema")),
                    priority=(_scalar(fm.get("priority")) or "").lower() or None,
                    kind=(_scalar(fm.get("kind")) or "").lower() or None,
                    tags=tuple(tag.lower() for tag in _string_tuple(fm.get("tags"))),
                    queue_admission=((_scalar(fm.get("queue_admission")) or "").lower() or None),
                    assigned_to=_scalar(fm.get("assigned_to")),
                    lane_affinity=_scalar(fm.get("lane_affinity")),
                    epic_serialize=_scalar(fm.get("epic_serialize")),
                    frontmatter=dict(fm),
                )
            )
    return notes


def _matching_tasks(pr: PullRequest, tasks: list[TaskNote]) -> list[TaskNote]:
    by_pr = [task for task in tasks if task.pr == pr.number]
    if by_pr:
        return by_pr
    return [task for task in tasks if task.branch == pr.head_ref]


def _task_blockers(
    task: TaskNote,
    *,
    require_route_metadata: bool,
    open_pr_number: int | None = None,
) -> list[str]:
    blockers: list[str] = []
    if not task.authority_case:
        blockers.append("task_missing_authority_case")
    if not task.parent_spec:
        blockers.append("task_missing_parent_spec")
    if require_route_metadata and task.route_metadata_schema != 1:
        blockers.append("task_missing_route_metadata_schema_1")

    if task.folder == "closed":
        if task.status not in CLOSED_READY_STATUSES:
            blockers.append(f"closed_task_status_not_ready:{task.status or 'missing'}")
        try:
            note_text = task.path.read_text(encoding="utf-8")
        except OSError as exc:
            blockers.append(f"closed_task_unreadable:{exc}")
        else:

            def _pr_state_lookup(pr_number: str) -> str:
                if open_pr_number is not None and pr_number == str(open_pr_number):
                    return "open"
                return "unknown"

            validity = task_closure_validity(
                note_text,
                pr_state_lookup=_pr_state_lookup,
                require_route_metadata=require_route_metadata,
            )
            blockers.extend(f"closed_task_closure_invalid:{reason}" for reason in validity.blockers)
            if task.pr is None and open_pr_number is not None:
                blockers.append(f"closed_task_linked_to_open_pr_without_pr_field:{open_pr_number}")
    elif task.status not in ACTIVE_READY_STATUSES:
        blockers.append(f"active_task_status_not_ready:{task.status or 'missing'}")

    avsdlc_gate = evaluate_avsdlc_release_gate(task.frontmatter)
    blockers.extend(f"avsdlc_release_gate:{blocker}" for blocker in avsdlc_gate.blockers)
    return blockers


def _is_ci_repair_task(task: TaskNote) -> bool:
    if task.folder != "active":
        return False
    if task.status not in ACTIVE_WORK_STATUSES:
        return False
    if task.priority not in {"p0", "p1"}:
        return False
    if task.kind in CI_REPAIR_KINDS:
        return True
    return bool(set(task.tags) & CI_REPAIR_TAGS)


def _has_independent_queue_admission(task: TaskNote) -> bool:
    return task.route_metadata_schema == 1 and task.queue_admission in INDEPENDENT_QUEUE_ADMISSION


def _active_ci_repair_task_ids(tasks: list[TaskNote]) -> tuple[str, ...]:
    return tuple(task.task_id for task in tasks if _is_ci_repair_task(task))


def _is_storm_exempt_task(task: TaskNote) -> bool:
    return _is_ci_repair_task(task) or _has_independent_queue_admission(task)


def unchecked_blocking_checkboxes(body: str) -> list[str]:
    blockers: list[str] = []
    for line in body.splitlines():
        match = UNCHECKED_PR_CHECKBOX_RE.match(line)
        if not match:
            continue
        text = match.group("text").strip()
        if NON_BLOCKING_CHECKBOX_RE.search(text):
            continue
        blockers.append(text)
    return blockers


def _epic_serialize_key(task: TaskNote) -> str | None:
    """The serialized shared-file epic a task belongs to, or ``None``.

    An explicit ``epic_serialize`` frontmatter value wins; otherwise the task's
    ``parent_spec`` basename is matched against :data:`SHARED_FILE_EPIC_PARENT_SPECS`
    so every member of a known epic is covered without editing each note.
    """
    if task.epic_serialize:
        return task.epic_serialize
    if task.parent_spec:
        return SHARED_FILE_EPIC_PARENT_SPECS.get(Path(task.parent_spec).name)
    return None


def _task_lane(task: TaskNote) -> str | None:
    """The lane a task is worked in: the live assignee, else declared affinity."""
    for candidate in (task.assigned_to, task.lane_affinity):
        lane = (candidate or "").strip().lower()
        if lane and lane not in EPIC_UNASSIGNED_LANES:
            return lane
    return None


def _epic_sibling_in_flight(task: TaskNote) -> bool:
    """Whether an epic sibling is actively contending for the shared file.

    In flight = active (not terminal) and either carrying an in-flight status or
    an open PR. Merged/closed predecessors and not-yet-started (offered/ready
    without a PR) siblings never contend.
    """
    if task.folder != "active" or task.status in CLOSED_READY_STATUSES:
        return False
    return task.status in EPIC_INFLIGHT_STATUSES or task.pr is not None


def shared_file_epic_affinity_blockers(
    matched_tasks: tuple[TaskNote, ...],
    all_tasks: list[TaskNote],
    *,
    pr_number: int | None,
) -> list[str]:
    """Single-lane-affinity holds for shared-file epic PRs (CASE-SBCL-CLOG-COORD-001).

    Hold this PR when a sibling in the same serialized epic is concurrently in
    flight in a DIFFERENT lane and is "ahead" — mid-edit with no PR yet, or
    carrying an earlier (lower-numbered) PR. Same-lane work, lane-ambiguous
    siblings, and terminal siblings never hold; the lowest-PR rule keeps two
    different-lane epic PRs from dead-holding each other.
    """
    blockers: list[str] = []
    seen: set[str] = set()
    for task in matched_tasks:
        epic = _epic_serialize_key(task)
        if epic is None:
            continue
        task_lane = _task_lane(task)
        if task_lane is None:
            continue
        for sibling in all_tasks:
            if sibling.task_id == task.task_id or _epic_serialize_key(sibling) != epic:
                continue
            if not _epic_sibling_in_flight(sibling):
                continue
            sibling_lane = _task_lane(sibling)
            if sibling_lane is None or sibling_lane == task_lane:
                continue  # same lane (serial) or lane unknown — not the hazard
            ahead = sibling.pr is None or (pr_number is not None and sibling.pr < pr_number)
            if not ahead:
                continue
            reason = (
                f"shared_file_epic_affinity_hold:{epic}:"
                f"{sibling.task_id}@{sibling_lane}:{sibling.status or 'unknown'}"
            )
            if reason not in seen:
                seen.add(reason)
                blockers.append(reason)
    return blockers


def classify_pr(
    pr: PullRequest,
    *,
    tasks: list[TaskNote],
    queued_prs: set[int],
    require_route_metadata: bool = True,
    include_pending_auto: bool = True,
    required_checks: tuple[str, ...] = DEFAULT_REQUIRED_CHECKS,
    active_ci_repair_task_ids: tuple[str, ...] = (),
    storm_admission_active: bool = False,
    storm_reasons: tuple[str, ...] = (),
) -> Decision:
    reasons: list[str] = []
    if pr.is_draft:
        reasons.append("draft")
    queued = pr.number in queued_prs
    if pr.merge_state_status in DIRTY_MERGE_STATES:
        reasons.append(f"merge_state:{pr.merge_state_status or 'missing'}")
    elif pr.merge_state_status == "UNKNOWN" and not queued and not pr.check_summary.has_pending:
        reasons.append("merge_state:UNKNOWN")
    if pr.review_decision and pr.review_decision.upper() in {
        "CHANGES_REQUESTED",
        "REVIEW_REQUIRED",
    }:
        reasons.append(f"review_decision:{pr.review_decision}")
    hold_labels = [label for label in pr.labels if HOLD_LABEL_RE.search(label)]
    if hold_labels:
        reasons.append("hold_labels:" + ",".join(hold_labels))
    unchecked = unchecked_blocking_checkboxes(pr.body)
    if unchecked:
        reasons.append("unchecked_pr_checklist:" + " | ".join(unchecked))
    if not pr.check_summary.passed and not pr.check_summary.pending and not pr.check_summary.failed:
        reasons.append("no_status_checks")
    missing_required = [
        check for check in required_checks if check not in pr.check_summary.observed
    ]
    if missing_required:
        reasons.append("missing_required_checks:" + ",".join(missing_required))
    if pr.check_summary.failed:
        reasons.append("failed_checks:" + ",".join(pr.check_summary.failed))

    matches = _matching_tasks(pr, tasks)
    matched_tasks = tuple(matches)
    task: TaskNote | None = matches[0] if len(matches) == 1 else None
    if not matches:
        reasons.append("missing_cc_task_link")
    else:
        for matched_task in matches:
            blockers = _task_blockers(
                matched_task,
                require_route_metadata=require_route_metadata,
                open_pr_number=pr.number,
            )
            if len(matches) == 1:
                reasons.extend(blockers)
            else:
                reasons.extend(
                    f"task_blocker:{matched_task.task_id}:{blocker}" for blocker in blockers
                )

    reasons.extend(shared_file_epic_affinity_blockers(matched_tasks, tasks, pr_number=pr.number))

    if (
        active_ci_repair_task_ids
        and not queued
        and matches
        and not any(_is_ci_repair_task(matched_task) for matched_task in matches)
        and not any(_has_independent_queue_admission(matched_task) for matched_task in matches)
    ):
        reasons.append(
            "admission_stabilization_hold:active_ci_repair:" + ",".join(active_ci_repair_task_ids)
        )

    if (
        storm_admission_active
        and not queued
        and not reasons
        and matches
        and not any(_is_storm_exempt_task(matched_task) for matched_task in matches)
    ):
        reasons.append("storm_admission_hold:" + ",".join(storm_reasons or ("admission_pressure",)))

    # Dispatch resilience to lane-death (CASE-CAPACITY-ROUTING-001). A CLEAN,
    # green PR whose single linked task is pr_open but never had its release
    # authorized (the lane died after `gh pr create`) strands forever. Running
    # as the system (FM-20), the autoqueue may auto-arm an eligible task; a
    # governance/public/audio-egress-sensitive one is held so it stays manual.
    auto_arm = False
    if task is not None and not reasons:
        arm = assess_release_auto_arm(task.frontmatter)
        if arm.needs_arming:
            if arm.eligible:
                auto_arm = True
            else:
                reasons.append("release_auto_arm_ineligible:" + ",".join(arm.blockers))

    if queued:
        if reasons:
            return Decision(
                pr=pr,
                task=task,
                tasks=matched_tasks,
                action="dequeue",
                reasons=tuple(reasons),
            )
        return Decision(
            pr=pr,
            task=task,
            tasks=matched_tasks,
            action="already_queued",
            reasons=tuple(reasons),
        )
    if reasons:
        if pr.auto_merge_enabled:
            return Decision(
                pr=pr,
                task=task,
                tasks=matched_tasks,
                action="disable_auto_merge",
                reasons=tuple(reasons),
            )
        return Decision(
            pr=pr,
            task=task,
            tasks=matched_tasks,
            action="blocked",
            reasons=tuple(reasons),
        )
    if pr.auto_merge_enabled:
        return Decision(
            pr=pr,
            task=task,
            tasks=matched_tasks,
            action="already_auto_merge_enabled",
        )
    if pr.check_summary.has_pending:
        if include_pending_auto:
            return Decision(
                pr=pr,
                task=task,
                tasks=matched_tasks,
                action="enable_auto_merge",
                auto_arm=auto_arm,
            )
        return Decision(
            pr=pr,
            task=task,
            tasks=matched_tasks,
            action="blocked",
            reasons=("pending_checks:" + ",".join(pr.check_summary.pending),),
        )
    return Decision(pr=pr, task=task, tasks=matched_tasks, action="queue", auto_arm=auto_arm)


def merge_pr(
    decision: Decision,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
) -> tuple[bool, str]:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    if decision.action == "dequeue":
        if not decision.pr.node_id:
            return False, "missing_pull_request_node_id"
        query = "mutation($id:ID!){dequeuePullRequest(input:{id:$id}){clientMutationId}}"
        cmd = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"id={decision.pr.node_id}",
        ]
    else:
        cmd = ["gh", "pr", "merge", str(decision.pr.number), "--repo", repo]
    if decision.action in ("enable_auto_merge", "queue"):
        # Arm-only (task reform-native-merge-queue): the local autoqueue's sole
        # positive mutation is to ARM auto-merge with one idempotent command.
        # GitHub's native merge queue then owns batching, speculative
        # gh-readonly-queue branches, auto-rebase, and bisect-on-failure — we no
        # longer issue a direct `--merge` (which raced the queue's own management).
        # Re-arming an already-armed PR is a no-op; `--squash` matches the queue's
        # configured merge method.
        cmd.extend(["--auto", "--squash"])
    elif decision.action == "disable_auto_merge":
        cmd.append("--disable-auto")
    elif decision.action != "dequeue":
        return False, f"unsupported_action:{decision.action}"
    proc = runner(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return False, output or f"gh pr merge failed rc={proc.returncode}"
    return True, output


RELEASE_AUTO_ARM_ROLE = "autoqueue-system"
DEFAULT_AUTHORITY_CASE_LEDGER = Path.home() / ".cache" / "hapax" / "authority-case-ledger.jsonl"


def default_authority_case_ledger() -> Path:
    raw = os.environ.get("HAPAX_AUTHORITY_CASE_LEDGER")
    return Path(raw).expanduser() if raw else DEFAULT_AUTHORITY_CASE_LEDGER


def _append_release_auto_arm_ledger(
    task: TaskNote, *, ledger_path: Path, now_iso: str, role: str
) -> None:
    """Append an audit record for a system release auto-arm. Best-effort."""
    record = {
        "ts": now_iso,
        "kind": "release_auto_arm",
        "tool": "cc-pr-autoqueue",
        "role": role,
        "task_id": task.task_id,
        "authority_case": task.authority_case,
        "pr": task.pr,
        "note": str(task.path),
    }
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as exc:  # never undo a written arm over a ledger hiccup
        LOG.warning("release auto-arm ledger append failed for %s: %s", task.task_id, exc)


def arm_release_for_task(
    task: TaskNote,
    *,
    ledger_path: Path | None = None,
    now: datetime | None = None,
    role: str = RELEASE_AUTO_ARM_ROLE,
) -> tuple[bool, str]:
    """Authorize release for a stranded task on behalf of a dead lane (system).

    Writes ``release_authorized: true`` + ``stage: S7_RELEASE`` to the note and
    appends an authority-case ledger record. Eligibility MUST already have been
    confirmed by :func:`assess_release_auto_arm` (the caller gates on it).
    """
    ledger_path = ledger_path or default_authority_case_ledger()
    now = now or datetime.now(UTC)
    now_iso = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        text = task.path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"note_unreadable:{exc}"
    armed = apply_release_auto_arm(text, now_iso=now_iso, role=role)
    if armed == text:
        return False, "note_unchanged"
    try:
        task.path.write_text(armed, encoding="utf-8")
    except OSError as exc:
        return False, f"note_write_failed:{exc}"
    _append_release_auto_arm_ledger(task, ledger_path=ledger_path, now_iso=now_iso, role=role)
    return True, f"release auto-armed {task.task_id}"


def _status_description(text: str, *, limit: int = 140) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _admission_status_for(decision: Decision) -> tuple[str, str] | None:
    if decision.action in {
        "queue",
        "enable_auto_merge",
        "already_queued",
        "already_auto_merge_enabled",
    }:
        return "success", _status_description(f"cc-pr-autoqueue admitted: {decision.action}")

    if decision.action in {"blocked", "dequeue", "disable_auto_merge"}:
        reasons = "; ".join(decision.reasons or ("not ready for merge queue",))
        return "failure", _status_description(f"cc-pr-autoqueue blocked: {reasons}")

    return None


def set_autoqueue_admission_status(
    decision: Decision,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
) -> tuple[bool, str] | None:
    """Write the server-visible autoqueue admission proof for a PR head SHA."""
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    status = _admission_status_for(decision)
    if status is None:
        return None
    if not decision.pr.head_sha:
        return False, "missing_head_sha"
    state, description = status
    cmd = [
        "gh",
        "api",
        "-X",
        "POST",
        f"repos/{repo}/statuses/{decision.pr.head_sha}",
        "-f",
        f"state={state}",
        "-f",
        f"context={AUTOQUEUE_ADMISSION_CONTEXT}",
        "-f",
        f"description={description}",
    ]
    proc = runner(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return False, output or f"status write failed rc={proc.returncode}"
    return True, output


def _decision_is_non_ready(decision: Decision) -> bool:
    return decision.action in {"blocked", "dequeue", "disable_auto_merge"} and bool(
        decision.reasons
    )


def _recent_failed_non_ready_merge_group_runs(
    *,
    lineage_ledger_path: Path | None,
    decisions: list[Decision],
    recent_limit: int,
) -> tuple[dict[str, Any], ...]:
    if lineage_ledger_path is None:
        return ()
    decisions_by_pr = {decision.pr.number: decision for decision in decisions}
    records = read_jsonl_records(lineage_ledger_path)
    ordered = sorted(records, key=lambda item: item.queue_entry_time or item.observed_at)
    failed: list[dict[str, Any]] = []
    for record in ordered[-max(1, recent_limit) :]:
        conclusion = str(record.run_conclusion or record.run_outcome or "").lower()
        if conclusion not in FAILED_MERGE_GROUP_CONCLUSIONS:
            continue
        if record.pr_number is None:
            continue
        decision = decisions_by_pr.get(record.pr_number)
        if decision is None or not _decision_is_non_ready(decision):
            continue
        failed.append(
            {
                "run_id": record.merge_group_run_id,
                "pr": record.pr_number,
                "run_outcome": record.run_outcome,
                "run_conclusion": record.run_conclusion,
                "decision_action": decision.action,
                "reasons": list(decision.reasons),
                "bottleneck": record.bottleneck.model_dump(mode="json")
                if record.bottleneck is not None
                else None,
            }
        )
    return tuple(failed)


def _build_storm_mode(
    *,
    prs: list[PullRequest],
    queued_prs: set[int],
    decisions: list[Decision],
    failed_recent_merge_group_runs: tuple[dict[str, Any], ...],
    throttle_decision: ThrottleDecision,
    recommended_max_entries_to_build: int,
) -> StormMode:
    blocked_queued = tuple(
        decision.as_dict()
        for decision in decisions
        if decision.pr.number in queued_prs and decision.action == "dequeue"
    )
    active = throttle_decision.frozen
    reasons = [throttle_decision.reason] if active else []
    return StormMode(
        active=active,
        reasons=tuple(reasons),
        open_pr_count=len(prs),
        queued_pr_count=len(queued_prs),
        blocked_queued_pr_count=len(blocked_queued),
        blocked_queued_prs=blocked_queued,
        failed_recent_merge_group_runs=failed_recent_merge_group_runs,
        recommended_max_entries_to_build=recommended_max_entries_to_build,
        recommended_throttle_state=throttle_decision.state,
        failure_rate=throttle_decision.failure_rate,
        failure_rate_samples=throttle_decision.samples,
        rate_frozen=throttle_decision.frozen,
        recommended_bisections=tuple(
            bisection_plan_for_failed_runs(failed_recent_merge_group_runs)
        ),
    )


def run_reconciler(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    apply: bool = False,
    require_route_metadata: bool = True,
    include_pending_auto: bool = True,
    required_checks: tuple[str, ...] = DEFAULT_REQUIRED_CHECKS,
    limit: int = 100,
    lineage_ledger_path: Path | None = DEFAULT_LEDGER_PATH,
    quarantine_path: Path = DEFAULT_QUARANTINE_PATH,
    storm_mode_enabled: bool = True,
    advisory_open_pr_count: int = DEFAULT_ADVISORY_OPEN_PR_COUNT,
    storm_failed_merge_group_threshold: int = DEFAULT_STORM_FAILED_MERGE_GROUP_THRESHOLD,
    storm_recent_run_limit: int = DEFAULT_STORM_RECENT_RUN_LIMIT,
    auto_arm_ledger_path: Path | None = None,
    runner: Any = None,
) -> dict[str, Any]:
    if any(os.environ.get(name) == "1" for name in KILLSWITCH_ENVS):
        return {
            "repo": repo,
            "apply": apply,
            "skipped": True,
            "reason": "killswitch",
            "killswitch_envs": list(KILLSWITCH_ENVS),
        }

    repo_root = repo_root or default_repo_root()
    tasks = load_task_notes(vault_root)
    active_ci_repair_task_ids = _active_ci_repair_task_ids(tasks)
    queued_prs = fetch_merge_queue_pr_numbers(repo=repo, repo_root=repo_root, runner=runner)
    prs = fetch_open_prs(repo=repo, repo_root=repo_root, limit=limit, runner=runner)
    preliminary_decisions = [
        classify_pr(
            pr,
            tasks=tasks,
            queued_prs=queued_prs,
            require_route_metadata=require_route_metadata,
            include_pending_auto=include_pending_auto,
            required_checks=required_checks,
            active_ci_repair_task_ids=active_ci_repair_task_ids,
        )
        for pr in prs
    ]
    now = datetime.now(UTC)
    lineage_records = read_jsonl_records(lineage_ledger_path) if lineage_ledger_path else []
    throttle_policy = FleetThrottlePolicy(advisory_open_pr_count=advisory_open_pr_count)
    # Quarantine WRITE side (FM-3/FM-4 reversible quarantine): open quarantines for
    # PRs over the failure threshold, lift expired ones, and persist (apply mode
    # only). PRs already quarantined ON ENTRY are excluded from THIS tick's
    # failure-rate signal; PRs newly quarantined this tick are persisted now and
    # take effect next tick — isolating a flaky PR converges without a one-tick
    # regression in fleet protection.
    existing_quarantine = read_quarantine(quarantine_path)
    quarantined_prs = active_quarantined_pr_numbers(existing_quarantine, now=now)
    quarantine_reconciliation = reconcile_flake_quarantines(
        existing_quarantine,
        lineage_records,
        candidate_prs={pr.number for pr in prs},
        policy=throttle_policy,
        now=now,
    )
    if apply and (quarantine_reconciliation.newly_quarantined or quarantine_reconciliation.lifted):
        write_quarantine(quarantine_path, quarantine_reconciliation.records)
    throttle_decision = decide_fleet_throttle(
        lineage_records,
        open_pr_count=len(prs),
        policy=throttle_policy,
        now=now,
        quarantined_prs=quarantined_prs,
    )
    recommended_entries = recommend_max_entries_to_build(
        lineage_records,
        policy=throttle_policy,
        now=now,
        quarantined_prs=quarantined_prs,
    )
    failed_recent_merge_group_runs = _recent_failed_non_ready_merge_group_runs(
        lineage_ledger_path=lineage_ledger_path,
        decisions=preliminary_decisions,
        recent_limit=storm_recent_run_limit,
    )
    storm_mode = _build_storm_mode(
        prs=prs,
        queued_prs=queued_prs,
        decisions=preliminary_decisions,
        failed_recent_merge_group_runs=failed_recent_merge_group_runs,
        throttle_decision=throttle_decision,
        recommended_max_entries_to_build=recommended_entries,
    )
    decisions = preliminary_decisions
    if storm_mode_enabled and storm_mode.active:
        decisions = [
            classify_pr(
                pr,
                tasks=tasks,
                queued_prs=queued_prs,
                require_route_metadata=require_route_metadata,
                include_pending_auto=include_pending_auto,
                required_checks=required_checks,
                active_ci_repair_task_ids=active_ci_repair_task_ids,
                storm_admission_active=True,
                storm_reasons=storm_mode.reasons,
            )
            for pr in prs
        ]
        failed_recent_merge_group_runs = _recent_failed_non_ready_merge_group_runs(
            lineage_ledger_path=lineage_ledger_path,
            decisions=decisions,
            recent_limit=storm_recent_run_limit,
        )
        storm_mode = _build_storm_mode(
            prs=prs,
            queued_prs=queued_prs,
            decisions=decisions,
            failed_recent_merge_group_runs=failed_recent_merge_group_runs,
            throttle_decision=throttle_decision,
            recommended_max_entries_to_build=recommended_entries,
        )

    mutation_results: list[dict[str, Any]] = []
    if apply:
        for decision in decisions:
            status_result = set_autoqueue_admission_status(
                decision, repo=repo, repo_root=repo_root, runner=runner
            )
            if decision.action not in {
                "queue",
                "enable_auto_merge",
                "disable_auto_merge",
                "dequeue",
            }:
                if status_result is not None:
                    ok, message = status_result
                    mutation_results.append(
                        {
                            **decision.as_dict(),
                            "action": "set_admission_status",
                            "status_state": _admission_status_for(decision)[0],
                            "ok": ok,
                            "message": message,
                        }
                    )
                continue
            if (
                decision.action in {"queue", "enable_auto_merge"}
                and status_result is not None
                and not status_result[0]
            ):
                mutation_results.append(
                    {
                        **decision.as_dict(),
                        "ok": False,
                        "message": "admission status write failed; queue mutation skipped",
                        "admission_status": {
                            "state": _admission_status_for(decision)[0],
                            "ok": status_result[0],
                            "message": status_result[1],
                        },
                    }
                )
                continue
            if decision.auto_arm and decision.task is not None:
                armed_ok, armed_message = arm_release_for_task(
                    decision.task, ledger_path=auto_arm_ledger_path, now=now
                )
                if not armed_ok:
                    mutation_results.append(
                        {
                            **decision.as_dict(),
                            "ok": False,
                            "message": f"release auto-arm failed: {armed_message}",
                        }
                    )
                    continue
            ok, message = merge_pr(decision, repo=repo, repo_root=repo_root, runner=runner)
            result = {
                **decision.as_dict(),
                "ok": ok,
                "message": message,
            }
            if status_result is not None:
                status_ok, status_message = status_result
                result["admission_status"] = {
                    "state": _admission_status_for(decision)[0],
                    "ok": status_ok,
                    "message": status_message,
                }
            mutation_results.append(result)

    return {
        "repo": repo,
        "apply": apply,
        "require_route_metadata": require_route_metadata,
        "include_pending_auto": include_pending_auto,
        "required_checks": list(required_checks),
        "active_ci_repair_task_ids": list(active_ci_repair_task_ids),
        "storm_mode_enabled": storm_mode_enabled,
        "storm_mode": storm_mode.as_dict(repo=repo),
        "flake_quarantine": {
            "path": str(quarantine_path),
            "active": quarantine_reconciliation.active,
            "newly_quarantined": quarantine_reconciliation.newly_quarantined,
            "lifted": quarantine_reconciliation.lifted,
            "written": bool(
                apply
                and (
                    quarantine_reconciliation.newly_quarantined or quarantine_reconciliation.lifted
                )
            ),
        },
        "lineage_ledger_path": str(lineage_ledger_path) if lineage_ledger_path else None,
        "open_pr_count": len(prs),
        "queued_prs": sorted(queued_prs),
        "decisions": [decision.as_dict() for decision in decisions],
        "counts": {
            "queue": sum(1 for decision in decisions if decision.action == "queue"),
            "enable_auto_merge": sum(
                1 for decision in decisions if decision.action == "enable_auto_merge"
            ),
            "already_queued": sum(
                1 for decision in decisions if decision.action == "already_queued"
            ),
            "already_auto_merge_enabled": sum(
                1 for decision in decisions if decision.action == "already_auto_merge_enabled"
            ),
            "disable_auto_merge": sum(
                1 for decision in decisions if decision.action == "disable_auto_merge"
            ),
            "dequeue": sum(1 for decision in decisions if decision.action == "dequeue"),
            "blocked": sum(1 for decision in decisions if decision.action == "blocked"),
        },
        "mutations": mutation_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Queue/arm eligible PRs.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo, owner/name.")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--allow-legacy-task-metadata",
        action="store_true",
        help="Do not require route_metadata_schema: 1 on linked cc-tasks.",
    )
    parser.add_argument(
        "--no-pending-auto",
        action="store_true",
        help="Do not arm auto-merge for governed PRs with pending checks.",
    )
    parser.add_argument(
        "--required-check",
        action="append",
        dest="required_checks",
        help=(
            "Required branch-protection check context. Repeat to override the "
            "default Hapax main required checks."
        ),
    )
    parser.add_argument(
        "--no-required-checks",
        action="store_true",
        help="Do not block PRs that lack the default required check contexts.",
    )
    parser.add_argument(
        "--lineage-ledger-path",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help="Merge queue lineage JSONL used to classify recent failed non-ready runs.",
    )
    parser.add_argument(
        "--disable-storm-mode",
        action="store_true",
        help="Report storm/admission pressure but do not add storm admission holds.",
    )
    parser.add_argument(
        "--advisory-open-pr-count",
        "--storm-open-pr-threshold",  # deprecated alias
        type=int,
        dest="advisory_open_pr_count",
        default=DEFAULT_ADVISORY_OPEN_PR_COUNT,
        help=(
            "Open PR count at or above which the queue reports an advisory 'busy' "
            "signal. Advisory only — it never freezes admission (the only freeze is "
            "failure-rate based). --storm-open-pr-threshold is a deprecated alias."
        ),
    )
    parser.add_argument(
        "--storm-failed-merge-group-threshold",
        type=int,
        default=DEFAULT_STORM_FAILED_MERGE_GROUP_THRESHOLD,
        help="Recent failed non-ready merge-group run count that activates storm mode.",
    )
    parser.add_argument(
        "--storm-recent-run-limit",
        type=int,
        default=DEFAULT_STORM_RECENT_RUN_LIMIT,
        help="Recent lineage records considered for failed non-ready merge-group runs.",
    )
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args(argv)

    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    report = run_reconciler(
        repo=args.repo,
        repo_root=args.repo_root,
        vault_root=args.vault_root,
        apply=args.apply,
        require_route_metadata=not args.allow_legacy_task_metadata,
        include_pending_auto=not args.no_pending_auto,
        required_checks=()
        if args.no_required_checks
        else tuple(args.required_checks or DEFAULT_REQUIRED_CHECKS),
        limit=args.limit,
        lineage_ledger_path=args.lineage_ledger_path,
        storm_mode_enabled=not args.disable_storm_mode,
        advisory_open_pr_count=args.advisory_open_pr_count,
        storm_failed_merge_group_threshold=args.storm_failed_merge_group_threshold,
        storm_recent_run_limit=args.storm_recent_run_limit,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
