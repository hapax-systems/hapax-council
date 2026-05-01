"""Git-activity content source for the overlay-zones producer.

Reads recent commits from the council git repo and emits short
``[GIT] <hash> <subject>`` lines to the ``main`` overlay zone, per the
spec at
``docs/superpowers/specs/2026-04-27-overlay-zones-producer-design.md``
§3.2.

The source is intentionally minimal: shells out to ``git log`` once per
:meth:`collect`, parses the structured output, and emits one
:class:`TextEntry` per commit. No watchers, no state, no caching —
the producer's dedup-by-id (commit hash) handles repeat collection.

When ``git`` is missing, the repo is invalid, or the subprocess fails,
:meth:`collect` logs and returns an empty list. The producer's
degraded-empty-state semantics handle the rest.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from shared.text_repo import TEXT_ENTRY_MAX_BODY_LEN, TextEntry

log = logging.getLogger(__name__)

#: Default time window — commits older than this are excluded from the
#: main zone (the operator already saw them yesterday).
DEFAULT_SINCE_SECONDS: Final[float] = 6 * 3600.0  # 6 hours

#: Default max commits per collect call, so a long burst of activity
#: doesn't dominate the zone.
DEFAULT_MAX_COMMITS: Final[int] = 8

#: Default body cap below the repo-wide cap so the Pango layout stays
#: legible (the spec recommends 1-2 sentences max).
DEFAULT_MAX_SUBJECT_LEN: Final[int] = 120


@dataclass(frozen=True)
class GitCommit:
    """One commit record parsed from ``git log``.

    ``sha`` is the full commit hash (used as the ``TextEntry.id``).
    ``subject`` is the first line of the commit message.
    ``timestamp`` is unix seconds, parsed from ``%ct``.
    """

    sha: str
    subject: str
    timestamp: float


def _git_log(
    repo: Path,
    since_seconds: float,
    max_commits: int,
    *,
    runner=subprocess.run,  # type: ignore[no-untyped-def]
) -> list[GitCommit]:
    """Return parsed commit records or an empty list on error.

    ``runner`` is injectable so tests can stub the subprocess call
    without touching the real git binary.
    """
    if shutil.which("git") is None:
        log.debug("git not on PATH; GitActivitySource degrades to empty")
        return []
    if not (repo / ".git").exists() and not (repo / "HEAD").exists():
        log.debug("no .git at %s; GitActivitySource degrades to empty", repo)
        return []
    try:
        proc = runner(
            [
                "git",
                "-C",
                str(repo),
                "log",
                f"-n{max_commits}",
                f"--since={int(since_seconds)} seconds ago",
                "--pretty=format:%H%x09%ct%x09%s",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.debug("git log subprocess raised at %s", repo, exc_info=True)
        return []
    if proc.returncode != 0:
        log.debug(
            "git log exit %d at %s: %s",
            proc.returncode,
            repo,
            (proc.stderr or "").strip()[:200],
        )
        return []

    commits: list[GitCommit] = []
    for raw in proc.stdout.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, ct_raw, subject = parts
        try:
            ts = float(int(ct_raw))
        except (TypeError, ValueError):
            continue
        if not sha or not subject.strip():
            continue
        commits.append(
            GitCommit(
                sha=sha.strip(),
                subject=subject.strip(),
                timestamp=ts,
            )
        )
    return commits


def _format_body(commit: GitCommit, *, max_subject_len: int) -> str:
    """Render a commit as a ``[GIT] <hash7> <subject>`` overlay line."""
    short = commit.sha[:7]
    subject = commit.subject
    if len(subject) > max_subject_len:
        subject = subject[: max_subject_len - 1] + "…"
    body = f"[GIT] {short} {subject}"
    # Defense-in-depth: respect the repo-wide body cap even if a future
    # change removes the per-source truncation above.
    if len(body) > TEXT_ENTRY_MAX_BODY_LEN:
        body = body[: TEXT_ENTRY_MAX_BODY_LEN - 1] + "…"
    return body


class GitActivitySource:
    """Emits ``[GIT] <hash> <subject>`` entries for recent commits.

    Targets the ``main`` zone via ``context_keys=["main"]``; the
    ``OverlayZoneManager`` matches that key when selecting for the
    ``main`` zone's rotation.
    """

    def __init__(
        self,
        *,
        repo_path: Path,
        since_seconds: float = DEFAULT_SINCE_SECONDS,
        max_commits: int = DEFAULT_MAX_COMMITS,
        max_subject_len: int = DEFAULT_MAX_SUBJECT_LEN,
        runner=subprocess.run,  # type: ignore[no-untyped-def]
    ) -> None:
        self._repo_path = repo_path
        self._since_seconds = since_seconds
        self._max_commits = max_commits
        self._max_subject_len = max_subject_len
        self._runner = runner

    def collect(self, now: float) -> list[TextEntry]:
        del now  # unused — git log filters by --since itself.
        commits = _git_log(
            self._repo_path,
            since_seconds=self._since_seconds,
            max_commits=self._max_commits,
            runner=self._runner,
        )
        entries: list[TextEntry] = []
        for commit in commits:
            try:
                entry = TextEntry(
                    id=commit.sha[:12],
                    body=_format_body(commit, max_subject_len=self._max_subject_len),
                    tags=["git"],
                    priority=5,
                    context_keys=["main"],
                )
            except Exception:
                log.debug("invalid commit %s; skipping", commit.sha, exc_info=True)
                continue
            entries.append(entry)
        return entries
