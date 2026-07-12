"""Supervisor diagnostics cannot escalate through a task-writing side channel."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"


def test_missing_worktree_is_repeatable_projection_without_stateful_escalation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    active = home / "vault" / "active"
    active.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tmux = bin_dir / "tmux"
    tmux.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    tmux.chmod(0o755)
    effect_log = tmp_path / "effects.log"
    for name in ("hapax-alert", "hapax-p0-incident-intake", "notify-send", "curl"):
        command = bin_dir / name
        command.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' '{name}' >> '{effect_log}'\n",
            encoding="utf-8",
        )
        command.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_SUPERVISOR_RUNTIME_DIR": str(tmp_path / "runtime"),
            "HAPAX_SUPERVISOR_WORKTREE_ROOT": str(home / "projects"),
            "HAPAX_SUPERVISOR_VAULT_ROOT": str(home / "vault"),
            "HAPAX_SUPERVISOR_CLAIM_CACHE_DIR": str(home / ".cache" / "hapax"),
            "HAPAX_SUPERVISOR_METRICS_FILE": "",
            "HAPAX_SUPERVISOR_CLAUDE_LANES": "delta",
            "HAPAX_SUPERVISOR_CODEX_LANES": "",
            "HAPAX_SUPERVISOR_ANTIGRAV_LANES": "",
            "HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS": "0",
            "HAPAX_SUPERVISOR_ESCALATE_MISSING_WORKTREE_CYCLES": "1",
        }
    )

    first = subprocess.run([str(SUPERVISOR)], env=env, capture_output=True, text=True)
    second = subprocess.run([str(SUPERVISOR)], env=env, capture_output=True, text=True)

    assert first.returncode == second.returncode == 0
    assert "CONFIGURATION_CANDIDATE" in first.stdout
    assert "CONFIGURATION_CANDIDATE" in second.stdout
    assert not effect_log.exists()


def test_supervisor_has_no_task_writing_alert_route() -> None:
    text = SUPERVISOR.read_text(encoding="utf-8")
    assert "hapax-alert" not in text
    assert "hapax-p0-incident-intake" not in text
    assert "notify-send" not in text
    assert "Priority: high" not in text
