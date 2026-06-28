"""Worktree registry: explicit, owned lifecycle status for git worktrees.

The reaper used to GUESS reapability from four weak signals (git-merged / fs-clean /
``/proc``-live / gh-PR) that cannot distinguish "paused between commits" from "session
died." So it fail-closed on the ambiguity and worktrees accumulated until the cap blocked
dispatch. This module is the "layer of indication" the operator named: a registry record
per worktree carrying an EXPLICIT status, keyed to a cc-task and refreshed by a heartbeat,
so abandoned != paused is KNOWABLE.

Record store: one atomic JSON file per worktree under ``$HAPAX_WORKTREE_REGISTRY_DIR``
(default ``~/.cache/hapax/worktree-registry``), keyed by a slug of the worktree path.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Status = Literal["infra", "active", "merging", "abandoned", "done"]

# A worktree whose owner heartbeat is older than this AND has no live process is no longer
# "being worked" — the create -> work -> destroy contract was broken.
DEFAULT_ABANDONED_AFTER_S = 3600


class WorktreeRecord(BaseModel):
    """One registered worktree. ``path`` is the identity (registry is keyed by it)."""

    path: str
    branch: str | None = None
    role: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    pr: int | None = None
    status: Status = "active"
    created_at: datetime
    last_heartbeat: datetime
    host: str | None = None
    note: str | None = None


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


def registry_dir() -> Path:
    env = os.environ.get("HAPAX_WORKTREE_REGISTRY_DIR")
    base = Path(env) if env else Path.home() / ".cache" / "hapax" / "worktree-registry"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _slug(path: str) -> str:
    norm = os.path.normpath(path)
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", norm).strip("_")
    return slug or "root"


def record_path(path: str) -> Path:
    return registry_dir() / f"{_slug(path)}.json"


def load(path: str) -> WorktreeRecord | None:
    rp = record_path(path)
    try:
        raw = rp.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        return WorktreeRecord.model_validate_json(raw)
    except Exception:
        return None


def save(rec: WorktreeRecord) -> None:
    rp = record_path(rec.path)
    data = rec.model_dump_json(indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(rp.parent), prefix=".wt-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, rp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def register(
    path: str,
    *,
    role: str | None = None,
    branch: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    pr: int | None = None,
    status: Status = "active",
    host: str | None = None,
    now: datetime | None = None,
) -> WorktreeRecord:
    """Create or refresh a registration. Preserves ``created_at`` across re-registration."""
    ts = _now(now)
    existing = load(path)
    created = existing.created_at if existing else ts
    rec = WorktreeRecord(
        path=path,
        branch=branch if branch is not None else (existing.branch if existing else None),
        role=role if role is not None else (existing.role if existing else None),
        session_id=session_id
        if session_id is not None
        else (existing.session_id if existing else None),
        task_id=task_id if task_id is not None else (existing.task_id if existing else None),
        pr=pr if pr is not None else (existing.pr if existing else None),
        status=status,
        created_at=created,
        last_heartbeat=ts,
        host=host if host is not None else (existing.host if existing else None),
    )
    save(rec)
    return rec


def heartbeat(path: str, *, now: datetime | None = None) -> WorktreeRecord | None:
    rec = load(path)
    if rec is None:
        return None
    rec.last_heartbeat = _now(now)
    save(rec)
    return rec


def set_status(path: str, status: Status) -> WorktreeRecord | None:
    rec = load(path)
    if rec is None:
        return None
    rec.status = status
    save(rec)
    return rec


def deregister(path: str) -> None:
    rp = record_path(path)
    try:
        rp.unlink()
    except FileNotFoundError:
        pass


def list_records() -> list[WorktreeRecord]:
    out: list[WorktreeRecord] = []
    for fp in sorted(registry_dir().glob("*.json")):
        try:
            out.append(WorktreeRecord.model_validate_json(fp.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


# --- pure classifiers (the heart; unit-tested without touching git/proc) ------------------------------


def is_infra_path(path: str, *, canonical: str) -> bool:
    """Permanent worktrees that must NEVER be reaped: the canonical repo, source-activation
    release snapshots, the rebuild/hooks worktree, the health-monitor source."""
    p = os.path.normpath(path)
    if p == os.path.normpath(canonical):
        return True
    if "/source-activation/releases/" in p:
        return True
    if p.endswith("/rebuild/worktree"):
        return True
    return p.endswith("/health-monitor-source")


def classify(
    *,
    is_infra: bool,
    live: bool,
    clean: bool,  # noqa: ARG001 - part of the signal contract; status doesn't gate on cleanliness
    merged: bool,
    heartbeat_age_s: float | None,
    abandoned_after_s: int,
    has_open_pr: bool,
) -> Status:
    """Derive explicit status. Order matters: infra and merged are terminal; a live owner or a
    fresh heartbeat means active; an open PR with an idle owner is mid-flight (merging); only a
    dead owner with no PR and no fresh heartbeat is abandoned."""
    if is_infra:
        return "infra"
    if merged:
        return "done"
    if live:
        return "active"
    if heartbeat_age_s is not None and heartbeat_age_s < abandoned_after_s:
        return "active"
    if has_open_pr:
        return "merging"
    return "abandoned"


def should_reap_worktree(*, is_infra: bool, live: bool, clean: bool) -> bool:
    """A checkout is disposable when nobody is editing it: not infra, no live process, and
    clean (no uncommitted work). A green PR merges server-side without its worktree, so an
    open PR does NOT protect the checkout — only an active editor (live) or unsaved work
    (dirty) does. The branch + commits survive ``git worktree remove``; only the checkout goes."""
    return (not is_infra) and (not live) and clean


# --- probes (integration: read git + /proc; exercised via the CLI on real worktrees) -----------------


def live_process_count(real_path: str, proc_root: str = "/proc") -> int:
    """Count same-user processes whose cwd/exe resolves to (or under) ``real_path``."""
    n = 0
    try:
        pids = [p for p in os.listdir(proc_root) if p.isdigit()]
    except OSError:
        return 1  # fail closed: unreadable proc -> treat as live, never reap
    for pid in pids:
        for kind in ("cwd", "exe"):
            try:
                target = os.readlink(os.path.join(proc_root, pid, kind))
            except OSError:
                continue
            target = target.removesuffix(" (deleted)")
            if target == real_path or target.startswith(real_path + "/"):
                n += 1
                break
    return n


def _git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)


def is_clean(worktree_path: str) -> bool:
    res = _git(worktree_path, "status", "--porcelain=v1", "--untracked-files=all")
    return res.returncode == 0 and res.stdout.strip() == ""


def is_merged(canonical: str, branch: str, base_ref: str = "origin/main") -> bool:
    if not branch:
        return False
    res = _git(canonical, "merge-base", "--is-ancestor", branch, base_ref)
    return res.returncode == 0


def mtime_age_seconds(path: str, *, now_epoch: float | None = None) -> float:
    """Seconds since the worktree's freshest activity signal (max of the dir, the git index, and
    HEAD mtimes). A staleness GATE for automatic reaping: combined with non-live, a worktree idle
    for many hours is abandoned, not paused. Returns inf if the path is gone (so callers reap it)."""
    candidates = [path, os.path.join(path, ".git", "index"), os.path.join(path, ".git", "HEAD")]
    newest = 0.0
    found = False
    for c in candidates:
        try:
            mt = os.path.getmtime(c)
        except OSError:
            continue
        found = True
        newest = max(newest, mt)
    if not found:
        return float("inf")
    now = now_epoch if now_epoch is not None else datetime.now(UTC).timestamp()
    return max(0.0, now - newest)
