"""Tests for hooks/scripts/conductor-start.sh.

The hook is a wired SessionStart launcher: it spawns the per-role
conductor sidecar via systemd-run if not already running, waits up
to 3s for the UDS socket to appear, then dumps any pending
spawn-context file to stdout (Claude reads stdout as additional
session context) and deletes it.

Test surface covered here:
- empty stdin / missing session_id → exit 0 silently
- existing PID file pointing at a live process → no relaunch attempt,
  spawn-context untouched even when present (early-exit before the
  context-file branch)
- spawn-context file present + no live PID → contents printed to
  stdout, file deleted

Tests override $HOME so the hook's PID_DIR / spawn-context paths
land under the tmp test dir, leaving the real conductor state
untouched. systemd-run launch path is fire-and-forget and goes to
/dev/null; we verify behaviour around it, not the launch itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "conductor-start.sh"


def _run(
    payload: dict,
    home: Path,
    role: str = "test-start-role",
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HAPAX_AGENT_ROLE"] = role
    env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=10,
    )


@contextmanager
def _isolated_home(tmp_path: Path) -> Iterator[Path]:
    """Yield a tmp HOME with the conductor cache dir pre-created."""
    pid_dir = tmp_path / ".cache" / "hapax" / "conductor"
    pid_dir.mkdir(parents=True, exist_ok=True)
    yield tmp_path


# ── Early-exit paths ───────────────────────────────────────────────


class TestEarlyExits:
    def test_empty_stdin_exits_zero(self) -> None:
        result = subprocess.run(
            ["bash", str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0

    def test_missing_session_id_exits_zero(self, tmp_path: Path) -> None:
        with _isolated_home(tmp_path) as home:
            result = _run({"tool_name": "SessionStart"}, home=home)
        assert result.returncode == 0


# ── PID-file branch: live process → no relaunch ────────────────────


class TestExistingConductor:
    def test_alive_pid_short_circuits(self, tmp_path: Path) -> None:
        """When the PID file points at a live process, hook exits 0 without
        printing any spawn-context (which would be late-stage work)."""
        role = "test-alive-001"
        with _isolated_home(tmp_path) as home:
            pid_dir = home / ".cache" / "hapax" / "conductor"
            # Use our own PID — guaranteed alive for the duration of the test.
            (pid_dir / f"conductor-{role}.pid").write_text(str(os.getpid()))
            # Plant a spawn-context. If the hook honoured it, stdout
            # would contain "PROOF" — but the hook should short-circuit
            # before reaching the spawn-context branch.
            (pid_dir / "session-xyz.spawn-context").write_text("PROOF\n")

            t0 = time.monotonic()
            result = _run(
                {"session_id": "session-xyz", "tool_name": "SessionStart"},
                home=home,
                role=role,
            )
            elapsed = time.monotonic() - t0

        assert result.returncode == 0
        assert "PROOF" not in result.stdout
        # No socket-wait loop runs; hook returns immediately. The 3s wait
        # only fires on the launch path, so the alive-PID short-circuit
        # should be well under 1s even on a busy CI runner.
        assert elapsed < 1.5, f"hook took {elapsed:.2f}s, expected short-circuit"

    def test_stale_pid_falls_through_to_launch(self, tmp_path: Path) -> None:
        """When the PID file points at a dead process, hook proceeds to
        systemd-run and the socket-wait loop. We don't verify the spawn
        itself (background, /dev/null) but we DO verify the hook eventually
        exits without raising."""
        role = "test-stale-002"
        with _isolated_home(tmp_path) as home:
            pid_dir = home / ".cache" / "hapax" / "conductor"
            # PID 1 is init — kill -0 on it from a non-root user typically
            # returns EPERM, which `kill -0 ... 2>/dev/null` suppresses, so
            # use a definitely-dead very-high PID instead.
            (pid_dir / f"conductor-{role}.pid").write_text("999999")

            result = _run(
                {"session_id": "s2", "tool_name": "SessionStart"},
                home=home,
                role=role,
            )
        assert result.returncode == 0


# ── Spawn-context injection ────────────────────────────────────────


class TestSpawnContext:
    def test_context_file_is_dumped_and_deleted(self, tmp_path: Path) -> None:
        """When no conductor is running and a spawn-context file exists,
        hook prints its contents to stdout and removes the file."""
        role = "test-ctx-003"
        with _isolated_home(tmp_path) as home:
            pid_dir = home / ".cache" / "hapax" / "conductor"
            ctx_path = pid_dir / "spawn-test-ctx-001.spawn-context"
            ctx_path.write_text("INJECTED CONTEXT\n")

            result = _run(
                {"session_id": "spawn-test-ctx-001", "tool_name": "SessionStart"},
                home=home,
                role=role,
            )

        assert result.returncode == 0
        assert "INJECTED CONTEXT" in result.stdout
        assert not ctx_path.exists()

    def test_no_context_file_no_extra_stdout(self, tmp_path: Path) -> None:
        """Without a spawn-context file, hook produces no stdout."""
        role = "test-noctx-004"
        with _isolated_home(tmp_path) as home:
            result = _run(
                {"session_id": "no-ctx-session", "tool_name": "SessionStart"},
                home=home,
                role=role,
            )
        assert result.returncode == 0
        assert result.stdout == ""
