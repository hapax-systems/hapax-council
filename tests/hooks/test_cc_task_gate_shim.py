"""Tests for the cc-task-gate stable-abs-path shim (reform FM-6 gate collapse).

hooks/scripts/cc-task-gate.sh is a thin shim that resolves to ONE canonical gate
impl (deployed to $HAPAX_CANONICAL_HOOKS), with a co-located impl fallback, and
NEVER fails stuck: when no impl is reachable it fails OPEN with a ledger line so a
blocked lane can still write cognition surfaces (INV-5). These tests pin that
resolution order and the stdin/exit passthrough contract. Self-contained per
project conventions (no shared conftest).
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"
IMPL = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"

# A live lane session leaks identity env into subprocesses; clear it so the real
# gate impl resolves role/claim from the test context, not from the runner.
_LEAKY = (
    "CLAUDE_ROLE",
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_SLOT",
    "HAPAX_SESSION_ID",
    "HAPAX_WORKTREE_ROLE",
    "CODEX_ROLE",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
)


def _env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    for key in _LEAKY:
        env.pop(key, None)
    env.update(overrides)
    return env


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)


def _run_shim(gate: Path, payload: dict, *, env: dict[str, str], timeout: int = 20):
    return subprocess.run(
        ["bash", str(gate)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=timeout,
    )


def test_shim_carries_marker():
    assert "HAPAX-GATE-SHIM" in SHIM.read_text(encoding="utf-8")


def test_resolves_colocated_impl_when_no_canonical():
    # canonical absent -> co-located impl (the repo's real gate). A Read is
    # non-mutating, so the impl allows (exit 0): proves the shim reached the impl.
    result = _run_shim(
        SHIM,
        {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}},
        env=_env(HAPAX_CANONICAL_HOOKS="/nonexistent/hapax-canon"),
    )
    assert result.returncode == 0, result.stderr


def test_cognition_write_allowed_through_shim():
    # INV-5 carve-out must survive the shim -> impl hop: a /dev/shm write is a
    # cognition surface and is allowed even though it is a mutating tool.
    result = _run_shim(
        SHIM,
        {"tool_name": "Write", "tool_input": {"file_path": "/dev/shm/hapax-shim-test"}},
        env=_env(HAPAX_CANONICAL_HOOKS="/nonexistent/hapax-canon"),
    )
    assert result.returncode == 0, result.stderr


def test_canonical_takes_precedence_over_impl(tmp_path):
    # A fake canonical prints a sentinel + exits 0. The shim must exec IT, not the
    # co-located impl (which would BLOCK this out-of-scope /etc write).
    canon = tmp_path / "canon"
    _write_exec(canon / "cc-task-gate.sh", "#!/usr/bin/env bash\necho CANON_SENTINEL\nexit 0\n")
    result = _run_shim(
        SHIM,
        {"tool_name": "Write", "tool_input": {"file_path": "/etc/whatever"}},
        env=_env(HAPAX_CANONICAL_HOOKS=str(canon)),
    )
    assert "CANON_SENTINEL" in result.stdout
    assert result.returncode == 0


def test_stdin_passthrough(tmp_path):
    canon = tmp_path / "canon"
    _write_exec(canon / "cc-task-gate.sh", "#!/usr/bin/env bash\ncat\nexit 0\n")
    result = _run_shim(
        SHIM,
        {"tool_name": "Write", "tool_input": {"file_path": "/x"}, "marker": "STDIN_OK"},
        env=_env(HAPAX_CANONICAL_HOOKS=str(canon)),
    )
    assert "STDIN_OK" in result.stdout


def test_exit_code_passthrough(tmp_path):
    canon = tmp_path / "canon"
    _write_exec(canon / "cc-task-gate.sh", "#!/usr/bin/env bash\nexit 2\n")
    result = _run_shim(
        SHIM,
        {"tool_name": "Write", "tool_input": {"file_path": "/x"}},
        env=_env(HAPAX_CANONICAL_HOOKS=str(canon)),
    )
    assert result.returncode == 2


def test_fail_open_when_no_impl_reachable(tmp_path):
    # ONLY the shim in an isolated dir (no co-located impl) + no canonical: the
    # shim must fail OPEN (exit 0) with a warning + ledger line, never fail-stuck.
    isolated = tmp_path / "iso"
    _write_exec(isolated / "cc-task-gate.sh", SHIM.read_text(encoding="utf-8"))
    home = tmp_path / "home"
    home.mkdir()
    result = _run_shim(
        isolated / "cc-task-gate.sh",
        {"tool_name": "Write", "tool_input": {"file_path": "/etc/passwd"}},
        env=_env(HAPAX_CANONICAL_HOOKS="/nonexistent/hapax-canon", HOME=str(home)),
    )
    assert result.returncode == 0
    assert "canonical gate missing" in result.stderr
    ledger = home / ".cache" / "hapax" / "cc-task-gate-shim.log"
    assert ledger.exists()
    assert "canonical_gate_missing" in ledger.read_text(encoding="utf-8")


def test_no_self_exec_loop():
    # Point canonical at the shim's OWN dir (canonical/cc-task-gate.sh IS a shim):
    # the -ef self-guard must prevent an infinite exec loop and fall through to the
    # co-located impl. The assertion that matters is that it TERMINATES (no
    # subprocess timeout) and returns the impl's allow for a non-mutating tool.
    result = _run_shim(
        SHIM,
        {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}},
        env=_env(HAPAX_CANONICAL_HOOKS=str(SHIM.parent)),
        timeout=15,
    )
    assert result.returncode == 0
