#!/usr/bin/env python3
"""GitHub PR/status helpers that keep routine polling off GraphQL.

The GitHub CLI implements many ``gh pr`` status fields through GraphQL.  Fleet
timers should use REST/core for routine status polling and reserve GraphQL for
operations that have no REST replacement, such as native merge-queue metadata
or the dequeue mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_REPO = "hapax-systems/hapax-council"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "hapax" / "pr-status"
DEFAULT_CACHE_TTL_SECONDS = 60
DEFAULT_GRAPHQL_MIN_REMAINING = 500
DEFAULT_GRAPHQL_BACKOFF_MAX_SLEEP_SECONDS = 0
DEFAULT_TIMEOUT_SECONDS = 60
STATUS_CACHE_SCHEMA_VERSION = 2
GRAPHQL_BACKOFF_RC = 75
REST_INDETERMINATE_CHECK_NAME = "github-rest-status-indeterminate"

_SAFE_CACHE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class GraphQLBackoff:
    remaining: int
    reset_epoch: int | None
    reason: str

    @property
    def reset_in_seconds(self) -> int | None:
        if self.reset_epoch is None:
            return None
        return max(0, self.reset_epoch - int(time.time()))


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _runner_uses_real_gh(runner: Any) -> bool:
    return runner is subprocess.run


def _run(
    runner: Any,
    cmd: list[str],
    *,
    repo_root: Path,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    return runner(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _json_from_proc(proc: subprocess.CompletedProcess) -> Any | None:
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None


def _upper_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.upper() if text else None


def _cache_key(repo: str, ref: str) -> Path:
    repo_part = _SAFE_CACHE_RE.sub("_", repo)
    ref_part = _SAFE_CACHE_RE.sub("_", ref)
    return DEFAULT_CACHE_DIR / repo_part / f"{ref_part}.json"


def _cache_ttl_seconds() -> int:
    return max(0, _env_int("HAPAX_GITHUB_PR_STATUS_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS))


def _read_cached_rollup(repo: str, ref: str) -> list[dict[str, Any]] | None:
    ttl = _cache_ttl_seconds()
    if ttl <= 0:
        return None
    path = _cache_key(repo, ref)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    fetched_at = payload.get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return None
    if time.time() - float(fetched_at) > ttl:
        return None
    if (
        payload.get("schema_version") != STATUS_CACHE_SCHEMA_VERSION
        or payload.get("complete") is not True
    ):
        return None
    rollup = payload.get("statusCheckRollup")
    return rollup if isinstance(rollup, list) else None


def _write_cached_rollup(repo: str, ref: str, rollup: list[dict[str, Any]]) -> None:
    ttl = _cache_ttl_seconds()
    if ttl <= 0:
        return
    path = _cache_key(repo, ref)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "fetched_at": time.time(),
                    "schema_version": STATUS_CACHE_SCHEMA_VERSION,
                    "complete": True,
                    "repo": repo,
                    "ref": ref,
                    "statusCheckRollup": rollup,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        return


def _rest_get_json(
    path: str,
    *,
    repo_root: Path,
    runner: Any,
    fields: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any | None:
    cmd = [
        "gh",
        "api",
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        path,
    ]
    for key, value in (fields or {}).items():
        cmd.extend(["-f", f"{key}={value}"])
    proc = _run(runner, cmd, repo_root=repo_root, timeout=timeout)
    return _json_from_proc(proc)


def _rest_get_json_pages_or_none(
    path: str,
    *,
    repo_root: Path,
    runner: Any,
    fields: dict[str, str] | None = None,
    limit: int = 100,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[Any] | None:
    if limit <= 0:
        return []
    out: list[Any] = []
    page = 1
    while len(out) < limit:
        per_page = min(100, limit - len(out))
        page_fields = dict(fields or {})
        page_fields.update({"per_page": str(per_page), "page": str(page)})
        payload = _rest_get_json(
            path,
            repo_root=repo_root,
            runner=runner,
            fields=page_fields,
            timeout=timeout,
        )
        if not isinstance(payload, list):
            return None
        if not payload:
            break
        out.extend(payload)
        if len(payload) < per_page:
            break
        page += 1
    return out


def _rest_get_json_pages(
    path: str,
    *,
    repo_root: Path,
    runner: Any,
    fields: dict[str, str] | None = None,
    limit: int = 100,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[Any]:
    return (
        _rest_get_json_pages_or_none(
            path,
            repo_root=repo_root,
            runner=runner,
            fields=fields,
            limit=limit,
            timeout=timeout,
        )
        or []
    )


def _rest_get_json_object_array_pages_or_none(
    path: str,
    *,
    array_key: str,
    total_key: str | None = None,
    repo_root: Path,
    runner: Any,
    fields: dict[str, str] | None = None,
    limit: int = 5000,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[Any] | None:
    if limit <= 0:
        return []
    out: list[Any] = []
    page = 1
    while len(out) < limit:
        per_page = min(100, limit - len(out))
        page_fields = dict(fields or {})
        page_fields.update({"per_page": str(per_page), "page": str(page)})
        payload = _rest_get_json(
            path,
            repo_root=repo_root,
            runner=runner,
            fields=page_fields,
            timeout=timeout,
        )
        if not isinstance(payload, dict):
            return None
        raw_items = payload.get(array_key)
        if not isinstance(raw_items, list):
            return None
        out.extend(raw_items)
        total_count = payload.get(total_key) if total_key else None
        if isinstance(total_count, int):
            if total_count > limit:
                return None
            if len(out) >= total_count:
                break
        if not raw_items or len(raw_items) < per_page:
            break
        page += 1
    return out


def _indeterminate_rollup(reason: str) -> list[dict[str, Any]]:
    return [
        {
            "name": REST_INDETERMINATE_CHECK_NAME,
            "status": "PENDING",
            "conclusion": None,
            "details": reason,
        }
    ]


def _check_run_to_rollup(item: dict[str, Any]) -> dict[str, Any]:
    app = item.get("app") if isinstance(item.get("app"), dict) else {}
    return {
        "name": item.get("name") or item.get("external_id") or "unnamed-check",
        "status": _upper_or_none(item.get("status")),
        "conclusion": _upper_or_none(item.get("conclusion")),
        "started_at": item.get("started_at"),
        "completed_at": item.get("completed_at"),
        "app": {"name": app.get("name")} if app else {},
    }


def _status_to_rollup(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "context": item.get("context") or "unnamed-status",
        "state": _upper_or_none(item.get("state")),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def fetch_status_check_rollup_rest(
    ref: str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    use_cache: bool | None = None,
) -> list[dict[str, Any]]:
    """Return a GraphQL-like ``statusCheckRollup`` using REST check/status APIs."""

    if not ref:
        return []
    if use_cache is None:
        use_cache = _runner_uses_real_gh(runner)
    if use_cache:
        cached = _read_cached_rollup(repo, ref)
        if cached is not None:
            return cached

    raw_runs = _rest_get_json_object_array_pages_or_none(
        f"repos/{repo}/commits/{ref}/check-runs",
        array_key="check_runs",
        total_key="total_count",
        repo_root=repo_root,
        runner=runner,
    )
    if raw_runs is None:
        return _indeterminate_rollup("check_runs_rest_indeterminate")

    combined_status = _rest_get_json(
        f"repos/{repo}/commits/{ref}/status",
        repo_root=repo_root,
        runner=runner,
        fields={"per_page": "100"},
    )
    raw_statuses = combined_status.get("statuses") if isinstance(combined_status, dict) else None
    if not isinstance(raw_statuses, list):
        return _indeterminate_rollup("combined_status_rest_indeterminate")

    rollup: list[dict[str, Any]] = []
    rollup.extend(_check_run_to_rollup(item) for item in raw_runs if isinstance(item, dict))
    rollup.extend(_status_to_rollup(item) for item in raw_statuses if isinstance(item, dict))

    if use_cache and rollup:
        _write_cached_rollup(repo, ref, rollup)
    return rollup


def get_pull_rest(
    pr_number: int | str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
) -> dict[str, Any] | None:
    payload = _rest_get_json(
        f"repos/{repo}/pulls/{pr_number}",
        repo_root=repo_root,
        runner=runner,
    )
    return payload if isinstance(payload, dict) else None


def rest_merge_state_status(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return "UNKNOWN"
    raw = str(payload.get("mergeable_state") or "").strip().upper()
    if raw:
        return raw
    mergeable = payload.get("mergeable")
    if mergeable is True:
        return "CLEAN"
    if mergeable is False:
        return "DIRTY"
    return "UNKNOWN"


def rest_pull_state(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    state = str(payload.get("state") or "").lower()
    if state == "open":
        return "OPEN"
    if state == "closed":
        if payload.get("merged") or payload.get("merged_at"):
            return "MERGED"
        return "CLOSED"
    return None


def list_pulls_for_branch_rest(
    branch: str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    state: str = "all",
    limit: int = 1,
    fail_on_indeterminate: bool = False,
) -> list[dict[str, Any]]:
    owner = repo.split("/", 1)[0]
    head = branch if ":" in branch else f"{owner}:{branch}"
    if fail_on_indeterminate:
        payload = _rest_get_json_pages_or_none(
            f"repos/{repo}/pulls",
            repo_root=repo_root,
            runner=runner,
            fields={"head": head, "state": state, "per_page": str(limit)},
            limit=limit,
        )
        if payload is None:
            raise subprocess.SubprocessError(f"REST pull list indeterminate for {repo} head={head}")
    else:
        payload = _rest_get_json_pages(
            f"repos/{repo}/pulls",
            repo_root=repo_root,
            runner=runner,
            fields={"head": head, "state": state, "per_page": str(limit)},
            limit=limit,
        )
    return [item for item in payload if isinstance(item, dict)]


def list_pulls_rest(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    state: str = "open",
    limit: int = 100,
    sort: str | None = None,
    direction: str | None = None,
    fail_on_indeterminate: bool = False,
) -> list[dict[str, Any]]:
    fields = {"state": state, "per_page": str(limit)}
    if sort:
        fields["sort"] = sort
    if direction:
        fields["direction"] = direction
    if fail_on_indeterminate:
        payload = _rest_get_json_pages_or_none(
            f"repos/{repo}/pulls",
            repo_root=repo_root,
            runner=runner,
            fields=fields,
            limit=limit,
        )
        if payload is None:
            raise subprocess.SubprocessError(f"REST pull list indeterminate for {repo}")
    else:
        payload = _rest_get_json_pages(
            f"repos/{repo}/pulls",
            repo_root=repo_root,
            runner=runner,
            fields=fields,
            limit=limit,
        )
    return [item for item in payload if isinstance(item, dict)]


def list_pull_files_rest(
    pr_number: int | str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    limit: int = 3000,
) -> list[dict[str, Any]]:
    payload = _rest_get_json_pages(
        f"repos/{repo}/pulls/{pr_number}/files",
        repo_root=repo_root,
        runner=runner,
        limit=limit,
    )
    return [item for item in payload if isinstance(item, dict)]


def review_decision_rest(
    pr_number: int | str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    limit: int = 100,
) -> str | None:
    payload = _rest_get_json_pages_or_none(
        f"repos/{repo}/pulls/{pr_number}/reviews",
        repo_root=repo_root,
        runner=runner,
        limit=limit,
    )
    if payload is None:
        return "REVIEW_REQUIRED"
    latest_by_reviewer: dict[str, str] = {}
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        state = _upper_or_none(item.get("state"))
        if not state or state == "COMMENTED":
            continue
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        reviewer = str(user.get("login") or item.get("user_login") or f"review-{index}")
        latest_by_reviewer[reviewer] = state
    states = set(latest_by_reviewer.values())
    if "CHANGES_REQUESTED" in states:
        return "CHANGES_REQUESTED"
    if "APPROVED" in states:
        return "APPROVED"
    return "REVIEW_REQUIRED"


def _files_payload_from_rest(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in files:
        filename = item.get("filename") or item.get("path")
        if filename:
            out.append({"path": str(filename)})
    return out


def _pull_status_row_from_rest(
    item: dict[str, Any],
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
    include_files: bool = False,
    include_review_decision: bool = False,
    include_status: bool = True,
    hydrate_pull: bool = False,
) -> dict[str, Any]:
    number = item.get("number")
    should_hydrate = hydrate_pull or include_files or include_review_decision
    detail = (
        (get_pull_rest(number, repo=repo, repo_root=repo_root, runner=runner) if number else None)
        if should_hydrate
        else None
    )
    pull = detail if isinstance(detail, dict) else item
    head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
    sha = str(head.get("sha") or "")
    head_ref = str(head.get("ref") or "")
    status_ref = sha or head_ref
    files = (
        list_pull_files_rest(number, repo=repo, repo_root=repo_root, runner=runner)
        if (include_files and number)
        else []
    )
    try:
        changed_files = (
            int(pull["changed_files"]) if pull.get("changed_files") is not None else None
        )
    except (TypeError, ValueError):
        changed_files = None
    if changed_files is None and files:
        changed_files = len(files)
    labels = pull.get("labels") if isinstance(pull.get("labels"), list) else []
    return {
        "number": number,
        "id": pull.get("node_id") or pull.get("id"),
        "state": rest_pull_state(pull),
        "title": pull.get("title") or "",
        "body": pull.get("body") or "",
        "url": pull.get("html_url") or pull.get("url"),
        "updatedAt": pull.get("updated_at"),
        "mergedAt": pull.get("merged_at"),
        "headRefName": head_ref,
        "headRefOid": sha,
        "changedFiles": changed_files,
        "files": _files_payload_from_rest(files) if include_files else None,
        "isDraft": bool(pull.get("draft")),
        "labels": labels,
        "reviewDecision": review_decision_rest(
            number,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
        )
        if include_review_decision and number
        else None,
        "autoMergeRequest": pull.get("auto_merge"),
        "mergeStateStatus": rest_merge_state_status(pull),
        "statusCheckRollup": fetch_status_check_rollup_rest(
            status_ref,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
        )
        if include_status and status_ref
        else [],
    }


def list_open_pr_statuses_rest(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    limit: int = 100,
    include_files: bool = False,
    include_review_decision: bool = False,
    include_status: bool = True,
    fail_on_indeterminate: bool = False,
) -> list[dict[str, Any]]:
    payload = list_pulls_rest(
        repo=repo,
        repo_root=repo_root,
        runner=runner,
        state="open",
        limit=limit,
        fail_on_indeterminate=fail_on_indeterminate,
    )

    out: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        out.append(
            _pull_status_row_from_rest(
                item,
                repo=repo,
                repo_root=repo_root,
                runner=runner,
                include_files=include_files,
                include_review_decision=include_review_decision,
                include_status=include_status,
                hydrate_pull=include_files or include_review_decision,
            )
        )
    return out


def list_pr_statuses_for_branch_rest(
    branch: str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    limit: int = 5,
    include_status: bool = True,
    fail_on_indeterminate: bool = False,
) -> list[dict[str, Any]]:
    payload = list_pulls_for_branch_rest(
        branch,
        repo=repo,
        repo_root=repo_root,
        runner=runner,
        state="open",
        limit=limit,
        fail_on_indeterminate=fail_on_indeterminate,
    )
    return [
        _pull_status_row_from_rest(
            item,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
            include_status=include_status,
            hydrate_pull=False,
        )
        for item in payload
        if isinstance(item, dict)
    ]


def get_pr_status_rest(
    pr_number: int | str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    include_status: bool = True,
) -> dict[str, Any] | None:
    pull = get_pull_rest(pr_number, repo=repo, repo_root=repo_root, runner=runner)
    if not isinstance(pull, dict):
        return None
    return _pull_status_row_from_rest(
        pull,
        repo=repo,
        repo_root=repo_root,
        runner=runner,
        include_status=include_status,
        hydrate_pull=True,
    )


def graphql_backoff(
    *,
    repo_root: Path,
    runner: Any = subprocess.run,
    min_remaining: int | None = None,
) -> GraphQLBackoff | None:
    """Return a backoff decision when GraphQL remaining is below threshold.

    A rate-limit lookup failure returns ``None`` so callers fail open: a network
    or auth hiccup must not be mistaken for confirmed GraphQL exhaustion.
    """

    min_remaining = (
        DEFAULT_GRAPHQL_MIN_REMAINING if min_remaining is None else max(0, min_remaining)
    )
    proc = _run(runner, ["gh", "api", "rate_limit"], repo_root=repo_root, timeout=30)
    payload = _json_from_proc(proc)
    resource = None
    if isinstance(payload, dict):
        resources = payload.get("resources")
        if isinstance(resources, dict):
            resource = resources.get("graphql")
    if not isinstance(resource, dict):
        return None
    try:
        remaining = int(resource.get("remaining"))
    except (TypeError, ValueError):
        return None
    reset_epoch: int | None
    try:
        reset_epoch = int(resource.get("reset"))
    except (TypeError, ValueError):
        reset_epoch = None
    if remaining >= min_remaining:
        return None
    return GraphQLBackoff(
        remaining=remaining,
        reset_epoch=reset_epoch,
        reason=f"github_graphql_remaining_below_threshold:{remaining}<{min_remaining}",
    )


def run_graphql_rate_aware(
    graphql_args: list[str],
    *,
    repo_root: Path,
    runner: Any = subprocess.run,
    min_remaining: int | None = None,
    max_sleep_seconds: int | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Run ``gh api graphql`` only when the GraphQL pool is not exhausted."""

    backoff = graphql_backoff(
        repo_root=repo_root,
        runner=runner,
        min_remaining=min_remaining
        if min_remaining is not None
        else _env_int("HAPAX_GITHUB_GRAPHQL_MIN_REMAINING", DEFAULT_GRAPHQL_MIN_REMAINING),
    )
    if backoff is not None:
        max_sleep = (
            _env_int(
                "HAPAX_GITHUB_GRAPHQL_BACKOFF_MAX_SLEEP_SECONDS",
                DEFAULT_GRAPHQL_BACKOFF_MAX_SLEEP_SECONDS,
            )
            if max_sleep_seconds is None
            else max(0, max_sleep_seconds)
        )
        reset = backoff.reset_in_seconds
        if reset is not None and max_sleep > 0:
            time.sleep(min(reset, max_sleep))
            backoff = graphql_backoff(
                repo_root=repo_root,
                runner=runner,
                min_remaining=min_remaining
                if min_remaining is not None
                else _env_int("HAPAX_GITHUB_GRAPHQL_MIN_REMAINING", DEFAULT_GRAPHQL_MIN_REMAINING),
            )
        if backoff is None:
            return _run(
                runner,
                ["gh", "api", "graphql", *graphql_args],
                repo_root=repo_root,
                timeout=timeout,
            )
        reset = backoff.reset_in_seconds
        retry = f"; retry_after={reset}s" if reset is not None else ""
        return subprocess.CompletedProcess(
            ["gh", "api", "graphql", *graphql_args],
            GRAPHQL_BACKOFF_RC,
            "",
            f"{backoff.reason}{retry}",
        )
    return _run(
        runner,
        ["gh", "api", "graphql", *graphql_args],
        repo_root=repo_root,
        timeout=timeout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    open_parser = subparsers.add_parser(
        "open-prs",
        help="Emit GraphQL-shaped open PR snapshots fetched through REST/core.",
    )
    open_parser.add_argument("--repo", default=DEFAULT_REPO)
    open_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    open_parser.add_argument("--head", help="Filter to an open PR head branch.")
    open_parser.add_argument("--limit", type=int, default=100)
    open_parser.add_argument(
        "--no-status",
        action="store_true",
        help="Omit per-PR check/status rollups when only PR identity is needed.",
    )

    args = parser.parse_args(argv)
    if args.command == "open-prs":
        include_status = not args.no_status
        if args.head:
            rows = list_pr_statuses_for_branch_rest(
                args.head,
                repo=args.repo,
                repo_root=args.repo_root,
                limit=args.limit,
                include_status=include_status,
                fail_on_indeterminate=True,
            )
        else:
            rows = list_open_pr_statuses_rest(
                repo=args.repo,
                repo_root=args.repo_root,
                limit=args.limit,
                include_status=include_status,
                fail_on_indeterminate=True,
            )
        json.dump(rows, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
