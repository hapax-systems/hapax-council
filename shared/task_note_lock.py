"""The one lock domain shared by every writer to a projected task-note path.

Why this module exists
----------------------
:mod:`shared.coord_projection` relocates task notes transactionally: it pins each file's
preimage, builds the postimage, and installs it atomically, serializing itself with
``flock(LOCK_EX)`` keyed by task id and by path. The ratified design treats concurrent writers
to those same paths as out of contract.

Measurement (beta, 2026-09-13T22:10Z; reproduced as codex-1's C1 on PR #4667) shows they are
not. ``cc-stage-advance``, ``cc-scope-widen``, ``cc-task-repair`` and the gate's
``_stamp_frontmatter_field`` each read-modify-write a task note taking no lock at all — and a
second search shape, over the callers of :mod:`shared.cc_task_root` rather than over the literal
vault string, adds ``cc-claim``, ``cc-close`` and ``cc-task-pr-link.sh``, three of the highest
frequency note writers in the estate. A writer that lands between the transition's preimage pin
and its install has its bytes counted by the transition's safety check and then destroyed, while
the transition is still recorded applied: fail-open, and invisible from either side.

The correction is not another guard on the transition — five mitigations against one hazard was
already the signal that the shape was wrong. It is that **the lock that guards relocation and the
lock that guards mutation are the same lock**. So this module owns the primitive and
:func:`shared.coord_projection._transition_locks` is a call into it, rather than a second
implementation that would have to agree with this one forever with nothing to detect the day it
stopped.

Stated without any estate noun: *independent mutators of a document must take the same exclusion
the document's transactional relocator takes, keyed by document identity.* What survives that
restatement is the architecture; the rest is binding. The bindings here, each swappable: the
exclusion mechanism is ``flock`` on a lock file per key; the key namespace is ``task:``/``path:``;
the digest is SHA-256; the default root is ``coord_base_dir()/task-locks``.

Three properties this primitive must have, each of which cost the estate a round to learn:

**Re-entrant.** ``flock`` is per open file description, not per process. A caller that holds a
lock and then calls something that takes the same lock — ``cc-close`` stamps the note and then
drives the terminal transition across it — blocks forever against itself and then reports a
concurrent writer that does not exist. Re-entrancy is per thread (two threads are two writers),
and the lock is released only when the outermost acquisition exits.

**Totally ordered.** Lock names are sorted before acquisition, so two callers naming overlapping
key sets in different argument orders cannot each hold one and wait for the other.

**Bounded.** Acquisition has a timeout and refuses with a typed error naming its next action.
Blocking a writer forever behind a transition wedged on a slow NFS mount would hang the session;
failing open would restore the exact race this closes. A refusal that names its own remedy is the
third option and the only sound one. The bound is a deadline over non-blocking ``flock`` rather
than ``SIGALRM``, so it holds on every thread and collides with no caller's own timers.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "TIMEOUT_ENV",
    "configured_timeout",
    "TaskNoteLockError",
    "default_lock_root",
    "lock_names",
    "projected_path_lock",
]

#: Long enough that a healthy transition never trips it, short enough that a wedged one surfaces
#: as a refusal the operator can act on rather than as a hung session.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Operator override, in seconds. A caller on a hot path — the gate stamps frontmatter inside a
#: tool-call hook — wants a short bound; an operator clearing a wedge wants a long one. ``0``
#: waits not at all. An unparseable or negative value falls back to the default rather than
#: refusing: a malformed knob must not be able to wedge every task-note writer in the estate.
TIMEOUT_ENV = "HAPAX_TASK_NOTE_LOCK_TIMEOUT"


class _Default:
    """Sentinel for "whatever the estate is configured for", distinct from an explicit None.

    ``None`` already means *wait forever*, so it cannot double as *use the default*; a caller
    that passed ``None`` meaning "I did not choose" would get an unbounded wait it never asked
    for, which is the wedge this module exists to make impossible.
    """


DEFAULT = _Default()


def configured_timeout() -> float:
    raw = os.environ.get(TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value >= 0 else DEFAULT_TIMEOUT_SECONDS


#: Backoff bounds for the acquisition poll. The floor keeps an uncontended handoff quick;
#: the ceiling keeps a long wait from spinning.
_POLL_MIN_SECONDS = 0.005
_POLL_MAX_SECONDS = 0.25

#: Key namespace. Kept as constants because :mod:`shared.coord_projection` and this module must
#: derive byte-identical names; a literal repeated in two files is how two domains begin.
TASK_KEY = "task:"
PATH_KEY = "path:"

_LOCK_SUFFIX = ".lock"
_LOCK_MODE = 0o600
_ROOT_MODE = 0o700


class TaskNoteLockError(Exception):
    """A typed refusal. ``repair_action`` is the next action, not an apology."""

    def __init__(self, reason_code: str, repair_action: str, detail: str | None = None) -> None:
        super().__init__(f"{reason_code}: {repair_action}" + (f" ({detail})" if detail else ""))
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail


def default_lock_root() -> Path:
    """The estate's canonical lock root. Imported lazily — this module must stay cheap."""

    from shared.coord_event_log import coord_base_dir

    return coord_base_dir() / "task-locks"


def _normalized(path: Path) -> Path:
    """One spelling per path, without resolving symlinks.

    ``Path.resolve()`` would follow links, which turns two distinct lock keys into one whenever
    the vault is reached through a symlink — silently widening the critical section. Lexical
    normalization keeps the key a function of the name the caller used.
    """

    return Path(os.path.normpath(os.path.abspath(str(path))))


def lock_names(task_id: str | None, paths: Iterable[Path] = ()) -> tuple[str, ...]:
    """Canonical lock file names for one write, in the total order they must be taken."""

    keys: set[str] = set()
    if task_id:
        keys.add(f"{TASK_KEY}{task_id}")
    for path in paths:
        keys.add(f"{PATH_KEY}{_normalized(path)}")
    if not keys:
        raise TaskNoteLockError(
            "task_note_lock_no_keys",
            "name the task id, the note path, or both — an empty key set locks nothing",
        )
    return tuple(sorted(sha256(key.encode("utf-8")).hexdigest() + _LOCK_SUFFIX for key in keys))


# --------------------------------------------------------------------- re-entrancy registry
#
# ``flock`` is per open file description, so process-wide bookkeeping is what makes nesting
# safe; ``threading.RLock`` is what keeps two *threads* of one process from treating each
# other's flock as their own. Depth is tracked per (root, name, thread).

_REGISTRY_GUARD = threading.Lock()
_THREAD_LOCKS: dict[tuple[str, str], threading.RLock] = {}
_HELD: dict[tuple[str, str, int], int] = {}
_HANDLES: dict[tuple[str, str], int] = {}


def _thread_lock(key: tuple[str, str]) -> threading.RLock:
    with _REGISTRY_GUARD:
        existing = _THREAD_LOCKS.get(key)
        if existing is None:
            existing = threading.RLock()
            _THREAD_LOCKS[key] = existing
        return existing


def _enter_depth(root_key: str, names: tuple[str, ...], thread_id: int) -> None:
    for name in names:
        key = (root_key, name, thread_id)
        _HELD[key] = _HELD.get(key, 0) + 1


def _exit_depth(root_key: str, names: tuple[str, ...], thread_id: int) -> None:
    """Release only at the outermost exit.

    Decrementing on every exit would be worse than having no re-entrancy: an inner ``with``
    closing would free the lock while the outer critical section ran on believing itself
    serialized.
    """

    for name in names:
        key = (root_key, name, thread_id)
        depth = _HELD.get(key, 0) - 1
        if depth > 0:
            _HELD[key] = depth
        else:
            _HELD.pop(key, None)


def _deadline(timeout: float | None) -> float | None:
    """Absolute monotonic deadline, or ``None`` for an unbounded wait."""

    return None if timeout is None else time.monotonic() + max(timeout, 0.0)


def _flock_until(handle: int, deadline: float | None, *, what: str, root: Path) -> None:
    """Take ``LOCK_EX`` on ``handle``, giving up at ``deadline``.

    Non-blocking ``flock`` plus a deadline rather than ``SIGALRM``: the signal is process-wide,
    single-slot and deliverable only on the main thread, so bounding a wait with it needs one
    guard for the thread and another for a caller's pending alarm — two mitigations for one
    hazard, which is the estate's signal that the shape is wrong rather than the guards
    insufficient. A poll loop is bounded on every thread, disturbs no global state, and leaves
    nothing for a daemon's own timers to collide with.
    """

    delay = _POLL_MIN_SECONDS
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise
        if deadline is not None and time.monotonic() >= deadline:
            raise TaskNoteLockError(
                "task_note_lock_timeout",
                "retry once the in-flight transition or writer for this task releases; "
                f"identify the holder with `fuser -v {root / what}`",
                str(root / what),
            )
        remaining = None if deadline is None else max(deadline - time.monotonic(), 0.0)
        time.sleep(delay if remaining is None else min(delay, remaining))
        delay = min(delay * 2, _POLL_MAX_SECONDS)


def _ensure_root(root: Path) -> int:
    """Open the lock root, creating it private. Returns an ``O_DIRECTORY`` fd."""

    try:
        root.mkdir(parents=True, mode=_ROOT_MODE, exist_ok=True)
    except OSError as exc:
        raise TaskNoteLockError(
            "task_note_lock_root_unavailable",
            f"create {root} as a private directory the task writers can share",
            str(exc),
        ) from exc
    try:
        return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as exc:
        raise TaskNoteLockError(
            "task_note_lock_root_unavailable",
            f"make {root} a real directory (not a symlink) readable by this euid",
            str(exc),
        ) from exc


def _open_verified(root_fd: int, name: str, root: Path) -> int:
    """Open one lock file and refuse anything that is not a lock.

    A file another euid can write, or that carries a second link, or that holds content, is not
    an exclusion primitive — it is a channel. Refusing is the only sound response; falling back
    to "use it anyway" would do *more* than the primary path, which is the shape of an unsound
    fallback.
    """

    handle = os.open(
        name, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, _LOCK_MODE, dir_fd=root_fd
    )
    try:
        metadata = os.fstat(handle)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o777 != _LOCK_MODE
            or metadata.st_size != 0
        ):
            raise TaskNoteLockError(
                "task_note_lock_file_unsafe",
                "use one euid-owned single-link empty mode-0600 lock file",
                str(root / name),
            )
    except Exception:
        os.close(handle)
        raise
    return handle


def _verify_identity(handle: int, root_fd: int, name: str, root: Path) -> None:
    """The pathname must still name the inode we hold, after the flock as well as before."""

    held = os.fstat(handle)
    named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    if held.st_nlink != 1 or held.st_dev != named.st_dev or held.st_ino != named.st_ino:
        raise TaskNoteLockError(
            "task_note_lock_identity_changed",
            "hold until the canonical lock pathname names the inode under flock",
            str(root / name),
        )


@contextmanager
def projected_path_lock(
    task_id: str | None,
    paths: Iterable[Path] = (),
    *,
    root: Path | None = None,
    timeout: float | None | _Default = DEFAULT,
) -> Iterator[tuple[str, ...]]:
    """Hold the projection lock for one task note while mutating it.

    Every writer to a projected task-note path takes this, including the transition itself.
    Re-entrant per thread; totally ordered; bounded by ``timeout`` with a typed refusal.
    """

    lock_root = _normalized(root if root is not None else default_lock_root())
    names = lock_names(task_id, paths)
    root_key = str(lock_root)
    thread_id = threading.get_ident()

    if isinstance(timeout, _Default):
        timeout = configured_timeout()
    deadline = _deadline(timeout)
    fresh = [name for name in names if _HELD.get((root_key, name, thread_id), 0) == 0]

    if not fresh:
        # Fully re-entrant: this thread already holds every name. Bump depth, take nothing.
        _enter_depth(root_key, names, thread_id)
        try:
            yield names
        finally:
            _exit_depth(root_key, names, thread_id)
        return

    thread_locks = [_thread_lock((root_key, name)) for name in fresh]
    acquired_thread_locks: list[threading.RLock] = []
    root_fd: int | None = None
    opened: list[tuple[str, int]] = []
    entered = False
    try:
        for name, guard in zip(fresh, thread_locks, strict=True):
            remaining = None if deadline is None else max(deadline - time.monotonic(), 0.0)
            got = guard.acquire(timeout=-1 if remaining is None else remaining)
            if not got:
                raise TaskNoteLockError(
                    "task_note_lock_timeout",
                    "retry once the concurrent writer for this task in this process releases; "
                    f"another thread holds {lock_root / name}",
                    f"{lock_root / name}",
                )
            acquired_thread_locks.append(guard)

        root_fd = _ensure_root(lock_root)
        # The root flock makes "create the lock file and flock it" indivisible against a
        # concurrent unlink of that same file; it is the ordering that lets the per-key locks
        # below be taken safely, and coord_projection has always held it this way.
        try:
            _flock_until(root_fd, deadline, what="", root=lock_root)
        except OSError as exc:  # pragma: no cover - defensive
            raise TaskNoteLockError(
                "task_note_lock_root_unavailable",
                f"make {lock_root} flock-able on this filesystem",
                str(exc),
            ) from exc

        for name in fresh:
            handle = _open_verified(root_fd, name, lock_root)
            try:
                _flock_until(handle, deadline, what=name, root=lock_root)
                _verify_identity(handle, root_fd, name, lock_root)
            except Exception:
                os.close(handle)
                raise
            opened.append((name, handle))
            _HANDLES[(root_key, name)] = handle

        # Acquisition is complete; drop the root. Holding it across the critical section would
        # make every task note in the estate serialize behind every other one — a global mutex
        # wearing a per-task lock's name, and the reason the per-key locks below were inert
        # (removing them changed no observable behaviour: measured 2026-09-16, mutation M5).
        #
        # It is safe to drop because the hazard it guards — someone unlinking a lock file
        # between our open and our flock — is already caught by _verify_identity above, which
        # compares the inode we hold against the inode the pathname now names, *after* the
        # flock. That check is machine-checkable at the moment of use; the root flock was a
        # second mitigation for the same hazard, and two is the signal to change the shape.
        fcntl.flock(root_fd, fcntl.LOCK_UN)
        os.close(root_fd)
        root_fd = None

        _enter_depth(root_key, names, thread_id)
        entered = True

        yield names
    finally:
        if entered:
            _exit_depth(root_key, names, thread_id)
        for name, handle in reversed(opened):
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - defensive
                pass
            _HANDLES.pop((root_key, name), None)
            try:
                os.close(handle)
            except OSError:  # pragma: no cover - defensive
                pass
        if root_fd is not None:
            try:
                fcntl.flock(root_fd, fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - defensive
                pass
            os.close(root_fd)
        for guard in reversed(acquired_thread_locks):
            guard.release()
