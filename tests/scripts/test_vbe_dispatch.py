"""Integration tests for the VBE launcher and dispatch helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "hapax-vibe"
SENDER = REPO_ROOT / "scripts" / "hapax-vibe-send"
HEALTH = REPO_ROOT / "scripts" / "hapax-vibe-health"
STANDUP = REPO_ROOT / "scripts" / "standup-vibe-team"


def _base_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    home = tmp_path / "home"
    projects = tmp_path / "projects"
    relay = tmp_path / "relay"
    spawns = tmp_path / "spawns"
    for path in (home, projects, relay, spawns):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(home)
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_VIBE_WORKTREE_ROOT"] = str(projects)
    env["HAPAX_VIBE_RELAY_DIR"] = str(relay)
    env["HAPAX_VIBE_SPAWN_DIR"] = str(spawns)
    env["MISTRAL_API_KEY"] = "test-key"
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("HAPAX_AGENT_INTERFACE", None)
    env.pop("CLAUDE_ROLE", None)
    return env, bin_dir, spawns


def _write_fake_vibe(bin_dir: Path, log_path: Path) -> Path:
    fake_vibe = bin_dir / "vibe"
    fake_vibe.write_text(
        f"""#!/usr/bin/env bash
if [ "${{1:-}}" = "--version" ]; then
  printf '%s\\n' 'vibe 0.0-test'
  exit 0
fi
printf '%s\\n' "$*" > {log_path}
printf 'HAPAX_AGENT_NAME=%s\\n' "$HAPAX_AGENT_NAME" >> {log_path}
printf 'HAPAX_AGENT_ROLE=%s\\n' "$HAPAX_AGENT_ROLE" >> {log_path}
"""
    )
    fake_vibe.chmod(0o755)
    return fake_vibe


def _write_fake_claim(bin_dir: Path, log_path: Path) -> Path:
    fake_claim = bin_dir / "cc-claim"
    fake_claim.write_text(
        f"""#!/usr/bin/env bash
printf '%s %s %s %s\\n' "$HAPAX_AGENT_NAME" "$HAPAX_AGENT_ROLE" "$CLAUDE_ROLE" "$*" > {log_path}
mkdir -p "$HOME/.cache/hapax"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-$HAPAX_AGENT_NAME"
"""
    )
    fake_claim.chmod(0o755)
    return fake_claim


def _write_fake_tmux(bin_dir: Path, tmp_path: Path) -> tuple[Path, Path, Path]:
    log_path = tmp_path / "tmux.log"
    sessions_dir = tmp_path / "tmux-sessions"
    panes_dir = tmp_path / "tmux-panes"
    sessions_dir.mkdir()
    panes_dir.mkdir()
    fake_tmux = bin_dir / "tmux"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> {log_path}
cmd="${{1:-}}"
shift || true
target=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-t" ] || [ "$prev" = "-s" ]; then
    target="$arg"
  fi
  prev="$arg"
done
case "$cmd" in
  has-session)
    [ -n "$target" ] && [ -f "{sessions_dir}/$target" ]
    ;;
  new-session)
    [ -n "$target" ] || exit 2
    touch "{sessions_dir}/$target"
    ;;
  kill-session)
    rm -f "{sessions_dir}/$target"
    ;;
  capture-pane)
    [ -n "$target" ] || exit 2
    [ -f "{panes_dir}/$target" ] || exit 1
    cat "{panes_dir}/$target"
    ;;
  set-buffer|paste-buffer|send-keys)
    ;;
esac
"""
    )
    fake_tmux.chmod(0o755)
    return log_path, sessions_dir, panes_dir


def test_tmux_launch_claims_task_and_writes_spawn_record(tmp_path: Path) -> None:
    env, bin_dir, spawns = _base_env(tmp_path)
    fake_vibe = _write_fake_vibe(bin_dir, tmp_path / "vibe.log")
    claim_log = tmp_path / "claim.log"
    _write_fake_claim(bin_dir, claim_log)
    tmux_log, sessions_dir, _panes_dir = _write_fake_tmux(bin_dir, tmp_path)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "vbe-1",
            "--task",
            "demo-task",
            "--cd",
            str(workdir),
            "--terminal",
            "tmux",
            "--prompt",
            "Audit queue",
            "--max-turns",
            "7",
            "--output",
            "streaming",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "hapax-vibe-vbe-1"
    assert (sessions_dir / "hapax-vibe-vbe-1").exists()
    assert claim_log.read_text(encoding="utf-8").strip() == "vbe-1 vbe-1 vbe-1 demo-task"

    tmux_text = tmux_log.read_text(encoding="utf-8")
    assert "new-session -d -s hapax-vibe-vbe-1" in tmux_text
    assert f"-c {workdir}" in tmux_text

    spawn_records = list(spawns.glob("*vbe-1-demo-task.yaml"))
    assert len(spawn_records) == 1
    spawn_text = spawn_records[0].read_text(encoding="utf-8")
    assert "session: vbe-1" in spawn_text
    assert "task: demo-task" in spawn_text
    assert "terminal: tmux" in spawn_text
    assert "headless: true" in spawn_text
    assert f"workdir: {workdir}" in spawn_text

    runner = next(spawns.glob("run-*vbe-1-demo-task.sh"))
    runner_text = runner.read_text(encoding="utf-8")
    assert f"exec {fake_vibe}" in runner_text
    assert "Audit\\ queue" in runner_text
    assert "--max-turns 7" in runner_text
    assert "--output streaming" in runner_text
    assert "export HAPAX_AGENT_ROLE=vbe-1" in runner_text
    assert "Hapax Vibe Lane - vbe-1" in (workdir / "AGENTS.md").read_text(encoding="utf-8")


def test_sender_routes_message_to_tmux_session(tmp_path: Path) -> None:
    env, bin_dir, _spawns = _base_env(tmp_path)
    tmux_log, sessions_dir, _panes_dir = _write_fake_tmux(bin_dir, tmp_path)
    (sessions_dir / "hapax-vibe-vbe-1").touch()

    result = subprocess.run(
        [str(SENDER), "--session", "vbe-1", "--", "Run dispatch validation"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "sent + submitted to hapax-vibe-vbe-1"
    tmux_text = tmux_log.read_text(encoding="utf-8")
    assert "has-session -t hapax-vibe-vbe-1" in tmux_text
    assert "set-buffer -- Run dispatch validation" in tmux_text
    assert "paste-buffer -t hapax-vibe-vbe-1" in tmux_text
    assert "send-keys -t hapax-vibe-vbe-1 Enter" in tmux_text


def test_standup_generates_relay_yaml_for_vbe_lanes(tmp_path: Path) -> None:
    env, bin_dir, _spawns = _base_env(tmp_path)
    _write_fake_vibe(bin_dir, tmp_path / "vibe.log")
    env["HAPAX_VIBE_CREATE_WORKTREE"] = "0"
    env["HAPAX_STANDUP_FORCE_STATUS"] = "1"
    env["HAPAX_VIBE_LAUNCHER"] = str(LAUNCHER)

    result = subprocess.run(
        [str(STANDUP)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    relay_dir = Path(env["HAPAX_VIBE_RELAY_DIR"])
    for lane in ("vbe-1", "vbe-2"):
        status = relay_dir / f"{lane}.yaml"
        assert status.exists()
        text = status.read_text(encoding="utf-8")
        assert f"session: {lane}" in text
        assert "session_status: |" in text
        assert "STANDBY - lane is provisioned but no task claimed" in text
        assert "interface: vibe" in text
        assert "tier: jr-plus" in text
        worktree = Path(env["HAPAX_VIBE_WORKTREE_ROOT"]) / f"hapax-council--{lane}"
        assert (worktree / "AGENTS.md").exists()


def test_health_detects_tmux_pane_content(tmp_path: Path) -> None:
    env, bin_dir, _spawns = _base_env(tmp_path)
    _write_fake_vibe(bin_dir, tmp_path / "vibe.log")
    tmux_log, sessions_dir, panes_dir = _write_fake_tmux(bin_dir, tmp_path)
    (sessions_dir / "hapax-vibe-vbe-1").touch()
    (panes_dir / "hapax-vibe-vbe-1").write_text(
        "Mistral Vibe ready\nAwaiting operator command\n",
        encoding="utf-8",
    )
    worktree = Path(env["HAPAX_VIBE_WORKTREE_ROOT"]) / "hapax-council--vbe-1"
    worktree.mkdir(parents=True)
    relay_dir = Path(env["HAPAX_VIBE_RELAY_DIR"])
    (relay_dir / "vbe-1.yaml").write_text(
        "\n".join(
            [
                "session: vbe-1",
                "updated: '2026-05-11T00:00:00Z'",
                "session_status: LIVE",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(HEALTH), "vbe-1"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "vbe-1" in result.stdout
    assert "LIVE" in result.stdout
    assert "Awaiting operator command" in result.stdout
    assert "capture-pane -t hapax-vibe-vbe-1 -p -S -40" in tmux_log.read_text(encoding="utf-8")
