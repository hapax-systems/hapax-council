"""Thin wrapper around the ``gh`` CLI for SDLC pipeline operations.

Used by ``scripts/sdlc_*.py`` to interact with GitHub issues and pull requests.
Depends only on the ``gh`` binary being authenticated (``GITHUB_TOKEN`` or ``gh auth``).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    head_branch: str = ""
    diff: str = ""


def _run_gh(*args: str, input_text: str | None = None) -> str:
    """Run a ``gh`` CLI command and return stdout."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        input=input_text,
        timeout=60,
    )
    if result.returncode != 0:
        msg = f"gh {' '.join(args)} failed: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Issue operations
# ---------------------------------------------------------------------------


def fetch_issue(number: int) -> Issue:
    """Fetch an issue by number."""
    raw = _run_gh(
        "issue",
        "view",
        str(number),
        "--json",
        "number,title,body,labels",
    )
    data = json.loads(raw)
    labels = [lb["name"] for lb in data.get("labels", [])]
    return Issue(
        number=data["number"],
        title=data["title"],
        body=data.get("body") or "",
        labels=labels,
    )


def post_issue_comment(number: int, body: str) -> None:
    """Post a comment on an issue."""
    _run_gh("issue", "comment", str(number), "--body", body)


def add_issue_labels(number: int, *labels: str) -> None:
    """Add labels to an issue."""
    if not labels:
        return
    _run_gh("issue", "edit", str(number), *[f"--add-label={lb}" for lb in labels])


def remove_issue_label(number: int, label: str) -> None:
    """Remove a label from an issue. No-op if label not present."""
    try:
        _run_gh("issue", "edit", str(number), f"--remove-label={label}")
    except RuntimeError:
        pass  # label wasn't there


def search_closed_issues(query: str, limit: int = 5) -> list[dict]:
    """Search closed issues/PRs matching query keywords.

    Returns list of dicts with number, title, labels, state.
    """
    raw = _run_gh(
        "issue",
        "list",
        "--state",
        "closed",
        "--search",
        query,
        "--limit",
        str(limit),
        "--json",
        "number,title,labels,state",
    )
    items = json.loads(raw)
    return [
        {
            "number": item["number"],
            "title": item["title"],
            "labels": [lb["name"] for lb in item.get("labels", [])],
            "state": item.get("state", "CLOSED"),
        }
        for item in items
    ]


# ---------------------------------------------------------------------------
# Pull request operations
# ---------------------------------------------------------------------------


def fetch_pr(number: int) -> PullRequest:
    """Fetch a pull request by number."""
    raw = _run_gh(
        "pr",
        "view",
        str(number),
        "--json",
        "number,title,body,labels,headRefName",
    )
    data = json.loads(raw)
    labels = [lb["name"] for lb in data.get("labels", [])]
    return PullRequest(
        number=data["number"],
        title=data["title"],
        body=data.get("body") or "",
        labels=labels,
        head_branch=data.get("headRefName", ""),
    )


def fetch_pr_diff(number: int) -> str:
    """Fetch the diff of a pull request."""
    return _run_gh("pr", "diff", str(number))


def fetch_pr_changed_files(number: int) -> list[str]:
    """Return list of file paths changed in a PR."""
    raw = _run_gh(
        "pr",
        "view",
        str(number),
        "--json",
        "files",
    )
    data = json.loads(raw)
    return [f["path"] for f in data.get("files", [])]


def post_pr_comment(number: int, body: str) -> None:
    """Post a comment on a pull request."""
    _run_gh("pr", "comment", str(number), "--body", body)


def add_pr_labels(number: int, *labels: str) -> None:
    """Add labels to a pull request."""
    if not labels:
        return
    _run_gh("pr", "edit", str(number), *[f"--add-label={lb}" for lb in labels])


def remove_pr_label(number: int, label: str) -> None:
    """Remove a label from a PR. No-op if label not present."""
    try:
        _run_gh("pr", "edit", str(number), f"--remove-label={label}")
    except RuntimeError:
        pass


def post_pr_review(
    number: int,
    body: str,
    event: str = "COMMENT",
) -> None:
    """Submit a PR review (COMMENT, APPROVE, or REQUEST_CHANGES)."""
    _run_gh(
        "api",
        "repos/{owner}/{repo}/pulls/{number}/reviews".format(
            owner="{owner}", repo="{repo}", number=number
        ),
        "-X",
        "POST",
        "-f",
        f"event={event}",
        "-f",
        f"body={body}",
    )


def fetch_pr_checks(number: int) -> list[dict]:
    """Fetch CI check statuses for a PR."""
    raw = _run_gh(
        "pr",
        "checks",
        str(number),
        "--json",
        "name,state,conclusion",
    )
    return json.loads(raw)


def dispatch_event(event_type: str, payload: dict) -> None:
    """Dispatch a repository_dispatch event."""
    _run_gh(
        "api",
        "repos/{owner}/{repo}/dispatches",
        "-X",
        "POST",
        "-f",
        f"event_type={event_type}",
        "-f",
        f"client_payload={json.dumps(payload)}",
    )
