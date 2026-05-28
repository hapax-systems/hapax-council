"""Tests for hooks/scripts/subagent-git-safety.sh (SubagentStop reflex).

Event-level reminder for the subagent-git-safety failure mode. Always
advisory (exit 0); never blocks.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "subagent-git-safety.sh"


def _run(
    *, env_extra: dict | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"session_id": "x", "hook_event_name": "SubagentStop"}),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


def test_emits_advisory_and_exits_zero(tmp_path: Path) -> None:
    result = _run(cwd=tmp_path)
    assert result.returncode == 0
    assert "subagent-git-safety" in result.stderr
    assert "git push -u origin HEAD" in result.stderr


def test_disabled_via_env(tmp_path: Path) -> None:
    result = _run(env_extra={"HAPAX_SUBAGENT_GIT_SAFETY_OFF": "1"}, cwd=tmp_path)
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_surfaces_unpushed_work(tmp_path: Path) -> None:
    repo = tmp_path / "wt"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "x.txt").write_text("hi\n")
    result = _run(cwd=repo)
    assert result.returncode == 0
    assert "uncommitted change" in result.stderr


def test_hook_uses_strict_bash() -> None:
    body = HOOK.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in body
