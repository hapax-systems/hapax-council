"""Tests for P0 relay broadcast surfacing in session-context.sh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SESSION_CONTEXT = REPO_ROOT / "hooks" / "scripts" / "session-context.sh"


def _scaffold_relay(home: Path, role: str = "cx-red") -> Path:
    relay = home / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "PROTOCOL.md").write_text("# Relay protocol\n")
    (relay / "alpha.yaml").write_text("session: alpha\nstatus: ACTIVE\n")
    (relay / "beta.yaml").write_text("session: beta\nstatus: STANDBY\n")
    (relay / f"{role}.yaml").write_text(f"session: {role}\nstatus: ACTIVE\n")
    return relay


def _run(home: Path, role: str = "cx-red") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CODEX_THREAD_NAME"] = role
    env["HAPAX_WORKTREE_ROLE"] = "beta"
    env["HAPAX_AGENT_INTERFACE"] = "codex"
    env["PATH"] = "/usr/bin:/bin"
    for name in ("HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE", "CODEX_ROLE", "CLAUDE_ROLE"):
        env.pop(name, None)
    return subprocess.run(
        ["bash", str(SESSION_CONTEXT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        cwd=str(REPO_ROOT),
    )


def test_unseen_p0_broadcast_surfaces_and_is_marked_seen(tmp_path: Path) -> None:
    relay = _scaffold_relay(tmp_path)
    inflection = relay / "inflections" / "20260428T170000Z-alpha-P0-broadcast.md"
    inflection.parent.mkdir(parents=True, exist_ok=True)
    inflection.write_text(
        "# P0 broadcast -> all peer sessions\n\n"
        "**From:** alpha\n"
        "**Severity:** P0\n"
        "**Time:** 2026-04-28T17:00:00Z\n\n"
        "Incident body\n"
    )
    (relay / "cx-red.yaml").write_text(
        "session: cx-red\n"
        "status: ACTIVE\n"
        f'p0_broadcast_inbox_20260428T170000Z: "{inflection}"\n'
        "wakeup_reason: P0_BROADCAST\n"
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "P0 BROADCAST INBOX:" in result.stdout
    assert "[P0] P0 broadcast -> all peer sessions" in result.stdout
    assert str(inflection) in result.stdout

    seen = relay / ".seen" / "cx-red-p0-broadcast.seen"
    assert seen.read_text().splitlines() == ["p0_broadcast_inbox_20260428T170000Z"]


def test_seen_p0_broadcast_is_not_repeated(tmp_path: Path) -> None:
    relay = _scaffold_relay(tmp_path)
    inflection = relay / "inflections" / "20260428T170000Z-alpha-P0-broadcast.md"
    inflection.parent.mkdir(parents=True, exist_ok=True)
    inflection.write_text("# P0 broadcast -> all peer sessions\n\n**Severity:** P0\n")
    (relay / "cx-red.yaml").write_text(
        "session: cx-red\n"
        "status: ACTIVE\n"
        f'p0_broadcast_inbox_20260428T170000Z: "{inflection}"\n'
        "wakeup_reason: P0_BROADCAST\n"
    )

    first = _run(tmp_path)
    second = _run(tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "P0 BROADCAST INBOX:" in first.stdout
    assert "P0 BROADCAST INBOX:" not in second.stdout
