"""Tests for the coordination daemon."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
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
    _discover_lanes,
    _dispatch_landed,
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

    def test_nullable_or_invalid_wsjf_defaults_to_zero(self, tmp_path: Path):
        for value in ("null", "not-a-number", ".nan"):
            task_file = tmp_path / f"{value}.md"
            task_file.write_text(
                f"""---
title: "Loose WSJF"
status: offered
assigned_to: unassigned
wsjf: {value}
---
""",
                encoding="utf-8",
            )

            task = _parse_task(task_file)

            assert task is not None
            assert task.wsjf == 0.0

    def test_nullable_string_frontmatter_fields_get_stable_defaults(self, tmp_path: Path):
        task_file = tmp_path / "nullable-fields.md"
        task_file.write_text(
            """---
title: null
status: offered
assigned_to: null
effort_class: null
quality_floor: null
---
""",
            encoding="utf-8",
        )

        task = _parse_task(task_file)

        assert task is not None
        assert task.title == "nullable-fields"
        assert task.assigned_to == "unassigned"
        assert task.effort_class == "standard"
        assert task.quality_floor == "deterministic_ok"

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

    def test_blocked_and_pr_open_tasks_remain_visible_for_flow_counts(self, tmp_path: Path):
        blocked = tmp_path / "blocked.md"
        blocked.write_text(
            """---
title: "Blocked"
status: blocked
assigned_to: unassigned
---
""",
            encoding="utf-8",
        )
        pr_open = tmp_path / "pr-open.md"
        pr_open.write_text(
            """---
title: "PR"
status: pr_open
assigned_to: cx-red
---
""",
            encoding="utf-8",
        )

        blocked_task = _parse_task(blocked)
        pr_open_task = _parse_task(pr_open)

        assert blocked_task is not None
        assert pr_open_task is not None
        assert blocked_task.status == "blocked"
        assert pr_open_task.status == "pr_open"

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

    def test_relay_task_id_none_does_not_create_phantom_claim(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "cx-blue.yaml").write_text(
            """session: cx-blue
platform: codex
status: idle
session_status: QUEUE-DRY
current_claim: null
task_id: none
""",
            encoding="utf-8",
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="cx-blue",
                    session="hapax-codex-cx-blue",
                    platform="codex",
                )
            )

        assert state.alive is True
        assert state.claimed_task is None
        assert state.idle is True

    def test_blocked_claim_ownership_relay_does_not_hold_lane_claim(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "cx-blue-status.yaml").write_text(
            """role: cx-blue
status: blocked_claim_ownership
task_id: p0-claim-blocked
""",
            encoding="utf-8",
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="cx-blue",
                    session="hapax-codex-cx-blue",
                    platform="codex",
                )
            )

        assert state.claimed_task is None
        assert state.idle is True

    def test_blocked_claim_ownership_relay_does_not_mask_active_lease(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "cx-blue-status.yaml").write_text(
            """role: cx-blue
status: blocked_claim_ownership
task_id: p0-claim-blocked
""",
            encoding="utf-8",
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "cc-active-task-cx-blue").write_text("older-live-task\n", encoding="utf-8")

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="cx-blue",
                    session="hapax-codex-cx-blue",
                    platform="codex",
                )
            )

        assert state.claimed_task == "older-live-task"
        assert state.idle is False

    def test_resolved_no_active_claim_relay_task_id_does_not_hold_lane(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "cx-gold.yaml").write_text(
            """session: cx-gold
platform: codex
status: resolved_pending_frontier_review_no_active_claim
current_claim: null
task_id: p0-resolved-incident
""",
            encoding="utf-8",
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="cx-gold",
                    session="hapax-codex-cx-gold",
                    platform="codex",
                )
            )

        assert state.claimed_task is None
        assert state.idle is True

    def test_no_task_other_session_diagnostic_claim_does_not_hold_lane(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "cx-green.yaml").write_text(
            """session: cx-green
platform: codex
status: bootstrap_preflight_no_task_other_session_claim_active
current_claim: "other session active: p0-incident assigned_to=cx-green session=old-session"
task_id: null
""",
            encoding="utf-8",
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="cx-green",
                    session="hapax-codex-cx-green",
                    platform="codex",
                )
            )

        assert state.claimed_task is None
        assert state.idle is True

    def test_active_relay_task_id_still_counts_as_claim(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "cx-red.yaml").write_text(
            """session: cx-red
platform: codex
status: active_claim_p0_incident_triage
current_claim: null
task_id: p0-active-incident
""",
            encoding="utf-8",
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="cx-red",
                    session="hapax-codex-cx-red",
                    platform="codex",
                )
            )

        assert state.claimed_task == "p0-active-incident"
        assert state.idle is False

    def test_role_status_retired_beats_stale_peer_active_without_claim(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        peer_status = relay_dir / "peer-status-epsilon.yaml"
        peer_status.write_text(
            """session: epsilon
platform: claude
session_status: ACTIVE
current_claim: old-task
""",
            encoding="utf-8",
        )
        role_status = relay_dir / "epsilon-status.yaml"
        role_status.write_text(
            """role: epsilon
status: retired
retired_reason: clean exit
""",
            encoding="utf-8",
        )
        now = time.time()
        os.utime(peer_status, (now - 3600, now - 3600))
        os.utime(role_status, (now, now))

        with (
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="epsilon",
                    session="hapax-claude-epsilon",
                    platform="claude",
                )
            )

        assert state.alive is True
        assert state.claimed_task is None
        assert state.idle is True

    def test_active_task_file_still_beats_retired_role_status(self, tmp_path: Path):
        role = "ut-role"
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / f"{role}-status.yaml").write_text(
            f"""role: {role}
status: retired
retired_reason: clean exit
""",
            encoding="utf-8",
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / f"cc-active-task-{role}").write_text("live-task\n", encoding="utf-8")

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role=role,
                    session=f"hapax-claude-{role}",
                    platform="claude",
                )
            )

        assert state.claimed_task == "live-task"
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
        assert (
            _headless_task_from_argv(
                ["bash", "not-hapax-claude-headless", "--task", "p0-task", "delta"],
                "delta",
            )
            is None
        )

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

    def test_live_headless_launcher_rejects_pidfile_reused_by_foreign_process(self, tmp_path: Path):
        role = "ut-foreign-pid-lane"
        pid_dir = tmp_path / "pid"
        pid_dir.mkdir()
        (pid_dir / f"{role}.launcher.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

        with patch("agents.coordinator.core.PID_DIR", pid_dir):
            assert _live_headless_launcher(role) is None

    def test_dynamic_tmux_discovery_includes_fallback_greek_and_codex(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        pid_dir = tmp_path / "pids"
        pid_dir.mkdir()
        codex_pid_dir = tmp_path / "codex-pids"
        codex_pid_dir.mkdir()
        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout="hapax-claude-alpha\nhapax-codex-cx-red\nwork\n",
            stderr="",
        )

        with (
            patch("agents.coordinator.core.PID_DIR", pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("agents.coordinator.core.subprocess.run", return_value=completed),
        ):
            lanes = Coordinator()._check_lanes()

        assert {
            "alpha",
            "beta",
            "gamma",
            "delta",
            "epsilon",
            "zeta",
            "eta",
            "theta",
            "cx-red",
        } <= set(lanes)
        assert lanes["alpha"].alive is True
        assert lanes["beta"].alive is False
        assert lanes["alpha"].platform == "claude"
        assert lanes["cx-red"].alive is True
        assert lanes["cx-red"].platform == "codex"

    def test_pid_backed_headless_lane_is_discovered_with_existing_tmux_sessions(
        self, tmp_path: Path
    ):
        pid_dir = tmp_path / "pids"
        pid_dir.mkdir()
        (pid_dir / "gamma.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
        codex_pid_dir = tmp_path / "codex-pids"
        codex_pid_dir.mkdir()
        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout="hapax-claude-beta\nhapax-claude-delta\n",
            stderr="",
        )

        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with (
            patch("agents.coordinator.core.PID_DIR", pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.subprocess.run", return_value=completed),
        ):
            descriptors = _discover_lanes()
            lanes = Coordinator()._check_lanes()

        gamma = next(lane for lane in descriptors if lane.role == "gamma")
        assert gamma.session == ""
        assert gamma.platform == "claude"
        assert lanes["gamma"].alive is True
        assert lanes["gamma"].pid == os.getpid()
        assert lanes["gamma"].pid_source == "pidfile"

    def test_codex_pid_backed_headless_lane_is_discovered_and_counts_as_landed(
        self, tmp_path: Path
    ):
        role = "cx-blue"
        task_id = "p0-codex-live-task"
        claude_pid_dir = tmp_path / "claude-pids"
        claude_pid_dir.mkdir()
        codex_pid_dir = tmp_path / "codex-pids"
        codex_pid_dir.mkdir()
        (codex_pid_dir / f"{role}.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / f"cc-active-task-{role}").write_text(f"{task_id}\n", encoding="utf-8")

        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout="hapax-claude-beta\n",
            stderr="",
        )

        with (
            patch("agents.coordinator.core.PID_DIR", claude_pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.subprocess.run", return_value=completed),
        ):
            descriptors = _discover_lanes()
            lanes = Coordinator()._check_lanes()
            task = Task(
                task_id=task_id,
                title="codex live pickup",
                status="offered",
                assigned_to="unassigned",
                wsjf=10.0,
                effort_class="standard",
                platform_suitability=("codex",),
                quality_floor="deterministic_ok",
                path=tmp_path / f"{task_id}.md",
            )

            assert _dispatch_landed(task, lanes[role]) is True

        descriptor = next(lane for lane in descriptors if lane.role == role)
        assert descriptor.session == ""
        assert descriptor.platform == "codex"
        assert lanes[role].alive is True
        assert lanes[role].pid == os.getpid()
        assert lanes[role].pid_source == "pidfile"
        assert lanes[role].claimed_task == task_id
        assert lanes[role].idle is False


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
    def test_methodology_dispatcher_honors_environment_override(self, tmp_path: Path):
        override = tmp_path / "hapax-methodology-dispatch"

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from agents.coordinator.core import METHODOLOGY_DISPATCHER; print(METHODOLOGY_DISPATCHER)",
            ],
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "HAPAX_METHODOLOGY_DISPATCHER": str(override)},
            text=True,
            capture_output=True,
            check=True,
        )

        assert result.stdout.strip() == str(override)

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
        run_kwargs: list[dict[str, object]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            run_kwargs.append(kwargs)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with (
            patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
            patch("agents.coordinator.core._prepare_dispatch_message", return_value="mq-test-1"),
            patch("agents.coordinator.core.DISPATCH_TIMEOUT_S", 42.0),
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
        assert run_kwargs[0]["timeout"] == 42.0

    def test_dispatch_timeout_with_live_pickup_counts_success(self, tmp_path: Path):
        dispatcher = tmp_path / "hapax-methodology-dispatch"
        dispatcher.write_text("#!/bin/sh\nsleep 60\n", encoding="utf-8")
        dispatcher.chmod(0o755)
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("claude",),
            quality_floor="deterministic_ok",
            path=tmp_path / "t1.md",
        )
        lane = LaneState(role="delta", platform="claude", alive=True, idle=True)

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        with (
            patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
            patch("agents.coordinator.core.DISPATCH_TIMEOUT_S", 30.0),
            patch("agents.coordinator.core.DISPATCH_TIMEOUT_LANDING_GRACE_S", 0.0),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
            patch("agents.coordinator.core._dispatch_landed", return_value=True),
        ):
            assert Coordinator()._dispatch(task, lane) == (True, "")

    def test_dispatch_landed_requires_exact_active_claim_lease(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "cx-red-status.yaml").write_text(
            """role: cx-red
status: active
current_claim: p0-task
""",
            encoding="utf-8",
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        task = Task(
            task_id="p0-task",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="deterministic_ok",
            path=tmp_path / "p0-task.md",
        )
        lane = LaneState(
            role="cx-red",
            session="hapax-codex-cx-red",
            platform="codex",
            alive=True,
            idle=False,
        )

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core._lane_launcher_process_present", return_value=True),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            assert _dispatch_landed(task, lane) is False
            (cache_dir / "cc-active-task-cx-red").write_text("p0-task\n", encoding="utf-8")
            assert _dispatch_landed(task, lane) is True

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


class TestOrphanClaimRecovery:
    def _task_note(
        self,
        tmp_path: Path,
        *,
        name: str = "p0-orphan",
        assigned_to: str = "alpha",
        status: str = "claimed",
        claimed_at: str = "2000-01-01T00:00:00Z",
    ) -> Path:
        path = tmp_path / f"{name}.md"
        path.write_text(
            f"""---
title: "P0 orphan"
status: {status}
assigned_to: {assigned_to}
priority: p0
claimed_at: {claimed_at}
updated_at: {claimed_at}
---

Body.
""",
            encoding="utf-8",
        )
        return path

    def test_stale_claimed_p0_without_live_pickup_reoffers(self, tmp_path: Path):
        path = self._task_note(tmp_path)
        task = _parse_task(path)
        assert task is not None
        ledger = tmp_path / "authority-case-ledger.jsonl"

        with patch("agents.coordinator.core.REOFFER_LEDGER", ledger):
            count = Coordinator()._reoffer_orphaned_claims([task], {}, now_wall=time.time())

        assert count == 1
        reparsed = _parse_task(path)
        assert reparsed is not None
        assert reparsed.status == "offered"
        assert reparsed.assigned_to == "unassigned"
        assert "orphan_claim_reoffer" in ledger.read_text(encoding="utf-8")

    def test_stale_in_progress_p0_without_live_pickup_reoffers(self, tmp_path: Path):
        path = self._task_note(tmp_path, status="in_progress")
        task = _parse_task(path)
        assert task is not None
        ledger = tmp_path / "authority-case-ledger.jsonl"

        with patch("agents.coordinator.core.REOFFER_LEDGER", ledger):
            count = Coordinator()._reoffer_orphaned_claims([task], {}, now_wall=time.time())

        assert count == 1
        reparsed = _parse_task(path)
        assert reparsed is not None
        assert reparsed.status == "offered"
        assert reparsed.assigned_to == "unassigned"
        assert "orphan_claim_reoffer" in ledger.read_text(encoding="utf-8")

    def test_orphan_reoffer_preserves_lane_claim_for_different_live_task(self, tmp_path: Path):
        path = self._task_note(tmp_path, assigned_to="delta")
        task = _parse_task(path)
        assert task is not None
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        active_claim = cache_dir / "cc-active-task-delta"
        active_claim.write_text("different-task\n", encoding="utf-8")
        ledger = tmp_path / "authority-case-ledger.jsonl"
        lanes = {
            "delta": LaneState(
                role="delta",
                platform="claude",
                alive=True,
                idle=False,
                claimed_task="different-task",
            )
        }

        with (
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.REOFFER_LEDGER", ledger),
        ):
            count = Coordinator()._reoffer_orphaned_claims([task], lanes, now_wall=time.time())

        assert count == 1
        assert active_claim.read_text(encoding="utf-8") == "different-task\n"

    def test_live_lane_pickup_is_not_reoffered(self, tmp_path: Path):
        path = self._task_note(tmp_path, assigned_to="delta")
        task = _parse_task(path)
        assert task is not None
        lanes = {
            "delta": LaneState(
                role="delta",
                platform="claude",
                alive=True,
                idle=False,
                claimed_task=task.task_id,
            )
        }

        with patch("agents.coordinator.core._lane_launcher_process_present", return_value=True):
            count = Coordinator()._reoffer_orphaned_claims([task], lanes, now_wall=time.time())

        assert count == 0
        reparsed = _parse_task(path)
        assert reparsed is not None
        assert reparsed.status == "claimed"

    def test_live_codex_tmux_pickup_without_launcher_is_not_reoffered(self, tmp_path: Path):
        path = self._task_note(tmp_path, assigned_to="cx-red")
        task = _parse_task(path)
        assert task is not None
        lanes = {
            "cx-red": LaneState(
                role="cx-red",
                session="hapax-codex-cx-red",
                platform="codex",
                alive=True,
                idle=False,
                claimed_task=task.task_id,
                output_age_s=0.0,
            )
        }

        with patch("agents.coordinator.core._lane_launcher_process_present", return_value=False):
            count = Coordinator()._reoffer_orphaned_claims([task], lanes, now_wall=time.time())

        assert count == 0
        reparsed = _parse_task(path)
        assert reparsed is not None
        assert reparsed.status == "claimed"

    def test_recent_claimed_p0_stays_in_grace(self, tmp_path: Path):
        path = self._task_note(tmp_path)
        task = _parse_task(path)
        assert task is not None
        recent = Task(
            task_id=task.task_id,
            title=task.title,
            status=task.status,
            assigned_to=task.assigned_to,
            wsjf=task.wsjf,
            effort_class=task.effort_class,
            platform_suitability=task.platform_suitability,
            quality_floor=task.quality_floor,
            path=task.path,
            claimed_at=1000.0,
            priority="p0",
        )

        count = Coordinator()._reoffer_orphaned_claims([recent], {}, now_wall=1001.0)

        assert count == 0
        assert _parse_task(path).status == "claimed"  # type: ignore[union-attr]


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
