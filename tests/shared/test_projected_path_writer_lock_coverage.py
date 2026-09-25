"""Coverage: every writer to a projected task-note path takes the projection lock.

Two things live here.

**End-to-end** — the real CLI tools, racing on one real note, under a redirected ``HOME``.
The row's acceptance shape is "two writers, one flock, no lost copy", and the only way to know
the tools take the lock is to run the tools.

**Conformance** — the inventory itself, as an assertion. The row's floor was four writers
(``cc-stage-advance``, ``cc-scope-widen``, ``cc-task-repair``, the gate's
``_stamp_frontmatter_field``) and named the floor a floor rather than a ceiling. It was right
to: the floor came from one search shape — grep for the literal vault path — and a second shape
over the callers of :mod:`shared.cc_task_root` finds ``cc-claim``, ``cc-close``,
``cc-cascade-unblock`` and ``cc-task-pr-link.sh``, none of which spell the vault themselves.
A list that was assembled by grep will be re-assembled by grep the next time someone adds a
writer, so it is pinned here instead: a file that writes a task note and is not in the
converted set has to be added to one list or the other, with a reason. Scratch classes
are a fourth classified set: a crashed-transition scratch is not a note writer, and
leaving it unnamed made work item 1's recovery-sweep half silently absent.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]


# ───────────────────────────────────────────────────────────── end-to-end, the real tools


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True)
    return root


NOTE = """\
---
type: cc-task
task_id: lock-probe-1
title: "concurrent writer probe"
status: claimed
assigned_to: theta
authority_case: CASE-CAPACITY-ROUTING-001
parent_spec: 30-areas/probe.md
route_metadata_schema: 1
priority: p2
wsjf: 1.0
quality_floor: deterministic_ok
mutation_surface: source
authority_level: support_non_authoritative
effort_class: small
risk_tier: T1
kind: engineering
stage: S6_IMPLEMENTATION
mutation_scope_refs:
  - shared/task_note_lock.py
updated_at: 2026-09-16T00:00:00Z
---

## Session log
"""


def _tool_env(home: Path) -> dict[str, str]:
    """Env for driving converted writers. cc-claim requires HAPAX_SESSION_ID."""
    return {
        **os.environ,
        "HOME": str(home),
        "HAPAX_COORD_DIR": str(home / "coord"),
        "HAPAX_AGENT_ROLE": "theta-test",
        "HAPAX_SESSION_ID": "lock-probe-session",
        "PYTHONPATH": f"{REPO_ROOT}:{os.environ.get('PYTHONPATH', '')}",
    }


@pytest.fixture
def probe(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    home = tmp_path / "home"
    home.mkdir()
    note = _vault(home) / "active" / "lock-probe-1.md"
    note.write_text(NOTE, encoding="utf-8")
    return home, note, _tool_env(home)


def test_cc_stage_advance_waits_for_a_held_projection_lock(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """The tool must be *observably* serialized, not merely importing the module.

    A conformance grep can only see that the name appears. This runs the tool against a lock a
    second process is holding and requires it to wait — the difference between taking a lock and
    mentioning one.
    """

    home, note, env = probe
    root = home / "coord" / "task-locks"

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from pathlib import Path
                from shared import task_note_lock as tnl
                with tnl.projected_path_lock("lock-probe-1", (Path({str(note)!r}),),
                                             root=Path({str(root)!r}), timeout=30.0):
                    print("HELD", flush=True)
                    time.sleep(4)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"
        started = time.monotonic()
        try:
            done = subprocess.run(
                [str(REPO_ROOT / "scripts" / "cc-stage-advance"), "lock-probe-1", "S7_RELEASE"],
                capture_output=True,
                text=True,
                env=env,
                timeout=90,
            )
        except subprocess.TimeoutExpired as exc:
            # Bind the failure here. Referencing `done` in the assertion below after a timeout
            # would raise NameError and hide the actual result, which is that the writer never
            # returned at all.
            raise AssertionError(
                f"cc-stage-advance never returned while the lock was held: {exc}"
            ) from exc
        waited = time.monotonic() - started
    finally:
        holder.wait(timeout=30)

    assert waited > 2.0, (
        f"cc-stage-advance did not wait for the projection lock (returned in {waited:.2f}s); "
        f"stdout={done.stdout!r} stderr={done.stderr!r}"
    )
    assert "S7_RELEASE" in note.read_text(encoding="utf-8")


def test_two_tools_writing_one_note_concurrently_lose_no_copy(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """``cc-stage-advance`` and ``cc-scope-widen`` on one note, at once, both survive.

    Each is a read-modify-write of the whole file. Unserialized, whichever reads first and
    writes last erases the other's field entirely — and neither reports anything wrong, because
    from inside each one the write succeeded.
    """

    _home, note, env = probe
    procs = [
        subprocess.Popen(
            [str(REPO_ROOT / "scripts" / "cc-stage-advance"), "lock-probe-1", "S7_RELEASE"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        ),
        subprocess.Popen(
            [
                str(REPO_ROOT / "scripts" / "cc-scope-widen"),
                "lock-probe-1",
                "--add",
                "shared/coord_projection.py",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        ),
    ]
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, f"writer failed: {out!r} {err!r}"

    final = note.read_text(encoding="utf-8")
    assert "stage: S7_RELEASE" in final, f"the stage advance's copy was lost:\n{final}"
    assert "shared/coord_projection.py" in final, f"the scope widen's copy was lost:\n{final}"


def _gate_stamp_source() -> str:
    """The gate's stamp function, sourced alone.

    The impl script is a gate, not a library: sourcing the whole of it would run the gate's own
    logic, and an earlier draft did exactly that in a prelude that was then overwritten eight
    lines later — dead, and misleading about what was being exercised.
    """

    body = (REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh").read_text(encoding="utf-8")
    root_match = re.search(r"^_cc_gate_repo_root\(\) \{.*?^\}", body, re.M | re.S)
    assert root_match, "the gate's repo-root resolver was renamed; update this test with it"
    match = re.search(r"^_stamp_frontmatter_field\(\) \{.*?^\}", body, re.M | re.S)
    assert match, "the gate's stamp function was renamed; update this test with it"
    return f"SCRIPT_DIR={str(REPO_ROOT / 'hooks' / 'scripts')!r}\n{root_match.group(0)}\n{match.group(0)}\n"


def test_the_gate_s_lock_bound_reaches_the_interpreter(tmp_path: Path) -> None:
    """Ask the interpreter what it inherited; do not read the source.

    Round 5 (gemini-1 critical, claude-1 major): the gate's 5s bound was an env prefix on a
    backslash-continued line with a comment after the continuation. Bash removes the
    backslash-newline before it tokenizes, so the comment was joined onto the assignment and its
    ``#`` ended the command there — the prefix became a plain, unexported shell variable, the
    interpreter never saw it, and the gate waited task_note_lock's 30s default inside a
    tool-call hook, which is the hang the 5s exists to prevent. Every existing test passed: each
    set the variable explicitly, which is the operator-override path, and the override survived
    the defect. This one runs the function with the variable UNSET, with a stand-in ``python3``
    first on PATH that prints what it inherited.
    """

    stand_in = tmp_path / "bin"
    stand_in.mkdir()
    (stand_in / "python3").write_text(
        '#!/usr/bin/env bash\necho "SEEN=${HAPAX_TASK_NOTE_LOCK_TIMEOUT:-unset}"\n',
        encoding="utf-8",
    )
    (stand_in / "python3").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "HAPAX_TASK_NOTE_LOCK_TIMEOUT"}
    env["PATH"] = f"{stand_in}:{env.get('PATH', '')}"
    script = f"{_gate_stamp_source()}\n_stamp_frontmatter_field /dev/null stage S9_DONE"

    default = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env, timeout=30
    )
    assert "SEEN=5" in default.stdout, (
        "the gate's 5s bound never reached the interpreter — the env prefix and the python3 "
        "command must be one logical line with nothing between them.\n"
        f"stdout={default.stdout!r}\nstderr={default.stderr!r}"
    )
    override = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={**env, "HAPAX_TASK_NOTE_LOCK_TIMEOUT": "1"},
        timeout=30,
    )
    assert "SEEN=1" in override.stdout, override.stdout


def test_the_gate_s_effective_bound_is_seconds_not_tens_of_seconds(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """The effect of the bound, with the real interpreter and the variable unset.

    A holder keeps the lock for longer than the 5s bound. A gate whose bound reaches the
    interpreter refuses at ~5s with exit 3. A gate on the 30s default outlives the holder,
    then stamps successfully — a different exit code AND a different note, so the mutant cannot
    pass by timing alone.
    """

    home, note, env = probe
    env = {k: v for k, v in env.items() if k != "HAPAX_TASK_NOTE_LOCK_TIMEOUT"}
    root = home / "coord" / "task-locks"
    before = note.read_text(encoding="utf-8")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from pathlib import Path
                from shared import task_note_lock as tnl
                with tnl.projected_path_lock(None, (Path({str(note)!r}),),
                                             root=Path({str(root)!r}), timeout=30.0):
                    print("HELD", flush=True)
                    time.sleep(10)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"
        started = time.monotonic()
        done = subprocess.run(
            [
                "bash",
                "-c",
                f'{_gate_stamp_source()}\n_stamp_frontmatter_field "{note}" stage S9_DONE',
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        waited = time.monotonic() - started
    finally:
        holder.wait(timeout=30)

    assert done.returncode == 3, (
        f"expected the contention exit (3) at the 5s bound, got {done.returncode} after "
        f"{waited:.1f}s: {done.stderr!r}"
    )
    assert waited < 8.5, f"the gate waited {waited:.1f}s — the 5s bound is not in effect"
    assert note.read_text(encoding="utf-8") == before, "the refused stamp still wrote"


def test_the_gate_stamp_refuses_rather_than_racing_a_held_lock(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """The gate stamps frontmatter; under contention it must refuse, not fail open.

    Failing open is what it did before, and it is what put the gate in the row's writer
    inventory. The stamp not landing is safe — the caller then reports an insufficient stage and
    the operator retries. The stamp landing mid-transition is not.
    """

    home, note, env = probe
    root = home / "coord" / "task-locks"
    before = note.read_text(encoding="utf-8")

    # Source only the functions under test via the shared helper; its docstring
    # explains why the impl script cannot be sourced whole.
    stamp = _gate_stamp_source()

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from pathlib import Path
                from shared import task_note_lock as tnl
                with tnl.projected_path_lock(None, (Path({str(note)!r}),),
                                             root=Path({str(root)!r}), timeout=30.0):
                    print("HELD", flush=True)
                    time.sleep(6)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"
        done = subprocess.run(
            ["bash", "-c", f'{stamp}\n_stamp_frontmatter_field "{note}" stage S9_DONE'],
            capture_output=True,
            text=True,
            env={**env, "HAPAX_TASK_NOTE_LOCK_TIMEOUT": "1"},
            timeout=60,
        )
    finally:
        holder.wait(timeout=30)

    assert done.returncode != 0, "the gate stamped a note held by another writer"
    assert note.read_text(encoding="utf-8") == before, "the refused stamp still wrote"
    assert "stamp skipped" in done.stderr, done.stderr


def _waits_for_a_held_lock(
    argv: list[str],
    note: Path,
    home: Path,
    env: dict[str, str],
    hold: float = 4.0,
    *,
    expect_success: bool = True,
) -> float:
    """Run a writer against a lock a second process holds; return how long it waited.

    The difference between taking a lock and mentioning one. Starting two CLIs and hoping their
    read-modify-write windows overlap does not establish anything — the race may simply not
    happen — so the contention is constructed instead of hoped for.
    """

    root = home / "coord" / "task-locks"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from pathlib import Path
                from shared import task_note_lock as tnl
                with tnl.projected_path_lock(None, (Path({str(note)!r}),),
                                             root=Path({str(root)!r}), timeout=30.0):
                    print("HELD", flush=True)
                    time.sleep({hold})
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"
        started = time.monotonic()
        done = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=120)
        waited = time.monotonic() - started
    finally:
        holder.wait(timeout=60)
    if expect_success:
        assert done.returncode == 0, f"writer failed: {done.stdout!r} {done.stderr!r}"
    return waited


def test_cc_task_repair_waits_for_a_held_projection_lock(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """cc-task-repair under real contention, not a regex over its own source.

    Of the converted writers this was the one whose only evidence was
    ``test_every_converted_writer_actually_takes_the_lock`` — a grep for an import and a
    ``with``. That assertion cannot tell locking the right note from locking the wrong path, a
    mismatched task id, or a lock around a section that does not cover the read. It is an
    implementation echo, and an echo is not a witness.
    """

    home, note, env = probe
    # Remove a scaffolding field so repair has something to write.
    note.write_text(
        note.read_text(encoding="utf-8").replace("route_metadata_schema: 1\n", ""),
        encoding="utf-8",
    )
    waited = _waits_for_a_held_lock(
        [str(REPO_ROOT / "scripts" / "cc-task-repair"), "lock-probe-1"], note, home, env
    )
    assert waited > 2.0, f"cc-task-repair did not wait for the projection lock ({waited:.2f}s)"
    assert "route_metadata_schema" in note.read_text(encoding="utf-8")


def test_cc_scope_widen_waits_for_a_held_projection_lock(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """The same constructed contention for scope-widen.

    Its other coverage is the two-CLI race, which can pass without effective locking whenever
    the two windows happen not to overlap.
    """

    home, note, env = probe
    waited = _waits_for_a_held_lock(
        [
            str(REPO_ROOT / "scripts" / "cc-scope-widen"),
            "lock-probe-1",
            "--add",
            "shared/coord_projection.py",
        ],
        note,
        home,
        env,
    )
    assert waited > 2.0, f"cc-scope-widen did not wait for the projection lock ({waited:.2f}s)"
    assert "shared/coord_projection.py" in note.read_text(encoding="utf-8")


def test_a_real_lifecycle_transition_cannot_enter_a_writer_s_window(tmp_path: Path) -> None:
    """A real ``execute_lifecycle_transition``, not just its lock.

    An earlier draft of this test entered ``_transition_locks`` directly and never used the
    ``FileProjection`` it captured — so it would have stayed green if the real lifecycle entry
    point had stopped acquiring its lock at all, which is precisely the regression it claims to
    guard. This runs the actual transition: preimage pin, atomic install, applied receipt.

    A converted writer holds the projection lock for the note across the attempt. The
    transition must refuse rather than proceed, and the writer's bytes must survive.
    """

    # Build the intent and the event log with the projection suite's own helpers rather than
    # by hand: LifecycleTransitionIntent carries eleven required fields, and a hand-rolled one
    # drifts from the real shape the moment any of them changes.
    transition = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(REPO_ROOT)!r})
        from pathlib import Path
        from shared import coord_projection as cp
        from tests.shared.test_coord_projection import _intent, _log
        cp._LIFECYCLE_EFFECT_ACTIVATION = True

        note = Path(sys.argv[1])
        root = Path(sys.argv[2])
        projection = cp.FileProjection.capture(note, after=b"stage: S7\\n")
        try:
            cp.execute_lifecycle_transition(
                event_log=_log(Path(sys.argv[3])),
                intent=_intent(),
                projections=[projection],
                transaction_root=Path(sys.argv[4]),
                lock_root=root,
            )
            print("TRANSITION-APPLIED", flush=True)
        except cp.LifecycleTransitionError as exc:
            print("TRANSITION-REFUSED", exc.args[0], flush=True)
        """
    )

    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "task-1.md"
    note.write_bytes(b"stage: S6\n")
    root = tmp_path / "locks"

    writer = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from pathlib import Path
                from shared.task_note_lock import projected_path_lock
                note = Path({str(note)!r})
                with projected_path_lock("task-1", (note,),
                                         root=Path({str(root)!r}), timeout=60.0):
                    print("HELD", flush=True)
                    time.sleep(6)
                    note.write_bytes(note.read_bytes() + b"writer-line\\n")
                print("WROTE", flush=True)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert writer.stdout is not None
        assert writer.stdout.readline().strip() == "HELD"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                transition,
                str(note),
                str(root),
                str(tmp_path / "events"),
                str(tmp_path / "transactions"),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "HAPAX_TASK_NOTE_LOCK_TIMEOUT": "2"},
        )
    finally:
        out, err = writer.communicate(timeout=120)

    assert "WROTE" in out, f"{out!r} {err!r}"
    assert "TRANSITION-REFUSED" in result.stdout, (
        "a real lifecycle transition entered a writer's critical section: "
        f"{result.stdout!r} {result.stderr!r}"
    )
    assert b"writer-line" in note.read_bytes(), "the writer's bytes were lost"


def test_cc_task_offer_ready_waits_for_a_held_projection_lock(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """Contention for a writer converted in this round, not a regex over its source.

    The suite's own standard, from `test_cc_task_repair_waits_for_a_held_projection_lock`: a
    grep for an import and a ``with`` is an implementation echo, and an echo is not a witness.
    The note is put into the state that actually drives the promotion, so the tool reaches its
    lock rather than refusing earlier for an unrelated reason and returning instantly — which
    is how the first draft of this test "passed" in 0.03s.
    """

    home, note, env = probe
    note.write_text(
        note.read_text(encoding="utf-8")
        .replace("status: claimed", "status: ready")
        .replace("assigned_to: theta", "assigned_to: unassigned"),
        encoding="utf-8",
    )
    waited = _waits_for_a_held_lock(
        [str(REPO_ROOT / "scripts" / "cc-task-offer-ready"), "lock-probe-1"],
        note,
        home,
        env,
        expect_success=False,
    )
    assert waited > 1.5, f"cc-task-offer-ready did not wait for the lock ({waited:.2f}s)"
    assert "status: offered" in note.read_text(encoding="utf-8")


def test_cc_cascade_unblock_waits_for_a_held_projection_lock(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """Same, for the cascade unblocker — with a blocked note whose dependency is satisfied."""

    home, note, env = probe
    vault = note.parent
    (vault.parent / "closed").mkdir(exist_ok=True)
    (vault.parent / "closed" / "dep-1.md").write_text(
        "---\ntask_id: dep-1\nstatus: done\n---\n", encoding="utf-8"
    )
    blocked = vault / "blocked-1.md"
    blocked.write_text(
        "---\ntask_id: blocked-1\nstatus: blocked\nblocked_reason: waiting\n"
        "depends_on:\n  - dep-1\n---\n\n## Session log\n",
        encoding="utf-8",
    )
    waited = _waits_for_a_held_lock(
        [str(REPO_ROOT / "scripts" / "cc-cascade-unblock")],
        blocked,
        home,
        env,
        expect_success=False,
    )
    assert waited > 1.5, f"cc-cascade-unblock did not wait for the lock ({waited:.2f}s)"


#: Child that takes the projection lock, lands a change while the tool under test is blocked on
#: it, and releases. Kept flat and %%-substituted rather than built with an indented f-string +
#: ``textwrap.dedent``: that combination mis-indented the generated source, the child died before
#: printing ``HELD``, and the test reported it as "the writer never took the lock" — a broken
#: harness wearing the costume of a real finding.
_FIRST_WRITER = """\
import sys, time
sys.path.insert(0, %(repo)r)
from pathlib import Path
from shared import task_note_lock as tnl
note = Path(%(note)r)
with tnl.projected_path_lock(None, (note,), root=Path(%(root)r), timeout=30.0):
    print("HELD", flush=True)
    time.sleep(3)
    text = note.read_text(encoding="utf-8")
    # The marker goes in as the first frontmatter key, so the same first writer serves every
    # note shape the parametrized race uses — not only the one with a stage line.
    assert text.startswith("---\\n"), text[:20]
    note.write_text("---\\n%(marker)s\\n" + text[4:], encoding="utf-8")
print("RELEASED", flush=True)
"""


def _prepare_repair(home: Path, note: Path) -> Path:
    """Remove a scaffolding field so repair has something to write."""

    note.write_text(
        note.read_text(encoding="utf-8").replace("route_metadata_schema: 1\n", ""),
        encoding="utf-8",
    )
    return note


def _prepare_offer_ready(home: Path, note: Path) -> Path:
    """The state that drives the promotion, so the tool reaches its lock instead of refusing
    early for an unrelated reason and returning in 0.03s."""

    note.write_text(
        note.read_text(encoding="utf-8")
        .replace("status: claimed", "status: ready")
        .replace("assigned_to: theta", "assigned_to: unassigned"),
        encoding="utf-8",
    )
    return note


def _prepare_cascade(home: Path, note: Path) -> Path:
    """A blocked sibling whose dependency is satisfied; the race is on the sibling."""

    vault = note.parent
    (vault.parent / "closed").mkdir(exist_ok=True)
    (vault.parent / "closed" / "dep-1.md").write_text(
        "---\ntask_id: dep-1\nstatus: done\n---\n", encoding="utf-8"
    )
    blocked = vault / "blocked-1.md"
    blocked.write_text(
        "---\ntask_id: blocked-1\nstatus: blocked\nblocked_reason: waiting\n"
        "depends_on:\n  - dep-1\n---\n\n## Session log\n",
        encoding="utf-8",
    )
    return blocked


def _prepare_close(home: Path, note: Path) -> Path:
    """cc-close's outcome gate refuses without its durable sink root under HOME."""

    (home / ".cache" / "hapax" / "stage0-durable-sink").mkdir(parents=True, exist_ok=True)
    return note


def _prepare_claim(home: Path, note: Path) -> Path:
    """An offered, claimable note.

    cc-claim's admitted path installs its Gate-0B root under HOME on first use, so the real
    publication machinery runs against this note — the role lock, the projection lock inside
    it, and ``_locked_preflight`` — with no killswitch and no legacy writer. That is also what
    drives ``shared/sdlc_claim.py``'s entry in the inventory.
    """

    (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
    note.write_text(
        note.read_text(encoding="utf-8")
        .replace("status: claimed", "status: offered\nclaimable: true")
        .replace("assigned_to: theta", "assigned_to: unassigned"),
        encoding="utf-8",
    )
    return note


#: Every converted writer the race below can drive on argv, keyed by its UNDER_LOCK entry:
#: (prepare, argv tail, evidence that the tool's own change landed — checked only when it
#: exits 0, since a refusal on a moved note is also a correct outcome).
ANTI_CLOBBER_CASES = {
    "scripts/cc-stage-advance": (None, ["lock-probe-1", "S7_RELEASE"], "stage: S7_RELEASE"),
    "scripts/cc-scope-widen": (
        None,
        ["lock-probe-1", "--add", "shared/coord_projection.py"],
        "shared/coord_projection.py",
    ),
    "scripts/cc-task-repair": (_prepare_repair, ["lock-probe-1"], "route_metadata_schema"),
    "scripts/cc-task-offer-ready": (_prepare_offer_ready, ["lock-probe-1"], "status: offered"),
    "scripts/cc-cascade-unblock": (_prepare_cascade, [], None),
    "scripts/cc-close": (_prepare_close, ["lock-probe-1"], "status: done"),
    "scripts/cc-claim": (_prepare_claim, ["lock-probe-1"], "status: claimed"),
}

#: UNDER_LOCK entries the race cannot reach on argv, each with the test that drives the same
#: property for it. A bare "covered elsewhere" is not a reason; the reason names the test.
ANTI_CLOBBER_DRIVEN_ELSEWHERE = {
    "hooks/scripts/cc-task-gate.impl.sh": (
        "test_the_gate_stamp_does_not_clobber_a_change_made_while_it_waited — the stamp is a "
        "sourced function, raced below with the same first writer"
    ),
    "hooks/scripts/cc-task-pr-link.sh": (
        "tests/test_cc_task_pr_link_hook.py::TestProjectionLock::"
        "test_the_link_does_not_clobber_a_change_made_while_it_waited — PostToolUse JSON on stdin"
    ),
    "shared/sdlc_claim.py": (
        "the scripts/cc-claim case: its admitted publication IS this module, and the change "
        "lands against _locked_preflight inside _claim_publication_lock"
    ),
}


def test_every_converted_writer_is_driven_through_the_anti_clobber_race() -> None:
    """Membership in UNDER_LOCK is not coverage.

    Each entry is either raced here or named with the test that races it, and a writer added
    to UNDER_LOCK fails this until it is one or the other. Round 5 (claude-1): the race covered
    two of nine converted writers, and membership is exactly what round 4's critical passed
    while its read sat ~800 lines above the lock.
    """

    driven = set(ANTI_CLOBBER_CASES) | set(ANTI_CLOBBER_DRIVEN_ELSEWHERE)
    assert driven == set(UNDER_LOCK), (
        "UNDER_LOCK and the anti-clobber drive disagree: "
        f"undriven={sorted(set(UNDER_LOCK) - driven)} "
        f"not_under_lock={sorted(driven - set(UNDER_LOCK))}"
    )
    assert not set(ANTI_CLOBBER_CASES) & set(ANTI_CLOBBER_DRIVEN_ELSEWHERE)


def _race_a_writer_against_a_change(
    home: Path,
    target: Path,
    env: dict[str, str],
    run: Callable[[dict[str, str]], subprocess.CompletedProcess[str]],
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Hold the lock on ``target``, change it while ``run`` waits, release; return the result
    and the note's final text (from ``closed/`` if the writer relocated it)."""

    root = home / "coord" / "task-locks"
    marker = "witness_field: survived-the-wait"
    first = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _FIRST_WRITER
            % {
                # str(), not the Path: %r on a Path renders PosixPath(...), which the child
                # cannot evaluate without the import.
                "repo": str(REPO_ROOT),
                "note": str(target),
                "root": str(root),
                "marker": marker,
            },
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert first.stdout is not None
        held = first.stdout.readline().strip()
        if held != "HELD":
            first.wait(timeout=30)
            raise AssertionError(
                f"the first writer never took the lock: {held!r}; "
                f"stderr={first.stderr.read() if first.stderr else ''!r}"
            )
        started = time.monotonic()
        done = run({**env, "HAPAX_TASK_NOTE_LOCK_TIMEOUT": "30"})
        waited = time.monotonic() - started
    finally:
        out, err = first.communicate(timeout=60)

    assert "RELEASED" in out, f"the first writer did not finish: {out!r} {err!r}"
    # The writer must have reached the lock: the first writer holds it for 3s, so a run that
    # returned sooner refused for some unrelated reason before ever contending — and a
    # surviving marker would then say nothing about its read. This is the assertion that keeps
    # the race from passing vacuously (the first draft of one contention test here "passed" in
    # 0.03s that way).
    assert waited > 2.0, (
        f"the writer returned in {waited:.2f}s without contending for the lock: "
        f"stdout={done.stdout!r} stderr={done.stderr!r}"
    )
    landed = target if target.exists() else target.parent.parent / "closed" / target.name
    assert landed.exists(), (
        f"no note at either name after the race: stdout={done.stdout!r} stderr={done.stderr!r}"
    )
    final = landed.read_text(encoding="utf-8")
    # Either the writer applied its change on top of the other writer's, or it refused because
    # the note changed under it. What it must not do is silently drop the other writer's bytes.
    assert marker in final, (
        "the writer clobbered a change made while it waited for the lock — its read happened "
        f"before the lock, not inside it.\nstdout={done.stdout!r}\nstderr={done.stderr!r}\n"
        f"note:\n{final}"
    )
    return done, final


@pytest.mark.parametrize("rel", sorted(ANTI_CLOBBER_CASES))
def test_a_writer_does_not_clobber_a_change_made_while_it_waited(
    probe: tuple[Path, Path, dict[str, str]], rel: str
) -> None:
    """The property `test_every_converted_writer_actually_takes_the_lock` cannot reach.

    That test keys on the FILE — an import and a ``with`` in the source — so it cannot tell a
    writer that locks its whole read-modify-write from one that locks only the write. The
    difference is invisible to it and fatal in production, and it is exactly how round 4's
    critical survived round 3: ``cc-claim`` was in ``UNDER_LOCK``, passed the membership check,
    and was still deriving its bytes from a read taken ~800 lines before the lock.

    This reaches it behaviourally, for every converted writer that runs on argv. Another
    writer takes the lock first, changes the note, and releases; the tool under test is
    already blocked on that lock when the change lands. If its read happened before the lock,
    it overwrites the change with a stale snapshot and nothing reports anything. If the read
    is inside, the change survives.
    """

    home, note, env = probe
    prepare, argv_tail, evidence = ANTI_CLOBBER_CASES[rel]
    target = prepare(home, note) if prepare else note
    done, final = _race_a_writer_against_a_change(
        home,
        target,
        env,
        lambda run_env: subprocess.run(
            [str(REPO_ROOT / rel), *argv_tail],
            capture_output=True,
            text=True,
            env=run_env,
            timeout=120,
        ),
    )
    if done.returncode == 0 and evidence is not None:
        assert evidence in final, f"{rel} reported success but its own change is absent:\n{final}"


#: A first writer that RELOCATES the note out of both projected names while holding the lock —
#: the one shape that reaches cc-close's "neither active/ nor closed/" refusal.
_MOVING_WRITER = """\
import sys, time
sys.path.insert(0, %(repo)r)
from pathlib import Path
from shared import task_note_lock as tnl
note = Path(%(note)r)
away = note.parent.parent / "_lineage" / note.name
with tnl.projected_path_lock(None, (note,), root=Path(%(root)r), timeout=30.0):
    print("HELD", flush=True)
    time.sleep(3)
    away.parent.mkdir(parents=True, exist_ok=True)
    note.rename(away)
print("RELEASED", flush=True)
"""


def test_cc_close_s_lost_note_refusal_names_the_root_it_actually_resolved(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """The recovery command in the one message an operator reaches when a note is lost.

    It used to hardcode ``~/Documents/Personal/20-projects/hapax-cc-tasks`` while every other
    path in the tool came from ``shared/cc_task_root`` — so under a redirected root (this
    suite's HOME, a moved work plane) the command it named looked in the wrong place, exactly
    when it mattered (round 5, claude-1). The note is moved out from under the close while the
    close waits on the lock; the refusal must name the root the tool resolved, not a literal.
    """

    home, note, env = probe
    _prepare_close(home, note)
    vault_root = note.parent.parent
    root = home / "coord" / "task-locks"
    first = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _MOVING_WRITER % {"repo": str(REPO_ROOT), "note": str(note), "root": str(root)},
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert first.stdout is not None
        assert first.stdout.readline().strip() == "HELD"
        done = subprocess.run(
            [str(REPO_ROOT / "scripts" / "cc-close"), "lock-probe-1"],
            capture_output=True,
            text=True,
            env={**env, "HAPAX_TASK_NOTE_LOCK_TIMEOUT": "30"},
            timeout=120,
        )
    finally:
        out, err = first.communicate(timeout=60)

    assert "RELEASED" in out, f"the moving writer did not finish: {out!r} {err!r}"
    assert done.returncode == 1, (
        f"a lost note must be exit 1 (lock contention is 3), got {done.returncode}: {done.stderr!r}"
    )
    assert "neither active/ nor closed/" in done.stderr, done.stderr
    assert f"ls {vault_root}/*/lock-probe-1*" in done.stderr, (
        f"the recovery command does not name the resolved root {vault_root}:\n{done.stderr}"
    )
    assert "~/Documents/Personal" not in done.stderr, done.stderr


def test_cc_close_lock_contention_exits_3_not_1(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """Lock contention is exit 3; a lost note is exit 1. Flattening them is the defect.

    Sibling writers (cc-claim, the gate stamp) use 3 for ``TaskNoteLockError``. cc-close
    used 1 for both, so a wrapper could not tell a retryable wait from a genuinely
    lost note without parsing stderr.
    """

    home, note, env = probe
    _prepare_close(home, note)
    root = home / "coord" / "task-locks"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from pathlib import Path
                from shared import task_note_lock as tnl
                with tnl.projected_path_lock(None, (Path({str(note)!r}),),
                                             root=Path({str(root)!r}), timeout=30.0):
                    print("HELD", flush=True)
                    time.sleep(10)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"
        done = subprocess.run(
            [str(REPO_ROOT / "scripts" / "cc-close"), "lock-probe-1"],
            capture_output=True,
            text=True,
            env={**env, "HAPAX_TASK_NOTE_LOCK_TIMEOUT": "1"},
            timeout=30,
        )
    finally:
        holder.terminate()
        holder.wait(timeout=30)
    assert done.returncode == 3, (
        f"lock contention must be exit 3, not {done.returncode}: {done.stderr!r}"
    )
    assert "REFUSED" in done.stderr, done.stderr


def test_cc_task_offer_ready_refuses_when_the_note_moved_during_acquisition(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """Re-resolve under the lock; a relocated note must not traceback FileNotFoundError."""

    home, note, env = probe
    _prepare_offer_ready(home, note)
    root = home / "coord" / "task-locks"
    first = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _MOVING_WRITER % {"repo": str(REPO_ROOT), "note": str(note), "root": str(root)},
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert first.stdout is not None
        assert first.stdout.readline().strip() == "HELD"
        done = subprocess.run(
            [str(REPO_ROOT / "scripts" / "cc-task-offer-ready"), "lock-probe-1"],
            capture_output=True,
            text=True,
            env={**env, "HAPAX_TASK_NOTE_LOCK_TIMEOUT": "30"},
            timeout=120,
        )
    finally:
        out, err = first.communicate(timeout=60)

    assert "RELEASED" in out, f"{out!r} {err!r}"
    assert done.returncode != 0, f"promoted a note that had left active/: {done.stderr!r}"
    assert "Traceback" not in done.stderr, done.stderr
    assert "moved while acquiring its lock" in done.stderr, done.stderr
    assert "rerun to act on its current position" in done.stderr, done.stderr


def test_the_gate_stamp_does_not_clobber_a_change_made_while_it_waited(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """The same race for the gate's stamp, which is a sourced function rather than a CLI."""

    home, note, env = probe
    done, final = _race_a_writer_against_a_change(
        home,
        note,
        env,
        lambda run_env: subprocess.run(
            [
                "bash",
                "-c",
                f'{_gate_stamp_source()}\n_stamp_frontmatter_field "{note}" stage S9_DONE',
            ],
            capture_output=True,
            text=True,
            env=run_env,
            timeout=120,
        ),
    )
    assert done.returncode == 0, f"the stamp did not land after waiting: {done.stderr!r}"
    assert "stage: S9_DONE" in final, final


# ───────────────────────────────────────────────────────────── conformance: the inventory

#: Writers converted to take the projection lock. Each must still take it.
UNDER_LOCK = (
    "scripts/cc-stage-advance",
    "scripts/cc-scope-widen",
    "scripts/cc-task-repair",
    "hooks/scripts/cc-task-gate.impl.sh",
    "hooks/scripts/cc-task-pr-link.sh",
    "scripts/cc-task-offer-ready",
    "scripts/cc-cascade-unblock",
    "scripts/cc-close",
    "scripts/cc-claim",
    "shared/sdlc_claim.py",
)

#: Files that name the vault and write, but are NOT task-note writers — each with the reason
#: it is out of scope. A bare "not a writer" is not a reason; the reason has to say what it
#: writes instead, so the next person can check it rather than trust it.
NOT_A_TASK_NOTE_WRITER = {
    "shared/task_note_lock.py": "the lock primitive itself",
    "shared/coord_projection.py": "owns the transition; takes the lock by construction",
    "agents/studio_compositor/durf_source.py": "reads notes for overlay copy",
    "agents/operator_current_state/collector.py": "reads notes",
    "agents/drift_detector/probes_executive.py": "reads notes",
    "agents/deliberative_council/capability_admission.py": "reads notes",
    "agents/coordination_tui/data.py": "read-only TUI data",
    "agents/coordination_tui/app.py": "read-only TUI",
    "agents/content_id_watcher/__init__.py": "reads notes",
    "shared/task_graph_tree_effect_scorer.py": "reads notes",
    "shared/public_gate_receipts.py": "writes receipts, not notes",
    "shared/github_public_surface.py": "reads notes for the public surface",
    "shared/scheduler_readiness_reconciler.py": "reads notes; writes no note",
    "shared/sdlc_invariants.py": "read-only invariant monitor",
    "shared/cc_task_root.py": "resolver only",
    "hooks/scripts/sense_reissue_capture.py": "writes its own capture JSONL",
    "hooks/scripts/cc-task-root.sh": "resolver only",
    "hooks/scripts/session-context.sh": "read-only session banner",
    "hooks/scripts/pr-release-gate.sh": "read-only release precheck",
    "hooks/scripts/authorization-packet-validator.sh": "read-only validator",
    "hooks/scripts/work-resolution-gate.sh": "read-only branch/PR gate",
    "hooks/scripts/cc-task-closure-gate.sh": "read-only closure gate",
    "scripts/cc-hygiene-dashboard-renderer.py": "renders the dashboard, not a note",
    "scripts/cc-hygiene-sweeper.py": "read-only sweep plus ntfy",
    "scripts/cc-close-sibling-check.py": "read-only check",
    "scripts/check-peer-glob-coherence.py": "read-only check",
    "scripts/check-audio-authority-case.py": "read-only check",
    "scripts/cc-task-lint": "read-only lint over the vault",
    "scripts/cc_hygiene/dashboard.py": "writes the _dashboard/ markdown, never a task note",
    "scripts/cc_hygiene/ntfy.py": "writes its own notification state JSON",
    "scripts/cc-pr-review-dispatch.py": "writes review dossiers under _evidence/, not notes",
    "scripts/epistemic_quality_dataset.py": "reads notes; writes JSONL datasets elsewhere",
    "scripts/cc-phase-advance.py": "writes request notes under a different root",
    "shared/policy_decide.py": "vault paths appear only in test fixtures/allowlists",
    "shared/merge_queue_lineage.py": "vault path appears only inside a parsing regex",
    "shared/capability_surface_delta.py": "reads active/ to render a delta report",
    "scripts/check-cc-task-vault-shape.py": "read-only vault shape checker",
    "scripts/cc_hygiene/checks.py": "read-only hygiene checks",
    "hooks/scripts/hooks-doctor.sh": "reports hook wiring; writes no note",
    "scripts/scheduler-readiness-unblock-reconcile.py": "writes no note (reconcile report only)",
}

#: Task-note writers the sweep found that this change does NOT route through the lock.
#:
#: Every entry is an OPEN HAZARD with a named owner — nothing read-only belongs here, and
#: nothing already under the lock belongs here. An earlier revision used it as a catch-all
#: for anything the sweep matched, which made the one artefact meant to say "these files are
#: unprotected" unable to say it: read-only linters sat beside real writers, the lock module
#: itself was filed as a hazard, and nine keys differed from a real entry only by trailing
#: whitespace (so they matched nothing — _candidate_files() strips every line) and were
#: reasoned "duplicate guard". A list that cannot be read is not a safeguard.
KNOWN_UNCONVERTED = {
    "scripts/cc-migration-capability": "migration tool, run by hand",
    "scripts/cc-pr-merge-watcher.py": "daemon writer; convert with the daemon pass",
    "scripts/cc-pr-autoqueue.py": "daemon writer; convert with the daemon pass",
    "scripts/protected-lane-revive-reconcile.py": "reconciler; convert with the daemon pass",
    "scripts/refused_lifecycle_classify.py": "refused/ lifecycle; convert with the daemon pass",
    "scripts/refused_lifecycle_migrate_schema.py": "one-shot schema migration",
    "scripts/migrate_native_tasks_to_vault.py": "one-shot import, runs before any transition",
    "scripts/downstream_contribution_ledger_v0.py": "appends a report note, not a task note",
    "scripts/downstream_contribution_measurement_design.py": "same",
    "scripts/audit-route-metadata-seed-candidates.py": "writes an audit report",
    "scripts/braided_value_snapshot_runner.py": "reads notes; writes a snapshot",
    "scripts/velocity_report_evidence_snapshot.py": "writes an evidence snapshot",
    "scripts/rag_documents_v2_shadow.py": "writes a shadow index",
    "scripts/cc-task-backfill-nogo": "backfill tool, run by hand",
    "hooks/scripts/cc-task-gate-bootstrap.py": "creates a new note; no transition can exist yet",
    "agents/coordinator/core.py": "coordinator note writer; convert with the daemon pass",
    "agents/triage_officer/core.py": "triage writer; convert with the daemon pass",
    "agents/refused_lifecycle/runner.py": "refused/ lifecycle; convert with the daemon pass",
    "agents/refused_lifecycle/state.py": "state helper for the above",
    "agents/marketing/cc_task_cross_linker.py": "cross-linker; convert with the daemon pass",
    "agents/relay_to_cc_tasks.py": "creates new notes from relay items",
    "agents/request_decomposer/writer.py": "creates new request notes",
    "agents/jr_spark_auto_consumer/consumer.py": "creates new notes from spark items",
    "agents/interview_compass.py": "writes its own compass file",
    "agents/publication_bus/refusal_brief_daemon.py": "writes refusal briefs",
    "agents/playwright_grant_submission_runner/__init__.py": "grant runner; reads notes",
    "agents/playwright_grant_submission_runner/package.py": "grant packaging",
    "shared/gate0b_claim_publication_install.py": "installs the claim-publication machinery",
    "shared/p0_incident_intake.py": "creates new incident notes",
    "shared/recovery_governor.py": "recovery writer; convert with the daemon pass",
    "shared/sdlc_close.py": "correct but has no production caller; scripts/cc-close is the live closer and is now under the lock",
}


#: Scratch filename classes. Work item 1 pre-registered recovery-sweep discovery of
#: every class, not only ``scratch.path.name``. Fallback B (PR #4667) introduces
#: pin / holding / spent with random transition names the current glob
#: (``.*.transition-scratch``) does not discover. That half of item 1 is deferred
#: here rather than silently absent: a class named in a scratch constructor that is
#: in none of the classified sets fails CI.
#:
#: Each deferred entry is ``(reason, owner)``. The owner is the named pass that
#: lands discovery — the NFS-fallback row that introduces the three classes.
SCRATCH_RECOVERY_DEFERRED: dict[str, tuple[str, str]] = {
    "pin": (
        "fallback-B preimage pin; random transition name, recovery glob does not discover it",
        "coord-projection-nfs-fallback-20260913",
    ),
    "holding": (
        "fallback-B in-flight holding; random transition name, recovery glob does not discover it",
        "coord-projection-nfs-fallback-20260913",
    ),
    "spent": (
        "fallback-B spent/terminal; random transition name, recovery glob does not discover it",
        "coord-projection-nfs-fallback-20260913",
    ),
}

#: Live constructor suffix the leftover-scratch assertions already glob.
SCRATCH_RECOVERY_DISCOVERED: dict[str, str] = {
    "transition-scratch": (
        "current ``_scratch_for`` suffix; leftover assertions glob ``.*.transition-scratch``"
    ),
    "transition-tmp": "transient sibling of transition-scratch in _TRANSIENT_SCRATCH_SUFFIXES",
    "transition-abandoned": "foreign scratch moved aside by _move_aside_atomically",
    "transition-consumed": "consumed operand named inside a scratch constructor",
    "transition-safety": "safety-copy operand named inside a scratch constructor",
    "transition-staged": "staged operand named inside a scratch constructor",
    "transition-withdrawn": "withdrawn operand named inside a scratch constructor",
}


#: The search shapes, unioned. One grep's silence is a fact about the grep, and this list has
#: grown once per lesson: shape A (the literal vault path) could not see the callers of the
#: cc_task_root resolver, which is how cc-claim, cc-close and cc-task-pr-link went unlisted in
#: the row's floor of four; shape C could not see shared/sdlc_claim.py, which names neither the
#: vault nor the resolver and reaches projected paths through coord_projection's own projection
#: helpers. Adding a shape is cheaper than trusting a silence.
SEARCH_SHAPES = (
    "hapax-cc-tasks",
    r"cc_task_root|cc-task-root|CC_TASK_ROOT",
    r"_apply_projections|FileProjection|_cas_project",
)


def _candidate_files() -> set[str]:
    """Union of the search shapes. One grep's silence is a fact about the grep."""

    found: set[str] = set()
    for pattern in SEARCH_SHAPES:
        out = subprocess.run(
            [
                "grep",
                "-rlE",
                pattern,
                "--include=*.py",
                "--include=*.sh",
                "--include=cc-*",
                "scripts",
                "hooks",
                "shared",
                "agents",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        ).stdout
        found |= {
            rel
            for rel in (line.strip() for line in out.splitlines())
            if rel and "__pycache__" not in Path(rel).parts and not rel.endswith((".pyc", ".pyo"))
        }
    return found


def _scratch_classes_named_in_constructors() -> set[str]:
    """Filename-class tokens used to name projection scratches.

    Work item 1 required recovery-sweep discovery of *classes*, not only
    ``scratch.path.name``. The live constructor is ``_scratch_for``
    (``.transition-scratch``). Fallback B adds pin / holding / spent as sibling
    suffixes. A new suffix in a ``*scratch*`` constructor that is in neither
    ``SCRATCH_RECOVERY_DISCOVERED`` nor ``SCRATCH_RECOVERY_DEFERRED`` fails CI.
    """

    source = (REPO_ROOT / "shared" / "coord_projection.py").read_text(encoding="utf-8")
    stripped = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in source.splitlines())
    found: set[str] = set()
    for match in re.finditer(
        r"^def (_\w*scratch\w*)\(.*?(?=\n@|\ndef |\nclass )", stripped, re.M | re.S
    ):
        found.update(re.findall(r'\.([A-Za-z][A-Za-z0-9_-]+)"', match.group(0)))
    assert found, (
        "no scratch filename class was found in coord_projection scratch constructors; "
        "the constructor scan is broken, and its silence is a fact about the search"
    )
    return found


def test_every_converted_writer_actually_takes_the_lock() -> None:
    """Assert the call shape, with comments stripped.

    A conformance grep that reads its own explanatory comments passes on a file that only
    *talks* about the lock. So the import and the call are matched separately, on
    comment-stripped source, and the call must be a real ``with`` of the context manager.
    """

    for rel in UNDER_LOCK:
        path = REPO_ROOT / rel
        source = path.read_text(encoding="utf-8")
        stripped = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in source.splitlines())
        assert re.search(
            r"from\s+shared\.task_note_lock\s+import\s+[^\n]*projected_path_lock", stripped
        ), f"{rel} does not import the projection lock"
        assert re.search(
            r"(with\s+projected_path_lock\s*\(|lock\s*=\s*projected_path_lock\s*\()", stripped
        ), f"{rel} imports the projection lock but never takes it"


def test_the_writer_inventory_has_no_unclassified_file() -> None:
    """A new task-note writer or scratch class must be classified, not silently added.

    This is the part that keeps the inventory a floor. The row's floor of four came from one
    search shape and missed ``cc-claim`` and ``cc-close``; the same thing happens again the
    moment the list lives only in a commit message. Anything the sweep finds must be in exactly
    one of: converted, not-a-note-writer, or known-unconverted-with-a-reason. Scratch classes
    are a fourth set: a crashed-transition scratch is none of those, and work item 1's
    recovery-sweep half is deferred here with a named owner rather than silently absent.
    """

    candidates = _candidate_files()
    # A sweep that finds nothing would make every assertion below vacuously true — a broken
    # grep, a wrong cwd or a renamed directory would read as "no unclassified writers" and this
    # test, the PR's durable safeguard, would pass while guarding nothing. Assert the sweep
    # worked before trusting its silence.
    assert len(candidates) > 40, (
        f"the writer sweep found only {len(candidates)} candidates; it is broken, and its "
        "silence is a fact about the search rather than about the estate"
    )
    for anchor in UNDER_LOCK:
        assert anchor in candidates, (
            f"the sweep no longer finds {anchor}, a file this test knows is a writer — "
            "the search shapes in _candidate_files() have stopped matching"
        )

    classified = (
        set(UNDER_LOCK)
        | set(NOT_A_TASK_NOTE_WRITER)
        | set(KNOWN_UNCONVERTED)
        | set(SCRATCH_RECOVERY_DEFERRED)
        | set(SCRATCH_RECOVERY_DISCOVERED)
    )
    unclassified = sorted(rel for rel in candidates if rel not in classified)
    assert not unclassified, (
        "these files reach the cc-task vault and are in no inventory list:\n  "
        + "\n  ".join(unclassified)
        + "\n\nClassify each one: add it to UNDER_LOCK (and route it through "
        "projected_path_lock), to NOT_A_TASK_NOTE_WRITER with what it writes instead, or to "
        "KNOWN_UNCONVERTED with the pass that will convert it."
    )

    constructed = _scratch_classes_named_in_constructors()
    scratch_classified = set(SCRATCH_RECOVERY_DEFERRED) | set(SCRATCH_RECOVERY_DISCOVERED)
    assert {"pin", "holding", "spent"} <= set(SCRATCH_RECOVERY_DEFERRED), (
        "fallback-B's three scratch classes must stay in SCRATCH_RECOVERY_DEFERRED "
        "until a named pass lands recovery-sweep discovery"
    )
    overlap = set(SCRATCH_RECOVERY_DEFERRED) & set(SCRATCH_RECOVERY_DISCOVERED)
    assert not overlap, f"scratch class listed as both discovered and deferred: {sorted(overlap)}"
    for name, (reason, owner) in SCRATCH_RECOVERY_DEFERRED.items():
        assert reason.strip(), f"{name} is deferred without a reason"
        assert owner.strip(), f"{name} is deferred without a named owner"
    unclassified_scratch = sorted(constructed - scratch_classified)
    assert not unclassified_scratch, (
        "these scratch classes are named in a constructor and in no inventory list:\n  "
        + "\n  ".join(unclassified_scratch)
        + "\n\nClassify each one: add it to SCRATCH_RECOVERY_DISCOVERED (and glob it "
        "from the recovery sweep) or to SCRATCH_RECOVERY_DEFERRED with a reason and "
        "a named owner pass."
    )


def test_the_transition_and_the_writers_share_one_lock_implementation() -> None:
    """``coord_projection`` must delegate, not re-implement.

    Two implementations that agree today serialize nothing the day they stop agreeing, and
    nothing would detect it. This asserts the delegation rather than the agreement.
    """

    source = (REPO_ROOT / "shared" / "coord_projection.py").read_text(encoding="utf-8")
    stripped = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in source.splitlines())
    body = re.search(r"^def _transition_locks\(.*?(?=\n@|\ndef |\nclass )", stripped, re.M | re.S)
    assert body, "_transition_locks was renamed; update this test with it"
    assert "task_note_lock.projected_path_lock" in body.group(0), (
        "_transition_locks no longer delegates to the shared primitive — the transition and the "
        "task-note writers are two lock domains again"
    )
    assert "fcntl.flock" not in body.group(0), (
        "_transition_locks took a flock of its own; the primitive is shared/task_note_lock.py"
    )


def test_the_contract_docstring_matches_the_inventory() -> None:
    """The in-code concurrency contract must name exactly the writers that are converted.

    `_transition_locks`'s docstring is the single in-code statement of this contract, and
    #4667's rebase and its C1 disposition are read against it. It has now been wrong in both
    directions: once claiming writers took the lock that did not, and once — after they were
    converted — still saying they did not, which three reviewer families filed independently.
    A prose claim that no test reads will drift again, so this reads it.
    """

    source = (REPO_ROOT / "shared" / "coord_projection.py").read_text(encoding="utf-8")
    body = re.search(
        r"^@contextmanager\ndef _transition_locks\(.*?\n    \"\"\"(.*?)\"\"\"", source, re.M | re.S
    )
    assert body, "_transition_locks docstring not found in the expected shape"
    contract = body.group(1)

    inside = contract.split("**Which are still outside it.**")[0]
    for rel in UNDER_LOCK:
        name = Path(rel).name.removesuffix(".impl.sh").removesuffix(".sh").removesuffix(".py")
        assert name in inside, (
            f"{rel} is in UNDER_LOCK but the contract docstring does not name it as inside the "
            "domain — the in-code contract understates what this PR ships"
        )

    outside = contract.split("**Which are still outside it.**")[-1]
    for rel in UNDER_LOCK:
        name = Path(rel).name.removesuffix(".impl.sh").removesuffix(".sh").removesuffix(".py")
        assert f"``{name}``" not in outside.split("So the fail-open hazard")[0], (
            f"{rel} is converted but the contract docstring still lists it as outside the "
            "domain — this is the direction that misled three reviewer families"
        )
