"""Tests for hooks/scripts/conductor-start.sh + conductor-stop.sh.

These hooks bracket a Claude Code session: ``conductor-start.sh`` is a
SessionStart hook that spawns the per-role session-conductor sidecar
under a systemd-run scope; ``conductor-stop.sh`` is the Stop hook that
shuts it down. Both source ``agent-role.sh`` for the role-name helper
and gate on ``session_id`` from the JSON payload.

Existing tests cover ``conductor-pre.sh`` and ``conductor-post.sh``.
This file closes the start/stop gap.

Active-path testing is out of scope here — both hooks invoke
``systemd-run`` / ``uv run python -m agents.session_conductor`` which
create real side effects (systemd scope, daemon process, /run/user/
sockets). The CI rust-check / smoke-test job would catch behavioral
regressions in the conductor itself; these tests pin the early-exit
gating + source contract that doesn't require a full conductor sandbox.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
START_HOOK = REPO_ROOT / "hooks" / "scripts" / "conductor-start.sh"
STOP_HOOK = REPO_ROOT / "hooks" / "scripts" / "conductor-stop.sh"


def _run(hook: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


# ── Early-exit: missing session_id ─────────────────────────────────


class TestSessionIdGate:
    def test_start_exits_silent_with_no_session_id(self) -> None:
        """No `session_id` in payload → start hook exits 0 without
        invoking systemd-run."""
        result = _run(START_HOOK, {})
        assert result.returncode == 0
        # The systemd-run command shouldn't have run; nothing in stderr.
        assert "systemd-run" not in result.stderr
        assert "conductor" not in result.stdout.lower()

    def test_stop_exits_silent_with_no_session_id(self) -> None:
        """No `session_id` → stop hook exits 0 without invoking the
        conductor stop subcommand."""
        result = _run(STOP_HOOK, {})
        assert result.returncode == 0

    def test_start_exits_silent_with_empty_session_id(self) -> None:
        result = _run(START_HOOK, {"session_id": ""})
        assert result.returncode == 0


# ── Source contract: hooks invoke the right subprocesses ───────────


class TestStartSourceContract:
    def test_start_spawns_systemd_run_scope(self) -> None:
        """Pin that the start hook uses `systemd-run --user --scope` to
        bracket the conductor — the operator's lifecycle invariant."""
        body = START_HOOK.read_text(encoding="utf-8")
        assert "systemd-run --user --scope" in body

    def test_start_invokes_conductor_module_with_start_arg(self) -> None:
        body = START_HOOK.read_text(encoding="utf-8")
        assert "agents.session_conductor" in body
        assert " start" in body  # subcommand on the python -m line

    def test_start_passes_role_to_conductor(self) -> None:
        """Role-keyed conductor: each role lane gets its own sidecar."""
        body = START_HOOK.read_text(encoding="utf-8")
        assert '--role "$ROLE"' in body

    def test_start_dedupes_via_role_pid_file(self) -> None:
        """Don't double-launch when an existing conductor is alive."""
        body = START_HOOK.read_text(encoding="utf-8")
        assert "conductor-${ROLE}.pid" in body
        assert "kill -0" in body

    def test_start_waits_for_socket(self) -> None:
        """Pin the socket-wait loop so a future refactor doesn't drop it
        and race the next IPC call past conductor readiness."""
        body = START_HOOK.read_text(encoding="utf-8")
        assert "conductor-${ROLE}.sock" in body
        assert "[ -S " in body  # the existence-check inside the loop


class TestStopSourceContract:
    def test_stop_invokes_conductor_module_with_stop_arg(self) -> None:
        body = STOP_HOOK.read_text(encoding="utf-8")
        assert "agents.session_conductor" in body
        assert " stop" in body

    def test_stop_passes_role(self) -> None:
        body = STOP_HOOK.read_text(encoding="utf-8")
        assert '--role "$ROLE"' in body

    def test_stop_failure_swallowed(self) -> None:
        """Stop must be idempotent; a missing/dead conductor isn't an error."""
        body = STOP_HOOK.read_text(encoding="utf-8")
        assert "|| true" in body


# ── agent-role.sh sourcing ─────────────────────────────────────────


class TestAgentRoleSourcing:
    def test_start_sources_agent_role(self) -> None:
        """Both hooks source agent-role.sh for the role-name helper."""
        body = START_HOOK.read_text(encoding="utf-8")
        assert "agent-role.sh" in body

    def test_stop_sources_agent_role(self) -> None:
        body = STOP_HOOK.read_text(encoding="utf-8")
        assert "agent-role.sh" in body

    def test_start_uses_default_alpha_role(self) -> None:
        """When the role helper can't determine a role, default is alpha."""
        body = START_HOOK.read_text(encoding="utf-8")
        assert "hapax_agent_role_or_default alpha" in body

    def test_stop_uses_default_alpha_role(self) -> None:
        body = STOP_HOOK.read_text(encoding="utf-8")
        assert "hapax_agent_role_or_default alpha" in body


# ── Hook integrity ─────────────────────────────────────────────────


class TestHookIntegrity:
    def test_start_hook_is_executable(self) -> None:
        assert os.access(START_HOOK, os.X_OK)

    def test_stop_hook_is_executable(self) -> None:
        assert os.access(STOP_HOOK, os.X_OK)

    def test_both_hooks_use_strict_bash(self) -> None:
        for hook in (START_HOOK, STOP_HOOK):
            body = hook.read_text(encoding="utf-8")
            assert body.startswith("#!/usr/bin/env bash"), f"{hook}: missing bash shebang"
            assert "set -euo pipefail" in body, f"{hook}: missing strict mode"
