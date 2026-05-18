#!/usr/bin/env python3
"""cc-pr-autoqueue — governed PR auto-queue reconciler.

The merge queue should not depend on a human/session remembering to run
``gh pr merge`` after a governed PR is ready. This reconciler scans open PRs,
matches each PR to a cc-task in the local Obsidian vault, and queues or arms
auto-merge only when Hapax governance and GitHub protection state both pass.

GitHub's current CLI behavior for branches that require a merge queue is the
primitive this script uses: ``gh pr merge`` adds a ready PR to the queue, and
``gh pr merge --auto`` arms auto-merge until required checks/reviews pass.

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
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger("cc-pr-autoqueue")

DEFAULT_REPO = "hapax-systems/hapax-council"
DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
KILLSWITCH_ENVS = ("HAPAX_CC_PR_AUTOQUEUE_OFF", "HAPAX_CC_HYGIENE_OFF")

PASS_STATES = {"SUCCESS", "SKIPPED", "NEUTRAL"}
FAIL_STATES = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
DIRTY_MERGE_STATES = {"DIRTY", "UNKNOWN"}
UNCHECKED_PR_CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[\s\]\s+(?P<text>.+?)\s*$")
NON_BLOCKING_CHECKBOX_RE = re.compile(
    r"\b(optional|non[-_\s]?blocking|informational|follow[-_\s]?up|stretch)\b",
    re.IGNORECASE,
)
ACTIVE_READY_STATUSES = {
    "pr_open",
    "ci_green",
    "ready",
    "ready_for_review",
    "review_ready",
    "ready_for_merge",
    "done",
    "completed",
}
CLOSED_READY_STATUSES = {"done", "completed", "complete", "closed", "fulfilled"}
HOLD_LABEL_RE = re.compile(
    r"(?:^|[-_\s])(hold|do[-_\s]?not[-_\s]?merge|manual[-_\s]?merge|blocked|wip)(?:$|[-_\s])",
    re.IGNORECASE,
)


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


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    head_ref: str
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


@dataclass(frozen=True)
class Decision:
    pr: PullRequest
    action: str
    task: TaskNote | None = None
    reasons: tuple[str, ...] = ()

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
        if self.reasons:
            out["reasons"] = list(self.reasons)
        return out


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
        title=_scalar(item.get("title")) or "",
        head_ref=_scalar(item.get("headRefName")) or "",
        body=str(item.get("body") or ""),
        is_draft=bool(item.get("isDraft")),
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
                "title",
                "body",
                "headRefName",
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
                )
            )
    return notes


def _matching_tasks(pr: PullRequest, tasks: list[TaskNote]) -> list[TaskNote]:
    by_pr = [task for task in tasks if task.pr == pr.number]
    if by_pr:
        return by_pr
    return [task for task in tasks if task.branch == pr.head_ref]


def _task_blockers(task: TaskNote, *, require_route_metadata: bool) -> list[str]:
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
    elif task.status not in ACTIVE_READY_STATUSES:
        blockers.append(f"active_task_status_not_ready:{task.status or 'missing'}")
    return blockers


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


def classify_pr(
    pr: PullRequest,
    *,
    tasks: list[TaskNote],
    queued_prs: set[int],
    require_route_metadata: bool = True,
    include_pending_auto: bool = True,
) -> Decision:
    reasons: list[str] = []
    if pr.is_draft:
        reasons.append("draft")
    if pr.merge_state_status in DIRTY_MERGE_STATES:
        reasons.append(f"merge_state:{pr.merge_state_status or 'missing'}")
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
    if pr.check_summary.failed:
        reasons.append("failed_checks:" + ",".join(pr.check_summary.failed))

    matches = _matching_tasks(pr, tasks)
    task: TaskNote | None = matches[0] if len(matches) == 1 else None
    if not matches:
        reasons.append("missing_cc_task_link")
    elif len(matches) > 1:
        reasons.append("multiple_cc_task_links:" + ",".join(task.task_id for task in matches))
    else:
        reasons.extend(_task_blockers(matches[0], require_route_metadata=require_route_metadata))

    if pr.number in queued_prs:
        return Decision(pr=pr, task=task, action="already_queued", reasons=tuple(reasons))
    if reasons:
        if pr.auto_merge_enabled:
            return Decision(pr=pr, task=task, action="disable_auto_merge", reasons=tuple(reasons))
        return Decision(pr=pr, task=task, action="blocked", reasons=tuple(reasons))
    if pr.auto_merge_enabled:
        return Decision(pr=pr, task=task, action="already_auto_merge_enabled")
    if pr.check_summary.has_pending:
        if include_pending_auto:
            return Decision(pr=pr, task=task, action="enable_auto_merge")
        return Decision(
            pr=pr,
            task=task,
            action="blocked",
            reasons=("pending_checks:" + ",".join(pr.check_summary.pending),),
        )
    return Decision(pr=pr, task=task, action="queue")


def merge_pr(
    decision: Decision,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    runner: Any = None,
) -> tuple[bool, str]:
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    cmd = ["gh", "pr", "merge", str(decision.pr.number), "--repo", repo]
    if decision.action == "enable_auto_merge":
        cmd.extend(["--auto", "--merge"])
    elif decision.action == "queue":
        cmd.append("--merge")
    elif decision.action == "disable_auto_merge":
        cmd.append("--disable-auto")
    else:
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


def run_reconciler(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path | None = None,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    apply: bool = False,
    require_route_metadata: bool = True,
    include_pending_auto: bool = True,
    limit: int = 100,
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
    queued_prs = fetch_merge_queue_pr_numbers(repo=repo, repo_root=repo_root, runner=runner)
    prs = fetch_open_prs(repo=repo, repo_root=repo_root, limit=limit, runner=runner)
    decisions = [
        classify_pr(
            pr,
            tasks=tasks,
            queued_prs=queued_prs,
            require_route_metadata=require_route_metadata,
            include_pending_auto=include_pending_auto,
        )
        for pr in prs
    ]

    mutation_results: list[dict[str, Any]] = []
    if apply:
        for decision in decisions:
            if decision.action not in {"queue", "enable_auto_merge", "disable_auto_merge"}:
                continue
            ok, message = merge_pr(decision, repo=repo, repo_root=repo_root, runner=runner)
            mutation_results.append(
                {
                    **decision.as_dict(),
                    "ok": ok,
                    "message": message,
                }
            )

    return {
        "repo": repo,
        "apply": apply,
        "require_route_metadata": require_route_metadata,
        "include_pending_auto": include_pending_auto,
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
        limit=args.limit,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
