"""Worktree registry: explicit, owned lifecycle status for git worktrees.

The reaper used to GUESS reapability from four weak signals (git-merged / fs-clean /
``/proc``-live / gh-PR) that cannot distinguish "paused between commits" from "session
died." So it fail-closed on the ambiguity and worktrees accumulated until the cap blocked
dispatch. This module is the "layer of indication" the operator named: a registry record
per worktree carrying an EXPLICIT status, keyed to a cc-task and refreshed by a heartbeat,
so abandoned != paused is KNOWABLE.

Record store: one atomic JSON file per worktree under ``$HAPAX_WORKTREE_REGISTRY_DIR``
(default ``~/.cache/hapax/worktree-registry``), keyed by a slug of the worktree path.

Status precedence (``classify``, highest first): ``infra`` > ``done`` > ``active`` > ``merging`` >
``abandoned``. A merged worktree is ``done`` even with a live process; a live owner or fresh heartbeat
is ``active``; an idle owner with an open PR is ``merging``; only a dead owner with no PR and a stale
heartbeat is ``abandoned``. Reaping (``is_reapable``) acts ONLY on ``done``/``abandoned`` — never on a
paused ``active`` or follow-through ``merging`` lane.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Status = Literal["infra", "active", "merging", "abandoned", "done"]

# A worktree with no live process, no open PR, and no activity (heartbeat OR mtime) newer than this
# is "abandoned". Deliberately generous (12h, not 1h) so a paused-mid-work session — operator at
# lunch, a lane between commits — is NOT misread as abandoned; the automatic reaper passes an even
# longer --min-idle-hours window. The live-process check is the primary, instantaneous guard.
DEFAULT_ABANDONED_AFTER_S = 12 * 3600


class WorktreeRecord(BaseModel):
    """One registered worktree. ``path`` is the identity (registry is keyed by it)."""

    path: str
    branch: str | None = None
    role: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    pr: int | None = None
    status: Status = "active"
    # When True, `status` is an explicit operator/owner decision (set_status) that is AUTHORITATIVE:
    # the live-signal derive refreshes only NON-pinned records, so a pinned `infra`/`active`/`merging`
    # is never silently re-derived and reaped.
    pinned: bool = False
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
    except Exception as exc:
        # A present-but-unparseable record is a real problem (schema drift / corruption), NOT the
        # same as absent — surface it so it isn't silently masked, then treat as missing.
        print(
            f"hapax-worktree-registry: WARN unparseable record {rp}: {exc} — "
            f"Next: inspect the file; if stale, `rm {rp}` then `hapax-worktree-register backfill`.",
            file=sys.stderr,
        )
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
    last_heartbeat: datetime | None = None,
    pinned: bool | None = None,
) -> WorktreeRecord:
    """Create or refresh a registration. Preserves ``created_at`` across re-registration. ``now`` is
    the creation timestamp; ``last_heartbeat`` defaults to ``now`` but can be set to a worktree's REAL
    last-activity (e.g. its mtime) on back-fill, so a freshly-written record does not falsely look
    just-heartbeated. A REFRESH (no explicit ``pinned``) never clobbers an explicit pin's status."""
    ts = _now(now)
    existing = load(path)
    created = existing.created_at if existing else ts
    if existing is not None and existing.pinned and pinned is None:
        eff_status: Status = existing.status
        eff_pinned = True
    else:
        eff_status = status
        eff_pinned = pinned if pinned is not None else (existing.pinned if existing else False)
    rec = WorktreeRecord(
        path=path,
        branch=branch if branch is not None else (existing.branch if existing else None),
        role=role if role is not None else (existing.role if existing else None),
        session_id=session_id
        if session_id is not None
        else (existing.session_id if existing else None),
        task_id=task_id if task_id is not None else (existing.task_id if existing else None),
        pr=pr if pr is not None else (existing.pr if existing else None),
        status=eff_status,
        pinned=eff_pinned,
        created_at=created,
        last_heartbeat=last_heartbeat if last_heartbeat is not None else ts,
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


def set_status(path: str, status: Status, *, pinned: bool = True) -> WorktreeRecord | None:
    """Explicitly set a worktree's status. ``pinned=True`` (the default) marks it AUTHORITATIVE — the
    live-signal refresh will not re-derive it, so an operator/owner decision sticks until deregistered."""
    rec = load(path)
    if rec is None:
        return None
    rec.status = status
    rec.pinned = pinned
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
    pr_signal_available: bool = True,
) -> Status:
    """Derive explicit status. Order matters: infra and merged are terminal; a live owner or a fresh
    heartbeat means active; an open PR with an idle owner is mid-flight (merging); only a dead owner
    with no PR and no fresh heartbeat is abandoned. FAIL-CLOSED on the PR signal: if the open-PR set
    is unavailable (gh down/unauthed), we cannot confirm there is no PR, so an otherwise-abandoned
    worktree is treated as ``merging`` and KEPT rather than reaped on an unverified no-PR assumption."""
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
    if not pr_signal_available:
        return "merging"
    return "abandoned"


def is_reapable(status: Status, clean: bool, *, live: bool = False) -> bool:
    """Reap a checkout ONLY by EXPLICIT status — never by inference. Reapable iff status is ``done``
    (merged, work is in base) or ``abandoned`` (no live owner, no open PR, stale), AND it is clean,
    AND it is NOT live. The ``live`` gate is decisive even for ``done``: ``classify`` calls a merged
    worktree ``done`` *before* checking liveness, so a merged worktree with an active process is
    ``done`` yet must NOT be removed (someone is working in it; the merged-branch cleanup is the GC's
    job, not ours). ``active``/``merging`` (open-PR) lanes are kept; dirty worktrees are kept (unsaved
    work). The branch + commits survive ``git worktree remove``; only the checkout goes."""
    return (not live) and clean and status in ("done", "abandoned")


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


def _resolve_git_dir(path: str) -> str | None:
    """The real git dir for a worktree. In a LINKED worktree ``.git`` is a FILE
    (``gitdir: <main>/.git/worktrees/<name>``), not a directory — so ``index``/``HEAD`` live there,
    NOT under ``<path>/.git/``. Returns the resolved dir, or None if it can't be determined."""
    dotgit = os.path.join(path, ".git")
    if os.path.isdir(dotgit):
        return dotgit
    try:
        with open(dotgit, encoding="utf-8") as fh:
            first = fh.readline().strip()
    except OSError:
        return None
    if first.startswith("gitdir:"):
        gd = first[len("gitdir:") :].strip()
        return gd if os.path.isabs(gd) else os.path.normpath(os.path.join(path, gd))
    return None


def mtime_age_seconds(path: str, *, now_epoch: float | None = None) -> float:
    """Seconds since the worktree's freshest activity signal — the max mtime of the worktree dir and
    (resolving a linked-worktree ``.git`` file to its real git dir) its ``index`` + ``HEAD``. A
    staleness GATE for automatic reaping: combined with non-live, a worktree idle for many hours is
    abandoned, not paused. Returns inf if the path is gone (callers treat it as maximally stale)."""
    candidates = [path]
    git_dir = _resolve_git_dir(path)
    if git_dir:
        candidates += [os.path.join(git_dir, "index"), os.path.join(git_dir, "HEAD")]
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


def probe_worktree(
    *,
    path: str,
    branch: str | None,
    canonical: str,
    open_pr_branches: set[str] | None,
    abandoned_after_s: int = DEFAULT_ABANDONED_AFTER_S,
    live_count_fn: Callable[[str], int] | None = None,
    now_epoch: float | None = None,
) -> dict | None:
    """Derive a worktree's effective status (the real reap code path; unit-tested with an injected
    ``live_count_fn``). Returns None if the path is gone.

    Status authority: an explicit PIN in the registry (``set_status``) is AUTHORITATIVE and returned
    as-is — only NON-pinned records are refreshed from live signals. The derive folds BOTH the registry
    ``last_heartbeat`` AND the filesystem mtime (freshest wins), so a heartbeated-but-quiet session
    reads ``active``. ``open_pr_branches=None`` means the PR signal is UNAVAILABLE (gh down): the derive
    fails closed (``merging``, kept) rather than assuming no PR. Keys: path, branch, infra, live, clean,
    merged, has_pr, status, pinned."""
    real = os.path.realpath(path)
    if not os.path.isdir(real):
        return None
    live_fn = live_count_fn if live_count_fn is not None else live_process_count
    infra = is_infra_path(real, canonical=canonical)
    live = live_fn(real) > 0
    clean = is_clean(real)
    merged = is_merged(canonical, branch) if branch else False
    pr_signal_available = open_pr_branches is not None
    has_pr = bool(pr_signal_available and branch and branch in open_pr_branches)
    now = now_epoch if now_epoch is not None else datetime.now(UTC).timestamp()
    ages = [mtime_age_seconds(real, now_epoch=now)]
    rec = load(real)
    if rec is not None:
        ages.append(max(0.0, now - rec.last_heartbeat.timestamp()))
    derived = classify(
        is_infra=infra,
        live=live,
        clean=clean,
        merged=merged,
        heartbeat_age_s=min(ages),
        abandoned_after_s=abandoned_after_s,
        has_open_pr=has_pr,
        pr_signal_available=pr_signal_available,
    )
    pinned = bool(rec is not None and rec.pinned)
    status = rec.status if pinned else derived
    return {
        "path": real,
        "branch": branch,
        "infra": infra,
        "live": live,
        "clean": clean,
        "merged": merged,
        "has_pr": has_pr,
        "status": status,
        "pinned": pinned,
        "registered": rec is not None,
    }
