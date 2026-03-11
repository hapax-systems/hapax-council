"""Git history extraction via subprocess."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from agents.dev_story.models import Commit, CommitFile

log = logging.getLogger(__name__)


def parse_log_line(line: str) -> Commit | None:
    """Parse a git log line in format: hash|date|message."""
    parts = line.split("|", 2)
    if len(parts) < 3:
        return None
    return Commit(
        hash=parts[0].strip(),
        author_date=parts[1].strip(),
        message=parts[2].strip(),
    )


def parse_numstat_line(line: str) -> tuple[int, int, str] | None:
    """Parse a git numstat line: insertions\\tdeletions\\tpath."""
    line = line.strip()
    if not line:
        return None
    parts = line.split("\t", 2)
    if len(parts) < 3:
        return None
    ins_str, del_str, path = parts
    insertions = int(ins_str) if ins_str != "-" else 0
    deletions = int(del_str) if del_str != "-" else 0
    return insertions, deletions, path


def extract_commits(
    repo_path: str,
    since: str | None = None,
    after_hash: str | None = None,
) -> tuple[list[Commit], list[CommitFile]]:
    """Extract commits and per-file stats from a git repository.

    Args:
        repo_path: Absolute path to the repository root.
        since: Only commits after this date (ISO 8601 or relative).
        after_hash: Only commits after this hash (exclusive).

    Returns:
        Tuple of (commits, commit_files).
    """
    cmd = [
        "git",
        "-C",
        repo_path,
        "log",
        "--format=%H|%ai|%s",
        "--numstat",
    ]
    if since:
        cmd.append(f"--since={since}")
    if after_hash:
        cmd.append(f"{after_hash}..HEAD")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log.warning("git log failed in %s: %s", repo_path, result.stderr[:200])
        return [], []

    commits: list[Commit] = []
    commit_files: list[CommitFile] = []
    current_commit: Commit | None = None
    current_insertions = 0
    current_deletions = 0
    current_file_count = 0

    for line in result.stdout.splitlines():
        line = line.rstrip()

        # Empty line: git log outputs blank lines between header and numstat,
        # and between commits. Only flush if we've accumulated file stats.
        if not line:
            if current_commit and current_file_count > 0:
                current_commit.files_changed = current_file_count
                current_commit.insertions = current_insertions
                current_commit.deletions = current_deletions
                commits.append(current_commit)
                current_commit = None
                current_insertions = 0
                current_deletions = 0
                current_file_count = 0
            continue

        # Try as commit header
        parsed = parse_log_line(line)
        if parsed:
            if current_commit:
                current_commit.files_changed = current_file_count
                current_commit.insertions = current_insertions
                current_commit.deletions = current_deletions
                commits.append(current_commit)
                current_insertions = 0
                current_deletions = 0
                current_file_count = 0
            current_commit = parsed
            continue

        # Try as numstat
        numstat = parse_numstat_line(line)
        if numstat and current_commit:
            ins, dels, path = numstat
            current_insertions += ins
            current_deletions += dels
            current_file_count += 1
            # Infer operation from numstat
            operation = "A" if dels == 0 and ins > 0 else "M"
            commit_files.append(
                CommitFile(
                    commit_hash=current_commit.hash,
                    file_path=path,
                    operation=operation,
                )
            )

    # Flush last commit
    if current_commit:
        current_commit.files_changed = current_file_count
        current_commit.insertions = current_insertions
        current_commit.deletions = current_deletions
        commits.append(current_commit)

    return commits, commit_files


def discover_bundles(bundles_dir: Path) -> list[tuple[Path, str]]:
    """Find .bundle files and derive repo names from filenames.

    Expects filenames like 'ai-agents-history.bundle' -> 'ai-agents'.
    Strips the '-history' suffix if present.

    Returns:
        List of (bundle_path, repo_name) tuples.
    """
    if not bundles_dir.is_dir():
        log.warning("Bundles directory not found: %s", bundles_dir)
        return []

    results: list[tuple[Path, str]] = []
    for path in sorted(bundles_dir.glob("*.bundle")):
        name = path.stem  # e.g. 'ai-agents-history'
        if name.endswith("-history"):
            name = name[: -len("-history")]
        results.append((path, name))
    return results


def extract_commits_from_bundle(
    bundle_path: Path,
    repo_name: str,
    since: str | None = None,
) -> tuple[list[Commit], list[CommitFile]]:
    """Extract commits from a git bundle file.

    Creates a temporary bare clone from the bundle, extracts commits
    using the same git log parsing, and sets source_repo on each result.

    Args:
        bundle_path: Path to the .bundle file.
        repo_name: Name to set as source_repo on extracted records.
        since: Only commits after this date (ISO 8601 or relative).

    Returns:
        Tuple of (commits, commit_files) with source_repo populated.
    """
    with tempfile.TemporaryDirectory(prefix=f"dev-story-{repo_name}-") as tmp_dir:
        clone_path = str(Path(tmp_dir) / "repo")

        # Clone the bundle into a bare repository
        result = subprocess.run(
            ["git", "clone", "--bare", str(bundle_path), clone_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            log.warning("Failed to clone bundle %s: %s", bundle_path, result.stderr[:200])
            return [], []

        commits, commit_files = extract_commits(clone_path, since=since)

        # Tag all results with source_repo
        for commit in commits:
            commit.source_repo = repo_name
        for cf in commit_files:
            cf.source_repo = repo_name

        log.info("Extracted %d commits from bundle %s", len(commits), bundle_path.name)
        return commits, commit_files
