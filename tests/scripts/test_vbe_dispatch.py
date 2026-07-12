"""Integration tests for the VBE launcher and dispatch helpers."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from tests.scripts.launcher_activation_fixture import install_launcher_activation

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
    env["HAPAX_VIBE_RELAY_POLL_SECONDS"] = "0"
    env["MISTRAL_API_KEY"] = "test-key"
    env.update(install_launcher_activation(home))
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("HAPAX_AGENT_INTERFACE", None)
    env.pop("CLAUDE_ROLE", None)
    for name in tuple(env):
        if name.startswith("HAPAX_CLAIM_DISPATCH_"):
            env.pop(name)
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


def _write_fake_claim(script_dir: Path, log_path: Path) -> Path:
    script_dir.mkdir(parents=True, exist_ok=True)
    fake_claim = script_dir / "cc-claim"
    fake_claim.write_text(
        f"""#!/usr/bin/env bash
case "${{1:-}}" in
  --dispatch-protocol-version)
    printf '%s\\n' 'hapax-claim-dispatch-v1'
    exit 0
    ;;
  --verify-dispatch-binding)
    printf 'verify %s\\n' "${{2:-}}" >> {log_path}
    exit "${{HAPAX_FAKE_CC_CLAIM_VERIFY_RC:-0}}"
    ;;
esac
printf '%s %s %s %s\\n' "$HAPAX_AGENT_NAME" "$HAPAX_AGENT_ROLE" "$CLAUDE_ROLE" "$*" > {log_path}
mkdir -p "$HOME/.cache/hapax"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-$HAPAX_AGENT_NAME"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-$HAPAX_AGENT_NAME-$HAPAX_SESSION_ID"
printf '{{}}\\n' > "$HOME/.cache/hapax/cc-claim-dispatch-$HAPAX_AGENT_NAME.json"
printf '{{}}\\n' > "$HOME/.cache/hapax/cc-claim-dispatch-$HAPAX_AGENT_NAME-$HAPAX_SESSION_ID.json"
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
    tmux_log, sessions_dir, _panes_dir = _write_fake_tmux(bin_dir, tmp_path)
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    _write_fake_claim(workdir / "scripts", claim_log)
    env["HAPAX_TEST_LAUNCHER_WORKDIR"] = str(workdir)
    env["HAPAX_SESSION_ID"] = "parent-vibe-session"
    path_claim_used = tmp_path / "path-claim-used"
    (bin_dir / "cc-claim").write_text(
        f"#!/usr/bin/env bash\ntouch {path_claim_used}\nexit 99\n",
        encoding="utf-8",
    )
    (bin_dir / "cc-claim").chmod(0o755)
    env["HAPAX_CLAIM_DISPATCH_MESSAGE_ID"] = "dispatch-message"

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
    assert claim_log.read_text(encoding="utf-8").splitlines() == [
        "vbe-1 vbe-1 vbe-1 demo-task",
        "verify demo-task",
    ]
    assert not path_claim_used.exists()
    session_claims = sorted((Path(env["HOME"]) / ".cache" / "hapax").glob("cc-active-task-vbe-1-*"))
    assert len(session_claims) == 1
    assert session_claims[0].name != "cc-active-task-vbe-1-parent-vibe-session"

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
    assert "export HAPAX_CLAIM_DISPATCH_MESSAGE_ID=dispatch-message" in runner_text
    assert "Hapax Vibe Lane - vbe-1" in (workdir / "AGENTS.md").read_text(encoding="utf-8")


def test_vibe_legacy_only_claim_requires_new_session_admission_and_binding(
    tmp_path: Path,
) -> None:
    env, bin_dir, spawns = _base_env(tmp_path)
    vibe_log = tmp_path / "vibe.log"
    _write_fake_vibe(bin_dir, vibe_log)
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    claim_log = tmp_path / "claim.log"
    _write_fake_claim(workdir / "scripts", claim_log)
    env["HAPAX_TEST_LAUNCHER_WORKDIR"] = str(workdir)
    cache = Path(env["HOME"]) / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "cc-active-task-vbe-1").write_text("demo-task\n", encoding="utf-8")
    env["HAPAX_CLAIM_DISPATCH_MESSAGE_ID"] = "dispatch-message"
    env["HAPAX_FAKE_CC_CLAIM_VERIFY_RC"] = "23"

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
            "none",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 18
    assert "exact dispatch binding verification failed" in result.stderr
    assert claim_log.read_text(encoding="utf-8").splitlines() == [
        "vbe-1 vbe-1 vbe-1 demo-task",
        "verify demo-task",
    ]
    assert not vibe_log.exists()
    assert not (workdir / "AGENTS.md").exists()
    assert list(spawns.iterdir()) == []


def test_vibe_new_claim_is_verified_before_worker_launch(tmp_path: Path) -> None:
    env, bin_dir, _spawns = _base_env(tmp_path)
    vibe_log = tmp_path / "vibe.log"
    _write_fake_vibe(bin_dir, vibe_log)
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    claim_log = tmp_path / "claim.log"
    _write_fake_claim(workdir / "scripts", claim_log)
    env["HAPAX_TEST_LAUNCHER_WORKDIR"] = str(workdir)
    env["HAPAX_CLAIM_DISPATCH_MESSAGE_ID"] = "dispatch-message"

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
            "none",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert claim_log.read_text(encoding="utf-8").splitlines() == [
        "vbe-1 vbe-1 vbe-1 demo-task",
        "verify demo-task",
    ]
    assert vibe_log.exists()


def test_vibe_never_replaces_existing_tmux_session(tmp_path: Path) -> None:
    env, bin_dir, _spawns = _base_env(tmp_path)
    vibe_log = tmp_path / "vibe.log"
    _write_fake_vibe(bin_dir, vibe_log)
    tmux_log, sessions_dir, _panes_dir = _write_fake_tmux(bin_dir, tmp_path)
    existing = sessions_dir / "hapax-vibe-vbe-1"
    existing.touch()
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    forced = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "vbe-1",
            "--cd",
            str(workdir),
            "--terminal",
            "tmux",
            "--force",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    refused = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "vbe-1",
            "--cd",
            str(workdir),
            "--terminal",
            "tmux",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert forced.returncode == 2
    assert "--force replacement is not supported" in forced.stderr
    assert refused.returncode == 11
    assert "stop it explicitly before dispatch" in refused.stderr
    assert existing.exists()
    assert "kill-session" not in tmux_log.read_text(encoding="utf-8")
    assert not vibe_log.exists()


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


def test_tmux_launch_polls_relay_inflections_into_headless_prompt(tmp_path: Path) -> None:
    env, bin_dir, spawns = _base_env(tmp_path)
    env["HAPAX_VIBE_RELAY_POLL_SECONDS"] = "2"
    _write_fake_vibe(bin_dir, tmp_path / "vibe.log")
    _write_fake_tmux(bin_dir, tmp_path)
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    inflections = Path(env["HAPAX_VIBE_RELAY_DIR"]) / "inflections"
    inflections.mkdir(parents=True)
    relay_file = inflections / "20260619T000000Z-cx-agy-to-vbe-1.md"

    timer = threading.Timer(
        0.2,
        lambda: relay_file.write_text("Check prior relay state before launch.\n", encoding="utf-8"),
    )
    timer.start()
    try:
        result = subprocess.run(
            [
                str(LAUNCHER),
                "--session",
                "vbe-1",
                "--cd",
                str(workdir),
                "--terminal",
                "tmux",
                "--prompt",
                "Audit queue",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
    finally:
        timer.join(timeout=1)

    assert result.returncode == 0, result.stderr
    runner = next(spawns.glob("run-*vbe-1-no-task.sh"))
    runner_text = runner.read_text(encoding="utf-8")
    assert "Relay Received" in runner_text
    assert "20260619T000000Z-cx-agy-to-vbe-1.md" in runner_text
    assert "Check prior relay state before launch." in runner_text
    assert not relay_file.exists()
    assert (inflections / "processed" / relay_file.name).exists()


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
