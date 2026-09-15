"""The one mutual-exclusion primitive for cc-task note mutation.

``cc-close`` reads a note, validates it, rewrites it into ``closed/`` and unlinks
the original. ``cc-claim`` reads a note, decides eligibility, rewrites it in place
and writes lease files. Neither excluded the other, so an interleaving destroyed
work: with a concurrent resume landing between cc-close's read and its unlink,
cc-close wrote its stale ``withdrawn`` snapshot into ``closed/`` and deleted the
resumed active note.

Review round 13 on PR #4668 named that critical, correctly, and asked for
validation "under the shared mutation lock" — "the same lock cc-claim uses".
**There was no such lock.** cc-claim writes atomically (tmp + ``os.replace``),
which makes each write all-or-nothing and says nothing about two writers
interleaving. Atomic replacement is not mutual exclusion; this module is the
missing half, and both writers take it.

Why ``flock`` and not a lock file carrying a pid: the kernel drops a ``flock`` when
the holding process exits, however it exits. A pid-bearing lock file needs a
staleness rule, a staleness rule is a second mechanism for the same hazard, and
every staleness rule is a guess about a pid that may have been recycled. A lock
with no stale state needs no reaper.

**Advisory, and only over the writers that take it.** A hand edit of the note in a
text editor takes nothing and is excluded by nothing. That is a limit of the
mechanism, not a hole to patch with a second one: the governed writers are the
population this covers, and they are the ones that run unattended.

Keyed by TASK ID, not by note path, because the path is exactly what cc-close
changes — a lock on ``active/<id>.md`` would be released by the very move it
exists to protect.

Held for the life of the acquiring process rather than a scoped block, because
both callers are bash-hosted: cc-close takes it in the shell (``exec 9>`` plus
``flock(1)``) so the writer heredoc AND the lease sweep that follows it inherit
one lock, and cc-claim takes it at the top of its mutating heredoc. Neither has a
place to put a ``finally``. Process exit is the release, and it is the one release
that cannot be skipped.
"""

from __future__ import annotations

import errno
import fcntl
import math
import os
import time
from pathlib import Path

#: Seconds to wait for a contended lock before refusing. Every holder's critical
#: section is a handful of file operations, so a wait this long means something is
#: wedged rather than busy, and a refusal that names its cause beats a hang.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Operator override for the wait, in seconds. Bounds the wait; it cannot disable
#: the lock, because a knob that skipped acquisition would be a documented way to
#: reintroduce the interleaving this module exists to exclude. A malformed or
#: non-positive value is ignored rather than honoured — "wait zero seconds" is a
#: plausible typo and would turn every contended close into a refusal.
TIMEOUT_ENV = "HAPAX_CC_TASK_LOCK_TIMEOUT_SECONDS"


def resolved_timeout(timeout: float | None) -> float:
    """The wait, from an explicit argument or the environment, with the default.

    Public because cc-close resolves the same knob from bash and must not
    re-implement it: a shell `case` pattern accepted `0.00` and `1.5.0` where this
    falls back to the default, so the two writers disagreed about a value the
    runbook described as shared.
    """
    if timeout is not None:
        return timeout
    raw = (os.environ.get(TIMEOUT_ENV) or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return DEFAULT_TIMEOUT_SECONDS
        # Finite AND positive. `inf` parses, is greater than zero, and would make
        # the wait unbounded — which is the hang this function's whole shape exists
        # to avoid. `nan` fails the comparison and falls through anyway; saying so
        # explicitly keeps the predicate readable.
        if math.isfinite(value) and value > 0:
            return value
    return DEFAULT_TIMEOUT_SECONDS


def lock_dir(cache_dir: Path | None = None) -> Path:
    """Where the lock files live: under the SAME root as the resources they protect.

    Runtime state, so the runtime cache — never the vault. A lock file in the vault
    would sync to Obsidian, show up in git status, and be enumerated by every check
    that walks the task directories.

    **Keyed on ``$HOME``, deliberately NOT on ``XDG_CACHE_HOME``.** This read
    ``XDG_CACHE_HOME or ~/.cache`` for two rounds, and all four reviewer families
    independently reported the same consequence: the protected resources do not
    follow that variable. ``cc-claim`` writes and ``cc-close`` globs
    ``$HOME/.cache/hapax/cc-active-task-*`` with ``$HOME`` hardcoded, so two writers
    sharing a ``$HOME`` but exporting different ``XDG_CACHE_HOME`` values took
    DIFFERENT locks over the SAME lease files — no mutual exclusion at all, which is
    the entire thing this module exists to provide. A relative value made it worse
    still: the lock path became cwd-dependent within one process tree.

    A lock namespace must be a function of the resource namespace. Honouring an
    environment variable the resource ignores is not configurability; it is a second
    namespace pretending to be the first.

    If the lease location ever becomes XDG-aware, this moves with it — together, in
    one edit, because they are one decision.
    """
    if cache_dir is not None:
        directory = Path(cache_dir)
        if not directory.is_absolute():
            # A relative override is cwd-dependent, so two processes in one tree
            # resolve it differently and neither is wrong. Refuse rather than pick.
            raise ValueError(f"cc-task lock directory must be an absolute path, got {directory!r}")
        return directory
    return Path.home() / ".cache" / "hapax" / "cc-task-locks"


def _safe_name(task_id: str) -> str:
    """A task id rendered as exactly one path segment.

    Task ids are already slug-shaped, so this changes nothing in practice. It is
    total rather than trusting, because a lock that silently escaped its directory
    would serialize the wrong thing and report success.
    """
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in task_id) or "_"


def lock_path(task_id: str, cache_dir: Path | None = None) -> Path:
    """The lock file for ``task_id``, with its directory created.

    In a ``tasks/`` subdirectory, and role locks in ``roles/``, because the two
    namespaces must be DISJOINT and a naming convention inside one directory is not.
    The first cut prefixed role locks with ``role-``, which collides exactly:
    ``lock_path("role-eta")`` and ``role_lock_path("eta")`` both resolved to
    ``role-eta.lock``, so a task actually named ``role-eta`` claimed by role ``eta``
    took the task lock and then timed out waiting for the same inode through a
    second descriptor — a self-deadlock, reproduced in review round 17. Any prefix
    scheme has such a task id; a separate directory has none.
    """
    directory = lock_dir(cache_dir) / "tasks"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{_safe_name(task_id)}.lock"


def role_lock_path(role: str, cache_dir: Path | None = None) -> Path:
    """The lock file for a ROLE's lease namespace, with its directory created.

    A second lock because there is a second resource, not because one lock proved
    weak. The note is keyed by task id; the lease files are keyed by
    ``<role>[-<session>]``, and cc-close's role-wide sweep and cc-claim's
    publication both write that namespace. Keying their exclusion by task id
    excludes nothing: review round 16 reproduced cc-close closing task A, reading a
    marker that named A, and deleting the file after cc-claim had already
    republished it as task B under B's own — different — task lock.

    **Lock order is task, then role.** Both writers take them in that order and
    neither takes them in the other, which is what makes two locks safe rather than
    a deadlock waiting for load. Nothing takes the role lock alone.

    In ``roles/``, disjoint from ``tasks/`` by directory rather than by prefix — see
    :func:`lock_path` for the collision a prefix produced.
    """
    directory = lock_dir(cache_dir) / "roles"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{_safe_name(role)}.lock"


# --- `held_task_locks`: REMOVED, deliberately ---------------------------------
# A "is anyone mid-mutation right now" probe lived here for one round, for the
# all-tasks recovery that could not name its resources in advance. It acquired each
# lock non-blockingly and RELEASED it before returning, so it answered a question
# about the past: a closer could take its locks immediately afterwards and archive a
# stale snapshot over the recovered note. Check-then-use, which is the exact shape
# this module exists to eliminate — reintroduced in the one place it was hardest to
# see, and caught in review round 22.
#
# It is gone rather than hardened because the premise was wrong: the set IS
# enumerable. An interrupted journal names its own task and role in its manifest, so
# cc-claim now recovers per task under that task's lock. A probe cannot be made into
# a hold; only naming the resource can.


class TaskLockTimeout(RuntimeError):
    """The lock could not be taken within the timeout."""


def hold_task_note_lock(
    task_id: str,
    *,
    cache_dir: Path | None = None,
    timeout: float | None = None,
) -> Path:
    """Take the exclusive lock for ``task_id`` and hold it until this process exits.

    The file descriptor is deliberately never closed: that is what makes the hold
    last, and the kernel releases it on exit by any path including a crash. Returns
    the lock path so a caller can name it in a message.

    Raises :class:`TaskLockTimeout` rather than blocking forever — a caller that
    cannot serialize must refuse rather than proceed, and a refusal has to be able
    to say what it is waiting on.
    """
    return _acquire(
        (_TASK_RANK, task_id),
        lock_path(task_id, cache_dir),
        f"cc-task lock for '{task_id}'",
        timeout,
    )


def hold_role_lease_lock(
    role: str,
    *,
    cache_dir: Path | None = None,
    timeout: float | None = None,
) -> Path:
    """Take the exclusive lock for ``role``'s lease namespace, held until exit.

    Take it AFTER the task lock, never before and never alone — see
    :func:`role_lock_path` for why there are two and why the order is what keeps
    them safe.
    """
    return _acquire(
        (_ROLE_RANK, role),
        role_lock_path(role, cache_dir),
        f"cc-task role lock for '{role}'",
        timeout,
    )


def journal_owners(
    transaction_root: Path, *, task_id: str | None = None
) -> tuple[set[tuple[str, str]], list[str]]:
    """``{(task_id, role)}`` per interrupted claim-publication journal, plus refusals.

    A journal says whose note and whose leases a recovery will rewrite. The CALLER's
    role does not: ``recover_claim_publications`` writes ``intent.role``, so a beta
    shell recovering an eta journal must hold eta's lock, not beta's.

    A journal that does not declare BOTH a readable task and a readable role is
    returned as a refusal rather than an owner. Recovering it would rewrite some
    role's leases with no way to name the lock that protects them, and guessing the
    caller's role is precisely the defect.

    Refusals carry ``(task_id_or_None, message)`` so a caller can exclude exactly the
    affected task and still recover the others. A blanket refusal would take out
    unrelated recoveries — and, on the automatic path, block a legitimate claim —
    for one unreadable file; fail-closed means "do not act on what you cannot name",
    not "do nothing at all".

    Every container is type-checked, not merely JSON-decoded: ``{"intent":
    ["malformed"]}`` is valid JSON whose ``intent`` has no ``.get``, and an
    AttributeError there would replace a named refusal with a traceback (review
    round 24).
    """
    import json

    root = Path(transaction_root)
    owners: set[tuple[str, str]] = set()
    refusals: list[tuple[str | None, str]] = []
    if not root.is_dir():
        return owners, refusals
    for entry in sorted(root.iterdir()):
        manifest = entry / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            document = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            refusals.append((None, f"{manifest}: {type(exc).__name__}: {exc}"))
            continue
        if not isinstance(document, dict):
            refusals.append(
                (None, f"{manifest}: top level is {type(document).__name__}, not a mapping")
            )
            continue
        intent = document.get("intent")
        if not isinstance(intent, dict):
            refusals.append(
                (None, f"{manifest}: 'intent' is {type(intent).__name__}, not a mapping")
            )
            continue
        owner_task = str(intent.get("task_id") or "").strip()
        owner_role = str(intent.get("role") or "").strip()
        if task_id is not None and owner_task and owner_task != task_id:
            continue
        if not owner_task:
            refusals.append((None, f"{manifest}: declares no task_id"))
            continue
        if not owner_role:
            refusals.append((owner_task, f"{manifest}: declares no role for task '{owner_task}'"))
            continue
        owners.add((owner_task, owner_role))
    return owners, refusals


def hold_journal_locks(
    transaction_root: Path,
    *,
    task_id: str | None = None,
    also_tasks: tuple[str, ...] = (),
    timeout: float | None = None,
    passes: int = 8,
) -> tuple[set[tuple[str, str]], list[str]]:
    """Hold a lock for every journal owner, RE-DISCOVERING until the set stops growing.

    Discovering owners and then locking them is not enough: recovery enumerates the
    journals again, so a publisher that already held a task lock can leave a NEW
    journal for another role before releasing it, and that journal would then be
    recovered with no lock on the leases it rewrites (review round 24).

    Locks are held to process exit and the owner set only ever grows, so re-scanning
    after each acquisition reaches a fixpoint. `passes` bounds it: a set that will
    not settle means journals are being published faster than they can be locked,
    and the caller must refuse rather than keep chasing.

    **The task set reaches its fixpoint before ANY role lock is taken.** The earlier
    shape interleaved them — task(t1), role(eta), then task(t2) on the next pass —
    which honours the task-before-role order only WITHIN one pass. Across passes it
    produces exactly the cycle the order exists to forbid: a cc-close holding
    task(t2) and waiting on role(eta) deadlocks against this process holding
    role(eta) and waiting on task(t2) (review round 25, reproduced with competing
    flock holders). Two phases, each its own fixpoint, restore the guarantee for
    the whole acquisition rather than for each step of it.

    A journal that appears after the role phase has begun cannot be ordered, and
    :func:`_acquire` refuses it by name rather than deadlocking. That refusal is a
    rerun, not a failure: the second run discovers it during the task phase.

    Returns the locked owners and any journals refused as unattributable.
    """
    locked_tasks: set[str] = set()
    owners: set[tuple[str, str]] = set()
    refusals: list[str] = []

    # PHASE 1 — task locks only, to a fixpoint. Nothing is held that a task lock
    # may not be awaited behind, so a slow acquisition here cannot close a cycle.
    settled = False
    for _pass in range(passes):
        owners, refusals = journal_owners(transaction_root, task_id=task_id)
        want_tasks = {t for (t, _r) in owners} | set(also_tasks)
        if want_tasks <= locked_tasks:
            settled = True
            break
        for task in sorted(want_tasks - locked_tasks):
            hold_task_note_lock(task, timeout=timeout)
            locked_tasks.add(task)
    if not settled:
        raise TaskLockTimeout(
            f"claim-publication journals kept naming new tasks while locking them "
            f"({passes} passes); another publisher is writing faster than this "
            "recovery can take the locks that protect what it would rewrite"
        )

    # PHASE 2 — role locks, also to a fixpoint. A role discovered here is still
    # ordered correctly (roles sort after every task). A new TASK discovered here
    # is not, and `_acquire` raises TaskLockOrderViolation rather than taking it.
    locked_roles: set[str] = set()
    for _pass in range(passes):
        owners, refusals = journal_owners(transaction_root, task_id=task_id)
        late_tasks = ({t for (t, _r) in owners} | set(also_tasks)) - locked_tasks
        if late_tasks:
            # Refuse, don't ignore. Silently proceeding would recover this task's
            # journal with nothing holding its note lock, which is the defect the
            # whole function exists to close; taking the lock now would acquire a
            # task lock behind a role lock, which is the cycle. Neither is
            # available, so the honest move is to name it and stop.
            raise TaskLockOrderViolation(
                f"journal(s) for task(s) {sorted(late_tasks)} appeared after this "
                "process began taking role locks: the note lock cannot be taken "
                "now without inverting the task-before-role order. Next action: "
                "rerun — the second run discovers them before it starts. Nothing "
                "was modified"
            )
        want_roles = {r for (_t, r) in owners}
        if want_roles <= locked_roles:
            return owners, refusals
        for role in sorted(want_roles - locked_roles):
            hold_role_lease_lock(role, timeout=timeout)
            locked_roles.add(role)
    raise TaskLockTimeout(
        f"claim-publication journals kept naming new roles while locking them "
        f"({passes} passes); another publisher is writing faster than this "
        "recovery can take the locks that protect what it would rewrite"
    )


#: Every lock this PROCESS holds, path -> the descriptor holding it.
#:
#: `flock` is per open file description, not per process: two `os.open` calls on
#: one path in one process produce two descriptions that CONFLICT. So a second
#: acquisition of a lock this process already holds does not return, it waits for
#: itself until the timeout and then reports "another process has held ...", which
#: is false and unactionable. That is not hypothetical — it shipped: a normal
#: `cc-claim <task>` took the task lock, then automatic recovery took the same
#: lock again through `hold_journal_locks` and every recovery with an attributable
#: journal exited 4 blaming a writer that did not exist (review round 25,
#: reproduced against this process).
#:
#: A process cannot race itself for these locks, and they are held to exit so a
#: recorded hold never goes stale. Re-acquisition is therefore a no-op rather than
#: a conflict — which is a property of the primitive, not a special case for one
#: caller to remember.
_HELD: dict[Path, int] = {}

#: Sort rank of each lock namespace, defining ONE total order over every lock this
#: module hands out: all task locks, then all role locks, each ascending by name.
#: Acquiring strictly in ascending order is what makes a cycle impossible, and it
#: has to be enforced here because no caller can see what another caller holds.
_TASK_RANK = 0
_ROLE_RANK = 1

#: The ascending keys acquired so far, in acquisition order.
_ORDER: list[tuple[int, str]] = []


class TaskLockOrderViolation(RuntimeError):
    """A lock was requested that sorts BEFORE one this process already holds.

    Not a timeout and not contention: nothing is waiting. The caller discovered a
    resource late, and honouring it would mean acquiring out of order — which is
    exactly the cycle the order exists to prevent. The remedy is to rerun (the set
    settles) or to widen the initial discovery, never to take the lock anyway.
    """


def held_lock_order() -> tuple[tuple[int, str], ...]:
    """The keys this process holds, in acquisition order. For tests and messages."""

    return tuple(_ORDER)


def release_all_process_locks() -> None:
    """Close every held descriptor, releasing the locks — i.e. simulate exiting.

    **Production code must never call this.** Holds last until the process ends
    precisely so that no code path can decide to let go early; a caller that could
    release could also release halfway through a mutation.

    It exists because a test harness runs many logical "processes" inside one
    interpreter, and the held-lock registry is per-interpreter. Forgetting the
    registry without closing the descriptors would be worse than useless: the
    kernel would still hold the locks and the next acquisition would wait for a
    process that is the test itself — the exact defect this registry fixes. So the
    reset closes, and the two stay consistent.
    """

    while _HELD:
        _path, handle = _HELD.popitem()
        os.close(handle)
    _ORDER.clear()


def _acquire(key: tuple[int, str], path: Path, description: str, timeout: float | None) -> Path:
    if path in _HELD:
        return path
    if _ORDER and key < _ORDER[-1]:
        kind = "task" if key[0] == _TASK_RANK else "role"
        prior_kind = "task" if _ORDER[-1][0] == _TASK_RANK else "role"
        raise TaskLockOrderViolation(
            f"refusing to take the {kind} lock for '{key[1]}' while already holding "
            f"the {prior_kind} lock for '{_ORDER[-1][1]}': locks are taken in one "
            "ascending order (all tasks, then all roles) so two writers can never "
            "wait on each other. This one was discovered too late to be ordered. "
            "Next action: rerun — a journal was published while this process was "
            "taking locks, and the second run discovers it before it starts"
        )
    _hold(path, description, timeout)
    _ORDER.append(key)
    return path


def _hold(path: Path, description: str, timeout: float | None) -> Path:
    timeout = resolved_timeout(timeout)
    deadline = time.monotonic() + timeout
    handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _HELD[path] = handle
            return path
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                os.close(handle)
                raise
            if time.monotonic() >= deadline:
                os.close(handle)
                raise TaskLockTimeout(
                    f"another process has held the {description} ({path}) for more "
                    f"than {timeout:g}s"
                ) from exc
            time.sleep(0.05)
