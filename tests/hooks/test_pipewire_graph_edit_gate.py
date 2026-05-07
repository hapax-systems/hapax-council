"""Tests for the P3 PipeWire graph edit gate."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agents.pipewire_graph.lock import acquire_session_lock

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "pipewire-graph-edit-gate.sh"
NOW = datetime(2999, 5, 7, 3, 20, tzinfo=UTC)


def _run_hook(
    tmp_path: Path,
    *,
    file_path: str,
    owner: str = "cx-cyan",
    bypass: bool = False,
) -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": "Edit", "tool_input": {"file_path": file_path}}
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["HAPAX_PIPEWIRE_GRAPH_LOCK_ROOT"] = str(tmp_path / "lock")
    env["CODEX_ROLE"] = owner
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("CODEX_THREAD_NAME", None)
    env.pop("CLAUDE_ROLE", None)
    if bypass:
        env["HAPAX_PIPEWIRE_GRAPH_BYPASS"] = "1"
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


def test_unrelated_edit_allows_without_lock(tmp_path: Path) -> None:
    result = _run_hook(tmp_path, file_path="agents/example.py")

    assert result.returncode == 0


def test_repo_pipewire_conf_edit_blocks_without_lock(tmp_path: Path) -> None:
    result = _run_hook(tmp_path, file_path="config/pipewire/hapax-livestream-tap.conf")

    assert result.returncode == 2
    assert "requires applier lock" in result.stderr
    assert "hapax-pipewire-graph lock" in result.stderr


def test_repo_pipewire_conf_edit_allows_matching_owner_lock(tmp_path: Path) -> None:
    acquire_session_lock(owner="cx-cyan", ttl_s=300, lock_root=tmp_path / "lock", now_utc=NOW)

    result = _run_hook(tmp_path, file_path="config/pipewire/hapax-livestream-tap.conf")

    assert result.returncode == 0, result.stderr


def test_repo_pipewire_conf_edit_blocks_other_owner_lock(tmp_path: Path) -> None:
    acquire_session_lock(owner="cx-blue", ttl_s=300, lock_root=tmp_path / "lock", now_utc=NOW)

    result = _run_hook(tmp_path, file_path="config/pipewire/hapax-livestream-tap.conf")

    assert result.returncode == 2
    assert "held by 'cx-blue'" in result.stderr


def test_home_wireplumber_conf_edit_blocks_without_lock(tmp_path: Path) -> None:
    target = str(tmp_path / ".config" / "wireplumber" / "wireplumber.conf.d" / "rule.conf")

    result = _run_hook(tmp_path, file_path=target)

    assert result.returncode == 2
    assert "requires applier lock" in result.stderr


def test_bypass_allows_audio_graph_edit(tmp_path: Path) -> None:
    result = _run_hook(
        tmp_path,
        file_path="config/wireplumber/50-hapax-voice-duck.conf",
        bypass=True,
    )

    assert result.returncode == 0
    assert "BYPASS active" in result.stderr
