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
    hold_task_note_lock,
    lock_path,
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
        assert mod._resolved_timeout(None) == pytest.approx(0.25)
        for bad in ("0", "-1", "", "soon"):
            monkeypatch.setenv(TIMEOUT_ENV, bad)
            assert mod._resolved_timeout(None) == DEFAULT_TIMEOUT_SECONDS, bad

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
        expected = home / ".cache" / "hapax" / "cc-task-locks" / "t1.lock"
        assert Path(result.stdout.strip()) == expected


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
