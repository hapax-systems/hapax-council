"""Tests for the coordination daemon."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from agents.coordinator.core import (
    _DISPATCH_CLAIM_GUARD_MARKERS,
    _DISPATCH_CLOSE_GUARD_MARKERS,
    TMUX_DISCOVERY_FORMAT,
    Coordinator,
    CoordinatorState,
    LaneDescriptor,
    LaneState,
    Task,
    _active_task_candidates,
    _check_lane,
    _discover_lanes,
    _dispatch_landed,
    _dispatch_tool_blocker,
    _dispatch_worktree,
    _effective_platform_suitability,
    _headless_task_from_argv,
    _lane_to_dict,
    _live_headless_launcher,
    _parse_task,
    _pid_generation,
    _prepare_dispatch_message,
    _refresh_dispatch_lane,
    _relay_status_is_retired,
    _task_flow_counts,
)
from shared.coord_dispatch import DispatchLaunchRequest, _accept_dispatch_message
from shared.coord_event_log import CoordEventLog
from shared.sdlc_pressure_gate import AdmissionDecision
from shared.sdlc_task_store import ClaimDispatchBinding, write_claim_dispatch_binding

REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCHER_SCRIPT = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"


def _guarded_worktree(path: Path) -> None:
    (path / "scripts").mkdir(parents=True)
    (path / "scripts" / "cc-claim").write_text(
        f"#!/bin/sh\n# {' '.join(_DISPATCH_CLAIM_GUARD_MARKERS)}\n",
        encoding="utf-8",
    )
    (path / "scripts" / "cc-close").write_text(
        f"#!/bin/sh\n# {' '.join(_DISPATCH_CLOSE_GUARD_MARKERS)}\n",
        encoding="utf-8",
    )


def _stale_worktree(path: Path) -> None:
    (path / "scripts").mkdir(parents=True)
    (path / "scripts" / "cc-claim").write_text("#!/bin/sh\n# legacy cc-claim\n", encoding="utf-8")
    (path / "scripts" / "cc-close").write_text("#!/bin/sh\n# legacy cc-close\n", encoding="utf-8")


def _stale_claim_worktree(path: Path) -> None:
    _guarded_worktree(path)
    (path / "scripts" / "cc-claim").write_text("#!/bin/sh\n# legacy cc-claim\n", encoding="utf-8")


def _stale_close_worktree(path: Path) -> None:
    _guarded_worktree(path)
    (path / "scripts" / "cc-close").write_text("#!/bin/sh\n# legacy cc-close\n", encoding="utf-8")


def _dispatcher_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_methodology_dispatch_coordinator_test",
        str(DISPATCHER_SCRIPT),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


class TestDispatchWorktreeGuard:
    def test_dispatch_worktree_mirrors_platform_mappings(self, tmp_path: Path):
        root = tmp_path / "projects"

        with patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(root)}, clear=False):
            assert _dispatch_worktree("cx-red", "codex") == root / "hapax-council--cx-red"
            assert _dispatch_worktree("red", "codex") == root / "hapax-council--cx-red"
            assert _dispatch_worktree("alpha", "claude") == root / "hapax-council"
            assert _dispatch_worktree("beta", "claude") == root / "hapax-council--beta"
            assert _dispatch_worktree("gamma", "gemini") == root / "hapax-council"
            assert _dispatch_worktree("vbe-1", "vibe") == root / "hapax-council--vbe-1"
            assert _dispatch_worktree("other", "unknown") == root / "hapax-council"

    def test_dispatch_worktree_expands_project_root_home(self, tmp_path: Path):
        with patch.dict(
            "os.environ",
            {"HOME": str(tmp_path), "HAPAX_DISPATCH_PROJECT_ROOT": "~/projects"},
            clear=False,
        ):
            assert _dispatch_worktree("cx-red", "codex") == (
                tmp_path / "projects" / "hapax-council--cx-red"
            )

    def test_dispatch_worktree_matches_methodology_dispatcher(self, tmp_path: Path):
        dispatcher = _dispatcher_module()
        root = tmp_path / "projects"
        override = tmp_path / "custom-worktree"
        cases = (
            ("cx-red", "codex"),
            ("red", "codex"),
            ("alpha", "claude"),
            ("beta", "claude"),
            ("gamma", "gemini"),
            ("vbe-1", "vibe"),
            ("other", "unknown"),
        )

        with patch.dict(os.environ, {"HAPAX_DISPATCH_PROJECT_ROOT": str(root)}, clear=True):
            for role, platform in cases:
                assert _dispatch_worktree(role, platform) == dispatcher.lane_worktree(
                    role, platform
                )

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            for role, platform in cases:
                assert _dispatch_worktree(role, platform) == dispatcher.lane_worktree(
                    role, platform
                )

        with patch.dict(
            os.environ,
            {
                "HAPAX_DISPATCH_PROJECT_ROOT": str(root),
                "HAPAX_DISPATCH_WORKTREE": str(override),
            },
            clear=True,
        ):
            for role, platform in cases:
                assert _dispatch_worktree(role, platform) == dispatcher.lane_worktree(
                    role, platform
                )

    def test_dispatch_worktree_override_wins(self, tmp_path: Path):
        override = tmp_path / "custom-worktree"

        with patch.dict("os.environ", {"HAPAX_DISPATCH_WORKTREE": str(override)}, clear=False):
            assert _dispatch_worktree("cx-red", "codex") == override

    def test_dispatch_guard_markers_match_methodology_dispatcher(self):
        dispatcher = _dispatcher_module()

        assert tuple(_DISPATCH_CLAIM_GUARD_MARKERS) == tuple(
            dispatcher.DISPATCH_CLAIM_GUARD_MARKERS
        )
        assert tuple(_DISPATCH_CLOSE_GUARD_MARKERS) == tuple(
            dispatcher.DISPATCH_CLOSE_GUARD_MARKERS
        )

    def test_dispatch_tool_blocker_reports_missing_close_with_next_action(self, tmp_path: Path):
        worktree = tmp_path / "projects" / "hapax-council--beta"
        (worktree / "scripts").mkdir(parents=True)
        (worktree / "scripts" / "cc-claim").write_text(
            f"#!/bin/sh\n# {' '.join(_DISPATCH_CLAIM_GUARD_MARKERS)}\n",
            encoding="utf-8",
        )

        with patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}):
            blocker = _dispatch_tool_blocker("beta", "claude")

        assert blocker is not None
        assert "missing cc-close" in blocker
        assert "next_action=" in blocker
        assert str(worktree) in blocker

    def test_dispatch_tool_blocker_reports_stale_close_with_next_action(self, tmp_path: Path):
        worktree = tmp_path / "projects" / "hapax-council--beta"
        _stale_close_worktree(worktree)

        with patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}):
            blocker = _dispatch_tool_blocker("beta", "claude")

        assert blocker is not None
        assert "stale cc-close" in blocker
        assert "frontmatter_task_id" in blocker
        assert "next_action=" in blocker

    def test_dispatch_tool_blocker_reports_unreadable_claim_with_next_action(self, tmp_path: Path):
        worktree = tmp_path / "projects" / "hapax-council--beta"
        _guarded_worktree(worktree)
        claim = worktree / "scripts" / "cc-claim"

        def fake_read_guard(path: Path) -> str:
            if path == claim:
                raise OSError("permission denied")
            raise AssertionError(f"unexpected guard read: {path}")

        with (
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
            patch("agents.coordinator.core._read_dispatch_guard", side_effect=fake_read_guard),
        ):
            blocker = _dispatch_tool_blocker("beta", "claude")

        assert blocker is not None
        assert "unreadable cc-claim" in blocker
        assert "next_action=" in blocker

    def test_dispatch_tool_blocker_reports_unreadable_close_with_next_action(self, tmp_path: Path):
        worktree = tmp_path / "projects" / "hapax-council--beta"
        _guarded_worktree(worktree)
        close = worktree / "scripts" / "cc-close"

        def fake_read_guard(path: Path) -> str:
            if path == close:
                raise OSError("permission denied")
            if path == worktree / "scripts" / "cc-claim":
                return path.read_text(encoding="utf-8", errors="replace")
            raise AssertionError(f"unexpected guard read: {path}")

        with (
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
            patch("agents.coordinator.core._read_dispatch_guard", side_effect=fake_read_guard),
        ):
            blocker = _dispatch_tool_blocker("beta", "claude")

        assert blocker is not None
        assert "unreadable cc-close" in blocker
        assert "next_action=" in blocker

    def test_dispatch_tool_blocker_rejects_gemini_even_with_guarded_worktree(self, tmp_path: Path):
        worktree = tmp_path / "projects" / "hapax-council--gamma"
        _guarded_worktree(worktree)

        with patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}):
            blocker = _dispatch_tool_blocker("gamma", "gemini")

        assert blocker is not None
        assert "unsupported dispatch platform 'gemini'" in blocker
        assert "next_action=" in blocker

    def test_dispatch_tool_blocker_rejects_unsupported_platform_before_guard_reads(
        self,
        tmp_path: Path,
    ):
        with (
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
            patch.object(
                Path,
                "is_file",
                side_effect=AssertionError("unsupported platform should not inspect guard files"),
            ),
            patch(
                "agents.coordinator.core._read_dispatch_guard",
                side_effect=AssertionError("unsupported platform should not read guard files"),
            ),
        ):
            blocker = _dispatch_tool_blocker("gamma", "gemini")

        assert blocker is not None
        assert "unsupported dispatch platform 'gemini'" in blocker
        assert "supported coordinator headless platform" in blocker

    def test_dispatch_tool_blocker_allows_vibe_with_guarded_worktree(self, tmp_path: Path):
        worktree = tmp_path / "projects" / "hapax-council--vbe-1"
        _guarded_worktree(worktree)

        with patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}):
            blocker = _dispatch_tool_blocker("vbe-1", "vibe")

        assert blocker is None

    def test_dispatch_tool_blocker_rejects_antigrav_even_with_guarded_worktree(
        self,
        tmp_path: Path,
    ):
        worktree = tmp_path / "projects" / "hapax-council--antigrav"
        _guarded_worktree(worktree)

        with patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}):
            blocker = _dispatch_tool_blocker("antigravity", "antigrav")

        assert blocker is not None
        assert "unsupported dispatch platform 'antigrav'" in blocker
        assert "next_action=" in blocker
        assert "mint measured supply-leaf intake" in blocker

    @pytest.mark.parametrize("platform", ["agy", "antigravity", "gemini-cli"])
    def test_dispatch_tool_blocker_retired_aliases_keep_intake_next_action(
        self,
        tmp_path: Path,
        platform: str,
    ):
        with (
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
            patch(
                "agents.coordinator.core._read_dispatch_guard",
                side_effect=AssertionError("unsupported platform should not read guard files"),
            ),
        ):
            blocker = _dispatch_tool_blocker(platform, platform)

        assert blocker is not None
        assert f"unsupported dispatch platform '{platform}'" in blocker
        assert "mint measured supply-leaf intake" in blocker
        assert "add coordinator headless dispatch support" not in blocker


class TestParseTask:
    def test_valid_task(self, tmp_path: Path):
        task_file = tmp_path / "test-task.md"
        task_file.write_text(
            """---
task_id: test-task
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

    def test_rejects_filename_frontmatter_identity_mismatch(self, tmp_path: Path):
        task_file = tmp_path / "filename-id.md"
        task_file.write_text(
            """---
task_id: different-id
title: "Mismatched identity"
status: offered
assigned_to: unassigned
---
""",
            encoding="utf-8",
        )

        assert _parse_task(task_file) is None

    def test_nullable_or_invalid_wsjf_defaults_to_zero(self, tmp_path: Path):
        for value in ("null", "not-a-number", ".nan"):
            task_file = tmp_path / f"loose-wsjf-{value}.md"
            task_file.write_text(
                f"""---
task_id: loose-wsjf
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
task_id: nullable-fields
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
task_id: blocked
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
task_id: pr-open
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

    def test_malformed_route_metadata_fails_closed_not_base(self):
        """R5 scope-mask fail-close, through the REAL parser (no mock): declared-but-
        unparseable route metadata means the scope NEVER/ONLY mask cannot be read, so
        suitability must be () (held) — never the unconstrained base. This is the exact
        fixture the review flagged: assess_route_metadata does NOT raise on it — it returns
        status=MALFORMED with metadata=None — so the fail-close must key on status, and a
        test that mocks the parser to raise would green-light the live fail-open."""
        # No patch: the real assess_route_metadata classifies this as MALFORMED.
        platforms = _effective_platform_suitability(
            ["claude", "codex"],
            {"route_metadata_schema": 1, "route_constraints": "not-a-dict"},
        )
        assert platforms == ()

    def test_nested_route_metadata_malformed_mask_fails_closed(self):
        """A scope mask declared under the NESTED route_metadata mapping
        (route_metadata.route_constraints) that is unparseable must ALSO fail closed —
        a top-level-key-only guard missed this form (review finding). Mask presence is
        detected with the canonical route_metadata_payload_from_frontmatter extractor."""
        platforms = _effective_platform_suitability(
            ["claude", "codex"],
            {"route_metadata_schema": 1, "route_metadata": {"route_constraints": "not-a-dict"}},
        )
        assert platforms == ()

    def test_malformed_explicit_metadata_with_a_mask_fails_closed(self):
        """A declared explicit block whose OTHER fields are unparseable (invalid quality_floor)
        is MALFORMED — even though a route_constraints mask is present, it cannot be trusted,
        so suitability fails closed to () rather than reading a mask off untrusted metadata."""
        platforms = _effective_platform_suitability(
            ["claude", "codex"],
            {
                "route_metadata_schema": 1,
                "quality_floor": "not-a-real-floor",
                "authority_level": "authoritative",
                "mutation_surface": "source",
                "route_constraints": {"prohibited_platforms": ["codex"]},
            },
        )
        assert platforms == ()

    def test_no_route_metadata_keeps_base_suitability(self):
        """Absence of declared constraints (metadata is None) is NOT the same as
        cannot-determine: with no route_metadata the base suitability stands."""
        platforms = _effective_platform_suitability(["claude", "codex"], {})
        assert set(platforms) == {"claude", "codex"}

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
            patch("agents.coordinator.core.CACHE_DIR", tmp_path / "cache"),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
        ):
            state = _check_lane("test_lane")
        assert state.alive is False
        assert state.pid is None
        assert state.idle is True
        assert state.dispatch_ready is False
        assert state.dispatch_blocked_reason is not None
        assert "lane_not_alive" in state.dispatch_blocked_reason
        assert "next_action=" in state.dispatch_blocked_reason

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

    def test_refresh_dispatch_lane_rebuilds_from_current_discovery(self):
        original = LaneState(
            role="cx-red",
            session="hapax-codex-cx-red",
            platform="codex",
            alive=True,
            idle=True,
        )
        descriptor = LaneDescriptor(
            role="cx-red",
            session="hapax-codex-cx-red",
            platform="codex",
        )
        refreshed = LaneState(
            role="cx-red",
            session="hapax-codex-cx-red",
            platform="codex",
            alive=False,
            idle=True,
            dispatch_ready=False,
        )

        with (
            patch("agents.coordinator.core._discover_lanes", return_value=[descriptor]),
            patch("agents.coordinator.core._check_lane", return_value=refreshed) as check,
        ):
            assert _refresh_dispatch_lane(original) is refreshed

        check.assert_called_once_with(descriptor)

    def test_refresh_dispatch_lane_holds_on_session_replacement(self):
        original = LaneState(
            role="cx-red",
            session="hapax-codex-cx-red",
            platform="codex",
            generation="$1:100",
            alive=True,
            idle=True,
        )
        replacement = LaneDescriptor(
            role="cx-red",
            session="hapax-codex-cx-red",
            platform="codex",
            generation="$2:101",
        )

        with patch("agents.coordinator.core._discover_lanes", return_value=[replacement]):
            refreshed = _refresh_dispatch_lane(original)

        assert refreshed.alive is False
        assert refreshed.dispatch_ready is False
        assert refreshed.dispatch_blocked_reason == "lane_disappeared_before_dispatch"

    def test_refresh_dispatch_lane_holds_on_pid_replacement(self):
        original = LaneState(
            role="cx-red",
            session="",
            platform="codex",
            generation="pid:100",
            alive=True,
            pid=100,
            idle=True,
        )
        descriptor = LaneDescriptor(
            role="cx-red",
            session="",
            platform="codex",
            generation="pid:100",
        )
        replacement = LaneState(
            role="cx-red",
            session="",
            platform="codex",
            generation="pid:100",
            alive=True,
            pid=200,
            idle=True,
        )

        with (
            patch("agents.coordinator.core._discover_lanes", return_value=[descriptor]),
            patch("agents.coordinator.core._check_lane", return_value=replacement),
        ):
            refreshed = _refresh_dispatch_lane(original)

        assert refreshed.alive is False
        assert refreshed.dispatch_ready is False
        assert refreshed.dispatch_blocked_reason == "lane_process_replaced_before_dispatch"

    def test_dispatch_pickup_rejects_same_name_replacement_generation(self):
        lane = LaneState(
            role="cx-red",
            session="hapax-codex-cx-red",
            platform="codex",
            generation="$1:100",
            alive=True,
            idle=True,
        )
        replacement = LaneDescriptor(
            role="cx-red",
            session="hapax-codex-cx-red",
            platform="codex",
            generation="$2:101",
        )
        task = Task(
            task_id="task-1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=1,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="deterministic_ok",
            path=Path("/tmp/task-1.md"),
            source_sha256="a" * 64,
        )

        with patch("agents.coordinator.core._discover_lanes", return_value=[replacement]):
            assert _dispatch_landed(task, lane, "dispatch-message") is False

    def test_peer_status_fallback_marks_queue_dry_lane_idle(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        _guarded_worktree(tmp_path / "projects" / "hapax-council--cx-red")
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
            patch("agents.coordinator.core.CACHE_DIR", tmp_path / "cache"),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
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
        assert state.dispatch_ready is True
        assert state.relay_age_s != float("inf")

    def test_live_lane_without_worktree_is_not_dispatch_ready(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", tmp_path / "cache"),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="dev",
                    session="hapax-claude-dev",
                    platform="claude",
                )
            )

        assert state.alive is True
        assert state.idle is True
        assert state.dispatch_ready is False
        assert state.dispatch_blocked_reason is not None
        assert "missing cc-claim" in state.dispatch_blocked_reason
        assert "hapax-council--dev" in state.dispatch_blocked_reason

    def test_live_lane_with_guarded_worktree_is_dispatch_ready(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        _guarded_worktree(tmp_path / "projects" / "hapax-council--beta")

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", tmp_path / "cache"),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="beta",
                    session="hapax-claude-beta",
                    platform="claude",
                )
            )

        assert state.alive is True
        assert state.idle is True
        assert state.dispatch_ready is True
        assert state.dispatch_blocked_reason is None

    def test_live_lane_with_stale_worktree_is_not_dispatch_ready(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        _stale_worktree(tmp_path / "projects" / "hapax-council--beta")

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", tmp_path / "cache"),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="beta",
                    session="hapax-claude-beta",
                    platform="claude",
                )
            )

        assert state.alive is True
        assert state.idle is True
        assert state.dispatch_ready is False
        assert state.dispatch_blocked_reason is not None
        assert "stale cc-claim" in state.dispatch_blocked_reason
        assert "authority_case" in state.dispatch_blocked_reason

    def test_live_lane_with_stale_close_guard_is_not_dispatch_ready(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        _stale_close_worktree(tmp_path / "projects" / "hapax-council--beta")

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", tmp_path / "cache"),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="beta",
                    session="hapax-claude-beta",
                    platform="claude",
                )
            )

        assert state.alive is True
        assert state.idle is True
        assert state.dispatch_ready is False
        assert state.dispatch_blocked_reason is not None
        assert "stale cc-close" in state.dispatch_blocked_reason
        assert "frontmatter_task_id" in state.dispatch_blocked_reason

    def test_gemini_lane_with_guarded_worktree_is_not_dispatch_ready(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        _guarded_worktree(tmp_path / "projects" / "hapax-council--gamma")

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", tmp_path / "cache"),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="gamma",
                    session="hapax-gemini-gamma",
                    platform="gemini",
                )
            )

        assert state.alive is True
        assert state.idle is True
        assert state.dispatch_ready is False
        assert state.dispatch_blocked_reason is not None
        assert "unsupported dispatch platform 'gemini'" in state.dispatch_blocked_reason
        assert "supported coordinator headless platform" in state.dispatch_blocked_reason

    def test_antigrav_lane_with_guarded_worktree_is_not_dispatch_ready(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        _guarded_worktree(tmp_path / "projects" / "hapax-council--antigrav")

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", tmp_path / "cache"),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="antigravity",
                    session="hapax-antigrav-antigravity",
                    platform="antigrav",
                )
            )

        assert state.alive is True
        assert state.idle is True
        assert state.dispatch_ready is False
        assert state.dispatch_blocked_reason is not None
        assert "unsupported dispatch platform 'antigrav'" in state.dispatch_blocked_reason
        assert "mint measured supply-leaf intake" in state.dispatch_blocked_reason

    def test_relay_claim_beats_stale_active_claim_file(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        _guarded_worktree(tmp_path / "projects" / "hapax-council--cx-red")
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
            patch("agents.coordinator.core.CACHE_DIR", claim_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
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
        assert state.dispatchable is False

    def test_codex_wound_down_relay_is_not_dispatchable(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "cx-fugu-1.yaml").write_text(
            """session: cx-fugu-1
platform: codex
status: wind_down_idle
current_claim: null
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
                    role="cx-fugu-1",
                    session="hapax-codex-cx-fugu-1",
                    platform="codex",
                )
            )

        assert state.alive is True
        assert state.claimed_task is None
        assert state.idle is True
        assert state.dispatchable is False

    def test_claude_operator_pool_descriptor_is_not_dispatchable(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.PID_DIR", tmp_path / "pids"),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            state = _check_lane(
                LaneDescriptor(
                    role="dev2",
                    session="hapax-claude-dev2",
                    platform="claude",
                )
            )

        assert state.alive is True
        assert state.idle is True
        assert state.dispatchable is False
        assert _lane_to_dict(state)["dispatchable"] is False

    def test_retired_relay_status_variants_normalize_and_suppress_claim(self, tmp_path: Path):
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        statuses = (
            "retired",
            "retired-clean-exit",
            "idle_wound_down",
            "idle-wound-down-after-close",
            "wind_down_idle",
            "wind-down-idle-after-close",
            "wound_down",
            "wound-down-by-operator",
            "wind_down",
            "wind-down-after-retire",
            "winding_down",
            "winding_down-after-retire",
        )
        for index, status in enumerate(statuses):
            role = f"cx-retired-{index}"
            (relay_dir / f"{role}.yaml").write_text(
                f"""session: {role}
platform: codex
status: {status}
current_claim: stale-task-{index}
""",
                encoding="utf-8",
            )

        with (
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            for index, status in enumerate(statuses):
                role = f"cx-retired-{index}"
                state = _check_lane(
                    LaneDescriptor(
                        role=role,
                        session=f"hapax-codex-{role}",
                        platform="codex",
                    )
                )

                assert _relay_status_is_retired(status) is True
                assert state.alive is True
                assert state.claimed_task is None
                assert state.idle is True
                assert state.dispatchable is False

        assert _relay_status_is_retired("retiring") is False
        # SUPERSEDED/CLOSED are now retired (broad-9: the launcher is the refusal
        # surface; the coordinator previously under-refused these -> routed -> rc=6).
        assert _relay_status_is_retired("superseded-by-cx-blue") is True
        assert _relay_status_is_retired("closed-by-operator") is True

    def test_retired_relay_multidoc_latest_document_suppresses_claim(self, tmp_path: Path):
        role = "cx-multidoc-retired"
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / f"{role}.yaml").write_text(
            """status: active
current_claim: stale-task
---
status: retired
current_claim: stale-task
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
                    role=role,
                    session=f"hapax-codex-{role}",
                    platform="codex",
                )
            )

        assert state.alive is True
        assert state.claimed_task is None
        assert state.idle is True
        assert state.dispatchable is False

    def test_retired_relay_status_union_suppresses_claim(self, tmp_path: Path):
        role = "cx-relay-status-retired"
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / f"{role}.yaml").write_text(
            """status: active
relay_status: closed-by-operator
current_claim: stale-task
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
                    role=role,
                    session=f"hapax-codex-{role}",
                    platform="codex",
                )
            )

        assert state.alive is True
        assert state.claimed_task is None
        assert state.idle is False
        assert state.dispatchable is False

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
        _guarded_worktree(tmp_path / "projects" / "hapax-council")
        _guarded_worktree(tmp_path / "projects" / "hapax-council--cx-red")
        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout=("hapax-claude-alpha\t$1\t100\nhapax-codex-cx-red\t$2\t101\nwork\t$3\t102\n"),
            stderr="",
        )

        with (
            patch("agents.coordinator.core.PID_DIR", pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("agents.coordinator.core.CACHE_DIR", tmp_path / "cache"),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
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
        assert lanes["alpha"].generation == "$1:100"
        assert lanes["beta"].alive is False
        assert lanes["alpha"].platform == "claude"
        assert lanes["alpha"].dispatch_ready is True
        assert lanes["cx-red"].alive is True
        assert lanes["cx-red"].generation == "$2:101"
        assert lanes["cx-red"].platform == "codex"
        assert lanes["cx-red"].dispatch_ready is True

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
        assert gamma.generation == _pid_generation(os.getpid())
        assert lanes["gamma"].alive is True
        assert lanes["gamma"].pid == os.getpid()
        assert lanes["gamma"].pid_source == "pidfile"

    def test_codex_pid_backed_lane_requires_dispatch_binding_to_count_as_landed(
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

            assert _dispatch_landed(task, lanes[role], "mq-test") is False

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


class TestDispatchableLaneSelection:
    def test_tick_excludes_claude_dev_operator_pool_lanes(self):
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
        lanes = {
            "dev": LaneState(role="dev", platform="claude", alive=True, idle=True),
            "beta": LaneState(role="beta", platform="claude", alive=True, idle=True),
        }
        dispatched: list[tuple[str, str]] = []

        with (
            patch.object(Coordinator, "_scan_tasks", return_value=[task]),
            patch.object(Coordinator, "_check_lanes", return_value=lanes),
            patch.object(
                Coordinator,
                "_dispatch",
                side_effect=lambda t, lane: dispatched.append((t.task_id, lane.role)) or (True, ""),
            ),
            patch.object(Coordinator, "_write_state"),
            patch(
                "agents.coordinator.core.admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coordinator.tick()

        assert dispatched == [("t1", "beta")]

    def test_tick_does_not_dispatch_when_only_claude_dev_operator_pool_is_idle(self):
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
            path=Path("/tmp/t1.md"),
        )
        lanes = {
            "dev2": LaneState(role="dev2", platform="claude", alive=True, idle=True),
        }
        dispatched: list[tuple[str, str]] = []
        written: list[CoordinatorState] = []

        def capture_state(state: CoordinatorState, **_kwargs: object) -> None:
            written.append(state)

        with (
            patch.object(Coordinator, "_scan_tasks", return_value=[task]),
            patch.object(Coordinator, "_check_lanes", return_value=lanes),
            patch.object(
                Coordinator,
                "_dispatch",
                side_effect=lambda t, lane: dispatched.append((t.task_id, lane.role)) or (True, ""),
            ),
            patch.object(Coordinator, "_write_state", side_effect=capture_state),
            patch(
                "agents.coordinator.core.admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coordinator.tick()

        assert dispatched == []
        assert written[0].lanes_idle == 0
        assert written[0].lanes["dev2"]["dispatchable"] is False

    def test_tick_does_not_dispatch_retired_codex_relay_lane(self):
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
            path=Path("/tmp/t1.md"),
        )
        lanes = {
            "cx-fugu-1": LaneState(
                role="cx-fugu-1",
                platform="codex",
                alive=True,
                idle=True,
                dispatchable=False,
            ),
        }
        dispatched: list[tuple[str, str]] = []
        written: list[CoordinatorState] = []

        def capture_state(state: CoordinatorState, **_kwargs: object) -> None:
            written.append(state)

        with (
            patch.object(Coordinator, "_scan_tasks", return_value=[task]),
            patch.object(Coordinator, "_check_lanes", return_value=lanes),
            patch.object(
                Coordinator,
                "_dispatch",
                side_effect=lambda t, lane: dispatched.append((t.task_id, lane.role)) or (True, ""),
            ),
            patch.object(Coordinator, "_write_state", side_effect=capture_state),
            patch(
                "agents.coordinator.core.admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coordinator.tick()

        assert dispatched == []
        assert written[0].lanes_idle == 0
        assert written[0].lanes["cx-fugu-1"]["dispatchable"] is False

    def test_tick_excludes_wind_down_codex_relay_before_dispatch(self, tmp_path: Path):
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
            path=Path("/tmp/t1.md"),
        )
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        (relay_dir / "cx-fugu-1.yaml").write_text(
            """session: cx-fugu-1
platform: codex
status: wind_down
current_claim: null
""",
            encoding="utf-8",
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        dispatched: list[tuple[str, str]] = []
        written: list[CoordinatorState] = []

        def capture_state(state: CoordinatorState, **_kwargs: object) -> None:
            written.append(state)

        with (
            patch.object(Coordinator, "_scan_tasks", return_value=[task]),
            patch(
                "agents.coordinator.core._discover_lanes",
                return_value=[
                    LaneDescriptor(
                        role="cx-fugu-1",
                        session="hapax-codex-cx-fugu-1",
                        platform="codex",
                    )
                ],
            ),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.object(
                Coordinator,
                "_dispatch",
                side_effect=lambda t, lane: dispatched.append((t.task_id, lane.role)) or (True, ""),
            ),
            patch.object(Coordinator, "_write_state", side_effect=capture_state),
            patch(
                "agents.coordinator.core.admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coordinator.tick()

        assert dispatched == []
        assert written[0].lanes_alive == 1
        assert written[0].lanes_idle == 0
        assert written[0].lanes["cx-fugu-1"]["dispatchable"] is False


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
        task_path = tmp_path / "t1.md"
        task_path.write_text("task preimage\n", encoding="utf-8")
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="deterministic_ok",
            path=task_path,
            authority_case="CASE-TEST-001",
            parent_spec="/tmp/spec.md",
            source_sha256=hashlib.sha256(task_path.read_bytes()).hexdigest(),
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
            recipient = conn.execute(
                "SELECT state, reason FROM recipients WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        assert row is not None
        assert row[0] == "t1"
        assert row[1] == "CASE-TEST-001"
        assert row[2] == "cx-red"
        payload = json.loads(row[3])
        assert payload["task_id"] == "t1"
        assert payload["lane"] == "cx-red"
        assert payload["parent_spec"] == "/tmp/spec.md"
        assert payload["dispatch_binding"]["task_sha256"] == task.source_sha256
        assert "next_action_on_binding_failure" in payload
        assert recipient == ("deferred", "coordinator_prepared_pending_revalidation")

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
            patch.object(Coordinator, "_read_task_snapshot", return_value=([task], True)),
            patch("agents.coordinator.core._prepare_dispatch_message", return_value="mq-test-1"),
            patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
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
        assert run_kwargs[0]["env"]["HAPAX_DISPATCH_CLAIM_SWEEP"] == "0"
        assert run_kwargs[0]["env"]["HAPAX_CLAIM_LEASE_TTL_SECS"] == str(2**63 - 1)

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
            patch.object(Coordinator, "_read_task_snapshot", return_value=([task], True)),
            patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
            patch("agents.coordinator.core.DISPATCH_TIMEOUT_S", 30.0),
            patch("agents.coordinator.core.DISPATCH_TIMEOUT_LANDING_GRACE_S", 0.0),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
            patch("agents.coordinator.core._dispatch_landed", return_value=True),
        ):
            assert Coordinator()._dispatch(task, lane) == (True, "")

    def test_dispatch_landed_rejects_claim_cache_without_dispatch_sidecar(self, tmp_path: Path):
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
        ):
            assert _dispatch_landed(task, lane, "mq-test") is False
            (cache_dir / "cc-active-task-cx-red").write_text("p0-task\n", encoding="utf-8")
            assert _dispatch_landed(task, lane, "mq-test") is False

    def test_dispatch_landed_requires_exact_message_bound_claim_sidecar(self, tmp_path: Path):
        vault_root = tmp_path / "tasks"
        active = vault_root / "active"
        active.mkdir(parents=True)
        task_path = active / "task-1.md"
        task_path.write_text(
            "---\n"
            "task_id: task-1\n"
            "status: offered\n"
            "assigned_to: unassigned\n"
            "authority_case: CASE-1\n"
            "parent_spec: /tmp/spec.md\n"
            "---\n",
            encoding="utf-8",
        )
        task = Task(
            task_id="task-1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=1,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="deterministic_ok",
            path=task_path,
            authority_case="CASE-1",
            parent_spec="/tmp/spec.md",
            source_sha256=hashlib.sha256(task_path.read_bytes()).hexdigest(),
        )
        generation = _pid_generation(os.getpid())
        lane = LaneState(
            role="cx-red",
            platform="codex",
            generation=generation,
            alive=True,
            pid=os.getpid(),
            idle=True,
        )
        cache_dir = tmp_path / "cache"
        relay_dir = tmp_path / "relay-state"
        db_path = tmp_path / "relay" / "messages.db"
        cache_dir.mkdir()
        relay_dir.mkdir()

        with (
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.TASKS_DIR", active),
            patch.dict(os.environ, {"HAPAX_RELAY_MQ_DB": str(db_path)}),
        ):
            message_id = _prepare_dispatch_message(task, lane)
            assert message_id is not None
            with sqlite3.connect(db_path) as conn:
                binding_hash = json.loads(
                    conn.execute("SELECT payload FROM messages").fetchone()[0]
                )["dispatch_binding"]["binding_hash"]
            request = DispatchLaunchRequest(
                task_id=task.task_id,
                lane=lane.role,
                platform=lane.platform,
                mode="headless",
                profile="full",
                authority_case=task.authority_case or "",
                authority_item=task.task_id,
                parent_spec=task.parent_spec,
                message_id=message_id,
                mq_db_path=db_path,
                event_log=CoordEventLog(
                    db_path=tmp_path / "coord" / "ledger.db",
                    jsonl_path=tmp_path / "coord" / "ledger.jsonl",
                    spool_dir=tmp_path / "coord" / "spool",
                ),
                binding_hash=binding_hash,
            )
            key = request.effective_idempotency_key
            _accept_dispatch_message(request, idempotency_key=key)
            task_path.write_text(
                "---\n"
                "task_id: task-1\n"
                "status: claimed\n"
                "assigned_to: cx-red\n"
                "authority_case: CASE-1\n"
                "parent_spec: /tmp/spec.md\n"
                "---\n",
                encoding="utf-8",
            )
            epoch = 123
            (cache_dir / "cc-active-task-cx-red").write_text("task-1\n", encoding="utf-8")
            (cache_dir / "cc-claim-epoch-cx-red").write_text(f"{epoch} task-1\n", encoding="utf-8")
            write_claim_dispatch_binding(
                cache_dir,
                "cx-red",
                ClaimDispatchBinding.create(
                    task_id="task-1",
                    lane="cx-red",
                    session_id="",
                    claim_epoch=epoch,
                    dispatch_message_id=message_id,
                    platform="codex",
                    mode="headless",
                    profile="full",
                    authority_case="CASE-1",
                    binding_hash=binding_hash,
                    coord_dispatch_idempotency_key=key,
                ),
            )
            observed = LaneState(
                role="cx-red",
                platform="codex",
                generation=generation,
                alive=True,
                pid=os.getpid(),
                idle=False,
                claimed_task="task-1",
            )
            with (
                patch("agents.coordinator.core._refresh_dispatch_lane", return_value=observed),
                patch(
                    "agents.coordinator.core._lane_launcher_process_present",
                    return_value=True,
                ),
            ):
                assert _dispatch_landed(task, lane, message_id) is True

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
            patch.object(Coordinator, "_read_task_snapshot", return_value=([task], True)),
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
            patch.object(Coordinator, "_read_task_snapshot", return_value=([task], True)),
            patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
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
task_id: {name}
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

    def test_stale_claimed_p0_without_live_pickup_holds(self, tmp_path: Path):
        path = self._task_note(tmp_path)
        task = _parse_task(path)
        assert task is not None
        before = path.read_bytes()

        count = Coordinator()._reoffer_orphaned_claims([task], {}, now_wall=time.time())

        assert count == 0
        assert path.read_bytes() == before
        reparsed = _parse_task(path)
        assert reparsed is not None
        assert reparsed.status == "claimed"
        assert reparsed.assigned_to == "alpha"

    def test_stale_in_progress_p0_without_live_pickup_holds(self, tmp_path: Path):
        path = self._task_note(tmp_path, status="in_progress")
        task = _parse_task(path)
        assert task is not None
        before = path.read_bytes()

        count = Coordinator()._reoffer_orphaned_claims([task], {}, now_wall=time.time())

        assert count == 0
        assert path.read_bytes() == before
        reparsed = _parse_task(path)
        assert reparsed is not None
        assert reparsed.status == "in_progress"
        assert reparsed.assigned_to == "alpha"

    def test_orphan_reoffer_preserves_lane_claim_for_different_live_task(self, tmp_path: Path):
        path = self._task_note(tmp_path, assigned_to="delta")
        task = _parse_task(path)
        assert task is not None
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        active_claim = cache_dir / "cc-active-task-delta"
        active_claim.write_text("different-task\n", encoding="utf-8")
        lanes = {
            "delta": LaneState(
                role="delta",
                platform="claude",
                alive=True,
                idle=False,
                claimed_task="different-task",
            )
        }

        with patch("agents.coordinator.core.CACHE_DIR", cache_dir):
            count = Coordinator()._reoffer_orphaned_claims([task], lanes, now_wall=time.time())

        assert count == 0
        assert _parse_task(path).status == "claimed"  # type: ignore[union-attr]
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

    def test_tick_does_not_dispatch_to_missing_worktree_lane(self, tmp_path: Path):
        coord = Coordinator()
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("claude",),
            quality_floor="deterministic_ok",
            path=Path("/tmp/t1.md"),
        )
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        pid_dir = tmp_path / "pids"
        pid_dir.mkdir()
        codex_pid_dir = tmp_path / "codex-pids"
        codex_pid_dir.mkdir()
        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout="hapax-claude-dev\n",
            stderr="",
        )

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if cmd == ["tmux", "list-sessions", "-F", TMUX_DISCOVERY_FORMAT]:
                return completed
            raise AssertionError(f"unexpected dispatch subprocess call: {cmd!r}")

        with (
            patch.object(Coordinator, "_scan_tasks", return_value=[task]),
            patch.object(Coordinator, "_read_task_snapshot", return_value=([task], True)),
            patch.object(Coordinator, "_write_state") as write_state,
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.PID_DIR", pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
            patch(
                "agents.coordinator.core.admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coord.tick()

        state = write_state.call_args.args[0]
        assert state.offered_tasks == 1
        assert state.task_flow_counts["offered"] == 1
        assert state.lanes_idle == 0
        assert state.dispatches_this_tick == 0
        assert state.lanes["dev"]["alive"] is True
        assert state.lanes["dev"]["idle"] is True
        assert state.lanes["dev"]["dispatch_ready"] is False
        assert "missing cc-claim" in state.lanes["dev"]["dispatch_blocked_reason"]
        assert state.lanes["alpha"]["alive"] is False
        assert state.lanes["alpha"]["dispatch_ready"] is False
        assert "lane_not_alive" in state.lanes["alpha"]["dispatch_blocked_reason"]
        assert "start or relaunch lane 'alpha'" in state.lanes["alpha"]["dispatch_blocked_reason"]

    def test_tick_dispatches_to_guarded_ready_lane(self, tmp_path: Path):
        coord = Coordinator()
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("claude",),
            quality_floor="deterministic_ok",
            path=Path("/tmp/t1.md"),
        )
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        pid_dir = tmp_path / "pids"
        pid_dir.mkdir()
        codex_pid_dir = tmp_path / "codex-pids"
        codex_pid_dir.mkdir()
        _guarded_worktree(tmp_path / "projects" / "hapax-council--beta")
        # Scope: coordinator-side readiness, planning, and dispatch argv. The
        # dispatcher script's own guard behavior is covered in dispatcher tests.
        dispatcher = tmp_path / "hapax-methodology-dispatch"
        dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        dispatcher.chmod(0o755)
        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout="hapax-claude-beta\n",
            stderr="",
        )
        dispatch_calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if cmd == ["tmux", "list-sessions", "-F", TMUX_DISCOVERY_FORMAT]:
                return completed
            dispatch_calls.append(cmd)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch.object(Coordinator, "_scan_tasks", return_value=[task]),
            patch.object(Coordinator, "_read_task_snapshot", return_value=([task], True)),
            patch.object(Coordinator, "_write_state") as write_state,
            patch(
                "agents.coordinator.core._discover_lanes",
                return_value=[
                    LaneDescriptor(role="beta", session="hapax-claude-beta", platform="claude")
                ],
            ),
            patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.PID_DIR", pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
            patch(
                "agents.coordinator.core.admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coord.tick()

        state = write_state.call_args.args[0]
        assert state.offered_tasks == 1
        assert state.lanes_idle == 1
        assert state.dispatches_this_tick == 1
        assert state.lanes["beta"]["alive"] is True
        assert state.lanes["beta"]["dispatch_ready"] is True
        assert dispatch_calls == [
            [
                str(dispatcher),
                "--task",
                "t1",
                "--lane",
                "beta",
                "--platform",
                "claude",
                "--mode",
                "headless",
                "--launch",
            ]
        ]

    def test_tick_does_not_count_failed_dispatch_as_dispatched(self, tmp_path: Path):
        coord = Coordinator()
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("claude",),
            quality_floor="deterministic_ok",
            path=Path("/tmp/t1.md"),
        )
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        pid_dir = tmp_path / "pids"
        pid_dir.mkdir()
        codex_pid_dir = tmp_path / "codex-pids"
        codex_pid_dir.mkdir()
        _guarded_worktree(tmp_path / "projects" / "hapax-council--beta")
        dispatcher = tmp_path / "hapax-methodology-dispatch"
        dispatcher.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
        dispatcher.chmod(0o755)
        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout="hapax-claude-beta\n",
            stderr="",
        )
        dispatch_calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if cmd == ["tmux", "list-sessions", "-F", TMUX_DISCOVERY_FORMAT]:
                return completed
            dispatch_calls.append(cmd)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=42,
                stdout="",
                stderr="BLOCKED: test refusal",
            )

        with (
            patch.object(Coordinator, "_scan_tasks", return_value=[task]),
            patch.object(Coordinator, "_read_task_snapshot", return_value=([task], True)),
            patch.object(Coordinator, "_write_state") as write_state,
            patch(
                "agents.coordinator.core._discover_lanes",
                return_value=[
                    LaneDescriptor(role="beta", session="hapax-claude-beta", platform="claude")
                ],
            ),
            patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.PID_DIR", pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
            patch(
                "agents.coordinator.core.admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coord.tick()

        state = write_state.call_args.args[0]
        assert state.offered_tasks == 1
        assert state.lanes_idle == 1
        assert state.dispatches_this_tick == 0
        assert state.lanes["beta"]["dispatch_ready"] is True
        assert len(dispatch_calls) == 1

    def test_tick_does_not_dispatch_to_stale_claim_lane(self, tmp_path: Path):
        coord = Coordinator()
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("claude",),
            quality_floor="deterministic_ok",
            path=Path("/tmp/t1.md"),
        )
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        pid_dir = tmp_path / "pids"
        pid_dir.mkdir()
        codex_pid_dir = tmp_path / "codex-pids"
        codex_pid_dir.mkdir()
        _stale_claim_worktree(tmp_path / "projects" / "hapax-council--dev")
        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout="hapax-claude-dev\n",
            stderr="",
        )

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if cmd == ["tmux", "list-sessions", "-F", TMUX_DISCOVERY_FORMAT]:
                return completed
            raise AssertionError(f"unexpected dispatch subprocess call: {cmd!r}")

        with (
            patch.object(Coordinator, "_scan_tasks", return_value=[task]),
            patch.object(Coordinator, "_write_state") as write_state,
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.PID_DIR", pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
            patch(
                "agents.coordinator.core.admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coord.tick()

        state = write_state.call_args.args[0]
        assert state.offered_tasks == 1
        assert state.task_flow_counts["offered"] == 1
        assert state.lanes_idle == 0
        assert state.dispatches_this_tick == 0
        assert state.lanes["dev"]["alive"] is True
        assert state.lanes["dev"]["idle"] is True
        assert state.lanes["dev"]["dispatch_ready"] is False
        assert "stale cc-claim" in state.lanes["dev"]["dispatch_blocked_reason"]
        assert "authority_case" in state.lanes["dev"]["dispatch_blocked_reason"]

    def test_tick_does_not_dispatch_to_stale_close_lane(self, tmp_path: Path):
        coord = Coordinator()
        task = Task(
            task_id="t1",
            title="test",
            status="offered",
            assigned_to="unassigned",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("claude",),
            quality_floor="deterministic_ok",
            path=Path("/tmp/t1.md"),
        )
        relay_dir = tmp_path / "relay"
        relay_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        pid_dir = tmp_path / "pids"
        pid_dir.mkdir()
        codex_pid_dir = tmp_path / "codex-pids"
        codex_pid_dir.mkdir()
        _stale_close_worktree(tmp_path / "projects" / "hapax-council--dev")
        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout="hapax-claude-dev\n",
            stderr="",
        )

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if cmd == ["tmux", "list-sessions", "-F", TMUX_DISCOVERY_FORMAT]:
                return completed
            raise AssertionError(f"unexpected dispatch subprocess call: {cmd!r}")

        with (
            patch.object(Coordinator, "_scan_tasks", return_value=[task]),
            patch.object(Coordinator, "_write_state") as write_state,
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.PID_DIR", pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")}),
            patch(
                "agents.coordinator.core.admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coord.tick()

        state = write_state.call_args.args[0]
        assert state.offered_tasks == 1
        assert state.task_flow_counts["offered"] == 1
        assert state.lanes_idle == 0
        assert state.dispatches_this_tick == 0
        assert state.lanes["dev"]["alive"] is True
        assert state.lanes["dev"]["idle"] is True
        assert state.lanes["dev"]["dispatch_ready"] is False
        assert "stale cc-close" in state.lanes["dev"]["dispatch_blocked_reason"]
        assert "frontmatter_task_id" in state.lanes["dev"]["dispatch_blocked_reason"]


class TestScanTasks:
    def test_scan_empty_dir(self, tmp_path: Path):
        coordinator = Coordinator()
        with patch("agents.coordinator.core.TASKS_DIR", tmp_path):
            tasks = coordinator._scan_tasks()
        assert tasks == []

    def test_scan_with_tasks(self, tmp_path: Path):
        (tmp_path / "high-priority.md").write_text(
            """---
task_id: high-priority
title: "High priority"
status: offered
assigned_to: unassigned
wsjf: 20.0
---
"""
        )
        (tmp_path / "low-priority.md").write_text(
            """---
task_id: low-priority
title: "Low priority"
status: offered
assigned_to: unassigned
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


def test_automatic_stalled_escalation_refuses_without_mutation(tmp_path: Path):
    coord = Coordinator()
    lane = LaneState(role="delta", alive=True, pid=111, pid_source="pidfile", claimed_task="x")
    task = tmp_path / "t.md"
    body = "---\nstatus: claimed\nassigned_to: delta\n---\nbody\n"
    task.write_text(body, encoding="utf-8")

    with patch("agents.coordinator.core.send_notification") as notify:
        assert (
            coord._escalate_stalled(lane, "p0-incident-demo-20260617", task, task.read_text())
            is False
        )

    assert task.read_text(encoding="utf-8") == body
    notify.assert_not_called()
