"""Tests for the D-30 Phase 4 CC-TASK SSOT block in session-context.sh.

Invokes session-context.sh in a controlled environment with a synthetic
vault under tmp HOME and asserts the new CC-task block surfaces the
claimed task + top-offered queue + dashboard reminder.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest  # noqa: TC002

REPO_ROOT = Path(__file__).parent.parent.parent
SESSION_CONTEXT = REPO_ROOT / "hooks" / "scripts" / "session-context.sh"


def _make_vault_task(
    vault_root: Path, *, task_id: str, status: str, title: str, wsjf: float = 0.0
) -> None:
    folder = "active" if status not in ("done", "withdrawn", "superseded") else "closed"
    note_dir = vault_root / folder
    note_dir.mkdir(parents=True, exist_ok=True)
    (note_dir / f"{task_id}-test.md").write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "{title}"
status: {status}
assigned_to: unassigned
priority: normal
wsjf: {wsjf}
created_at: 2026-04-20T00:00:00Z
updated_at: 2026-04-20T00:00:00Z
---

# {title}
"""
    )


def _scaffold_minimal_relay(home: Path, role: str = "alpha") -> Path:
    """Build a minimal relay dir so RELAY_ACTIVE evaluates true."""
    relay = home / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "PROTOCOL.md").write_text("# Relay protocol\n")
    (relay / "alpha.yaml").write_text("session: alpha\nstatus: ACTIVE\n")
    (relay / "beta.yaml").write_text("session: beta\nstatus: STANDBY\n")
    return relay


def _run(home: Path, role: str = "cx-red") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("HAPAX_WORKTREE_ROLE", None)
    env.pop("CODEX_THREAD_NAME", None)
    env.pop("CODEX_ROLE", None)
    env.pop("CLAUDE_ROLE", None)
    env["CODEX_THREAD_NAME"] = role
    env["HAPAX_WORKTREE_ROLE"] = "alpha"
    env["HAPAX_AGENT_INTERFACE"] = "codex"
    # Stop hapax-whoami from being found so role inference falls to PWD.
    env["PATH"] = "/usr/bin:/bin"
    return subprocess.run(
        ["bash", str(SESSION_CONTEXT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Synthetic HOME with relay scaffold + empty vault."""
    _scaffold_minimal_relay(tmp_path)
    vault = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (vault / "active").mkdir(parents=True, exist_ok=True)
    (vault / "closed").mkdir(parents=True, exist_ok=True)
    return tmp_path


class TestCCTaskBlockSurfaces:
    def test_block_appears_in_output(self, home: Path) -> None:
        result = _run(home)
        assert "CC-TASK SSOT" in result.stdout, f"stderr={result.stderr}"

    def test_codex_agent_identity_appears(self, home: Path) -> None:
        result = _run(home)
        assert "Agent: codex/cx-red (slot alpha)" in result.stdout

    def test_dashboard_reminder_always_shown(self, home: Path) -> None:
        result = _run(home)
        assert "Dashboard: open Obsidian" in result.stdout

    def test_no_claim_message(self, home: Path) -> None:
        """When no claim file exists, says (none)."""
        result = _run(home)
        assert "Claimed: (none — await governed dispatch" in result.stdout
        assert "do not self-claim by WSJF" in result.stdout


class TestClaimedTaskSurfaces:
    def test_claimed_task_title_shown(self, home: Path) -> None:
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _make_vault_task(vault, task_id="alph-001", status="in_progress", title="Active alpha task")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "cc-active-task-cx-red").write_text("alph-001\n")
        result = _run(home)
        assert "Claimed: alph-001" in result.stdout
        assert "Active alpha task" in result.stdout
        assert "[in_progress]" in result.stdout

    def test_descriptorless_claimed_task_title_shown(self, home: Path) -> None:
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _make_vault_task(vault, task_id="alph-001", status="in_progress", title="Active alpha task")
        active = vault / "active"
        (active / "alph-001-test.md").rename(active / "alph-001.md")
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "cc-active-task-cx-red").write_text("alph-001\n")

        result = _run(home)

        assert "Claimed: alph-001" in result.stdout
        assert "Active alpha task" in result.stdout


class TestNoSelfSelectionPrompt:
    def test_top_offered_queue_not_printed(self, home: Path) -> None:
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        _make_vault_task(vault, task_id="bbb-002", status="offered", title="High", wsjf=15.5)
        result = _run(home)
        assert "Top offered" not in result.stdout
        assert "bbb-002" not in result.stdout
        assert "await governed dispatch" in result.stdout


class TestPlanningFeedDispatchBlock:
    def _write_feed(self, home: Path, *, generated_at: str = "2099-01-01T00:00:00Z") -> None:
        feed = home / ".cache" / "hapax" / "planning-feed-state.json"
        feed.parent.mkdir(parents=True, exist_ok=True)
        feed.write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "dispatch": {
                        "readiness": "ready",
                        "dispatchable_count": 1,
                        "planning_attention_count": 1,
                        "dispatchable_tasks": [
                            {
                                "task_id": "eligible-001",
                                "wsjf": 11.5,
                                "authority_case": "CASE-TEST-001",
                            }
                        ],
                        "planning_queue": [
                            {
                                "item_type": "request",
                                "request_id": "REQ-NEEDS-CASE",
                                "action_needed": "needs authority case creation",
                                "age_hours": 4,
                            }
                        ],
                        "capacity_routing": {
                            "warning_count": 1,
                            "non_green_states": [
                                {
                                    "state": "route_metadata_hold",
                                    "summary": "1 offered task(s) have hold route metadata",
                                }
                            ],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_missing_feed_warns_manual_dispatch_only(self, home: Path) -> None:
        result = _run(home)
        assert "PLANNING FEED: priority feed unavailable" in result.stdout

    def test_ready_feed_surfaces_dispatch_and_planning_attention(self, home: Path) -> None:
        self._write_feed(home)
        result = _run(home)
        assert "DISPATCHABLE WORK: 1 item(s) exist" in result.stdout
        assert "must wait for governed dispatch" in result.stdout
        assert "eligible-001" not in result.stdout
        assert "PLANNING ATTENTION (1 items)" in result.stdout
        assert "REQ-NEEDS-CASE" in result.stdout

    def test_ready_feed_surfaces_capacity_routing_warnings(self, home: Path) -> None:
        self._write_feed(home)
        result = _run(home)
        assert "CAPACITY ROUTING (1 non-green, observe-only)" in result.stdout
        assert "route_metadata_hold" in result.stdout

    def test_claimed_session_suppresses_eligible_work_prompt(self, home: Path) -> None:
        self._write_feed(home)
        cache = home / ".cache" / "hapax"
        (cache / "cc-active-task-cx-red").write_text("already-claimed\n", encoding="utf-8")
        result = _run(home)
        assert "DISPATCHABLE WORK" not in result.stdout
        assert "PLANNING ATTENTION (1 items)" in result.stdout

    def test_stale_feed_escalates_to_unavailable(self, home: Path) -> None:
        self._write_feed(home, generated_at="2020-01-01T00:00:00Z")
        result = _run(home)
        assert "PLANNING FEED: unavailable" in result.stdout
        assert "timer investigation needed" in result.stdout
        assert "DISPATCHABLE WORK" not in result.stdout


class TestVaultAbsent:
    def test_vault_missing_silently_skips(self, tmp_path: Path) -> None:
        # Scaffold relay but NOT vault.
        _scaffold_minimal_relay(tmp_path)
        result = _run(tmp_path)
        assert "CC-TASK SSOT" not in result.stdout
