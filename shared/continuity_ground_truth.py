"""Live D10 ground-truth snapshot for the Continuity Substrate.

This module reads source-of-truth surfaces at snapshot time. It deliberately does
not inspect transcript content: git, PR, coordination claim files, and cc-task
frontmatter are authoritative pointers used later to catch hallucinated progress.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.frontmatter import parse_frontmatter

DEFAULT_RECENT_COMMIT_LIMIT = 5
DEFAULT_CLAIM_LEASE_SECONDS = 21_600
DEFAULT_TASK_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"


class _FrozenSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GitState(_FrozenSourceModel):
    """Live git state for the repository being snapshotted."""

    head: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    dirty: bool = Field(strict=True)
    recent_commits: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _nonblank_commits(self) -> Self:
        if any(not commit.strip() for commit in self.recent_commits):
            raise ValueError("recent_commits must not contain blank entries")
        return self


class PrState(_FrozenSourceModel):
    """Best-effort GitHub PR state for the current branch."""

    number: int | None = Field(default=None, ge=1)
    state: str | None = None
    head: str | None = None
    merge_state: str | None = None

    @model_validator(mode="after")
    def _consistent_optional_pr(self) -> Self:
        for name in ("state", "head", "merge_state"):
            value = getattr(self, name)
            if isinstance(value, str) and not value.strip():
                raise ValueError(f"{name} must not be blank when present")
        if self.number is None and any((self.state, self.head, self.merge_state)):
            raise ValueError("PR metadata requires a PR number")
        return self


class CoordState(_FrozenSourceModel):
    """Live coordination claim-file state.

    Entries are intentionally strings so readers can preserve their local claim
    key format. The default reader emits ``<claim-key>=<task-id>`` entries.
    """

    active_claims: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _nonblank_claims(self) -> Self:
        if any(not claim.strip() for claim in self.active_claims):
            raise ValueError("active_claims must not contain blank entries")
        return self


class CcTaskState(_FrozenSourceModel):
    """Live cc-task frontmatter state for the active task, when discoverable."""

    task_id: str | None = None
    status: str | None = None

    @model_validator(mode="after")
    def _status_requires_task(self) -> Self:
        if isinstance(self.task_id, str) and not self.task_id.strip():
            raise ValueError("task_id must not be blank when present")
        if isinstance(self.status, str) and not self.status.strip():
            raise ValueError("status must not be blank when present")
        if self.task_id is None and self.status is not None:
            raise ValueError("status requires task_id")
        return self


class GroundTruthSnapshot(_FrozenSourceModel):
    """D10 source snapshot assembled from live, non-transcript surfaces."""

    captured_at: datetime
    git: GitState
    pr: PrState
    coord: CoordState
    cc_task: CcTaskState
    provenance: Literal["SOURCE"] = "SOURCE"

    @model_validator(mode="after")
    def _captured_at_is_aware(self) -> Self:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return self


class GitReader(Protocol):
    def __call__(self, repo: Path) -> GitState | Mapping[str, Any]: ...


class PrReader(Protocol):
    def __call__(self, repo: Path) -> PrState | Mapping[str, Any]: ...


class CoordReader(Protocol):
    def __call__(self, repo: Path) -> CoordState | Mapping[str, Any]: ...


class CcTaskReader(Protocol):
    def __call__(self, repo: Path, coord: CoordState) -> CcTaskState | Mapping[str, Any]: ...


NowProvider = datetime | Callable[[], datetime]


def read_ground_truth(
    *,
    repo: str | Path,
    now: NowProvider,
    git_reader: GitReader | None = None,
    pr_reader: PrReader | None = None,
    coord_reader: CoordReader | None = None,
    cc_task_reader: CcTaskReader | None = None,
) -> GroundTruthSnapshot:
    """Read a live D10 ground-truth snapshot.

    Reader arguments are dependency-injection seams for tests and future wiring.
    Defaults read real git subprocess state, best-effort ``gh pr view`` state,
    Hapax ``cc-active-task-*`` claim files, and the cc-task vault frontmatter.
    """

    repo_path = Path(repo).expanduser().resolve()
    captured_at = now() if callable(now) else now

    git = _coerce_model(GitState, (git_reader or default_git_reader)(repo_path))
    pr = _coerce_model(PrState, (pr_reader or default_pr_reader)(repo_path))
    coord = _coerce_model(CoordState, (coord_reader or default_coord_reader)(repo_path))
    cc_task = _coerce_model(
        CcTaskState,
        (cc_task_reader or default_cc_task_reader)(repo_path, coord),
    )

    return GroundTruthSnapshot(
        captured_at=captured_at,
        git=git,
        pr=pr,
        coord=coord,
        cc_task=cc_task,
    )


def default_git_reader(repo: Path) -> GitState:
    """Read git state from ``repo`` with subprocesses."""

    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current") or "HEAD"
    status = _git(repo, "status", "--porcelain")
    log = _git(
        repo,
        "log",
        f"--max-count={DEFAULT_RECENT_COMMIT_LIMIT}",
        "--pretty=format:%H %s",
    )
    commits = tuple(line for line in log.splitlines() if line.strip())
    return GitState(head=head, branch=branch, dirty=bool(status), recent_commits=commits)


def default_pr_reader(repo: Path) -> PrState:
    """Read the current branch PR with GitHub CLI, returning empty state on miss."""

    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                "--json",
                "number,state,headRefName,mergeStateStatus",
            ],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return PrState()
    if result.returncode != 0 or not result.stdout.strip():
        return PrState()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return PrState()
    number = payload.get("number")
    return PrState(
        number=number if isinstance(number, int) else None,
        state=_optional_text(payload.get("state")),
        head=_optional_text(payload.get("headRefName")),
        merge_state=_optional_text(payload.get("mergeStateStatus")),
    )


def default_coord_reader(repo: Path) -> CoordState:
    """Read non-expired Hapax cc-active-task claim files.

    ``repo`` is accepted for the reader protocol; claim files are global to the
    local Hapax coordination plane rather than repository-local.
    """

    del repo
    claim_dir = Path(os.environ.get("HAPAX_CC_CLAIMS_DIR", str(Path.home() / ".cache/hapax")))
    if not claim_dir.is_dir():
        return CoordState()

    now_epoch = datetime.now().timestamp()
    ttl = _claim_lease_seconds()
    entries: list[str] = []
    for path in sorted(claim_dir.glob("cc-active-task-*")):
        if not path.is_file() or _is_expired_claim(path, now_epoch=now_epoch, ttl_seconds=ttl):
            continue
        task_id = _first_line(path)
        if not task_id:
            continue
        claim_key = path.name.removeprefix("cc-active-task-")
        entries.append(f"{claim_key}={task_id}")
    return CoordState(active_claims=tuple(entries))


def default_cc_task_reader(repo: Path, coord: CoordState) -> CcTaskState:
    """Read cc-task status for the best-matching active claim."""

    del repo
    task_id = _choose_current_task_id(coord)
    if task_id is None:
        return CcTaskState()
    task_root = Path(os.environ.get("HAPAX_CC_TASK_ROOT", str(DEFAULT_TASK_ROOT))).expanduser()
    note = _find_task_note(task_root, task_id)
    if note is None:
        return CcTaskState(task_id=task_id)
    frontmatter, _body = parse_frontmatter(note)
    status = _optional_text(frontmatter.get("status"))
    return CcTaskState(task_id=task_id, status=status)


def _coerce_model[T: BaseModel](model: type[T], value: T | Mapping[str, Any]) -> T:
    if isinstance(value, model):
        return value
    return model.model_validate(value)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _claim_lease_seconds() -> int:
    raw = os.environ.get("HAPAX_CLAIM_LEASE_TTL_SECS")
    if raw is None:
        return DEFAULT_CLAIM_LEASE_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_CLAIM_LEASE_SECONDS


def _is_expired_claim(path: Path, *, now_epoch: float, ttl_seconds: int) -> bool:
    if ttl_seconds <= 0:
        return False
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return True
    return now_epoch - mtime > ttl_seconds


def _first_line(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _choose_current_task_id(coord: CoordState) -> str | None:
    pairs = [_split_claim_entry(entry) for entry in coord.active_claims]
    pairs = [(key, task_id) for key, task_id in pairs if task_id]
    if not pairs:
        return None

    role = (
        os.environ.get("HAPAX_AGENT_ROLE")
        or os.environ.get("CODEX_ROLE")
        or os.environ.get("CLAUDE_ROLE")
    )
    session_id = os.environ.get("HAPAX_SESSION_ID")
    preferred_keys = []
    if role and session_id:
        preferred_keys.append(f"{role}-{session_id}")
    if role:
        preferred_keys.append(role)

    for preferred in preferred_keys:
        for key, task_id in pairs:
            if key == preferred:
                return task_id

    unique_task_ids = sorted({task_id for _key, task_id in pairs})
    if len(unique_task_ids) == 1:
        return unique_task_ids[0]
    return None


def _split_claim_entry(entry: str) -> tuple[str, str]:
    if "=" in entry:
        key, task_id = entry.split("=", 1)
        return key.strip(), task_id.strip()
    stripped = entry.strip()
    return stripped, stripped


def _find_task_note(task_root: Path, task_id: str) -> Path | None:
    for subdir in ("active", "closed"):
        directory = task_root / subdir
        if not directory.is_dir():
            continue
        exact = directory / f"{task_id}.md"
        if exact.is_file():
            return exact
        matches = sorted(directory.glob(f"{task_id}-*.md"))
        if matches:
            return matches[0]
    return None


# Pydantic invokes validators dynamically during model construction; the unused
# function gate is static, so keep explicit references near the export surface.
_DYNAMIC_ENTRYPOINTS = (
    GitState._nonblank_commits,
    PrState._consistent_optional_pr,
    CoordState._nonblank_claims,
    CcTaskState._status_requires_task,
    GroundTruthSnapshot._captured_at_is_aware,
)


__all__ = [
    "CcTaskReader",
    "CcTaskState",
    "CoordReader",
    "CoordState",
    "GitReader",
    "GitState",
    "GroundTruthSnapshot",
    "PrReader",
    "PrState",
    "default_cc_task_reader",
    "default_coord_reader",
    "default_git_reader",
    "default_pr_reader",
    "read_ground_truth",
]
