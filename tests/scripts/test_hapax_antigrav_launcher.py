"""Tests for the retired Hapax Antigrav/agy launcher stub."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "hapax-antigrav"


def test_antigrav_launcher_refuses_without_side_effects(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = tmp_path / "projects" / "hapax-council--antigrav"
    home.mkdir()
    workdir.mkdir(parents=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
        "HAPAX_ANTIGRAV_BIN": str(tmp_path / "agy"),
    }

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "antigrav",
            "--task",
            "test-task",
            "--cd",
            str(workdir),
            "--wire-hooks-only",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "retired" in result.stderr
    assert "reason_code=antigrav_worker_stub_refusal" in result.stderr
    assert not (home / ".gemini" / "antigravity-cli" / "hooks.json").exists()
    assert not (workdir / ".agents").exists()
