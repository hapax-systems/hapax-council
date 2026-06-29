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
``abandoned``. A merged worktree is ``done`` even with a live process; a live owner is ``active``.
Within the freshness window (heartbeat/mtime activity newer than the abandoned threshold) a non-live lane
is ``merging`` if it has an open PR (idle owner mid-flight on it) else ``active``. Past the window with no
live owner the session has STOPPED, so the lane is ``abandoned`` REGARDLESS of any (stale) PR — abandonment
is HEARTBEAT-DRIVEN and gh-INDEPENDENT, so it holds on the production timer that runs without a GH_TOKEN.
Reaping (``is_reapable``) acts ONLY on ``done``/``abandoned`` — never on a paused ``active`` or
follow-through (fresh) ``merging`` lane; the checkout reap keeps the branch + PR.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

Status = Literal["infra", "active", "merging", "abandoned", "done"]

# A worktree with no live process, no open PR, and no activity (heartbeat OR mtime) newer than this
# is "abandoned". Deliberately generous (12h, not 1h) so a paused-mid-work session — operator at
# lunch, a lane between commits — is NOT misread as abandoned; the automatic reaper passes an even
# longer --min-idle-hours window. The live-process check is the primary, instantaneous guard.
DEFAULT_ABANDONED_AFTER_S = 12 * 3600


@dataclass
class WorktreeRecord:
    """One registered worktree. ``path`` is the identity (registry is keyed by it).

    Plain stdlib dataclass (NOT pydantic) on purpose: the record + reap path must be callable from the
    systemd GC reaper using the bare system ``python3``, which has no project venv. JSON (de)serialized
    by hand below with ISO-8601 datetimes."""

    path: str
    created_at: datetime
    last_heartbeat: datetime
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
    host: str | None = None
    note: str | None = None


def _record_from_json(raw: str) -> WorktreeRecord:
    d = json.loads(raw)
    return WorktreeRecord(
        path=d["path"],
        created_at=datetime.fromisoformat(d["created_at"]),
        last_heartbeat=datetime.fromisoformat(d["last_heartbeat"]),
        branch=d.get("branch"),
        role=d.get("role"),
        session_id=d.get("session_id"),
        task_id=d.get("task_id"),
        pr=d.get("pr"),
        status=d.get("status", "active"),
        pinned=bool(d.get("pinned", False)),
        host=d.get("host"),
        note=d.get("note"),
    )


def _record_to_json(rec: WorktreeRecord) -> str:
    d = asdict(rec)
    d["created_at"] = rec.created_at.isoformat()
    d["last_heartbeat"] = rec.last_heartbeat.isoformat()
    return json.dumps(d, indent=2, sort_keys=True)


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


class CorruptRecordError(Exception):
    """A registry record file EXISTS but cannot be parsed. Callers must FAIL CLOSED on it: never
    overwrite it with a derived status (that would silently drop a pin) and never treat the worktree as
    reapable. Distinct from an ABSENT record (no file), which legitimately means "not registered"."""


def _read_record(path: str) -> tuple[WorktreeRecord | None, bool]:
    """Read a record, distinguishing ABSENT ((None, False): no file) from CORRUPT ((None, True): file
    present but unparseable). Conflating the two is the fail-OPEN hole: a corrupt PINNED record read as
    'absent' lets backfill overwrite the pin and the legacy sweep reap the lane. Warns on corruption."""
    rp = record_path(path)
    try:
        raw = rp.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, False
    try:
        return _record_from_json(raw), False
    except Exception as exc:
        print(
            f"hapax-worktree-registry: WARN unparseable record {rp}: {exc} — fail-closed (the worktree "
            f"stays PROTECTED from inference reaping until repaired). Next: inspect the file; if stale, "
            f"`rm {rp}` then `hapax-worktree-register backfill`.",
            file=sys.stderr,
        )
        return None, True


def load(path: str) -> WorktreeRecord | None:
    """Best-effort read: the record, or None if ABSENT or CORRUPT (corruption is warned). Callers that
    must fail closed on corruption (``register``, ``probe_worktree``) use ``_read_record`` to tell the
    two apart — heartbeat/set_status return None on corrupt, a safe no-op that never clobbers the pin."""
    return _read_record(path)[0]


def save(rec: WorktreeRecord) -> None:
    rp = record_path(rec.path)
    data = _record_to_json(rec)
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
    existing, corrupt = _read_record(path)
    if corrupt:
        # Fail CLOSED: a present-but-corrupt record may hold a pin. Overwriting it with a derived status
        # (what backfill passes) would silently drop that pin — the exact fail-open the lifecycle
        # predicate forbids. Refuse; the caller (backfill) skips it so it stays protected, or an operator
        # repairs it. heartbeat/set_status already no-op on corrupt (load -> None), preserving the file.
        raise CorruptRecordError(
            f"refusing to overwrite a corrupt registry record for {path}: repair it first "
            f"(`rm {record_path(path)}` then re-register) so a pin is never silently dropped"
        )
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
    """All parseable records. Corrupt files are skipped with a per-file warning AND an aggregate count
    (not silently), so a corrupt record is never invisible to a caller of this function — callers that
    must *act* on corruption use ``_read_record`` per path."""
    out: list[WorktreeRecord] = []
    corrupt = 0
    for fp in sorted(registry_dir().glob("*.json")):
        try:
            out.append(_record_from_json(fp.read_text(encoding="utf-8")))
        except Exception as exc:
            corrupt += 1
            print(
                f"hapax-worktree-registry: WARN skipping corrupt record {fp}: {exc}",
                file=sys.stderr,
            )
    if corrupt:
        print(
            f"hapax-worktree-registry: WARN list_records skipped {corrupt} corrupt record(s) "
            f"(fail-closed: they stay protected; repair with `rm` + `backfill`)",
            file=sys.stderr,
        )
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
    """Derive explicit status, HEARTBEAT-DRIVEN and gh-INDEPENDENT. Order: infra and merged are
    terminal; a live owner is ``active``. Within the freshness window (heartbeat/mtime activity newer
    than ``abandoned_after_s``) a non-live lane is ``merging`` if it has an open PR (idle owner mid-flight
    on it) else ``active``. Past the window with no live owner the session has STOPPED, so the lane is
    ``abandoned`` REGARDLESS of the PR signal — this is the operator's model (``abandoned`` = stale
    heartbeat AND dead owner AND (no PR OR *stale PR*)), and reaping the checkout is non-destructive (the
    branch + PR survive ``git worktree remove``). Driving abandonment off the heartbeat, not the open-PR
    set, is what makes the exit predicate hold on the production timer, which runs WITHOUT a GH_TOKEN: a
    stopped non-merged lane flips to abandoned and is reaped even when ``has_open_pr`` is unknowable."""
    if is_infra:
        return "infra"
    if merged:
        return "done"
    if live:
        return "active"
    fresh = heartbeat_age_s is not None and heartbeat_age_s < abandoned_after_s
    if fresh:
        return "merging" if has_open_pr else "active"
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


def is_inference_protected(status: Status, *, pinned: bool) -> bool:
    """Whether the legacy ``hapax-worktree-gc.sh`` age+clean+merged INFERENCE sweep must keep its hands
    off a REGISTERED worktree. The registry — explicit lifecycle status — is authoritative for the
    durable timer: an explicit pin, or an in-use status (``infra``/``active``/``merging``), is never
    overridden by inference. ``done``/``abandoned`` are NOT inference-protected — the legacy sweep may
    still reap a merged ``done`` checkout and delete its merged branch (the registry reaper keeps
    branches; the legacy sweep proves content-is-in-base first). Counterpart to ``is_reapable``:
    ``is_reapable`` says what the REGISTRY reaper removes; this says what the legacy sweep must not."""
    return pinned or status in ("infra", "active", "merging")


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
    # --no-optional-locks (= GIT_OPTIONAL_LOCKS=0): a plain `git status` REFRESHES the index stat cache
    # ON DISK, bumping the index file's mtime. The reap path reads that mtime as an activity signal
    # (mtime_age_seconds), so without this flag every 6h GC probe would reset the idle clock and a
    # genuinely-abandoned lane would NEVER age to the --min-idle-hours threshold. This flag makes the
    # status read non-mutating, so only real work (commits, edits) advances the idle clock.
    res = _git(
        worktree_path, "--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=all"
    )
    return res.returncode == 0 and res.stdout.strip() == ""


def _branch_remote_deleted(canonical: str, branch: str) -> bool:
    """Port of the legacy GC guard: the branch was pushed AS ``origin/<name>`` (its upstream remote is
    ``origin`` AND its merge ref is ``refs/heads/<name>``) AND that remote-tracking ref is now GONE
    (GitHub auto-deleted on merge + pruned). The merge-ref guard avoids a data-loss false positive for a
    branch that merely TRACKS a different ref (e.g. created off ``origin/main``), which never had an
    ``origin/<name>`` ref to delete."""
    name = branch.removeprefix("refs/heads/")
    if not name or name.startswith("detached:"):
        return False
    if _git(canonical, "config", "--get", f"branch.{name}.remote").stdout.strip() != "origin":
        return False
    merge_ref = _git(canonical, "config", "--get", f"branch.{name}.merge").stdout.strip()
    if merge_ref != f"refs/heads/{name}":
        return False
    return (
        _git(
            canonical, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}"
        ).returncode
        != 0
    )


def _branch_content_merged(canonical: str, branch: str, base_ref: str) -> bool:
    """Port of the legacy GC content gate: True iff merging ``branch`` into ``base_ref`` adds NOTHING —
    the merged tree equals base's own tree. POSITIVE evidence that a squash/rebase merge already landed
    the content (ancestry cannot see that). A branch with real unique commits yields a different tree
    (or a conflict, nonzero exit) and is NOT content-merged, so unmerged work is never classed done."""
    base_tree = _git(
        canonical, "rev-parse", "--verify", "--quiet", f"{base_ref}^{{tree}}"
    ).stdout.strip()
    if not base_tree:
        return False
    res = _git(canonical, "merge-tree", "--write-tree", base_ref, branch)
    if res.returncode != 0:  # nonzero exit = the merge conflicts => not cleanly contained
        return False
    merged_tree = res.stdout.split("\n", 1)[0].strip()
    return bool(merged_tree) and merged_tree == base_tree


def is_merged(canonical: str, branch: str, base_ref: str = "origin/main") -> bool:
    """Whether the branch's work is already in base, so removing its checkout loses nothing. Detects
    BOTH (a) merge-commit / fast-forward merges via ancestry, AND (b) SQUASH/REBASE merges — the
    council's DEFAULT, which break ancestry — via the same evidence the legacy GC uses: the remote
    branch was auto-deleted+pruned AND the branch's content is positively present in base. Without (b),
    a squash-merged stale lane mis-classifies as ``merging`` (kept) when gh is down, and the round-6
    registry gate would then mask it from the legacy sweep — regressing cleanup for squash merges."""
    if not branch:
        return False
    if _git(canonical, "merge-base", "--is-ancestor", branch, base_ref).returncode == 0:
        return True
    return _branch_remote_deleted(canonical, branch) and _branch_content_merged(
        canonical, branch, base_ref
    )


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
    reads ``active``. ``open_pr_branches=None`` means the PR signal is UNAVAILABLE (gh down): ``has_pr``
    is then False and abandonment falls back to the HEARTBEAT — a stale, non-live lane is abandoned even
    without gh (the production timer path). A CORRUPT record (present but unparseable) fails closed: the
    worktree is returned registered + pinned + ``corrupt=True`` so it is protected and never reaped on a
    guess. Keys: path, branch, infra, live, clean, merged, has_pr,
    status, pinned, registered, corrupt."""
    real = os.path.realpath(path)
    if not os.path.isdir(real):
        return None
    rec, corrupt = _read_record(real)
    live_fn = live_count_fn if live_count_fn is not None else live_process_count
    infra = is_infra_path(real, canonical=canonical)
    live = live_fn(real) > 0
    # Capture the mtime-based idle age BEFORE is_clean(): is_clean() already uses --no-optional-locks so
    # `git status` cannot rewrite the index mtime, but reading the staleness signal first is belt-and-
    # suspenders — no status read this probe makes can advance the idle clock it then classifies on.
    now = now_epoch if now_epoch is not None else datetime.now(UTC).timestamp()
    mtime_age = mtime_age_seconds(real, now_epoch=now)
    clean = is_clean(real)
    merged = is_merged(canonical, branch) if branch else False
    pr_signal_available = open_pr_branches is not None
    has_pr = bool(pr_signal_available and branch and branch in open_pr_branches)
    if corrupt:
        # FAIL CLOSED: the record exists but we cannot read its (possibly pinned) status. Treat the
        # worktree as registered + PROTECTED (pinned) + non-reapable until repaired — never reap on a
        # guess. `status="active"` is the safe non-reapable default; `corrupt` is the real reason.
        return {
            "path": real,
            "branch": branch,
            "infra": infra,
            "live": live,
            "clean": clean,
            "merged": merged,
            "has_pr": has_pr,
            "status": "active",
            "pinned": True,
            "registered": True,
            "corrupt": True,
        }
    ages = [mtime_age]
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
        "corrupt": False,
    }
