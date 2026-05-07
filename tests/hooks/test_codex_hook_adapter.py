"""Codex hook adapter contract tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
ADAPTER = REPO_ROOT / "hooks" / "scripts" / "codex-hook-adapter.sh"


def _make_repo_on_main(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)
    (path / "README.md").write_text("repo\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True, env=env)
    subprocess.run(["git", "branch", "alpha/foo"], cwd=path, check=True)
    return path


def _run_adapter(
    payload: dict,
    *,
    home: Path,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("CODEX_ROLE", None)
    env.pop("CODEX_SESSION", None)
    env.pop("CODEX_SESSION_NAME", None)
    env["CODEX_THREAD_NAME"] = "cx-red"
    env["HAPAX_WORKTREE_ROLE"] = "alpha"
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        ["bash", str(ADAPTER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd or REPO_ROOT),
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_permission_request_auto_approves_no_ask_policy(tmp_path: Path) -> None:
    result = _run_adapter(
        {"hook_event_name": "PermissionRequest", "session_id": "s1"},
        home=tmp_path,
    )
    assert result["decision"] == "approve"


def test_shell_command_normalizes_to_bash_and_blocks_direct_pip(tmp_path: Path) -> None:
    result = _run_adapter(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "pip install requests"},
        },
        home=tmp_path,
    )
    assert result["decision"] == "block"
    assert "pip" in result["reason"].lower()


def test_shell_command_runs_session_name_enforcement(tmp_path: Path) -> None:
    result = _run_adapter(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "scripts/hapax-codex --session zeta -- mcp list"},
        },
        home=tmp_path,
    )

    assert result["decision"] == "block"
    assert "session-name-enforcement.sh" in result["reason"]
    assert "unknown session name" in result["reason"].lower()


def test_shell_command_runs_canonical_worktree_protect(tmp_path: Path) -> None:
    canonical = _make_repo_on_main(tmp_path / "canonical")
    result = _run_adapter(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "cwd": str(canonical),
            "tool_name": "exec_command",
            "tool_input": {"cmd": "git switch alpha/foo"},
        },
        home=tmp_path,
        cwd=REPO_ROOT,
        extra_env={"HAPAX_CANONICAL_PATH_OVERRIDE": str(canonical)},
    )

    assert result["decision"] == "block"
    assert "canonical-worktree-protect.sh" in result["reason"]
    assert "Canonical worktree" in result["reason"]


def test_task_gate_blocks_destructive_shell_without_claim(tmp_path: Path) -> None:
    result = _run_adapter(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "git commit -m test"},
        },
        home=tmp_path,
        extra_env={"HAPAX_CC_TASK_GATE": "1"},
    )

    assert result["decision"] == "block"
    assert "no claimed task" in result["reason"].lower()


def test_task_gate_allows_readonly_shell_without_claim(tmp_path: Path) -> None:
    result = _run_adapter(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "ls -la"},
        },
        home=tmp_path,
        extra_env={"HAPAX_CC_TASK_GATE": "1"},
    )

    assert result.get("continue") is True


def test_apply_patch_is_scanned_by_axiom_guard(tmp_path: Path) -> None:
    patch = """*** Begin Patch
*** Add File: agents/example_user_manager.py
+class UserManager:
+    pass
*** End Patch
"""
    result = _run_adapter(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "apply_patch",
            "tool_input": {"patch": patch},
        },
        home=tmp_path,
    )
    assert result["decision"] == "block"
    assert "single_user" in result["reason"]


def test_apply_patch_runs_pipewire_graph_edit_gate(tmp_path: Path) -> None:
    patch = """*** Begin Patch
*** Update File: config/pipewire/hapax-livestream-tap.conf
@@
+context.modules = []
*** End Patch
"""
    result = _run_adapter(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "apply_patch",
            "tool_input": {"patch": patch},
        },
        home=tmp_path,
        extra_env={"HAPAX_PIPEWIRE_GRAPH_LOCK_ROOT": str(tmp_path / "lock")},
    )

    assert result["decision"] == "block"
    assert "pipewire-graph-edit-gate.sh" in result["reason"]
    assert "requires applier lock" in result["reason"]


def test_session_start_returns_codex_additional_context(tmp_path: Path) -> None:
    relay = tmp_path / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True)
    (relay / "PROTOCOL.md").write_text("# Relay\n")
    (relay / "alpha.yaml").write_text("session: alpha\nsession_status: ACTIVE\n")
    (relay / "beta.yaml").write_text("session: beta\nsession_status: ACTIVE\n")
    vault = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (vault / "active").mkdir(parents=True)

    result = _run_adapter(
        {
            "hook_event_name": "SessionStart",
            "session_id": "s1",
            "cwd": str(REPO_ROOT),
            "tool_name": "",
            "tool_input": {},
        },
        home=tmp_path,
    )
    assert result["continue"] is True
    assert result["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "CC-TASK SSOT" in result["hookSpecificOutput"]["additionalContext"]
    assert "codex/cx-red" in result["hookSpecificOutput"]["additionalContext"]
