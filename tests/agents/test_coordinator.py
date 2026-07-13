"""Tests for the coordination daemon."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from agents.coordinator.core import (
    _DISPATCH_CLAIM_GUARD_MARKERS,
    _DISPATCH_CLOSE_GUARD_MARKERS,
    TMUX_EXECUTABLE,
    Coordinator,
    CoordinatorState,
    DispatchDisposition,
    LaneDescriptor,
    LaneState,
    MethodologyDispatchResult,
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
    _parse_methodology_dispatch_carrier,
    _parse_task,
    _reconcile_task_canon_echo,
    _relay_status_is_retired,
    _task_flow_counts,
)
from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter
from shared.methodology_dispatch_carrier import (
    build_dispatch_support_fact,
    canonical_dispatch_carrier_bytes,
    seal_methodology_dispatch_carrier,
)
from shared.relay_mq import (
    CanonEchoError,
    CanonEchoReconciliation,
    MessageFilters,
    ack_message,
    consume_messages,
    list_messages,
    load_latest_dispatch_echo_expectation,
    send_message,
)
from shared.relay_mq_envelope import Envelope
from shared.sdlc_pressure_gate import AdmissionDecision
from shared.sdlc_task_store import ClaimDispatchBinding, resolve_task_note

REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCHER_SCRIPT = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"
TMUX_LIST_COMMAND = [
    str(TMUX_EXECUTABLE),
    "-f",
    "/dev/null",
    "list-sessions",
    "-F",
    "#{session_name}",
]


def test_daemon_boot_is_support_only_and_never_drains_spool() -> None:
    source = (REPO_ROOT / "agents/coordinator/__main__.py").read_text(encoding="utf-8")

    assert ".replay(fail_open=True)" in source
    assert "support_only=true effects=0" in source
    assert ".boot_reconcile(" not in source
    assert ".ingest_spool(" not in source
    assert ".append(" not in source
    assert ".unlink(" not in source
    assert "Gemini-backed" not in source


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


def _dispatch_carrier_stdout(
    *,
    task_id: str = "t1",
    lane: str = "cx-red",
    platform: str = "codex",
    mode: str = "headless",
    profile: str = "full",
    effect_state: str = "held_not_admitted",
    materialization_state: str = "not_materialized",
    may_authorize: bool = False,
    receipt_is_admission: bool = False,
    reason: str | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "event": "methodology_dispatch",
        "task_id": task_id,
        "lane": lane,
        "platform": platform,
        "mode": mode,
        "profile": profile,
        "requested_operation": "launch",
        "launched": False,
        "may_authorize": False,
        "receipt_is_admission": False,
    }
    if reason is not None:
        payload["support"] = [
            build_dispatch_support_fact(
                kind="diagnostic",
                code="validation.reason",
                value=reason,
            )
        ]
    carrier = seal_methodology_dispatch_carrier(payload)
    hostile_overrides = {
        "effect_state": effect_state,
        "materialization_state": materialization_state,
        "may_authorize": may_authorize,
        "receipt_is_admission": receipt_is_admission,
    }
    if any(carrier[field] != value for field, value in hostile_overrides.items()):
        body = {
            key: value
            for key, value in carrier.items()
            if key not in {"carrier_hash", "carrier_ref"}
        }
        body.update(hostile_overrides)
        digest = hashlib.sha256(canonical_dispatch_carrier_bytes(body)).hexdigest()
        carrier = {
            **body,
            "carrier_hash": digest,
            "carrier_ref": f"methodology-dispatch-carrier@sha256:{digest}",
        }
    return canonical_dispatch_carrier_bytes(carrier) + b"\n"


def _echo_dispatch_record(source_message_id: str) -> dict:
    canon = {
        "canon_hash": "a" * 64,
        "canon_version": 1,
        "image_hash": "b" * 64,
        "level": "pi0",
        "payload_sha256": hashlib.sha256(b"exact canon payload").hexdigest(),
        "stage_token": "S6",
    }
    position_body = {
        "authority_case": "CASE-ECHO-001",
        "declared_task_constraint_digest": "c" * 64,
        "effective_constraint_state": "unresolved_scope_chain",
        "lane": "cx-red",
        "legal_successors": ["S7", "BLOCKED"],
        "stage_token": "S6",
        "task_id": "task-echo",
    }
    position_hash = _canonical_hash(position_body)
    position = {
        **position_body,
        "position_hash": position_hash,
        "position_ref": f"dispatch-position@sha256:{position_hash}",
    }
    binding_body = {
        "advisory_carriage": True,
        "canon": canon,
        "may_authorize": False,
        "position": position,
        "receipt_is_admission": False,
        "schema": "hapax.dispatch-canon-binding.v1",
    }
    binding_hash = _canonical_hash(binding_body)
    binding = {
        **binding_body,
        "binding_hash": binding_hash,
        "binding_ref": f"dispatch-canon-binding@sha256:{binding_hash}",
    }
    return {
        "event": "methodology_dispatch",
        "ok": True,
        "launched": True,
        "launch_returncode": 0,
        "launch_eligible": True,
        "durable_mq_dispatch_bound": True,
        "durable_mq_message_id": source_message_id,
        "may_authorize": False,
        "receipt_is_admission": False,
        "canon_binding": binding,
        "canon_binding_hash": binding_hash,
        "canon_binding_ref": binding["binding_ref"],
        "dispatch_position_hash": position_hash,
        "dispatch_position_ref": position["position_ref"],
    }


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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
            patch(
                "agents.coordinator.core._read_dispatch_guard",
                side_effect=fake_read_guard,
            ),
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
            patch(
                "agents.coordinator.core._read_dispatch_guard",
                side_effect=fake_read_guard,
            ),
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            {
                "route_metadata_schema": 1,
                "route_metadata": {"route_constraints": "not-a-dict"},
            },
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            role="beta",
            alive=True,
            pid=12345,
            pid_source="pidfile",
            claimed_task="fix-bug",
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
            stdout="hapax-claude-alpha\nhapax-codex-cx-red\nwork\n",
            stderr="",
        )

        with (
            patch("agents.coordinator.core.PID_DIR", pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("agents.coordinator.core.CACHE_DIR", tmp_path / "cache"),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
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
        assert lanes["alpha"].dispatch_ready is True
        assert lanes["cx-red"].alive is True
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
    def test_tick_holds_before_scan_when_claim_inspection_is_unresolved(self) -> None:
        coordinator = Coordinator()
        unresolved = SimpleNamespace(
            disposition="hold",
            publication_id="claim-publication-unresolved",
            reason_code="claim_publication_reconciliation_required",
        )
        lifecycle = SimpleNamespace(estate_complete=True, reason_codes=())

        with (
            patch.dict(os.environ, {"HAPAX_CANON_ECHO_ENFORCEMENT": "1"}),
            patch(
                "agents.coordinator.core.capture_coord_replay_snapshot",
                return_value=object(),
            ),
            patch(
                "agents.coordinator.core.inspect_lifecycle_transactions",
                return_value=lifecycle,
            ),
            patch(
                "agents.coordinator.core.inspect_claim_publications",
                return_value=[unresolved],
            ),
            patch.object(coordinator, "_scan_tasks") as scan_tasks,
        ):
            coordinator.tick()

        scan_tasks.assert_not_called()

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
            path=Path("/tmp/t1.md"),
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
                side_effect=lambda t, lane: (
                    dispatched.append((t.task_id, lane.role))
                    or MethodologyDispatchResult(
                        DispatchDisposition.HELD_CANDIDATE,
                        "methodology_candidate_held_not_admitted",
                    )
                ),
            ),
            patch.object(Coordinator, "_write_state"),
            patch(
                "agents.coordinator.core.observe_admission_state",
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
                "agents.coordinator.core.observe_admission_state",
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
                "agents.coordinator.core.observe_admission_state",
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
                "agents.coordinator.core.observe_admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coordinator.tick()

        assert dispatched == []
        assert written[0].lanes_alive == 1
        assert written[0].lanes_idle == 0
        assert written[0].lanes["cx-fugu-1"]["dispatchable"] is False


class TestDispatch:
    def test_methodology_dispatcher_ignores_environment_override(self, tmp_path: Path):
        override = tmp_path / "hapax-methodology-dispatch"
        expected = Path(__file__).resolve().parents[2] / "scripts" / "hapax-methodology-dispatch"

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

        assert result.stdout.strip() == str(expected)

    def test_dispatch_uses_methodology_without_pre_admission_mq(self, tmp_path: Path):
        dispatcher = tmp_path / "projects/hapax-council/scripts/hapax-methodology-dispatch"
        dispatcher.parent.mkdir(parents=True)
        dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        dispatcher.chmod(0o755)
        interpreter = tmp_path / "projects/hapax-council/.venv/bin/python"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text("pinned interpreter fixture\n", encoding="utf-8")
        interpreter.chmod(0o755)
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
            return subprocess.CompletedProcess(cmd, 0, _dispatch_carrier_stdout(), b"")

        with (
            patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
            patch("agents.coordinator.core.METHODOLOGY_PYTHON", interpreter),
            patch("agents.coordinator.core.DISPATCH_TIMEOUT_S", 42.0),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
            patch("shared.relay_mq.send_message") as send_mq,
            patch.dict(
                os.environ,
                {
                    "PATH": "/tmp/hostile-path",
                    "PYTHONPATH": "/tmp/hostile-pythonpath",
                    "PYTHONHOME": "/tmp/hostile-pythonhome",
                },
            ),
        ):
            result = Coordinator()._dispatch(task, lane)

        assert result.disposition is DispatchDisposition.HELD_CANDIDATE
        assert not hasattr(result, "materialized")
        send_mq.assert_not_called()
        assert calls == [
            [
                str(interpreter),
                "-I",
                str(dispatcher),
                "--task",
                "t1",
                "--lane",
                "cx-red",
                "--platform",
                "codex",
                "--mode",
                "headless",
                "--profile",
                "full",
                "--launch",
            ]
        ]
        assert "--mq-message-id" not in calls[0]
        assert run_kwargs[0]["timeout"] == 42.0
        child_env = run_kwargs[0]["env"]
        assert isinstance(child_env, dict)
        assert "PYTHONPATH" not in child_env
        assert "PYTHONHOME" not in child_env

    def test_dispatch_timeout_with_live_pickup_is_indeterminate(self, tmp_path: Path):
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
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
            patch("agents.coordinator.core._dispatch_landed", return_value=True) as landed,
        ):
            result = Coordinator()._dispatch(task, lane)

        assert result.disposition is DispatchDisposition.INDETERMINATE
        assert not hasattr(result, "materialized")
        landed.assert_called_once_with(task, lane)

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
            patch(
                "agents.coordinator.core._lane_launcher_process_present",
                return_value=True,
            ),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            assert _dispatch_landed(task, lane) is False
            (cache_dir / "cc-active-task-cx-red").write_text("p0-task\n", encoding="utf-8")
            assert _dispatch_landed(task, lane) is True

    def test_carrier_hash_tamper_fails_closed(self):
        carrier = json.loads(_dispatch_carrier_stdout())
        carrier["effect_state"] = "admitted"
        carrier["materialization_state"] = "materialized"
        carrier["may_authorize"] = True
        carrier["receipt_is_admission"] = True

        result = _parse_methodology_dispatch_carrier(
            canonical_dispatch_carrier_bytes(carrier) + b"\n",
            task_id="t1",
            lane="cx-red",
            platform="codex",
            mode="headless",
            profile="full",
        )

        assert result.disposition is DispatchDisposition.INDETERMINATE
        assert result.reason == "dispatch_carrier_hash_mismatch"

    @pytest.mark.parametrize("stdout", [b"", b"not json\n", b"{}\n", b"{broken\n"])
    def test_malformed_or_absent_carrier_is_indeterminate(self, stdout: bytes):
        result = _parse_methodology_dispatch_carrier(
            stdout,
            task_id="t1",
            lane="cx-red",
            platform="codex",
            mode="headless",
            profile="full",
        )

        assert result.disposition is DispatchDisposition.INDETERMINATE
        assert not hasattr(result, "materialized")

    def test_duplicate_carriers_are_indeterminate(self):
        carrier = _dispatch_carrier_stdout()

        result = _parse_methodology_dispatch_carrier(
            carrier + carrier,
            task_id="t1",
            lane="cx-red",
            platform="codex",
            mode="headless",
            profile="full",
        )

        assert result.disposition is DispatchDisposition.INDETERMINATE
        assert result.reason == "dispatch_carrier_raw_line_invalid"

    def test_authorizing_carrier_states_are_indeterminate(self):
        refused = _parse_methodology_dispatch_carrier(
            _dispatch_carrier_stdout(effect_state="refused", reason="policy_refused"),
            task_id="t1",
            lane="cx-red",
            platform="codex",
            mode="headless",
            profile="full",
        )
        materialized = _parse_methodology_dispatch_carrier(
            _dispatch_carrier_stdout(
                effect_state="admitted",
                materialization_state="materialized",
                may_authorize=True,
                receipt_is_admission=True,
            ),
            task_id="t1",
            lane="cx-red",
            platform="codex",
            mode="headless",
            profile="full",
        )

        assert refused.disposition is DispatchDisposition.INDETERMINATE
        assert refused.reason == "dispatch_carrier_gate0a_invariant_invalid"
        assert materialized.disposition is DispatchDisposition.INDETERMINATE
        assert materialized.reason == "dispatch_carrier_gate0a_invariant_invalid"
        assert not hasattr(materialized, "materialized")


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

    def test_stale_claimed_p0_without_live_pickup_holds(self, tmp_path: Path):
        path = self._task_note(tmp_path)
        before = path.read_bytes()
        task = _parse_task(path)
        assert task is not None
        ledger = tmp_path / "authority-case-ledger.jsonl"

        with patch("agents.coordinator.core.REOFFER_LEDGER", ledger):
            count = Coordinator()._reoffer_orphaned_claims([task], {}, now_wall=time.time())

        assert count == 0
        assert path.read_bytes() == before
        assert not ledger.exists()

    def test_stale_in_progress_p0_without_live_pickup_holds(self, tmp_path: Path):
        path = self._task_note(tmp_path, status="in_progress")
        before = path.read_bytes()
        task = _parse_task(path)
        assert task is not None
        ledger = tmp_path / "authority-case-ledger.jsonl"

        with patch("agents.coordinator.core.REOFFER_LEDGER", ledger):
            count = Coordinator()._reoffer_orphaned_claims([task], {}, now_wall=time.time())

        assert count == 0
        assert path.read_bytes() == before
        assert not ledger.exists()

    def test_canon_enforcement_holds_orphan_reoffer_without_mutation(self, tmp_path: Path) -> None:
        path = self._task_note(tmp_path)
        before = path.read_bytes()
        task = _parse_task(path)
        assert task is not None
        ledger = tmp_path / "authority-case-ledger.jsonl"

        with (
            patch.dict(os.environ, {"HAPAX_CANON_ECHO_ENFORCEMENT": "1"}),
            patch("agents.coordinator.core.REOFFER_LEDGER", ledger),
        ):
            count = Coordinator()._reoffer_orphaned_claims([task], {}, now_wall=time.time())

        assert count == 0
        assert path.read_bytes() == before
        assert not ledger.exists()

    def test_canon_enforcement_holds_stalled_reoffer_without_mutation(self, tmp_path: Path) -> None:
        path = self._task_note(tmp_path)
        before = path.read_bytes()
        lane = LaneState(
            role="alpha",
            claimed_task="p0-orphan",
            stalled=True,
            output_age_s=3600.0,
        )
        cache = tmp_path / "cache"
        cache.mkdir()

        with (
            patch.dict(os.environ, {"HAPAX_CANON_ECHO_ENFORCEMENT": "1"}),
            patch("agents.coordinator.core.CACHE_DIR", cache),
        ):
            assert Coordinator()._reoffer_stalled(lane) is False

        assert path.read_bytes() == before

    def test_orphan_hold_preserves_lane_claim_and_task_for_different_live_task(
        self, tmp_path: Path
    ):
        path = self._task_note(tmp_path, assigned_to="delta")
        before = path.read_bytes()
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

        assert count == 0
        assert path.read_bytes() == before
        assert active_claim.read_text(encoding="utf-8") == "different-task\n"
        assert not ledger.exists()

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
            if cmd == TMUX_LIST_COMMAND:
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
            patch(
                "agents.coordinator.core.observe_admission_state",
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

    def test_tick_requests_carrier_without_counting_materialization(self, tmp_path: Path):
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
        interpreter = tmp_path / ".venv/bin/python"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text("pinned interpreter fixture\n", encoding="utf-8")
        interpreter.chmod(0o755)
        completed = subprocess.CompletedProcess(
            args=["tmux"],
            returncode=0,
            stdout="hapax-claude-beta\n",
            stderr="",
        )
        dispatch_calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if cmd == TMUX_LIST_COMMAND:
                return completed
            dispatch_calls.append(cmd)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=_dispatch_carrier_stdout(
                    task_id="t1",
                    lane="beta",
                    platform="claude",
                ),
                stderr=b"",
            )

        with (
            patch.object(Coordinator, "_scan_tasks", return_value=[task]),
            patch.object(Coordinator, "_write_state") as write_state,
            patch(
                "agents.coordinator.core._discover_lanes",
                return_value=[
                    LaneDescriptor(role="beta", session="hapax-claude-beta", platform="claude")
                ],
            ),
            patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
            patch("agents.coordinator.core.METHODOLOGY_PYTHON", interpreter),
            patch("agents.coordinator.core.RELAY_DIR", relay_dir),
            patch("agents.coordinator.core.CACHE_DIR", cache_dir),
            patch("agents.coordinator.core.PID_DIR", pid_dir),
            patch("agents.coordinator.core.CODEX_PID_DIR", codex_pid_dir),
            patch("agents.coordinator.core._live_headless_launcher", return_value=None),
            patch("agents.coordinator.core.subprocess.run", side_effect=fake_run),
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
            patch(
                "agents.coordinator.core.observe_admission_state",
                return_value=AdmissionDecision(state="open"),
            ),
        ):
            coord.tick()

        state = write_state.call_args.args[0]
        assert state.offered_tasks == 1
        assert state.lanes_idle == 1
        assert state.dispatches_this_tick == 0
        assert state.lanes["beta"]["alive"] is True
        assert state.lanes["beta"]["dispatch_ready"] is True
        assert dispatch_calls == [
            [
                str(interpreter),
                "-I",
                str(dispatcher),
                "--task",
                "t1",
                "--lane",
                "beta",
                "--platform",
                "claude",
                "--mode",
                "headless",
                "--profile",
                "full",
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
            if cmd == TMUX_LIST_COMMAND:
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
            patch(
                "agents.coordinator.core.observe_admission_state",
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
            if cmd == TMUX_LIST_COMMAND:
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
            patch(
                "agents.coordinator.core.observe_admission_state",
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
            if cmd == TMUX_LIST_COMMAND:
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
            patch.dict(
                "os.environ",
                {"HAPAX_DISPATCH_PROJECT_ROOT": str(tmp_path / "projects")},
            ),
            patch(
                "agents.coordinator.core.observe_admission_state",
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
        active = tmp_path / "active"
        active.mkdir()
        coordinator = Coordinator()
        with patch("agents.coordinator.core.TASKS_DIR", active):
            tasks = coordinator._scan_tasks()
        assert tasks == []
        assert coordinator._task_store_observation["disposition"] == "current"

    def test_scan_with_tasks(self, tmp_path: Path):
        active = tmp_path / "active"
        active.mkdir()
        (active / "high-priority.md").write_text(
            """---
task_id: high-priority
title: "High priority"
status: offered
wsjf: 20.0
---
"""
        )
        (active / "low-priority.md").write_text(
            """---
task_id: low-priority
title: "Low priority"
status: offered
wsjf: 5.0
---
"""
        )
        coordinator = Coordinator()
        with patch("agents.coordinator.core.TASKS_DIR", active):
            tasks = coordinator._scan_tasks()
        assert len(tasks) == 2
        ids = {t.task_id for t in tasks}
        assert "high-priority" in ids
        assert "low-priority" in ids
        assert coordinator._task_store_observation["disposition"] == "current"
        assert coordinator._task_store_observation["candidate_count"] == 2

    def test_scan_holds_entire_candidate_set_on_duplicate_identity(self, tmp_path: Path):
        active = tmp_path / "active"
        active.mkdir()
        for name in ("task-a.md", "legacy-name.md"):
            (active / name).write_text(
                """---
task_id: task-a
title: Duplicate
status: offered
---
"""
            )
        coordinator = Coordinator()

        with patch("agents.coordinator.core.TASKS_DIR", active):
            tasks = coordinator._scan_tasks()

        assert tasks == []
        assert coordinator._task_store_observation["disposition"] == "hold"
        assert coordinator._task_store_observation["duplicate_task_ids"] == ["task-a"]
        assert coordinator._task_store_observation["candidate_count"] == 0

    def test_scan_holds_one_tick_then_rebuilds_a_changed_frontier(self, tmp_path: Path):
        active = tmp_path / "active"
        active.mkdir()
        task_path = active / "task-a.md"
        task_path.write_text(
            """---
task_id: task-a
title: Current
status: offered
---
"""
        )
        coordinator = Coordinator()
        with patch("agents.coordinator.core.TASKS_DIR", active):
            assert [task.task_id for task in coordinator._scan_tasks()] == ["task-a"]
            initial_frontier = coordinator._task_identity_index.frontier_hash
            task_path.write_text(task_path.read_text() + "\nchanged\n")

            assert coordinator._scan_tasks() == []
            first_hold = dict(coordinator._task_store_observation)
            rebuilt = coordinator._scan_tasks()

        assert first_hold["reason_code"] == "task_store_frontier_changed_since_index"
        assert "active/task-a.md" in first_hold["evidence_refs"][0]
        assert first_hold["candidate_count"] == 0
        assert [task.task_id for task in rebuilt] == ["task-a"]
        assert coordinator._task_store_observation["disposition"] == "current"
        assert coordinator._task_identity_index.frontier_hash != initial_frontier

    def test_scan_holds_if_task_bytes_change_during_parse(self, tmp_path: Path):
        active = tmp_path / "active"
        active.mkdir()
        task_path = active / "task-a.md"
        task_path.write_text(
            """---
task_id: task-a
title: Current
status: offered
---
"""
        )
        coordinator = Coordinator()
        original_parse = _parse_task

        def parse_then_mutate(path: Path):
            task = original_parse(path)
            path.write_text(path.read_text().replace("status: offered", "status: claimed"))
            return task

        with (
            patch("agents.coordinator.core.TASKS_DIR", active),
            patch("agents.coordinator.core._parse_task", side_effect=parse_then_mutate),
        ):
            assert coordinator._scan_tasks() == []

        observation = coordinator._task_store_observation
        assert observation["disposition"] == "hold"
        assert observation["reason_code"] == "task_store_frontier_changed_since_index"
        assert observation["candidate_count"] == 0
        assert observation["frontier_ref"].startswith(
            "task-identity-index-frontier@sha256:"
        )

    def test_scan_holds_on_unbound_artifact(self, tmp_path: Path):
        active = tmp_path / "active"
        active.mkdir()
        (active / "legacy.md").write_text(
            """---
title: Missing identity
status: offered
---
"""
        )
        coordinator = Coordinator()

        with patch("agents.coordinator.core.TASKS_DIR", active):
            assert coordinator._scan_tasks() == []

        observation = coordinator._task_store_observation
        assert observation["disposition"] == "hold"
        assert observation["unbound_refs"] == ["active/legacy.md"]
        assert len(observation["blocking_unbound_refs"]) == 1
        assert observation["blocking_unbound_refs"][0].startswith(
            "task-artifact:active/legacy.md@content:"
        )
        assert observation["legacy_snapshots"] == []
        assert observation["candidate_count"] == 0

    def test_scan_preserves_terminal_legacy_snapshot_without_holding_candidates(
        self, tmp_path: Path
    ):
        active = tmp_path / "active"
        closed = tmp_path / "closed"
        active.mkdir()
        closed.mkdir()
        (active / "task-a.md").write_text(
            """---
task_id: task-a
title: Current
status: offered
---
"""
        )
        (closed / "legacy-record.md").write_text(
            """---
type: cc-task
title: Historical task without canonical identity
status: done
---
"""
        )
        coordinator = Coordinator()

        with patch("agents.coordinator.core.TASKS_DIR", active):
            assert [task.task_id for task in coordinator._scan_tasks()] == ["task-a"]

        observation = coordinator._task_store_observation
        assert observation["disposition"] == "current"
        assert observation["reason_code"] is None
        assert observation["unbound_refs"] == []
        assert observation["blocking_unbound_refs"] == []
        assert observation["candidate_count"] == 1
        assert observation["assessment_ref"].startswith(
            "task-store-assessment@sha256:"
        )
        assert observation["legacy_snapshots"] == [
            {
                "authority_ceiling": "support_non_authoritative",
                "classification": "legacy_cc_task",
                "content_sha256": observation["legacy_snapshots"][0]["content_sha256"],
                "identity_state": "unresolved_candidate",
                "legacy_locator": "legacy-record",
                "loss": "canonical_task_identity_absent",
                "may_authorize": False,
                "relative_path": "closed/legacy-record.md",
                "state": "closed",
                "status": "done",
            }
        ]

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


def test_escalate_stalled_holds_every_task_without_mutation(tmp_path: Path):
    coord = Coordinator()
    lane = LaneState(role="delta", alive=True, pid=111, pid_source="pidfile", claimed_task="x")
    task = tmp_path / "t.md"
    body = "---\nstatus: claimed\nassigned_to: delta\n---\nbody\n"

    for task_id in (
        "p0-incident-demo-20260617",
        "segprep-normal-task-20260617",
    ):
        task.write_text(body, encoding="utf-8")
        before = task.read_bytes()
        assert coord._escalate_stalled(lane, task_id, task, task.read_text()) is False
        assert task.read_bytes() == before


@dataclass(frozen=True)
class CanonEchoFixture:
    task: Task
    lane: LaneState
    db_path: Path
    ledger_path: Path
    task_path: Path
    tasks_dir: Path
    cache: Path
    relay_dir: Path
    relay: Path
    event_log: CoordEventLog
    applied_claim: SimpleNamespace


class TestCanonEchoCoordinator:
    def _fixture(self, tmp_path: Path) -> CanonEchoFixture:
        tasks_dir = tmp_path / "vault" / "active"
        task_path = tasks_dir / "task-echo.md"
        task_path.parent.mkdir(parents=True)
        task_path.write_text(
            """---
type: cc-task
task_id: task-echo
title: "Echo"
status: claimed
assigned_to: cx-red
authority_case: CASE-ECHO-001
parent_spec: /tmp/spec.md
stage: S6_IMPLEMENTATION
claimable: true
implementation_authorized: true
source_mutation_authorized: true
claimed_at: 2026-07-11T14:00:00Z
updated_at: 2026-07-11T14:00:00Z
---

# Echo

## Session log
""",
            encoding="utf-8",
        )
        frontmatter = {
            "task_id": "task-echo",
            "status": "claimed",
            "assigned_to": "cx-red",
            "authority_case": "CASE-ECHO-001",
            "parent_spec": "/tmp/spec.md",
            "stage": "S6_IMPLEMENTATION",
            "claimable": True,
            "implementation_authorized": True,
            "source_mutation_authorized": True,
        }
        task = Task(
            task_id="task-echo",
            title="Echo",
            status="claimed",
            assigned_to="cx-red",
            wsjf=10.0,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="frontier_review_required",
            path=task_path,
            authority_case="CASE-ECHO-001",
            parent_spec="/tmp/spec.md",
            stage="S6_IMPLEMENTATION",
            frontmatter=frontmatter,
        )
        lane = LaneState(
            role="cx-red",
            platform="codex",
            alive=True,
            idle=False,
            claimed_task="task-echo",
        )
        db_path = tmp_path / "relay" / "messages.db"
        db_path.parent.mkdir()
        source_message_id = "dispatch-echo-source"
        send_message(
            db_path,
            Envelope(
                message_id=source_message_id,
                sender="hapax-coordinator",
                message_type="dispatch",
                priority=0,
                subject="task-echo",
                authority_case="CASE-ECHO-001",
                authority_item="task-echo",
                recipients_spec="cx-red",
                payload='{"task_id":"task-echo"}',
            ),
        )
        consume_messages(db_path, "cx-red")
        ack_message(db_path, source_message_id, "cx-red", "accepted")
        ack_message(db_path, source_message_id, "cx-red", "processed")
        ledger_path = tmp_path / "methodology-dispatch.jsonl"
        ledger_path.write_text(
            json.dumps(_echo_dispatch_record(source_message_id), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        expected = load_latest_dispatch_echo_expectation(
            ledger_path,
            task_id="task-echo",
            lane="cx-red",
        )
        cache = tmp_path / "cache"
        cache.mkdir()
        binding = ClaimDispatchBinding.create(
            task_id="task-echo",
            lane="cx-red",
            session_id="session-1",
            claim_epoch=123,
            dispatch_message_id=source_message_id,
            platform="codex",
            mode="headless",
            profile="full",
            authority_case="CASE-ECHO-001",
            binding_hash=expected.binding_hash,
            coord_dispatch_idempotency_key="coord-dispatch-echo-fixture",
        )
        task_snapshot = resolve_task_note(tmp_path / "vault", "task-echo", state="active")
        applied_claim = SimpleNamespace(
            current_task=task_snapshot,
            leases=(SimpleNamespace(binding=binding),),
        )
        relay_dir = tmp_path / "relay-status"
        relay_dir.mkdir()
        relay = relay_dir / "cx-red.yaml"
        relay.write_text(
            "role: cx-red\nstatus: active\ncurrent_claim: task-echo\nstage_token: S6\n",
            encoding="utf-8",
        )
        coord_dir = tmp_path / "coord"
        event_log = CoordEventLog(
            db_path=coord_dir / "ledger.db",
            jsonl_path=coord_dir / "ledger.jsonl",
            spool_dir=coord_dir / "spool",
        )
        event_log.append(
            CoordEvent(
                event_id="dispatch-echo-launch-succeeded",
                timestamp="2026-07-11T14:59:00Z",
                event_type="coord_dispatch.launch_succeeded",
                actor="cx-red",
                subject="task-echo",
                authority_case="CASE-ECHO-001",
                payload={
                    "idempotency_key": "coord-dispatch-echo-fixture",
                    "message_id": source_message_id,
                    "mode": "headless",
                    "outcome": "succeeded",
                    "platform": "codex",
                    "profile": "full",
                    "returncode": 0,
                },
            ),
            writer=CoordWriter.daemon("test-dispatch"),
        )
        return CanonEchoFixture(
            task,
            lane,
            db_path,
            ledger_path,
            task_path,
            tasks_dir,
            cache,
            relay_dir,
            relay,
            event_log,
            applied_claim,
        )

    def test_legacy_echo_position_holds_before_repair_or_any_effect(self, tmp_path: Path) -> None:
        fixture = self._fixture(tmp_path)
        note_before = fixture.task_path.read_bytes()
        relay_before = fixture.relay.read_bytes()
        messages_before = list_messages(fixture.db_path, MessageFilters(limit=100))
        claim_paths = tuple(
            path
            for key in ("cx-red", "cx-red-session-1")
            for path in (
                fixture.cache / f"cc-active-task-{key}",
                fixture.cache / f"cc-claim-epoch-{key}",
                fixture.cache / f"cc-claim-dispatch-{key}.json",
            )
        )
        claims_before = {path: path.read_bytes() if path.exists() else None for path in claim_paths}
        events_before = fixture.event_log.replay().events
        now = datetime(2026, 7, 11, 15, 0, tzinfo=UTC)

        with (
            patch("agents.coordinator.core.TASKS_DIR", fixture.tasks_dir),
            patch("agents.coordinator.core.CACHE_DIR", fixture.cache),
            patch("agents.coordinator.core.RELAY_DIR", fixture.relay_dir),
            patch(
                "agents.coordinator.core.default_event_log",
                return_value=fixture.event_log,
            ),
            patch(
                "agents.coordinator.core.resolve_applied_claim_publication_for_task",
                return_value=fixture.applied_claim,
            ),
            patch("agents.coordinator.core._render_expected_canon_payload") as render,
        ):
            with pytest.raises(CanonEchoError) as raised:
                _reconcile_task_canon_echo(
                    fixture.task,
                    fixture.lane,
                    db_path=fixture.db_path,
                    ledger_path=fixture.ledger_path,
                    now=now,
                )

        assert raised.value.reason_code == "canon_pre_gate0_claim_migration_required"
        render.assert_not_called()
        assert fixture.task_path.read_bytes() == note_before
        assert fixture.relay.read_bytes() == relay_before
        assert list_messages(fixture.db_path, MessageFilters(limit=100)) == messages_before
        assert {
            path: path.read_bytes() if path.exists() else None for path in claim_paths
        } == claims_before
        assert fixture.event_log.replay().events == events_before

    def test_echo_pass_projects_migration_hold_without_external_effect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fixture = self._fixture(tmp_path)
        monkeypatch.setenv("HAPAX_COORD_DIR", str(fixture.event_log.db_path.parent))
        monkeypatch.setenv("HAPAX_CANON_ECHO_ENFORCEMENT", "1")
        note_before = fixture.task_path.read_bytes()
        relay_before = fixture.relay.read_bytes()
        messages_before = list_messages(fixture.db_path, MessageFilters(limit=100))
        claim_paths = tuple(
            path
            for key in ("cx-red", "cx-red-session-1")
            for path in (
                fixture.cache / f"cc-active-task-{key}",
                fixture.cache / f"cc-claim-epoch-{key}",
                fixture.cache / f"cc-claim-dispatch-{key}.json",
            )
        )
        claim_before = {path: path.read_bytes() if path.exists() else None for path in claim_paths}
        events_before = fixture.event_log.replay().events
        coordinator = Coordinator()

        with (
            patch("agents.coordinator.core.TASKS_DIR", fixture.tasks_dir),
            patch("agents.coordinator.core.CACHE_DIR", fixture.cache),
            patch("agents.coordinator.core.RELAY_DIR", fixture.relay_dir),
            patch(
                "agents.coordinator.core.default_event_log",
                return_value=fixture.event_log,
            ),
            patch(
                "agents.coordinator.core.resolve_applied_claim_publication_for_task",
                return_value=fixture.applied_claim,
            ),
            patch("agents.coordinator.core._render_expected_canon_payload") as render,
        ):
            echo_pass = coordinator._reconcile_canon_echoes(
                [fixture.task],
                {fixture.lane.role: fixture.lane},
            )

        assert echo_pass.held_task_ids == frozenset({"task-echo"})
        assert echo_pass.blocked_count == 0
        assert fixture.lane.dispatch_ready is False
        assert fixture.lane.dispatch_blocked_reason == "canon_pre_gate0_claim_migration_required"
        render.assert_not_called()
        assert fixture.task_path.read_bytes() == note_before
        assert fixture.relay.read_bytes() == relay_before
        assert list_messages(fixture.db_path, MessageFilters(limit=100)) == messages_before
        assert {
            path: path.read_bytes() if path.exists() else None for path in claim_paths
        } == claim_before
        assert fixture.event_log.replay().events == events_before

    def test_valid_echo_inspection_holds_without_repair_publication(self, tmp_path: Path) -> None:
        fixture = self._fixture(tmp_path)
        expected = load_latest_dispatch_echo_expectation(
            fixture.ledger_path,
            task_id=fixture.task.task_id,
            lane=fixture.lane.role,
        )
        messages_before = list_messages(fixture.db_path, MessageFilters(limit=100))

        with (
            patch(
                "agents.coordinator.core.inspect_lifecycle_transactions",
                return_value=SimpleNamespace(scope_complete=True),
            ),
            patch(
                "agents.coordinator.core.resolve_applied_claim_publication_for_task",
                return_value=fixture.applied_claim,
            ),
            patch(
                "agents.coordinator.core.resolve_claim_bound_canon_position",
                return_value=expected,
            ),
            patch(
                "agents.coordinator.core._render_expected_canon_payload",
                return_value="exact canon payload",
            ),
        ):
            reconciliation, transaction_id = _reconcile_task_canon_echo(
                fixture.task,
                fixture.lane,
                db_path=fixture.db_path,
                now=datetime(2026, 7, 11, 15, 0, tzinfo=UTC),
            )

        assert reconciliation.action == "hold"
        assert reconciliation.reason_code == "canon_echo_projection_required"
        assert transaction_id is None
        assert list_messages(fixture.db_path, MessageFilters(limit=100)) == messages_before

    def test_echo_pass_holds_dead_lane_repair_without_reoffer_escape(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "p0-incident-echo.md"
        path.write_text("status: claimed\nassigned_to: cx-red\n", encoding="utf-8")
        task = Task(
            task_id="p0-incident-echo",
            title="Echo hold",
            status="claimed",
            assigned_to="cx-red",
            wsjf=100,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="frontier_review_required",
            path=path,
            claimed_at=0.0,
        )
        monkeypatch.setenv("HAPAX_CANON_ECHO_ENFORCEMENT", "1")
        coordinator = Coordinator()
        with patch(
            "agents.coordinator.core._reconcile_task_canon_echo",
            return_value=(
                CanonEchoReconciliation(
                    "hold",
                    "canon_echo_repair_required",
                ),
                None,
            ),
        ) as reconcile:
            echo_pass = coordinator._reconcile_canon_echoes([task], {})

        assert echo_pass.held_task_ids == frozenset({task.task_id})
        assert echo_pass.blocked_count == 0
        reconcile.assert_called_once()
        assert (
            coordinator._reoffer_orphaned_claims(
                [task],
                {},
                now_wall=time.time(),
                held_task_ids=echo_pass.held_task_ids,
            )
            == 0
        )
        assert "status: claimed" in path.read_text(encoding="utf-8")

    def test_echo_block_is_held_not_counted_as_transition(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "task-block.md"
        path.write_text("status: claimed\nassigned_to: cx-red\n", encoding="utf-8")
        task = Task(
            task_id="task-block",
            title="Echo block",
            status="claimed",
            assigned_to="cx-red",
            wsjf=1,
            effort_class="standard",
            platform_suitability=("codex",),
            quality_floor="frontier_review_required",
            path=path,
        )
        lane = LaneState(role="cx-red", claimed_task=task.task_id)
        monkeypatch.setenv("HAPAX_CANON_ECHO_ENFORCEMENT", "1")
        with patch(
            "agents.coordinator.core._reconcile_task_canon_echo",
            return_value=(
                CanonEchoReconciliation("block", "canon_echo_failed"),
                None,
            ),
        ):
            echo_pass = Coordinator()._reconcile_canon_echoes([task], {lane.role: lane})

        assert echo_pass.blocked_count == 0
        assert echo_pass.held_task_ids == frozenset({task.task_id})
