"""Git commit history RAG sync — local repository commit extraction.

Walks a configured list of local Git repositories, extracts commit history
(messages, stats, key-file diffs), and writes per-repo markdown summaries
to rag-sources/git/ for RAG ingestion.

Usage:
    uv run python -m agents.git_sync --full-sync    # Full 90-day history sync
    uv run python -m agents.git_sync --auto         # Incremental sync
    uv run python -m agents.git_sync --stats        # Show sync state
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

try:
    from agents import _langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "git-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "git-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"

RAG_SOURCES = Path.home() / "documents" / "rag-sources"
GIT_DIR = RAG_SOURCES / "git"

ROLLING_WINDOW_DAYS = 90

KEY_FILE_PATTERNS: set[str] = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
}
KEY_FILE_NAMES: set[str] = {
    "CLAUDE.md",
    "pyproject.toml",
}

REPOS: list[Path] = [
    Path.home() / "projects" / "hapax-council",
    Path.home() / "projects" / "hapax-officium",
    Path.home() / "projects" / "hapax-constitution",
    Path.home() / "projects" / "distro-work",
]

MAX_DIFF_LINES = 40


# ── Schemas ──────────────────────────────────────────────────────────────────


class CommitInfo(BaseModel):
    """A single parsed git commit."""

    hash: str
    author: str
    date: str
    subject: str
    body: str = ""
    files_changed: list[str] = Field(default_factory=list)
    stats: str = ""
    diff_hunks: str = ""


class RepoState(BaseModel):
    """Per-repo sync state."""

    last_commit_sha: str = ""
    commit_count: int = 0


class GitSyncState(BaseModel):
    """Persistent sync state across all repos."""

    repos: dict[str, RepoState] = Field(default_factory=dict)
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)


# ── Git Subprocess Helpers ───────────────────────────────────────────────────


def _git(repo: Path, *args: str, timeout: int = 30) -> str | None:
    """Run a git command in the given repo directory. Returns stdout or None on error."""
    cmd = ["git", "-C", str(repo), *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            log.warning("git command failed in %s: %s\n%s", repo.name, cmd, result.stderr.strip())
            return None
        return result.stdout
    except subprocess.TimeoutExpired:
        log.warning("git command timed out in %s: %s", repo.name, cmd)
        return None
    except FileNotFoundError:
        log.error("git binary not found")
        return None


def _is_git_repo(repo: Path) -> bool:
    """Check if a path is a valid git repository."""
    if not repo.is_dir():
        return False
    result = _git(repo, "rev-parse", "--is-inside-work-tree")
    return result is not None and result.strip() == "true"


# ── State Management ─────────────────────────────────────────────────────────


def _load_state(path: Path = STATE_FILE) -> GitSyncState:
    """Load sync state from disk."""
    if path.exists():
        try:
            return GitSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return GitSyncState()


def _save_state(state: GitSyncState, path: Path = STATE_FILE) -> None:
    """Persist sync state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── Commit Extraction ────────────────────────────────────────────────────────


def _get_commits_since(
    repo: Path, since_sha: str | None, since_days: int = ROLLING_WINDOW_DAYS
) -> list[CommitInfo]:
    """Extract commits from a repo, either since a SHA or since N days ago."""
    since_date = (datetime.now(tz=UTC) - timedelta(days=since_days)).strftime("%Y-%m-%d")

    # Use a delimiter that won't appear in commit messages
    sep = "---GIT_SYNC_RECORD_SEP---"
    field_sep = "---GIT_SYNC_FIELD_SEP---"
    fmt = f"{field_sep}%H{field_sep}%an{field_sep}%ai{field_sep}%s{field_sep}%b{sep}"

    args = [
        "log",
        f"--format={fmt}",
        f"--since={since_date}",
        "--no-merges",
    ]

    # If we have a last-seen SHA, only get commits after it
    if since_sha:
        # Verify the SHA still exists (branch may have been rebased)
        check = _git(repo, "cat-file", "-t", since_sha)
        if check and check.strip() == "commit":
            args.append(f"{since_sha}..HEAD")

    raw = _git(repo, *args, timeout=60)
    if not raw or not raw.strip():
        return []

    commits: list[CommitInfo] = []
    for block in raw.split(sep):
        block = block.strip()
        if not block:
            continue
        parts = block.split(field_sep)
        # parts[0] is empty (before first sep), then hash, author, date, subject, body
        if len(parts) < 5:
            continue

        commit_hash = parts[1].strip()
        author = parts[2].strip()
        date = parts[3].strip()
        subject = parts[4].strip()
        body = parts[5].strip() if len(parts) > 5 else ""

        # Get file stats for this commit
        stat_output = _git(repo, "diff-tree", "--no-commit-id", "-r", "--stat", commit_hash)
        files_raw = _git(repo, "diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash)

        files_changed = [f.strip() for f in (files_raw or "").strip().splitlines() if f.strip()]
        stats = (stat_output or "").strip()

        # For key files, get abbreviated diff hunks
        diff_hunks = _get_key_file_diffs(repo, commit_hash, files_changed)

        commits.append(
            CommitInfo(
                hash=commit_hash,
                author=author,
                date=date,
                subject=subject,
                body=body,
                files_changed=files_changed,
                stats=stats,
                diff_hunks=diff_hunks,
            )
        )

    return commits


def _is_key_file(filepath: str) -> bool:
    """Check if a file matches key-file patterns for diff extraction."""
    name = Path(filepath).name
    if name in KEY_FILE_NAMES:
        return True
    suffix = Path(filepath).suffix
    return suffix in KEY_FILE_PATTERNS


def _get_key_file_diffs(repo: Path, commit_hash: str, files: list[str]) -> str:
    """Get abbreviated diff hunks for key files in a commit."""
    key_files = [f for f in files if _is_key_file(f)]
    if not key_files:
        return ""

    hunks: list[str] = []
    for filepath in key_files[:5]:  # Cap at 5 files per commit
        diff_output = _git(
            repo,
            "diff-tree",
            "-p",
            "--no-commit-id",
            "-U2",
            commit_hash,
            "--",
            filepath,
        )
        if not diff_output:
            continue

        # Truncate long diffs
        lines = diff_output.strip().splitlines()
        if len(lines) > MAX_DIFF_LINES:
            lines = lines[:MAX_DIFF_LINES]
            lines.append(f"... ({len(diff_output.splitlines()) - MAX_DIFF_LINES} more lines)")

        hunks.append("\n".join(lines))

    return "\n\n".join(hunks)


# ── Formatting ───────────────────────────────────────────────────────────────


def _format_repo_markdown(repo_name: str, commits: list[CommitInfo]) -> str:
    """Format a repo's commit history as a markdown document for RAG ingestion."""
    if not commits:
        return ""

    # Determine date range
    dates = [c.date for c in commits if c.date]
    date_range = ""
    if dates:
        earliest = min(dates)[:10]
        latest = max(dates)[:10]
        date_range = f"{earliest} to {latest}"

    lines = [
        "---",
        "platform: local",
        "source_service: git",
        "content_type: commit_history",
        f"record_id: {repo_name}",
        f"repository: {repo_name}",
        f"commit_count: {len(commits)}",
        f'date_range: "{date_range}"',
        "modality_tags: [development, decisions]",
        "---",
        "",
        f"# {repo_name} — Git Commit History",
        "",
        f"**{len(commits)} commits** | {date_range}",
        "",
    ]

    for commit in commits:
        lines.append(f"## `{commit.hash[:8]}` — {commit.subject}")
        lines.append("")
        lines.append(f"**Author:** {commit.author} | **Date:** {commit.date}")
        lines.append("")

        if commit.body:
            lines.append(commit.body)
            lines.append("")

        if commit.files_changed:
            lines.append(
                f"**Files ({len(commit.files_changed)}):** "
                + ", ".join(f"`{f}`" for f in commit.files_changed[:15])
            )
            if len(commit.files_changed) > 15:
                lines.append(f"  ... and {len(commit.files_changed) - 15} more")
            lines.append("")

        if commit.diff_hunks:
            lines.append("<details><summary>Key file diffs</summary>")
            lines.append("")
            lines.append("```diff")
            lines.append(commit.diff_hunks)
            lines.append("```")
            lines.append("")
            lines.append("</details>")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ── File Writing ─────────────────────────────────────────────────────────────


def _write_repo_file(repo_name: str, commits: list[CommitInfo]) -> bool:
    """Write a repo's commit history markdown to the RAG output directory."""
    if not commits:
        return False

    content = _format_repo_markdown(repo_name, commits)
    if not content:
        return False

    GIT_DIR.mkdir(parents=True, exist_ok=True)
    path = GIT_DIR / f"repo-{repo_name}.md"
    path.write_text(content, encoding="utf-8")
    log.info("Wrote %d commits to %s", len(commits), path)
    return True


# ── Changes Log ──────────────────────────────────────────────────────────────


def _append_changes_log(repo_name: str, new_commits: list[CommitInfo]) -> None:
    """Record new commits seen per sync to the changes log."""
    if not new_commits:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        entry = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "repo": repo_name,
            "new_commits": len(new_commits),
            "shas": [c.hash[:12] for c in new_commits[:20]],
            "subjects": [c.subject for c in new_commits[:10]],
        }
        fh.write(json.dumps(entry) + "\n")


# ── Sync Operations ──────────────────────────────────────────────────────────


def _sync_repo(
    repo: Path,
    state: GitSyncState,
    *,
    full: bool = False,
) -> tuple[str, int]:
    """Sync a single repo. Returns (repo_name, commits_written)."""
    repo_name = repo.name
    if not _is_git_repo(repo):
        log.warning("Skipping %s — not a git repo or does not exist", repo)
        return repo_name, 0

    repo_state = state.repos.get(repo_name, RepoState())

    since_sha = None if full else (repo_state.last_commit_sha or None)
    commits = _get_commits_since(repo, since_sha)

    if not commits:
        log.debug("No new commits in %s", repo_name)
        return repo_name, 0

    # For full sync, write all commits within the rolling window
    # For incremental, we got only commits since the last SHA
    written = _write_repo_file(repo_name, commits)

    # Update state with the newest commit SHA
    repo_state.last_commit_sha = commits[0].hash
    repo_state.commit_count = len(commits)
    state.repos[repo_name] = repo_state

    # Log changes for incremental syncs
    if not full:
        _append_changes_log(repo_name, commits)

    return repo_name, len(commits) if written else 0


def _full_sync(state: GitSyncState) -> dict[str, int]:
    """Full sync: all repos, full rolling window. Returns {repo: commit_count}."""
    results: dict[str, int] = {}
    for repo in REPOS:
        name, count = _sync_repo(repo, state, full=True)
        results[name] = count
    return results


def _incremental_sync(state: GitSyncState) -> dict[str, int]:
    """Incremental sync: only new commits since last seen SHA."""
    results: dict[str, int] = {}
    for repo in REPOS:
        name, count = _sync_repo(repo, state, full=False)
        results[name] = count
    return results


# ── Profiler Integration ─────────────────────────────────────────────────────


def _generate_profile_facts(state: GitSyncState) -> list[dict]:
    """Generate deterministic profile facts from git commit state."""
    facts: list[dict] = []
    source = "git-sync:git-profile-facts"

    # Commit frequency per repo
    repo_counts = {name: rs.commit_count for name, rs in state.repos.items() if rs.commit_count > 0}
    if repo_counts:
        summary = ", ".join(
            f"{name} ({count})"
            for name, count in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True)
        )
        facts.append(
            {
                "dimension": "development_activity",
                "key": "git_commit_frequency",
                "value": summary,
                "confidence": 0.90,
                "source": source,
                "evidence": f"Commit counts across {len(repo_counts)} repos in last {ROLLING_WINDOW_DAYS} days",
            }
        )

    # Collect per-repo stats from the written markdown files
    all_files: Counter[str] = Counter()
    all_extensions: Counter[str] = Counter()
    all_hours: Counter[int] = Counter()

    for repo in REPOS:
        if not _is_git_repo(repo):
            continue
        # Get file-change frequency
        raw = _git(
            repo,
            "log",
            f"--since={ROLLING_WINDOW_DAYS} days ago",
            "--name-only",
            "--format=",
            "--no-merges",
        )
        if raw:
            for line in raw.strip().splitlines():
                line = line.strip()
                if line:
                    all_files[line] += 1
                    ext = Path(line).suffix
                    if ext:
                        all_extensions[ext] += 1

        # Get commit hours
        hours_raw = _git(
            repo, "log", f"--since={ROLLING_WINDOW_DAYS} days ago", "--format=%H", "--no-merges"
        )
        if hours_raw:
            for h in hours_raw.strip().splitlines():
                h = h.strip()
                if h.isdigit():
                    all_hours[int(h)] += 1

    # Most-changed files
    if all_files:
        top_files = ", ".join(f"{f} ({n})" for f, n in all_files.most_common(10))
        facts.append(
            {
                "dimension": "development_activity",
                "key": "git_most_changed_files",
                "value": top_files,
                "confidence": 0.85,
                "source": source,
                "evidence": f"Top files by change frequency across {len(all_files)} unique files",
            }
        )

    # Language distribution
    if all_extensions:
        top_langs = ", ".join(f"{ext} ({n})" for ext, n in all_extensions.most_common(8))
        facts.append(
            {
                "dimension": "development_activity",
                "key": "git_languages",
                "value": top_langs,
                "confidence": 0.85,
                "source": source,
                "evidence": f"File extension frequency across {sum(all_extensions.values())} file changes",
            }
        )

    # Active hours
    if all_hours:
        peak_hours = sorted(all_hours.items(), key=lambda x: x[1], reverse=True)[:5]
        hours_str = ", ".join(f"{h:02d}:00 ({n})" for h, n in peak_hours)
        facts.append(
            {
                "dimension": "work_patterns",
                "key": "git_active_hours",
                "value": hours_str,
                "confidence": 0.80,
                "source": source,
                "evidence": f"Commit hour distribution across {sum(all_hours.values())} commits",
            }
        )

    return facts


def _write_profile_facts(state: GitSyncState) -> None:
    """Write profile facts JSONL for profiler bridge consumption."""
    facts = _generate_profile_facts(state)
    if not facts:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_FACTS_FILE, "w", encoding="utf-8") as fh:
        for fact in facts:
            fh.write(json.dumps(fact) + "\n")
    log.info("Wrote %d profile facts to %s", len(facts), PROFILE_FACTS_FILE)


# ── Stats ────────────────────────────────────────────────────────────────────


def _print_stats(state: GitSyncState) -> None:
    """Print sync statistics."""
    total_commits = sum(rs.commit_count for rs in state.repos.values())
    print("Git Sync State")
    print("=" * 40)
    print(f"Tracked repos:  {len(state.repos)}")
    print(f"Total commits:  {total_commits:,}")
    print(
        f"Last sync:      {datetime.fromtimestamp(state.last_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}"
    )

    if state.repos:
        print("\nPer-repo state:")
        for name, rs in sorted(state.repos.items()):
            sha_short = rs.last_commit_sha[:8] if rs.last_commit_sha else "none"
            print(f"  {name}: {rs.commit_count} commits, last={sha_short}")


# ── Orchestration ────────────────────────────────────────────────────────────


def run_full_sync() -> None:
    """Full sync of all repos within the rolling window."""
    from agents._notify import send_notification

    state = _load_state()
    results = _full_sync(state)

    state.last_sync = time.time()
    total = sum(results.values())
    state.stats = {
        "total_commits": total,
        "repos_synced": len([v for v in results.values() if v > 0]),
    }

    _save_state(state)
    _write_profile_facts(state)

    # Sensor protocol — write state + impingement
    from agents._sensor_protocol import emit_sensor_impingement, write_sensor_state

    write_sensor_state(
        "git", {"total_commits": total, "repos_synced": len(results), "last_sync": time.time()}
    )
    if total > 0:
        emit_sensor_impingement("git", "work_patterns", ["commit_sync"])

    per_repo = ", ".join(f"{name}={count}" for name, count in sorted(results.items()) if count > 0)
    msg = f"Git sync (full): {total} commits across {len(results)} repos. {per_repo}"
    log.info(msg)
    send_notification("Git Sync", msg, tags=["git"])


def run_auto() -> None:
    """Incremental git sync."""
    from agents._notify import send_notification

    state = _load_state()

    if not state.repos:
        log.info("No prior sync — running full sync")
        run_full_sync()
        return

    results = _incremental_sync(state)

    state.last_sync = time.time()
    total = sum(results.values())
    state.stats = {
        "total_commits": total,
        "repos_synced": len([v for v in results.values() if v > 0]),
    }

    _save_state(state)
    _write_profile_facts(state)

    # Sensor protocol — write state + impingement on changes
    from agents._sensor_protocol import emit_sensor_impingement, write_sensor_state

    write_sensor_state(
        "git", {"total_commits": total, "repos_synced": len(results), "last_sync": time.time()}
    )
    if total > 0:
        emit_sensor_impingement("git", "work_patterns", ["commit_sync"])

    if total > 0:
        per_repo = ", ".join(
            f"{name}={count}" for name, count in sorted(results.items()) if count > 0
        )
        msg = f"Git sync: {total} new commits. {per_repo}"
        log.info(msg)
        send_notification("Git Sync", msg, tags=["git"])
    else:
        log.info("No new git commits")


def run_stats() -> None:
    """Display sync statistics."""
    state = _load_state()
    if not state.repos:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Git commit history RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full-sync", action="store_true", help="Full rolling-window sync")
    group.add_argument("--auto", action="store_true", help="Incremental sync")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from agents._log_setup import configure_logging

    configure_logging(agent="git-sync", level="DEBUG" if args.verbose else None)

    action = "full_sync" if args.full_sync else "auto" if args.auto else "stats"
    with _tracer.start_as_current_span(
        f"git_sync.{action}",
        attributes={"agent.name": "git_sync", "agent.repo": "hapax-council"},
    ):
        if args.full_sync:
            run_full_sync()
        elif args.auto:
            run_auto()
        elif args.stats:
            run_stats()


if __name__ == "__main__":
    main()
