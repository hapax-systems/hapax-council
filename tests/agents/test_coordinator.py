"""Tests for the coordination daemon."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from agents.coordinator.core import (
    Coordinator,
    CoordinatorState,
    LaneDescriptor,
    LaneState,
    Task,
    _active_task_candidates,
    _check_lane,
    _effective_platform_suitability,
    _headless_task_from_argv,
    _lane_to_dict,
    _live_headless_launcher,
    _parse_task,
    _prepare_dispatch_message,
    _task_flow_counts,
)


class TestParseTask:
    def test_valid_task(self, tmp_path: Path):
        task_file = tmp_path / "test-task.md"
        task_file.write_text(
            """---
title: "Fix the widget"
status: offered
assigned_to: unassigned
wsjf: 12.0
effort_class: standard
quality_floor: deterministic_ok
platform_suitability: [claude, codex]
---

Fix the broken widget.
"""
        )
        task = _parse_task(task_file)
        assert task is not None
        assert task.task_id == "test-task"
        assert task.title == "Fix the widget"
        assert task.status == "offered"
        assert task.wsjf == 12.0
        assert "claude" in task.platform_suitability

    def test_invalid_yaml(self, tmp_path: Path):
        task_file = tmp_path / "bad.md"
        task_file.write_text("no frontmatter here")
        assert _parse_task(task_file) is None

    def test_done_task_skipped(self, tmp_path: Path):
        task_file = tmp_path / "done.md"
        task_file.write_text(
            """---
title: "Already done"
status: done
---

Done.
"""
        )
        assert _parse_task(task_file) is None

    def test_route_constraints_narrow_platform_suitability(self):
        platforms = _effective_platform_suitability(
            ["any"],
            {
                "route_metadata_schema": 1,
                "quality_floor": "deterministic_ok",
                "authority_level": "authoritative",
                "mutation_surface": "source",
                "mutation_scope_refs": [],
                "route_constraints": {
                    "allowed_platforms": ["codex"],
                    "prohibited_platforms": [],
                    "required_mode": "headless",
                    "required_profile": "full",
                },
            },
        )

        assert platforms == ("codex",)

    def test_required_interactive_mode_is_not_coordinator_routable(self):
        platforms = _effective_platform_suitability(
            ["claude"],
            {
                "route_metadata_schema": 1,
                "quality_floor": "deterministic_ok",
                "authority_level": "authoritative",
                "mutation_surface": "source",
                "mutation_scope_refs": [],
                "route_constraints": {"required_mode": "interactive"},
            },
        )

        assert platforms == ()

    def test_required_non_full_profile_is_not_coordinator_routable(self):
        platforms = _effective_platform_suitability(
            ["claude"],
            {
                "route_metadata_schema": 1,
                "quality_floor": "deterministic_ok",
                "authority_level": "authoritative",
                "mutation_surface": "source",
                "mutation_scope_refs": [],
                "route_constraints": {"required_profile": "spark"},
            },
        )

        assert platforms == ()

    def test_route_constraints_subtract_prohibited_platforms(self):
        platforms = _effective_platform_suitability(
            ["any"],
            {
                "route_metadata_schema": 1,
                "quality_floor": "deterministic_ok",
                "authority_level": "authoritative",
                "mutation_surface": "source",
                "mutation_scope_refs": [],
                "route_constraints": {
                    "allowed_platforms": ["claude", "codex"],
                    "prohibited_platforms": ["claude"],
                },
            },
        )

        assert platforms == ("codex",)

    def test_route_constraints_intersect_explicit_platforms_with_allowed(self):
        platforms = _effective_platform_suitability(
            ["claude", "codex"],
            {
                "route_metadata_schema": 1,
                "quality_floor": "deterministic_ok",
                "authority_level": "authoritative",
                "mutation_surface": "source",
                "mutation_scope_refs": [],
                "route_constraints": {"allowed_platforms": ["claude"]},
            },
        )

        assert platforms == ("claude",)


class TestLaneState:
    def test_dead_lane(self, tmp_path: Path):
        with (
            patch("agents.coordinator.core.PID_DIR", tmp_path / "pids"),
            patch("agents.coordinator.core.RELAY_DIR", tmp_path / "relay"),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane("test_lane")
        assert state.alive is False
        assert state.pid is None
        assert state.idle is True

    def test_lane_to_dict(self):
        lane = LaneState(
            role="beta", alive=True, pid=12345, pid_source="pidfile", claimed_task="fix-bug"
        )
        d = _lane_to_dict(lane)
        assert d["role"] == "beta"
        assert d["platform"] == "claude"
        assert d["alive"] is True
        assert d["pid"] == 12345
        assert d["pid_source"] == "pidfile"
        assert d["claimed_task"] == "fix-bug"

    def test_peer_status_fallback_marks_queue_dry_lane_idle(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "peer-status-cx-red.yaml").write_text(
            """session: cx-red
platform: codex
session_status: QUEUE-DRY
current_claim: null
""",
            encoding="utf-8",
        )

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="cx-red",
                    session="hapax-codex-cx-red",
                    platform="codex",
                )
            )

        assert state.alive is True
        assert state.platform == "codex"
        assert state.idle is True
        assert state.relay_age_s != float("inf")

    def test_relay_claim_beats_stale_active_claim_file(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "peer-status-cx-red.yaml").write_text(
            """session: cx-red
platform: codex
session_status: IN_PROGRESS
current_claim: relay-task
""",
            encoding="utf-8",
        )
        claim_dir = tmp_path / ".cache/hapax"
        claim_dir.mkdir(parents=True)
        (claim_dir / "cc-active-task-cx-red").write_text("stale-task\n", encoding="utf-8")

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="cx-red",
                    session="hapax-codex-cx-red",
                    platform="codex",
                )
            )

        assert state.claimed_task == "relay-task"
        assert state.idle is False

    def test_active_task_candidates_include_session_keyed_claims(self, tmp_path: Path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        old_session = cache_dir / "cc-active-task-cx-red-old"
        new_session = cache_dir / "cc-active-task-cx-red-new"
        old_session.write_text("old-task\n", encoding="utf-8")
        new_session.write_text("new-task\n", encoding="utf-8")

        with patch("agents.coordinator.core.CACHE_DIR", cache_dir):
            candidates = _active_task_candidates("cx-red")

        assert candidates[0] == cache_dir / "cc-active-task-cx-red"
        assert new_session in candidates
        assert old_session in candidates

    def test_headless_cmdline_task_parser_requires_matching_lane(self):
        argv = [
            "bash",
            "/home/hapax/.local/bin/hapax-claude-headless",
            "--task",
            "p0-task",
            "delta",
            "prompt",
        ]

        assert _headless_task_from_argv(argv, "delta") == "p0-task"
        assert _headless_task_from_argv(argv, "epsilon") is None

    def test_pidfile_free_headless_launcher_marks_lane_busy(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with (
            patch("agents.coordinator.core.PID_DIR", tmp_path / "pids"),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch(
                "agents.coordinator.core._live_headless_launcher",
                return_value=(12345, "p0-live-task"),
            ),
        ):
            state = _check_lane(LaneDescriptor(role="delta", session="", platform="claude"))

        assert state.alive is True
        assert state.pid == 12345
        assert state.pid_source == "proc"
        assert state.claimed_task == "p0-live-task"
        assert state.idle is False

    def test_live_headless_launcher_discovers_real_pidfile_free_process(self, tmp_path: Path):
        role = "ut-proc-lane"
        task_id = "p0-proc-discovery-task"
        proc = subprocess.Popen(
            [
                "bash",
                "-c",
                (
                    "exec -a hapax-claude-headless "
                    'python3 -c \'import time; time.sleep(60)\' --task "$1" "$2"'
                ),
                "_",
                task_id,
                role,
            ]
        )
        try:
            found: tuple[int, str | None] | None = None
            deadline = time.time() + 5
            with patch("agents.coordinator.core.PID_DIR", tmp_path / "pid"):
                while time.time() < deadline:
                    found = _live_headless_launcher(role)
                    if found is not None:
                        break
                    time.sleep(0.05)

            assert found == (proc.pid, task_id)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def test_dynamic_tmux_discovery_includes_alpha_and_codex(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout="hapax-claude-alpha\nhapax-codex-cx-red\nwork\n",
            stderr="",
        )

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("agents.coordinator.core.subprocess.run", return_value=completed),
        ):
            lanes = Coordinator()._check_lanes()

        assert set(lanes) == {"alpha", "cx-red"}
        assert lanes["alpha"].alive is True
        assert lanes["alpha"].platform == "claude"
        assert lanes["cx-red"].alive is True
        assert lanes["cx-red"].platform == "codex"


class TestCoordinatorState:
    def test_write_state(self, tmp_path: Path):
        coordinator = Coordinator()
        state = CoordinatorState(
            timestamp=1234.0,
            offered_tasks=3,
            claimed_tasks=2,
            lanes_alive=4,
            lanes_idle=1,
            dispatches_this_tick=0,
        )
        with (
            patch("agents.coordinator.core.SHM_DIR", tmp_path),
            patch("agents.coordinator.core.SHM_FILE", tmp_path / "state.json"),
        ):
            coordinator._write_state(state)
        data = json.loads((tmp_path / "state.json").read_text())
        assert data["offered_tasks"] == 3
        assert data["lanes_alive"] == 4


class TestPickLane:
    def test_picks_claude_compatible(self):
        coordinator = Coordinator()
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("claude",),
            quality_floor="deterministic_ok",
            path=Path("/dev/null"),
        )
        lanes = [LaneState(role="beta", alive=True, idle=True)]
        result = coordinator._pick_lane(task, lanes)
        assert result is not None
        assert result.role == "beta"

    def test_picks_codex_compatible_lane(self):
        coordinator = Coordinator()
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="deterministic_ok",
            path=Path("/dev/null"),
        )
        lanes = [LaneState(role="cx-red", platform="codex", alive=True, idle=True)]
        result = coordinator._pick_lane(task, lanes)
        assert result is not None
        assert result.role == "cx-red"

    def test_returns_none_when_no_match(self):
        coordinator = Coordinator()
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("gemini",),
            quality_floor="deterministic_ok",
            path=Path("/dev/null"),
        )
        lanes = [LaneState(role="beta", alive=True, idle=True)]
        result = coordinator._pick_lane(task, lanes)
        assert result is None


class TestDispatch:
    def test_prepare_dispatch_message_writes_strict_mq_binding(self, tmp_path: Path):
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="deterministic_ok",
            path=Path("/tmp/t1.md"),
            authority_case="CASE-TEST-001",
            parent_spec="/tmp/spec.md",
        )
        lane = LaneState(role="cx-red", platform="codex", alive=True, idle=True)
        db_path = tmp_path / "relay" / "messages.db"

        with patch.dict(os.environ, {"HAPAX_RELAY_MQ_DB": str(db_path)}):
            message_id = _prepare_dispatch_message(task, lane)

        assert message_id is not None
        assert db_path.exists()
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT subject, authority_case, recipients_spec, payload FROM messages"
            ).fetchone()
        assert row is not None
        assert row[0] == "t1"
        assert row[1] == "CASE-TEST-001"
        assert row[2] == "cx-red"
        payload = json.loads(row[3])
        assert payload["task_id"] == "t1"
        assert payload["lane"] == "cx-red"
        assert payload["parent_spec"] == "/tmp/spec.md"
        assert "next_action_on_binding_failure" in payload

    def test_dispatch_uses_methodology_dispatcher(self, tmp_path: Path):
        dispatcher = tmp_path / "projects/hapax-council/scripts/hapax-methodology-dispatch"
        dispatcher.parent.mkdir(parents=True)
        dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        dispatcher.chmod(0o755)
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="deterministic_ok",
            path=Path("/tmp/t1.md"),
            authority_case="CASE-TEST-001",
        )
        lane = LaneState(role="cx-red", platform="codex", alive=True, idle=True)
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with (
            patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
            patch("agents.coordinator.core._prepare_dispatch_message", return_value="mq-test-1"),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
        ):
            assert Coordinator()._dispatch(task, lane) == (True, "")

        assert calls == [
            [
                str(dispatcher),
                "--task",
                "t1",
                "--lane",
                "cx-red",
                "--platform",
                "codex",
                "--mode",
                "headless",
                "--launch",
                "--mq-message-id",
                "mq-test-1",
            ]
        ]

    def test_dispatch_reports_mq_prepare_failure_with_next_action(self, tmp_path: Path):
        dispatcher = tmp_path / "hapax-methodology-dispatch"
        dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        dispatcher.chmod(0o755)
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="deterministic_ok",
            path=Path("/tmp/t1.md"),
            authority_case="CASE-TEST-001",
        )
        lane = LaneState(role="cx-red", platform="codex", alive=True, idle=True)

        with (
            patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
            patch("agents.coordinator.core._prepare_dispatch_message", side_effect=OSError("disk")),
        ):
            ok, reason = Coordinator()._dispatch(task, lane)

        assert ok is False
        assert reason.startswith("durable_mq_prepare_failed:OSError:disk")
        assert "next_action=check HAPAX_RELAY_MQ_DB" in reason

    def test_dispatch_without_authority_case_omits_mq_message_id(self, tmp_path: Path):
        dispatcher = tmp_path / "hapax-methodology-dispatch"
        dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        dispatcher.chmod(0o755)
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="deterministic_ok",
            path=Path("/tmp/t1.md"),
        )
        lane = LaneState(role="cx-red", platform="codex", alive=True, idle=True)
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with (
            patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
        ):
            assert Coordinator()._dispatch(task, lane) == (True, "")

        assert "--mq-message-id" not in calls[0]


class TestScanTasks:
    def test_scan_empty_dir(self, tmp_path: Path):
        coordinator = Coordinator()
        with patch("agents.coordinator.core.TASKS_DIR", tmp_path):
            tasks = coordinator._scan_tasks()
        assert tasks == []

    def test_scan_with_tasks(self, tmp_path: Path):
        (tmp_path / "high-priority.md").write_text(
            """---
title: "High priority"
status: offered
wsjf: 20.0
---
"""
        )
        (tmp_path / "low-priority.md").write_text(
            """---
title: "Low priority"
status: offered
wsjf: 5.0
---
"""
        )
        coordinator = Coordinator()
        with patch("agents.coordinator.core.TASKS_DIR", tmp_path):
            tasks = coordinator._scan_tasks()
        assert len(tasks) == 2
        ids = {t.task_id for t in tasks}
        assert "high-priority" in ids
        assert "low-priority" in ids

    def test_task_flow_counts_include_remediation_and_no_owner(self):
        tasks = [
            Task(
                task_id="request-decompose-admission-blocked-a",
                title="Repair request decomposition admission",
                status="offered",
                assigned_to="unassigned",
                wsjf=10.0,
                effort_class="standard",
                platform_suitability=("codex",),
                quality_floor="deterministic_ok",
                path=Path("/tmp/a.md"),
            ),
            Task(
                task_id="task-b",
                title="PR task",
                status="pr_open",
                assigned_to="cx-red",
                wsjf=10.0,
                effort_class="standard",
                platform_suitability=("codex",),
                quality_floor="deterministic_ok",
                path=Path("/tmp/b.md"),
            ),
        ]

        counts = _task_flow_counts(tasks)

        assert counts["offered"] == 1
        assert counts["pr_open"] == 1
        assert counts["remediation"] == 1
        assert counts["no_owner"] == 1
