"""Tests for shared/task_note_lock.py — the one lock domain every task-note writer shares.

The hazard these pin (beta, 2026-09-13T22:10Z; codex-1 C1 on PR #4667): the projection
transition serializes itself with ``flock(LOCK_EX)`` keyed by task id and path, while the
routine task-note writers (``cc-stage-advance``, ``cc-scope-widen``, ``cc-task-repair``, the
gate's ``_stamp_frontmatter_field``, and — found by the second search shape — ``cc-claim``,
``cc-close`` and ``cc-task-pr-link.sh``) write the same paths taking no lock at all. A writer
that lands between the transition's preimage pin and its install has its bytes counted by the
safety check and then destroyed, and the transition is still recorded applied: fail-open.

The fix is not a second guard on the transition. It is that the lock guarding relocation and
the lock guarding mutation are the *same* lock, so the concurrency contract the ratified design
already assumes actually holds.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from shared import task_note_lock as tnl

REPO_ROOT = Path(__file__).resolve().parents[2]


def _child(body: str, *args: str, env: dict[str, str] | None = None) -> subprocess.Popen[str]:
    """Run a lock participant in a real second process — flock is per-fd, per-open-file."""

    script = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, {str(REPO_ROOT)!r})
        from pathlib import Path
        from shared import task_note_lock as tnl
        {textwrap.indent(textwrap.dedent(body), "        ").strip()}
        """
    )
    merged = {**os.environ, **(env or {})}
    return subprocess.Popen(
        [sys.executable, "-c", script, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=merged,
    )


# ---------------------------------------------------------------- naming / ordering


def test_lock_names_are_order_independent_and_totally_ordered(tmp_path: Path) -> None:
    """Two callers naming the same keys in different orders take them in the same order.

    A total order over lock names is what makes multi-key acquisition deadlock-free; if the
    order depended on the caller's argument order, two writers naming {A,B} and {B,A} could
    hold one each and wait forever.
    """

    a, b = tmp_path / "a.md", tmp_path / "b.md"
    assert tnl.lock_names("task-1", (a, b)) == tnl.lock_names("task-1", (b, a))
    assert list(tnl.lock_names("task-1", (a, b))) == sorted(tnl.lock_names("task-1", (a, b)))


def test_lock_names_are_stable_across_equivalent_spellings(tmp_path: Path) -> None:
    """``./x/../a.md`` and ``a.md`` are one path, so they must be one lock."""

    direct = tmp_path / "a.md"
    indirect = tmp_path / "x" / ".." / "a.md"
    assert tnl.lock_names(None, (direct,)) == tnl.lock_names(None, (indirect,))


# ---------------------------------------------------------------- re-entrancy


def test_same_thread_reentrant_acquisition_does_not_deadlock(tmp_path: Path) -> None:
    """The primitive must be re-entrant.

    ``flock`` is per *open file description*, not per process: a second ``os.open`` + ``flock``
    of the same lock file inside one process blocks forever against itself and then reports a
    concurrent writer that does not exist. Every caller here is a writer that may also drive a
    transition (``cc-close`` stamps the note and then runs the terminal transition over it), so
    nesting is the normal case, not an exotic one.
    """

    note = tmp_path / "vault" / "active" / "t-1.md"
    note.parent.mkdir(parents=True)
    note.write_text("x\n", encoding="utf-8")
    root = tmp_path / "locks"

    finished = threading.Event()

    def nested() -> None:
        with tnl.projected_path_lock("task-1", (note,), root=root, timeout=5.0):
            with tnl.projected_path_lock("task-1", (note,), root=root, timeout=5.0):
                with tnl.projected_path_lock("task-1", (), root=root, timeout=5.0):
                    pass
        finished.set()

    worker = threading.Thread(target=nested, daemon=True)
    worker.start()
    worker.join(timeout=20)
    assert finished.is_set(), "re-entrant acquisition self-deadlocked"


def test_reentrant_release_holds_the_lock_until_the_outermost_exit(tmp_path: Path) -> None:
    """An inner ``with`` exiting must not retire the outer acquisition's bookkeeping.

    The observable is subtle and it is worth naming, because probing for the wrong one makes
    this test pass against the defect. Depth is not what holds the lock — the open file
    description is, and the outer frame owns that until it exits. So a depth counter that
    forgets on the inner exit does NOT leak the lock to another process.

    What it does instead is tell the *next* acquisition in this same thread that the lock is
    free. That acquisition then opens a second fd and blocks on a lock its own thread is
    holding, forever, and reports a concurrent writer that does not exist. That is the failure
    the estate has already paid four rounds for, so this reaches for it directly.
    """

    note = tmp_path / "t-1.md"
    note.write_text("x\n", encoding="utf-8")
    root = tmp_path / "locks"

    done = threading.Event()

    def nested() -> None:
        with tnl.projected_path_lock("task-1", (note,), root=root, timeout=5.0):
            with tnl.projected_path_lock("task-1", (note,), root=root, timeout=5.0):
                pass
            # The inner frame is gone; this thread still holds the lock, so a further
            # acquisition must be recognised as re-entrant rather than waited on.
            with tnl.projected_path_lock("task-1", (note,), root=root, timeout=5.0):
                pass
        done.set()

    worker = threading.Thread(target=nested, daemon=True)
    worker.start()
    worker.join(timeout=25)
    assert done.is_set(), (
        "re-acquiring after an inner release self-deadlocked: the inner exit dropped the "
        "outer acquisition's depth"
    )


def test_different_threads_exclude_each_other(tmp_path: Path) -> None:
    """Re-entrancy is per thread, not per process — two threads are two writers."""

    root = tmp_path / "locks"
    order: list[str] = []
    entered_first = threading.Event()
    release_first = threading.Event()

    def first() -> None:
        with tnl.projected_path_lock("task-1", (), root=root, timeout=10.0):
            order.append("first-in")
            entered_first.set()
            release_first.wait(timeout=10)
            order.append("first-out")

    def second() -> None:
        entered_first.wait(timeout=10)
        with tnl.projected_path_lock("task-1", (), root=root, timeout=10.0):
            order.append("second-in")

    t1, t2 = threading.Thread(target=first), threading.Thread(target=second)
    t1.start()
    t2.start()
    entered_first.wait(timeout=10)
    time.sleep(0.2)
    assert order == ["first-in"], "second thread entered while the first held the lock"
    release_first.set()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert order == ["first-in", "first-out", "second-in"]


# ---------------------------------------------------------------- cross-process exclusion


def test_a_second_process_is_refused_while_the_lock_is_held(tmp_path: Path) -> None:
    root = tmp_path / "locks"
    with tnl.projected_path_lock("task-1", (), root=root, timeout=5.0):
        child = _child(
            """
            root = Path(sys.argv[1])
            try:
                with tnl.projected_path_lock("task-1", (), root=root, timeout=0.5):
                    print("ACQUIRED")
            except tnl.TaskNoteLockError as exc:
                print("REFUSED", exc.reason_code, "|", exc.repair_action)
            """,
            str(root),
        )
        out, err = child.communicate(timeout=30)
    assert "REFUSED" in out, f"{out!r} {err!r}"
    assert "task_note_lock_timeout" in out


def test_a_second_process_acquires_once_the_lock_is_released(tmp_path: Path) -> None:
    root = tmp_path / "locks"
    child_started = None
    with tnl.projected_path_lock("task-1", (), root=root, timeout=5.0):
        child_started = _child(
            """
            root = Path(sys.argv[1])
            with tnl.projected_path_lock("task-1", (), root=root, timeout=30.0):
                print("ACQUIRED")
            """,
            str(root),
        )
        time.sleep(0.5)
        assert child_started.poll() is None, "child did not wait for the held lock"
    out, err = child_started.communicate(timeout=60)
    assert "ACQUIRED" in out, f"{out!r} {err!r}"


def test_timeout_refusal_names_its_own_next_action(tmp_path: Path) -> None:
    """executive_function: an error must carry the action that clears it."""

    root = tmp_path / "locks"
    with tnl.projected_path_lock("task-1", (), root=root, timeout=5.0):
        child = _child(
            """
            root = Path(sys.argv[1])
            try:
                with tnl.projected_path_lock("task-1", (), root=root, timeout=0.3):
                    pass
            except tnl.TaskNoteLockError as exc:
                print("|".join([exc.reason_code, exc.repair_action, str(exc.detail)]))
            """,
            str(root),
        )
        out, _err = child.communicate(timeout=30)
    reason, repair, _detail = out.strip().split("|", 2)
    assert reason == "task_note_lock_timeout"
    assert repair.strip(), "refusal carries no repair action"


# ---------------------------------------------------------------- lost-update, the row's ask


_APPENDER = """
    note, root, line, delay = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], float(sys.argv[4])
    locked = sys.argv[5] == "locked"
    import contextlib
    ctx = (
        tnl.projected_path_lock("task-1", (note,), root=root, timeout=60.0)
        if locked
        else contextlib.nullcontext()
    )
    with ctx:
        text = note.read_text(encoding="utf-8")   # read
        time.sleep(delay)                          # ...interleave window...
        note.write_text(text + line + "\\n", encoding="utf-8")  # modify-write
    print("DONE")
"""


def _run_two_appenders(note: Path, root: Path, *, locked: bool) -> str:
    mode = "locked" if locked else "unlocked"
    a = _child(_APPENDER, str(note), str(root), "alpha", "0.6", mode)
    time.sleep(0.15)
    b = _child(_APPENDER, str(note), str(root), "beta", "0.0", mode)
    for proc in (a, b):
        out, err = proc.communicate(timeout=90)
        assert "DONE" in out, f"appender failed: {out!r} {err!r}"
    return note.read_text(encoding="utf-8")


def test_two_writers_under_one_lock_lose_no_copy(tmp_path: Path) -> None:
    """The row's acceptance shape: two writers, one flock, no lost copy."""

    note = tmp_path / "vault" / "active" / "t-1.md"
    note.parent.mkdir(parents=True)
    note.write_text("base\n", encoding="utf-8")
    final = _run_two_appenders(note, tmp_path / "locks", locked=True)
    assert "alpha" in final and "beta" in final, f"a writer's copy was lost: {final!r}"
    assert final.splitlines()[0] == "base"


def test_unlocked_writers_do_lose_a_copy(tmp_path: Path) -> None:
    """Negative control — proof the test above can fail.

    Without this, ``test_two_writers_under_one_lock_lose_no_copy`` is documentation: it would
    stay green against a lock that does nothing at all. This pins that the interleaving the
    harness constructs really is lossy when the lock is removed.
    """

    note = tmp_path / "vault" / "active" / "t-1.md"
    note.parent.mkdir(parents=True)
    note.write_text("base\n", encoding="utf-8")
    final = _run_two_appenders(note, tmp_path / "locks", locked=False)
    assert not ("alpha" in final and "beta" in final), (
        "the unlocked harness did not actually race; the positive test proves nothing"
    )


# ---------------------------------------------------------------- one domain, not two


def test_writer_lock_and_transition_lock_are_one_domain(tmp_path: Path) -> None:
    """A held writer lock must exclude ``coord_projection``'s transition lock, and vice versa.

    This is the whole claim of the row. Two lock implementations that merely *look* alike
    serialize nothing: they would have to agree on the root, the key spelling and the digest
    forever, and nothing would detect the day they stopped agreeing. So the transition lock
    is not a second implementation — it is this one.
    """

    from shared import coord_projection as cp

    note = tmp_path / "vault" / "active" / "t-1.md"
    note.parent.mkdir(parents=True)
    note.write_text("x\n", encoding="utf-8")
    root = tmp_path / "locks"

    # Same keys must hash to the same lock file names on both sides.
    assert tuple(tnl.lock_names("task-1", (note,))) == tuple(
        cp._transition_lock_names("task-1", (note,))
    )

    # And a writer holding the lock really does keep a transition out.
    with tnl.projected_path_lock("task-1", (note,), root=root, timeout=5.0):
        child = _child(
            """
            sys.path.insert(0, sys.argv[4])
            from shared import coord_projection as cp
            note, root = Path(sys.argv[1]), Path(sys.argv[2])
            try:
                with cp._transition_locks("task-1", (note,), root, timeout=float(sys.argv[3])):
                    print("ACQUIRED")
            except Exception as exc:
                print("REFUSED", type(exc).__name__, getattr(exc, "reason_code", ""))
            """,
            str(note),
            str(root),
            "0.5",
            str(REPO_ROOT),
        )
        out, err = child.communicate(timeout=30)
    assert "REFUSED" in out, f"transition entered a writer's critical section: {out!r} {err!r}"


def test_lock_root_is_created_private_when_absent(tmp_path: Path) -> None:
    root = tmp_path / "deep" / "locks"
    with tnl.projected_path_lock("task-1", (), root=root, timeout=5.0):
        pass
    assert root.is_dir()
    assert root.stat().st_mode & 0o777 == 0o700


def test_unsafe_lock_file_is_refused_rather_than_used(tmp_path: Path) -> None:
    """A lock file someone else can write is not a lock."""

    root = tmp_path / "locks"
    root.mkdir(mode=0o700)
    name = tnl.lock_names("task-1", ())[0]
    planted = root / name
    planted.write_text("", encoding="utf-8")
    planted.chmod(0o666)
    with pytest.raises(tnl.TaskNoteLockError) as excinfo:
        with tnl.projected_path_lock("task-1", (), root=root, timeout=5.0):
            pytest.fail("entered the critical section behind an unsafe lock file")
    assert excinfo.value.reason_code == "task_note_lock_file_unsafe"


def test_a_failed_inner_acquisition_leaves_the_outer_holder_intact(tmp_path: Path) -> None:
    """A refused nested acquisition must release only the names it actually took.

    If the failure path released every name it was *asked* for rather than every name it
    *took*, an inner acquisition that timed out on one new key would retire the outer holder's
    depth on the keys they share. As above, that does not leak the flock — it makes this
    thread's next acquisition of those keys wait on itself. So the probe is a re-acquisition
    after the refusal, in the same thread, inside the outer frame.
    """

    note = tmp_path / "t-1.md"
    note.write_text("x\n", encoding="utf-8")
    other = tmp_path / "t-2.md"
    other.write_text("y\n", encoding="utf-8")
    root = tmp_path / "locks"

    holder = _child(
        """
        root, note = Path(sys.argv[1]), Path(sys.argv[2])
        with tnl.projected_path_lock(None, (note,), root=root, timeout=30.0):
            print("HELD", flush=True)
            time.sleep(6)
        """,
        str(root),
        str(other),
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "HELD"

    survived = threading.Event()

    def body() -> None:
        with tnl.projected_path_lock("task-1", (note,), root=root, timeout=10.0):
            try:
                # Asks for {task-1, t-1} — already held by this thread — plus t-2, which the
                # child process holds. The acquisition must fail as a whole.
                with tnl.projected_path_lock("task-1", (note, other), root=root, timeout=0.5):
                    raise AssertionError("acquired a lock a second process holds")
            except tnl.TaskNoteLockError:
                pass
            # The outer acquisition must still be recognised as held by this thread.
            with tnl.projected_path_lock("task-1", (note,), root=root, timeout=5.0):
                pass
        survived.set()

    worker = threading.Thread(target=body, daemon=True)
    worker.start()
    worker.join(timeout=40)
    holder.wait(timeout=30)
    assert survived.is_set(), (
        "a failed inner acquisition retired depth it never took: the outer holder's own "
        "re-acquisition then blocked on itself"
    )


def test_the_lock_disturbs_no_process_wide_timer_state(tmp_path: Path) -> None:
    """Bounding the wait must cost the caller nothing they can observe.

    An earlier draft bounded ``flock`` with ``SIGALRM``. That slot is process-wide and
    single-slot, so it needed one guard for non-main threads (where the signal is never
    delivered) and another for a caller's pending alarm (which arming ours would destroy) — and
    it still left a threaded writer with no bound at all. Two guards for one hazard is the
    signal to change the shape, not to add a third. This pins the property the replacement
    buys: the caller's timer and handler are exactly as they were.
    """

    import signal as signal_module

    def _noop(_signum: int, _frame: object) -> None:  # pragma: no cover - never fires here
        raise AssertionError("the lock armed the caller's alarm")

    previous = signal_module.signal(signal_module.SIGALRM, _noop)
    try:
        signal_module.setitimer(signal_module.ITIMER_REAL, 30.0)
        before, _ = signal_module.getitimer(signal_module.ITIMER_REAL)
        with tnl.projected_path_lock("task-1", (), root=tmp_path / "locks", timeout=5.0):
            pass
        after, _ = signal_module.getitimer(signal_module.ITIMER_REAL)
        assert after > 0 and abs(before - after) < 2.0, "the caller's pending alarm was disturbed"
        assert signal_module.getsignal(signal_module.SIGALRM) is _noop
    finally:
        signal_module.setitimer(signal_module.ITIMER_REAL, 0)
        signal_module.signal(signal_module.SIGALRM, previous)


def test_a_worker_thread_gets_the_same_bound_as_the_main_thread(tmp_path: Path) -> None:
    """The bound must not be a main-thread privilege.

    Agents write task notes from background threads. A timeout that silently degrades to an
    unbounded wait off the main thread is the worst of both: the caller reads the signature and
    believes it is bounded, and the wedge shows up as a hung daemon with no refusal anywhere.
    """

    root = tmp_path / "locks"
    outcome: list[str] = []

    def probe() -> None:
        try:
            with tnl.projected_path_lock("task-1", (), root=root, timeout=0.5):
                outcome.append("ACQUIRED")
        except tnl.TaskNoteLockError as exc:
            outcome.append(exc.reason_code)

    holder = _child(
        """
        root = Path(sys.argv[1])
        with tnl.projected_path_lock("task-1", (), root=root, timeout=30.0):
            print("HELD", flush=True)
            time.sleep(8)
        """,
        str(root),
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"
        worker = threading.Thread(target=probe, daemon=True)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive(), "a worker thread's acquisition ignored its own timeout"
        assert outcome == ["task_note_lock_timeout"], outcome
    finally:
        holder.wait(timeout=30)
