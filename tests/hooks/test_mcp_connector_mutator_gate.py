"""Tests for the MCP connector mutator receipt gate."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "mcp-connector-mutator-gate.sh"

_CLEARED_ENV = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_AGENT_SLOT",
    "HAPAX_AGENT_INTERFACE",
    "HAPAX_SESSION_ID",
    "CLAUDE_ROLE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_ROLE",
    "CODEX_SESSION",
    "CODEX_SESSION_NAME",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
    "CODEX_HOME",
)


def _run_gate(
    payload: dict, *, home: Path, role: str | None = "cx-red"
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    for key in _CLEARED_ENV:
        env.pop(key, None)
    if role is not None:
        env["CODEX_THREAD_NAME"] = role
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )


def test_read_only_mcp_tool_passes_without_claim(tmp_path: Path) -> None:
    result = _run_gate(
        {
            "tool_name": "mcp__context7__query-docs",
            "tool_input": {"libraryId": "/reactjs/react.dev"},
        },
        home=tmp_path,
    )

    assert result.returncode == 0


def test_side_effecting_connector_without_claim_blocks_with_next_action(tmp_path: Path) -> None:
    result = _run_gate(
        {
            "tool_name": "mcp__codex_apps__gmail___forward_emails",
            "tool_input": {"message_ids": ["m1"], "to": "person@example.com"},
        },
        home=tmp_path,
    )

    assert result.returncode == 2
    assert "no claimed task" in result.stderr
    assert "Next action:" in result.stderr


def test_side_effecting_connector_with_claim_requires_route_decision(tmp_path: Path) -> None:
    cache = tmp_path / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-cx-red").write_text("task-1\n", encoding="utf-8")

    result = _run_gate(
        {
            "tool_name": "mcp__codex_apps__gmail___forward_emails",
            "tool_input": {"message_ids": ["m1"], "to": "person@example.com"},
        },
        home=tmp_path,
    )

    assert result.returncode == 2
    assert "route_decision_absent" in result.stderr
    assert "Next action:" in result.stderr
