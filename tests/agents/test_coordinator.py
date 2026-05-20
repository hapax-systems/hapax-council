"""Tests for the coordination daemon."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from agents.coordinator.core import (
    Coordinator,
    CoordinatorState,
    LaneDescriptor,
    LaneState,
    Task,
    _check_lane,
    _lane_to_dict,
    _parse_task,
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
        lane = LaneState(role="beta", alive=True, pid=12345, claimed_task="fix-bug")
        d = _lane_to_dict(lane)
        assert d["role"] == "beta"
        assert d["platform"] == "claude"
        assert d["alive"] is True
        assert d["pid"] == 12345
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
        )
        lane = LaneState(role="cx-red", platform="codex", alive=True, idle=True)
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
        ):
            assert Coordinator()._dispatch(task, lane) is True

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
            ]
        ]


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
