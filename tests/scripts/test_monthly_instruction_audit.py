"""The real monthly audit must scan the canonical Git blob, not a link blob."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_monthly_audit_reads_canonical_main_content(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    council = workspace / "hapax-council"
    council.mkdir(parents=True)
    for repo in (council, workspace / "hapax-officium"):
        (repo / "vscode").mkdir(parents=True)
        (repo / "vscode/CLAUDE.md").write_text("Stable extension guidance.\n")
    (council / "AGENTS.md").write_text("This is currently broken\n")
    (council / "CLAUDE.md").symlink_to("AGENTS.md")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=council,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    git("init", "-q")
    git("add", ".")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    assert git("show", "origin/main:CLAUDE.md") == "AGENTS.md"
    (council / "AGENTS.md").write_text("Working tree is clean of rot.\n")

    # The actual notification executable is replaced, so this test sends nothing.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text('#!/bin/sh\nprintf "called\\n" >> "$AUDIT_NOTIFICATION_LOG"\n')
    curl.chmod(0o755)
    notification_log = tmp_path / "notifications"
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/monthly-claude-md-audit.sh")],
        env={
            **env,
            "WORKSPACE": str(workspace),
            "COUNCIL_CANONICAL": str(council),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "AUDIT_NOTIFICATION_LOG": str(notification_log),
        },
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "/council/AGENTS.md: [broken-claim] 1:" in result.stderr
    assert "rot:default" in result.stderr
    assert notification_log.read_text().splitlines() == ["called"]
