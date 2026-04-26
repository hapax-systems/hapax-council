"""Velocity measurement primitives — read-only over `git log`."""

from __future__ import annotations

import shutil
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class VelocityReport:
    repo: str
    window_days: int
    commits: int
    commits_per_day: float
    distinct_authors: int
    author_rotation: float
    additions: int
    deletions: int
    loc_churn_per_day: float
    prs: int | None
    prs_per_day: float | None
    measured_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _git_log_since(repo: Path, since_iso: str) -> list[tuple[str, str]]:
    out = _run_git(
        repo,
        "log",
        f"--since={since_iso}",
        "--pretty=format:%H%x09%an",
    )
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, _, author = line.partition("\t")
        rows.append((sha.strip(), author.strip()))
    return rows


def _git_churn_since(repo: Path, since_iso: str) -> tuple[int, int]:
    out = _run_git(
        repo,
        "log",
        f"--since={since_iso}",
        "--numstat",
        "--pretty=format:",
    )
    additions = 0
    deletions = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        adds, dels, _ = parts
        if adds == "-" or dels == "-":
            continue
        try:
            additions += int(adds)
            deletions += int(dels)
        except ValueError:
            continue
    return additions, deletions


def _gh_pr_count_since(repo: Path, since_iso: str) -> int | None:
    if shutil.which("gh") is None:
        return None
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "all",
                "--limit",
                "500",
                "--json",
                "createdAt",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=repo,
        )
    except subprocess.CalledProcessError:
        return None
    import json

    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    cutoff = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
    return sum(
        1 for p in prs if datetime.fromisoformat(p["createdAt"].replace("Z", "+00:00")) >= cutoff
    )


def measure_repo(repo: str | Path = ".", window_days: int = 7) -> VelocityReport:
    repo_path = Path(repo).resolve()
    if not (repo_path / ".git").exists() and not (repo_path / ".git").is_file():
        raise ValueError(f"{repo_path} is not a git repository")
    if window_days < 1:
        raise ValueError("window_days must be >= 1")

    now = datetime.now(UTC)
    since = now - timedelta(days=window_days)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = _git_log_since(repo_path, since_iso)
    commits = len(rows)
    authors = Counter(author for _, author in rows)
    distinct_authors = len(authors)
    rotation = (distinct_authors / commits) if commits else 0.0
    additions, deletions = _git_churn_since(repo_path, since_iso)
    pr_count = _gh_pr_count_since(repo_path, since_iso)

    return VelocityReport(
        repo=str(repo_path),
        window_days=window_days,
        commits=commits,
        commits_per_day=commits / window_days,
        distinct_authors=distinct_authors,
        author_rotation=rotation,
        additions=additions,
        deletions=deletions,
        loc_churn_per_day=(additions + deletions) / window_days,
        prs=pr_count,
        prs_per_day=(pr_count / window_days) if pr_count is not None else None,
        measured_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
