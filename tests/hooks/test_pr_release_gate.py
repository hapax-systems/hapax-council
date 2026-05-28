"""Tests for hooks/scripts/pr-release-gate.sh (conditional release gate).

Covers the fast, hermetic paths: command detection, env bypass, and the
fail-open advisory when no claimed task resolves. The blocked-on-evidence
verdict itself is exercised by tests/test_avsdlc_release_precheck.py (the
precheck the hook delegates to); this file avoids a cold `uv run` so the
focused suite stays fast and non-flaky.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "pr-release-gate.sh"


def _run(payload: dict, *, env_extra: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in ("HAPAX_AGENT_ROLE", "CODEX_ROLE", "CLAUDE_ROLE"):
        env.pop(key, None)
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


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def test_non_pr_command_passes() -> None:
    result = _run(_bash("ls -la"))
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_unrelated_gh_command_passes() -> None:
    result = _run(_bash("gh pr list --state open"))
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_bypass_env_skips() -> None:
    result = _run(_bash("gh pr merge 123"), env_extra={"HAPAX_PR_RELEASE_GATE_OFF": "1"})
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_create_without_claim_is_advisory(tmp_path: Path) -> None:
    # No claim file under the fake HOME → advisory, never blocks create.
    result = _run(
        _bash("gh pr create --fill"),
        env_extra={"HOME": str(tmp_path), "CLAUDE_ROLE": "gamma"},
    )
    assert result.returncode == 0
    assert "ADVISORY" in result.stderr


def test_merge_without_claim_is_advisory(tmp_path: Path) -> None:
    result = _run(
        _bash("gh pr merge 123"),
        env_extra={"HOME": str(tmp_path), "CLAUDE_ROLE": "gamma"},
    )
    assert result.returncode == 0
    assert "ADVISORY" in result.stderr


def test_hook_uses_strict_bash() -> None:
    body = HOOK.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in body
