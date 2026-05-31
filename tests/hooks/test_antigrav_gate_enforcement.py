"""End-to-end witness: an Antigravity (agy) tool call hits a real Hapax gate.

This is the acceptance witness for the Antigrav enforcing-gate parity P0. It does
NOT stub the gate: it pipes representative `agy` PreToolUse payloads through the
real chain that `scripts/hapax-antigrav` wires into
`$HOME/.gemini/antigravity-cli/hooks.json` —

    antigrav-hook-adapter.sh  ->  cc-task-gate.sh

— and proves that an unauthorized agy mutation (a session with no claimed
cc-task) is BLOCKED, while a read-only agy tool call is allowed through.

The hooks.json that drives this chain in production is asserted by
tests/scripts/test_hapax_antigrav_launcher.py; the agy tool-name translation is
asserted by tests/hooks/test_antigrav_hook_adapter.py. Together they witness that
an agy run_command / write_to_file / replace_file_content call reaches and is
adjudicated by the same governance chokepoint Claude Code and Codex enforce.

(A fully live witness — agy itself executing the gated tool call — is blocked by
the agy CLI's interactive OAuth wall; the config path + load are strace-verified.)
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER = REPO_ROOT / "hooks" / "scripts" / "antigrav-hook-adapter.sh"
GATE = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"


def _run_chain(
    payload: dict, *, home: Path, role: str = "antigrav-witness"
) -> subprocess.CompletedProcess[str]:
    """Run agy payload -> adapter -> real cc-task-gate with a controlled env.

    The env is built from scratch (not inherited) so a lane session's own
    CLAUDE_ROLE / claim files cannot leak in and change the verdict.
    """
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "HAPAX_AGENT_ROLE": role,
    }
    return subprocess.run(
        ["bash", str(ADAPTER), str(GATE)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
    )


def test_agy_run_command_mutation_is_blocked_without_claim(tmp_path: Path) -> None:
    result = _run_chain(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "run_command",
            "tool_input": {"command": "rm -rf /tmp/hapax-witness-target"},
        },
        home=tmp_path,
    )

    assert result.returncode != 0, (
        f"agy run_command mutation was NOT gated (rc=0). stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "cc-task-gate" in result.stderr


def test_agy_write_to_file_is_blocked_without_claim(tmp_path: Path) -> None:
    # write_to_file is the mapping added for agy parity; prove it reaches the
    # gate and is blocked when writing a non-cognition, unscoped path.
    result = _run_chain(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "write_to_file",
            "tool_input": {"file_path": "/etc/hapax-witness.conf", "content": "x"},
        },
        home=tmp_path,
    )

    assert result.returncode != 0, (
        f"agy write_to_file was NOT gated (rc=0). stderr={result.stderr!r}"
    )
    assert "cc-task-gate" in result.stderr


def test_agy_read_only_tool_is_allowed(tmp_path: Path) -> None:
    # Read-only agy tools must pass: a blocked lane can still inspect state.
    result = _run_chain(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "read_file",
            "tool_input": {"file_path": "/etc/hostname"},
        },
        home=tmp_path,
    )

    assert result.returncode == 0, f"read-only agy tool was blocked. stderr={result.stderr!r}"
