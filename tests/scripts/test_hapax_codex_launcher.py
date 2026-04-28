"""Tests for the Hapax Codex launcher."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "hapax-codex"


def _env_with_fake_codex(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "codex-args.txt"
    env_file = tmp_path / "codex-env.txt"
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" > {args_file}
printf 'HAPAX_AGENT_INTERFACE=%s\\n' "$HAPAX_AGENT_INTERFACE" > {env_file}
printf 'HAPAX_AGENT_NAME=%s\\n' "$HAPAX_AGENT_NAME" >> {env_file}
printf 'HAPAX_AGENT_SLOT=%s\\n' "$HAPAX_AGENT_SLOT" >> {env_file}
printf 'HAPAX_WORKTREE_ROLE=%s\\n' "$HAPAX_WORKTREE_ROLE" >> {env_file}
printf 'CODEX_THREAD_NAME=%s\\n' "$CODEX_THREAD_NAME" >> {env_file}
printf 'HAPAX_IDLE_UPDATE_SECONDS=%s\\n' "$HAPAX_IDLE_UPDATE_SECONDS" >> {env_file}
printf 'GITHUB_PERSONAL_ACCESS_TOKEN=%s\\n' "${{GITHUB_PERSONAL_ACCESS_TOKEN:-}}" >> {env_file}
printf 'CODEX_GITHUB_PERSONAL_ACCESS_TOKEN=%s\\n' "${{CODEX_GITHUB_PERSONAL_ACCESS_TOKEN:-}}" >> {env_file}
printf 'TAVILY_API_KEY=%s\\n' "${{TAVILY_API_KEY:-}}" >> {env_file}
"""
    )
    fake_codex.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["HOME"] = str(tmp_path / "home")
    env.pop("CODEX_THREAD_NAME", None)
    env.pop("CODEX_ROLE", None)
    env.pop("CODEX_SESSION_NAME", None)
    env.pop("CODEX_SESSION", None)
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("HAPAX_AGENT_ROLE", None)
    return env, args_file, env_file


def test_rejects_slot_name_as_visible_session(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "alpha",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--",
            "mcp",
            "list",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "expected cx-<color>" in result.stderr


def test_valid_codex_session_execs_codex_with_no_ask_flags(tmp_path: Path) -> None:
    env, args_file, env_file = _env_with_fake_codex(tmp_path)

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-red",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--",
            "mcp",
            "list",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    args = args_file.read_text()
    assert "--dangerously-bypass-approvals-and-sandbox" in args
    assert "--cd" in args
    assert str(REPO_ROOT) in args
    assert "mcp list" in args

    launched_env = env_file.read_text()
    assert "HAPAX_AGENT_INTERFACE=codex" in launched_env
    assert "HAPAX_AGENT_NAME=cx-red" in launched_env
    assert "HAPAX_AGENT_SLOT=alpha" in launched_env
    assert "HAPAX_WORKTREE_ROLE=alpha" in launched_env
    assert "CODEX_THREAD_NAME=cx-red" in launched_env
    assert "HAPAX_IDLE_UPDATE_SECONDS=180" in launched_env


def test_launcher_scrubs_mcp_tokens_from_codex_session_env(tmp_path: Path) -> None:
    env, _args_file, env_file = _env_with_fake_codex(tmp_path)
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = "github-parent-token"
    env["CODEX_GITHUB_PERSONAL_ACCESS_TOKEN"] = "codex-github-parent-token"
    env["TAVILY_API_KEY"] = "tavily-parent-token"

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-red",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--",
            "mcp",
            "list",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    launched_env = env_file.read_text()
    assert "GITHUB_PERSONAL_ACCESS_TOKEN=\n" in launched_env
    assert "CODEX_GITHUB_PERSONAL_ACCESS_TOKEN=\n" in launched_env
    assert "TAVILY_API_KEY=\n" in launched_env
    assert "github-parent-token" not in launched_env
    assert "codex-github-parent-token" not in launched_env
    assert "tavily-parent-token" not in launched_env


def test_task_launch_generates_bootstrap_prompt_without_claim_when_disabled(tmp_path: Path) -> None:
    env, args_file, _env_file = _env_with_fake_codex(tmp_path)
    env["HAPAX_AGENT_NAME"] = "cx-red"
    env["CODEX_THREAD_NAME"] = "cx-red"

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-green",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--task",
            "demo-task",
            "--no-claim",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    args = args_file.read_text()
    assert "Bootstrap file:" in args

    bootstrap_files = list(
        (tmp_path / "cache" / "hapax" / "codex-spawns").glob("*cx-green-demo-task.md")
    )
    assert len(bootstrap_files) == 1
    bootstrap = bootstrap_files[0].read_text()
    assert "parent_session: cx-red" in bootstrap
    assert "session: cx-green" in bootstrap
    assert "task_id: demo-task" in bootstrap
    assert "idle_update_seconds: 180" in bootstrap
    assert f"{REPO_ROOT}/AGENTS.md" in bootstrap
    assert "relay/preflight note" in bootstrap
    assert "Codex version, MCP startup warnings" in bootstrap
    assert "not actively producing" in bootstrap
    assert "timestamp-only changes" in bootstrap
    assert "Use scripts/hapax-codex for child Codex sessions" in bootstrap
    assert "not watching" in bootstrap
    assert "baseline clean/regroup/stop" in bootstrap


def test_slot_relay_history_does_not_block_new_codex_session(tmp_path: Path) -> None:
    env, args_file, _env_file = _env_with_fake_codex(tmp_path)
    relay_dir = Path(env["HOME"]) / ".cache" / "hapax" / "relay"
    relay_dir.mkdir(parents=True)
    (relay_dir / "alpha.yaml").write_text(
        "session: alpha\n"
        "role: SUPERSEDED legacy Claude slot\n"
        "session_status: |\n"
        "  ACTIVE historical text with superseded_closed metadata\n"
    )

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-red",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--",
            "mcp",
            "list",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "mcp list" in args_file.read_text()


def test_default_child_workdir_uses_codex_session_path_not_legacy_slot(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    env["HAPAX_CODEX_CREATE_WORKTREE"] = "0"

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-green",
            "--slot",
            "delta",
            "--",
            "mcp",
            "list",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 3
    assert "hapax-council--cx-green" in result.stderr
    assert "hapax-council--delta" not in result.stderr


def test_current_session_relay_retirement_blocks_without_force(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    relay_dir = Path(env["HOME"]) / ".cache" / "hapax" / "relay"
    relay_dir.mkdir(parents=True)
    (relay_dir / "cx-red.yaml").write_text("session: cx-red\nstatus: SUPERSEDED\n")

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-red",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--",
            "mcp",
            "list",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 6
    assert "relay 'cx-red' is retired/superseded" in result.stderr


def test_terminal_tmux_starts_codex_runner_without_parent_claim(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    tmux_args = tmp_path / "tmux-args.txt"
    fake_tmux = tmp_path / "bin" / "tmux"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
if [ "$1" = "has-session" ]; then
  exit 1
fi
printf '%s\\n' "$@" > {tmux_args}
"""
    )
    fake_tmux.chmod(0o755)

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-amber",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--task",
            "demo-task",
            "--terminal",
            "tmux",
            "--force",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "hapax-codex-cx-amber"
    args = tmux_args.read_text()
    assert "new-session" in args
    assert "hapax-codex-cx-amber" in args

    runner = Path(args.strip().splitlines()[-1])
    runner_text = runner.read_text()
    assert "hapax-codex" in runner_text
    assert "--session cx-amber" in runner_text
    assert "--force" in runner_text
    assert "--task demo-task" in runner_text
    assert "--no-claim" not in runner_text


def test_terminal_foot_prefers_direct_foot_when_available(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    foot_args = tmp_path / "foot-args.txt"
    fake_foot = tmp_path / "bin" / "foot"
    fake_foot.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {foot_args}
"""
    )
    fake_foot.chmod(0o755)

    fake_footclient = tmp_path / "bin" / "footclient"
    fake_footclient.write_text(
        """#!/usr/bin/env bash
echo "footclient should not be selected" >&2
exit 99
"""
    )
    fake_footclient.chmod(0o755)

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-violet",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--terminal",
            "foot",
            "--bootstrap",
            str(tmp_path / "bootstrap.md"),
            "--no-claim",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 9
    assert "bootstrap file not found" in result.stderr

    bootstrap = tmp_path / "bootstrap.md"
    bootstrap.write_text("# bootstrap\n")
    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-violet",
            "--slot",
            "alpha",
            "--cd",
            str(REPO_ROOT),
            "--terminal",
            "foot",
            "--bootstrap",
            str(bootstrap),
            "--no-claim",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    for _ in range(20):
        if foot_args.exists():
            break
        time.sleep(0.05)
    args = foot_args.read_text()
    assert "--app-id\nhapax-codex-cx-violet" in args
    assert "--title\ncx-violet" in args
    assert "--working-directory" in args
