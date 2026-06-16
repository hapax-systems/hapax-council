from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _supervisor_fixture(tmp_path: Path, *, intake_exit: int) -> tuple[Path, dict[str, str], Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (repo / "shared").mkdir()
    supervisor = scripts / "hapax-lane-supervisor"
    supervisor.write_text(SUPERVISOR.read_text(encoding="utf-8"), encoding="utf-8")
    supervisor.chmod(0o755)

    calls = tmp_path / "calls"
    calls.mkdir()
    _write_executable(
        scripts / "hapax-p0-incident-intake",
        f"""
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> "{calls / "intake.txt"}"
        exit {intake_exit}
        """,
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "curl",
        f"""
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> "{calls / "curl.txt"}"
        exit 0
        """,
    )
    _write_executable(
        fake_bin / "notify-send",
        f"""
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> "{calls / "notify-send.txt"}"
        exit 0
        """,
    )

    home = tmp_path / "home"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "HAPAX_SUPERVISOR_STATE_DIR": str(tmp_path / "state"),
            "HAPAX_SUPERVISOR_RUNTIME_DIR": str(tmp_path / "runtime"),
            "HAPAX_SUPERVISOR_WORKTREE_ROOT": str(home / "projects"),
            "HAPAX_SUPERVISOR_VAULT_ROOT": str(home / "vault"),
            "HAPAX_SUPERVISOR_CLAUDE_LANES": "",
            "HAPAX_SUPERVISOR_CODEX_LANES": "cx-missing",
            "HAPAX_SUPERVISOR_ANTIGRAV_LANES": "",
            "HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS": "0",
            "HAPAX_SUPERVISOR_ESCALATE_MISSING_WORKTREE_CYCLES": "1",
            "HAPAX_SUPERVISOR_ESCALATE_REFIRE_S": "0",
            "HAPAX_SUPERVISOR_NTFY_TOPIC": "hapax-test",
        }
    )
    return supervisor, env, calls


def test_lane_supervisor_escalation_executes_p0_intake_before_raw_desktop(tmp_path):
    supervisor, env, calls = _supervisor_fixture(tmp_path, intake_exit=0)

    result = subprocess.run([str(supervisor)], env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    intake = (calls / "intake.txt").read_text(encoding="utf-8")
    assert "notification" in intake
    assert "--technical" in intake
    assert "--priority urgent" in intake
    assert "Hapax lane-supervisor: cx-missing has no worktree" in intake
    assert not (calls / "notify-send.txt").exists()


def test_lane_supervisor_intake_failure_logs_next_action_and_raw_fallback(tmp_path):
    supervisor, env, calls = _supervisor_fixture(tmp_path, intake_exit=7)

    result = subprocess.run([str(supervisor)], env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    assert "notify: p0 incident intake failed; next action:" in result.stdout
    assert "~/.cache/hapax/p0-incident-intake/state.json" in result.stdout
    notify = (calls / "notify-send.txt").read_text(encoding="utf-8")
    assert "-u" in notify
    assert "critical" in notify
    assert "Hapax lane-supervisor: cx-missing has no worktree" in notify
