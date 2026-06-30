"""Tests for the MCP connector mutator receipt gate."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "mcp-connector-mutator-gate.sh"
BASH = Path("/usr/bin/bash") if Path("/usr/bin/bash").exists() else Path("/bin/bash")

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
    payload: dict,
    *,
    home: Path,
    role: str | None = "cx-red",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    for key in _CLEARED_ENV:
        env.pop(key, None)
    if role is not None:
        env["CODEX_THREAD_NAME"] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(BASH), str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )


def _path_without_python(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("cat", "dirname", "jq"):
        target = shutil.which(name)
        assert target is not None
        (bin_dir / name).symlink_to(target)
    return str(bin_dir)


def _path_without_jq(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin-no-jq"
    bin_dir.mkdir()
    for name in ("cat", "dirname"):
        target = shutil.which(name)
        assert target is not None
        (bin_dir / name).symlink_to(target)
    return str(bin_dir)


def _run_gate_text(
    payload: str, *, home: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    for key in _CLEARED_ENV:
        env.pop(key, None)
    env["CODEX_THREAD_NAME"] = "cx-red"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(BASH), str(HOOK)],
        input=payload,
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


def test_python3_absent_classifier_path_fails_closed(tmp_path: Path) -> None:
    result = _run_gate(
        {
            "tool_name": "mcp__codex_apps__gmail___forward_emails",
            "tool_input": {"message_ids": ["m1"], "to": "person@example.com"},
        },
        home=tmp_path,
        extra_env={"PATH": _path_without_python(tmp_path)},
    )

    assert result.returncode == 2
    assert "connector classifier failed" in result.stderr


def test_jq_absent_blocks_instead_of_passing_empty_tool_name(tmp_path: Path) -> None:
    result = _run_gate(
        {
            "tool_name": "mcp__codex_apps__gmail___forward_emails",
            "tool_input": {"message_ids": ["m1"], "to": "person@example.com"},
        },
        home=tmp_path,
        extra_env={"PATH": _path_without_jq(tmp_path)},
    )

    assert result.returncode == 2
    assert "cannot parse hook payload tool_name" in result.stderr


def test_malformed_hook_payload_blocks_instead_of_passing_empty_tool_name(
    tmp_path: Path,
) -> None:
    result = _run_gate_text("{", home=tmp_path)

    assert result.returncode == 2
    assert "cannot parse hook payload tool_name" in result.stderr
