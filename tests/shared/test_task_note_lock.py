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

import inspect
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

    # There is no second name derivation to compare against: coord_projection does not have
    # one any more. An alias kept for symmetry would itself be a thing that could drift, so
    # what is asserted is the delegation and its observable consequence, below.
    assert "task_note_lock.projected_path_lock" in inspect.getsource(cp._transition_locks)

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


# ─────────────────────────────────────── the review-round criticals, pinned


def test_contention_on_one_task_does_not_stall_an_unrelated_task(tmp_path: Path) -> None:
    """gemini-1 critical, reproduced 2026-09-16 and fixed.

    An earlier draft polled a contended key while holding the lock root EXCLUSIVELY. Every
    other acquirer needs the root, so any one contended task refused every unrelated task in
    the estate for the whole of its timeout — a global mutex wearing a per-task lock's name.
    The measured shape: unrelated task T2 refused with ``task_note_lock_timeout`` after 3.02s
    purely because T1 was contended.

    The earlier granularity test missed it because it probed the *held* case, not the
    *contended* case: with a lock merely held the root was already released, so an unrelated
    task sailed through. The defect lived entirely in the window where somebody is waiting.
    """

    root = tmp_path / "locks"
    holder = _child(
        """
        root = Path(sys.argv[1])
        with tnl.projected_path_lock("T1", (), root=root, timeout=30.0):
            print("HELD", flush=True)
            time.sleep(6)
        """,
        str(root),
    )
    waiter = None
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"

        # This one must WAIT on T1 — it is the process that used to camp on the root.
        waiter = _child(
            """
            root = Path(sys.argv[1])
            try:
                with tnl.projected_path_lock("T1", (), root=root, timeout=20.0):
                    print("W-ACQUIRED", flush=True)
            except tnl.TaskNoteLockError as exc:
                print("W-REFUSED", exc.reason_code, flush=True)
            """,
            str(root),
        )
        time.sleep(1.5)

        started = time.monotonic()
        other = _child(
            """
            root = Path(sys.argv[1])
            try:
                with tnl.projected_path_lock("T2", (), root=root, timeout=3.0):
                    print("T2-ACQUIRED", flush=True)
            except tnl.TaskNoteLockError as exc:
                print("T2-REFUSED", exc.reason_code, flush=True)
            """,
            str(root),
        )
        out, err = other.communicate(timeout=60)
        elapsed = time.monotonic() - started
    finally:
        for proc in (holder, waiter):
            if proc is not None:
                try:
                    proc.communicate(timeout=60)
                except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                    proc.kill()

    assert "T2-ACQUIRED" in out, (
        f"an unrelated task was blocked by T1's contention: {out!r} {err!r}"
    )
    assert elapsed < 2.0, f"unrelated task waited {elapsed:.2f}s behind a contended sibling"


def test_no_lock_is_held_while_another_is_wanted(tmp_path: Path) -> None:
    """The deadlock argument, as a property rather than an ordering claim.

    Two participants each want both keys, in opposite argument orders, concurrently. With
    hold-and-wait they can take one each and block; the all-or-nothing acquisition releases
    whatever it got before waiting, so one of them always completes. Sorting alone would not
    save the pair that an earlier draft created, where a nesting thread waited on the root
    while the root holder waited on its key.
    """

    root = tmp_path / "locks"
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    for path in (a, b):
        path.write_text("x\n", encoding="utf-8")

    body = """
        root, first, second = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
        import time as _t
        deadline = _t.monotonic() + 25
        wins = 0
        while _t.monotonic() < deadline and wins < 5:
            try:
                with tnl.projected_path_lock(None, (first, second), root=root, timeout=8.0):
                    wins += 1
                    _t.sleep(0.05)
            except tnl.TaskNoteLockError as exc:
                print("REFUSED", exc.reason_code, flush=True)
                break
        print("WINS", wins, flush=True)
    """
    one = _child(body, str(root), str(a), str(b))
    two = _child(body, str(root), str(b), str(a))
    outs = []
    for proc in (one, two):
        out, err = proc.communicate(timeout=120)
        outs.append(out)
        assert "REFUSED" not in out, f"deadlocked into a refusal: {out!r} {err!r}"
    for out in outs:
        wins = int(out.strip().split("WINS")[1])
        assert wins == 5, f"a participant starved or blocked: {out!r}"


def test_expanding_the_key_set_under_a_held_lock_is_refused(tmp_path: Path) -> None:
    """The one shape all-or-nothing cannot make safe is refused, not silently supported.

    An outer frame's keys cannot be released to break a cycle, so a nested acquisition that
    ADDS a key is the single remaining hold-and-wait edge. Refusing it makes deadlock-freedom
    structural instead of resting on a deadline, and the refusal names the remedy: take every
    key in the outermost call.
    """

    root = tmp_path / "locks"
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    for path in (a, b):
        path.write_text("x\n", encoding="utf-8")

    with tnl.projected_path_lock("task-1", (a,), root=root, timeout=5.0):
        # Repeating held keys stays legal — that is ordinary re-entrancy.
        with tnl.projected_path_lock("task-1", (a,), root=root, timeout=5.0):
            pass
        with pytest.raises(tnl.TaskNoteLockError) as excinfo:
            with tnl.projected_path_lock("task-1", (a, b), root=root, timeout=5.0):
                pytest.fail("expanded the key set under a held lock")
    assert excinfo.value.reason_code == "task_note_lock_expansion_under_hold"
    assert "outermost" in excinfo.value.repair_action


def test_an_unsafe_lock_root_is_refused(tmp_path: Path) -> None:
    """codex-1 major: the validated traversal must not be traded for mkdir(exist_ok=True).

    A lock directory other users can write is not an exclusion primitive — anyone may unlink a
    lock pathname and recreate it, handing out the very substitution ``_verify_identity``
    exists to catch. An earlier draft accepted ``/tmp``.
    """

    shared = tmp_path / "shared-root"
    shared.mkdir(mode=0o777)
    # mkdir applies the ambient umask, so mode=0o777 alone does not guarantee a
    # world-writable root (a runner umask of 0077 yields exactly the 0700 the
    # validator accepts). Pin the mode explicitly: this test asserts that a
    # genuinely world-writable root is refused, whatever the process umask is.
    os.chmod(shared, 0o777)
    with pytest.raises(tnl.TaskNoteLockError) as excinfo:
        with tnl.projected_path_lock("task-1", (), root=shared, timeout=5.0):
            pytest.fail("entered with a world-writable lock root")
    assert excinfo.value.reason_code == "task_note_lock_root_unsafe"

    # And the real /tmp, which the earlier helper accepted.
    with pytest.raises(tnl.TaskNoteLockError):
        with tnl.projected_path_lock("task-1", (), root=Path("/tmp"), timeout=5.0):
            pytest.fail("entered with /tmp as the lock root")


def test_a_symlinked_ancestor_of_the_lock_root_is_refused(tmp_path: Path) -> None:
    """O_NOFOLLOW component-by-component: a symlinked ancestor redirects the whole domain."""

    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(tnl.TaskNoteLockError) as excinfo:
        with tnl.projected_path_lock("task-1", (), root=link / "locks", timeout=5.0):
            pytest.fail("traversed a symlinked ancestor")
    assert excinfo.value.reason_code == "task_note_lock_root_unavailable"


def test_configured_timeout_falls_back_rather_than_wedging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """claude-1 minor: the documented fallback behaviour of the knob had no test.

    A malformed value must not be able to wedge every task-note writer in the estate, so it
    falls back to the default rather than refusing; ``0`` means do not wait at all.
    """

    monkeypatch.delenv(tnl.TIMEOUT_ENV, raising=False)
    assert tnl.configured_timeout() == tnl.DEFAULT_TIMEOUT_SECONDS
    # `inf` and `nan` are the sharp cases: both parse as floats and `inf >= 0` is True, so a
    # bare float()/sign check would let the knob produce the unbounded wait it promises to make
    # unreachable — every converted writer wedged behind one stuck holder, with no refusal.
    for bad in ("", "   ", "garbage", "-1", "nan-ish", "inf", "-inf", "nan", "Infinity"):
        monkeypatch.setenv(tnl.TIMEOUT_ENV, bad)
        assert tnl.configured_timeout() == tnl.DEFAULT_TIMEOUT_SECONDS, bad
    monkeypatch.setenv(tnl.TIMEOUT_ENV, "0")
    assert tnl.configured_timeout() == 0.0
    monkeypatch.setenv(tnl.TIMEOUT_ENV, "2.5")
    assert tnl.configured_timeout() == 2.5


def test_naming_no_keys_at_all_is_refused(tmp_path: Path) -> None:
    """claude-1 minor: a typed refusal with a repair action and no coverage."""

    with pytest.raises(tnl.TaskNoteLockError) as excinfo:
        tnl.lock_names(None, ())
    assert excinfo.value.reason_code == "task_note_lock_no_keys"
    assert excinfo.value.repair_action


def test_every_primitive_reason_code_is_mapped_by_the_transition_taxonomy() -> None:
    """The map from this module's refusals to the transition's must be total.

    It used to default an unknown code to ``transition_lock_identity_changed`` — reporting a
    refusal the map had not learned yet as a lock file whose inode was swapped, a failure that
    did not occur, sending the operator to inspect the lock root instead of the real cause.
    The default is now ``transition_lock_unclassified`` carrying the real code, and this
    asserts the map is total so the default stays unreachable in practice.
    """

    import re

    from shared import coord_projection as cp

    source = Path(tnl.__file__).read_text(encoding="utf-8")
    raised = set(re.findall(r'"(task_note_lock_[a-z_]+)"', source))
    assert raised, "no reason codes found; the extraction is broken, not the map"
    unmapped = sorted(raised - set(cp._TRANSITION_LOCK_REASONS))
    assert not unmapped, (
        "these primitive reason codes have no transition mapping and would surface as "
        f"transition_lock_unclassified: {unmapped}"
    )


def test_the_transition_and_the_writers_default_to_the_same_lock_root() -> None:
    """The one binding the PR did not eliminate, pinned.

    Converted writers and the gate stamp default to ``default_lock_root()``; the transition
    takes its root from ``coord_projection._lock_root``. Those are two places holding one
    agreement about a directory — the PR's own argument against two lock implementations
    applies verbatim: an agreement that serializes nothing the day it stops agreeing, with
    nothing to detect it. So it is detected here.
    """

    from shared import coord_projection as cp

    assert cp._lock_root(None) == tnl.default_lock_root()


def test_an_override_root_is_honoured_by_both_sides(tmp_path: Path) -> None:
    """And the agreement must survive the environment knob that moves one of them.

    Run in a subprocess: ``HAPAX_COORD_DIR`` is read at import time, so checking it in-process
    would mean reloading ``coord_event_log`` and ``coord_projection``, and a reload replaces the
    module objects every other test in the session already holds references to — it broke 54
    unrelated projection tests when tried. A test that damages its neighbours is not a test.
    """

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from shared import coord_projection as cp
                from shared import task_note_lock as tnl
                a, b = cp._lock_root(None), tnl.default_lock_root()
                print("SAME" if a == b else f"DIFFER {{a}} != {{b}}")
                print("UNDER_OVERRIDE" if str(a).startswith(sys.argv[1]) else f"OUTSIDE {{a}}")
                """
            ),
            str(tmp_path / "coord"),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "HAPAX_COORD_DIR": str(tmp_path / "coord")},
        timeout=120,
    )
    assert "SAME" in result.stdout, f"{result.stdout!r} {result.stderr!r}"
    assert "UNDER_OVERRIDE" in result.stdout, f"{result.stdout!r} {result.stderr!r}"


def test_guard_registry_does_not_grow_without_bound(tmp_path: Path) -> None:
    """A long-lived writer must not accumulate one thread guard per task note it ever touched.

    The guards are interned so two threads reach the same object; interning without a matching
    release is a leak, and a daemon that stamps thousands of notes over a run would hold a guard
    for every one of them forever.
    """

    root = tmp_path / "locks"
    before = len(tnl._THREAD_LOCKS)
    for index in range(40):
        with tnl.projected_path_lock(f"task-{index}", (), root=root, timeout=5.0):
            pass
    assert len(tnl._THREAD_LOCKS) == before, (
        f"the guard registry grew from {before} to {len(tnl._THREAD_LOCKS)} entries"
    )
    assert not tnl._THREAD_LOCK_USERS, tnl._THREAD_LOCK_USERS


def test_a_held_guard_is_not_forgotten_while_another_caller_wants_it(tmp_path: Path) -> None:
    """Pruning must count interest, not depth.

    Dropping the entry while a second thread still referenced it would hand that thread a fresh
    object, and two threads holding two different objects exclude nothing — a leak traded for a
    correctness hole.
    """

    root = tmp_path / "locks"
    entered = threading.Event()
    release = threading.Event()
    observed: list[int] = []

    def holder() -> None:
        with tnl.projected_path_lock("task-1", (), root=root, timeout=10.0):
            entered.set()
            release.wait(timeout=10)

    worker = threading.Thread(target=holder, daemon=True)
    worker.start()
    entered.wait(timeout=10)
    try:
        key = (str(tnl._normalized(root)), tnl.lock_names("task-1", ())[0])
        observed.append(tnl._THREAD_LOCK_USERS.get(key, 0))
    finally:
        release.set()
        worker.join(timeout=10)
    assert observed == [1], f"a held guard was not tracked as in use: {observed}"


def test_a_forked_child_does_not_inherit_the_parents_locks(tmp_path: Path) -> None:
    """``fork`` copies the bookkeeping; the child must not act on it.

    Without the at-fork handler the child starts believing it holds everything the parent held
    — ``_HELD`` is process-global and the child's main thread reuses the parent's thread id —
    so it would either re-enter a lock it does not own or, because a different key set counts
    as an expansion, be refused for a lock nobody in the child ever took. The estate's
    claim-publication test forks exactly this way and is what surfaced it.
    """

    import multiprocessing as mp

    root = tmp_path / "locks"
    ctx = mp.get_context("fork")
    result: mp.Queue = ctx.Queue()

    def child(out: mp.Queue) -> None:  # pragma: no cover - runs in the forked child
        try:
            with tnl.projected_path_lock("task-beta", (), root=root, timeout=5.0):
                out.put(("ok", len(tnl._HELD)))
        except tnl.TaskNoteLockError as exc:
            out.put(("refused", exc.reason_code))

    with tnl.projected_path_lock("task-alpha", (), root=root, timeout=5.0):
        assert tnl._HELD, "the parent should be holding something"
        proc = ctx.Process(target=child, args=(result,))
        proc.start()
        outcome = result.get(timeout=30)
        proc.join(timeout=30)

    assert outcome[0] == "ok", f"the forked child inherited the parent's hold: {outcome}"


def test_claim_publication_takes_the_projection_lock_in_one_direction_only() -> None:
    """Containment: the projection lock is taken inside the role lock and nowhere else here.

    ``sdlc_claim``'s role lock is acquired in exactly three places, all inside
    ``_claim_publication_lock``, and the projection lock is taken inside it — so the order is
    always role-then-note. This is a containment check, not the enforcement: the inversion that
    matters (a note-holder calling onward into claim publication) needs no new acquisition site,
    so a site count cannot see it (round 5, claude-1). The direction itself is asserted at the
    moment of use and driven by
    :func:`test_the_role_lock_refuses_while_this_thread_holds_a_projected_path_lock`.
    """

    import re

    from shared import sdlc_claim

    source = Path(sdlc_claim.__file__).read_text(encoding="utf-8")
    stripped = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in source.splitlines())

    takers = re.findall(r"with _claim_publication_lock\(", stripped)
    assert len(takers) == 3, (
        f"the role lock is now taken in {len(takers)} places, not 3 — re-derive the ordering "
        "argument before assuming role-then-note is still the only direction"
    )

    body = re.search(
        r"def _claim_publication_lock\(.*?(?=\ndef |\n@contextmanager)", stripped, re.S
    )
    assert body, "_claim_publication_lock was renamed"
    assert "with projected_path_lock(" in body.group(0), (
        "claim publication no longer takes the projection lock, so its _apply_projections "
        "calls can land inside a transition's pin/install window again"
    )

    # And nothing in this module may take the projection lock anywhere BUT inside the role
    # lock's body — that containment is what makes role-then-note the only direction. (File
    # offset is not lock order: the acquisition inside _claim_publication_lock necessarily
    # appears earlier in the file than its own call sites.)
    uses = len(re.findall(r"with projected_path_lock\(", stripped))
    inside = len(re.findall(r"with projected_path_lock\(", body.group(0)))
    assert uses == inside == 1, (
        f"sdlc_claim takes the projection lock in {uses} places, {inside} of them inside the "
        "role lock — any acquisition outside it could invert the order"
    )


def test_the_role_lock_refuses_while_this_thread_holds_a_projected_path_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The direction, asserted at the moment of use — not inferred from a count of sites.

    Claim publication nests the projection lock inside its role-keyed lock, so role-then-note is
    the only safe order across the two domains. The reverse is hold-and-wait: a note-holder
    sitting on the role lock while a publisher on the other side sits on that note. Both waits
    are bounded, so the failure is mutual refusal rather than a wedge — and it needs no new
    acquisition site to occur, which is why the site count above cannot see it. The role lock
    refuses instead, before it opens anything. Both orders are driven here: the estate's shape
    must work, the inversion must be refused with a typed reason, and the refusal must name what
    was held so the caller can release the right thing.
    """

    from types import SimpleNamespace

    from shared import sdlc_claim
    from shared.sdlc_claim import ClaimPublicationError

    # The nested projected_path_lock inside the role lock uses the estate's default root; point
    # it into tmp so the test holds and checks the same namespace the guard would see.
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    assert tnl.default_lock_root() == tmp_path / "coord" / "task-locks"
    note = tmp_path / "vault" / "active" / "t-1.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ntask_id: t-1\n---\n", encoding="utf-8")
    # _claim_publication_lock reads three attributes of the intent. The rest of a real
    # ClaimPublicationIntent — dispatch binding, note bytes, epoch — has no bearing on lock order.
    intent = SimpleNamespace(task_id="t-1", role="theta-test", note_path=note)
    claim_root = tmp_path / "claim-locks"

    # Role-then-note: the shape the estate takes. It must work, and it must actually take the
    # projection lock inside — otherwise the guard would be guarding nothing.
    with sdlc_claim._claim_publication_lock(intent, lock_root=claim_root):
        assert tnl.held_by_current_thread(), "the role lock did not take the projection lock"
    assert not tnl.held_by_current_thread(), "the projection lock leaked past the role lock"

    # Note-then-role: the inversion. Refused before the role lock is touched.
    with tnl.projected_path_lock("t-1", (note,)):
        with pytest.raises(ClaimPublicationError) as refused:
            with sdlc_claim._claim_publication_lock(intent, lock_root=claim_root):
                raise AssertionError(
                    "the role lock was taken while this thread held a projected-path lock"
                )
    assert refused.value.reason_code == "claim_publication_lock_order_inversion"
    held_names = tnl.lock_names("t-1", (note,))
    assert all(name in str(refused.value) for name in held_names), (
        f"the refusal does not name what was held: {refused.value}"
    )
    assert not tnl.held_by_current_thread()
