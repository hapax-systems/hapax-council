"""Tests for the Hapax Codex launcher."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "hapax-codex"
SENDER = REPO_ROOT / "scripts" / "hapax-codex-send"
HEALTH = REPO_ROOT / "scripts" / "hapax-codex-health"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "codex"


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


def _write_active_task(
    env: dict[str, str],
    task_id: str,
    *,
    status: str = "offered",
    assigned_to: str = "unassigned",
) -> Path:
    active_root = (
        Path(env["HOME"]) / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    )
    active_root.mkdir(parents=True, exist_ok=True)
    note = active_root / f"{task_id}.md"
    note.write_text(
        "\n".join(
            [
                "---",
                f"task_id: {task_id}",
                f"status: {status}",
                f"assigned_to: {assigned_to}",
                "claimed_at: null",
                "updated_at: 2026-04-28T00:00:00Z",
                "---",
                "",
                "## Session log",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return note


def _write_fake_tmux(bin_dir: Path, log_path: Path, *, has_session_exit: int = 1) -> Path:
    fake_tmux = bin_dir / "tmux"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {log_path}
if [ "$1" = "has-session" ]; then
  exit {has_session_exit}
fi
exit 0
"""
    )
    fake_tmux.chmod(0o755)
    return fake_tmux


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
    assert f'projects."{REPO_ROOT}".trust_level="trusted"' in args
    assert "mcp list" in args

    launched_env = env_file.read_text()
    assert "HAPAX_AGENT_INTERFACE=codex" in launched_env
    assert "HAPAX_AGENT_NAME=cx-red" in launched_env
    assert "HAPAX_AGENT_SLOT=alpha" in launched_env
    assert "HAPAX_WORKTREE_ROLE=alpha" in launched_env
    assert "CODEX_THREAD_NAME=cx-red" in launched_env
    assert "HAPAX_IDLE_UPDATE_SECONDS=270" in launched_env


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
    assert "idle_update_seconds: 270" in bootstrap
    assert f"{REPO_ROOT}/AGENTS.md" in bootstrap
    assert "relay/preflight note" in bootstrap
    assert "Codex version, MCP startup warnings" in bootstrap
    assert "not actively producing" in bootstrap
    assert "timestamp-only changes" in bootstrap
    assert "Use scripts/hapax-codex for child Codex sessions" in bootstrap
    assert "off by default as baseline defects" in bootstrap
    assert "not watching" in bootstrap
    assert "baseline clean/regroup/stop" in bootstrap


def test_task_claim_uses_selected_workdir_cc_claim(tmp_path: Path) -> None:
    env, args_file, _env_file = _env_with_fake_codex(tmp_path)
    _write_active_task(env, "demo-task")
    workdir = tmp_path / "target-worktree"
    claim_log = tmp_path / "target-claim.log"
    (workdir / "scripts").mkdir(parents=True)
    claim_script = workdir / "scripts" / "cc-claim"
    claim_script.write_text(
        f"""#!/usr/bin/env bash
printf '%s %s\\n' "$0" "$*" > {claim_log}
exit 0
""",
        encoding="utf-8",
    )
    claim_script.chmod(0o755)

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-green",
            "--slot",
            "delta",
            "--cd",
            str(workdir),
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert str(workdir) in args_file.read_text()
    assert claim_log.read_text(encoding="utf-8").strip() == f"{claim_script} demo-task"


def test_task_launch_appends_safe_operator_dossier_context(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    env["HAPAX_CODEX_OPERATOR_DOSSIER"] = str(FIXTURE_ROOT / "operator-dossier-safe.md")

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
    bootstrap_files = list(
        (tmp_path / "cache" / "hapax" / "codex-spawns").glob("*cx-green-demo-task.md")
    )
    assert len(bootstrap_files) == 1
    bootstrap = bootstrap_files[0].read_text()
    assert "## Codex-Visible Operator Dossier" in bootstrap
    assert "status: safe_summary" in bootstrap
    assert "SAFE-CODEX-DOSSIER-FIXTURE" in bootstrap
    assert "Update only from durable operator directives" in bootstrap
    assert "Invalidate after contradiction" in bootstrap


def test_task_launch_rejects_unsafe_operator_dossier_context(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    env["HAPAX_CODEX_OPERATOR_DOSSIER"] = str(FIXTURE_ROOT / "operator-dossier-unsafe.md")

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
    bootstrap_files = list(
        (tmp_path / "cache" / "hapax" / "codex-spawns").glob("*cx-green-demo-task.md")
    )
    assert len(bootstrap_files) == 1
    bootstrap = bootstrap_files[0].read_text()
    assert "## Codex-Visible Operator Dossier" in bootstrap
    assert "status: unavailable" in bootstrap
    assert "source failed leak guard" in bootstrap
    assert "do-not-leak-token-value" not in bootstrap
    assert "do-not-leak-private-transcript-content" not in bootstrap
    assert "Operator:" not in bootstrap


def test_idle_cadence_contract_defaults_to_relay_protocol_270() -> None:
    launcher = LAUNCHER.read_text()
    agents = (REPO_ROOT / "AGENTS.md").read_text()

    assert 'HAPAX_IDLE_UPDATE_SECONDS="${HAPAX_IDLE_UPDATE_SECONDS:-270}"' in launcher
    assert 'HAPAX_IDLE_UPDATE_SECONDS="${HAPAX_IDLE_UPDATE_SECONDS:-180}"' not in launcher
    assert "`HAPAX_IDLE_UPDATE_SECONDS` (default 270)" in agents
    assert "`HAPAX_IDLE_UPDATE_SECONDS` (default 180)" not in agents


def test_health_dashboard_uses_lane_level_status_not_nested_notes(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    relay_dir = Path(env["XDG_CACHE_HOME"]) / "hapax" / "relay"
    relay_dir.mkdir(parents=True)
    (relay_dir / "cx-green.yaml").write_text(
        "\n".join(
            [
                "session: cx-green",
                "status: watching_idle_cadence",
                "mode: coordination_glue_only",
                "task_id: null",
                "current_claim: null",
                "worktree:",
                "  branch: codex/cx-green-flow-expeditor",
                "protected_sessions:",
                "  cx-violet:",
                "    note: Protected lane remains visible; observe only.",
                "notes:",
                "  - Green should monitor claims and PRs every cadence.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    fake_tmux = tmp_path / "bin" / "tmux"
    fake_tmux.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "has-session" ] && [ "$3" = "hapax-codex-cx-green" ]; then
  exit 0
fi
exit 1
"""
    )
    fake_tmux.chmod(0o755)

    fake_hyprctl = tmp_path / "bin" / "hyprctl"
    fake_hyprctl.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "clients" ]; then
  printf '%s\n' '[]'
fi
"""
    )
    fake_hyprctl.chmod(0o755)

    dashboard = tmp_path / "dashboard.md"
    result = subprocess.run(
        [
            str(HEALTH),
            "--write-obsidian",
            str(dashboard),
            "cx-green",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    text = dashboard.read_text(encoding="utf-8")
    assert "coordination_glue_only" in text
    assert "codex/cx-green-flow-expeditor" in text
    assert "Protected lane remains visible" not in text


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
    _write_active_task(env, "demo-task")
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


def test_terminal_launch_refuses_non_offered_task_before_opening_foot(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    _write_active_task(env, "demo-task", status="pr_open")
    _write_fake_tmux(tmp_path / "bin", tmp_path / "tmux.log")
    foot_args = tmp_path / "foot-args.txt"
    fake_foot = tmp_path / "bin" / "foot"
    fake_foot.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {foot_args}
"""
    )
    fake_foot.chmod(0o755)

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "cx-blue",
            "--slot",
            "delta",
            "--cd",
            str(REPO_ROOT),
            "--task",
            "demo-task",
            "--terminal",
            "foot",
            "--force",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 4
    assert "current status is 'pr_open', not 'offered'" in result.stderr
    assert not foot_args.exists()
    assert not list((tmp_path / "cache" / "hapax" / "codex-spawns").glob("*cx-blue-demo-task.md"))


def test_terminal_foot_starts_visible_tmux_backed_session(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    foot_args = tmp_path / "foot-args.txt"
    hyprctl_args = tmp_path / "hyprctl-args.txt"
    tmux_log = tmp_path / "tmux.log"
    _write_fake_tmux(tmp_path / "bin", tmux_log)
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
    fake_hyprctl = tmp_path / "bin" / "hyprctl"
    fake_hyprctl.write_text(
        f"""#!/usr/bin/env bash
case "$1" in
  activeworkspace)
    printf '%s\\n' '{{"name":"1"}}'
    ;;
  clients)
    printf '%s\\n' '[{{"class":"hapax-codex-cx-violet","address":"0xabc"}}]'
    ;;
  dispatch)
    printf '%s\\n' "$*" >> {hyprctl_args}
    ;;
esac
"""
    )
    fake_hyprctl.chmod(0o755)

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
    assert "tmux\nattach-session\n-t\nhapax-codex-cx-violet" in args
    tmux_text = tmux_log.read_text()
    assert "has-session -t hapax-codex-cx-violet" in tmux_text
    assert "new-session -d -s hapax-codex-cx-violet" in tmux_text
    assert "dispatch movetoworkspacesilent name:1,address:0xabc" in hyprctl_args.read_text()


def test_protected_live_session_refuses_duplicate_visible_launch(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    protection = Path(env["HOME"]) / ".cache" / "hapax" / "relay" / "session-protection.md"
    protection.parent.mkdir(parents=True, exist_ok=True)
    protection.write_text("- `cx-violet` is protected.\n", encoding="utf-8")

    foot_args = tmp_path / "foot-args.txt"
    _write_fake_tmux(tmp_path / "bin", tmp_path / "tmux.log")
    fake_foot = tmp_path / "bin" / "foot"
    fake_foot.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {foot_args}
"""
    )
    fake_foot.chmod(0o755)

    fake_hyprctl = tmp_path / "bin" / "hyprctl"
    fake_hyprctl.write_text(
        """#!/usr/bin/env bash
case "$1" in
  clients)
    printf '%s\\n' '[{"class":"hapax-codex-cx-violet","address":"0xabc"}]'
    ;;
  activeworkspace)
    printf '%s\\n' '{"name":"1"}'
    ;;
esac
"""
    )
    fake_hyprctl.chmod(0o755)

    bootstrap = tmp_path / "bootstrap.md"
    bootstrap.write_text("# bootstrap\n", encoding="utf-8")

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
            "--force",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 12
    assert "refusing to launch protected live session 'cx-violet'" in result.stderr
    assert not foot_args.exists()


def test_codex_send_foot_targets_window_shortcuts_without_focus(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    env["HAPAX_CODEX_SEND_PASTE_DELAY"] = "0"
    env["HAPAX_CODEX_SEND_SUBMIT_DELAY"] = "0"
    env["HAPAX_CODEX_SEND_RESTORE_DELAY"] = "0"
    env["HAPAX_CODEX_SEND_RETURN_HOLD_MS"] = "0"
    env["HAPAX_CODEX_SEND_AFTER_SUBMIT_DELAY"] = "0"

    hyprctl_log = tmp_path / "hyprctl.log"
    fake_hyprctl = tmp_path / "bin" / "hyprctl"
    fake_hyprctl.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {hyprctl_log}
case "$1" in
  clients)
    printf '%s\\n' '[{{"class":"hapax-codex-cx-blue","address":"0xabc"}}]'
    ;;
  activewindow)
    printf '%s\\n' '{{"address":"0xdef"}}'
    ;;
  dispatch)
    if [ "$2" = "sendshortcut" ]; then
      printf '%s\\n' ok
    fi
    ;;
esac
"""
    )
    fake_hyprctl.chmod(0o755)

    copy_log = tmp_path / "wl-copy.log"
    fake_wl_copy = tmp_path / "bin" / "wl-copy"
    fake_wl_copy.write_text(
        f"""#!/usr/bin/env bash
printf 'ARGS:%s\\n' "$*" >> {copy_log}
cat >> {copy_log}
printf '\\n---\\n' >> {copy_log}
"""
    )
    fake_wl_copy.chmod(0o755)

    fake_wl_paste = tmp_path / "bin" / "wl-paste"
    fake_wl_paste.write_text(
        """#!/usr/bin/env bash
case "$1" in
  --list-types)
    printf '%s\n' 'text/plain'
    ;;
  --no-newline)
    printf '%s' 'OLD CLIP'
    ;;
esac
"""
    )
    fake_wl_paste.chmod(0o755)

    wtype_log = tmp_path / "wtype.log"
    fake_wtype = tmp_path / "bin" / "wtype"
    fake_wtype.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {wtype_log}
"""
    )
    fake_wtype.chmod(0o755)

    result = subprocess.run(
        [
            str(SENDER),
            "--session",
            "cx-blue",
            "--transport",
            "foot",
            "--",
            "Proceed with the current task.",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    hyprctl_text = hyprctl_log.read_text()
    assert "dispatch sendshortcut CTRL,U,address:0xabc" in hyprctl_text
    assert "dispatch sendshortcut CTRL SHIFT,V,address:0xabc" in hyprctl_text
    assert "dispatch sendshortcut ,Return,address:0xabc" in hyprctl_text
    assert "dispatch focuswindow" not in hyprctl_text
    copy_text = copy_log.read_text()
    assert "Proceed with the current task." in copy_text
    assert "OLD CLIP" in copy_text
    assert not wtype_log.exists()


def test_codex_send_foot_falls_back_to_focus_path_when_shortcut_unavailable(
    tmp_path: Path,
) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    env["HAPAX_CODEX_SEND_PASTE_DELAY"] = "0"
    env["HAPAX_CODEX_SEND_SUBMIT_DELAY"] = "0"
    env["HAPAX_CODEX_SEND_RESTORE_DELAY"] = "0"
    env["HAPAX_CODEX_SEND_RETURN_HOLD_MS"] = "0"
    env["HAPAX_CODEX_SEND_AFTER_SUBMIT_DELAY"] = "0"

    hyprctl_log = tmp_path / "hyprctl.log"
    fake_hyprctl = tmp_path / "bin" / "hyprctl"
    fake_hyprctl.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {hyprctl_log}
case "$1" in
  clients)
    printf '%s\\n' '[{{"class":"hapax-codex-cx-blue","address":"0xabc","at":[10,20],"size":[200,100]}}]'
    ;;
  activewindow)
    printf '%s\\n' '{{"address":"0xabc"}}'
    ;;
  dispatch)
    if [ "$2" = "sendshortcut" ]; then
      printf '%s\\n' 'invalid args'
    fi
    ;;
esac
"""
    )
    fake_hyprctl.chmod(0o755)

    fake_wl_copy = tmp_path / "bin" / "wl-copy"
    fake_wl_copy.write_text("#!/usr/bin/env bash\ncat >/dev/null\n")
    fake_wl_copy.chmod(0o755)

    fake_wl_paste = tmp_path / "bin" / "wl-paste"
    fake_wl_paste.write_text(
        """#!/usr/bin/env bash
case "$1" in
  --list-types)
    printf '%s\n' 'text/plain'
    ;;
  --no-newline)
    printf '%s' 'OLD CLIP'
    ;;
esac
"""
    )
    fake_wl_paste.chmod(0o755)

    wtype_log = tmp_path / "wtype.log"
    fake_wtype = tmp_path / "bin" / "wtype"
    fake_wtype.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {wtype_log}
"""
    )
    fake_wtype.chmod(0o755)

    result = subprocess.run(
        [
            str(SENDER),
            "--session",
            "cx-blue",
            "--transport",
            "foot",
            "--",
            "Proceed with the current task.",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    hyprctl_text = hyprctl_log.read_text()
    assert "dispatch sendshortcut CTRL,U,address:0xabc" in hyprctl_text
    assert "dispatch movecursor 110 70" in hyprctl_text
    assert "dispatch focuswindow address:0xabc" in hyprctl_text
    wtype_lines = wtype_log.read_text().splitlines()
    assert "-M ctrl -k u -m ctrl" in wtype_lines
    assert "-M ctrl -M shift -k v -m shift -m ctrl" in wtype_lines
    assert "-P Return -s 0 -p Return" in wtype_lines


def test_codex_send_tmux_pastes_buffer_then_enter(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    env["HAPAX_CODEX_SEND_SUBMIT_DELAY"] = "0"

    tmux_log = tmp_path / "tmux.log"
    tmux_message = tmp_path / "tmux-message.txt"
    fake_tmux = tmp_path / "bin" / "tmux"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {tmux_log}
case "$1" in
  has-session)
    exit 0
    ;;
  load-buffer)
    file="${{@: -1}}"
    cat "$file" > {tmux_message}
    ;;
esac
"""
    )
    fake_tmux.chmod(0o755)

    result = subprocess.run(
        [
            str(SENDER),
            "--session",
            "cx-amber",
            "--transport",
            "tmux",
            "--",
            "Repair the PR and report status.",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert tmux_message.read_text() == "Repair the PR and report status."
    tmux_text = tmux_log.read_text()
    assert "has-session -t hapax-codex-cx-amber" in tmux_text
    assert "send-keys -t hapax-codex-cx-amber C-u" in tmux_text
    assert "paste-buffer -b hapax-codex-send-cx-amber-" in tmux_text
    assert "delete-buffer -b hapax-codex-send-cx-amber-" in tmux_text
    assert "send-keys -t hapax-codex-cx-amber C-m" in tmux_text


def test_codex_send_tmux_default_submit_delay_allows_paste_settle() -> None:
    sender = SENDER.read_text()

    assert "HAPAX_CODEX_SEND_SUBMIT_DELAY:-1.10" in sender
    assert "HAPAX_CODEX_SEND_SUBMIT_DELAY:-0.35" not in sender


def test_codex_send_tmux_waits_for_required_ack(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    env["HAPAX_CODEX_SEND_SUBMIT_DELAY"] = "0"
    env["HAPAX_CODEX_SEND_ACK_TIMEOUT"] = "2"

    ack_file = tmp_path / "ack.txt"
    tmux_log = tmp_path / "tmux.log"
    tmux_message = tmp_path / "tmux-message.txt"
    fake_tmux = tmp_path / "bin" / "tmux"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {tmux_log}
case "$1" in
  has-session)
    exit 0
    ;;
  load-buffer)
    file="${{@: -1}}"
    cat "$file" > {tmux_message}
    ;;
  send-keys)
    if [ "${{@: -1}}" = "C-m" ]; then
      printf '%s\\n' "$HAPAX_CODEX_SEND_ACK_TOKEN" > "$HAPAX_CODEX_SEND_ACK_FILE"
    fi
    ;;
esac
"""
    )
    fake_tmux.chmod(0o755)

    result = subprocess.run(
        [
            str(SENDER),
            "--session",
            "cx-amber",
            "--transport",
            "tmux",
            "--require-ack",
            "--ack-file",
            str(ack_file),
            "--ack-token",
            "token-123",
            "--json",
            "--",
            "Repair the PR and report status.",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert ack_file.read_text().strip() == "token-123"
    assert "ACK REQUIRED" in tmux_message.read_text()
    assert '"ack_required":1' in result.stdout


def test_codex_send_tmux_retries_submit_until_required_ack(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    env["HAPAX_CODEX_SEND_SUBMIT_DELAY"] = "0"
    env["HAPAX_CODEX_SEND_ACK_TIMEOUT"] = "2"
    env["HAPAX_CODEX_SEND_ACK_NUDGE_SECONDS"] = "0"
    env["HAPAX_CODEX_SEND_ACK_NUDGE_LIMIT"] = "1"

    ack_file = tmp_path / "ack.txt"
    c_m_count = tmp_path / "cm-count.txt"
    tmux_log = tmp_path / "tmux.log"
    tmux_message = tmp_path / "tmux-message.txt"
    fake_tmux = tmp_path / "bin" / "tmux"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {tmux_log}
case "$1" in
  has-session)
    exit 0
    ;;
  load-buffer)
    file="${{@: -1}}"
    cat "$file" > {tmux_message}
    ;;
  send-keys)
    if [ "${{@: -1}}" = "C-m" ]; then
      count=0
      if [ -f {c_m_count} ]; then
        count="$(cat {c_m_count})"
      fi
      count=$((count + 1))
      printf '%s\\n' "$count" > {c_m_count}
      if [ "$count" -ge 2 ]; then
        printf '%s\\n' "$HAPAX_CODEX_SEND_ACK_TOKEN" > "$HAPAX_CODEX_SEND_ACK_FILE"
      fi
    fi
    ;;
esac
"""
    )
    fake_tmux.chmod(0o755)

    result = subprocess.run(
        [
            str(SENDER),
            "--session",
            "cx-amber",
            "--transport",
            "tmux",
            "--require-ack",
            "--ack-file",
            str(ack_file),
            "--ack-token",
            "token-123",
            "--json",
            "--",
            "Repair the PR and report status.",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert ack_file.read_text().strip() == "token-123"
    assert c_m_count.read_text().strip() == "2"
    assert tmux_log.read_text().count("send-keys -t hapax-codex-cx-amber C-m") == 2


def test_codex_send_tmux_refuses_ack_gated_message_when_pane_is_busy(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)

    tmux_log = tmp_path / "tmux.log"
    tmux_message = tmp_path / "tmux-message.txt"
    fake_tmux = tmp_path / "bin" / "tmux"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {tmux_log}
case "$1" in
  has-session)
    exit 0
    ;;
  capture-pane)
    printf '%s\\n' 'Working (42s - esc to interrupt)'
    ;;
  load-buffer)
    file="${{@: -1}}"
    cat "$file" > {tmux_message}
    ;;
esac
"""
    )
    fake_tmux.chmod(0o755)

    result = subprocess.run(
        [
            str(SENDER),
            "--session",
            "cx-amber",
            "--transport",
            "tmux",
            "--require-ack",
            "--ack-timeout",
            "1",
            "--",
            "Repair the PR and report status.",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 14
    assert "appears busy" in result.stderr
    assert not tmux_message.exists()


def test_codex_send_requires_tmux_for_ack_by_default(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)

    fake_tmux = tmp_path / "bin" / "tmux"
    fake_tmux.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "has-session" ]; then
  exit 1
fi
exit 0
"""
    )
    fake_tmux.chmod(0o755)

    fake_hyprctl = tmp_path / "bin" / "hyprctl"
    fake_hyprctl.write_text(
        """#!/usr/bin/env bash
case "$1" in
  clients)
    printf '%s\n' '[{"class":"hapax-codex-cx-blue","address":"0xabc"}]'
    ;;
esac
"""
    )
    fake_hyprctl.chmod(0o755)

    result = subprocess.run(
        [
            str(SENDER),
            "--session",
            "cx-blue",
            "--require-ack",
            "--",
            "Proceed with the current task.",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 13
    assert "needs a tmux-backed session" in result.stderr


def test_codex_send_auto_prefers_tmux_over_visible_foot(tmp_path: Path) -> None:
    env, _args_file, _env_file = _env_with_fake_codex(tmp_path)
    env["HAPAX_CODEX_SEND_SUBMIT_DELAY"] = "0"

    tmux_log = tmp_path / "tmux.log"
    tmux_message = tmp_path / "tmux-message.txt"
    fake_tmux = tmp_path / "bin" / "tmux"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {tmux_log}
case "$1" in
  has-session)
    exit 0
    ;;
  load-buffer)
    file="${{@: -1}}"
    cat "$file" > {tmux_message}
    ;;
esac
"""
    )
    fake_tmux.chmod(0o755)

    foot_log = tmp_path / "foot-path.log"
    fake_hyprctl = tmp_path / "bin" / "hyprctl"
    fake_hyprctl.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {foot_log}
case "$1" in
  clients)
    printf '%s\\n' '[{{"class":"hapax-codex-cx-blue","address":"0xabc"}}]'
    ;;
esac
"""
    )
    fake_hyprctl.chmod(0o755)

    result = subprocess.run(
        [
            str(SENDER),
            "--session",
            "cx-blue",
            "--",
            "Use the tmux route when it exists.",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert tmux_message.read_text() == "Use the tmux route when it exists."
    assert not foot_log.exists()
