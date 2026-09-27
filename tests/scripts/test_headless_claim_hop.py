"""Claim-hop terminality + truthful teardown records for hapax-claude-headless.

Row: headless-launcher-treats-a-claim-hop-as-task-terminal-and-kills-its-lane-20260916

Measured 2026-09-16T10:06Z on gamma (PR 4674 unmerged): the teardown watchdog
read a claim file naming a DIFFERENT live task as 'task closed/merged' and
SIGTERMd claude mid-turn; the relay status was then written
``retired_reason: clean exit (headless)`` for a SIGTERM.

Pinned behaviors:
  (a) a claim file naming a DIFFERENT live task is ``claim_moved:<from>:<to>``
      — never terminal. The launcher re-binds to the new task and keeps
      polling it. (Red before the fix.)
  (b) a measurably closed launch row still kills within one poll — no
      regression of the zombie-launcher self-reap fix.
  (c) a missing claim file stays indeterminate (fail-open) — no kill.
  (d) the SIGTERM teardown writes ``retired_reason: self_reap:<why>`` with the
      child exit code, never 'clean exit (headless)'.
  (e) 'clean exit (headless)' is reserved for a child that exited 0 on its
      own with a result event in the log — pinned in both directions.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-headless"

# Distinctive sleep length so a timed-out test can reap only ITS OWN orphaned
# fake claude without touching the rest of the suite (which uses sleep 600)
# or anything else on the host.
FAKE_CLAUDE_SLEEP = "313"


# ---------------------------------------------------------------------------
# Unit harness: drive the REAL task_is_terminal extracted from the launcher.
# ---------------------------------------------------------------------------


def _extract_task_is_terminal() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("task_is_terminal()")
    end = text.index("\n}\n", start) + 3
    return text[start:end]


def _run_unit(
    tmp_path: Path,
    *,
    role: str = "cx-test",
    task_under_test: str = "task-a",
    claim_files: dict[str, str] | None = None,
    notes: dict[str, tuple[str, str]] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the extracted task_is_terminal against claim/note fixtures.

    ``claim_files`` maps claim-file suffix (e.g. ``cx-test`` or
    ``cx-test-<session>``) to the task id it names. ``notes`` maps task id to
    (status, assigned_to); a task absent from the dict has no row in active/.
    Returns the bash result: exit 0 = terminal, 1 = live.
    """
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    for suffix, content in (claim_files or {}).items():
        (cache / f"cc-active-task-{suffix}").write_text(f"{content}\n", encoding="utf-8")

    vault = tmp_path / "vault" / "active"
    vault.mkdir(parents=True, exist_ok=True)
    case_arms = []
    for note_task, (status, assigned) in (notes or {}).items():
        note = vault / f"{note_task}.md"
        note.write_text(
            f"---\ntask_id: {note_task}\nstatus: {status}\nassigned_to: {assigned}\npr: null\n---\n",
            encoding="utf-8",
        )
        case_arms.append(f"    {note_task}) printf '%s' '{note}' ;;")
    find_note = (
        'find_active_note() {\n  case "$1" in\n'
        + "\n".join(case_arms)
        + "\n    *) printf '' ;;\n  esac\n}"
    )

    current_task_file = tmp_path / "current-task"
    current_task_file.write_text(f"{task_under_test}\n", encoding="utf-8")
    hops_log = tmp_path / "task-hops.log"

    harness = textwrap.dedent(f"""\
        set -u
        export HOME="{home}"
        ROLE="{role}"
        CLAIM_FILE="{cache}/cc-active-task-{role}"
        SESSION_CLAIM_FILE="{cache}/cc-active-task-{role}-no-such-session"
        CURRENT_TASK_FILE="{current_task_file}"
        HOPS_LOG_FILE="{hops_log}"
        CC_TASK_ACTIVE="{vault}"
        gh() {{ return 1; }}
        {find_note}
        {_extract_task_is_terminal()}
        task_is_terminal "{task_under_test}"
        """)
    return subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True, timeout=10, check=False
    )


class TestClaimMovedUnit:
    """(a) A claim hop to a LIVE second row is claim_moved — never terminal."""

    def test_claim_moved_to_live_second_row_is_not_terminal_and_rebinds(
        self, tmp_path: Path
    ) -> None:
        """The gamma 2026-09-16T10:05Z shape: the lane re-pointed its claim
        from its launch row (pr_open, PR unmerged) to a second live row. The
        old code returned terminal on `claimed != task` and the watchdog
        SIGTERMd claude mid-turn. Terminality is a property of the task's own
        row/PR, never of the claim file's current target."""
        result = _run_unit(
            tmp_path,
            task_under_test="task-a",
            claim_files={"cx-test": "task-b"},
            notes={"task-a": ("claimed", "cx-test"), "task-b": ("claimed", "cx-test")},
        )
        assert result.returncode == 1, (
            f"claim hop to a live row was treated as TERMINAL (the gamma kill). "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "claim_moved:task-a:task-b" in result.stderr
        # The launcher follows the claim onto the new row.
        current = tmp_path / "current-task"
        assert current.exists() and current.read_text(encoding="utf-8").strip() == "task-b"
        hops = tmp_path / "task-hops.log"
        hops_text = hops.read_text(encoding="utf-8") if hops.exists() else ""
        assert "claim_moved:task-a:task-b" in hops_text

    def test_claim_moved_to_a_closed_row_is_terminal(self, tmp_path: Path) -> None:
        """Only a measurably closed row may kill: when the hop target's own
        row is closed, the re-bound check is terminal."""
        result = _run_unit(
            tmp_path,
            task_under_test="task-a",
            claim_files={"cx-test": "task-b"},
            notes={"task-a": ("claimed", "cx-test"), "task-b": ("closed", "cx-test")},
        )
        assert result.returncode == 0

    def test_launch_row_closed_with_matching_claim_is_terminal(self, tmp_path: Path) -> None:
        """(b) unit half: a measurably closed launch row is terminal in one
        evaluation (the zombie-launcher fix must not regress)."""
        result = _run_unit(
            tmp_path,
            task_under_test="task-a",
            claim_files={"cx-test": "task-a"},
            notes={"task-a": ("closed", "cx-test")},
        )
        assert result.returncode == 0

    def test_missing_claim_file_is_indeterminate_not_terminal(self, tmp_path: Path) -> None:
        """(c) unit half: no claim file anywhere -> indeterminate, fail-open."""
        result = _run_unit(
            tmp_path,
            task_under_test="task-a",
            claim_files={},
            notes={"task-a": ("claimed", "cx-test")},
        )
        assert result.returncode == 1, (
            f"missing claim cache was treated as TERMINAL. stderr: {result.stderr}"
        )
        assert "indeterminate" in result.stderr


# ---------------------------------------------------------------------------
# Integration harness: run the REAL launcher end-to-end with a fake claude.
# ---------------------------------------------------------------------------


def _stub_bin(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(0o755)


def _integration_env(home: Path, bin_dir: Path, pipe_dir: Path, vault: Path, relay: Path) -> dict:
    env = os.environ.copy()
    # Host-independence: scrub every dispatch/identity/relay var the host lane
    # estate may have exported (this host currently carries the claude-headless
    # DISABLE latch — pointing the launcher under test at it would exit 77).
    for var in (
        "HAPAX_DISPATCH_HOST",
        "HAPAX_DISPATCH_HOST_FALLBACK",
        "HAPAX_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "HAPAX_AGENT_ROLE",
        "HAPAX_AGENT_NAME",
        "CLAUDE_ROLE",
        "HAPAX_WORKTREE_ROLE",
        "HAPAX_METHODOLOGY_DISPATCH_TASK",
        "HAPAX_CLAUDE_BIN",
        "HAPAX_CLAUDE_BIN_PATH",
        "NPM_CONFIG_PREFIX",
        "HAPAX_RELAY_DIR",
        "HAPAX_CC_TASK_ROOT",
        "HAPAX_COUNCIL_DIR",
        "HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS",
        "HAPAX_CLAUDE_HEADLESS_DISABLE_FILE",
        "HAPAX_CLAUDE_HEADLESS_ENABLE_FILE",
        "HAPAX_CLAUDE_HEADLESS_WORKDIR",
        "HAPAX_CLAUDE_HEADLESS_RESTART_BACKOFF_SECONDS",
        "HAPAX_GH_REPO",
        "GH_REPO",
        "HAPAX_CLAIM_STAMP_GRACE_S",
        "HAPAX_CLAIM_EPOCH_CHECK_BYPASS",
    ):
        env.pop(var, None)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
    # Don't re-exec into a real systemd scope from the test sandbox.
    env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
    env["HAPAX_CLAUDE_HEADLESS_PIPE_DIR"] = str(pipe_dir)
    env["HAPAX_CLAUDE_HEADLESS_RESTART_BACKOFF_SECONDS"] = "0"
    env["HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS"] = "0.5"
    env["HAPAX_CC_TASK_ROOT"] = str(vault)
    env["HAPAX_RELAY_DIR"] = str(relay)
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)  # resolves the real hapax-relay-retire
    return env


def _make_lane(
    tmp_path: Path,
    *,
    claude_body: str,
    notes: dict[str, str],
    claim: str = "task-a",
) -> tuple[dict, Path, Path, Path, Path, Path]:
    """Build a sandboxed lane: fake claude, claim cache, vault notes, relay.

    Returns (env, home, cache, vault, pipe_dir, relay_dir). Notes map task id
    to status; every note is assigned to beta with pr: null.
    """
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text(f"{claim}\n", encoding="utf-8")
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    for note_task, status in notes.items():
        (vault / "active" / f"{note_task}.md").write_text(
            f"---\ntask_id: {note_task}\nstatus: {status}\nassigned_to: beta\npr: null\n---\n",
            encoding="utf-8",
        )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", claude_body)
    pipe_dir = tmp_path / "pipe"
    relay_dir = tmp_path / "relay"
    relay_dir.mkdir()
    (relay_dir / "beta-status.yaml").write_text("role: beta\nstatus: active\n", encoding="utf-8")
    env = _integration_env(home, bin_dir, pipe_dir, vault, relay_dir)
    return env, home, cache, vault, pipe_dir, relay_dir


def _write_note(vault: Path, task: str, status: str) -> None:
    (vault / "active" / f"{task}.md").write_text(
        f"---\ntask_id: {task}\nstatus: {status}\nassigned_to: beta\npr: null\n---\n",
        encoding="utf-8",
    )


def _wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise TimeoutError("condition not met within timeout")


def _reap_stray_fake_claudes() -> None:
    subprocess.run(["pkill", "-TERM", "-f", f"sleep {FAKE_CLAUDE_SLEEP}"], check=False)


def _retired_reason(relay_dir: Path, role: str = "beta") -> str:
    text = (relay_dir / f"{role}-status.yaml").read_text(encoding="utf-8")
    assert "status: retired" in text, f"relay was not retired:\n{text}"
    for line in text.splitlines():
        if line.startswith("retired_reason:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no retired_reason in relay status:\n{text}")


def test_claim_hop_lane_survives_and_launcher_follows(tmp_path: Path) -> None:
    """(a) end-to-end: a persistent claude whose lane claim-hops to a second
    LIVE row is NOT killed; the launcher logs claim_moved and re-binds its
    current-task file to the new row. Red before the fix (the old watchdog
    SIGTERMd within one poll of the hop)."""
    env, home, cache, vault, pipe_dir, _relay = _make_lane(
        tmp_path,
        claude_body=f"exec sleep {FAKE_CLAUDE_SLEEP}\n",
        notes={"task-a": "claimed", "task-b": "claimed"},
    )
    out = tmp_path / "launcher.out"
    proc = None
    try:
        with out.open("w") as stdout:
            proc = subprocess.Popen(
                [str(SCRIPT), "--task", "task-a", "beta", "governed prompt"],
                env=env,
                stdout=stdout,
                stderr=subprocess.STDOUT,
                text=True,
            )
            _wait_for(lambda: (pipe_dir / "beta.pid").exists())
            claude_pid = int((pipe_dir / "beta.pid").read_text(encoding="utf-8").strip())

            # The governed re-point: the lane takes a second live row while its
            # launch row waits on its PR (gamma 2026-09-16T10:05:19Z).
            (cache / "cc-active-task-beta").write_text("task-b\n", encoding="utf-8")
            time.sleep(2.0)  # >= 3 terminality polls at 0.5s

            assert proc.poll() is None, (
                f"launcher died on a claim hop (the gamma kill):\n{out.read_text()}"
            )
            os.kill(claude_pid, 0)  # claude itself must still be alive
            bound = (pipe_dir / "beta.current-task").read_text(encoding="utf-8").strip()
            assert bound == "task-b", f"launcher did not re-bind to the new task (bound={bound!r})"
            hops = home / ".cache" / "hapax" / "claude-headless" / "beta" / "task-hops.log"
            hops_text = hops.read_text(encoding="utf-8") if hops.exists() else ""
            assert "claim_moved:task-a:task-b" in hops_text
    finally:
        # Governed end: close the bound row so the launcher self-reaps; never
        # leak a fake claude on a failure.
        _write_note(vault, "task-b", "closed")
        _write_note(vault, "task-a", "closed")
        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        _reap_stray_fake_claudes()

    assert proc is not None and proc.returncode == 0
    text = out.read_text(encoding="utf-8")
    assert "self-reaping" in text
    assert "stopping respawn loop" in text


def test_launch_row_close_kills_within_one_poll(tmp_path: Path) -> None:
    """(b) end-to-end: with a persistent claude and a LIVE launch row the lane
    survives; once the row is measurably closed the watchdog SIGTERMs within
    one poll (zombie-launcher-fix non-regression)."""
    env, _home, _cache, vault, pipe_dir, _relay = _make_lane(
        tmp_path,
        claude_body=f"exec sleep {FAKE_CLAUDE_SLEEP}\n",
        notes={"task-a": "claimed"},
    )
    out = tmp_path / "launcher.out"
    proc = None
    try:
        with out.open("w") as stdout:
            proc = subprocess.Popen(
                [str(SCRIPT), "--task", "task-a", "beta", "governed prompt"],
                env=env,
                stdout=stdout,
                stderr=subprocess.STDOUT,
                text=True,
            )
            _wait_for(lambda: (pipe_dir / "beta.pid").exists())
            time.sleep(1.2)  # >= 2 polls with a live row — must survive
            assert proc.poll() is None, f"lane died on a live row:\n{out.read_text()}"

            closed_at = time.monotonic()
            _write_note(vault, "task-a", "closed")
            proc.wait(timeout=15)
            elapsed = time.monotonic() - closed_at
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        _reap_stray_fake_claudes()

    assert proc is not None and proc.returncode == 0
    text = out.read_text(encoding="utf-8")
    assert "self-reaping" in text
    assert "stopping respawn loop" in text
    assert elapsed < 3.0, f"kill took {elapsed:.1f}s — far beyond one 0.5s poll"


def test_missing_claim_file_mid_run_stays_indeterminate_no_kill(tmp_path: Path) -> None:
    """(c) end-to-end: the claim cache vanishes mid-run (the 2026-06-12
    delta/zeta shape) while the row stays live -> indeterminate, no kill."""
    env, _home, cache, vault, pipe_dir, _relay = _make_lane(
        tmp_path,
        claude_body=f"exec sleep {FAKE_CLAUDE_SLEEP}\n",
        notes={"task-a": "claimed"},
    )
    out = tmp_path / "launcher.out"
    proc = None
    try:
        with out.open("w") as stdout:
            proc = subprocess.Popen(
                [str(SCRIPT), "--task", "task-a", "beta", "governed prompt"],
                env=env,
                stdout=stdout,
                stderr=subprocess.STDOUT,
                text=True,
            )
            _wait_for(lambda: (pipe_dir / "beta.pid").exists())
            claude_pid = int((pipe_dir / "beta.pid").read_text(encoding="utf-8").strip())
            (cache / "cc-active-task-beta").unlink()  # cache vanishes mid-run
            time.sleep(2.0)  # >= 3 polls
            assert proc.poll() is None, (
                f"lane died when its claim cache vanished:\n{out.read_text()}"
            )
            os.kill(claude_pid, 0)
    finally:
        _write_note(vault, "task-a", "closed")
        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        _reap_stray_fake_claudes()
    assert proc is not None and proc.returncode == 0


def test_sigterm_teardown_records_self_reap_not_clean_exit(tmp_path: Path) -> None:
    """(d): a watchdog-SIGTERMd lane must record the real reason. The measured
    gamma incident wrote `retired_reason: clean exit (headless)` for a SIGTERM.
    Red before the fix."""
    env, _home, _cache, _vault, _pipe, relay_dir = _make_lane(
        tmp_path,
        claude_body=f"exec sleep {FAKE_CLAUDE_SLEEP}\n",
        notes={"task-a": "closed"},  # measurably closed from the start
    )
    try:
        result = subprocess.run(
            [str(SCRIPT), "--task", "task-a", "beta", "governed prompt"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        _reap_stray_fake_claudes()
        raise

    assert result.returncode == 0, result.stderr
    assert "self-reaping" in result.stdout  # the kill was a SIGTERM self-reap
    reason = _retired_reason(relay_dir)
    assert reason.startswith("self_reap:row_status_closed"), (
        f"SIGTERM teardown recorded the wrong reason: {reason!r}"
    )
    assert "exit_code=143" in reason  # 128 + SIGTERM
    assert "clean exit" not in reason


def test_own_exit_zero_with_result_event_is_clean_exit(tmp_path: Path) -> None:
    """(e) positive bound: 'clean exit (headless)' is correct when the child
    exited 0 on its own AND a result event is present in the log."""
    env, _home, _cache, _vault, _pipe, relay_dir = _make_lane(
        tmp_path,
        claude_body='printf \'%s\\n\' \'{"type":"result","subtype":"success"}\'\nexit 0\n',
        notes={"task-a": "done"},
    )
    result = subprocess.run(
        [str(SCRIPT), "--task", "task-a", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert _retired_reason(relay_dir) == "clean exit (headless)"


def test_own_exit_zero_without_result_event_is_not_clean_exit(tmp_path: Path) -> None:
    """(e) negative bound: a 0-exit child with NO result event in the log is
    own_exit, not 'clean exit'. Red before the fix (always 'clean exit')."""
    env, _home, _cache, _vault, _pipe, relay_dir = _make_lane(
        tmp_path,
        claude_body="exit 0\n",
        notes={"task-a": "done"},
    )
    result = subprocess.run(
        [str(SCRIPT), "--task", "task-a", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    reason = _retired_reason(relay_dir)
    assert reason.startswith("own_exit:code_0"), f"wrong reason: {reason!r}"
    assert "clean exit" not in reason
