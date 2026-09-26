#!/usr/bin/env python3
"""cc-pr-autoqueue — governed PR auto-queue reconciler.

The merge queue should not depend on a human/session remembering to run
``gh pr merge`` after a governed PR is ready. This reconciler scans open PRs,
matches each PR to a cc-task in the local Obsidian vault, and ARMS auto-merge
only when Hapax governance and GitHub protection state both pass.

Arm-only (task reform-native-merge-queue): the sole positive GitHub mutation is
one idempotent ``gh pr merge --auto`` whose merge method is verified against the
active ``main-merge-queue`` ruleset. GitHub's native merge queue then owns
batching, speculative ``gh-readonly-queue`` branches, auto-rebase, and
bisect-on-failure — this script no longer issues a direct merge or manages the
queue itself, which previously raced GitHub's own batching and stranded PRs.

Usage::

    uv run python scripts/cc-pr-autoqueue.py
    uv run python scripts/cc-pr-autoqueue.py --apply
    HAPAX_CC_PR_AUTOQUEUE_OFF=1 uv run python scripts/cc-pr-autoqueue.py --apply
    uv run python scripts/cc-pr-autoqueue.py --apply --expected-merge-method SQUASH
    HAPAX_CC_PR_AUTOQUEUE_EXPECTED_MERGE_METHOD=SQUASH uv run python scripts/cc-pr-autoqueue.py --apply

Default mode is a dry-run report. ``--apply`` performs the GitHub mutation.
``--expected-merge-method`` overrides the desired strategy; applicable queue
governance must still be verified. The report records the override source.
No merge-method bypass flag exists by design. During a GitHub rulesets outage,
stop the autoqueue timer with ``systemctl --user stop hapax-cc-pr-autoqueue.timer``
until governance is readable again, then run
``systemctl --user start hapax-cc-pr-autoqueue.timer``. The override is not an
outage bypass.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
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
    REST_INDETERMINATE_CHECK_NAME,
    ListingRoute,
    PrListingUnavailable,
    RestIndeterminateError,
    _pull_status_row_from_rest,
    _rest_get_json,
    choose_transport,
    fetch_status_check_rollup_rest,
    get_pr_status_graphql,
    get_pull_rest,
    graphql_pool_blocked,
    list_open_pr_statuses,
    listing_unavailable_detail,
    pr_reference_reasons,
    rate_snapshot,
    read_ref_name,
    rest_merge_state_status,
    rest_pool_blocked,
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
from shared.release_gate import (  # noqa: E402
    assess_release_auto_arm_estate,
    evaluate_avsdlc_release_gate,
)
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
DEFAULT_ROTATION_STATE_PATH = DEFAULT_REPORT_PATH.with_name("cc-pr-autoqueue-examined.json")
DEFAULT_ADMISSION_GOVERNOR_PATH = Path.home() / ".cache" / "hapax" / "pr-admission-governor.yaml"
KILLSWITCH_ENVS = ("HAPAX_CC_PR_AUTOQUEUE_OFF", "HAPAX_CC_HYGIENE_OFF")
EXPECTED_MERGE_METHOD_OVERRIDE_ENV = "HAPAX_CC_PR_AUTOQUEUE_EXPECTED_MERGE_METHOD"
OVERRIDE_CONTRADICTION_PREFIX = "auto_merge_method_override_contradicts_queue_governance:"
TRANSIENT_TRANSPORT_UNVERIFIED_PREFIX = "auto_merge_method_unverified:transient_transport:"

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
AUTOQUEUE_MERGE_QUEUE_RULESET_NAME = "main-merge-queue"
AUTOQUEUE_DEFAULT_MERGE_METHOD = "SQUASH"
GITHUB_MERGE_METHOD_FLAGS = {
    "MERGE": "--merge",
    "REBASE": "--rebase",
    "SQUASH": "--squash",
}
AUTOQUEUE_IGNORED_CHECK_CONTEXTS = {
    AUTOQUEUE_ADMISSION_CONTEXT,
    REVIEW_TEAM_QUORUM_EVIDENCE,
    "governance-gate",
    "hkp-advisory",
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
# Must-include guarantee (spec autoqueue-queued-pr-decision-guarantee-20260923):
# merge-queued and auto-merge-armed PRs get an admission-proof refresh every
# tick through a cheap path, because the fair rotation re-examines the estate
# on a ~102-minute cycle while the merge-group gate demands proofs younger
# than the 30-minute TTL (evidence: #4715 03:47Z, #4711 ~04:5xZ, 2026-09-23).
MUST_INCLUDE_CAP = 8
# Rotation slots preserved even when must-include fills the window: without
# them, a queued backlog would freeze ordinary reconciliation entirely.
MUST_INCLUDE_RESERVE = 2
# Refresh POSTs per tick across all must-include PRs. At q=2 the R4 margin
# spends ~20 POSTs/hr against GitHub's ~500/hr content limit.
MUST_INCLUDE_REFRESH_POST_CAP = 4
# R4: refresh must-include proofs when older than one tick (~6 min), not
# TTL/2 — tolerates 3-4 missed ticks before the gate sees a stale proof.
MUST_INCLUDE_REFRESH_MARGIN_SECONDS = 6 * 60
# R3: the persisted last-known must-include set lives no longer than the
# proof TTL it exists to keep fresh.
MUST_INCLUDE_STATE_MAX_AGE_SECONDS = AUTOQUEUE_ADMISSION_TTL_SECONDS
# Fresh evidence (spec autoqueue-admits-fresh-receipt-or-dossier-next-tick-20260924):
# an acceptance receipt or review dossier written after a PR's last examination
# changes its admission inputs, yet the PR is neither queued nor armed, so the
# rotation alone left the stale admission status standing for a full cycle
# (#4729: examined 22:07:20Z, receipt 21 s later, next exam ~17 ticks away).
# Such a PR takes a one-shot full exam in a must-include seat, after the
# queued/armed/dequeued seats and under the same cap and reserve.
FRESH_EVIDENCE_TIMESTAMP_FIELDS = ("timestamp", "constituted_at")
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
class MergeQueueGovernance:
    method: str | None = None
    source: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PullRequest:
    number: int
    node_id: str | None
    title: str
    head_ref: str | None
    head_sha: str | None
    files: tuple[str, ...] | None
    changed_files_count: int | None
    body: str
    is_draft: bool
    merge_state_status: str
    labels: tuple[str, ...]
    review_decision: str | None
    auto_merge_enabled: bool
    auto_merge_method: str | None
    check_summary: CheckSummary
    base_ref: str | None = None
    default_branch: str | None = None
    queue_governance: MergeQueueGovernance | None = None
    base_ref_detail: str | None = None
    base_ref_detail_latest: str | None = None
    default_branch_detail: str | None = None
    reference_reasons: tuple[str, ...] = ()
    # Paths the PR deletes; None when any file's change status is unknown.
    deleted_files: tuple[str, ...] | None = None


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
    expected_auto_merge_method: str | None = None

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
        if self.pr.auto_merge_enabled:
            out["auto_merge_method"] = self.pr.auto_merge_method
        governance = self.pr.queue_governance
        if governance is not None:
            out["merge_queue_governance"] = {
                "base_ref": self.pr.base_ref,
                "method": governance.method,
                "source": governance.source,
                "reason": governance.reason,
            }
            if self.pr.base_ref_detail:
                out["merge_queue_governance"]["base_ref_detail"] = self.pr.base_ref_detail
            if self.pr.base_ref_detail_latest:
                out["merge_queue_governance"]["base_ref_detail_latest"] = (
                    self.pr.base_ref_detail_latest
                )
            if self.pr.default_branch_detail:
                out["merge_queue_governance"]["default_branch_detail"] = (
                    self.pr.default_branch_detail
                )
            if self.pr.auto_merge_enabled:
                out["auto_merge_method_owner"] = (
                    "unverified"
                    if governance.reason
                    or (
                        self.action in {"blocked", "hold"}
                        and any(
                            reason.startswith(OVERRIDE_CONTRADICTION_PREFIX)
                            for reason in self.reasons
                        )
                    )
                    else "merge_queue"
                    if governance.method
                    else "pull_request"
                )
        if (
            self.expected_auto_merge_method is not None
            and self.expected_auto_merge_method != AUTOQUEUE_DEFAULT_MERGE_METHOD
        ):
            out["expected_auto_merge_method"] = self.expected_auto_merge_method
        if next_action := _decision_next_action(self.action, self.reasons):
            out["next_action"] = next_action
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


def _normalize_merge_method(value: Any) -> str | None:
    text = _scalar(value)
    if text is None:
        return None
    normalized = text.replace("-", "_").upper()
    if normalized == "MERGE_COMMIT":
        return "MERGE"
    if normalized in GITHUB_MERGE_METHOD_FLAGS:
        return normalized
    return None


def _supported_merge_methods_label() -> str:
    return ",".join(sorted(GITHUB_MERGE_METHOD_FLAGS))


def _merge_method_operator_next_action(
    *,
    ruleset_name: str = AUTOQUEUE_MERGE_QUEUE_RULESET_NAME,
) -> str:
    methods = _supported_merge_methods_label()
    return (
        f"Find active branch ruleset {ruleset_name} with "
        f'`gh api repos/<repo>/rulesets --jq \'.[] | select(.name=="{ruleset_name}" '
        'and .target=="branch" and .enforcement=="active") | .id\'`, then inspect '
        "`gh api repos/<repo>/rulesets/<ruleset_id> --jq "
        "'.rules[] | select(.type==\"merge_queue\") | .parameters.merge_method'` "
        f"and verify one of {methods}; "
        "set `--expected-merge-method <METHOD>` or "
        f"{EXPECTED_MERGE_METHOD_OVERRIDE_ENV}=<METHOD> to match the applicable queue strategy, "
        "or remove the contradictory override. Restore unreadable governance evidence "
        "before retrying; an override cannot replace that evidence. No merge-method bypass "
        "flag exists by design. During a GitHub rulesets outage, run "
        "`systemctl --user stop hapax-cc-pr-autoqueue.timer` until governance is readable "
        "again, then run `systemctl --user start hapax-cc-pr-autoqueue.timer`."
    )


def _decision_next_action(action: str, reasons: tuple[str, ...]) -> str | None:
    if _transient_transport_refusal_only(list(reasons)):
        return (
            "The merge-queue ruleset fetch hit a transient transport window (rate limit or "
            "GitHub unavailable), which says nothing about this PR. A queued entry is held in "
            "place — not dequeued — and no admission status is written; the next reconciler "
            "pass re-evaluates once the window clears. No operator action is required."
        )
    if _missing_cc_task_link_only(list(reasons)):
        return (
            "This PR has no matching vault cc-task note. A queued entry is held in place — "
            "not dequeued — and hapax/autoqueue-admission stays pending until a note exists. "
            "Add or fix the note (scripts/cc-task-lint); the next reconciler pass can then "
            "admit."
        )
    if any(reason.startswith(OVERRIDE_CONTRADICTION_PREFIX) for reason in reasons):
        return _merge_method_operator_next_action()
    merge_method_reason = any(
        reason.startswith("auto_merge_method_mismatch")
        or reason.startswith("auto_merge_method_unverified")
        or reason.startswith("auto_merge_method_unrecognized")
        for reason in reasons
    )
    override_governance_reason = any(
        reason.startswith("auto_merge_method_unverified:") and ":override=" in reason
        for reason in reasons
    )
    if action == "dequeue" and merge_method_reason:
        if override_governance_reason:
            return (
                "This decision removes the PR from the native merge queue when run "
                "with --apply; it does not disable auto-merge. Queue governance "
                f"evidence is unverified. {_merge_method_operator_next_action()}"
            )
        if any(
            reason.startswith("auto_merge_method_unverified:expected_missing") for reason in reasons
        ):
            return (
                "This decision removes the PR from the native merge queue when run "
                "with --apply; it does not disable auto-merge. Expected merge-method "
                f"evidence is missing. {_merge_method_operator_next_action()}"
            )
        return (
            "This decision removes the PR from the native merge queue when run with "
            "--apply; it does not disable auto-merge. After a successful dequeue, "
            "the next reconciler pass revalidates queue membership and armed "
            "auto-merge state before choosing any disable or re-arm mutation."
        )
    if override_governance_reason or any(
        reason.startswith("auto_merge_method_unverified:expected_missing") for reason in reasons
    ):
        return _merge_method_operator_next_action()
    if action != "disable_auto_merge":
        return None
    if any(
        reason.startswith("auto_merge_method_mismatch")
        or reason.startswith("auto_merge_method_unverified:armed_missing")
        or reason.startswith("auto_merge_method_unrecognized")
        for reason in reasons
    ):
        return (
            "This decision disables auto-merge when run with --apply and the GitHub "
            "command succeeds; after a successful disable, the next reconciler pass "
            "will re-arm with the verified merge queue method if the PR remains otherwise "
            "admissible."
        )
    return None


def _auto_merge_request_method(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    raw_method = _scalar(value.get("mergeMethod") or value.get("merge_method"))
    if raw_method is None:
        return None
    return _normalize_merge_method(raw_method) or raw_method


def _merge_method_mismatch_reason(
    pr: PullRequest,
    *,
    expected_auto_merge_method: str,
) -> str | None:
    expected = _normalize_merge_method(expected_auto_merge_method)
    armed = _normalize_merge_method(pr.auto_merge_method)
    assert expected is not None
    if armed is None:
        raw_armed = _scalar(pr.auto_merge_method)
        if raw_armed is not None:
            return f"auto_merge_method_unrecognized:armed={raw_armed}:expected={expected}"
        return f"auto_merge_method_unverified:armed_missing:expected={expected}"
    if armed != expected:
        return f"auto_merge_method_mismatch:armed={armed}:expected={expected}"
    return None


def _expected_merge_method_unverified_reason(source: str | None) -> str:
    detail = _scalar(source) or "source_missing"
    # A rulesets fetch that failed on a transient transport window (rate-limit / 429 / 5xx)
    # says nothing about the PR — the same fetch succeeds at the next reset. Emit a distinct
    # reason so the queue decision HOLDS a queued entry instead of dequeuing it, and so the
    # admission-status writer skips the `failure` write that would drop the entry. Reuses the
    # one canonical transport-window classifier; adds no second predicate for the same hazard.
    if detail.startswith("rulesets_fetch_failed:"):
        message = detail[len("rulesets_fetch_failed:") :]
        if _admission_status_write_deferral_class(message) in {
            "github_rate_limit",
            "github_unavailable",
        }:
            return f"auto_merge_method_unverified:transient_transport:source={detail}"
    return f"auto_merge_method_unverified:expected_missing:source={detail}"


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


def _gh_api_get_json(
    path: str,
    *,
    repo_root: Path,
    runner: Any,
) -> tuple[bool, Any, str]:
    cmd = [
        "gh",
        "api",
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        path,
    ]
    try:
        proc = runner(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, None, "gh_api_timeout:TimeoutExpired"
    except OSError as exc:
        return False, None, f"gh_api_invocation_error:{exc.__class__.__name__}"
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return False, None, output or f"gh api failed rc={proc.returncode}"
    try:
        return True, json.loads(proc.stdout or "null"), "ok"
    except (json.JSONDecodeError, TypeError) as exc:
        return False, None, f"invalid_json:{exc.__class__.__name__}"


def _merge_queue_method_from_ruleset(ruleset: Any) -> tuple[str | None, str | None]:
    if not isinstance(ruleset, dict):
        return None, None
    rules = ruleset.get("rules")
    if not isinstance(rules, list):
        return None, None
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "merge_queue":
            continue
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict):
            continue
        raw_method = parameters.get("merge_method")
        method = _normalize_merge_method(raw_method)
        if method:
            return method, None
        if raw_method_text := _scalar(raw_method):
            return None, f"unsupported_auto_merge_method:raw={raw_method_text}"
    return None, None


def fetch_merge_queue_merge_method(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
    ruleset_name: str = AUTOQUEUE_MERGE_QUEUE_RULESET_NAME,
) -> tuple[str | None, str]:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    ok, rulesets, message = _gh_api_get_json(
        f"repos/{repo}/rulesets",
        repo_root=repo_root,
        runner=runner,
    )
    if not ok:
        return None, f"rulesets_fetch_failed:{message}"
    if not isinstance(rulesets, list):
        return None, f"rulesets_payload_not_list:{type(rulesets).__name__}"

    active_branch_rulesets = [
        item
        for item in rulesets
        if isinstance(item, dict)
        and item.get("target") == "branch"
        and item.get("enforcement") == "active"
    ]
    named_rulesets = sorted(
        (item for item in active_branch_rulesets if _scalar(item.get("name")) == ruleset_name),
        key=lambda item: str(item.get("id") or ""),
    )
    if not named_rulesets:
        return None, f"active_named_merge_queue_ruleset_missing:{ruleset_name}"

    ruleset = named_rulesets[0]
    ruleset_id = ruleset.get("id")
    ruleset_label = _scalar(ruleset.get("name")) or str(ruleset_id or "unknown")
    method, method_error = _merge_queue_method_from_ruleset(ruleset)
    if method:
        return method, f"ruleset:{ruleset_label}:{ruleset_id or 'inline'}"
    if method_error:
        return None, f"{method_error}:ruleset={ruleset_label}:{ruleset_id or 'inline'}"
    if ruleset_id is None:
        return None, f"active_named_merge_queue_ruleset_method_missing:{ruleset_name}:id_missing"

    ok, detail, message = _gh_api_get_json(
        f"repos/{repo}/rulesets/{ruleset_id}",
        repo_root=repo_root,
        runner=runner,
    )
    if not ok:
        return None, f"ruleset_detail_fetch_failed:{ruleset_label}:{message}"
    method, method_error = _merge_queue_method_from_ruleset(detail)
    if method:
        return method, f"ruleset:{ruleset_label}:{ruleset_id}"
    if method_error:
        return None, f"{method_error}:ruleset={ruleset_label}:{ruleset_id}"
    return None, f"active_named_merge_queue_ruleset_method_missing:{ruleset_name}"


def _ruleset_applies_to_pr(ruleset: dict[str, Any], pr: PullRequest) -> bool | None:
    """Resolve observed ref conditions; unfamiliar pattern syntax stays unknown."""
    conditions = ruleset.get("conditions")
    refs = conditions.get("ref_name") if isinstance(conditions, dict) else None
    if not isinstance(refs, dict) or not pr.base_ref:
        return None
    matches: dict[str, bool] = {}
    for key in ("include", "exclude"):
        patterns = refs.get(key)
        if not isinstance(patterns, list) or (key == "include" and not patterns):
            return None
        matches[key] = False
        for pattern in patterns:
            if pattern == "~ALL":
                match = True
            elif pattern == "~DEFAULT_BRANCH":
                if not pr.default_branch:
                    return None
                match = pr.base_ref == pr.default_branch
            elif (
                isinstance(pattern, str)
                and pattern.startswith("refs/heads/")
                and not any(char in pattern for char in "*?[]\\")
            ):
                match = pattern == f"refs/heads/{pr.base_ref}"
            else:
                return None
            matches[key] |= match
    return matches["include"] and not matches["exclude"]


def fetch_pr_merge_queue_governance(
    pr: PullRequest,
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
) -> MergeQueueGovernance:
    """Validate all enforced queue rules for this base, separately from arm flags.

    The REST status adapter carries base.ref and base.repo.default_branch from
    the list payload, with detail reads as a secondary source. REST does not
    expose isInMergeQueue/mergeQueueEntry. An empty queue membership list
    cannot establish that ordinary per-PR auto-merge owns the strategy.
    """
    prefix = "auto_merge_method_unverified:"
    if pr.reference_reasons:
        return MergeQueueGovernance(reason=prefix + pr.reference_reasons[0])
    if not pr.base_ref:
        return MergeQueueGovernance(reason=prefix + "pr_base_ref_missing")
    if pr.base_ref_detail and pr.base_ref_detail != pr.base_ref:
        return MergeQueueGovernance(
            reason=prefix + f"pr_base_ref_conflict:list={pr.base_ref}:detail={pr.base_ref_detail}"
        )
    if pr.default_branch_detail and pr.default_branch_detail != pr.default_branch:
        return MergeQueueGovernance(
            reason=prefix
            + f"pr_default_branch_conflict:list={pr.default_branch}:detail={pr.default_branch_detail}"
        )
    methods: set[str] = set()
    sources: list[str] = []
    page = 1
    while True:
        try:
            rulesets = _rest_get_json(
                f"repos/{repo}/rulesets?per_page=100&page={page}",
                repo_root=repo_root,
                runner=runner,
                fail_on_indeterminate=True,
            )
        except RestIndeterminateError as exc:
            return MergeQueueGovernance(
                reason=prefix + f"enforcement_unreadable:source=rulesets:cause={exc.reason}"
            )
        if not isinstance(rulesets, list):
            return MergeQueueGovernance(reason=prefix + "enforcement_malformed:rulesets")
        for summary in rulesets:
            if (
                not isinstance(summary, dict)
                or summary.get("target") not in ("branch", "tag", "push")
                or summary.get("enforcement") not in ("active", "evaluate", "disabled")
            ):
                return MergeQueueGovernance(reason=prefix + "enforcement_malformed:summary")
            if summary["target"] != "branch" or summary["enforcement"] != "active":
                continue
            ruleset_id = summary.get("id")
            if type(ruleset_id) is not int or ruleset_id <= 0:
                return MergeQueueGovernance(reason=prefix + "enforcement_malformed:ruleset_id")
            try:
                detail = _rest_get_json(
                    f"repos/{repo}/rulesets/{ruleset_id}",
                    repo_root=repo_root,
                    runner=runner,
                    fail_on_indeterminate=True,
                )
            except RestIndeterminateError as exc:
                return MergeQueueGovernance(
                    reason=prefix
                    + f"enforcement_unreadable:ruleset={ruleset_id}:cause={exc.reason}"
                )
            if not isinstance(detail, dict) or any(
                detail.get(key) != summary.get(key) for key in ("id", "target", "enforcement")
            ):
                return MergeQueueGovernance(
                    reason=prefix + f"enforcement_conflict:ruleset={ruleset_id}"
                )
            rules = detail.get("rules")
            if not isinstance(rules, list) or any(
                not isinstance(rule, dict) or not isinstance(rule.get("type"), str)
                for rule in rules
            ):
                return MergeQueueGovernance(
                    reason=prefix + f"queue_rule_malformed:ruleset={ruleset_id}"
                )
            queue_rules = [rule for rule in rules if rule["type"] == "merge_queue"]
            if not queue_rules:
                continue
            applies = _ruleset_applies_to_pr(detail, pr)
            if applies is None:
                return MergeQueueGovernance(
                    reason=prefix + f"ref_enforcement_unknown:ruleset={ruleset_id}"
                )
            if not applies:
                continue
            for rule in queue_rules:
                parameters = rule.get("parameters")
                method = (
                    _normalize_merge_method(parameters.get("merge_method"))
                    if isinstance(parameters, dict)
                    else None
                )
                if method is None:
                    return MergeQueueGovernance(
                        reason=prefix + f"queue_strategy_invalid:ruleset={ruleset_id}"
                    )
                methods.add(method)
            sources.append(f"ruleset:{detail.get('name') or ruleset_id}:{ruleset_id}")
        if len(rulesets) < 100:
            break
        page += 1
    if len(methods) > 1:
        return MergeQueueGovernance(
            reason=prefix + "queue_strategy_conflict:" + ",".join(sorted(methods))
        )
    return MergeQueueGovernance(
        method=next(iter(methods), None),
        source=",".join(sources) if sources else f"rulesets:base={pr.base_ref}:non_queue",
    )


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
    file_entries = (
        [entry for entry in files_payload if isinstance(entry, dict) and entry.get("path")]
        if isinstance(files_payload, list)
        else None
    )
    deleted_files = (
        tuple(str(entry["path"]) for entry in file_entries if entry["changeType"] == "DELETED")
        if file_entries is not None
        and all(isinstance(entry.get("changeType"), str) for entry in file_entries)
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
        head_ref=read_ref_name(item.get("headRefName")),
        files=files,
        changed_files_count=changed_files_count,
        body=str(item.get("body") or ""),
        is_draft=bool(item.get("isDraft")),
        head_sha=_scalar(item.get("headRefOid")),
        merge_state_status=str(item.get("mergeStateStatus") or "").upper(),
        labels=_labels_from_payload(item),
        review_decision=_scalar(item.get("reviewDecision")),
        auto_merge_enabled=bool(item.get("autoMergeRequest")),
        auto_merge_method=_auto_merge_request_method(item.get("autoMergeRequest")),
        check_summary=summarize_checks(item.get("statusCheckRollup") or []),
        base_ref=read_ref_name(item.get("baseRefName")),
        default_branch=read_ref_name(item.get("baseRepoDefaultBranch")),
        default_branch_detail=read_ref_name(item.get("baseRepoDefaultBranchDetail")),
        base_ref_detail=read_ref_name(item.get("baseRefNameDetail")),
        base_ref_detail_latest=read_ref_name(item.get("baseRefNameDetailLatest")),
        reference_reasons=pr_reference_reasons(item),
        deleted_files=deleted_files,
    )


def _list_candidate_pages(
    *, transport: str, repo: str, repo_root: Path, runner: Any
) -> list[dict[str, Any]]:
    """List identities without per-PR hydration; require transport pagination evidence."""
    owner, name = repo.split("/", 1)
    query = (
        "query($owner:String!,$name:String!,$cursor:String){"
        "repository(owner:$owner,name:$name){defaultBranchRef{name}"
        "pullRequests(states:OPEN,first:100,after:$cursor,"
        "orderBy:{field:CREATED_AT,direction:ASC}){totalCount "
        "pageInfo{hasNextPage endCursor} nodes{number headRefOid headRefName "
        "baseRefName autoMergeRequest{mergeMethod}}}}}"
    )
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    cursors: set[str] = set()
    cursor = None
    page = 1
    total = None
    while True:
        if transport == "rest":
            cmd = [
                "gh",
                "api",
                "--method",
                "GET",
                "-H",
                "Accept: application/vnd.github+json",
                f"repos/{repo}/pulls",
                "--include",
                "-f",
                "state=open",
                "-f",
                "sort=created",
                "-f",
                "direction=asc",
                "-f",
                "per_page=100",
                "-f",
                f"page={page}",
            ]
        else:
            cmd = [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
            ]
            if cursor is not None:
                cmd.extend(["-f", f"cursor={cursor}"])
        try:
            proc = runner(
                cmd, cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=60
            )
            if proc.returncode:
                raise RestIndeterminateError(f"{transport}_listing_failed")
            body = proc.stdout
            if transport == "rest":
                parts = re.split(r"\r?\n\r?\n", body, maxsplit=1)
                if len(parts) != 2 or not re.match(r"HTTP/\S+ 200\b", parts[0]):
                    raise RestIndeterminateError("rest_pagination_headers_missing")
                headers, body = parts
                links = re.findall(r"^link:\s*(.+)$", headers, re.IGNORECASE | re.MULTILINE)
                relations = []
                for link in links:
                    pattern = r'<[^>]+>;\s*rel="(next|prev|first|last)"'
                    if re.sub(pattern, "", link).strip(", \r\t"):
                        raise RestIndeterminateError("rest_pagination_link_invalid")
                    relations.extend(re.findall(pattern, link))
                # GitHub's terminal-page signal is a complete HTTP response with no
                # rel="next" (including no Link header for a single-page estate).
                has_next = "next" in relations
                batch = json.loads(body)
            else:
                payload = json.loads(body)
                if payload.get("errors"):
                    raise RestIndeterminateError("graphql_listing_errors")
                repository = payload["data"]["repository"]
                connection = repository["pullRequests"]
                info = connection["pageInfo"]
                has_next = info["hasNextPage"]
                count = connection["totalCount"]
                if type(has_next) is not bool or type(count) is not int or count < 0:
                    raise RestIndeterminateError("graphql_pagination_invalid")
                if total is not None and count != total:
                    raise RestIndeterminateError("open_pr_count_changed_during_listing")
                total = count
                batch = connection["nodes"]
                if has_next:
                    cursor = info["endCursor"]
                    if not isinstance(cursor, str) or not cursor or cursor in cursors:
                        raise RestIndeterminateError("graphql_pagination_cursor_invalid")
                    cursors.add(cursor)
        except (
            OSError,
            subprocess.TimeoutExpired,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as exc:
            raise RestIndeterminateError(f"{transport}_listing_indeterminate") from exc
        if not isinstance(batch, list) or len(batch) > 100 or (has_next and not batch):
            raise RestIndeterminateError(f"{transport}_pagination_invalid")
        for item in batch:
            number = item.get("number") if isinstance(item, dict) else None
            if type(number) is not int or number <= 0 or number in seen:
                raise RestIndeterminateError("open_pr_identity_invalid_or_duplicate")
            seen.add(number)
            if transport == "graphql":
                default_ref = repository.get("defaultBranchRef") or {}
                item["baseRepoDefaultBranch"] = default_ref.get("name")
            rows.append(item)
        if not has_next:
            if total is not None and len(rows) != total:
                raise RestIndeterminateError("open_pr_listing_truncated")
            return rows
        page += 1


@contextmanager
def _rotation_state(
    *, repo: str, state_path: Path, persist: bool
) -> Iterator[tuple[dict[int, datetime], dict[int, dict[str, Any]]]]:
    """Read/modify/write under one lock; old examined-only state remains readable."""
    try:
        if persist:
            state_path.parent.mkdir(parents=True, exist_ok=True)
        with state_path.with_suffix(".lock").open("a") if persist else nullcontext() as lock:
            if lock is not None:
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                state = {"schema_version": 1, "repositories": {}}
            if state["schema_version"] != 1 or not isinstance(state["repositories"], dict):
                raise ValueError("invalid rotation state")
            examined = {
                int(number): datetime.fromisoformat(stamp)
                for number, stamp in state["repositories"].get(repo, {}).items()
            }
            failure_repos = state.setdefault("hydration_failures", {})
            failures = {
                int(number): failure for number, failure in failure_repos.get(repo, {}).items()
            }
            stamps = list(examined.values())
            for failure in failures.values():
                count = failure["consecutive_failures"]
                if type(count) is not int or count < 1 or not isinstance(failure["reason"], str):
                    raise ValueError("invalid hydration failure")
                stamps.append(datetime.fromisoformat(failure["last_failed_at"]))
            if any(stamp.tzinfo is None for stamp in stamps):
                raise ValueError("rotation timestamps must include a timezone")
            yield examined, failures
            if persist:
                state["repositories"][repo] = {
                    str(number): stamp.isoformat() for number, stamp in examined.items()
                }
                failure_repos[repo] = {str(number): failure for number, failure in failures.items()}
                temporary = state_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
                temporary.replace(state_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise RestIndeterminateError("rotation_state_unavailable_or_invalid") from exc


def _rotation_timestamp(
    examined: dict[int, datetime], failures: dict[int, dict[str, Any]]
) -> datetime:
    # Completion and retry order must progress even with equal/backward wall clocks.
    stamps = [*examined.values()]
    stamps.extend(
        datetime.fromisoformat(failure["last_failed_at"]) for failure in failures.values()
    )
    return max(
        datetime.now(UTC),
        max(stamps, default=datetime.min.replace(tzinfo=UTC)) + timedelta(microseconds=1),
    )


def _must_include_guarantee_disabled() -> bool:
    """Killswitch: ``HAPAX_AUTOQUEUE_MUST_INCLUDE_OFF=1`` restores pre-guarantee
    behavior — no must-include seats, no refresh path, no persisted state, no
    R3 refresh-only fallback. The rotation alone reconciles, exactly as before
    this guarantee existed (the manual stopgap watcher is the documented
    compensating control while the killswitch is engaged).
    """

    return os.environ.get("HAPAX_AUTOQUEUE_MUST_INCLUDE_OFF", "") == "1"


def _row_auto_merge_armed(row: dict[str, Any]) -> bool:
    """Whether a listing row (GraphQL or REST shape) carries an armed auto-merge request."""
    auto_merge = row.get("autoMergeRequest")
    if auto_merge is None:
        # REST listing rows spell it ``auto_merge``.
        auto_merge = row.get("auto_merge")
    return bool(auto_merge)


def _listing_head_sha(row: dict[str, Any]) -> str | None:
    """Head SHA from a listing row without hydration (GraphQL or REST shape)."""
    if "headRefOid" in row:
        sha = row.get("headRefOid")
        return sha if isinstance(sha, str) and sha else None
    head = row.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    return sha if isinstance(sha, str) and sha else None


def _listing_head_ref(row: dict[str, Any]) -> str | None:
    """Head branch from a listing row without hydration (GraphQL or REST shape)."""
    if "headRefName" in row:
        ref = row.get("headRefName")
    else:
        head = row.get("head")
        ref = head.get("ref") if isinstance(head, dict) else None
    return ref if isinstance(ref, str) and ref else None


def _evidence_file_newer_than(path: Path, since: datetime, *, now: datetime) -> bool:
    """Whether a receipt/dossier's mtime or recorded timestamp is after ``since``.

    Times later than ``now`` are discarded: a future-dated file would otherwise
    read as fresh after every examination until real time caught up. An
    unreadable or malformed file contributes its mtime only.
    """
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return False
    if since < mtime <= now:
        return True
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    if not isinstance(loaded, dict):
        return False
    for key in FRESH_EVIDENCE_TIMESTAMP_FIELDS:
        value = loaded.get(key)
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                continue
        if isinstance(value, datetime) and value.tzinfo is not None and since < value <= now:
            return True
    return False


def _release_stamp_newer_than(
    task: TaskNote, head_sha: str | None, since: datetime, *, now: datetime
) -> bool:
    """Whether the note authorizes release at this listing head, stamped after ``since``.

    A seat release stamp is a frontmatter edit, so the note's mtime dates it. It counts
    only when it authorizes release at the PR's current head, the one stamp an exam can
    act on; a note edit that names no head, or another head, is not evidence.
    """
    if head_sha is None or not assess_release_auto_arm(task.frontmatter).armed:
        return False
    if _release_authorized_head_stamp_blocker(task.frontmatter, expected_head_sha=head_sha):
        return False
    try:
        mtime = datetime.fromtimestamp(task.path.stat().st_mtime, UTC)
    except OSError:
        return False
    return since < mtime <= now


def _fresh_evidence_probe(
    tasks: list[TaskNote], *, now: datetime
) -> Callable[[dict[str, Any], datetime], bool]:
    """Answer "did a linked receipt, dossier or current-head release stamp land after
    ``since``?" for a listing row.

    Rows link to tasks the way ``_matching_tasks`` links hydrated PRs: by
    ``pr`` first, else by head branch. Each task folder is listed at most once.
    """
    by_pr: dict[int, list[TaskNote]] = {}
    by_branch: dict[str, list[TaskNote]] = {}
    for task in tasks:
        if task.pr is not None:
            by_pr.setdefault(task.pr, []).append(task)
        if task.branch:
            by_branch.setdefault(task.branch, []).append(task)
    listings: dict[Path, list[str]] = {}

    def evidence_paths(task: TaskNote) -> list[Path]:
        folder = task.path.parent
        if folder not in listings:
            try:
                listings[folder] = sorted(os.listdir(folder))
            except OSError:
                listings[folder] = []
        receipt_prefix = f"{task.task_id}.acceptance"
        dossier = review_team.review_dossier_path(task.path, task.task_id).name
        return [
            folder / name
            for name in listings[folder]
            if name == dossier or (name.startswith(receipt_prefix) and name.endswith(".yaml"))
        ]

    def probe(row: dict[str, Any], since: datetime) -> bool:
        matches = by_pr.get(row["number"]) or by_branch.get(_listing_head_ref(row) or "", [])
        head_sha = _listing_head_sha(row)
        return any(
            _release_stamp_newer_than(task, head_sha, since, now=now)
            or any(_evidence_file_newer_than(path, since, now=now) for path in evidence_paths(task))
            for task in matches
        )

    return probe


@dataclass(frozen=True)
class _WindowSelection:
    """One tick's window split by treatment.

    ``rotation_rows`` take the existing full hydration/classify path.
    ``must_refresh`` are (number, head_sha) identities served by the cheap
    refresh-only path (R5): one status read, at most one status POST, no
    hydration, no new admission decision. ``full_exam_rows`` are must-include
    rows that need a full pass this tick (dequeued follow-up, R6).
    ``overflow`` lists must-include numbers the cap could not serve (oldest
    proofs are served first). ``fresh_served`` are fresh-evidence rows given a
    one-shot full exam (they are part of ``full_exam_rows``);
    ``fresh_overflow`` are fresh-evidence rows left unserved this tick, which
    stay fresh and are carried to the next tick.
    """

    rotation_rows: list[dict[str, Any]]
    must_refresh: tuple[tuple[int, str | None], ...]
    full_exam_rows: list[dict[str, Any]]
    overflow: tuple[int, ...]
    must_identities: tuple[tuple[int, str | None], ...]
    armed_live: frozenset[int] = frozenset()
    fresh_served: tuple[int, ...] = ()
    fresh_overflow: tuple[int, ...] = ()


def _select_pr_window(
    rows: list[dict[str, Any]],
    *,
    repo: str,
    limit: int,
    state_path: Path,
    persist: bool,
    must_include: frozenset[int] | set[int] = frozenset(),
    full_exam: frozenset[int] | set[int] = frozenset(),
    fresh_evidence: Callable[[dict[str, Any], datetime], bool] | None = None,
) -> _WindowSelection:
    """Select without acknowledging work. Repeated failures share the fair rotation.

    Must-include PRs (merge-queued, auto-merge-armed, or dequeued follow-up) are
    guaranteed a window slot every tick (R2). When must-include PRs would
    otherwise squeeze the rotation, the window grows to at most
    ``MUST_INCLUDE_CAP`` extra seats beyond the requested limit, with
    ``MUST_INCLUDE_RESERVE`` rotation slots always preserved (R5). A large
    ``--limit`` legitimately serves more must-include rows than the cap — the
    cap bounds the guarantee's dominance over the rotation, not the window.
    The guarantee never silently dominates: overflow is reported, and the
    oldest proofs are served first.

    ``fresh_evidence(row, since)`` marks a previously examined PR whose linked
    receipt or dossier landed after its last examination attempt (a hydration
    failure counts as an attempt). Those rows take one-shot full-exam seats
    after every other must-include row, within the same cap and reserve; the
    exam's rotation ack retires them. Never-examined rows already head the
    rotation and take no seat.
    """
    if limit <= 0:
        raise ValueError("autoqueue limit must be positive")
    with _rotation_state(repo=repo, state_path=state_path, persist=persist) as (examined, failures):
        live = {row["number"] for row in rows}
        for records in (examined, failures):
            for number in set(records) - live:
                del records[number]

        def priority(row: dict[str, Any]) -> tuple[datetime, int]:
            number = row["number"]
            stamp = examined.get(number, datetime.min.replace(tzinfo=UTC))
            failure = failures.get(number)
            if failure and failure["consecutive_failures"] >= 2:
                stamp = max(stamp, datetime.fromisoformat(failure["last_failed_at"]))
            return stamp, number

        armed = {row["number"] for row in rows if _row_auto_merge_armed(row)}
        if _must_include_guarantee_disabled():
            armed = set()
        must = (set(must_include) | armed | set(full_exam)) & live
        core_rows = sorted((row for row in rows if row["number"] in must), key=priority)
        fresh: set[int] = set()
        if fresh_evidence is not None and not _must_include_guarantee_disabled():
            for row in rows:
                number = row["number"]
                if number in must or number not in examined:
                    continue
                last_attempt = examined[number]
                failure = failures.get(number)
                if failure:
                    last_attempt = max(
                        last_attempt, datetime.fromisoformat(failure["last_failed_at"])
                    )
                if fresh_evidence(row, last_attempt):
                    fresh.add(number)
        # Queued/armed/dequeued seats first: fresh evidence only fills what the
        # #4716 guarantee leaves of the cap.
        must_rows = [
            *core_rows,
            *sorted((row for row in rows if row["number"] in fresh), key=priority),
        ]
        # No must-include rows: keep the historical window size exactly.
        reserve_floor = (
            min(len(must_rows), MUST_INCLUDE_CAP) + MUST_INCLUDE_RESERVE if must_rows else 0
        )
        effective_limit = max(limit, reserve_floor)
        # Cap, not dominance: leave the rotation its reserve even mid-backlog.
        must_capacity = effective_limit - MUST_INCLUDE_RESERVE
        served = must_rows[: max(must_capacity, 0)]
        served_numbers = {row["number"] for row in served}
        unserved = [row["number"] for row in must_rows[max(must_capacity, 0) :]]
        overflow = tuple(number for number in unserved if number in must)
        # Armed rows are R2 refresh seats, not R6 follow-ups: a PR that is armed
        # but has never queued (or re-armed after a dequeue) stays on the cheap
        # refresh path; the R6 one-shot full exam belongs to rows that left the
        # queue unarmed.
        full_exam_live = ((set(full_exam) & live) - armed) | fresh
        full_exam_rows = [row for row in served if row["number"] in full_exam_live]
        must_refresh = tuple(
            (row["number"], _listing_head_sha(row))
            for row in served
            if row["number"] not in full_exam_live
        )
        rotation_rows = [
            row for row in sorted(rows, key=priority) if row["number"] not in served_numbers
        ][: max(effective_limit - len(served), 0)]
        rotation_numbers = {row["number"] for row in rotation_rows}
        # Fresh rows never enter the persisted must-include set: their seat is
        # re-derived each tick from evidence vs. the rotation stamp.
        must_identities = tuple((row["number"], _listing_head_sha(row)) for row in core_rows)
        return _WindowSelection(
            rotation_rows=rotation_rows,
            must_refresh=must_refresh,
            full_exam_rows=full_exam_rows,
            overflow=overflow,
            must_identities=must_identities,
            armed_live=frozenset(armed),
            fresh_served=tuple(row["number"] for row in served if row["number"] in fresh),
            fresh_overflow=tuple(
                number for number in unserved if number in fresh and number not in rotation_numbers
            ),
        )


def _record_hydration_failure(
    number: int, reason: str, *, repo: str, state_path: Path, persist: bool
) -> dict[str, Any]:
    with _rotation_state(repo=repo, state_path=state_path, persist=persist) as (examined, failures):
        failure = {
            "consecutive_failures": failures.get(number, {}).get("consecutive_failures", 0) + 1,
            "last_failed_at": _rotation_timestamp(examined, failures).isoformat(),
            "reason": reason,
        }
        failures[number] = failure
    return failure


@contextmanager
def _reconciled_pr(
    number: int, *, repo: str, state_path: Path | None, failures: dict[int, dict[str, Any]]
) -> Iterator[None]:
    """Acknowledge only a completed per-PR pass, including explicit holds/refusals.

    An exception or interrupted process leaves the old timestamp intact. This
    scope also covers early continues in the mutation loop.
    """
    yield
    if state_path is not None:
        with _rotation_state(repo=repo, state_path=state_path, persist=True) as (examined, pending):
            examined[number] = _rotation_timestamp(examined, pending)
            pending.pop(number, None)
        failures.pop(number, None)


def _hydrate_selected_pr(
    listed: dict[str, Any],
    route: ListingRoute,
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
) -> PullRequest:
    """Hydrate one selected identity without replacing its branch observations."""
    if route.transport == "rest":
        # Seed only listing evidence. If the detail read fails, no old head or
        # status can masquerade as a fresh hydration of this selected identity.
        row = _pull_status_row_from_rest(
            {
                "number": listed["number"],
                "base": {
                    "ref": listed.get("baseRefName"),
                    "repo": {"default_branch": listed.get("baseRepoDefaultBranch")},
                },
            },
            repo=repo,
            repo_root=repo_root,
            runner=runner,
            include_files=True,
            include_review_decision=True,
        )
    else:
        row = get_pr_status_graphql(
            listed["number"],
            repo=repo,
            repo_root=repo_root,
            runner=runner,
            expected_head_sha=listed.get("headRefOid"),
        )
        if row is None:
            raise RestIndeterminateError("selected_pr_hydration_failed")
        row["baseRefNameDetail"] = row.get("baseRefName")
        row["refEvidenceReasons"] = pr_reference_reasons(
            {**listed, "refEvidenceReasons": pr_reference_reasons(row)}
        )
        row["baseRefName"] = read_ref_name(listed.get("baseRefName")) or row.get("baseRefName")
        row["baseRepoDefaultBranch"] = listed.get("baseRepoDefaultBranch")
    if not row.get("headRefOid") or row["headRefOid"] != listed.get("headRefOid"):
        raise RestIndeterminateError("selected_pr_hydration_head_changed")
    hydrated, _ = _hydrate_open_prs([row], route, repo=repo, repo_root=repo_root, runner=runner)
    if len(hydrated) != 1 or hydrated[0].number != listed["number"]:
        raise RestIndeterminateError("selected_pr_hydration_identity_invalid")
    return hydrated[0]


def fetch_rotating_open_prs(
    *,
    repo: str,
    repo_root: Path,
    limit: int,
    state_path: Path,
    persist: bool,
    runner: Any,
    must_include: frozenset[int] | set[int] = frozenset(),
    full_exam: frozenset[int] | set[int] = frozenset(),
    fresh_evidence: Callable[[dict[str, Any], datetime], bool] | None = None,
) -> tuple[list[PullRequest], ListingRoute, int, dict[int, dict[str, Any]], _WindowSelection]:
    """Prove the complete estate, then hydrate at most limit identities independently.

    Must-include identities (R2) are selected every tick and split off for the
    caller's cheap refresh-only path; only rotation rows and dequeued follow-up
    rows pay for full hydration here.
    """
    snapshot = rate_snapshot(repo_root=repo_root, runner=runner)
    transport, reason = choose_transport(repo_root=repo_root, runner=runner, snapshot=snapshot)
    if transport is None:
        raise RestIndeterminateError("both_rate_pools_below_floor")
    rest_blocked = rest_pool_blocked(snapshot) is not None
    try:
        rows = _list_candidate_pages(
            transport=transport, repo=repo, repo_root=repo_root, runner=runner
        )
    except RestIndeterminateError:
        fallback = "rest" if transport == "graphql" else "graphql"
        if (fallback == "rest" and rest_blocked) or (
            fallback == "graphql" and graphql_pool_blocked(snapshot) is not None
        ):
            raise
        rows = _list_candidate_pages(
            transport=fallback, repo=repo, repo_root=repo_root, runner=runner
        )
        reason = f"{transport}_listing_indeterminate_{fallback}_fallback"
        transport = fallback
    selection = _select_pr_window(
        rows,
        repo=repo,
        limit=limit,
        state_path=state_path,
        persist=persist,
        must_include=must_include,
        full_exam=full_exam,
        fresh_evidence=fresh_evidence,
    )
    if selection.overflow:
        LOG.warning(
            "must-include overflow: %d queued/armed PRs beyond the per-tick cap (%d); "
            "oldest proofs served first, unserved: %s",
            len(selection.overflow),
            MUST_INCLUDE_CAP,
            list(selection.overflow),
        )
    if selection.fresh_overflow:
        LOG.warning(
            "fresh-evidence overflow: %d PRs with a receipt/dossier newer than their last "
            "exam did not fit the must-include cap (%d); carried to the next tick: %s",
            len(selection.fresh_overflow),
            MUST_INCLUDE_CAP,
            list(selection.fresh_overflow),
        )
    with _rotation_state(repo=repo, state_path=state_path, persist=False) as (_, failures):
        failures = {
            number: {**failure, "attempted_this_tick": False}
            for number, failure in failures.items()
        }
    route = ListingRoute(transport=transport, rest_blocked=rest_blocked, reason=reason)
    prs = []
    # Dequeued follow-up (R6) needs a real decision this tick, not a refresh:
    # hydrate those rows first so a crash mid-loop cannot drop the one-shot.
    for item in [*selection.full_exam_rows, *selection.rotation_rows]:
        try:
            listed = item
            if transport == "rest":
                base = item.get("base") or {}
                listed = {
                    "number": item["number"],
                    "headRefOid": (item.get("head") or {}).get("sha"),
                    "headRefName": (item.get("head") or {}).get("ref"),
                    "baseRefName": base.get("ref"),
                    "baseRepoDefaultBranch": (base.get("repo") or {}).get("default_branch"),
                }
            try:
                hydrated = _hydrate_selected_pr(
                    listed, route, repo=repo, repo_root=repo_root, runner=runner
                )
            except (
                OSError,
                subprocess.SubprocessError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
            ):
                fallback = "rest" if transport == "graphql" else "graphql"
                if (fallback == "rest" and rest_blocked) or (
                    fallback == "graphql" and graphql_pool_blocked(snapshot) is not None
                ):
                    raise
                LOG.warning(
                    "PR #%s %s hydration failed; trying eligible %s",
                    item["number"],
                    transport,
                    fallback,
                )
                hydrated = _hydrate_selected_pr(
                    listed,
                    ListingRoute(
                        transport=fallback,
                        rest_blocked=rest_blocked,
                        reason=f"{transport}_hydration_failed_{fallback}_fallback",
                    ),
                    repo=repo,
                    repo_root=repo_root,
                    runner=runner,
                )
        except (
            OSError,
            subprocess.SubprocessError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exc:
            failure_reason = (
                exc.reason if isinstance(exc, RestIndeterminateError) else type(exc).__name__
            )
            failure = _record_hydration_failure(
                item["number"], failure_reason, repo=repo, state_path=state_path, persist=persist
            )
            failures[item["number"]] = {**failure, "attempted_this_tick": True}
            LOG.warning(
                "PR #%s hydration failed (%s), consecutive failures=%s; retry remains scheduled",
                item["number"],
                failure_reason,
                failure["consecutive_failures"],
            )
            continue
        prs.append(hydrated)
    return prs, route, len(rows), failures, selection


def fetch_open_prs(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    limit: int = 100,
    runner: Any = None,
    must_include: frozenset[int] | set[int] = frozenset(),
) -> tuple[list[PullRequest], ListingRoute | None]:
    """Open PRs plus the cycle's transport decision.

    The decision is returned rather than left for the caller to infer from row stamps: an
    empty GraphQL-routed listing has no rows to inspect, so inference silently read "rest".
    ``None`` means the listing was unavailable and the cycle is skipping.
    Strict REST failures retain their RestIndeterminateError cause for the report.

    ``must_include`` numbers missing from the limit-sliced listing (estate larger
    than the limit) are fetched per-PR, bounded by ``MUST_INCLUDE_CAP``, so the
    one-shot path cannot silently drop merge-queued PRs (T01 #12).
    """
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    try:
        raw, route = list_open_pr_statuses(
            repo=repo,
            repo_root=repo_root,
            runner=runner,
            limit=limit,
            include_files=True,
            include_review_decision=True,
        )
    except PrListingUnavailable as exc:
        # The router has already tried any eligible fallback. Preserve the strict REST
        # cause for the reconciler's classified refusal, without changing its pure token.
        if isinstance(exc.__cause__, RestIndeterminateError):
            raise RestIndeterminateError(exc.__cause__.reason) from exc
        # Skip this cycle rather than spending a listing plus per-PR hydration into
        # guaranteed 403s. Distinguished from the empty-scan warning below because the
        # two mean different things: this one is "we did not look", not "nothing found".
        LOG.warning(
            "open PR scan skipped: %s%s",
            exc.reason,
            listing_unavailable_detail(exc),
        )
        return [], None
    listed_numbers = {item.get("number") for item in raw if isinstance(item, dict)}
    missing = sorted(set(must_include) - {number for number in listed_numbers if number})
    for number in missing[:MUST_INCLUDE_CAP]:
        row = get_pr_status_graphql(number, repo=repo, repo_root=repo_root, runner=runner)
        if row is None:
            row = get_pull_rest(number, repo=repo, repo_root=repo_root, runner=runner)
        if isinstance(row, dict):
            raw.append(row)
    if len(missing) > MUST_INCLUDE_CAP:
        LOG.warning(
            "one-shot listing: %d must-include PRs beyond the limit, %d fetched, unserved: %s",
            len(missing),
            MUST_INCLUDE_CAP,
            missing[MUST_INCLUDE_CAP:],
        )
    return _hydrate_open_prs(raw, route, repo=repo, repo_root=repo_root, runner=runner)


def _hydrate_open_prs(
    raw: list[dict[str, Any]], route: ListingRoute, *, repo: str, repo_root: Path, runner: Any
) -> tuple[list[PullRequest], ListingRoute]:
    if not raw:
        # A successful listing with zero rows is a genuinely quiet estate, NOT an unavailable
        # one. Returning `None` here made the caller skip the cycle on a correct measurement —
        # the mirror of the defect this route object exists to fix, introduced by fixing it.
        LOG.info("open PR scan returned no rows (estate is quiet, listing succeeded)")
        return [], route
    prs: list[PullRequest] = []
    for item in raw:
        if isinstance(item, dict):
            rest_pr = None
            # Rows fetched over GraphQL already carry mergeStateStatus and a per-PR rollup, so
            # re-hydrating them through REST would spend the pool the routing exists to spare —
            # one call moved and nothing saved, which is what the review found. Only REST rows
            # need this pass.
            if item.get("transport") != "graphql":
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
            # Fill missing base evidence, but never erase a disagreement already
            # observed by the adapter, even if this read returns to the list base.
            base = rest_pr.get("base") if isinstance(rest_pr, dict) else None
            base = base if isinstance(base, dict) else {}
            base_repo = base.get("repo")
            detail_default = (
                base_repo.get("default_branch") if isinstance(base_repo, dict) else None
            )
            item["refEvidenceReasons"] = pr_reference_reasons(
                {
                    "refEvidenceReasons": pr_reference_reasons(item),
                    "baseRefNameDetailLatest": base.get("ref"),
                    "baseRepoDefaultBranchDetail": detail_default,
                }
            )
            detail_ref = read_ref_name(base.get("ref"))
            item["baseRefName"] = read_ref_name(item.get("baseRefName")) or detail_ref
            if detail_ref and detail_ref != item["baseRefName"]:
                if not read_ref_name(item.get("baseRefNameDetail")):
                    item["baseRefNameDetail"] = detail_ref
                elif detail_ref != item["baseRefNameDetail"]:
                    item["baseRefNameDetailLatest"] = detail_ref
            if (
                read_ref_name(item.get("baseRefNameDetail"))
                and item["baseRefNameDetail"] != item["baseRefName"]
            ):
                item["baseRefConflict"] = "pr_base_ref_conflict"
            detail_default = read_ref_name(detail_default)
            item["baseRepoDefaultBranch"] = (
                read_ref_name(item.get("baseRepoDefaultBranch")) or detail_default
            )
            if (
                detail_default
                and detail_default != item["baseRepoDefaultBranch"]
                and not read_ref_name(item.get("baseRepoDefaultBranchDetail"))
            ):
                item["baseRepoDefaultBranchDetail"] = detail_default
            # Preserve the shared REST snapshot when available. If it is absent, derive the
            # rollup through REST/core check-runs and commit statuses, not another GraphQL PR
            # view. Fail-closed: an unfetchable rollup reads as "checks unknown / not green".
            fallback_rollup = item.get("statusCheckRollup")
            if (
                isinstance(fallback_rollup, list)
                and fallback_rollup
                and not _rollup_is_rest_indeterminate(fallback_rollup)
            ):
                item["statusCheckRollup"] = fallback_rollup
            elif item.get("transport") == "graphql":
                # A GraphQL row already made its own per-PR rollup call. An empty result here
                # means no checks or an unfetchable rollup, and `[]` is the fail-closed value
                # either way — it reads downstream as "checks unknown / not green". Reaching
                # for REST would spend the exhausted pool to reach the same verdict.
                item["statusCheckRollup"] = (
                    fallback_rollup if isinstance(fallback_rollup, list) else []
                )
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
    return prs, route


def _fetch_status_check_rollup(
    number: object,
    *,
    head_sha: object | None = None,
    repo: str,
    repo_root: Path,
    runner: Any,
    use_cache: bool | None = None,
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
        use_cache=use_cache,
    )

    if not rollup or _rollup_is_rest_indeterminate(rollup):
        try:
            pr_number = int(number)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pr_number = None
        if pr_number is not None:
            ok, gql_sha, gql_rollup = _fetch_status_check_rollup_graphql(
                pr_number,
                repo=repo,
                repo_root=repo_root,
                runner=runner,
            )
            if ok and gql_rollup and (not sha or gql_sha == sha):
                return gql_rollup
    if not rollup:
        LOG.warning(
            "REST status rollup fetch returned no checks for #%s sha=%s",
            number,
            sha,
        )
    return rollup


def _rollup_is_rest_indeterminate(rollup: list[Any]) -> bool:
    return bool(rollup) and all(
        isinstance(item, dict) and _check_name(item) == REST_INDETERMINATE_CHECK_NAME
        for item in rollup
    )


def _fetch_status_check_rollup_graphql(
    pr_number: int,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
) -> tuple[bool, str, list[Any]]:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    owner, name = repo.split("/", 1)
    query = (
        "query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){"
        "pullRequest(number:$number){headRefOid commits(last:1){nodes{commit{oid "
        "statusCheckRollup{contexts(first:100){totalCount nodes{__typename ... on CheckRun{name status "
        "conclusion completedAt startedAt} ... on StatusContext{context state createdAt}}}}}}}}}}"
    )
    try:
        proc = run_graphql_rate_aware(
            [
                "-f",
                f"query={query}",
                "-f",
                f"owner={owner}",
                "-f",
                f"repo={name}",
                "-F",
                f"number={pr_number}",
            ],
            repo_root=repo_root,
            runner=runner,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        reason = (
            f"pr_release_evidence_transport_unavailable:{type(exc).__name__}. "
            f"Next action: retry `gh pr view {pr_number} --repo {repo} "
            "--json headRefOid,statusCheckRollup`; if it still fails, check `gh auth status` "
            "and `uv run python scripts/github_pr_status.py rate` before retrying the cycle."
        )
        LOG.warning("%s", reason)
        return False, reason, []
    if proc.returncode != 0:
        return False, "invalid_pr_release_evidence_payload", []
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return False, "invalid_pr_release_evidence_payload", []
    pull = (
        payload.get("data", {}).get("repository", {}).get("pullRequest")
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(pull, dict):
        return False, "invalid_pr_release_evidence_payload", []
    sha = _scalar(pull.get("headRefOid"))
    if not sha:
        return False, "missing_head_sha", []
    commit_nodes = (
        pull.get("commits", {}).get("nodes", []) if isinstance(pull.get("commits"), dict) else []
    )
    commit = None
    if commit_nodes and isinstance(commit_nodes[-1], dict):
        commit = commit_nodes[-1].get("commit")
    status_rollup = commit.get("statusCheckRollup") if isinstance(commit, dict) else None
    contexts = status_rollup.get("contexts") if isinstance(status_rollup, dict) else None
    rollup = contexts.get("nodes") if isinstance(contexts, dict) else None
    total = contexts.get("totalCount") if isinstance(contexts, dict) else None
    # A later failed run may sit outside this page. Partial checks cannot verify release
    # mitigations; the caller can retry via REST only when that pool is eligible.
    if not isinstance(rollup, list) or type(total) is not int or len(rollup) != total:
        return False, "invalid_status_check_rollup", []
    return True, sha, rollup


def fetch_pr_release_evidence(
    pr_number: int,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
    route: ListingRoute | None = None,
) -> tuple[bool, str, set[str]]:
    """Release evidence for one PR, on the transport the cycle chose.

    An apply cycle reaches this per actionable PR, so beginning unconditionally on REST meant
    a cycle routed AWAY from REST still spent it N times before falling back. The GraphQL path
    already existed here as a post-failure fallback; when the cycle measured REST below its
    floor it becomes the primary instead.
    """
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    if route is not None and route.transport == "graphql":
        primary = _fetch_pr_release_evidence_graphql(
            pr_number, repo=repo, repo_root=repo_root, runner=runner
        )
        if primary[0] or route.rest_blocked:
            # A measured-empty REST pool is not an eligible fallback, so a GraphQL failure is
            # the answer rather than a reason to spend REST anyway.
            return primary
    payload = get_pull_rest(pr_number, repo=repo, repo_root=repo_root, runner=runner)
    if not isinstance(payload, dict):
        fallback = _fetch_pr_release_evidence_graphql(
            pr_number,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
        )
        if fallback[0] or fallback[1].startswith("pr_release_evidence_transport_unavailable:"):
            return fallback
        return False, "invalid_pr_release_evidence_payload", set()
    head = payload.get("head") if isinstance(payload.get("head"), dict) else {}
    sha = _scalar(head.get("sha"))
    if not sha:
        fallback = _fetch_pr_release_evidence_graphql(
            pr_number,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
        )
        if fallback[0] or fallback[1].startswith("pr_release_evidence_transport_unavailable:"):
            return fallback
        return False, "missing_head_sha", set()
    rollup = _fetch_status_check_rollup(
        pr_number,
        head_sha=sha,
        repo=repo,
        repo_root=repo_root,
        runner=runner,
        use_cache=False,
    )
    if not isinstance(rollup, list):
        return False, "invalid_status_check_rollup", set()
    if _rollup_is_rest_indeterminate(rollup):
        return False, "invalid_status_check_rollup", set()
    return True, sha, set(summarize_checks(rollup).verified_passed)


def _fetch_pr_release_evidence_graphql(
    pr_number: int,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
) -> tuple[bool, str, set[str]]:
    ok, sha, rollup = _fetch_status_check_rollup_graphql(
        pr_number,
        repo=repo,
        repo_root=repo_root,
        runner=runner,
    )
    if not ok:
        return False, sha, set()
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

    def indeterminate(cause: str) -> None:
        LOG.error("gh merge queue query indeterminate: %s", cause)
        return None

    if not isinstance(payload, dict):
        return indeterminate("invalid_payload")
    if "errors" in payload:
        if not isinstance(payload["errors"], list):
            return indeterminate("invalid_errors")
        if payload["errors"]:
            return indeterminate("graphql_errors")
    if "data" not in payload:
        return indeterminate("missing_data")
    data = payload["data"]
    if not isinstance(data, dict):
        return indeterminate("invalid_data")
    if "repository" not in data:
        return indeterminate("missing_repository")
    repository = data["repository"]
    if repository is None:
        return indeterminate("repository_unresolved")
    if not isinstance(repository, dict):
        return indeterminate("invalid_repository")
    if "mergeQueue" not in repository:
        return indeterminate("missing_merge_queue")
    merge_queue = repository["mergeQueue"]
    if merge_queue is None:
        LOG.info(
            "gh merge queue query decided: %s",
            "no_configured_merge_queue:ref_fallback=gh-readonly-queue",
        )
        nodes = []
    else:
        if not isinstance(merge_queue, dict):
            return indeterminate("invalid_merge_queue")
        entries = merge_queue.get("entries")
        if not isinstance(entries, dict):
            return indeterminate("invalid_entries")
        if "nodes" not in entries:
            return indeterminate("invalid_nodes")
        nodes = entries["nodes"]
        if nodes is None:
            return indeterminate("nodes_unresolved")
        if not isinstance(nodes, list):
            return indeterminate("invalid_nodes")
    queued: set[int] = set()
    for node in nodes:
        # Nullable entries/PRs are schema-licensed but cannot establish membership.
        if node is None:
            return indeterminate("entry_unresolved:null_node")
        if not isinstance(node, dict):
            return indeterminate("invalid_entry:node_type")
        # The query selects this key unconditionally; omission is not nullability.
        if "pullRequest" not in node:
            return indeterminate("invalid_entry:missing_pull_request")
        pull_request = node["pullRequest"]
        if pull_request is None:
            return indeterminate("entry_unresolved:null_pull_request")
        if not isinstance(pull_request, dict):
            return indeterminate("invalid_entry:pull_request_type")
        if "number" not in pull_request:
            return indeterminate("invalid_entry:missing_number")
        number = pull_request["number"]
        if isinstance(number, bool) or not isinstance(number, int):
            return indeterminate("invalid_entry:number_type")
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
    return [task for task in tasks if pr.head_ref and task.branch == pr.head_ref]


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
    floor_release: dict[str, Any] = {}
    blockers = review_team.review_dossier_validity_blockers(
        frontmatter,
        task.path,
        pr_head_sha=pr_head_sha,
        pr_number=pr_number,
        changed_files=changed_files or (),
        changed_file_count=changed_file_count,
        floor_release_out=floor_release,
    )
    if floor_release:
        # The seat's T2 rule admits a merge below the family floor; it is not the
        # quorum-accept that sensitive classes need to auto-arm, so the seat still releases them.
        return (*blockers, f"review_team_quorum_by_seat_rule:{floor_release['rule']}")
    return blockers


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


def _override_only_refusal(reasons: list[str]) -> bool:
    """Only a contradictory override alone is exempt from revocation."""
    return bool(reasons) and all(
        reason.startswith(OVERRIDE_CONTRADICTION_PREFIX) for reason in reasons
    )


def _transient_transport_refusal_only(reasons: list[str]) -> bool:
    """Every blocker is an unverified merge-method caused solely by a transient transport
    window (rate-limit / 429 / 5xx) on the rulesets fetch. Such a window says nothing about
    the PR, so a queued entry is held in place rather than dequeued."""
    return bool(reasons) and all(
        reason.startswith(TRANSIENT_TRANSPORT_UNVERIFIED_PREFIX) for reason in reasons
    )


def _is_missing_cc_task_link_reason(reason: str) -> bool:
    return reason == "missing_cc_task_link" or reason.startswith("missing_cc_task_link (NOTE:")


def _missing_cc_task_link_only(reasons: list[str]) -> bool:
    """Every blocker is a missing vault cc-task note (exact, or the unparseable-notes
    variant). That is a process gap, not a product defect: posting `failure` on
    hapax/autoqueue-admission would fail the required check and make GitHub drop a
    queued CI-green PR (overnight 2026-09-17)."""
    return bool(reasons) and all(_is_missing_cc_task_link_reason(reason) for reason in reasons)


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
    expected_auto_merge_method: str | None = None,
    expected_auto_merge_method_source: str | None = None,
    expected_auto_merge_method_is_override: bool = False,
    require_expected_auto_merge_method: bool = False,
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
    failed_release_checks = [
        check
        for check in pr.check_summary.failed
        if not required_checks or check in required_checks
    ]
    if failed_release_checks:
        reasons.append("failed_checks:" + ",".join(failed_release_checks))

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

    expected_method = _normalize_merge_method(expected_auto_merge_method)
    expected_method_unverified = expected_method is None
    expected_method_unverified_reason = None
    if expected_method_unverified and require_expected_auto_merge_method:
        expected_method_unverified_reason = _expected_merge_method_unverified_reason(
            expected_auto_merge_method_source
        )
        if queued or pr.auto_merge_enabled or not reasons:
            reasons.append(expected_method_unverified_reason)

    governance = pr.queue_governance
    if governance is not None:
        if queued and governance.reason is None and governance.method is None:
            # Membership and applicable-rule receipts contradict each other;
            # neither receipt establishes ownership of the per-PR method.
            governance = replace(
                governance,
                reason="auto_merge_method_unverified:queue_membership_evidence_contradiction:"
                "owner=merge_queue:membership=present:governance=non_queue",
            )
            pr = replace(pr, queue_governance=governance)
        if governance.reason:
            if expected_auto_merge_method_is_override:
                reasons.append(f"{governance.reason}:override={expected_method}")
            else:
                reasons.append(governance.reason)
        elif governance.method is not None and governance.method != expected_method:
            if expected_auto_merge_method_is_override:
                reasons.append(
                    OVERRIDE_CONTRADICTION_PREFIX
                    + f"override={expected_method}:governed={governance.method}"
                )
            else:
                reasons.append(
                    "auto_merge_method_unverified:queue_strategy_expected_conflict:"
                    f"rule={governance.method}:expected={expected_method}"
                )

    # GitHub ignores autoMergeRequest.mergeMethod under enforced queue handling;
    # only a validated applicable rule establishes queue ownership of that field.
    if (
        pr.auto_merge_enabled
        and expected_method is not None
        and (governance is None or (governance.reason is None and governance.method is None))
    ):
        method_mismatch = _merge_method_mismatch_reason(
            pr,
            expected_auto_merge_method=expected_method,
        )
        if method_mismatch:
            reasons.append(method_mismatch)

    if reasons:
        if _override_only_refusal(reasons):
            action = "hold" if queued or pr.auto_merge_enabled else "blocked"
        elif _transient_transport_refusal_only(reasons):
            # Transport window says nothing about the PR: hold a queued entry (never
            # dequeue), otherwise stay blocked and re-evaluate next pass once it clears.
            action = "hold" if queued else "blocked"
        elif _missing_cc_task_link_only(reasons):
            # Missing vault note is not a product defect. Hold a queued entry so GitHub
            # and this reconciler never drop it; otherwise stay blocked until a note exists.
            action = "hold" if queued else "blocked"
        elif queued:
            action = "dequeue"
        elif pr.auto_merge_enabled and not expected_method_unverified:
            action = "disable_auto_merge"
        else:
            action = "blocked"
        return Decision(
            pr=pr,
            task=task,
            tasks=matched_tasks,
            action=action,
            reasons=tuple(reasons),
            expected_auto_merge_method=expected_auto_merge_method,
        )
    if queued:
        return Decision(
            pr=pr,
            task=task,
            tasks=matched_tasks,
            action="already_queued",
            reasons=tuple(reasons),
            auto_arm=auto_arm,
            auto_arm_verified_checks=auto_arm_verified_checks,
            expected_auto_merge_method=expected_auto_merge_method,
        )
    if pr.auto_merge_enabled:
        return Decision(
            pr=pr,
            task=task,
            tasks=matched_tasks,
            action="already_auto_merge_enabled",
            auto_arm=auto_arm,
            auto_arm_verified_checks=auto_arm_verified_checks,
            expected_auto_merge_method=expected_auto_merge_method,
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
                expected_auto_merge_method=expected_auto_merge_method,
            )
        return Decision(
            pr=pr,
            task=task,
            tasks=matched_tasks,
            action="blocked",
            reasons=("pending_checks:" + ",".join(pr.check_summary.pending),),
            expected_auto_merge_method=expected_auto_merge_method,
        )
    return Decision(
        pr=pr,
        task=task,
        tasks=matched_tasks,
        action="queue",
        auto_arm=auto_arm,
        auto_arm_verified_checks=auto_arm_verified_checks,
        expected_auto_merge_method=expected_auto_merge_method,
    )


def merge_pr(
    decision: Decision,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
    require_route_metadata: bool = True,
    route: ListingRoute | None = None,
) -> tuple[bool, str]:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    graphql_args: list[str] | None = None
    if decision.action == "dequeue":
        queued_prs = fetch_merge_queue_pr_numbers(repo=repo, repo_root=repo_root, runner=runner)
        if queued_prs is None:
            return False, "merge_queue_state_indeterminate:dequeue_revalidation_failed"
        if decision.pr.number not in queued_prs:
            return False, "pull_request_not_in_merge_queue:dequeue_revalidation_failed"
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
        expected_method = _normalize_merge_method(decision.expected_auto_merge_method)
        merge_flag = GITHUB_MERGE_METHOD_FLAGS.get(expected_method or "")
        if merge_flag is None:
            return (
                False,
                "unsupported_auto_merge_method:"
                f"{decision.expected_auto_merge_method}:next_action="
                f"{_merge_method_operator_next_action()}",
            )
        cmd.extend(["--auto", merge_flag])
        if _decision_requires_head_guard(decision):
            boundary_blocker = _release_head_boundary_blocker(
                decision,
                require_route_metadata=require_route_metadata,
                repo=repo,
                repo_root=repo_root,
                runner=runner,
                # The second call site. Threading only the first left the auto-arm
                # revalidation re-entering REST on a cycle routed away from it.
                route=route,
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
    changed_files: tuple[str, ...] | None = None,
    deleted_files: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    if "release_authorized" not in frontmatter:
        return ()
    probe = dict(frontmatter)
    probe["release_authorized"] = False
    assessment = assess_release_auto_arm_estate(
        probe,
        verified_checks=verified_checks,
        changed_files=changed_files,
        deleted_files=deleted_files,
    )
    blockers = assessment.blockers
    if assess_release_auto_arm(frontmatter, verified_checks=verified_checks).armed:
        # These are auto-arm vetoes, not post-authorization vetoes. Once a task
        # is explicitly head-locked with release_authorized: true, release-head
        # revalidation should still replay current check/risk evidence, but it
        # must not strand the accepted manual release solely because the
        # authorized task is a public/current release or touches protected paths.
        blockers = tuple(
            blocker
            for blocker in blockers
            if not (
                blocker.startswith("sensitive_path:")
                or blocker == "mutation_surface:public"
                or blocker == "public_current"
            )
        )
    return blockers


def _release_auto_arm_authorized_waivers(
    frontmatter: dict[str, Any],
    *,
    verified_checks: set[str],
) -> tuple[str, ...]:
    if not assess_release_auto_arm(frontmatter, verified_checks=verified_checks).armed:
        return ()
    probe = dict(frontmatter)
    probe["release_authorized"] = False
    assessment = assess_release_auto_arm(probe, verified_checks=verified_checks)
    waivers: list[str] = []
    for blocker in assessment.blockers:
        if blocker.startswith("sensitive_path:"):
            waivers.append(
                "sensitive_path_waived_by_release_authorization:"
                f"{blocker.removeprefix('sensitive_path:')}"
            )
        elif blocker == "mutation_surface:public":
            waivers.append(
                "mutation_surface_waived_by_release_authorization:"
                f"{blocker.removeprefix('mutation_surface:')}"
            )
        elif blocker == "public_current":
            waivers.append("public_current_waived_by_release_authorization")
    return tuple(waivers)


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
    deleted_files: tuple[str, ...] | None = None,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
    release_authorization_waivers: list[str] | None = None,
    route: ListingRoute | None = None,
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
        route=route,
    )
    if not evidence_ok:
        if current_head_sha.startswith(
            "pr_release_evidence_transport_unavailable:"
        ) or current_head_sha in {
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
        changed_files=decision.pr.files if changed_files is None else changed_files,
        deleted_files=(
            deleted_files
            if changed_files is not None or deleted_files is not None
            else decision.pr.deleted_files
        ),
    )
    if evidence_blockers:
        return "current_release_auto_arm_blocked:" + ",".join(evidence_blockers)
    if release_authorization_waivers is not None:
        release_authorization_waivers.extend(
            _release_auto_arm_authorized_waivers(
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
    route: ListingRoute | None = None,
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
            # The THIRD call site. `_release_head_boundary_blocker` and `merge_pr` were threaded
            # two commits ago and this one was not, so auto-arm still revalidated a head over
            # REST on a cycle routed away from it. Enumerating the callers would have found all
            # three at once; fixing the two the review named found two.
            route=route,
        )
        if not evidence_ok:
            if current_head_sha.startswith(
                "pr_release_evidence_transport_unavailable:"
            ) or current_head_sha in {
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

    if _transient_transport_refusal_only(list(decision.reasons or ())):
        # A transient transport window (rate-limit / 429 / 5xx) on the rulesets fetch says
        # nothing about the PR. Writing a `failure` status would fail the required
        # hapax/autoqueue-admission check and make GitHub drop the queue entry (the #4672
        # loss, 2026-09-16). Defer the write; the next pass re-evaluates once it clears.
        return None

    if _missing_cc_task_link_only(list(decision.reasons or ())):
        # A missing vault cc-task note is a process gap, not a product defect. Writing
        # `failure` would fail the required hapax/autoqueue-admission check and make
        # GitHub drop an already-queued CI-green PR (overnight 2026-09-17: #4680-#4686,
        # #4673, #4665). `pending` does not fail that check: a queued entry stays queued,
        # and a not-yet-queued PR stays unqueued until a note exists (honest: not admitted).
        reasons = "; ".join(decision.reasons)
        return "pending", _status_description(
            f"cc-pr-autoqueue waiting for vault task note: {reasons}"
        )

    if decision.action in {"blocked", "hold", "dequeue", "disable_auto_merge"}:
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


@dataclass(frozen=True)
class AdmissionStatusReadFailed:
    reason: str


def _latest_admission_status(
    head_sha: str,
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
) -> tuple[str, str, datetime | None] | None | AdmissionStatusReadFailed:
    """The most recent autoqueue-admission (state, description, created_at) on
    ``head_sha``, None when absent, or AdmissionStatusReadFailed when unreadable.
    Read-before-write lets the
    reconciler POST a fresh status only when it actually changed or is about to
    go stale: GitHub caps statuses at 1000 per SHA+context, and the old
    unconditional POST burned that cap into a 422 self-DoS that made the apply
    loop skip the queue mutation."""
    cmd = ["gh", "api", f"repos/{repo}/commits/{head_sha}/statuses"]
    try:
        proc = runner(
            cmd, cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=60
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return AdmissionStatusReadFailed(f"query_unavailable:{type(exc).__name__}")
    if getattr(proc, "returncode", 1) != 0:
        return AdmissionStatusReadFailed(f"query_failed:rc={proc.returncode}")
    try:
        items = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        return AdmissionStatusReadFailed("invalid_json")
    if not isinstance(items, list):
        return AdmissionStatusReadFailed("expected_status_list")
    for item in items:  # the statuses API returns most-recent-first
        if not isinstance(item, dict) or not isinstance(item.get("context"), str):
            return AdmissionStatusReadFailed("malformed_status_row")
        if item.get("context") == AUTOQUEUE_ADMISSION_CONTEXT:
            if not isinstance(item.get("state"), str) or item["state"] not in {
                "pending",
                "success",
                "failure",
                "error",
            }:
                return AdmissionStatusReadFailed("malformed_status_state")
            return (
                str(item.get("state") or ""),
                str(item.get("description") or ""),
                _parse_status_created_at(item.get("created_at")),
            )
    return None


def _latest_admission_status_graphql(
    head_sha: str,
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
) -> tuple[str | None, tuple[str, str, datetime | None] | None]:
    """GraphQL twin of ``_latest_admission_status`` for a cycle routed off REST.

    Returns ``(repository_node_id, current_status)``. The node id proves the read reached the
    repository; commit statuses have no GraphQL mutation (GitHub's schema defines none), so the
    write itself stays on REST and is deferred while that pool is below its floor. ``(None,
    None)`` means the pool refused or the payload was not the shape asked for — the caller then
    either uses independently eligible REST or fails closed when REST is measured blocked.
    """
    owner, name = repo.split("/", 1)
    query = (
        "query($owner:String!,$repo:String!,$sha:GitObjectID!,$ctx:String!){"
        "repository(owner:$owner,name:$repo){id object(oid:$sha){... on Commit{"
        "status{context(name:$ctx){state description createdAt}}}}}}"
    )
    try:
        proc = run_graphql_rate_aware(
            [
                "-f",
                f"query={query}",
                "-f",
                f"owner={owner}",
                "-f",
                f"repo={name}",
                "-f",
                f"sha={head_sha}",
                "-f",
                f"ctx={AUTOQUEUE_ADMISSION_CONTEXT}",
            ],
            repo_root=repo_root,
            runner=runner,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        LOG.warning(
            "GraphQL admission status read unavailable for %s: %s", head_sha, type(exc).__name__
        )
        return None, None
    if proc.returncode != 0:
        return None, None
    try:
        payload = json.loads(proc.stdout or "{}")
    except (json.JSONDecodeError, TypeError):
        return None, None
    if not isinstance(payload, dict) or payload.get("errors"):
        return None, None
    data = payload.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repository, dict):
        return None, None
    repository_id = _scalar(repository.get("id"))
    if not repository_id:
        return None, None
    commit = repository.get("object")
    if not isinstance(commit, dict) or "status" not in commit:
        return None, None
    status = commit["status"]
    if status is None:
        return repository_id, None  # readable commit with no statuses
    if not isinstance(status, dict) or "context" not in status:
        return None, None
    context = status["context"]
    if context is None:
        return repository_id, None  # readable status with no context of ours
    if not isinstance(context, dict):
        return None, None
    if not isinstance(context.get("state"), str) or context["state"] not in {
        "PENDING",
        "SUCCESS",
        "FAILURE",
        "ERROR",
    }:
        return None, None
    return repository_id, (
        str(context.get("state") or "").lower(),  # GraphQL enums are upper-case; REST is lower
        str(context.get("description") or ""),
        _parse_status_created_at(context.get("createdAt")),
    )


def set_autoqueue_admission_status(
    decision: Decision,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
    now: datetime | None = None,
    force_fresh_success: bool = False,
    route: ListingRoute | str | None = None,
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
    # **Stay off a measured-blocked pool.** When the listing was routed to GraphQL because REST
    # is below its floor, an unguarded REST GET here (and the REST POST after it) fails, and the
    # apply loop then skips the queue mutation. But a GraphQL route may also mean only that
    # GraphQL has proportionally more headroom. In that case REST remains an eligible fallback
    # if the preferred GraphQL read fails.
    repository_id: str | None = None
    # The cycle's route arrives as the ListingRoute the listing chose (transport, whether REST is
    # below its floor, and why) — every caller passes `route=listing_route` — or as a bare
    # transport string. Until round 9 of #4610 this compared the OBJECT against "graphql", which
    # never matched, so every cycle stayed on REST however empty that pool was measured to be.
    if isinstance(route, ListingRoute):
        transport = route.transport
        rest_blocked = route.rest_blocked
        route_reason = route.reason
    else:
        transport = route or "rest"
        # Legacy GraphQL callers supplied no independent REST measurement. Keep their
        # conservative no-REST contract; measured fallback eligibility requires ListingRoute.
        rest_blocked = transport == "graphql"
        route_reason = ""
    if transport == "graphql":
        repository_id, current = _latest_admission_status_graphql(
            decision.pr.head_sha, repo=repo, repo_root=repo_root, runner=runner
        )
        if repository_id is None:
            if rest_blocked:
                return (
                    False,
                    "graphql_admission_status_read_failed. Next action: retry the read next "
                    "cycle when GraphQL recovers or `github_pr_status.py rate` shows REST headroom.",
                )
            current = _latest_admission_status(
                decision.pr.head_sha, repo=repo, repo_root=repo_root, runner=runner
            )
    else:
        current = _latest_admission_status(
            decision.pr.head_sha, repo=repo, repo_root=repo_root, runner=runner
        )
    if isinstance(current, AdmissionStatusReadFailed):
        return (
            False,
            f"rest_admission_status_read_failed:{current.reason}. Next action: retry the "
            "admission read next cycle; if it persists, check `gh auth status` and "
            "`github_pr_status.py rate` before retrying.",
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
    if rest_blocked:
        # Commit statuses have no GraphQL mutation — GitHub's schema defines none, and the
        # `createCommitStatus` call this branch used to make was invented (review finding on
        # #4610, round 9). The write waits for the REST pool to clear its floor. The message
        # says "rate limit" so `_admission_status_write_deferral_class` files it as a
        # transport-window deferral, not as a verdict on the pull request.
        return (
            False,
            "admission status write deferred: GitHub commit statuses are REST-only and the core "
            f"REST pool is below its floor (rate limit; {route_reason or 'no reason recorded'})",
        )
    proc = runner(
        _admission_status_post_cmd(decision.pr.head_sha, state, description, repo=repo),
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


def _admission_status_post_cmd(
    head_sha: str, state: str, description: str, *, repo: str
) -> list[str]:
    return [
        "gh",
        "api",
        "-X",
        "POST",
        f"repos/{repo}/statuses/{head_sha}",
        "-f",
        f"state={state}",
        "-f",
        f"context={AUTOQUEUE_ADMISSION_CONTEXT}",
        "-f",
        f"description={description}",
    ]


def _read_admission_status_for_refresh(
    head_sha: str,
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
    route: ListingRoute | str | None,
) -> tuple[tuple[str, str, datetime | None] | None, str | None]:
    """Route-aware admission-status read for the refresh-only path (R5).

    Mirrors the transport dispatch of `set_autoqueue_admission_status` without
    touching its reviewed control flow. Returns ``(current, None)`` on a
    successful read (``current`` is None when no status exists) or
    ``(None, reason)`` when the read itself failed.
    """
    if isinstance(route, ListingRoute):
        transport = route.transport
        rest_blocked = route.rest_blocked
    else:
        transport = route or "rest"
        rest_blocked = transport == "graphql"
    current: tuple[str, str, datetime | None] | None | AdmissionStatusReadFailed
    if transport == "graphql":
        repository_id, current = _latest_admission_status_graphql(
            head_sha, repo=repo, repo_root=repo_root, runner=runner
        )
        if repository_id is None:
            if rest_blocked:
                return None, "admission_status_read_failed:graphql_no_fallback"
            current = _latest_admission_status(
                head_sha, repo=repo, repo_root=repo_root, runner=runner
            )
    else:
        current = _latest_admission_status(head_sha, repo=repo, repo_root=repo_root, runner=runner)
    if isinstance(current, AdmissionStatusReadFailed):
        return None, f"admission_status_read_failed:{current.reason}"
    return current, None


def _refresh_must_include_proof(
    number: int,
    head_sha: str | None,
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
    now: datetime,
    apply: bool,
    route: ListingRoute | str | None,
) -> dict[str, Any]:
    """The R4/R5 cheap path: repost the existing successful admission proof.

    One status read, at most one status POST, no hydration, no new admission
    decision. Only successful proofs are refreshed (R3): a non-success status
    on a must-include PR is a signal the full path must re-examine, not
    something to re-stamp.
    """
    result: dict[str, Any] = {"pr": number}
    if not head_sha:
        return {**result, "ok": False, "message": "missing_head_sha"}
    current, read_error = _read_admission_status_for_refresh(
        head_sha, repo=repo, repo_root=repo_root, runner=runner, route=route
    )
    if read_error is not None:
        return {**result, "ok": False, "message": read_error}
    if current is None:
        return {**result, "ok": False, "message": "no_existing_admission_status"}
    state, description, created = current
    if state != "success":
        return {**result, "ok": False, "message": f"existing_status_not_success:{state}"}
    if created is not None and (now - created) < timedelta(
        seconds=MUST_INCLUDE_REFRESH_MARGIN_SECONDS
    ):
        return {**result, "ok": True, "message": "fresh", "posted": False}
    if isinstance(route, ListingRoute) and route.rest_blocked:
        return {
            **result,
            "ok": False,
            "message": (
                "admission status write deferred: GitHub commit statuses are REST-only and "
                f"the core REST pool is below its floor (rate limit; {route.reason or 'no reason recorded'})"
            ),
        }
    if not apply:
        return {**result, "ok": True, "message": "stale_would_refresh", "posted": False}
    proc = runner(
        _admission_status_post_cmd(head_sha, state, description, repo=repo),
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return {
            **result,
            "ok": False,
            "message": output or f"status write failed rc={proc.returncode}",
        }
    return {**result, "ok": True, "message": output, "posted": True}


def _must_include_state_path(rotation_state_path: Path) -> Path:
    return rotation_state_path.parent / (rotation_state_path.name + ".must-include.json")


def _load_must_include_state(path: Path, *, repo: str, now: datetime) -> dict[int, dict[str, Any]]:
    """Last-known must-include set with per-PR write-failure counters (R3/R6/R7).

    Fail-open: this is an auxiliary cache feeding a fallback and an alert, not
    fairness authority like the rotation state — a corrupt file logs and starts
    empty rather than wedging the reconciler.
    """
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        LOG.warning("must-include state unreadable, starting empty: %s", exc)
        return {}
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        LOG.warning("must-include state has an unexpected schema, starting empty")
        return {}
    entries: dict[int, dict[str, Any]] = {}
    for number, entry in (state.get("repositories", {}).get(repo) or {}).items():
        if not isinstance(entry, dict):
            continue
        try:
            last_seen = datetime.fromisoformat(entry["last_seen_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if now - last_seen > timedelta(seconds=MUST_INCLUDE_STATE_MAX_AGE_SECONDS):
            continue
        try:
            entries[int(number)] = {
                "head_sha": entry.get("head_sha"),
                "last_seen_at": entry["last_seen_at"],
                "last_success_at": entry.get("last_success_at"),
                "consecutive_failures": int(entry.get("consecutive_failures") or 0),
            }
        except (TypeError, ValueError):
            continue
    return entries


def _save_must_include_state(path: Path, repo: str, entries: dict[int, dict[str, Any]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = {"schema_version": 1, "repositories": {repo: {}}}
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and existing.get("schema_version") == 1:
                    state = existing
            except (OSError, ValueError):
                pass
            repositories = state.setdefault("repositories", {})
            repositories[repo] = {str(number): entry for number, entry in entries.items()}
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(path)
    except OSError as exc:
        LOG.warning("must-include state write failed: %s", exc)


def _refresh_must_include_batch(
    identities: list[tuple[int, str | None]] | tuple[tuple[int, str | None], ...],
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
    now: datetime,
    apply: bool,
    route: ListingRoute | str | None,
) -> dict[int, dict[str, Any]]:
    """R5: bounded per-tick refresh pass.

    Both the reads and the POST count against the per-tick cap; identities
    beyond it are reported as ``deferred_post_cap`` so the R7 counters see the
    truth instead of a silent skip.
    """
    results: dict[int, dict[str, Any]] = {}
    for index, (number, head_sha) in enumerate(identities):
        if index >= MUST_INCLUDE_REFRESH_POST_CAP:
            results[number] = {"pr": number, "ok": False, "message": "deferred_post_cap"}
            continue
        results[number] = _refresh_must_include_proof(
            number,
            head_sha,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
            now=now,
            apply=apply,
            route=route,
        )
    return results


def _record_must_include_outcomes(
    state: dict[int, dict[str, Any]],
    refresh_results: dict[int, dict[str, Any]],
    *,
    current_identities: tuple[tuple[int, str | None], ...] | None,
    apply: bool,
    path: Path,
    repo: str,
    now: datetime,
    served_full_exam: frozenset[int] | set[int] = frozenset(),
    forced_failures: tuple[int, ...] | list[int] = (),
) -> None:
    """Advance the persisted must-include counters one tick (apply mode only).

    ``current_identities`` is the new authoritative set; ``None`` keeps the
    existing keys (the R3 indeterminate path, where the only job is to record
    refresh outcomes and keep fresh entries alive).
    """
    if not apply:
        return
    if current_identities is None:
        identity_map = {number: entry.get("head_sha") for number, entry in state.items()}
    else:
        identity_map = dict(current_identities)
    entries: dict[int, dict[str, Any]] = {}
    for number in sorted(identity_map):
        if number in served_full_exam:
            # R6 is one-shot: a dequeued follow-up that got its full exam this
            # tick leaves the persisted set. If it re-arms, the armed-row
            # detection re-adds it on the next determinate tick.
            continue
        entry = dict(state.get(number) or {})
        entry["head_sha"] = identity_map.get(number)
        entry["last_seen_at"] = now.isoformat()
        result = refresh_results.get(number)
        if result is not None and result.get("ok"):
            entry["consecutive_failures"] = 0
            entry["last_success_at"] = now.isoformat()
        elif result is not None or number in forced_failures:
            entry["consecutive_failures"] = int(entry.get("consecutive_failures") or 0) + 1
        entries[number] = entry
    state.clear()
    state.update(entries)
    _save_must_include_state(path, repo, entries)


def _must_include_report_summary(
    results: dict[int, dict[str, Any]], *, overflow: tuple[int, ...] | list[int]
) -> dict[str, Any]:
    return {
        "refreshed": sorted(number for number, result in results.items() if result.get("posted")),
        "ok": sorted(number for number, result in results.items() if result.get("ok")),
        "deferred": {
            str(number): result.get("message")
            for number, result in sorted(results.items())
            if not result.get("ok")
        },
        "overflow": list(overflow),
        "post_cap": MUST_INCLUDE_REFRESH_POST_CAP,
    }


def _decision_is_non_ready(decision: Decision) -> bool:
    return decision.action in {"blocked", "hold", "dequeue", "disable_auto_merge"} and bool(
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
        expected_auto_merge_method=decision.expected_auto_merge_method,
    )


def _release_auto_arm_write_ok(ok: bool, message: str) -> bool:
    return ok or message == "note_unchanged"


def _admission_status_write_deferral_class(message: str) -> str | None:
    """Name why a failed admission-status write says nothing about the PR, or None if it might.

    A GitHub rate-limit (403 "API rate limit exceeded", secondary limit, 429) or 5xx response is a
    property of the transport window, not of the pull request: the admission already recorded on
    the head still stands, and the same write succeeds at the next reset with nothing changed on
    our side. Treating it as a failed governance write removed two admitted PRs from the merge
    queue on 2026-09-02 (#4615, #4616) — a 403 became a lost merge. Everything that is not one of
    these documented transport responses keeps the fail-closed path.
    """
    lowered = (message or "").lower()
    if lowered.startswith(
        ("rest_admission_status_read_failed", "graphql_admission_status_read_failed")
    ):
        return "admission_status_read_failed"
    if "rate limit" in lowered or '"status": "429"' in lowered or "http 429" in lowered:
        return "github_rate_limit"
    # Any 5xx, not a list of the usual ones (review finding on #4627, round 3): a 501 or a 599
    # is exactly as much about the transport window as a 502.
    if re.search(r'"status":\s*"5\d\d"|\bhttp 5\d\d\b', lowered):
        return "github_unavailable"
    return None


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
    route: str | None = None,
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
        route=route,
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
    open_pr_count: int | None = None,
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
        open_pr_count=len(prs) if open_pr_count is None else open_pr_count,
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
    rotation_state_path: Path | None = None,
    admission_governor_path: Path = DEFAULT_ADMISSION_GOVERNOR_PATH,
    expected_auto_merge_method_override: str | None = None,
    expected_auto_merge_method_source: str | None = None,
    runner: Any = None,
) -> dict[str, Any]:
    """Reconcile one batch; timer/CLI callers provide rotation_state_path across ticks.

    Without a state path, the one-shot API retains its bounded snapshot behavior.
    Dry runs can preview the persistent window but never advance it.
    """
    if limit <= 0:
        raise ValueError("autoqueue limit must be positive")
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
    must_include_state_path = (
        _must_include_state_path(rotation_state_path) if rotation_state_path is not None else None
    )
    must_include_state: dict[int, dict[str, Any]] = {}
    if (
        queued_prs_snapshot is None
        and must_include_state_path is not None
        and not _must_include_guarantee_disabled()
    ):
        # R3: the queue snapshot is indeterminate, but the persisted last-known
        # must-include set can still keep its proofs fresh — refresh-only, then
        # skip the cycle exactly as before.
        must_include_state = _load_must_include_state(must_include_state_path, repo=repo, now=now)
        refresh_only = _refresh_must_include_batch(
            [
                (number, entry.get("head_sha"))
                for number, entry in sorted(must_include_state.items())
            ],
            repo=repo,
            repo_root=repo_root,
            runner=runner or subprocess.run,
            now=now,
            apply=apply,
            route=None,
        )
        must_include_report = _must_include_report_summary(refresh_only, overflow=())
        _record_must_include_outcomes(
            must_include_state,
            refresh_only,
            current_identities=None,
            apply=apply,
            path=must_include_state_path,
            repo=repo,
            now=now,
        )
        for number, entry in sorted(must_include_state.items()):
            if entry.get("consecutive_failures", 0) >= 2:
                LOG.error(
                    "must-include PR #%s has gone %s consecutive ticks without a successful "
                    "admission status write (indeterminate queue snapshot); inspect "
                    "`github_pr_status.py rate` and this PR's status history",
                    number,
                    entry.get("consecutive_failures", 0),
                )
        must_include_report["starved"] = sorted(
            number
            for number, entry in must_include_state.items()
            if entry.get("consecutive_failures", 0) >= 2
        )
        report = {
            "repo": repo,
            "apply": apply,
            "skipped": True,
            "reason": "merge_queue_state_indeterminate",
            "detail": "native merge-queue GraphQL probe failed or backed off; no queue mutations attempted",
            "must_include": must_include_report,
        }
        return _finalize_reconciler_report(
            report,
            report_path=report_path,
            admission_governor_path=admission_governor_path,
            now=now,
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
    if must_include_state_path is not None and not _must_include_guarantee_disabled():
        must_include_state = _load_must_include_state(must_include_state_path, repo=repo, now=now)
    if _must_include_guarantee_disabled():
        # Killswitch: no must-include seats, no R3/R6 machinery this tick.
        queued_prs = frozenset()
        must_include_state_path = None
    # R6: PRs in the previous snapshot, missing now, still open get a one-shot
    # full exam this tick (still-open is enforced against the listing inside
    # selection) — the fair rotation alone would keep them waiting ~100+ min
    # for the re-arm decision after a dequeue.
    dequeued_followup = frozenset(must_include_state) - queued_prs
    if expected_auto_merge_method_override is not None:
        expected_auto_merge_method = _normalize_merge_method(expected_auto_merge_method_override)
        if expected_auto_merge_method is None:
            merge_method_source = (
                "unsupported_auto_merge_method_override:"
                f"raw={_scalar(expected_auto_merge_method_override) or 'missing'}"
            )
        else:
            merge_method_source = expected_auto_merge_method_source or "override"
    else:
        expected_auto_merge_method, merge_method_source = fetch_merge_queue_merge_method(
            repo=repo,
            repo_root=repo_root,
            runner=runner,
        )
    hydration_failures: dict[int, dict[str, Any]] = {}
    window: _WindowSelection | None = None
    try:
        if rotation_state_path is not None:
            (
                prs,
                listing_route,
                open_pr_count,
                hydration_failures,
                window,
            ) = fetch_rotating_open_prs(
                repo=repo,
                repo_root=repo_root,
                limit=limit,
                state_path=rotation_state_path,
                persist=apply,
                runner=runner or subprocess.run,
                must_include=queued_prs,
                full_exam=dequeued_followup,
                fresh_evidence=_fresh_evidence_probe(tasks, now=now),
            )
        else:
            prs, listing_route = fetch_open_prs(
                repo=repo,
                repo_root=repo_root,
                limit=limit,
                runner=runner,
                must_include=queued_prs | dequeued_followup,
            )
            open_pr_count = len(prs)
    except RestIndeterminateError as exc:
        report = {
            "repo": repo,
            "apply": apply,
            "skipped": True,
            "reason": f"open_pr_scan_indeterminate:{exc.reason}",
            "decisions": [],
            "mutations": [],
        }
        return _finalize_reconciler_report(
            report,
            report_path=report_path,
            admission_governor_path=admission_governor_path,
            now=now,
        )
    if listing_route is None:
        LOG.warning(
            "autoqueue reconcile skipped: open-PR listing unavailable "
            "(this is 'we did not look', not 'nothing to do'). Next action: none if the next "
            "cycle proceeds; if it repeats, run `github_pr_status.py rate` and `gh auth status` "
            "— a listing that fails with both pools healthy is not a quota condition."
        )
        report = {
            "repo": repo,
            "apply": apply,
            "skipped": True,
            "reason": "open_pr_listing_unavailable",
            "detail": (
                "both rate pools measured below their floors, or the listing itself failed; "
                "no PR decisions attempted"
            ),
            "decisions": [],
            "mutations": [],
        }
        return _finalize_reconciler_report(
            report,
            report_path=report_path,
            admission_governor_path=admission_governor_path,
            now=now,
        )
    must_refresh_results: dict[int, dict[str, Any]] = {}
    must_overflow: tuple[int, ...] = ()
    if window is not None and window.must_refresh:
        must_refresh_results = _refresh_must_include_batch(
            list(window.must_refresh),
            repo=repo,
            repo_root=repo_root,
            runner=runner or subprocess.run,
            now=now,
            apply=apply,
            route=listing_route,
        )
        must_overflow = window.overflow
        if apply:
            for number, result in must_refresh_results.items():
                if result.get("ok"):
                    # Rotation ack: a refreshed must-include PR must not also be
                    # picked up by the fair rotation's next fill.
                    with _reconciled_pr(
                        number, repo=repo, state_path=rotation_state_path, failures={}
                    ):
                        pass
    elif window is not None:
        must_overflow = window.overflow
    if expected_auto_merge_method is not None:
        governance_by_base: dict[
            tuple[str | None, str | None, str | None, str | None, tuple[str, ...]],
            MergeQueueGovernance,
        ] = {}
        governed_prs: list[PullRequest] = []
        for pr in prs:
            base_key = (
                pr.base_ref,
                pr.default_branch,
                pr.base_ref_detail,
                pr.default_branch_detail,
                pr.reference_reasons,
            )
            if base_key not in governance_by_base:
                governance_by_base[base_key] = fetch_pr_merge_queue_governance(
                    pr, repo=repo, repo_root=repo_root, runner=runner or subprocess.run
                )
            governed_prs.append(replace(pr, queue_governance=governance_by_base[base_key]))
        prs = governed_prs
    preliminary_decisions = [
        classify_pr(
            pr,
            tasks=tasks,
            queued_prs=queued_prs,
            require_route_metadata=require_route_metadata,
            include_pending_auto=include_pending_auto,
            required_checks=required_checks,
            active_ci_repair_task_ids=active_ci_repair_task_ids,
            expected_auto_merge_method=expected_auto_merge_method,
            expected_auto_merge_method_source=merge_method_source,
            expected_auto_merge_method_is_override=expected_auto_merge_method_override is not None,
            require_expected_auto_merge_method=True,
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
        open_pr_count=open_pr_count,
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
        open_pr_count=open_pr_count,
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
                expected_auto_merge_method=expected_auto_merge_method,
                expected_auto_merge_method_source=merge_method_source,
                expected_auto_merge_method_is_override=expected_auto_merge_method_override
                is not None,
                require_expected_auto_merge_method=True,
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
            open_pr_count=open_pr_count,
        )

    mutation_results: list[dict[str, Any]] = []
    if apply:
        for decision in decisions:
            with _reconciled_pr(
                decision.pr.number,
                repo=repo,
                state_path=rotation_state_path,
                failures=hydration_failures,
            ):
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
                            route=listing_route,
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
                                    route=listing_route,
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
                        deleted_files=decision.pr.deleted_files,
                        repo=repo,
                        repo_root=repo_root,
                        runner=runner,
                        release_authorization_waivers=release_authorization_waivers,
                        route=listing_route,
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
                                route=listing_route,
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
                    route=listing_route,
                )
                # An unreadable status prevents new admission, but a known blocker still requires
                # cancellation. merge_pr retains the existing dequeue revalidation below.
                if (
                    decision.action not in {"dequeue", "disable_auto_merge"}
                    and status_result is not None
                    and not status_result[0]
                    and _admission_status_write_deferral_class(status_result[1])
                    == "admission_status_read_failed"
                ):
                    mutation_results.append(
                        {
                            **decision.as_dict(),
                            "action": "hold",
                            "ok": True,
                            "reasons": ["admission_status_read_failed"],
                            "message": status_result[1],
                        }
                    )
                    continue
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
                            deferral = _admission_status_write_deferral_class(message)
                            if deferral is not None:
                                # The write failed for a reason that is not about this PR (see
                                # _admission_status_write_deferral_class): hold the queue state and
                                # let the next cycle write the same status. Failure paths narrow —
                                # no mutation is the only safe act on evidence about the transport.
                                mutation_results.append(
                                    {
                                        **decision.as_dict(),
                                        "action": "hold",
                                        "ok": True,
                                        "reasons": [f"admission_status_write_deferred:{deferral}"],
                                        "message": (
                                            "admission status write failed on a transport response; "
                                            "queue state held for the next cycle"
                                        ),
                                    }
                                )
                            else:
                                mutation_results.extend(
                                    _release_auto_arm_fail_closed_mutations(
                                        decision,
                                        message,
                                        reason_prefix="admission_status_write_failed",
                                        repo=repo,
                                        repo_root=repo_root,
                                        runner=runner,
                                        now=now,
                                        route=listing_route,
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
                    route=listing_route,
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
                            route=listing_route,
                        )
                    )

    starved: list[int] = []
    if must_include_state_path is not None:
        _record_must_include_outcomes(
            must_include_state,
            must_refresh_results,
            current_identities=window.must_identities if window is not None else None,
            apply=apply,
            path=must_include_state_path,
            repo=repo,
            now=now,
            served_full_exam=frozenset(dequeued_followup) & {pr.number for pr in prs},
            forced_failures=tuple(
                number
                for number in must_overflow
                # An overflow row may still have won a rotation slot and a full
                # decision; only genuinely unserved numbers count as failures.
                if number not in {pr.number for pr in prs}
            ),
        )
        starved = sorted(
            number
            for number, entry in must_include_state.items()
            if entry.get("consecutive_failures", 0) >= 2
        )
        for number in starved:
            LOG.error(
                "must-include PR #%s has gone %s consecutive ticks without a successful "
                "admission status write; inspect `github_pr_status.py rate` and this PR's "
                "status history",
                number,
                must_include_state[number].get("consecutive_failures", 0),
            )
    report = {
        "repo": repo,
        "apply": apply,
        "require_route_metadata": require_route_metadata,
        "include_pending_auto": include_pending_auto,
        "required_checks": list(required_checks),
        "active_ci_repair_task_ids": list(active_ci_repair_task_ids),
        "merge_queue_merge_method": {
            "method": expected_auto_merge_method,
            "source": merge_method_source,
            "indeterminate": expected_auto_merge_method is None,
            "next_action": _merge_method_operator_next_action()
            if expected_auto_merge_method is None
            else None,
        },
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
        "open_pr_count": open_pr_count,
        "examined_pr_count": len(prs),
        "rotation_state_path": str(rotation_state_path) if rotation_state_path else None,
        "hydration_failures": [
            {
                "pr": number,
                **failure,
                "retry_policy": "next_tick"
                if failure["consecutive_failures"] == 1
                else "fair_rotation",
                "next_action": "Retry automatically; inspect this PR's hydration if failures persist.",
            }
            for number, failure in sorted(hydration_failures.items())
        ],
        "queued_prs": sorted(queued_prs),
        "must_include": {
            **_must_include_report_summary(must_refresh_results, overflow=must_overflow),
            "starved": starved,
            "dequeued_followup": sorted(
                dequeued_followup - (window.armed_live if window is not None else frozenset())
            ),
            "fresh_evidence": sorted(window.fresh_served) if window is not None else [],
            "fresh_evidence_overflow": (
                sorted(window.fresh_overflow) if window is not None else []
            ),
        },
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
            "hold": sum(1 for decision in decisions if decision.action == "hold"),
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
    parser.add_argument("--limit", type=int, default=100, help="Maximum PRs examined per tick.")
    parser.add_argument(
        "--rotation-state-path",
        type=Path,
        default=DEFAULT_ROTATION_STATE_PATH,
        help="Persistent examination timestamps beside the autoqueue report.",
    )
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
        "--expected-merge-method",
        help=(
            "Governed emergency bypass for rulesets API/configuration incidents. "
            "Must normalize to one of MERGE, REBASE, or SQUASH; source is recorded "
            "in the report."
        ),
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
    if args.limit <= 0:
        parser.error("--limit must be positive")

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
    expected_method_override = args.expected_merge_method or os.environ.get(
        EXPECTED_MERGE_METHOD_OVERRIDE_ENV
    )
    expected_method_source = None
    if args.expected_merge_method:
        expected_method_source = "override:cli:--expected-merge-method"
    elif expected_method_override:
        expected_method_source = f"override:env:{EXPECTED_MERGE_METHOD_OVERRIDE_ENV}"

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
        rotation_state_path=args.rotation_state_path,
        admission_governor_path=args.admission_governor_path,
        expected_auto_merge_method_override=expected_method_override,
        expected_auto_merge_method_source=expected_method_source,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
