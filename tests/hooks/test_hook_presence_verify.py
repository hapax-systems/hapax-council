"""Tests for hooks/scripts/hook-presence-verify.sh (SessionStart verifier).

Verifies that registered hook command paths exist + are executable. Always
advisory (exit 0); warns loudly when a registered hook is missing.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "hook-presence-verify.sh"


def _settings(tmp_path: Path, commands: list[str]) -> Path:
    payload = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": c} for c in commands]}
            ]
        }
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload))
    return path


def _run(settings_path: Path, *, env_extra: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HAPAX_SETTINGS_FILE"] = str(settings_path)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"hook_event_name": "SessionStart"}),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_silent_when_all_present(tmp_path: Path) -> None:
    # Reference an existing, executable hook script (stable +x in the repo).
    existing = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"
    result = _run(_settings(tmp_path, [str(existing)]))
    assert result.returncode == 0
    assert "WARNING" not in result.stderr


def test_warns_when_missing(tmp_path: Path) -> None:
    missing = str(tmp_path / "nonexistent-hook.sh")
    result = _run(_settings(tmp_path, [missing]))
    assert result.returncode == 0
    assert "WARNING" in result.stderr
    assert "nonexistent-hook.sh" in result.stderr


def test_skips_relative_and_inline_commands(tmp_path: Path) -> None:
    # Non-absolute commands aren't script paths — must not warn.
    result = _run(_settings(tmp_path, ["echo hi", "relative/path.sh"]))
    assert result.returncode == 0
    assert "WARNING" not in result.stderr


def test_disabled_via_env(tmp_path: Path) -> None:
    result = _run(
        _settings(tmp_path, [str(tmp_path / "missing.sh")]),
        env_extra={"HAPAX_HOOK_PRESENCE_VERIFY_OFF": "1"},
    )
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_hook_uses_strict_bash() -> None:
    body = HOOK.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in body
