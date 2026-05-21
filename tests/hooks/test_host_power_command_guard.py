"""Tests for hooks/scripts/host-power-command-guard.sh."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "host-power-command-guard.sh"


def _run(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestBlocksPowerCommands:
    def test_blocks_incident_command(self) -> None:
        result = _run(_bash("sudo systemctl poweroff"))
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr
        assert "systemctl poweroff" in result.stderr

    def test_blocks_absolute_systemctl_reboot(self) -> None:
        result = _run(_bash("sudo /usr/bin/systemctl reboot"))
        assert result.returncode == 2

    def test_blocks_systemctl_shutdown(self) -> None:
        result = _run(_bash("sudo /usr/bin/systemctl shutdown"))
        assert result.returncode == 2
        assert "systemctl shutdown" in result.stderr

    def test_blocks_direct_poweroff(self) -> None:
        result = _run(_bash("poweroff"))
        assert result.returncode == 2

    def test_blocks_shutdown(self) -> None:
        result = _run(_bash("/usr/sbin/shutdown -h now"))
        assert result.returncode == 2

    def test_blocks_chained_command(self) -> None:
        result = _run(_bash("cd /home/hapax/projects && sudo systemctl poweroff"))
        assert result.returncode == 2

    def test_blocks_nested_shell_c(self) -> None:
        result = _run(_bash("bash -c 'sudo systemctl reboot'"))
        assert result.returncode == 2

    def test_blocks_env_wrapped_command(self) -> None:
        result = _run(_bash("env FOO=1 sudo -n systemctl halt"))
        assert result.returncode == 2

    def test_blocks_malformed_command_with_power_token(self) -> None:
        result = _run(_bash("bash -c 'sudo systemctl poweroff"))
        assert result.returncode == 2
        assert "unparseable command containing host power token" in result.stderr


class TestAllowsNonPowerCommands:
    def test_allows_systemctl_status(self) -> None:
        result = _run(_bash("systemctl --user status hapax-daimonion.service"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_allows_systemctl_restart(self) -> None:
        result = _run(_bash("systemctl --user restart studio-compositor.service"))
        assert result.returncode == 0

    def test_allows_daemon_reload(self) -> None:
        result = _run(_bash("systemctl --user daemon-reload"))
        assert result.returncode == 0

    def test_allows_echoed_warning(self) -> None:
        result = _run(_bash('echo "do not run sudo systemctl poweroff"'))
        assert result.returncode == 0

    def test_allows_pr_body_heredoc_mention(self) -> None:
        command = (
            "gh pr create --title 'docs' --body \"$(cat <<'EOF'\n"
            "Do not run sudo systemctl poweroff from agent sessions.\n"
            "EOF\n"
            ')"'
        )
        result = _run(_bash(command))
        assert result.returncode == 0

    def test_allows_malformed_non_power_command(self) -> None:
        result = _run(_bash("python -c 'unterminated"))
        assert result.returncode == 0


class TestPassthrough:
    def test_passes_non_bash_tools(self) -> None:
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}})
        assert result.returncode == 0

    def test_passes_empty_command(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {}})
        assert result.returncode == 0

    def test_hook_is_executable(self) -> None:
        assert os.access(HOOK, os.X_OK)
