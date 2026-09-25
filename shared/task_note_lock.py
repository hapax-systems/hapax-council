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

**Never hold-and-wait — within this primitive.** A participant that cannot take every key it
needs releases the keys it did take, waits, and starts the whole attempt over. Among
projected-path locks no lock is ever held while another is wanted, so no wait cycle can form
among them — a stronger property than an acquisition order, because it does not depend on
every participant agreeing about the order. The one shape it cannot cover is a nested
acquisition that *adds* a key, since the outer frame's keys cannot be released to break a cycle;
that is refused (``task_note_lock_expansion_under_hold``) rather than supported, and the remedy
is to name every key in the outermost call.

**Composed with a foreign lock, the property is an acquisition order, and it is enforced.**
Claim publication (``shared.sdlc_claim._claim_publication_lock``) holds a role-keyed lock under
a different root and takes this lock *inside* it. A projected-path lock held across that role
acquisition would be hold-and-wait, so the permitted direction is role-then-note only, and the
role lock refuses (``claim_publication_lock_order_inversion``) when the calling thread already
holds any projected-path lock — see :func:`held_by_current_thread`. That is a runtime check on
the direction, not a count of acquisition sites: the inversion that matters needs no new site,
only an existing note-holder calling onward into claim publication.

**The lock root is shared, and that is a contract.** Acquirers take the root ``LOCK_SH``, so they
do not exclude one another — an earlier draft took it ``LOCK_EX`` and polled contended keys while
holding it, which made one contended task refuse every unrelated task in the estate (reproduced
2026-09-16: an unrelated task refused after 3s). The root exists for a different party:
:func:`_verify_identity` protects an *acquirer* at acquisition, not an *incumbent* for the
duration, so a lock file unlinked mid-section would let a second acquirer create a fresh inode,
flock it, verify against it and enter alongside. **Anything that removes files from the lock root
— a cache sweep over ``coord_base_dir()``, a recovery reaper, a hand-run ``rm`` — must take the
root ``LOCK_EX`` first**, and will then wait for every in-flight critical section. Nothing in this
estate removes them today; the contract is written here so that the day something does, it has a
protocol to follow rather than an assumption to violate.

**Bounded.** Acquisition has a timeout and refuses with a typed error naming its next action.
Blocking a writer forever behind a transition wedged on a slow NFS mount would hang the session;
failing open would restore the exact race this closes. A refusal that names its own remedy is the
third option and the only sound one. The bound is a deadline over non-blocking ``flock`` rather
than ``SIGALRM``, so it holds on every thread and collides with no caller's own timers.

**The bypass is ``HAPAX_COORD_DIR``, and pretending otherwise was the mistake.** An earlier
revision of this docstring claimed there was deliberately no bypass. That was wrong in the
dangerous direction: the lock root is ``coord_base_dir()/task-locks``, and ``HAPAX_COORD_DIR``
moves it — so a writer invoked with a different value takes a *different* lock and excludes
nothing, silently. An undocumented escape hatch that nobody is warned about is worse than a
documented one, because the people who trip it are not the people who chose it.

So it is named here as what it is:

* ``HAPAX_COORD_DIR`` **splits the lock domain.** Every participant that must exclude one another
  — every converted writer, the gate stamp, claim publication, and every lifecycle transition —
  has to resolve the *same* root. Setting it per-invocation is the emergency route out of a
  wedged or broken lock root, and its hazard is exactly the fail-open this module exists to
  close: a note written while a transition holds it, with no refusal anywhere.
* ``HAPAX_TASK_NOTE_LOCK_TIMEOUT`` only tunes the wait. ``0`` refuses sooner; it never admits.

Preferred order when the root is unusable: repair the root; if it cannot be repaired, move
``HAPAX_COORD_DIR`` **for the whole estate at once**, never for one writer. See
``docs/runbooks/projection-lock-domain.md``.
"""

from __future__ import annotations

import errno
import fcntl
import math
import os
import stat
import sys
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
    "held_by_current_thread",
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


def _discarded(raw: str) -> float:
    """Fall back to the default, and say so.

    Silently discarding the operator's value is how they end up reasoning about a timeout that
    was never in effect: they set 2, saw a 30s wait, and concluded the lock was wedged. The
    fallback itself is right — a malformed knob must not wedge every writer in the estate — but
    it owes them a line on stderr.
    """

    print(
        f"task_note_lock: {TIMEOUT_ENV}={raw!r} is not a finite non-negative number; "
        f"using the {DEFAULT_TIMEOUT_SECONDS}s default",
        file=sys.stderr,
    )
    return DEFAULT_TIMEOUT_SECONDS


def configured_timeout() -> float:
    raw = os.environ.get(TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _discarded(raw)
    # `inf` and `nan` both parse, and `inf >= 0` is True — a bare float() check would let
    # HAPAX_TASK_NOTE_LOCK_TIMEOUT=inf produce precisely the unbounded wait this fallback
    # exists to make unreachable, wedging every converted writer behind one stuck holder.
    if not math.isfinite(value) or value < 0:
        return _discarded(raw)
    return value


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
#: One re-entrant guard per lock name. Interned rather than made per acquisition, because two
#: threads must reach the *same* object for it to exclude anything — and reference-counted so a
#: long-lived writer touching many task notes does not accumulate one guard per note forever.
_THREAD_LOCKS: dict[tuple[str, str], threading.RLock] = {}
_THREAD_LOCK_USERS: dict[tuple[str, str], int] = {}
_HELD: dict[tuple[str, str, int], int] = {}
#: Open lock descriptors, so a forked child can disown what it inherited. Not bookkeeping for
#: release — the acquisition frame owns that — and an earlier revision deleted this map as dead
#: state, correctly observing it had no reader. It had no reader because its consumer was
#: missing, not because it was unnecessary: see _forget_inherited_locks.
_OPEN_HANDLES: dict[int, None] = {}


def _thread_lock(key: tuple[str, str]) -> threading.RLock:
    """Intern the guard for one lock name and register interest in it."""

    with _REGISTRY_GUARD:
        existing = _THREAD_LOCKS.get(key)
        if existing is None:
            existing = threading.RLock()
            _THREAD_LOCKS[key] = existing
        _THREAD_LOCK_USERS[key] = _THREAD_LOCK_USERS.get(key, 0) + 1
        return existing


def _drop_thread_lock(key: tuple[str, str]) -> None:
    """Withdraw interest in a guard, forgetting it once nobody holds or wants it.

    The count is of *interest*, not of lock depth: incremented when a caller obtains the object
    and decremented when that caller is finished with it, whether or not it managed to acquire.
    Dropping the entry while another thread still referenced it would hand the next caller a
    fresh object, and two threads holding two different objects exclude nothing.
    """

    with _REGISTRY_GUARD:
        remaining = _THREAD_LOCK_USERS.get(key, 1) - 1
        if remaining > 0:
            _THREAD_LOCK_USERS[key] = remaining
        else:
            _THREAD_LOCK_USERS.pop(key, None)
            _THREAD_LOCKS.pop(key, None)


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


def _forget_inherited_locks() -> None:
    """Disown every lock this process inherited across ``fork``.

    ``fork`` copies the whole address space, so a child starts life believing it holds every
    lock the parent held: ``_HELD`` is process-global, and the child's main thread reuses the
    parent's thread id. The child would then either re-enter a lock it does not own, or — since
    a key set that differs from the inherited one is an expansion — be refused outright for a
    lock nobody in the child ever took. The estate's own claim-publication test forks exactly
    this way and caught it.

    The inherited *descriptors* are closed too. ``flock`` is released only when every descriptor
    referring to the open file description is closed, so the parent keeps its lock; all this
    does is stop the child from silently extending the parent's hold for as long as it lives.
    ``O_CLOEXEC`` already covers fork+exec, which is how every shell caller reaches this module;
    this covers bare ``fork``, which multiprocessing uses.
    """

    for handle in list(_OPEN_HANDLES):
        try:
            os.close(handle)
        except OSError:  # pragma: no cover - defensive
            pass
    _OPEN_HANDLES.clear()
    _HELD.clear()
    _THREAD_LOCKS.clear()
    _THREAD_LOCK_USERS.clear()


os.register_at_fork(after_in_child=_forget_inherited_locks)


def _thread_held(root_key: str, thread_id: int) -> set[str]:
    return {name for (rk, name, tid) in _HELD if rk == root_key and tid == thread_id}


def _thread_holds_any(root_key: str, thread_id: int) -> bool:
    return any(rk == root_key and tid == thread_id for (rk, _name, tid) in _HELD)


def held_by_current_thread() -> tuple[tuple[str, str], ...]:
    """Every projected-path lock this thread holds right now, as ``(lock_root, name)`` pairs.

    For a foreign lock that composes with this one to assert its acquisition direction at the
    moment of use: ``shared.sdlc_claim._claim_publication_lock`` refuses to take the role lock
    while this returns anything, because the role lock takes a projected-path lock inside it and
    the reverse order would be hold-and-wait. Across every root, deliberately — a caller holding
    a note under a redirected root is still a holder, and a direction rule that only sees one
    root is a rule with a hole in it.
    """

    thread_id = threading.get_ident()
    return tuple(
        sorted(
            (rk, name) for (rk, name, tid), depth in _HELD.items() if tid == thread_id and depth > 0
        )
    )


def _release_attempt(
    _root_key: str,
    opened: list[tuple[str, int]],
    guards: list[tuple[tuple[str, str], threading.RLock]],
    root_fd: int | None,
) -> None:
    """Undo one acquisition attempt completely, in reverse order.

    Called both on the retry path and in the final ``finally``; it must be exact either way,
    because a half-released attempt would leave this thread holding a key it believes it does
    not, and the depth bookkeeping would then disagree with the filesystem.
    """

    for _name, handle in reversed(opened):
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:  # pragma: no cover - defensive
            pass
        _OPEN_HANDLES.pop(handle, None)
        try:
            os.close(handle)
        except OSError:  # pragma: no cover - defensive
            pass
    if root_fd is not None:
        try:
            fcntl.flock(root_fd, fcntl.LOCK_UN)
        except OSError:  # pragma: no cover - defensive
            pass
        try:
            os.close(root_fd)
        except OSError:  # pragma: no cover - defensive
            pass
    for key, guard in reversed(guards):
        guard.release()
        _drop_thread_lock(key)


def _deadline(timeout: float | None) -> float | None:
    """Absolute monotonic deadline, or ``None`` for an unbounded wait."""

    return None if timeout is None else time.monotonic() + max(timeout, 0.0)


def _try_flock(handle: int, operation: int) -> bool:
    """One non-blocking ``flock``. ``False`` means contended, never "gave up and continued".

    Nothing in this module ever *waits* while holding a lock. That is the whole deadlock
    argument among projected-path locks: a participant that cannot take every key it needs
    releases the keys it did take and starts over, so there is no hold-and-wait edge for a cycle
    to form on. Within the primitive it is a stronger property than an acquisition order, because
    it does not depend on every participant agreeing about the order (the composition with the
    claim path's role lock is the exception, and there the direction is enforced — see the
    module docstring) — and an earlier draft of this module proved why that matters, by
    polling a contended key while holding the root exclusively and turning a per-task lock into
    an estate-wide one (reproduced 2026-09-16: an unrelated task was refused after 3s purely
    because a different task was contended).
    """

    try:
        fcntl.flock(handle, operation | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            return False
        raise TaskNoteLockError(
            "task_note_lock_unavailable",
            "make the lock root flock-able on this filesystem, then retry",
            str(exc),
        ) from exc


def _ensure_root(root: Path) -> int:
    """Open the lock root, creating it private, refusing anything that is not.

    Component-by-component with ``O_NOFOLLOW``, and the final directory must be a real
    directory owned by this euid at mode 0700 — the same validation
    ``coord_projection._ensure_private_directory_fd`` has always applied to this path.

    ``mkdir(parents=True, exist_ok=True)`` plus one open is NOT equivalent and an earlier draft
    of this module used it: it accepts a symlinked ancestor, and it accepts an existing
    world-writable root (it accepted ``/tmp``). A lock directory other users can write is not an
    exclusion primitive — anyone can unlink a lock pathname and recreate it, which is precisely
    the substitution :func:`_verify_identity` exists to catch, made trivially available.
    """

    normalized = _normalized(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for component in normalized.parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, _ROOT_MODE, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        metadata = os.fstat(fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != _ROOT_MODE
        ):
            raise TaskNoteLockError(
                "task_note_lock_root_unsafe",
                f"use one euid-owned mode-0700 real directory at {normalized} "
                "(a shared or world-writable lock root excludes nothing)",
                str(normalized),
            )
        return fd
    except TaskNoteLockError:
        os.close(fd)
        raise
    except OSError as exc:
        os.close(fd)
        raise TaskNoteLockError(
            "task_note_lock_root_unavailable",
            f"make every component of {normalized} a real euid-owned directory "
            "(no symlinked ancestor), then retry",
            str(exc),
        ) from exc
    except Exception:
        os.close(fd)
        raise


def _open_verified(root_fd: int, name: str, root: Path) -> int:
    """Open one lock file and refuse anything that is not a lock.

    A file another euid can write, or that carries a second link, or that holds content, is not
    an exclusion primitive — it is a channel. Refusing is the only sound response; falling back
    to "use it anyway" would do *more* than the primary path, which is the shape of an unsound
    fallback.
    """

    try:
        handle = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
            _LOCK_MODE,
            dir_fd=root_fd,
        )
    except OSError as exc:
        # A symlink at the lock pathname lands here via ELOOP. Callers are promised a typed
        # refusal with a next action; an ordinary OSError escaping would reach
        # coord_projection's translator, which catches only TaskNoteLockError, and surface
        # with no reason code at all.
        raise TaskNoteLockError(
            "task_note_lock_file_unsafe",
            "replace the lock pathname with one euid-owned single-link mode-0600 regular file",
            f"{root / name}: {exc}",
        ) from exc
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

    try:
        held = os.fstat(handle)
        named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except OSError as exc:
        # The canonical pathname disappearing between the flock and this stat is exactly the
        # substitution this check exists to catch — report it as such, not as a raw OSError.
        raise TaskNoteLockError(
            "task_note_lock_identity_changed",
            "hold until the canonical lock pathname names the inode under flock",
            f"{root / name}: {exc}",
        ) from exc
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

    fresh = tuple(name for name in names if _HELD.get((root_key, name, thread_id), 0) == 0)

    if not fresh:
        # Fully re-entrant: this thread already holds every name. Bump depth, take nothing.
        _enter_depth(root_key, names, thread_id)
        try:
            yield names
        finally:
            _exit_depth(root_key, names, thread_id)
        return

    if _thread_holds_any(root_key, thread_id):
        # Expansion under a held lock: this thread holds some keys and is asking for one it
        # does not. Refused rather than supported, because it is the one shape the all-or-
        # nothing acquisition below cannot make deadlock-free: the outer frame's keys cannot
        # be released to break a cycle, so two threads expanding into each other's held keys
        # wait until their deadlines. Taking every key in one outermost call costs the caller
        # one argument and removes the cycle entirely.
        raise TaskNoteLockError(
            "task_note_lock_expansion_under_hold",
            "acquire every key this operation needs in one outermost projected_path_lock() "
            "call; a nested acquisition may repeat keys already held but may not add new ones",
            f"{lock_root}: already holding {sorted(_thread_held(root_key, thread_id))}, "
            f"asked to add {sorted(fresh)}",
        )

    entered = False
    root_fd: int | None = None
    opened: list[tuple[str, int]] = []
    guards: list[tuple[tuple[str, str], threading.RLock]] = []
    delay = _POLL_MIN_SECONDS
    try:
        while True:
            # One full attempt. Anything not obtained is released before we wait, so this
            # process never holds a lock while wanting another — no hold-and-wait, hence no
            # cycle, independent of what any other participant does.
            root_fd = _ensure_root(lock_root)
            # SHARED, not exclusive. Acquirers do not exclude each other here; the root is a
            # gate against whoever would *remove* lock files, who must take it exclusively and
            # will therefore wait for every in-flight critical section (see the module
            # docstring's reaper contract). Held exclusively, as an earlier draft did, it made
            # every task note in the estate serialize behind every other one.
            if _try_flock(root_fd, fcntl.LOCK_SH):
                for name in fresh:
                    guard_key = (root_key, name)
                    guard = _thread_lock(guard_key)
                    if not guard.acquire(blocking=False):
                        _drop_thread_lock(guard_key)
                        break
                    guards.append((guard_key, guard))
                    handle = _open_verified(root_fd, name, lock_root)
                    try:
                        if not _try_flock(handle, fcntl.LOCK_EX):
                            os.close(handle)
                            break
                        _verify_identity(handle, root_fd, name, lock_root)
                    except Exception:
                        os.close(handle)
                        raise
                    opened.append((name, handle))
                    _OPEN_HANDLES[handle] = None
                else:
                    break  # every key taken

            _release_attempt(root_key, opened, guards, root_fd)
            opened, guards, root_fd = [], [], None

            if deadline is not None and time.monotonic() >= deadline:
                raise TaskNoteLockError(
                    "task_note_lock_timeout",
                    "retry once the in-flight transition or writer for this task releases; "
                    f"identify the holder with `fuser -v {lock_root}/<lock>`",
                    f"{lock_root}: {sorted(fresh)}",
                )
            remaining = None if deadline is None else max(deadline - time.monotonic(), 0.0)
            time.sleep(delay if remaining is None else min(delay, remaining))
            delay = min(delay * 2, _POLL_MAX_SECONDS)

        _enter_depth(root_key, names, thread_id)
        entered = True
        yield names
    finally:
        if entered:
            _exit_depth(root_key, names, thread_id)
        _release_attempt(root_key, opened, guards, root_fd)
