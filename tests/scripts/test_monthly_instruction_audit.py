"""Exercise the real audit's canonical source, discovery, and failure paths."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def git(council: Path, env: dict[str, str], *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=council, env=env, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def audit(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    workspace = tmp_path / "projects"
    council = workspace / "hapax-council"
    council.mkdir(parents=True)
    for repo in (council, workspace / "hapax-officium"):
        (repo / "vscode").mkdir(parents=True)
        (repo / "vscode/CLAUDE.md").write_text("Stable extension guidance.\n")
    (council / "AGENTS.md").write_text("This is currently broken\n")
    (council / "CLAUDE.md").symlink_to("AGENTS.md")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    git(council, env, "init", "-q")
    git(council, env, "add", ".")
    git(
        council,
        env,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    git(council, env, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert git(council, env, "show", "origin/main:CLAUDE.md") == "AGENTS.md"
    (council / "AGENTS.md").write_text("Working tree is clean of rot.\n")

    # The actual notification executable is replaced, so this test sends nothing.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text('#!/bin/sh\nprintf "called\\n" >> "$AUDIT_NOTIFICATION_LOG"\n')
    curl.chmod(0o755)
    notification_log = tmp_path / "notifications"
    env.update(
        WORKSPACE=str(workspace),
        COUNCIL_CANONICAL=str(council),
        PATH=f"{fake_bin}:{env['PATH']}",
        AUDIT_NOTIFICATION_LOG=str(notification_log),
    )
    return council, env, notification_log


def run_audit(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / "scripts/monthly-claude-md-audit.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_monthly_audit_reads_canonical_main_content(
    audit: tuple[Path, dict[str, str], Path],
) -> None:
    _, env, notification_log = audit
    result = run_audit(env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "/council/AGENTS.md: [broken-claim] 1:" in result.stderr
    assert "rot:default" in result.stderr
    assert notification_log.read_text().splitlines() == ["called"]


def test_monthly_audit_discovers_sibling_agents_once(
    audit: tuple[Path, dict[str, str], Path],
) -> None:
    council, env, _ = audit
    # Drop the remote ref so the clean working tree supplies Council's content.
    git(council, env, "update-ref", "-d", "refs/remotes/origin/main")
    sibling = council.parent / "sibling"
    sibling.mkdir()
    (sibling / "AGENTS.md").write_text("This is currently broken\n")
    (sibling / "CLAUDE.md").symlink_to("AGENTS.md")
    result = run_audit(env)
    assert result.returncode == 1, result.stdout + result.stderr
    # Once per mode (default and strict), never again under the alias filename.
    assert result.stderr.count(f"{sibling}/AGENTS.md: [broken-claim] 1:") == 2
    assert f"{sibling}/CLAUDE.md:" not in result.stderr


@pytest.mark.parametrize("rotten", [False, True])
def test_monthly_audit_falls_back_to_working_tree(
    audit: tuple[Path, dict[str, str], Path], rotten: bool
) -> None:
    council, env, notification_log = audit
    git(council, env, "update-ref", "-d", "refs/remotes/origin/main")
    if rotten:
        (council / "AGENTS.md").write_text("This is currently broken\n")
    result = run_audit(env)
    assert result.returncode == int(rotten), result.stdout + result.stderr
    assert "fetch origin/main" in result.stderr
    assert "Trying working-tree content" in result.stderr
    assert "working-tree-fallback (origin/main comparison unobserved)" in (
        result.stderr if rotten else result.stdout
    )
    assert notification_log.exists() == rotten
    if rotten:
        assert "/council/AGENTS.md: [broken-claim] 1:" in result.stderr
    else:
        assert "3 file(s) clean" in result.stdout


def test_monthly_audit_refuses_missing_canonical_content(
    audit: tuple[Path, dict[str, str], Path],
) -> None:
    council, env, notification_log = audit
    git(council, env, "update-ref", "-d", "refs/remotes/origin/main")
    (council / "AGENTS.md").unlink()
    result = run_audit(env)
    assert result.returncode == 2
    assert "working-tree fallback also failed; restore AGENTS.md" in result.stderr
    assert "clean" not in result.stdout
    assert not notification_log.exists()


@pytest.mark.parametrize(
    "policy",
    [
        "config/agent-instructions/AGENTS.md",
        "config/agent-instructions/native/grok.md",
        "docs/runbooks/council-domain-context.md",
    ],
)
@pytest.mark.parametrize("fallback", [False, True])
def test_extracted_policy_uses_canonical_snapshot(audit, policy, fallback):
    council, env, _ = audit
    target = council / policy
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("currently broken\n")
    if fallback:
        git(council, env, "update-ref", "-d", "refs/remotes/origin/main")
    else:
        git(council, env, "add", ".")
        git(
            council,
            env,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "extracted policy",
        )
        git(council, env, "update-ref", "refs/remotes/origin/main", "HEAD")
        target.write_text("Clean working-tree successor.\n")
    result = run_audit(env)
    assert result.returncode == 1, result.stderr
    assert f"/council/{policy}: [broken-claim] 1:" in result.stderr
