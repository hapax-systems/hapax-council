#!/usr/bin/env python3
"""Validate server-side merge queue admission proof.

The full Hapax queue admission decision depends on local cc-task vault state
that GitHub Actions cannot read. The governed local autoqueue therefore writes
a fresh commit status on the PR head SHA after it validates a PR. This check is
the server-side counterpart: queued or auto-merge PRs must carry that fresh
successful status before merge-group admission can pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from github_pr_status import run_graphql_rate_aware

AUTOQUEUE_ADMISSION_CONTEXT = "hapax/autoqueue-admission"
DEFAULT_TTL_SECONDS = 30 * 60
QUEUE_ACTIONS = {"enqueued", "auto_merge_enabled"}


@dataclass(frozen=True)
class Proof:
    pr: int
    head_sha: str
    state: str
    created_at: datetime | None
    description: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def _gh_json(cmd: list[str], *, runner: Any = None) -> Any:
    runner = runner or subprocess.run
    proc = runner(cmd, capture_output=True, text=True, check=False, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or f"command failed: {cmd}").strip())
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh emitted non-JSON for {cmd}: {exc}") from exc


def pr_numbers_from_ref(*refs: str | None) -> list[int]:
    numbers: list[int] = []
    for ref in refs:
        if not ref:
            continue
        for match in re.finditer(r"(?:^|[/-])pr-(\d+)(?=-|/|$)", ref):
            number = int(match.group(1))
            if number not in numbers:
                numbers.append(number)
    return numbers


def pr_numbers_from_event(
    *,
    event_name: str,
    event_path: Path,
    ref_name: str | None,
    ref: str | None,
) -> tuple[list[int], str]:
    payload: dict[str, Any] = {}
    if event_path.is_file():
        loaded = json.loads(event_path.read_text(encoding="utf-8") or "{}")
        payload = loaded if isinstance(loaded, dict) else {}

    if event_name == "pull_request":
        action = str(payload.get("action") or "")
        if action not in QUEUE_ACTIONS:
            return [], f"pull_request action {action or '<missing>'} is not queue admission"
        number = ((payload.get("pull_request") or {}).get("number")) or payload.get("number")
        if number is None:
            raise RuntimeError("pull_request event is missing pull_request.number")
        return [int(number)], f"pull_request:{action}"

    if event_name == "merge_group":
        merge_group = payload.get("merge_group") or {}
        refs = [
            ref_name,
            ref,
            merge_group.get("head_ref") if isinstance(merge_group, dict) else None,
            merge_group.get("ref") if isinstance(merge_group, dict) else None,
        ]
        numbers = pr_numbers_from_ref(*refs)
        if not numbers:
            raise RuntimeError(
                "merge_group event did not expose PR numbers in ref/head_ref; "
                "cannot validate queue admission proof"
            )
        return numbers, "merge_group"

    return [], f"event {event_name or '<missing>'} is not queue admission"


def fetch_head_sha(repo: str, pr: int, *, runner: Any = None) -> str:
    try:
        payload = _gh_json(["gh", "api", f"repos/{repo}/pulls/{pr}"], runner=runner)
    except RuntimeError as exc:
        return fetch_head_sha_graphql(repo, pr, runner=runner, rest_error=str(exc))
    head = payload.get("head") if isinstance(payload, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    if not sha:
        raise RuntimeError(f"PR #{pr} head SHA unavailable")
    return str(sha)


def fetch_head_sha_graphql(
    repo: str, pr: int, *, runner: Any = None, rest_error: str | None = None
) -> str:
    runner = runner or subprocess.run
    owner, name = repo.split("/", 1)
    query = (
        "query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){"
        "pullRequest(number:$number){headRefOid}}}"
    )
    proc = run_graphql_rate_aware(
        [
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={name}",
            "-F",
            f"number={pr}",
        ],
        repo_root=Path.cwd(),
        runner=runner,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"graphql failed rc={proc.returncode}").strip()
        prefix = f"REST pull fetch failed: {rest_error}; " if rest_error else ""
        raise RuntimeError(f"{prefix}GraphQL head fallback failed: {detail}")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GraphQL head fallback emitted non-JSON: {exc}") from exc
    pull = (
        payload.get("data", {}).get("repository", {}).get("pullRequest")
        if isinstance(payload, dict)
        else None
    )
    sha = pull.get("headRefOid") if isinstance(pull, dict) else None
    if not sha:
        raise RuntimeError(f"PR #{pr} head SHA unavailable from GraphQL fallback")
    return str(sha)


def fetch_latest_proof(repo: str, pr: int, *, runner: Any = None) -> Proof:
    head_sha = fetch_head_sha(repo, pr, runner=runner)
    statuses = _gh_json(
        ["gh", "api", f"repos/{repo}/commits/{head_sha}/statuses?per_page=100"],
        runner=runner,
    )
    if not isinstance(statuses, list):
        statuses = []
    matching = [
        item
        for item in statuses
        if isinstance(item, dict) and item.get("context") == AUTOQUEUE_ADMISSION_CONTEXT
    ]
    if not matching:
        return Proof(pr=pr, head_sha=head_sha, state="missing", created_at=None, description="")
    matching.sort(
        key=lambda item: (
            _parse_time(str(item.get("created_at") or "")) or datetime.min.replace(tzinfo=UTC)
        ),
        reverse=True,
    )
    latest = matching[0]
    return Proof(
        pr=pr,
        head_sha=head_sha,
        state=str(latest.get("state") or ""),
        created_at=_parse_time(str(latest.get("created_at") or "")),
        description=str(latest.get("description") or ""),
    )


def validate_proofs(
    *,
    repo: str,
    prs: list[int],
    ttl_seconds: int,
    now: datetime | None = None,
    runner: Any = None,
) -> list[str]:
    now = now or _utc_now()
    cutoff = now - timedelta(seconds=ttl_seconds)
    failures: list[str] = []
    for pr in prs:
        proof = fetch_latest_proof(repo, pr, runner=runner)
        if proof.state != "success":
            failures.append(f"PR #{pr}: admission status is {proof.state or 'missing'}")
            continue
        if proof.created_at is None:
            failures.append(f"PR #{pr}: admission status has no parseable created_at")
            continue
        if proof.created_at < cutoff:
            failures.append(
                f"PR #{pr}: admission status is stale "
                f"({proof.created_at.isoformat()} < {cutoff.isoformat()})"
            )
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository as owner/name.")
    parser.add_argument(
        "--event-path", type=Path, default=Path(os.environ.get("GITHUB_EVENT_PATH", ""))
    )
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--ref-name", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF", ""))
    parser.add_argument("--pr", action="append", type=int, default=[], help="Explicit PR number.")
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    prs = list(dict.fromkeys(args.pr))
    reason = "explicit"
    if not prs:
        prs, reason = pr_numbers_from_event(
            event_name=args.event_name,
            event_path=args.event_path.expanduser(),
            ref_name=args.ref_name,
            ref=args.ref,
        )
    if not prs:
        print(f"queue admission proof: PASS ({reason})")
        return 0
    failures = validate_proofs(repo=args.repo, prs=prs, ttl_seconds=args.ttl_seconds)
    if failures:
        print("queue admission proof: FAIL", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"queue admission proof: PASS ({reason}) for PRs {prs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
