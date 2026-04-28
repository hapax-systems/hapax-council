#!/usr/bin/env python
"""Build a machine-readable velocity-report evidence snapshot.

This script is intentionally narrow: it records the local evidence needed to
audit the 2026-04-25 velocity report without publishing anything and without
mutating repositories. It does not try to recover the original missing command
transcript; it records the current reconstruction windows and corpus counts so
future claims cite a concrete artifact instead of prose memory.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_NAMES = (
    "hapax-council",
    "hapax-officium",
    "hapax-mcp",
    "hapax-watch",
    "hapax-phone",
    "hapax-constitution",
)

WINDOWS = {
    "civil_day_current_branches": (
        "2026-04-25T00:00:00-05:00",
        "2026-04-25T23:59:59-05:00",
        False,
    ),
    "civil_day_all_refs": (
        "2026-04-25T00:00:00-05:00",
        "2026-04-25T23:59:59-05:00",
        True,
    ),
    "churn_nearest_reported_window_current_branches": (
        "2026-04-25T00:00:00-05:00",
        "2026-04-25T18:00:00-05:00",
        False,
    ),
    "commit_nearest_reported_window_current_branches": (
        "2026-04-25T05:27:00-05:00",
        "2026-04-25T23:27:00-05:00",
        False,
    ),
}


@dataclass(frozen=True)
class RepoWindow:
    repo: str
    ref_mode: str
    branch: str | None
    head: str | None
    commits: int
    additions: int
    deletions: int
    churn: int
    commit_shas: list[str]


def _run(cmd: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def _display_path(path: Path) -> str:
    home = Path.home()
    try:
        rel = path.resolve().relative_to(home)
    except ValueError:
        return str(path)
    return f"~/{rel}"


def _repo_paths(projects_root: Path) -> list[Path]:
    return [projects_root / name for name in REPO_NAMES]


def _git_branch(repo: Path) -> str | None:
    try:
        branch = _run(["git", "-C", str(repo), "branch", "--show-current"]).strip()
    except subprocess.CalledProcessError:
        return None
    return branch or None


def _git_head(repo: Path) -> str | None:
    try:
        return _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).strip()
    except subprocess.CalledProcessError:
        return None


def measure_repo_window(repo: Path, *, since: str, until: str, all_refs: bool) -> RepoWindow:
    base = ["git", "-C", str(repo), "log"]
    if all_refs:
        base.append("--all")
    base.extend([f"--since={since}", f"--until={until}"])

    commit_out = _run([*base, "--pretty=%H"])
    commit_shas = [line.strip() for line in commit_out.splitlines() if line.strip()]

    numstat = _run([*base, "--numstat", "--pretty=format:"])
    additions = 0
    deletions = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, _path = parts
        if not (added.isdigit() and deleted.isdigit()):
            continue
        additions += int(added)
        deletions += int(deleted)

    return RepoWindow(
        repo=_display_path(repo),
        ref_mode="all_refs" if all_refs else "current_branch",
        branch=_git_branch(repo),
        head=_git_head(repo),
        commits=len(set(commit_shas)),
        additions=additions,
        deletions=deletions,
        churn=additions + deletions,
        commit_shas=sorted(set(commit_shas)),
    )


def _window_totals(rows: list[RepoWindow]) -> dict[str, int]:
    return {
        "commits": sum(row.commits for row in rows),
        "additions": sum(row.additions for row in rows),
        "deletions": sum(row.deletions for row in rows),
        "churn": sum(row.churn for row in rows),
    }


def _frontmatter_value(text: str, key: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    prefix = f"{key}:"
    for line in text[4:end].splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix).strip().strip('"').strip("'")
    return None


def count_research_drops(repo: Path, *, through_date: str = "2026-04-25") -> dict[str, Any]:
    research_dir = repo / "docs" / "research"
    files = sorted(research_dir.glob("*.md"))
    dated = [path for path in files if path.name[:10] <= through_date]
    shaped = 0
    for path in dated:
        status = _frontmatter_value(path.read_text(encoding="utf-8"), "status")
        if status == "shaped":
            shaped += 1
    return {
        "repo": _display_path(repo),
        "through_date": through_date,
        "total_dated_files": len(dated),
        "shaped_files": shaped,
    }


def count_refusal_tasks(task_root: Path) -> dict[str, Any]:
    files = sorted(task_root.glob("*/*.md"))
    status_refused = 0
    automation_refused = 0
    refusal_like = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        status = (_frontmatter_value(text, "status") or "").lower()
        automation = (_frontmatter_value(text, "automation_status") or "").upper()
        if status == "refused":
            status_refused += 1
            refusal_like.add(path)
        if automation == "REFUSED":
            automation_refused += 1
            refusal_like.add(path)
        if "/refused/" in path.as_posix() or "REFUSED" in text[:500] or "refused-as-data" in text:
            refusal_like.add(path)
    total = len(files)
    return {
        "task_root": _display_path(task_root),
        "total_task_files": total,
        "status_refused": status_refused,
        "automation_status_refused": automation_refused,
        "refusal_like_unique": len(refusal_like),
        "status_refused_ratio": round(status_refused / total, 4) if total else 0.0,
        "automation_refused_ratio": round(automation_refused / total, 4) if total else 0.0,
        "refusal_like_ratio": round(len(refusal_like) / total, 4) if total else 0.0,
    }


def build_snapshot(*, projects_root: Path, task_root: Path) -> dict[str, Any]:
    repos = [
        path
        for path in _repo_paths(projects_root)
        if (path / ".git").exists() or (path / ".git").is_file()
    ]
    windows: dict[str, Any] = {}
    for label, (since, until, all_refs) in WINDOWS.items():
        rows = [
            measure_repo_window(repo, since=since, until=until, all_refs=all_refs) for repo in repos
        ]
        windows[label] = {
            "since": since,
            "until": until,
            "ref_mode": "all_refs" if all_refs else "current_branch",
            "totals": _window_totals(rows),
            "repos": [asdict(row) for row in rows],
        }

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "velocity-report-2026-04-25 evidence reconciliation",
        "reported_values": {
            "commits": 137,
            "loc_churn_approx": 33500,
            "research_drops_total": 265,
            "research_drops_per_day": 5.9,
            "refused_task_ratio": 0.218,
            "first_attempt_ci_pass_rate": 0.47,
        },
        "windows": windows,
        "research_drops": count_research_drops(projects_root / "hapax-council"),
        "refusal_tasks": count_refusal_tasks(task_root),
        "ci_first_attempt_pass_rate": {
            "status": "not_reconstructed",
            "reason": "No durable first-attempt PR-to-CI raw output was found during WSJF-007.",
        },
        "interpretation": {
            "original_metric_transcript_found": False,
            "single_window_matches_reported_commits_and_churn": False,
            "recommended_public_claim_state": "corrected_pending_superseding_measurement",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-root", type=Path, default=Path.home() / "projects")
    parser.add_argument(
        "--task-root",
        type=Path,
        default=Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = build_snapshot(projects_root=args.projects_root, task_root=args.task_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
