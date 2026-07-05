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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import review_team  # noqa: E402
from github_pr_status import (  # noqa: E402
    GRAPHQL_BACKOFF_RC,
    fetch_status_check_rollup_rest,
    get_pull_rest,
    list_open_pr_statuses_rest,
    rest_merge_state_status,
    run_graphql_rate_aware,
)

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
    RELEASE_MITIGATION_CHECKS,
    REVIEW_TEAM_QUORUM_EVIDENCE,
    TASK_MERGE_READY_STATUSES,
    ReleaseAutoArmAssessment,
    acceptance_receipt_blockers,
    apply_release_auto_arm,
    assess_release_auto_arm,
    frontmatter_from_text,
    release_auto_arm_waivers,
    task_closure_validity,
)

LOG = logging.getLogger("cc-pr-autoqueue")

DEFAULT_REPO = "hapax-systems/hapax-council"
DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
DEFAULT_REPORT_PATH = (
    Path.home() / ".cache" / "hapax" / "orchestration" / "cc-pr-autoqueue-report.json"
)
DEFAULT_ADMISSION_GOVERNOR_PATH = Path.home() / ".cache" / "hapax" / "pr-admission-governor.yaml"
KILLSWITCH_ENVS = ("HAPAX_CC_PR_AUTOQUEUE_OFF", "HAPAX_CC_HYGIENE_OFF")

PASS_STATES = {"SUCCESS", "SKIPPED", "NEUTRAL"}
# Ordinary queue admission treats skipped/neutral as non-failing, but mitigation
# evidence must be affirmative: a sensitive release gate is satisfied by SUCCESS
# only.
MITIGATION_EVIDENCE_PASS_STATES = {"SUCCESS"}
FAIL_STATES = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
DIRTY_MERGE_STATES = {"DIRTY"}
UNCHECKED_PR_CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[\s\]\s+(?P<text>.+?)\s*$")
NON_BLOCKING_CHECKBOX_RE = re.compile(
    r"\b(optional|non[-_\s]?blocking|informational|follow[-_\s]?up|stretch)\b",
    re.IGNORECASE,
)
_MERGE_QUEUE_REF_PR_RE = re.compile(r"/pr-(\d+)-")
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
AUTOQUEUE_IGNORED_CHECK_CONTEXTS = {
    AUTOQUEUE_ADMISSION_CONTEXT,
    REVIEW_TEAM_QUORUM_EVIDENCE,
    "governance-gate",
    "pr-admission",
}
VIRTUAL_RELEASE_MITIGATION_CONTEXTS = frozenset({REVIEW_TEAM_QUORUM_EVIDENCE})
RELEASE_MITIGATION_CHECK_CONTEXTS = frozenset(
    check
    for checks in RELEASE_MITIGATION_CHECKS.values()
    for check in checks
    if check not in VIRTUAL_RELEASE_MITIGATION_CONTEXTS
)
# Mirrors queue-admission-proof-check.py DEFAULT_TTL_SECONDS. The reconciler
# re-posts the admission proof once it is older than half this window so the
# server-side proof never goes stale (G3 idempotent writes).
AUTOQUEUE_ADMISSION_TTL_SECONDS = 30 * 60
# Failure proofs intentionally refresh less often than success proofs: blocked
# PRs can sit for days, and GitHub caps commit statuses per SHA+context. Still,
# when the blocker text changes, the proof must eventually stop advertising
# cleared blockers.
FAILURE_DESCRIPTION_REFRESH_SECONDS = 10 * 60
AUTOQUEUE_REPORT_SCHEMA_VERSION = 1
AUTOQUEUE_REPORT_STALENESS_SECONDS = 7 * 60
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
    verified_passed: list[str] = field(default_factory=list)

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
    files: tuple[str, ...] | None
    changed_files_count: int | None
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
    auto_arm_verified_checks: tuple[str, ...] = ()

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
            out["auto_arm_verified_checks"] = list(self.auto_arm_verified_checks)
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


def _isoformat_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _file_mtime_iso(path: Path) -> str | None:
    try:
        return _isoformat_z(datetime.fromtimestamp(path.stat().st_mtime, tz=UTC))
    except OSError:
        return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _admission_governor_projection(path: Path, *, observed_at: datetime) -> dict[str, Any]:
    """Raw governor feed projection for cockpit consumers.

    The autoqueue is not the admission-governor authority; it only exposes the
    governor file state beside its own PR decisions so downstream panels can
    render missing/stale governor data distinctly from a normal-mode governor.
    """
    base: dict[str, Any] = {
        "source_id": "pr-admission-governor",
        "authority_class": "admission-authority",
        "path": str(path),
        "watch": True,
        "observed_at": _isoformat_z(observed_at),
        "mtime": None,
        "present": False,
        "read_error": None,
        "raw": None,
        "mode": None,
        "reason": None,
        "set_by": None,
        "hysteresis": {
            "entry_open_pr_count": None,
            "exit_below_count": None,
            "exit_stable_ticks_required": None,
            "stable_ticks_observed": None,
        },
    }
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        base["read_error"] = "missing"
        return base
    except OSError as exc:
        base["read_error"] = f"unreadable:{exc.__class__.__name__}"
        return base
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        base["present"] = True
        base["mtime"] = _file_mtime_iso(path)
        base["read_error"] = f"yaml_error:{str(exc).splitlines()[0][:90]}"
        return base
    if not isinstance(raw, dict):
        base["present"] = True
        base["mtime"] = _file_mtime_iso(path)
        base["read_error"] = f"not_mapping:{type(raw).__name__}"
        return base
    base.update(
        {
            "present": True,
            "mtime": _file_mtime_iso(path),
            "raw": _jsonable(raw),
            "mode": raw.get("mode"),
            "reason": raw.get("reason"),
            "set_by": raw.get("set_by"),
            "hysteresis": {
                "entry_open_pr_count": raw.get("entry_open_pr_count"),
                "exit_below_count": raw.get("exit_below_count"),
                "exit_stable_ticks_required": raw.get("exit_stable_ticks_required"),
                "stable_ticks_observed": raw.get("stable_ticks_observed"),
            },
        }
    )
    return base


def _stable_pr_admission(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "pr": decision["pr"],
        "title": decision.get("title"),
        "head_ref": decision.get("head_ref"),
        "task_id": decision.get("task_id"),
        "task_ids": decision.get("task_ids"),
        "task_status": decision.get("task_status"),
        "action": decision["action"],
        # The verdict vocabulary is the autoqueue action itself; cockpit code
        # must not remap it into an invented state machine.
        "verdict": decision["action"],
        "blockers": list(decision.get("reasons") or ()),
        "auto_arm": bool(decision.get("auto_arm")),
    }


def _with_stable_feed_metadata(
    report: dict[str, Any],
    *,
    report_path: Path,
    admission_governor_path: Path,
    now: datetime,
) -> dict[str, Any]:
    payload = dict(report)
    payload.update(
        {
            "schema_version": AUTOQUEUE_REPORT_SCHEMA_VERSION,
            "event": "cc_pr_autoqueue_report",
            "generated_at": _isoformat_z(now),
            "source_definition": {
                "source_id": "cc-pr-autoqueue",
                "authority_class": "per-pr-admission-verdicts",
                "path": str(report_path),
                "staleness_budget_seconds": AUTOQUEUE_REPORT_STALENESS_SECONDS,
                "watch": True,
            },
            "consumed_sources": [
                {
                    "source_id": "pr-admission-governor",
                    "authority_class": "admission-authority",
                    "path": str(admission_governor_path),
                    "watch": True,
                }
            ],
            "admission_governor": _admission_governor_projection(
                admission_governor_path, observed_at=now
            ),
            "per_pr_admission": [
                _stable_pr_admission(decision) for decision in report.get("decisions", [])
            ],
        }
    )
    return payload


def write_stable_report(
    report: dict[str, Any],
    *,
    report_path: Path,
    admission_governor_path: Path = DEFAULT_ADMISSION_GOVERNOR_PATH,
    now: datetime | None = None,
) -> tuple[dict[str, Any], tuple[bool, str]]:
    now = now or datetime.now(UTC)
    payload = _with_stable_feed_metadata(
        report,
        report_path=report_path,
        admission_governor_path=admission_governor_path,
        now=now,
    )
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = report_path.with_name(f".{report_path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(report_path)
    except OSError as exc:
        return payload, (False, f"{exc.__class__.__name__}: {exc}")
    return payload, (True, str(report_path))


def _finalize_reconciler_report(
    report: dict[str, Any],
    *,
    report_path: Path | None,
    admission_governor_path: Path,
    now: datetime,
) -> dict[str, Any]:
    if report_path is None:
        return report
    payload, (ok, message) = write_stable_report(
        report,
        report_path=report_path,
        admission_governor_path=admission_governor_path,
        now=now,
    )
    payload["stable_report"] = {
        "path": str(report_path),
        "written": ok,
        "message": message,
    }
    if not ok:
        LOG.warning("stable autoqueue report write failed: %s", message)
    return payload


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


def _check_observed_at(item: dict[str, Any]) -> datetime | None:
    for key in (
        "completedAt",
        "completed_at",
        "startedAt",
        "started_at",
        "createdAt",
        "created_at",
    ):
        value = _scalar(item.get(key))
        if not value:
            continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            continue
    return None


def summarize_checks(items: list[dict[str, Any]]) -> CheckSummary:
    latest_by_name: dict[str, tuple[datetime | None, int, str]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            latest_by_name["malformed-check"] = (None, index, "PENDING")
            continue
        name = _check_name(item)
        raw_state = item.get("conclusion") or item.get("state") or item.get("status")
        candidate = (_check_observed_at(item), index, str(raw_state or "").upper())
        previous = latest_by_name.get(name)
        if previous is None or (candidate[0] or datetime.min.replace(tzinfo=UTC), index) >= (
            previous[0] or datetime.min.replace(tzinfo=UTC),
            previous[1],
        ):
            latest_by_name[name] = candidate
    passed: list[str] = []
    pending: list[str] = []
    failed: list[str] = []
    verified_passed: list[str] = []
    for name, (_observed_at, _index, state) in latest_by_name.items():
        if (
            name not in VIRTUAL_RELEASE_MITIGATION_CONTEXTS
            and state in MITIGATION_EVIDENCE_PASS_STATES
            and (
                name not in AUTOQUEUE_IGNORED_CHECK_CONTEXTS
                or name in RELEASE_MITIGATION_CHECK_CONTEXTS
            )
        ):
            verified_passed.append(name)
    for name, (_observed_at, _index, state) in latest_by_name.items():
        if name in AUTOQUEUE_IGNORED_CHECK_CONTEXTS:
            continue
        if state in PASS_STATES:
            passed.append(name)
        elif state in FAIL_STATES:
            failed.append(name)
        else:
            pending.append(name)
    return CheckSummary(
        passed=passed,
        pending=pending,
        failed=failed,
        verified_passed=verified_passed,
    )


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
    files_payload = item.get("files")
    files = (
        tuple(
            str(entry["path"])
            for entry in files_payload
            if isinstance(entry, dict) and entry.get("path")
        )
        if isinstance(files_payload, list)
        else None
    )
    try:
        changed_files_count = (
            int(item["changedFiles"]) if item.get("changedFiles") is not None else None
        )
    except (TypeError, ValueError):
        changed_files_count = None
    return PullRequest(
        number=number,
        node_id=_scalar(item.get("id")),
        title=_scalar(item.get("title")) or "",
        head_ref=_scalar(item.get("headRefName")) or "",
        files=files,
        changed_files_count=changed_files_count,
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
    raw = list_open_pr_statuses_rest(
        repo=repo,
        repo_root=repo_root,
        runner=runner,
        limit=limit,
        include_files=True,
        include_review_decision=True,
    )
    if not raw:
        LOG.warning("REST open PR scan returned no rows")
        return []
    prs: list[PullRequest] = []
    for item in raw:
        if isinstance(item, dict):
            if "reviewDecision" not in item or item.get("reviewDecision") is None:
                item["reviewDecision"] = "REVIEW_REQUIRED"
            rest_pr = None
            try:
                number = int(item.get("number"))
                rest_pr = get_pull_rest(number, repo=repo, repo_root=repo_root, runner=runner)
            except (TypeError, ValueError):
                rest_pr = None
            item["mergeStateStatus"] = (
                rest_merge_state_status(rest_pr)
                if rest_pr is not None
                else str(item.get("mergeStateStatus") or "UNKNOWN").upper()
            )
            # Preserve the shared REST snapshot when available. If it is absent, derive the
            # rollup through REST/core check-runs and commit statuses, not another GraphQL PR
            # view. Fail-closed: an unfetchable rollup reads as "checks unknown / not green".
            fallback_rollup = item.get("statusCheckRollup")
            if isinstance(fallback_rollup, list) and fallback_rollup:
                item["statusCheckRollup"] = fallback_rollup
            else:
                item["statusCheckRollup"] = _fetch_status_check_rollup(
                    item.get("number"),
                    head_sha=item.get("headRefOid"),
                    repo=repo,
                    repo_root=repo_root,
                    runner=runner,
                )
            pr = _parse_pr(item)
            if pr is not None:
                prs.append(pr)
    return prs


def _fetch_status_check_rollup(
    number: object,
    *,
    head_sha: object | None = None,
    repo: str,
    repo_root: Path,
    runner: Any,
) -> list[Any]:
    """Fetch one PR's status rollup via REST check-runs/statuses.

    Kept separate from the open-PR metadata scan because check-runs are fetched per
    head SHA through REST/core. Returns ``[]`` fail-closed on any
    error so an unknown-checks PR is never treated as green.
    """
    sha = _scalar(head_sha)
    if not sha and isinstance(number, int):
        payload = get_pull_rest(number, repo=repo, repo_root=repo_root, runner=runner)
        head = payload.get("head") if isinstance(payload, dict) else None
        if isinstance(head, dict):
            sha = _scalar(head.get("sha"))
    if not sha:
        return []
    rollup = fetch_status_check_rollup_rest(
        sha,
        repo=repo,
        repo_root=repo_root,
        runner=runner,
    )
    if not rollup:
        LOG.warning(
            "REST status rollup fetch returned no checks for #%s sha=%s",
            number,
            sha,
        )
    return rollup


def fetch_pr_release_evidence(
    pr_number: int,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
) -> tuple[bool, str, set[str]]:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    payload = get_pull_rest(pr_number, repo=repo, repo_root=repo_root, runner=runner)
    if not isinstance(payload, dict):
        return False, "invalid_pr_release_evidence_payload", set()
    head = payload.get("head") if isinstance(payload.get("head"), dict) else {}
    sha = _scalar(head.get("sha"))
    if not sha:
        return False, "missing_head_sha", set()
    rollup = fetch_status_check_rollup_rest(
        sha,
        repo=repo,
        repo_root=repo_root,
        runner=runner,
        use_cache=False,
    )
    if not isinstance(rollup, list):
        return False, "invalid_status_check_rollup", set()
    return True, sha, set(summarize_checks(rollup).verified_passed)


def fetch_merge_queue_pr_numbers(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
) -> set[int] | None:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    owner, name = repo.split("/", 1)
    query = (
        "query($owner:String!,$repo:String!){repository(owner:$owner,name:$repo){"
        "mergeQueue{entries(first:100){nodes{pullRequest{number}}}}}}"
    )
    graphql_args = [
        "-f",
        f"query={query}",
        "-f",
        f"owner={owner}",
        "-f",
        f"repo={name}",
    ]
    proc = run_graphql_rate_aware(
        graphql_args,
        repo_root=repo_root,
        runner=runner,
    )
    if proc.returncode != 0:
        level = logging.WARNING if proc.returncode == GRAPHQL_BACKOFF_RC else logging.ERROR
        LOG.log(
            level,
            "gh merge queue query indeterminate (rc=%d): %s",
            proc.returncode,
            proc.stderr.strip(),
        )
        return None
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        LOG.error("gh merge queue query emitted non-JSON: %s", exc)
        return None
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
    queued |= _merge_queue_ref_pr_numbers(repo=repo, repo_root=repo_root, runner=runner)
    return queued


def _merge_queue_ref_pr_numbers(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
) -> set[int]:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    cmd = [
        "gh",
        "api",
        f"repos/{repo}/git/matching-refs/heads/gh-readonly-queue",
        "--jq",
        ".[].ref",
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
        return set()
    refs = proc.stdout.splitlines()
    queued: set[int] = set()
    for ref in refs:
        if match := _MERGE_QUEUE_REF_PR_RE.search(ref.strip()):
            queued.add(int(match.group(1)))
    return queued


def _frontmatter(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"unreadable: {exc.__class__.__name__}"
    if not text.startswith("---"):
        return None, "no frontmatter fence"
    end = text.find("\n---", 3)
    if end == -1:
        return None, "unterminated frontmatter fence"
    raw = text[3:end].strip()
    if "\x1b[" in raw:
        # ANSI escapes silently break YAML and made a task invisible on
        # 2026-06-10 (admission reported missing_cc_task_link — a lie).
        return None, "ANSI escape sequences in frontmatter"
    try:
        parsed = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        return None, f"YAML error: {str(exc).splitlines()[0][:90]}"
    if not isinstance(parsed, dict):
        return None, "frontmatter is not a mapping"
    return parsed, None


TASK_NOTE_PARSE_FAILURES: list[tuple[str, str]] = []
"""(filename, reason) for every task note the loader could not parse this run.

SDLC legibility contract (operator directive 2026-06-10): a confusion in the
SDLC is a FAILURE of the SDLC — reason codes must name the true failure.
A PR whose task note is unparseable must NOT read as merely "unlinked".
"""


def _task_note_from_frontmatter(path: Path, folder: str, fm: dict[str, Any]) -> TaskNote | None:
    task_id = _scalar(fm.get("task_id"))
    if not task_id:
        return None
    return TaskNote(
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


def load_task_notes(vault_root: Path = DEFAULT_VAULT_ROOT) -> list[TaskNote]:
    notes: list[TaskNote] = []
    for folder in ("active", "closed"):
        root = vault_root / folder
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            fm, parse_error = _frontmatter(path)
            if parse_error is not None:
                TASK_NOTE_PARSE_FAILURES.append((path.name, parse_error))
                LOG.warning("task note unparseable: %s — %s", path.name, parse_error)
                continue
            if not fm or fm.get("type") != "cc-task":
                continue
            task = _task_note_from_frontmatter(path, folder, fm)
            if task is None:
                continue
            notes.append(task)
    return notes


def _task_note_with_frontmatter(task: TaskNote, frontmatter: dict[str, Any]) -> TaskNote:
    return TaskNote(
        task_id=_scalar(frontmatter.get("task_id")) or task.task_id,
        path=task.path,
        folder=task.folder,
        status=(_scalar(frontmatter.get("status")) or "").lower(),
        pr=_int_or_none(frontmatter.get("pr")),
        branch=_scalar(frontmatter.get("branch")),
        authority_case=_scalar(frontmatter.get("authority_case") or frontmatter.get("case_id")),
        parent_spec=_scalar(frontmatter.get("parent_spec")),
        route_metadata_schema=_int_or_none(frontmatter.get("route_metadata_schema")),
        priority=(_scalar(frontmatter.get("priority")) or "").lower() or None,
        kind=(_scalar(frontmatter.get("kind")) or "").lower() or None,
        tags=tuple(tag.lower() for tag in _string_tuple(frontmatter.get("tags"))),
        queue_admission=((_scalar(frontmatter.get("queue_admission")) or "").lower() or None),
        assigned_to=_scalar(frontmatter.get("assigned_to")),
        lane_affinity=_scalar(frontmatter.get("lane_affinity")),
        epic_serialize=_scalar(frontmatter.get("epic_serialize")),
        frontmatter=dict(frontmatter),
    )


def _matching_tasks(pr: PullRequest, tasks: list[TaskNote]) -> list[TaskNote]:
    by_pr = [task for task in tasks if task.pr == pr.number]
    if by_pr:
        return by_pr
    return [task for task in tasks if task.branch == pr.head_ref]


def _release_authorized_head_blockers(
    frontmatter: dict[str, Any],
    *,
    pr_head_sha: str | None,
) -> tuple[str, ...]:
    assessment = assess_release_auto_arm(frontmatter)
    if not assessment.armed:
        return ()
    if not pr_head_sha:
        return ("release_authorized_head_unavailable",)
    blocker = _release_authorized_head_stamp_blocker(
        frontmatter,
        expected_head_sha=pr_head_sha,
        expected_label="current",
    )
    if blocker:
        return (blocker,)
    return ()


def _task_blockers(
    task: TaskNote,
    *,
    require_route_metadata: bool,
    open_pr_number: int | None = None,
    allow_release_auto_arm: bool = False,
    pr_head_sha: str | None = None,
    changed_files: tuple[str, ...] | None = None,
    changed_file_count: int | None = None,
) -> list[str]:
    blockers: list[str] = []
    if not task.authority_case:
        blockers.append("task_missing_authority_case")
    if not task.parent_spec:
        blockers.append("task_missing_parent_spec")
    if require_route_metadata and task.route_metadata_schema != 1:
        blockers.append("task_missing_route_metadata_schema_1")

    # Routing Phase 0.2: review-floor (frontier_review_required) tasks admit
    # only with a signed acceptance receipt beside the note. Applies to active
    # and closed task links alike; non-review-floor tasks return no blockers.
    blockers.extend(acceptance_receipt_blockers(task.frontmatter, task.path))

    # Review-team quorum gate (CASE-ROUTING-OPERATIONALIZATION-20260609): every
    # PR admits only with a quorum-accept review dossier beside the task note,
    # keyed to the PR's current head sha. No quorum, no merge. Dossiers are
    # produced by scripts/cc-pr-review-dispatch.py; emergency bypass is
    # HAPAX_REVIEW_TEAM_GATE_OFF=1 (gate only, not the whole autoqueue).
    blockers.extend(
        review_team.review_team_verdict_blockers(
            task.frontmatter,
            task.path,
            pr_head_sha=pr_head_sha,
            pr_number=open_pr_number,
            changed_files=changed_files or (),
            changed_file_count=changed_file_count,
        )
    )

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
    elif task.folder == "active":
        release_arm = assess_release_auto_arm(task.frontmatter)
        if release_arm.needs_arming and not allow_release_auto_arm:
            blockers.append("release_authorized_false")

    blockers.extend(_release_authorized_head_blockers(task.frontmatter, pr_head_sha=pr_head_sha))

    avsdlc_gate = evaluate_avsdlc_release_gate(task.frontmatter)
    blockers.extend(f"avsdlc_release_gate:{blocker}" for blocker in avsdlc_gate.blockers)
    return blockers


def _review_team_quorum_evidence_blockers(
    task: TaskNote,
    frontmatter: dict[str, Any],
    *,
    pr_number: int | None,
    pr_head_sha: str | None,
    changed_files: tuple[str, ...] | None,
    changed_file_count: int | None,
) -> tuple[str, ...]:
    return review_team.review_dossier_validity_blockers(
        frontmatter,
        task.path,
        pr_head_sha=pr_head_sha,
        pr_number=pr_number,
        changed_files=changed_files or (),
        changed_file_count=changed_file_count,
    )


def _release_mitigation_verified_checks(
    checks: set[str],
    task: TaskNote | None,
    frontmatter: dict[str, Any],
    *,
    pr_number: int | None,
    pr_head_sha: str | None,
    changed_files: tuple[str, ...] | None,
    changed_file_count: int | None,
) -> set[str]:
    verified = set(checks) - VIRTUAL_RELEASE_MITIGATION_CONTEXTS
    if task is None:
        return verified
    blockers = _review_team_quorum_evidence_blockers(
        task,
        frontmatter,
        pr_number=pr_number,
        pr_head_sha=pr_head_sha,
        changed_files=changed_files,
        changed_file_count=changed_file_count,
    )
    if not blockers:
        verified.add(REVIEW_TEAM_QUORUM_EVIDENCE)
    return verified


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
        if TASK_NOTE_PARSE_FAILURES:
            broken = ",".join(name for name, _ in TASK_NOTE_PARSE_FAILURES[:4])
            reasons.append(
                f"missing_cc_task_link (NOTE: {len(TASK_NOTE_PARSE_FAILURES)} unparseable task note(s): {broken} — fix or run scripts/cc-task-lint)"
            )
        else:
            reasons.append("missing_cc_task_link")
    else:
        for matched_task in matches:
            blockers = _task_blockers(
                matched_task,
                require_route_metadata=require_route_metadata,
                open_pr_number=pr.number,
                allow_release_auto_arm=len(matches) == 1,
                pr_head_sha=pr.head_sha,
                changed_files=pr.files,
                changed_file_count=pr.changed_files_count,
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
    # as the system (FM-20), the autoqueue may auto-arm a task once its release
    # gate is satisfied. Sensitivity is no longer a manual-arm veto (operator
    # directive 2026-06-22): the PR's verified checks are supplied as evidence,
    # so a sensitive class auto-arms iff its mitigation checks
    # (RELEASE_MITIGATION_CHECKS) passed.
    # Broad admission mirror checks remain ignored for release mitigation because
    # they can pass vacuously on ordinary PR events. An unmitigated class fails
    # closed (held until its gate is defined), never released by a manual
    # override.
    auto_arm = False
    auto_arm_verified_checks: tuple[str, ...] = ()
    if task is not None and not reasons:
        verified_checks = _release_mitigation_verified_checks(
            set(pr.check_summary.verified_passed),
            task,
            task.frontmatter,
            pr_number=pr.number,
            pr_head_sha=pr.head_sha,
            changed_files=pr.files,
            changed_file_count=pr.changed_files_count,
        )
        arm = assess_release_auto_arm(task.frontmatter, verified_checks=verified_checks)
        if arm.needs_arming:
            if arm.eligible:
                auto_arm = True
                auto_arm_verified_checks = tuple(sorted(verified_checks))
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
            auto_arm=auto_arm,
            auto_arm_verified_checks=auto_arm_verified_checks,
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
            auto_arm=auto_arm,
            auto_arm_verified_checks=auto_arm_verified_checks,
        )
    if pr.check_summary.has_pending:
        if include_pending_auto:
            return Decision(
                pr=pr,
                task=task,
                tasks=matched_tasks,
                action="enable_auto_merge",
                auto_arm=auto_arm,
                auto_arm_verified_checks=auto_arm_verified_checks,
            )
        return Decision(
            pr=pr,
            task=task,
            tasks=matched_tasks,
            action="blocked",
            reasons=("pending_checks:" + ",".join(pr.check_summary.pending),),
        )
    return Decision(
        pr=pr,
        task=task,
        tasks=matched_tasks,
        action="queue",
        auto_arm=auto_arm,
        auto_arm_verified_checks=auto_arm_verified_checks,
    )


def merge_pr(
    decision: Decision,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
    require_route_metadata: bool = True,
) -> tuple[bool, str]:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    graphql_args: list[str] | None = None
    if decision.action == "dequeue":
        if not decision.pr.node_id:
            return False, "missing_pull_request_node_id"
        query = "mutation($id:ID!){dequeuePullRequest(input:{id:$id}){clientMutationId}}"
        graphql_args = [
            "-f",
            f"query={query}",
            "-f",
            f"id={decision.pr.node_id}",
        ]
        cmd = ["gh", "api", "graphql", *graphql_args]
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
        if _decision_requires_head_guard(decision):
            boundary_blocker = _release_head_boundary_blocker(
                decision,
                require_route_metadata=require_route_metadata,
                repo=repo,
                repo_root=repo_root,
                runner=runner,
            )
            if boundary_blocker:
                return False, boundary_blocker
            cmd.extend(["--match-head-commit", decision.pr.head_sha])
    elif decision.action == "disable_auto_merge":
        cmd.append("--disable-auto")
    elif decision.action != "dequeue":
        return False, f"unsupported_action:{decision.action}"
    if graphql_args is not None:
        proc = run_graphql_rate_aware(
            graphql_args,
            repo_root=repo_root,
            runner=runner,
            timeout=120,
        )
    else:
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


def _release_auto_arm_current_admission_blockers(
    frontmatter: dict[str, Any],
    *,
    pr_number: int | None,
    head_ref: str | None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    current_status = (_scalar(frontmatter.get("status")) or "").lower()
    if current_status not in TASK_MERGE_READY_STATUSES:
        blockers.append(f"current_task_status_not_ready:{current_status or 'missing'}")

    current_pr = _int_or_none(frontmatter.get("pr"))
    current_branch = _scalar(frontmatter.get("branch"))
    expected_branch = _scalar(head_ref)
    if pr_number is not None:
        if current_pr is None:
            if not (expected_branch and current_branch == expected_branch):
                blockers.append(
                    "current_task_identity_missing_pr:"
                    f"expected_pr={pr_number}:"
                    f"branch={current_branch or 'missing'}:"
                    f"expected_branch={expected_branch or 'missing'}"
                )
        elif current_pr != pr_number:
            blockers.append(f"current_task_pr_mismatch:current={current_pr}:expected={pr_number}")
    if (
        expected_branch is not None
        and current_branch is not None
        and current_branch != expected_branch
    ):
        blockers.append(
            f"current_task_branch_mismatch:current={current_branch}:expected={expected_branch}"
        )
    return tuple(blockers)


def _release_auto_arm_current_task_gate_blockers(
    task: TaskNote,
    frontmatter: dict[str, Any],
    *,
    require_route_metadata: bool,
    pr_number: int | None,
    pr_head_sha: str | None,
    changed_files: tuple[str, ...] | None,
    changed_file_count: int | None,
) -> tuple[str, ...]:
    if frontmatter.get("type") != "cc-task":
        return ("current_task_not_cc_task",)
    current_task_id = _scalar(frontmatter.get("task_id"))
    if not current_task_id:
        return ("current_task_missing_task_id",)
    if current_task_id != task.task_id:
        return (f"current_task_id_mismatch:current={current_task_id}:expected={task.task_id}",)
    current_task = _task_note_with_frontmatter(task, frontmatter)
    return tuple(
        _task_blockers(
            current_task,
            require_route_metadata=require_route_metadata,
            open_pr_number=pr_number,
            allow_release_auto_arm=True,
            pr_head_sha=pr_head_sha,
            changed_files=changed_files,
            changed_file_count=changed_file_count,
        )
    )


def _release_authorized_head_stamp_blocker(
    frontmatter: dict[str, Any],
    *,
    expected_head_sha: str | None,
    expected_label: str = "expected",
) -> str | None:
    if expected_head_sha is None:
        return None
    authorized_head_sha = _scalar(frontmatter.get("release_authorized_head_sha"))
    if not authorized_head_sha:
        return f"release_authorized_head_missing:{expected_label}={expected_head_sha}"
    if authorized_head_sha != expected_head_sha:
        return (
            f"release_authorized_head_mismatch:"
            f"authorized={authorized_head_sha}:{expected_label}={expected_head_sha}"
        )
    return None


def _release_auto_arm_current_evidence_blockers(
    frontmatter: dict[str, Any],
    *,
    verified_checks: set[str],
) -> tuple[str, ...]:
    if "release_authorized" not in frontmatter:
        return ()
    probe = dict(frontmatter)
    probe["release_authorized"] = False
    assessment = assess_release_auto_arm(probe, verified_checks=verified_checks)
    blockers = assessment.blockers
    if assess_release_auto_arm(frontmatter, verified_checks=verified_checks).armed:
        # A sensitive path is an auto-arm veto, not a post-authorization veto.
        # Once a task is explicitly head-locked with release_authorized: true,
        # release-head revalidation should still replay current check/risk
        # evidence, but it must not strand the accepted manual release solely
        # because the authorized mutation scope includes CLAUDE.md/CODEOWNERS.
        blockers = tuple(
            blocker for blocker in blockers if not blocker.startswith("sensitive_path:")
        )
    return blockers


def _release_auto_arm_sensitive_path_waivers(
    frontmatter: dict[str, Any],
    *,
    verified_checks: set[str],
) -> tuple[str, ...]:
    if not assess_release_auto_arm(frontmatter, verified_checks=verified_checks).armed:
        return ()
    probe = dict(frontmatter)
    probe["release_authorized"] = False
    assessment = assess_release_auto_arm(probe, verified_checks=verified_checks)
    prefix = "sensitive_path:"
    return tuple(
        f"sensitive_path_waived_by_release_authorization:{blocker.removeprefix(prefix)}"
        for blocker in assessment.blockers
        if blocker.startswith(prefix)
    )


def _decision_requires_head_guard(decision: Decision) -> bool:
    if decision.action not in {"queue", "enable_auto_merge"}:
        return False
    return _decision_is_release_head_guard_subject(decision)


def _decision_is_release_head_guard_subject(decision: Decision) -> bool:
    if decision.auto_arm:
        return True
    if decision.task is None:
        return False
    return assess_release_auto_arm(decision.task.frontmatter).armed


def _release_head_boundary_blocker(
    decision: Decision,
    *,
    require_route_metadata: bool = True,
    changed_files: tuple[str, ...] | None = None,
    changed_file_count: int | None = None,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
    release_authorization_waivers: list[str] | None = None,
) -> str | None:
    if decision.action not in {
        "queue",
        "enable_auto_merge",
        "already_queued",
        "already_auto_merge_enabled",
    }:
        return None
    if not _decision_is_release_head_guard_subject(decision):
        return None
    if decision.task is None:
        return "release_authorized_task_missing"
    try:
        text = decision.task.path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"release_authorized_note_unreadable:{exc}"
    current_frontmatter = frontmatter_from_text(text)
    admission_blockers = _release_auto_arm_current_admission_blockers(
        current_frontmatter,
        pr_number=decision.pr.number,
        head_ref=decision.pr.head_ref,
    )
    if admission_blockers:
        return "current_task_not_admissible:" + ",".join(admission_blockers)
    if not decision.pr.head_sha:
        return "missing_head_sha_for_head_guard"
    gate_blockers = _release_auto_arm_current_task_gate_blockers(
        decision.task,
        current_frontmatter,
        require_route_metadata=require_route_metadata,
        pr_number=decision.pr.number,
        pr_head_sha=decision.pr.head_sha,
        changed_files=decision.pr.files if changed_files is None else changed_files,
        changed_file_count=(
            decision.pr.changed_files_count if changed_file_count is None else changed_file_count
        ),
    )
    if gate_blockers:
        return "current_task_gate_blocked:" + ",".join(gate_blockers)
    if not assess_release_auto_arm(current_frontmatter).armed:
        return "release_authorized_not_current"
    stamp_blocker = _release_authorized_head_stamp_blocker(
        current_frontmatter,
        expected_head_sha=decision.pr.head_sha,
        expected_label="current",
    )
    if stamp_blocker:
        return stamp_blocker
    evidence_ok, current_head_sha, current_verified_checks = fetch_pr_release_evidence(
        decision.pr.number,
        repo=repo,
        repo_root=repo_root,
        runner=runner,
    )
    if not evidence_ok:
        if current_head_sha in {
            "invalid_pr_release_evidence_payload",
            "invalid_status_check_rollup",
        }:
            return f"current_pr_checks_unreadable:{current_head_sha}"
        return f"current_pr_head_unreadable:{current_head_sha}"
    if current_head_sha != decision.pr.head_sha:
        return (
            f"current_pr_head_mismatch:current={current_head_sha}:expected={decision.pr.head_sha}"
        )
    current_verified_checks = _release_mitigation_verified_checks(
        current_verified_checks,
        decision.task,
        current_frontmatter,
        pr_number=decision.pr.number,
        pr_head_sha=current_head_sha,
        changed_files=decision.pr.files if changed_files is None else changed_files,
        changed_file_count=(
            decision.pr.changed_files_count if changed_file_count is None else changed_file_count
        ),
    )
    evidence_blockers = _release_auto_arm_current_evidence_blockers(
        current_frontmatter,
        verified_checks=current_verified_checks,
    )
    if evidence_blockers:
        return "current_release_auto_arm_blocked:" + ",".join(evidence_blockers)
    if release_authorization_waivers is not None:
        release_authorization_waivers.extend(
            _release_auto_arm_sensitive_path_waivers(
                current_frontmatter,
                verified_checks=current_verified_checks,
            )
        )
    return None


def _append_release_auto_arm_ledger(
    task: TaskNote,
    *,
    ledger_path: Path,
    now_iso: str,
    role: str,
    frontmatter: dict[str, Any] | None = None,
    pr_head_sha: str | None = None,
    pr_head_ref: str | None = None,
    verified_checks: set[str] | None = None,
    pre_arm_assessment: ReleaseAutoArmAssessment | None = None,
    post_arm_assessment: ReleaseAutoArmAssessment | None = None,
) -> None:
    """Append an audit record for a system release auto-arm. Best-effort."""
    ledger_frontmatter = frontmatter or task.frontmatter
    auto_arm_waivers = release_auto_arm_waivers(ledger_frontmatter)

    def assessment_record(assessment: ReleaseAutoArmAssessment) -> dict[str, Any]:
        return {
            "subject": assessment.subject,
            "armed": assessment.armed,
            "needs_arming": assessment.needs_arming,
            "eligible": assessment.eligible,
            "blockers": list(assessment.blockers),
        }

    record = {
        "ts": now_iso,
        "kind": "release_auto_arm",
        "tool": "cc-pr-autoqueue",
        "role": role,
        "task_id": task.task_id,
        "authority_case": (
            _scalar(ledger_frontmatter.get("authority_case") or ledger_frontmatter.get("case_id"))
            or task.authority_case
        ),
        "pr": task.pr,
        "note": str(task.path),
    }
    if pr_head_sha:
        record["pr_head_sha"] = pr_head_sha
        record["verified_checks_head_sha"] = pr_head_sha
        record["planned_autoqueue_admission_head_sha"] = pr_head_sha
        record["autoqueue_admission_proof_state"] = "pending_status_write"
    if pr_head_ref:
        record["pr_head_ref"] = pr_head_ref
    if verified_checks is not None:
        record["verified_checks"] = sorted(verified_checks)
    if pre_arm_assessment is not None:
        record["release_auto_arm_pre_arm_assessment"] = assessment_record(pre_arm_assessment)
    if post_arm_assessment is not None:
        record["release_auto_arm_assessment"] = assessment_record(post_arm_assessment)
        record["release_auto_arm_result"] = {
            "armed": post_arm_assessment.armed,
            "armed_at": now_iso,
            "note_mutated": True,
        }
    if auto_arm_waivers:
        record["auto_arm_waivers"] = list(auto_arm_waivers)
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
    verified_checks: set[str] | None = None,
    pr_number: int | None = None,
    head_ref: str | None = None,
    expected_head_sha: str | None = None,
    require_route_metadata: bool = True,
    changed_files: tuple[str, ...] | None = None,
    changed_file_count: int | None = None,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
) -> tuple[bool, str]:
    """Authorize release for a stranded task on behalf of a dead lane (system).

    Writes ``release_authorized: true`` + ``stage: S7_RELEASE`` to the note and
    appends an authority-case ledger record. The write boundary rereads the note
    and revalidates both release-arm eligibility and the current PR/task identity
    so a stale classifier decision cannot arm a repointed or no-longer-ready note.
    """
    ledger_path = ledger_path or default_authority_case_ledger()
    now = now or datetime.now(UTC)
    now_iso = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        text = task.path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"note_unreadable:{exc}"
    current_frontmatter = frontmatter_from_text(text)
    admission_blockers = _release_auto_arm_current_admission_blockers(
        current_frontmatter,
        pr_number=pr_number,
        head_ref=head_ref,
    )
    if admission_blockers:
        return False, "current_task_not_admissible:" + ",".join(admission_blockers)
    gate_blockers = _release_auto_arm_current_task_gate_blockers(
        task,
        current_frontmatter,
        require_route_metadata=require_route_metadata,
        pr_number=pr_number,
        pr_head_sha=expected_head_sha,
        changed_files=changed_files,
        changed_file_count=changed_file_count,
    )
    if gate_blockers:
        return False, "current_task_gate_blocked:" + ",".join(gate_blockers)
    if pr_number is not None and not expected_head_sha:
        return False, "current_pr_head_unverifiable:missing_expected_head_sha"
    if expected_head_sha and pr_number is None:
        return False, "current_pr_head_unverifiable:missing_pr_number"
    verified_checks = set(verified_checks or set()) - VIRTUAL_RELEASE_MITIGATION_CONTEXTS
    if expected_head_sha:
        evidence_ok, current_head_sha, current_verified_checks = fetch_pr_release_evidence(
            pr_number,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
        )
        if not evidence_ok:
            if current_head_sha in {
                "invalid_pr_release_evidence_payload",
                "invalid_status_check_rollup",
            }:
                return False, f"current_pr_checks_unreadable:{current_head_sha}"
            return False, f"current_pr_head_unreadable:{current_head_sha}"
        if current_head_sha != expected_head_sha:
            return (
                False,
                f"current_pr_head_mismatch:current={current_head_sha}:expected={expected_head_sha}",
            )
        verified_checks = _release_mitigation_verified_checks(
            current_verified_checks,
            task,
            current_frontmatter,
            pr_number=pr_number,
            pr_head_sha=current_head_sha,
            changed_files=changed_files,
            changed_file_count=changed_file_count,
        )
    pre_arm_assessment = assess_release_auto_arm(
        current_frontmatter, verified_checks=verified_checks
    )
    if not pre_arm_assessment.eligible:
        if pre_arm_assessment.armed:
            head_stamp_blocker = _release_authorized_head_stamp_blocker(
                current_frontmatter,
                expected_head_sha=expected_head_sha,
            )
            if head_stamp_blocker:
                return False, head_stamp_blocker
            return True, "note_unchanged"
        reasons = ",".join(pre_arm_assessment.blockers or ("not_eligible",))
        return False, f"release_auto_arm_ineligible:{reasons}"
    armed = apply_release_auto_arm(
        text,
        now_iso=now_iso,
        role=role,
        head_sha=expected_head_sha,
        head_ref=head_ref,
    )
    if armed == text:
        return False, "note_unchanged"
    try:
        task.path.write_text(armed, encoding="utf-8")
    except OSError as exc:
        return False, f"note_write_failed:{exc}"
    post_arm_assessment = assess_release_auto_arm(
        frontmatter_from_text(armed), verified_checks=verified_checks
    )
    _append_release_auto_arm_ledger(
        task,
        ledger_path=ledger_path,
        now_iso=now_iso,
        role=role,
        frontmatter=current_frontmatter,
        pr_head_sha=expected_head_sha,
        pr_head_ref=head_ref,
        verified_checks=verified_checks,
        pre_arm_assessment=pre_arm_assessment,
        post_arm_assessment=post_arm_assessment,
    )
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


def _parse_status_created_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def _latest_admission_status(
    head_sha: str,
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
) -> tuple[str, str, datetime | None] | None:
    """The most recent autoqueue-admission (state, description, created_at) on
    ``head_sha``, or None when absent/unreadable. Read-before-write lets the
    reconciler POST a fresh status only when it actually changed or is about to
    go stale: GitHub caps statuses at 1000 per SHA+context, and the old
    unconditional POST burned that cap into a 422 self-DoS that made the apply
    loop skip the queue mutation."""
    cmd = ["gh", "api", f"repos/{repo}/commits/{head_sha}/statuses"]
    proc = runner(cmd, cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=60)
    if getattr(proc, "returncode", 1) != 0:
        return None
    try:
        items = json.loads(proc.stdout or "[]")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(items, list):
        return None
    for item in items:  # the statuses API returns most-recent-first
        if isinstance(item, dict) and item.get("context") == AUTOQUEUE_ADMISSION_CONTEXT:
            return (
                str(item.get("state") or ""),
                str(item.get("description") or ""),
                _parse_status_created_at(item.get("created_at")),
            )
    return None


def set_autoqueue_admission_status(
    decision: Decision,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
    now: datetime | None = None,
    force_fresh_success: bool = False,
) -> tuple[bool, str] | None:
    """Write the server-visible autoqueue admission proof for a PR head SHA.

    Idempotent (G3): reads the current status first and POSTs only when the
    (state, description) changed OR the existing status is older than half the
    proof TTL. GitHub caps statuses at 1000 per SHA+context; the old
    unconditional POST burned that cap into a 422 self-DoS that made the apply
    loop skip the queue mutation."""
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    now = now or datetime.now(UTC)
    status = _admission_status_for(decision)
    if status is None:
        return None
    if not decision.pr.head_sha:
        return False, "missing_head_sha"
    state, description = status
    current = _latest_admission_status(
        decision.pr.head_sha, repo=repo, repo_root=repo_root, runner=runner
    )
    if current is not None:
        cur_state, cur_description, cur_created = current
        if cur_state == state == "failure":
            if cur_description == description:
                return True, "unchanged_failure_state"
            fresh_failure_description = cur_created is not None and (now - cur_created) < timedelta(
                seconds=FAILURE_DESCRIPTION_REFRESH_SECONDS
            )
            if fresh_failure_description:
                return True, "deferred_failure_description_update"
        unchanged = cur_state == state and cur_description == description
        fresh = cur_created is not None and (now - cur_created) < timedelta(
            seconds=AUTOQUEUE_ADMISSION_TTL_SECONDS / 2
        )
        if unchanged and fresh and not (force_fresh_success and state == "success"):
            return True, "unchanged"
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


def _release_auto_arm_fail_closed_decision(
    decision: Decision,
    message: str,
    *,
    reason_prefix: str = "release_auto_arm_failed",
) -> Decision | None:
    if decision.action == "already_queued":
        action = "dequeue"
    elif decision.action == "already_auto_merge_enabled":
        action = "disable_auto_merge"
    elif decision.action in {"queue", "enable_auto_merge"}:
        action = "blocked"
    else:
        return None
    return Decision(
        pr=decision.pr,
        task=decision.task,
        tasks=decision.tasks,
        action=action,
        reasons=(f"{reason_prefix}:{message}",),
    )


def _release_auto_arm_write_ok(ok: bool, message: str) -> bool:
    return ok or message == "note_unchanged"


def _remove_admitted_pr_for_release_auto_arm_failure(
    decision: Decision,
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
) -> tuple[bool, str]:
    if decision.action not in {"dequeue", "disable_auto_merge"}:
        return False, f"unsupported_release_auto_arm_removal:{decision.action}"
    return merge_pr(decision, repo=repo, repo_root=repo_root, runner=runner)


def _release_auto_arm_fail_closed_mutations(
    decision: Decision,
    message: str,
    *,
    reason_prefix: str = "release_auto_arm_failed",
    repo: str,
    repo_root: Path,
    runner: Any,
    now: datetime,
) -> list[dict[str, Any]]:
    fail_decision = _release_auto_arm_fail_closed_decision(
        decision,
        message,
        reason_prefix=reason_prefix,
    )
    if fail_decision is None:
        return []

    results: list[dict[str, Any]] = []
    fail_status = _admission_status_for(fail_decision)
    fail_status_result = set_autoqueue_admission_status(
        fail_decision,
        repo=repo,
        repo_root=repo_root,
        runner=runner,
        now=now,
    )
    if fail_status_result is not None:
        if fail_status is None:
            results.append(
                {
                    **fail_decision.as_dict(),
                    "action": "set_admission_status",
                    "status_state": "missing",
                    "ok": False,
                    "message": "missing_fail_closed_admission_status",
                }
            )
        else:
            ok, status_message = fail_status_result
            results.append(
                {
                    **fail_decision.as_dict(),
                    "action": "set_admission_status",
                    "status_state": fail_status[0],
                    "ok": ok,
                    "message": status_message,
                }
            )
    if fail_decision.action in {"dequeue", "disable_auto_merge"}:
        ok, merge_message = _remove_admitted_pr_for_release_auto_arm_failure(
            fail_decision,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
        )
        results.append(
            {
                **fail_decision.as_dict(),
                "ok": ok,
                "message": merge_message,
            }
        )
    return results


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
    report_path: Path | None = None,
    admission_governor_path: Path = DEFAULT_ADMISSION_GOVERNOR_PATH,
    runner: Any = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    if any(os.environ.get(name) == "1" for name in KILLSWITCH_ENVS):
        report = {
            "repo": repo,
            "apply": apply,
            "skipped": True,
            "reason": "killswitch",
            "killswitch_envs": list(KILLSWITCH_ENVS),
        }
        return _finalize_reconciler_report(
            report,
            report_path=report_path,
            admission_governor_path=admission_governor_path,
            now=now,
        )

    repo_root = repo_root or default_repo_root()
    tasks = load_task_notes(vault_root)
    active_ci_repair_task_ids = _active_ci_repair_task_ids(tasks)
    queued_prs_snapshot = fetch_merge_queue_pr_numbers(
        repo=repo, repo_root=repo_root, runner=runner
    )
    if queued_prs_snapshot is None:
        report = {
            "repo": repo,
            "apply": apply,
            "skipped": True,
            "reason": "merge_queue_state_indeterminate",
            "detail": "native merge-queue GraphQL probe failed or backed off; no queue mutations attempted",
        }
        return _finalize_reconciler_report(
            report,
            report_path=report_path,
            admission_governor_path=admission_governor_path,
            now=now,
        )
    queued_prs = queued_prs_snapshot
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
            admission_status = _admission_status_for(decision)
            release_head_subject = decision.action in {
                "queue",
                "enable_auto_merge",
                "already_queued",
                "already_auto_merge_enabled",
            }
            if release_head_subject:
                if decision.auto_arm and decision.task is not None:
                    armed_ok, armed_message = arm_release_for_task(
                        decision.task,
                        ledger_path=auto_arm_ledger_path,
                        now=now,
                        verified_checks=set(decision.auto_arm_verified_checks),
                        pr_number=decision.pr.number,
                        head_ref=decision.pr.head_ref,
                        expected_head_sha=decision.pr.head_sha,
                        require_route_metadata=require_route_metadata,
                        changed_files=decision.pr.files,
                        changed_file_count=decision.pr.changed_files_count,
                        repo=repo,
                        repo_root=repo_root,
                        runner=runner,
                    )
                    auto_arm_ok = _release_auto_arm_write_ok(armed_ok, armed_message)
                    if not auto_arm_ok:
                        mutation_results.append(
                            {
                                **decision.as_dict(),
                                "action": "release_auto_arm",
                                "ok": False,
                                "message": f"release auto-arm failed: {armed_message}",
                            }
                        )
                        mutation_results.extend(
                            _release_auto_arm_fail_closed_mutations(
                                decision,
                                armed_message,
                                repo=repo,
                                repo_root=repo_root,
                                runner=runner,
                                now=now,
                            )
                        )
                        continue
                    mutation_results.append(
                        {
                            **decision.as_dict(),
                            "action": "release_auto_arm",
                            "ok": True,
                            "message": armed_message,
                        }
                    )
                release_authorization_waivers: list[str] = []
                head_blocker = _release_head_boundary_blocker(
                    decision,
                    require_route_metadata=require_route_metadata,
                    changed_files=decision.pr.files,
                    changed_file_count=decision.pr.changed_files_count,
                    repo=repo,
                    repo_root=repo_root,
                    runner=runner,
                    release_authorization_waivers=release_authorization_waivers,
                )
                if head_blocker is not None:
                    mutation_results.append(
                        {
                            **decision.as_dict(),
                            "action": "release_head_revalidation",
                            "ok": False,
                            "message": head_blocker,
                        }
                    )
                    mutation_results.extend(
                        _release_auto_arm_fail_closed_mutations(
                            decision,
                            head_blocker,
                            reason_prefix="release_head_revalidation_failed",
                            repo=repo,
                            repo_root=repo_root,
                            runner=runner,
                            now=now,
                        )
                    )
                    continue
                if release_authorization_waivers:
                    mutation_results.append(
                        {
                            **decision.as_dict(),
                            "action": "release_authorization_waiver",
                            "ok": True,
                            "waivers": release_authorization_waivers,
                        }
                    )
            status_result = set_autoqueue_admission_status(
                decision,
                repo=repo,
                repo_root=repo_root,
                runner=runner,
                now=now,
                force_fresh_success=_decision_is_release_head_guard_subject(decision),
            )
            if decision.action not in {
                "queue",
                "enable_auto_merge",
                "disable_auto_merge",
                "dequeue",
            }:
                if status_result is not None:
                    assert admission_status is not None
                    ok, message = status_result
                    mutation_results.append(
                        {
                            **decision.as_dict(),
                            "action": "set_admission_status",
                            "status_state": admission_status[0],
                            "ok": ok,
                            "message": message,
                        }
                    )
                    if not ok:
                        mutation_results.extend(
                            _release_auto_arm_fail_closed_mutations(
                                decision,
                                message,
                                reason_prefix="admission_status_write_failed",
                                repo=repo,
                                repo_root=repo_root,
                                runner=runner,
                                now=now,
                            )
                        )
                continue
            if (
                decision.action in {"queue", "enable_auto_merge"}
                and status_result is not None
                and not status_result[0]
            ):
                assert admission_status is not None
                mutation_results.append(
                    {
                        **decision.as_dict(),
                        "action": "set_admission_status",
                        "status_state": admission_status[0],
                        "ok": False,
                        "message": "admission status write failed; queue mutation skipped",
                        "admission_status": {
                            "state": admission_status[0],
                            "ok": status_result[0],
                            "message": status_result[1],
                        },
                    }
                )
                continue
            ok, message = merge_pr(
                decision,
                repo=repo,
                repo_root=repo_root,
                runner=runner,
                require_route_metadata=require_route_metadata,
            )
            result = {
                **decision.as_dict(),
                "ok": ok,
                "message": message,
            }
            if status_result is not None:
                assert admission_status is not None
                status_ok, status_message = status_result
                result["admission_status"] = {
                    "state": admission_status[0],
                    "ok": status_ok,
                    "message": status_message,
                }
            mutation_results.append(result)
            if (
                not ok
                and admission_status is not None
                and admission_status[0] == "success"
                and status_result is not None
            ):
                mutation_results.extend(
                    _release_auto_arm_fail_closed_mutations(
                        decision,
                        message,
                        reason_prefix="queue_mutation_failed",
                        repo=repo,
                        repo_root=repo_root,
                        runner=runner,
                        now=now,
                    )
                )

    report = {
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
    return _finalize_reconciler_report(
        report,
        report_path=report_path,
        admission_governor_path=admission_governor_path,
        now=now,
    )


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
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Stable JSON feed path for cockpit/coord consumers.",
    )
    parser.add_argument(
        "--admission-governor-path",
        type=Path,
        default=DEFAULT_ADMISSION_GOVERNOR_PATH,
        help="Admission governor YAML path included raw in the stable report.",
    )
    parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not write the stable cockpit/coord JSON feed.",
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
        report_path=None if args.no_write_report else args.report_path,
        admission_governor_path=args.admission_governor_path,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
