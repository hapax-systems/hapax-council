"""PR registry: explicit, owned lifecycle status for GitHub pull requests.

A PR is the one in-flight work-unit the spine never captured. Worktrees got a
registry (:mod:`shared.worktree_registry`) with a DERIVED total status + a reaper
(``hapax-lane-reaper``); PRs got only a *merger* (``cc-pr-autoqueue``) and no
*reaper* — so an unowned/unworked PR keeps the ``open`` status GitHub hands it,
which the spine never reconciles, and orphaned PRs accumulate (49 of them, the
2026-07-02 pile-up). This module is the PR half of Totality obligation **T1**:
a record per PR carrying an EXPLICIT status keyed to a cc-task, a **total**
derived ``classify_pr`` (heartbeat/task-driven, gh-INDEPENDENT so it runs under
the bare ``python3`` reaper with no ``GH_TOKEN``), and ``is_reapable_pr`` that
fires ONLY on explicit terminal status — never on inference.

It is the exact mirror of :mod:`shared.worktree_registry` for the PR unit type;
the slice-2 reaper (``hapax-pr-reaper``) consumes it. This slice adds NO GitHub
calls and NO reaper — the status model + its tests only.

Record store: one atomic JSON file per PR under ``$HAPAX_PR_REGISTRY_DIR``
(default ``~/.cache/hapax/pr-registry``), keyed by a slug of ``(repo, number)``.
``(repo, number)`` is identity so two repos' PRs never collide (multi-repo
capture). ``task_id`` is the JOIN key to ``WorktreeRecord.task_id`` — a PR and
its worktree are two faces of one owned work-unit.

Status lattice (``classify_pr``), fail-closed toward KEEP on ambiguity:
  ``done`` (merged) and ``closed`` (closed-unmerged) are GitHub-terminal; a bot
  PR is ``mergeable_ownerless`` (green+mergeable -> autoqueue merges, no cc-task)
  or ``bot_blocked``; a live owner is ``active``; an unresolvable owner is
  ``indeterminate`` (the explicit bottom ``⊥_PR`` — join-failure is NOT
  owner-death, so it is PROTECTED, never reaped on a guess); only a POSITIVELY
  dead owner (closed/missing task) past the idle window with no live owner is
  ``abandoned``/``orphaned`` and hence reapable. Reaping a PR is ``gh pr close``,
  which is non-destructive — the branch + commits survive.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

#: Derived spine status for a PR. ``done``/``closed`` are GitHub-terminal;
#: ``abandoned``/``orphaned`` are open-but-reapable; ``indeterminate`` is the
#: explicit bottom (⊥_PR) — protected, never reaped on a guess.
PrStatus = Literal[
    "active",
    "merging",
    "done",
    "closed",
    "abandoned",
    "orphaned",
    "mergeable_ownerless",
    "bot_blocked",
    "indeterminate",
]

#: The owning cc-task's status, bucketed by the caller from the
#: :mod:`shared.sdlc_lifecycle` frozensets. ``unresolvable`` means the owner
#: could not be determined (gh down / ambiguous) — NOT that it is dead.
OwnerTaskStatus = Literal["mutable", "merge_ready", "closed", "missing", "unresolvable"]

#: GitHub-terminal statuses — the PR object is already resolved.
TERMINAL_PR_STATUSES: frozenset[PrStatus] = frozenset({"done", "closed"})

#: Open statuses the reaper may CLOSE (``gh pr close``). Only explicit dead-owner
#: states — never ``active``/``merging``/``indeterminate``/bot states.
REAPABLE_PR_STATUSES: frozenset[PrStatus] = frozenset({"abandoned", "orphaned"})

# A PR whose owner is dead and whose record has not been refreshed within this
# window is stale. Generous (12h) so a paused-mid-review PR — owner at lunch,
# a lane between pushes — is NOT misread as abandoned; matches the worktree
# registry's DEFAULT_ABANDONED_AFTER_S. The live-owner check is the primary,
# instantaneous guard.
DEFAULT_ORPHANED_AFTER_S = 12 * 3600


@dataclass
class PrRecord:
    """One registered PR. ``(repo, number)`` is the identity (registry is keyed by it).

    Plain stdlib dataclass (NOT pydantic) on purpose: the record + reap path must be
    callable from the systemd reaper using the bare system ``python3``, which has no
    project venv. JSON (de)serialized by hand below with ISO-8601 datetimes."""

    repo: str
    number: int
    created_at: datetime
    last_seen: datetime
    head_ref: str | None = None
    #: JOIN key to WorktreeRecord.task_id — the owning cc-task.
    task_id: str | None = None
    #: The owning worktree's path (inverse of WorktreeRecord.pr), written eagerly
    #: so the reaper reads the PR's heartbeat via its worktree without a live join.
    worktree_path: str | None = None
    #: Provenance: a governed bot (e.g. ``dependabot[bot]``) vs a lane/human. Drives
    #: the ``mergeable_ownerless`` / ``bot_blocked`` capture path.
    author: str | None = None
    #: The remote head SHA last observed — the ahead-of-remote guard for the reaper.
    remote_tip_sha: str | None = None
    status: PrStatus = "active"
    # When True, ``status`` is an explicit operator/owner decision (set_status) that
    # is AUTHORITATIVE: a derive/refresh never re-derives a pinned record, so an
    # explicit hold/keep is never silently reaped.
    pinned: bool = False
    note: str | None = None


def _record_from_json(raw: str) -> PrRecord:
    d = json.loads(raw)
    return PrRecord(
        repo=d["repo"],
        number=int(d["number"]),
        created_at=datetime.fromisoformat(d["created_at"]),
        last_seen=datetime.fromisoformat(d["last_seen"]),
        head_ref=d.get("head_ref"),
        task_id=d.get("task_id"),
        worktree_path=d.get("worktree_path"),
        author=d.get("author"),
        remote_tip_sha=d.get("remote_tip_sha"),
        status=d.get("status", "active"),
        pinned=bool(d.get("pinned", False)),
        note=d.get("note"),
    )


def _record_to_json(rec: PrRecord) -> str:
    d = asdict(rec)
    d["created_at"] = rec.created_at.isoformat()
    d["last_seen"] = rec.last_seen.isoformat()
    return json.dumps(d, indent=2, sort_keys=True)


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


def registry_dir() -> Path:
    env = os.environ.get("HAPAX_PR_REGISTRY_DIR")
    base = Path(env) if env else Path.home() / ".cache" / "hapax" / "pr-registry"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _slug(repo: str, number: int) -> str:
    norm = re.sub(r"[^A-Za-z0-9._-]", "_", f"{repo}#{number}").strip("_")
    return norm or f"pr_{number}"


def record_path(repo: str, number: int) -> Path:
    return registry_dir() / f"{_slug(repo, number)}.json"


class CorruptRecordError(Exception):
    """A registry record file EXISTS but cannot be parsed. Callers must FAIL CLOSED on it:
    never overwrite it with a derived status (that would silently drop a pin) and never treat
    the PR as reapable. Distinct from an ABSENT record (no file), which legitimately means
    "not registered"."""


def _read_record(repo: str, number: int) -> tuple[PrRecord | None, bool]:
    """Read a record, distinguishing ABSENT ((None, False): no file) from CORRUPT ((None, True):
    file present but unparseable). Conflating the two is the fail-OPEN hole: a corrupt PINNED
    record read as 'absent' lets backfill overwrite the pin and a sweep reap the PR. Warns on
    corruption."""
    rp = record_path(repo, number)
    try:
        raw = rp.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, False
    try:
        return _record_from_json(raw), False
    except Exception as exc:
        print(
            f"hapax-pr-registry: WARN unparseable record {rp}: {exc} — fail-closed (the PR stays "
            f"PROTECTED from inference reaping until repaired). Next: inspect the file; if stale, "
            f"`rm {rp}` then re-register.",
            file=sys.stderr,
        )
        return None, True


def load(repo: str, number: int) -> PrRecord | None:
    """Best-effort read: the record, or None if ABSENT or CORRUPT (corruption is warned).
    Callers that must fail closed on corruption use ``_read_record`` to tell the two apart —
    heartbeat/set_status return None on corrupt, a safe no-op that never clobbers the pin."""
    return _read_record(repo, number)[0]


def save(rec: PrRecord) -> None:
    rp = record_path(rec.repo, rec.number)
    data = _record_to_json(rec)
    fd, tmp = tempfile.mkstemp(dir=str(rp.parent), prefix=".pr-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, rp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def register(
    repo: str,
    number: int,
    *,
    head_ref: str | None = None,
    task_id: str | None = None,
    worktree_path: str | None = None,
    author: str | None = None,
    remote_tip_sha: str | None = None,
    status: PrStatus = "active",
    now: datetime | None = None,
    last_seen: datetime | None = None,
    pinned: bool | None = None,
) -> PrRecord:
    """Create or refresh a registration. Preserves ``created_at`` across re-registration.
    A REFRESH (no explicit ``pinned``) never clobbers an explicit pin's status."""
    ts = _now(now)
    existing, corrupt = _read_record(repo, number)
    if corrupt:
        # Fail CLOSED: a present-but-corrupt record may hold a pin. Overwriting it with a derived
        # status would silently drop that pin — the exact fail-open the lifecycle predicate forbids.
        raise CorruptRecordError(
            f"refusing to overwrite a corrupt registry record for {repo}#{number}: repair it first "
            f"(`rm {record_path(repo, number)}` then re-register) so a pin is never silently dropped"
        )
    created = existing.created_at if existing else ts
    if existing is not None and existing.pinned and pinned is None:
        eff_status: PrStatus = existing.status
        eff_pinned = True
    else:
        eff_status = status
        eff_pinned = pinned if pinned is not None else (existing.pinned if existing else False)
    rec = PrRecord(
        repo=repo,
        number=number,
        created_at=created,
        last_seen=last_seen if last_seen is not None else ts,
        head_ref=head_ref if head_ref is not None else (existing.head_ref if existing else None),
        task_id=task_id if task_id is not None else (existing.task_id if existing else None),
        worktree_path=worktree_path
        if worktree_path is not None
        else (existing.worktree_path if existing else None),
        author=author if author is not None else (existing.author if existing else None),
        remote_tip_sha=remote_tip_sha
        if remote_tip_sha is not None
        else (existing.remote_tip_sha if existing else None),
        status=eff_status,
        pinned=eff_pinned,
        note=existing.note if existing else None,
    )
    save(rec)
    return rec


def heartbeat(repo: str, number: int, *, now: datetime | None = None) -> PrRecord | None:
    """Refresh ``last_seen`` (the reaper observed the PR alive). No-op on absent/corrupt."""
    rec = load(repo, number)
    if rec is None:
        return None
    rec.last_seen = _now(now)
    save(rec)
    return rec


def set_status(repo: str, number: int, status: PrStatus, *, pinned: bool = True) -> PrRecord | None:
    """Explicitly set a PR's status. ``pinned=True`` (the default) marks it AUTHORITATIVE — the
    derive/refresh will not re-derive it, so an operator/owner hold sticks until deregistered."""
    rec = load(repo, number)
    if rec is None:
        return None
    rec.status = status
    rec.pinned = pinned
    save(rec)
    return rec


def deregister(repo: str, number: int) -> None:
    rp = record_path(repo, number)
    try:
        rp.unlink()
    except FileNotFoundError:
        pass


def list_records() -> list[PrRecord]:
    """All parseable records. Corrupt files are skipped with a per-file warning AND an aggregate
    count (never silently), so a corrupt record is never invisible to a caller."""
    out: list[PrRecord] = []
    corrupt = 0
    for fp in sorted(registry_dir().glob("*.json")):
        try:
            out.append(_record_from_json(fp.read_text(encoding="utf-8")))
        except Exception as exc:
            corrupt += 1
            print(f"hapax-pr-registry: WARN skipping corrupt record {fp}: {exc}", file=sys.stderr)
    if corrupt:
        print(
            f"hapax-pr-registry: WARN list_records skipped {corrupt} corrupt record(s) "
            f"(fail-closed: they stay protected; repair with `rm` + re-register)",
            file=sys.stderr,
        )
    return out


# --- pure classifiers (the heart; unit-tested without touching gh) ------------------------------


def classify_pr(
    *,
    merged: bool,
    closed: bool,
    is_bot: bool,
    checks_green: bool,
    mergeable: bool,
    owner_task_status: OwnerTaskStatus,
    owner_live: bool,
    seen_age_s: float | None,
    orphaned_after_s: int = DEFAULT_ORPHANED_AFTER_S,
) -> PrStatus:
    """Derive a PR's explicit status. TOTAL (every input maps to a defined ``PrStatus``),
    heartbeat/task-driven and gh-INDEPENDENT, fail-closed toward KEEP on ambiguity.

    Precedence: GitHub-terminal first (``merged`` -> ``done``; ``closed`` -> ``closed``); then
    bot provenance (green+mergeable -> ``mergeable_ownerless``, else ``bot_blocked``) — a bot PR
    never needs a human owner and is never reaped. A live owner is ``active`` (the join-independent
    KEEP). An UNRESOLVABLE owner is ``indeterminate`` (⊥): join-failure is NOT owner-death, so the
    PR is protected, not reaped. Only a POSITIVELY dead owner (task ``closed``/``missing``) with no
    live owner past the idle window flips to ``abandoned``/``orphaned`` (reapable); within the
    window it is kept (``active``/``merging``), so a paused lane is never false-reaped (the
    #4383 claim-stamp-race class)."""
    if merged:
        return "done"
    if closed:
        return "closed"
    # The PR is OPEN from here.
    if is_bot:
        return "mergeable_ownerless" if (checks_green and mergeable) else "bot_blocked"
    if owner_live:
        return "active"
    if owner_task_status == "unresolvable":
        return "indeterminate"
    fresh = seen_age_s is not None and seen_age_s < orphaned_after_s
    if owner_task_status == "mutable":
        return "active" if fresh else "abandoned"
    if owner_task_status == "merge_ready":
        return "merging" if (fresh and mergeable) else ("active" if fresh else "abandoned")
    if owner_task_status == "closed":
        # Owner positively terminal: within the window give grace (active), past it reap.
        return "active" if fresh else "abandoned"
    if owner_task_status == "missing":
        # No owning task exists. Fresh -> maybe just created and not yet linked (⊥, protect);
        # stale -> a PR nobody owns (orphaned, reapable).
        return "indeterminate" if fresh else "orphaned"
    return "indeterminate"


def is_terminal_pr(status: PrStatus) -> bool:
    """The PR object is already resolved on GitHub (merged or closed). Its record may be
    deregistered; the reaper does not re-close it."""
    return status in TERMINAL_PR_STATUSES


def is_reapable_pr(status: PrStatus, *, has_unrecoverable_work: bool = False) -> bool:
    """Reap (``gh pr close``) a PR ONLY by EXPLICIT status — never by inference. Reapable iff the
    status is ``abandoned`` (dead owner, stale) or ``orphaned`` (no owner, stale), AND it does not
    hold work recoverable only from this PR's branch (the no-lossy-reap veto — closing keeps the
    branch, but if a downstream worktree GC would then delete an only-copy branch, the caller must
    pass ``has_unrecoverable_work=True`` to protect it). ``active``/``merging``/``indeterminate``
    and both bot states are KEPT; ``done``/``closed`` are already terminal. Closing a PR is
    non-destructive — the branch + commits survive."""
    return (not has_unrecoverable_work) and status in REAPABLE_PR_STATUSES
