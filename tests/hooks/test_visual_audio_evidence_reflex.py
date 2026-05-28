"""Tests for hooks/scripts/visual-audio-evidence-reflex.sh.

PostToolUse advisory naming the screenshot / routing-check evidence command
when a visual or audio surface is edited. Always exit 0 (advisory).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "visual-audio-evidence-reflex.sh"


def _run(payload: dict, *, env_extra: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _edit(file_path: str, tool: str = "Edit") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": file_path, "new_string": "x"}}


def test_visual_surface_tsx_advises_screenshot() -> None:
    result = _run(_edit("/repo/hapax-logos/src/App.tsx"))
    assert result.returncode == 0
    assert "visual surface" in result.stderr
    assert "compositor-frame-capture.sh" in result.stderr


def test_visual_surface_shader_advises_screenshot() -> None:
    result = _run(_edit("/repo/agents/shaders/nodes/sat_breath.wgsl"))
    assert result.returncode == 0
    assert "visual surface" in result.stderr


def test_audio_surface_advises_routing_check() -> None:
    result = _run(_edit("/repo/config/pipewire/voice-fx-warm.conf"))
    assert result.returncode == 0
    assert "audio surface" in result.stderr
    assert "hapax-audio-routing-check" in result.stderr


def test_non_surface_file_is_silent() -> None:
    result = _run(_edit("/repo/shared/util.py"))
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_non_edit_tool_passes() -> None:
    result = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_disabled_via_env() -> None:
    result = _run(_edit("/repo/x.tsx"), env_extra={"HAPAX_VISUAL_AUDIO_EVIDENCE_OFF": "1"})
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_hook_uses_strict_bash() -> None:
    body = HOOK.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in body
