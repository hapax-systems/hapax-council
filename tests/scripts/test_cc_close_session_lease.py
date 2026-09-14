"""cc-close must clear the session-keyed lease, not just the legacy one.

cc-claim (reform Phase 1, cluster 6) writes TWO claim files for a session:
the legacy ``cc-active-task-<role>`` and the session-keyed
``cc-active-task-<role>-<session_id>`` (agent-role.sh ``hapax_session_id``).
cc-close historically removed only the legacy file, leaking the session-keyed
lease until its 6h TTL — and the gate reads the session-keyed file FIRST, so it
kept seeing the just-closed task. Regression coverage for reform finding
#12/#13: cc-close must clear BOTH lease forms (the current session's only, and
only when the file still names the task being closed).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-close"

# Identity env that agent-role.sh consults to resolve role / session id. The
# session running pytest sets several of these (HAPAX_AGENT_NAME, CLAUDE_ROLE,
# CLAUDE_CODE_SESSION_ID, ...); stripping them keeps the subprocess role/session
# deterministic instead of leaking the harness lane's identity into the script.
_IDENTITY_ENV = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_INTERFACE",
    "HAPAX_SESSION_ID",
    "CLAUDE_ROLE",
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_ROLE",
    "CODEX_HOME",
)


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _write_task(vault_root: Path, task_id: str, *, status: str = "in_progress") -> Path:
    path = vault_root / "active" / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: {status}
            completed_at:
            updated_at:
            pr:
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )
    return path


def _cache(home: Path) -> Path:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _run_close(
    home: Path, task_id: str, *, role: str, session_id: str | None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = role
    if session_id is not None:
        env["HAPAX_SESSION_ID"] = session_id
    # --status withdrawn isolates the claim-clearing block (the done-only gates —
    # rapid-close, AC checklist, PR-merge — are skipped; the claim clear runs for
    # every terminal status).
    return subprocess.run(
        ["bash", str(SCRIPT), task_id, "--status", "withdrawn"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cc_close_clears_both_legacy_and_session_keyed_lease(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    legacy = cache / "cc-active-task-eta"
    session = cache / "cc-active-task-eta-sess123"
    legacy_sidecar = cache / "cc-claim-epoch-eta"
    session_sidecar = cache / "cc-claim-epoch-eta-sess123"
    legacy.write_text("foo\n", encoding="utf-8")
    session.write_text("foo\n", encoding="utf-8")
    legacy_sidecar.write_text("1780000000 foo\n", encoding="utf-8")
    session_sidecar.write_text("1780000000 foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id="sess123")

    assert result.returncode == 0, result.stderr
    assert not legacy.exists(), f"legacy lease not cleared\nstdout={result.stdout}"
    assert not legacy_sidecar.exists(), f"legacy epoch sidecar leaked\nstdout={result.stdout}"
    assert not session.exists(), (
        f"session-keyed lease leaked (finding #12/#13)\nstdout={result.stdout}"
    )
    assert not session_sidecar.exists(), f"session epoch sidecar leaked\nstdout={result.stdout}"


def test_cc_close_preserves_session_lease_naming_a_different_task(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    session = cache / "cc-active-task-eta-sess123"
    sidecar = cache / "cc-claim-epoch-eta-sess123"
    session.write_text("other-task\n", encoding="utf-8")
    sidecar.write_text("1780000000 other-task\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id="sess123")

    assert result.returncode == 0, result.stderr
    assert session.exists(), "a session lease for different work must not be clobbered"
    assert sidecar.exists(), "a sidecar for different work must not be clobbered"
    assert session.read_text(encoding="utf-8").strip() == "other-task"


def test_cc_close_without_session_id_still_clears_legacy(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    legacy = cache / "cc-active-task-eta"
    legacy.write_text("foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id=None)

    assert result.returncode == 0, result.stderr
    assert not legacy.exists(), f"legacy lease not cleared\nstdout={result.stdout}"


def test_cc_close_clears_a_lease_for_this_task_held_by_another_session(
    tmp_path: Path,
) -> None:
    """The stale-marker leak: cc-close swept one session key, not the role.

    cc-claim's lease scan globs ``cc-active-task-<role>-*``; cc-close cleared
    only ``<role>`` and ``<role>-<closing session's id>``. So a marker written by
    session A and closed by session B survived until the 6h TTL, and the live
    marker set drifted away from the vault SSOT with nothing to reconcile it
    (measured 2026-09-13: cc-active-task-cx-crit naming a CLOSED_DONE task).

    This leak is largely MASKED today by the inherited-session-id defect — sibling
    lanes share one id, so the closing session usually presents the claiming
    session's key. Minting fresh ids per launch removes that accident and makes
    every mid-task lane restart leave a guaranteed orphan, so the two fixes ship
    together.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    # Claimed by session A (a lane that has since restarted), closed by session B.
    stale = cache / "cc-active-task-eta-3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
    stale_sidecar = cache / "cc-claim-epoch-eta-3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
    stale.write_text("foo\n", encoding="utf-8")
    stale_sidecar.write_text("1780000000 foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id="b8e2d7c4-1a55-4f93-8c60-77ad3e9b0125")

    assert result.returncode == 0, result.stderr
    assert not stale.exists(), (
        "a lease naming the just-closed task survived because it was keyed to a "
        f"different session — CLOSED_DONE left a live marker\nstdout={result.stdout}"
    )
    assert not stale_sidecar.exists(), "the orphaned epoch sidecar leaked too"


def test_cc_close_orphan_sweep_spares_other_roles(tmp_path: Path) -> None:
    """The sweep is keyed to THIS role; another lane's marker is not ours to clear."""
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    other = cache / "cc-active-task-epsilon-sessX"
    other.write_text("foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id="b8e2d7c4-1a55-4f93-8c60-77ad3e9b0125")

    assert result.returncode == 0, result.stderr
    assert other.exists(), (
        "cc-close cleared a DIFFERENT role's claim marker — a role may only retire its own leases"
    )


def test_cc_close_orphan_sweep_spares_a_role_sharing_its_prefix(
    tmp_path: Path,
) -> None:
    """`cx-blue` must not sweep `cx-blue-shadow`'s lease.

    The sweep globs `cc-active-task-<role>-*`, which is prefix-based, so a role
    whose name extends another's is caught by it. The same-task guard does NOT
    save us here: two roles naming one task is precisely the contested state the
    hygiene check routes to operator-adjudication, so deleting it destroys the
    contention evidence. The existing eta-vs-epsilon case cannot detect this —
    those names share no prefix.

    A globbed key is retired only when its remainder is a session id this system
    mints (uuid4, or the alpha-infixed last resort); `shadow-<uuid>` is neither.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    other_role = cache / "cc-active-task-cx-blue-shadow-9d4e1f77-2a3b-4c58-b0e6-1f2a3b4c5d6e"
    other_role.write_text("foo\n", encoding="utf-8")
    mine = cache / "cc-active-task-cx-blue-3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
    mine.write_text("foo\n", encoding="utf-8")

    result = _run_close(
        home, "foo", role="cx-blue", session_id="b8e2d7c4-1a55-4f93-8c60-77ad3e9b0125"
    )

    assert result.returncode == 0, result.stderr
    assert other_role.exists(), (
        "cc-close swept a DIFFERENT role's lease because its name extends this "
        f"role's — contention evidence destroyed\nstdout={result.stdout}"
    )
    assert not mine.exists(), (
        f"this role's own foreign-session lease was not swept\nstdout={result.stdout}"
    )


def test_cc_close_prefers_the_exact_task_over_a_prefix_neighbour(tmp_path: Path) -> None:
    """`cc-close t1` must not select `t1-next.md`.

    The descriptor glob ran before the exact filename, so with both notes present
    cc-close withdrew a DIFFERENT, live task — and cc-hygiene's remediation emits
    exactly this command shape, so following the runbook verbatim could close
    unrelated work.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "t1")
    _write_task(vault, "t1-next")

    result = _run_close(home, "t1", role="eta", session_id=None)

    assert result.returncode == 0, result.stderr
    assert not (vault / "active" / "t1.md").exists(), "the exact task was not closed"
    assert (vault / "active" / "t1-next.md").exists(), (
        f"cc-close closed the prefix neighbour instead\nstdout={result.stdout}"
    )


def test_cc_close_refuses_a_note_whose_task_id_disagrees(tmp_path: Path) -> None:
    """Filename conventions are not identity; the note's own task_id is.

    The glob can only ever match a prefix, so a descriptor-suffixed neighbour is
    reachable for a shorter id. Comparing the selected note's declared task_id
    closes that without relying on naming discipline.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "t1-next")  # declares task_id: t1-next

    result = _run_close(home, "t1", role="eta", session_id=None)

    assert result.returncode == 2, (
        f"cc-close accepted a note declaring a different task\nstdout={result.stdout}"
    )
    assert "declares task_id" in result.stderr, result.stderr
    assert (vault / "active" / "t1-next.md").exists(), "the wrong note was mutated"


def test_cc_close_guard_failure_spares_the_lease_rather_than_deleting_it(
    tmp_path: Path,
) -> None:
    """If the foreign-lease guard cannot run, the lease survives.

    The guard delegates to shared.session_identity through `python3 -I -`. Its
    failure disposition is the whole safety question: a fail-OPEN branch would
    delete another role's live lease, which is exactly the contested-claim evidence
    the hygiene check routes to operator-adjudication rather than deleting. This
    forces the subprocess to fail by putting a python3 on PATH that always exits
    non-zero, and asserts the foreign lease is still there.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    foreign = cache / "cc-active-task-eta-3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
    foreign.write_text("foo\n", encoding="utf-8")

    # Fail ONLY the foreign-lease guard. A python3 that always exits 70 kills
    # cc-close at its note rewrite, long before the predicate — so the
    # marker-survives assertion stayed green even with the predicate deleted. And
    # matching on `-I -` alone is too broad: the frontmatter identity guard uses
    # that shape too, and failing it refuses the close before cleanup.
    #
    # Discriminated on the guard's own `lease-guard` first argument. Argument COUNT
    # stood here for two rounds and broke the moment another `python3 -I -` call
    # gained a third positional — which is what a count-based heuristic is always
    # one edit away from. The subprocess now names itself.
    #
    # It exits **1**, not 70, on purpose: exit 1 is what an ImportError or any
    # other uncaught Python exception produces, and that is the failure this
    # handler used to misread as "not this role's lease". Injecting an exotic code
    # tested only the exotic case. The predicate now returns 3 for a real negative,
    # so 1 is unambiguously an execution failure.
    real_python = shutil.which("python3")
    assert real_python is not None
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    broken = fakebin / "python3"
    broken.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-I" ] && [ "$2" = "-" ] && [ "$3" = "lease-guard" ]; then exit 1; fi\n'
        f'exec {real_python} "$@"\n',
        encoding="utf-8",
    )
    broken.chmod(0o755)

    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "eta"
    env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
    result = subprocess.run(
        ["bash", str(SCRIPT), "foo", "--status", "withdrawn"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    # Closure must actually COMPLETE — otherwise the marker surviving proves only
    # that cc-close died early, which is what made the first version of this test
    # vacuous. So the note must be gone from active/, AND the exit status must say
    # the cleanup did not finish.
    #
    # Exit 3, not 0. `cleanup_incomplete` was set in three places and read in none,
    # so a close that kept a lease it could not evaluate was indistinguishable from
    # a clean one to anything scripting cc-close (review round 17). The closure DID
    # happen, which is why this is not a generic failure code: re-running cc-close
    # cannot reach cleanup again, because the note is no longer in active/.
    assert result.returncode == 3, (
        "a partially-completed close did not report itself through the exit status\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert not (vault / "active" / "foo.md").exists(), "task was not closed"
    # An unevaluable guard must be REPORTED, not silently folded into "no match".
    # The note has already moved to closed/, so a rerun cannot reach this cleanup
    # again — a silent skip leaves the lease with no record and no second chance.
    assert "cleanup incomplete" in result.stderr, (
        f"unevaluable guard was silent; closure reported clean\nstderr={result.stderr}"
    )
    assert str(foreign) in result.stderr, "the preserved lease was not named"
    assert foreign.exists(), (
        "the foreign-lease guard failed open and deleted a lease it could not "
        f"adjudicate\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_cc_close_sweeps_a_last_resort_minted_session_id(tmp_path: Path) -> None:
    """The alpha-infixed fallback mint is a real session id and must be swept.

    agent-role.sh falls back to `sid<nanos>x<rand><rand>` when no uuid source
    exists. Restricting the foreign-session sweep to uuids alone would silently
    skip those, so both mint shapes are accepted.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    stale = cache / "cc-active-task-eta-sid1789999999999999999x1234527891"
    stale.write_text("foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id="b8e2d7c4-1a55-4f93-8c60-77ad3e9b0125")

    assert result.returncode == 0, result.stderr
    assert not stale.exists(), f"last-resort-minted lease leaked\nstdout={result.stdout}"


def test_cc_close_orphan_sweep_reports_what_it_cleared(tmp_path: Path) -> None:
    """A reconciliation that clears silently cannot be audited after the fact."""
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    (cache / "cc-active-task-eta-3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01").write_text(
        "foo\n", encoding="utf-8"
    )

    result = _run_close(home, "foo", role="eta", session_id="b8e2d7c4-1a55-4f93-8c60-77ad3e9b0125")

    assert result.returncode == 0, result.stderr
    assert "cc-active-task-eta-3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01" in result.stdout, (
        f"the orphaned marker was cleared without naming it\nstdout={result.stdout}"
    )
