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
    return _hold(lock_path(task_id, cache_dir), f"cc-task lock for '{task_id}'", timeout)


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
    return _hold(role_lock_path(role, cache_dir), f"cc-task role lock for '{role}'", timeout)


def _hold(path: Path, description: str, timeout: float | None) -> Path:
    timeout = resolved_timeout(timeout)
    deadline = time.monotonic() + timeout
    handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
