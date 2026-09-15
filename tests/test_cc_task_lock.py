"""The mutual-exclusion primitive, and proof that BOTH writers take it.

`shared/cc_task_lock.py` exists because cc-close's read -> validate -> write
closed/ -> unlink active/ was not atomic against a concurrent cc-claim. A lock
only one side takes excludes nothing, so the load-bearing test here is the
claim-side one: review round 14 observed that removing cc-claim's acquisition
would leave the close-side contention test passing, which is exactly the shape of
a test that proves less than it appears to.

The competing writer is always plain `fcntl.flock` on the path
`shared.cc_task_lock.lock_path` names — never the helper on both sides — so these
prove the lock FILE is the rendezvous rather than trusting one implementation to
agree with itself.
"""

from __future__ import annotations

import errno
import fcntl
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shared.cc_task_lock import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    TIMEOUT_ENV,
    TaskLockTimeout,
    hold_role_lease_lock,
    hold_task_note_lock,
    lock_path,
    role_lock_path,
)

CC_CLAIM = REPO_ROOT / "scripts" / "cc-claim"
CC_CLOSE = REPO_ROOT / "scripts" / "cc-close"

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
    "HAPAX_CC_TASKS_ROOT",
)


def _write_note(vault: Path, task_id: str, status: str) -> Path:
    (vault / "active").mkdir(parents=True, exist_ok=True)
    (vault / "closed").mkdir(parents=True, exist_ok=True)
    path = vault / "active" / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: {status}
            assigned_to: unassigned
            claimable: true
            kind: build
            authority_case: CASE-TEST-001
            parent_spec: /tmp/isap-test.md
            depends_on: []
            created_at: 2026-05-09T00:00:00Z
            updated_at: 2026-05-09T00:00:00Z
            claimed_at: null
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )
    return path


def _artifact_ledger_with_open_debt(home: Path, task_id: str) -> Path:
    """An artifact ledger the disposition gate will actually WRITE to.

    Without this the gate returns 0 at its first check (`no ledger` / `no entries
    for this task`) and never reaches its mutation — so a contention test around it
    passes whether the gate runs before or after the lock, which is exactly what my
    first version of these tests did.

    A `gate`-ceiling entry with a non-terminal disposition is the combination that
    makes `--debt` rewrite both the ledger and the task note.
    """
    ledger = home / ".cache" / "hapax" / "document-pipeline" / "artifact-ledger.yaml"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        textwrap.dedent(
            f"""\
            - task_id: {task_id}
              artifact_id: doc-1
              class: publication
              authority_ceiling: gate
              disposition: produced
            """
        ),
        encoding="utf-8",
    )
    return ledger


def _lane_env(home: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env["HOME"] = str(home)
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    env["HAPAX_AGENT_NAME"] = "eta"
    env["HAPAX_AGENT_ROLE"] = "eta"
    env["HAPAX_SESSION_ID"] = "12345678-1234-4321-8765-123456789abc"
    env["HAPAX_GATE0B_CLAIM_PUBLICATION_OFF"] = "1"
    env.update(extra)
    return env


class TestTheHelper:
    def test_a_contended_lock_times_out_rather_than_blocking_forever(self, tmp_path: Path) -> None:
        """A caller that cannot serialize must refuse, and say what it waited on."""
        held = lock_path("t1", tmp_path / "locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            started = time.monotonic()
            with pytest.raises(TaskLockTimeout) as excinfo:
                hold_task_note_lock("t1", cache_dir=tmp_path / "locks", timeout=0.3)
            waited = time.monotonic() - started
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

        assert 0.2 <= waited < 10, f"did not wait the requested timeout: {waited:.2f}s"
        assert "t1" in str(excinfo.value) and str(held) in str(excinfo.value), (
            f"the refusal does not name what it waited on: {excinfo.value}"
        )

    def test_an_uncontended_lock_is_taken_immediately(self, tmp_path: Path) -> None:
        path = hold_task_note_lock("t1", cache_dir=tmp_path / "locks", timeout=0.3)
        assert path == lock_path("t1", tmp_path / "locks")

    def test_an_unexpected_oserror_is_raised_not_read_as_contention(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EIO is not EAGAIN. Folding it into the retry loop would spin for the
        whole timeout and then report contention that never existed, sending an
        operator to hunt a holder that does not exist.
        """
        import shared.cc_task_lock as mod

        def boom(_fd, _op):  # type: ignore[no-untyped-def]
            raise OSError(errno.EIO, "Input/output error")

        monkeypatch.setattr(mod.fcntl, "flock", boom)
        with pytest.raises(OSError) as excinfo:
            hold_task_note_lock("t1", cache_dir=tmp_path / "locks", timeout=5)
        assert not isinstance(excinfo.value, TaskLockTimeout)
        assert excinfo.value.errno == errno.EIO

    def test_the_timeout_override_is_honoured_but_cannot_disable_the_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bounding the wait is an operator control; skipping the lock is not.

        A zero or malformed value falls back to the default rather than being
        honoured: "wait zero seconds" is a plausible typo that would turn every
        contended close into a refusal, and there is deliberately no value that
        skips acquisition.
        """
        import shared.cc_task_lock as mod

        monkeypatch.setenv(TIMEOUT_ENV, "0.25")
        assert mod.resolved_timeout(None) == pytest.approx(0.25)
        # Spellings a shell `case` pattern accepted and this rejects — the
        # disagreement review round 15 measured. `0.00` refuses instantly; `1.5.0`
        # made flock reject the timeout while the message still blamed a holder.
        for bad in ("0", "0.0", "0.00", "-1", "1.5.0", "", "soon", " ", "inf", "nan"):
            monkeypatch.setenv(TIMEOUT_ENV, bad)
            assert mod.resolved_timeout(None) == DEFAULT_TIMEOUT_SECONDS, bad
        # An unusual but finite positive value IS the operator's call to make.
        monkeypatch.setenv(TIMEOUT_ENV, "1e3")
        assert mod.resolved_timeout(None) == pytest.approx(1000.0)

    def test_cc_close_resolves_the_same_lock_path_the_helper_does(self, tmp_path: Path) -> None:
        """Two derivations of one path is two lock files and no exclusion.

        cc-close computes the path in bash by calling into this module; if it ever
        passed its own cache dir instead, the writers would serialize against
        different files and nothing would notice.
        """
        home = tmp_path / "home"
        (home / ".cache").mkdir(parents=True)
        env = _lane_env(home)
        result = subprocess.run(
            [
                "python3",
                "-I",
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]);"
                "from shared.cc_task_lock import lock_path; print(lock_path(sys.argv[2]))",
                str(REPO_ROOT),
                "t1",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        expected = home / ".cache" / "hapax" / "cc-task-locks" / "tasks" / "t1.lock"
        assert Path(result.stdout.strip()) == expected

    def test_task_and_role_locks_cannot_name_the_same_file(self, tmp_path: Path) -> None:
        """Disjoint namespaces, not a prefix convention.

        `role_lock_path("eta")` once returned `role-eta.lock` — exactly what
        `lock_path("role-eta")` returns. A task genuinely named `role-eta`, claimed
        by role `eta`, then took the task lock and timed out waiting for the SAME
        inode through a second descriptor: a self-deadlock that looks like
        contention and has no holder to find. Any prefix scheme has such a task id.
        """
        locks = tmp_path / "locks"
        collided = [
            (lock_path("role-eta", locks), role_lock_path("eta", locks)),
            (lock_path("roles", locks), role_lock_path("", locks)),
            (lock_path("eta", locks), role_lock_path("eta", locks)),
        ]
        for task_lock, role_lock in collided:
            assert task_lock != role_lock, (
                f"a task lock and a role lock resolve to one file: {task_lock}"
            )
        # And the split is structural, so the property holds for ids never listed.
        assert lock_path("x", locks).parent != role_lock_path("x", locks).parent

    def test_the_two_locks_are_independently_holdable(self, tmp_path: Path) -> None:
        """The self-deadlock, as behaviour rather than as two path strings."""
        locks = tmp_path / "locks"
        hold_task_note_lock("role-eta", cache_dir=locks, timeout=0.3)
        # Would raise TaskLockTimeout against the same inode.
        assert hold_role_lease_lock("eta", cache_dir=locks, timeout=0.3)


class TestOneTimeoutParser:
    """cc-close must resolve the knob the way the Python side does, not beside it.

    A shell `case` pattern stood in for it and disagreed: it accepted `1.5.0`,
    which flock then rejected while the refusal still told the operator to go find
    a lock holder, and `0.00`, which turns every contended close into an instant
    refusal. Both now route through `shared.cc_task_lock.resolved_timeout`.
    """

    def _closable(self, home: Path) -> Path:
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "withdrawn")
        return note

    def test_a_malformed_timeout_does_not_become_a_phantom_lock_holder(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        note = self._closable(home)
        env = _lane_env(home, HAPAX_CC_TASK_LOCK_TIMEOUT_SECONDS="1.5.0")
        result = subprocess.run(
            ["bash", str(CC_CLOSE), "t1", "--status", "withdrawn"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        assert "held the cc-task lock" not in result.stderr, (
            "a malformed timeout was reported as contention, sending the operator "
            f"to find a holder that does not exist\n{result.stderr}"
        )
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert not note.exists(), "the close did not happen"

    def test_a_zero_spelling_does_not_silently_become_no_wait(self, tmp_path: Path) -> None:
        """`0.00` falls back to the default rather than refusing on contact."""
        home = tmp_path / "home"
        self._closable(home)
        env = _lane_env(home, HAPAX_CC_TASK_LOCK_TIMEOUT_SECONDS="0.00")

        held = lock_path("t1", home / ".cache" / "hapax" / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            proc = subprocess.Popen(
                ["bash", str(CC_CLOSE), "t1", "--status", "withdrawn"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            settle = time.monotonic() + 3.0
            while proc.poll() is None and time.monotonic() < settle:
                time.sleep(0.05)
            blocked = proc.poll() is None
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)
        stdout, stderr = proc.communicate(timeout=120)

        assert blocked, (
            "cc-close refused immediately — `0.00` was honoured as a zero wait, so a "
            f"momentarily contended close fails instead of waiting\n{stdout}\n{stderr}"
        )
        assert proc.returncode == 0, f"{stdout}\n{stderr}"


class TestTheCloseSideFdIsHeldThroughout:
    """cc-close takes the lock in BASH (`exec 9>` + flock) and the writer heredoc
    plus the lease sweep inherit it. That is an assumption about fd inheritance and
    shell scoping, not a fact any Python-side test establishes — review round 15
    asked for it directly: if fd 9 were closed early, or the sweep ran somewhere
    that did not inherit it, marker retirement would run unprotected.
    """

    def test_the_lock_is_never_acquirable_while_cc_close_runs(self, tmp_path: Path) -> None:
        """Held from acquisition to exit — polled, not assumed.

        The sibling test below proves cc-close BLOCKS on a held lock. It cannot see
        an early release: by the time the writer runs, the competitor has let go.
        So this one runs cc-close uncontended and polls for the lock in a tight
        non-blocking loop. If fd 9 were closed before the writer, or the lease sweep
        ran somewhere that did not inherit it, the poll acquires while cc-close is
        still working — and the sweep, which is the part furthest from the
        acquisition, would be running unprotected.
        """
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "withdrawn")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        lease = cache / "cc-active-task-eta"
        lease.write_text("t1\n", encoding="utf-8")
        env = _lane_env(home)

        held = lock_path("t1", cache / "cc-task-locks")
        proc = subprocess.Popen(
            ["bash", str(CC_CLOSE), "t1", "--status", "withdrawn"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        def _acquirable(fd: int) -> bool:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True

        # TWO PHASES, and the first is not optional: polling from the moment Popen
        # returns proves nothing, because cc-close runs its read-only gates before
        # taking the lock and the very first poll succeeds against a lock nobody
        # holds yet. That version of this test reported the shipped code as broken.
        observed_held = False
        stole_it = False
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            while proc.poll() is None and not observed_held:
                observed_held = not _acquirable(handle)
                if not observed_held:
                    time.sleep(0.005)
            while observed_held and proc.poll() is None:
                if _acquirable(handle):
                    stole_it = True
                    break
                time.sleep(0.005)
        finally:
            os.close(handle)
        stdout, stderr = proc.communicate(timeout=120)

        assert observed_held, (
            "the lock was never observed held while cc-close ran — either it does "
            f"not take one, or it released it faster than a 5ms poll\n{stdout}\n{stderr}"
        )
        assert not stole_it, (
            "the cc-task lock became acquirable while cc-close was still running, so "
            "part of its mutating tail — the lease sweep is the furthest — runs "
            f"unprotected\n{stdout}\n{stderr}"
        )
        assert proc.returncode == 0, f"{stdout}\n{stderr}"
        assert not note.exists() and not lease.exists(), (
            f"the close did not complete\n{stdout}\n{stderr}"
        )

    def test_a_competing_holder_blocks_cc_close_through_marker_retirement(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "withdrawn")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        lease = cache / "cc-active-task-eta"
        lease.write_text("t1\n", encoding="utf-8")
        env = _lane_env(home)

        held = lock_path("t1", cache / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            proc = subprocess.Popen(
                ["bash", str(CC_CLOSE), "t1", "--status", "withdrawn"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            settle = time.monotonic() + 3.0
            while proc.poll() is None and time.monotonic() < settle:
                time.sleep(0.05)
            blocked = proc.poll() is None
            # Nothing may have happened yet — note untouched AND lease untouched.
            note_present = note.exists()
            lease_present = lease.exists()
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

        stdout, stderr = proc.communicate(timeout=120)

        assert blocked, f"cc-close proceeded while the lock was held\n{stdout}\n{stderr}"
        assert note_present and lease_present, "cc-close mutated state before acquiring the lock"
        assert proc.returncode == 0, f"{stdout}\n{stderr}"
        assert not note.exists(), "the note was not closed once the lock cleared"
        # The sweep is AFTER the writer heredoc. Its having run is the evidence that
        # fd 9 was still held there rather than released with the heredoc.
        assert not lease.exists(), (
            "the lease sweep did not run — it is the part of cc-close furthest from "
            f"the acquisition, and the part that would run unprotected\n{stdout}"
        )


class TestTheRoleLeaseNamespace:
    """The SECOND resource, and why the task lock could not protect it.

    Lease files are keyed by `<role>[-<session>]`; the note is keyed by task id.
    cc-close's role-wide sweep and cc-claim's publication both write the lease
    namespace, so keying their exclusion by task id excludes nothing: review round
    16 reproduced cc-close closing task A, reading a marker that named A, and
    removing the file after cc-claim had republished it as task B — held under B's
    own, different, task lock.
    """

    def test_a_replacement_claim_for_another_task_survives_a_close(self, tmp_path: Path) -> None:
        """Two tasks, two task locks, one lease namespace.

        cc-close(A) is started while the ROLE lock is held, so it cannot reach its
        sweep. The replacement publication for B happens in that window, exactly as
        a concurrent cc-claim would. When the role lock clears, cc-close must not
        delete a lease that no longer names the task it is closing.
        """
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _write_note(vault, "task-a", "withdrawn")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        lease = cache / "cc-active-task-eta-3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
        epoch = cache / "cc-claim-epoch-eta-3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
        lease.write_text("task-a\n", encoding="utf-8")
        epoch.write_text("1757800000 task-a\n", encoding="utf-8")
        env = _lane_env(home)

        held = role_lock_path("eta", cache / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            proc = subprocess.Popen(
                ["bash", str(CC_CLOSE), "task-a", "--status", "withdrawn"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            settle = time.monotonic() + 4.0
            while proc.poll() is None and time.monotonic() < settle:
                time.sleep(0.05)
            blocked_before_sweep = proc.poll() is None
            # The replacement: this lane has moved on to task B and republished the
            # SAME filename. A concurrent cc-claim does exactly this.
            lease.write_text("task-b\n", encoding="utf-8")
            epoch.write_text("1757800999 task-b\n", encoding="utf-8")
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

        stdout, stderr = proc.communicate(timeout=180)

        assert blocked_before_sweep, (
            "cc-close reached its lease sweep while the role lock was held — the "
            f"lease namespace is not serialized\n{stdout}\n{stderr}"
        )
        assert proc.returncode == 0, f"{stdout}\n{stderr}"
        assert lease.exists() and lease.read_text(encoding="utf-8").strip() == "task-b", (
            "cc-close deleted a live claim for a DIFFERENT task — the replacement "
            f"published while it waited\n{stdout}\n{stderr}"
        )
        assert epoch.exists(), "the replacement's epoch sidecar was deleted with it"


class TestTheRoleLockIsTakenBeforeTheClosure:
    """Where the acquisition sits decides what a failure can be.

    Taken just before the lease sweep, the note had already moved to closed/, so a
    timeout returned SUCCESS with leases retained and prescribed a re-run that
    exits at the active-note lookup — cleanup unreachable forever. And the
    missing-path branch set a flag without clearing `role`, so the sweep ran
    unlocked regardless. Both are review round 17's findings, and both are
    consequences of the placement rather than of the branches.

    Taken before the writer, every failure here is a refusal with nothing modified.
    """

    def test_an_unresolvable_role_lock_path_refuses_instead_of_sweeping(
        self, tmp_path: Path
    ) -> None:
        """The fallthrough: a flag was set, `role` was left populated, the sweep ran.

        The path is made unresolvable by pointing HOME at a tree whose cache
        directory cannot be created, which is what an unimportable helper or an
        unwritable cache looks like from cc-close's side.
        """
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "withdrawn")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        lease = cache / "cc-active-task-eta"
        lease.write_text("t1\n", encoding="utf-8")
        env = _lane_env(home)

        # A FILE where the roles lock directory must be: mkdir fails, so
        # role_lock_path cannot resolve and cc-close must refuse before writing.
        locks = cache / "cc-task-locks"
        locks.mkdir(parents=True, exist_ok=True)
        (locks / "roles").write_text("not a directory\n", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(CC_CLOSE), "t1", "--status", "withdrawn"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )

        assert result.returncode != 0, (
            f"cc-close swept leases without a role lock it could not resolve\n{result.stdout}"
        )
        assert note.exists(), "the note was closed despite the refusal"
        assert lease.exists(), "the lease was retired without the lock that makes retirement safe"
        assert "could not resolve the role lease lock path" in result.stderr, (
            "cc-close failed for some other reason — the fallthrough this pins let "
            f"the sweep run after merely setting a flag\n{result.stderr}"
        )
        assert "Nothing was modified" in result.stderr, result.stderr

    def test_an_unwritable_lock_file_refuses_with_a_permissions_remedy(
        self, tmp_path: Path
    ) -> None:
        """`exec 9>` under `set -euo pipefail` dies bare if the file is unwritable.

        The explanatory flock handlers below it never run, so the operator gets a
        shell redirection error and no remedy for a problem whose remedy is obvious.
        """
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "withdrawn")
        env = _lane_env(home)

        stale = lock_path("t1", home / ".cache" / "hapax" / "cc-task-locks")
        stale.write_text("", encoding="utf-8")
        stale.chmod(0o400)
        try:
            result = subprocess.run(
                ["bash", str(CC_CLOSE), "t1", "--status", "withdrawn"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
        finally:
            stale.chmod(0o600)

        assert result.returncode == 2, f"{result.stdout}\n{result.stderr}"
        assert "cannot open the cc-task lock file" in result.stderr, (
            f"cc-close died on the redirection with no remedy\n{result.stderr}"
        )
        assert "permissions" in result.stderr and "Nothing was modified" in result.stderr
        assert note.exists()

    def test_a_held_role_lock_refuses_with_the_note_untouched(self, tmp_path: Path) -> None:
        """A timeout must not arrive after the closure is already committed."""
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "withdrawn")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        lease = cache / "cc-active-task-eta"
        lease.write_text("t1\n", encoding="utf-8")
        env = _lane_env(home, HAPAX_CC_TASK_LOCK_TIMEOUT_SECONDS="0.4")

        held = role_lock_path("eta", cache / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            result = subprocess.run(
                ["bash", str(CC_CLOSE), "t1", "--status", "withdrawn"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

        assert result.returncode == 2, (
            "a role-lock timeout reported success after committing the closure — the "
            f"prescribed re-run can never reach cleanup again\n{result.stdout}"
        )
        assert note.exists(), "the note moved to closed/ before the role lock was taken"
        assert lease.exists()
        assert "role lease lock" in result.stderr and "Nothing was modified" in result.stderr, (
            result.stderr
        )
        # And re-running once the holder is gone must work, which is what makes the
        # prescribed next action true.
        again = subprocess.run(
            ["bash", str(CC_CLOSE), "t1", "--status", "withdrawn"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        assert again.returncode == 0, f"{again.stdout}\n{again.stderr}"
        assert not note.exists() and not lease.exists()


class TestTheLockNamespaceFollowsTheResourceNamespace:
    """The lock must be a function of what it protects, not of an unrelated knob.

    `lock_dir` read `XDG_CACHE_HOME or ~/.cache` while cc-claim writes and cc-close
    globs `$HOME/.cache/hapax/cc-active-task-*` with `$HOME` hardcoded. Two writers
    sharing a HOME and exporting different XDG_CACHE_HOME values therefore took
    different locks over the same lease files — no exclusion at all. Every fixture
    in this file had aligned the two, which is exactly why the suite could not see
    it; all four reviewer families reported it independently.
    """

    def test_the_lock_path_ignores_xdg_cache_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        (home / ".cache").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "somewhere-else"))
        first = lock_path("t1")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "different-again"))
        second = lock_path("t1")
        monkeypatch.delenv("XDG_CACHE_HOME")
        third = lock_path("t1")

        assert first == second == third, (
            "the lock path moved with XDG_CACHE_HOME while the leases it protects "
            f"did not: {first} / {second} / {third}"
        )
        assert first == home / ".cache" / "hapax" / "cc-task-locks" / "tasks" / "t1.lock"

    def test_a_relative_override_is_refused_rather_than_resolved(self, tmp_path: Path) -> None:
        """cwd-dependent means two processes in one tree disagree, neither wrongly."""
        with pytest.raises(ValueError, match="absolute"):
            lock_path("t1", Path("relative/locks"))
        with pytest.raises(ValueError, match="absolute"):
            role_lock_path("eta", Path("relative/locks"))

    def test_two_writers_with_different_xdg_still_exclude_each_other(self, tmp_path: Path) -> None:
        """The contention case the aligned fixtures could not reach.

        cc-claim runs with one XDG_CACHE_HOME, cc-close with another — a normal
        lane-versus-dispatcher divergence — and they must still meet on one lock.
        """
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _write_note(vault, "t1", "withdrawn")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)

        close_env = _lane_env(home)
        close_env["XDG_CACHE_HOME"] = str(tmp_path / "close-cache")

        # The competitor holds the lock the way cc-claim would, resolving it with a
        # THIRD XDG value — and from HOME, which is what makes them meet.
        holder_home_lock = home / ".cache" / "hapax" / "cc-task-locks" / "tasks" / "t1.lock"
        holder_home_lock.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(holder_home_lock, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            proc = subprocess.Popen(
                ["bash", str(CC_CLOSE), "t1", "--status", "withdrawn"],
                env=close_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            settle = time.monotonic() + 3.0
            while proc.poll() is None and time.monotonic() < settle:
                time.sleep(0.05)
            blocked = proc.poll() is None
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)
        stdout, stderr = proc.communicate(timeout=120)

        assert blocked, (
            "cc-close and a concurrent holder took DIFFERENT locks because their "
            f"XDG_CACHE_HOME values differed — no exclusion\n{stdout}\n{stderr}"
        )
        assert proc.returncode == 0, f"{stdout}\n{stderr}"


class TestEveryMutationIsUnderTheLock:
    """Not just the writer — every step of cc-close that changes state.

    The artifact-disposition gate rewrites the task note and the artifact ledger
    when `--debt` is given, and it ran BEFORE either lock: an unprotected
    read/write that could overwrite a concurrent cc-claim update, and a later lock
    refusal that said "Nothing was modified" over a note that had been. Every
    contention test in this file used `withdrawn`, which skips that checker
    entirely — review round 20 said so, and was right.
    """

    def test_a_done_debt_close_mutates_nothing_before_the_lock(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "in_progress")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        before = note.read_text(encoding="utf-8")
        ledger = _artifact_ledger_with_open_debt(home, "t1")
        ledger_before = ledger.read_text(encoding="utf-8")
        env = _lane_env(home, HAPAX_PR_MERGE_GATE_OFF="1")

        held = lock_path("t1", cache / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            proc = subprocess.Popen(
                [
                    "bash",
                    str(CC_CLOSE),
                    "t1",
                    "--status",
                    "done",
                    "--debt",
                    "deferred artifact capture",
                ],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            settle = time.monotonic() + 3.0
            while proc.poll() is None and time.monotonic() < settle:
                time.sleep(0.05)
            blocked = proc.poll() is None
            note_during = note.read_text(encoding="utf-8")
            ledger_during = ledger.read_text(encoding="utf-8") if ledger.exists() else None
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)
        stdout, stderr = proc.communicate(timeout=180)

        assert blocked, (
            f"a --debt close ran its mutating gate while the task lock was held\n{stdout}\n{stderr}"
        )
        assert note_during == before, (
            "the artifact-disposition gate rewrote the task note before taking the "
            "lock — a concurrent cc-claim update would have been lost"
        )
        assert ledger_during == ledger_before, (
            "the artifact ledger was rewritten before the lock was taken"
        )

    def test_a_lock_refusal_does_not_claim_nothing_changed_after_changing_things(
        self, tmp_path: Path
    ) -> None:
        """The message has to be true. It was not, for exactly this path."""
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "in_progress")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        before = note.read_text(encoding="utf-8")
        _artifact_ledger_with_open_debt(home, "t1")
        env = _lane_env(home, HAPAX_PR_MERGE_GATE_OFF="1", HAPAX_CC_TASK_LOCK_TIMEOUT_SECONDS="0.4")

        held = lock_path("t1", cache / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            result = subprocess.run(
                [
                    "bash",
                    str(CC_CLOSE),
                    "t1",
                    "--status",
                    "done",
                    "--debt",
                    "deferred artifact capture",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=180,
            )
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

        assert result.returncode != 0, result.stdout
        if "Nothing was modified" in result.stderr:
            assert note.read_text(encoding="utf-8") == before, (
                "cc-close reported 'Nothing was modified' over a note it had already "
                f"rewritten\n{result.stderr}"
            )


class TestTheOrderingInvariant:
    """Task then role, in both writers — pinned, not merely commented.

    glm-1: "the invariant lives in prose in two languages and no test pins the
    ordering itself." Correct, and a deadlock from a future edit to one writer
    would surface as a hang under load rather than as a red.

    The order is observable: while a writer is blocked on the TASK lock it must not
    yet hold the ROLE lock. If it took role-first, the role lock would be
    unavailable while it waits — and two writers taking opposite orders is exactly
    the deadlock.
    """

    def _role_lock_free(self, home: Path) -> bool:
        path = role_lock_path("eta", home / ".cache" / "hapax" / "cc-task-locks")
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True
        finally:
            os.close(fd)

    def _blocked_on_task_lock(self, home: Path, argv: list[str], env: dict[str, str]):
        held = lock_path("t1", home / ".cache" / "hapax" / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            proc = subprocess.Popen(
                argv, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            settle = time.monotonic() + 3.0
            while proc.poll() is None and time.monotonic() < settle:
                time.sleep(0.05)
            still_running = proc.poll() is None
            role_free = self._role_lock_free(home)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)
        stdout, stderr = proc.communicate(timeout=180)
        return still_running, role_free, stdout, stderr

    def test_cc_close_takes_the_task_lock_first(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _write_note(vault, "t1", "withdrawn")
        (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
        running, role_free, stdout, stderr = self._blocked_on_task_lock(
            home,
            ["bash", str(CC_CLOSE), "t1", "--status", "withdrawn"],
            _lane_env(home),
        )
        assert running, f"cc-close did not block on the task lock\n{stdout}\n{stderr}"
        assert role_free, (
            "cc-close held the ROLE lock while waiting for the TASK lock — it takes "
            "them in the opposite order from cc-claim, which is a deadlock under load"
        )

    def test_cc_claim_takes_the_task_lock_first(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _write_note(vault, "t1", "offered")
        (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
        running, role_free, stdout, stderr = self._blocked_on_task_lock(
            home, ["bash", str(CC_CLAIM), "t1"], _lane_env(home)
        )
        assert running, f"cc-claim did not block on the task lock\n{stdout}\n{stderr}"
        assert role_free, (
            "cc-claim held the ROLE lock while waiting for the TASK lock — opposite "
            "order from cc-close, which is a deadlock under load"
        )

    def test_neither_production_caller_overrides_the_lock_directory(self) -> None:
        """An absolute override is honoured, so it could still split the namespace.

        claude-1's residual note: nothing pinned that the two production callers
        pass none. They must resolve through `lock_dir()` with no argument, or the
        namespace is a function of the caller again rather than of the resource.
        """
        for script in (CC_CLAIM, CC_CLOSE):
            code = "\n".join(
                line
                for line in script.read_text(encoding="utf-8").splitlines()
                if not line.strip().startswith("#")
            )
            for call in (
                "lock_path(",
                "role_lock_path(",
                "hold_task_note_lock(",
                "hold_role_lease_lock(",
            ):
                for line in code.splitlines():
                    if call not in line:
                        continue
                    args = line.split(call, 1)[1]
                    assert "cache_dir" not in args, (
                        f"{script.name} passes a cache_dir override to {call}: "
                        f"{line.strip()!r} — the lock namespace must follow the "
                        "resource namespace, not the caller"
                    )


class TestRecoveryParticipatesToo:
    """Recovery mutates the same resources a close does, so it takes the same locks.

    `--recover-claim-publications` and `--rehydrate-activation-cache` returned
    before the lock acquisition and used `shared.sdlc_claim`'s own
    `task-locks/<digest>.lock`, which cc-close never takes. Two lock namespaces
    over one resource is not exclusion — it is two processes agreeing to watch
    different doors — so a recovery could replace a note between cc-close's read
    and its unlink and the archived snapshot would silently lack the recovered
    changes.
    """

    def test_rehydrate_waits_for_a_held_task_lock(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _write_note(vault, "t1", "in_progress")
        (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
        env = _lane_env(home)

        held = lock_path("t1", home / ".cache" / "hapax" / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            proc = subprocess.Popen(
                ["bash", str(CC_CLAIM), "--rehydrate-activation-cache", "t1"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            settle = time.monotonic() + 3.0
            while proc.poll() is None and time.monotonic() < settle:
                time.sleep(0.05)
            blocked = proc.poll() is None
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)
        stdout, stderr = proc.communicate(timeout=120)

        assert blocked, (
            "the rehydrate path ran while a close held the task lock — it can replace "
            f"the note between that close's read and its unlink\n{stdout}\n{stderr}"
        )

    def test_recovering_all_tasks_refuses_while_any_writer_is_mid_mutation(
        self, tmp_path: Path
    ) -> None:
        """The all-tasks form has no single lock to take, so it checks instead.

        Not "proceed unprotected" and not "refuse always": the precondition that
        actually matters is whether another writer is mid-mutation right now, and
        that is checkable at the moment of use.
        """
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _write_note(vault, "t1", "in_progress")
        (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
        env = _lane_env(home, HAPAX_CC_TASK_LOCK_TIMEOUT_SECONDS="0.4")

        held = lock_path("t1", home / ".cache" / "hapax" / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            result = subprocess.run(
                ["bash", str(CC_CLAIM), "--recover-claim-publications"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

        assert result.returncode == 4, f"{result.stdout}\n{result.stderr}"
        assert "recovering ALL tasks while another writer holds a task lock" in result.stderr, (
            result.stderr
        )
        assert str(held) in result.stderr, "the refusal did not name the holder"
        assert "one task at a time" in result.stderr, (
            "the refusal does not name the narrower command that IS safe"
        )

    def test_recovering_all_tasks_proceeds_when_nothing_is_held(self, tmp_path: Path) -> None:
        """Fail-closed must not mean fail-always."""
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _write_note(vault, "t1", "in_progress")
        (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["bash", str(CC_CLAIM), "--recover-claim-publications"],
            env=_lane_env(home),
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        assert "another writer holds a task lock" not in result.stderr, result.stderr


class TestARefusalMutatesNothing:
    """ "Nothing was modified" has to be true of the artifact ledger too.

    Identity and --expect-status were checked only in the writer, which runs AFTER
    the artifact-disposition gate. So `--status done --expect-status done --debt`
    against an in_progress task rewrote the note and the ledger, then refused with
    "Nothing was modified" — and each repeat refreshed the debt timestamps, so the
    refusal was not even idempotent.
    """

    def test_a_failed_expect_status_leaves_note_and_ledger_untouched(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "in_progress")
        (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
        ledger = _artifact_ledger_with_open_debt(home, "t1")
        note_before = note.read_text(encoding="utf-8")
        ledger_before = ledger.read_text(encoding="utf-8")
        env = _lane_env(home, HAPAX_PR_MERGE_GATE_OFF="1")

        result = subprocess.run(
            [
                "bash",
                str(CC_CLOSE),
                "t1",
                "--status",
                "done",
                "--expect-status",
                "done",
                "--debt",
                "deferred artifact capture",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )

        assert result.returncode != 0, f"a stale precondition was accepted\n{result.stdout}"
        assert "Nothing was modified" in result.stderr, result.stderr
        assert note.read_text(encoding="utf-8") == note_before, (
            "the note was rewritten by the artifact gate before the precondition was "
            "checked, under a refusal that said nothing was modified"
        )
        assert ledger.read_text(encoding="utf-8") == ledger_before, (
            "the artifact ledger was rewritten under the same refusal"
        )

    def test_repeated_refusals_do_not_refresh_debt_timestamps(self, tmp_path: Path) -> None:
        """Idempotence: a refusal repeated is a refusal, not a slow mutation."""
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _write_note(vault, "t1", "in_progress")
        (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
        ledger = _artifact_ledger_with_open_debt(home, "t1")
        env = _lane_env(home, HAPAX_PR_MERGE_GATE_OFF="1")
        argv = [
            "bash",
            str(CC_CLOSE),
            "t1",
            "--status",
            "done",
            "--expect-status",
            "done",
            "--debt",
            "deferred artifact capture",
        ]
        subprocess.run(argv, env=env, capture_output=True, check=False, timeout=180)
        first = ledger.read_text(encoding="utf-8")
        subprocess.run(argv, env=env, capture_output=True, check=False, timeout=180)
        assert ledger.read_text(encoding="utf-8") == first, (
            "a repeated refusal refreshed the debt record"
        )


class TestBothWritersParticipate:
    """The load-bearing pair: each tool must block on the lock the other holds."""

    def test_cc_claim_waits_for_a_held_lock_and_then_succeeds(self, tmp_path: Path) -> None:
        """Removing cc-claim's acquisition makes this test fail, and only this one.

        The close-side contention test passes either way, which is why it cannot
        stand for claim-side exclusion.
        """
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "offered")
        env = _lane_env(home)

        held = lock_path("t1", home / ".cache" / "hapax" / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            proc = subprocess.Popen(
                ["bash", str(CC_CLAIM), "t1"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            settle = time.monotonic() + 3.0
            while proc.poll() is None and time.monotonic() < settle:
                time.sleep(0.05)
            blocked = proc.poll() is None
            note_while_blocked = note.read_text(encoding="utf-8")
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

        stdout, stderr = proc.communicate(timeout=120)

        assert blocked, (
            "cc-claim ran to completion while another process held the task lock — "
            f"it is not participating in the exclusion\n{stdout}\n{stderr}"
        )
        assert "status: offered" in note_while_blocked, (
            "cc-claim mutated the note before taking the lock"
        )
        assert proc.returncode == 0, f"cc-claim failed after the lock cleared\n{stderr}"
        assert "status: claimed" in note.read_text(encoding="utf-8"), (
            "cc-claim did not proceed once the lock was released"
        )

    def test_cc_claim_refuses_and_changes_nothing_when_the_lock_never_clears(
        self, tmp_path: Path
    ) -> None:
        """The failure path: refuse with a next action, leave note AND leases alone."""
        home = tmp_path / "home"
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        note = _write_note(vault, "t1", "offered")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        before = note.read_text(encoding="utf-8")
        env = _lane_env(home, HAPAX_CC_TASK_LOCK_TIMEOUT_SECONDS="0.4")

        held = lock_path("t1", cache / "cc-task-locks")
        handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            result = subprocess.run(
                ["bash", str(CC_CLAIM), "t1"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

        assert result.returncode != 0, f"cc-claim claimed through a held lock\n{result.stdout}"
        assert "cc-task lock" in result.stderr, result.stderr
        assert "Next action" in result.stderr, (
            f"the refusal does not name a next action\n{result.stderr}"
        )
        assert note.read_text(encoding="utf-8") == before, "the note was modified anyway"
        leases = sorted(p.name for p in cache.glob("cc-active-task-*"))
        assert not leases, f"a lease was written despite the refusal: {leases}"
