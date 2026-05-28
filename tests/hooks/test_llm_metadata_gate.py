"""Tests for hooks/scripts/llm-metadata-gate.sh.

PostToolUse advisory (HANDOFF-llm-enforcement Task 3): when a new
*/agents/<name>/__init__.py is written without a sibling METADATA.yaml,
emit a non-blocking advisory naming the generator command. Always exits 0
(PostToolUse cannot undo the write). Replaces the historical no-op.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "llm-metadata-gate.sh"


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


def _write(file_path: str) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": "x = 1\n"}}


def test_advises_when_metadata_missing(tmp_path: Path) -> None:
    init = tmp_path / "agents" / "widget" / "__init__.py"
    init.parent.mkdir(parents=True)
    init.write_text("x = 1\n")
    result = _run(_write(str(init)))
    assert result.returncode == 0
    assert "METADATA.yaml" in result.stderr
    assert "llm_metadata_gen.py agents.widget" in result.stderr


def test_silent_when_metadata_present(tmp_path: Path) -> None:
    pkg = tmp_path / "agents" / "widget"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("x = 1\n")
    (pkg / "METADATA.yaml").write_text("name: widget\n")
    result = _run(_write(str(pkg / "__init__.py")))
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_ignores_non_agent_path(tmp_path: Path) -> None:
    f = tmp_path / "shared" / "util.py"
    f.parent.mkdir(parents=True)
    f.write_text("x = 1\n")
    result = _run(_write(str(f)))
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_ignores_non_write_tool(tmp_path: Path) -> None:
    init = tmp_path / "agents" / "widget" / "__init__.py"
    result = _run({"tool_name": "Edit", "tool_input": {"file_path": str(init)}})
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_disabled_via_env() -> None:
    result = _run(
        _write("/x/agents/widget/__init__.py"),
        env_extra={"HAPAX_LLM_METADATA_GATE_OFF": "1"},
    )
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_hook_uses_strict_bash() -> None:
    body = HOOK.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in body
