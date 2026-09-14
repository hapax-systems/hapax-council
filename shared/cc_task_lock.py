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


def _resolved_timeout(timeout: float | None) -> float:
    if timeout is not None:
        return timeout
    raw = (os.environ.get(TIMEOUT_ENV) or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return DEFAULT_TIMEOUT_SECONDS
        if value > 0:
            return value
    return DEFAULT_TIMEOUT_SECONDS


def lock_dir(cache_dir: Path | None = None) -> Path:
    """Where the per-task lock files live.

    Runtime state, so the runtime cache — never the vault. A lock file in the vault
    would sync to Obsidian, show up in git status, and be enumerated by every check
    that walks the task directories.
    """
    if cache_dir is not None:
        return Path(cache_dir)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "hapax" / "cc-task-locks"


def _safe_name(task_id: str) -> str:
    """A task id rendered as exactly one path segment.

    Task ids are already slug-shaped, so this changes nothing in practice. It is
    total rather than trusting, because a lock that silently escaped its directory
    would serialize the wrong thing and report success.
    """
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in task_id) or "_"


def lock_path(task_id: str, cache_dir: Path | None = None) -> Path:
    """The lock file for ``task_id``, with its directory created."""
    directory = lock_dir(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{_safe_name(task_id)}.lock"


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
    timeout = _resolved_timeout(timeout)
    path = lock_path(task_id, cache_dir)
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
                    f"another process has held the cc-task lock for '{task_id}' "
                    f"({path}) for more than {timeout:g}s"
                ) from exc
            time.sleep(0.05)
