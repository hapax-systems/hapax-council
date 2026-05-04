"""Tests for shared.director_world_surface_prompt_block.

cc-task ``director-prompt-world-surface-block`` acceptance criteria:
- Prompt block is derived from snapshot source refs.
- Compact rows include availability, blockers, claim posture, and evidence.
- Static hints cannot authorize public/live/available state.
- Missing snapshot yields safe degraded/fallback prompt state.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from shared.director_world_surface_prompt_block import (
    MAX_SNAPSHOT_AGE_S,
    render_world_surface_prompt_block,
)


@pytest.fixture()
def snapshot_path(tmp_path: Path) -> Path:
    return tmp_path / "world-surface-snapshot.json"


def _write_snapshot(path: Path, data: dict, *, epoch: float | None = None) -> None:
    if epoch is not None:
        data["_written_at_epoch"] = epoch
    path.write_text(json.dumps(data), encoding="utf-8")


def _minimal_snapshot(
    *,
    available: list[str] | None = None,
    blocked: list[str] | None = None,
    dry_run: list[str] | None = None,
    private_only: list[str] | None = None,
    mode: str = "research",
    programme_ref: str | None = None,
) -> dict:
    """Build a minimal valid snapshot dict for testing."""
    return {
        "schema_version": 1,
        "snapshot_id": "director-wcs-snapshot-test-001",
        "generated_at": "2026-05-04T12:00:00Z",
        "freshness_ttl_s": 120,
        "mode": mode,
        "programme_ref": programme_ref,
        "prompt_summary": {
            "checked_at": "2026-05-04T12:00:00Z",
            "mode": mode,
            "available": available or [],
            "dry_run": dry_run or [],
            "blocked": blocked or [],
            "private_only": private_only or [],
            "prompt_hint_refs": [],
        },
        "evidence_obligations": [],
    }


# ── Missing / absent snapshot → empty (fail-closed) ──────────────────


class TestMissingSnapshot:
    """Missing snapshot yields empty block — the director sees nothing
    rather than false availability."""

    def test_missing_file_returns_empty(self, snapshot_path: Path) -> None:
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path)
        assert result == ""

    def test_malformed_json_returns_empty(self, snapshot_path: Path) -> None:
        snapshot_path.write_text("not json {{{", encoding="utf-8")
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path)
        assert result == ""

    def test_non_dict_json_returns_empty(self, snapshot_path: Path) -> None:
        snapshot_path.write_text("[1,2,3]", encoding="utf-8")
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path)
        assert result == ""


# ── Stale snapshot → empty (fail-closed) ─────────────────────────────


class TestStaleSnapshot:
    """Stale snapshots are treated as absent — fail-closed."""

    def test_stale_snapshot_returns_empty(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(available=["foreground audio.broadcast"])
        _write_snapshot(snapshot_path, data, epoch=now - MAX_SNAPSHOT_AGE_S - 10)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert result == ""

    def test_fresh_snapshot_returns_content(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(available=["foreground audio.broadcast via route:public"])
        _write_snapshot(snapshot_path, data, epoch=now - 5)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert "World Surface Read Model" in result
        assert "foreground audio.broadcast via route:public" in result


# ── Fresh snapshot renders correctly ─────────────────────────────────


class TestFreshSnapshot:
    """Fresh snapshots render compact prompt blocks with the right shape."""

    def test_header_fields(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(
            mode="fortress",
            programme_ref="prog-01-tier-list",
            available=["foreground audio.broadcast"],
        )
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert "mode: fortress" in result
        assert "programme: prog-01-tier-list" in result

    def test_available_moves_rendered(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(
            available=[
                "foreground audio.broadcast_voice via route:broadcast_public",
                "transition lane.reverie_substrate; witnesses: frame_fresh",
            ]
        )
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert "available:" in result
        assert "foreground audio.broadcast_voice via route:broadcast_public" in result
        assert "transition lane.reverie_substrate" in result

    def test_blocked_moves_rendered(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(
            blocked=[
                "foreground audio.private_assistant_monitor; reason: private route",
                "intensify re_splay_m8; reason: hardware_smoke_missing",
            ]
        )
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert "blocked:" in result
        assert "private route" in result
        assert "hardware_smoke_missing" in result

    def test_dry_run_moves_rendered(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(
            dry_run=["mark_boundary public.youtube_cuepoint; reason: broadcast_smoke_missing"]
        )
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert "dry_run:" in result
        assert "broadcast_smoke_missing" in result

    def test_private_only_moves_rendered(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(
            private_only=["route_attention control.sidechat; reason: local operator channel"]
        )
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert "private_only:" in result
        assert "local operator channel" in result

    def test_empty_moves_returns_empty(self, snapshot_path: Path) -> None:
        """Snapshot with no moves at all shouldn't clutter the prompt."""
        now = time.time()
        data = _minimal_snapshot()
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert result == ""

    def test_programme_ref_none(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(available=["hold some.surface"], programme_ref=None)
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert "programme: none" in result


# ── Context budget bounding ──────────────────────────────────────────


class TestContextBudget:
    """Block is capped to prevent context budget blowout."""

    def test_available_capped_at_10(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(available=[f"foreground surface_{i}" for i in range(20)])
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        # Should have exactly 10 available entries, not 20
        assert result.count("foreground surface_") == 10

    def test_blocked_capped_at_8(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(
            blocked=[f"hold blocked_surface_{i}; reason: test" for i in range(15)]
        )
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert result.count("blocked_surface_") == 8


# ── Static hints cannot authorize availability ───────────────────────


class TestStaticHints:
    """Static hint refs are rendered as style/safety only, never availability."""

    def test_static_hints_labeled_correctly(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(available=["hold some.surface"])
        data["prompt_summary"]["prompt_hint_refs"] = [
            "hint:reverie_preset_families",
            "hint:camera_positions",
        ]
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert "style/safety only, NOT availability" in result
        assert "hint:reverie_preset_families" in result


# ── Full move row projection (when prompt_summary is sparse) ─────────


class TestMoveRowProjection:
    """When prompt_summary lists are empty, the renderer falls back to
    projecting from full move row dicts."""

    def test_projects_from_full_rows(self, snapshot_path: Path) -> None:
        now = time.time()
        data = {
            "schema_version": 1,
            "snapshot_id": "director-wcs-snapshot-test-002",
            "generated_at": "2026-05-04T12:00:00Z",
            "mode": "research",
            "programme_ref": None,
            "prompt_summary": {
                "checked_at": "2026-05-04T12:00:00Z",
                "mode": "research",
                "available": [],
                "dry_run": [],
                "blocked": [],
                "private_only": [],
                "prompt_hint_refs": [],
            },
            "available_moves": [
                {
                    "verb": "foreground",
                    "surface_id": "audio.broadcast_voice",
                    "target_id": "broadcast_voice",
                    "display_name": "Broadcast Voice",
                    "route_refs": ["route:broadcast_public"],
                    "required_witness_refs": ["audio_safe", "egress_marker"],
                    "blocked_reasons": [],
                    "blocker_reason": None,
                }
            ],
            "blocked_moves": [
                {
                    "verb": "foreground",
                    "surface_id": "audio.private_monitor",
                    "target_id": "private_monitor",
                    "display_name": "Private Monitor",
                    "route_refs": [],
                    "required_witness_refs": [],
                    "blocked_reasons": ["private route, no public claim"],
                    "blocker_reason": "private route, no public claim",
                }
            ],
            "dry_run_moves": [],
            "private_only_moves": [],
            "evidence_obligations": [],
            "_written_at_epoch": now,
        }
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert "available:" in result
        assert "foreground audio.broadcast_voice" in result
        assert "via route:broadcast_public" in result
        assert "blocked:" in result
        assert "reason: private route, no public claim" in result


# ── Unsatisfied obligations ──────────────────────────────────────────


class TestEvidenceObligations:
    """Unsatisfied evidence obligations are surfaced."""

    def test_unsatisfied_obligations_rendered(self, snapshot_path: Path) -> None:
        now = time.time()
        data = _minimal_snapshot(available=["hold some.surface"])
        data["evidence_obligations"] = [
            {
                "obligation_id": "obligation.egress.broadcast",
                "dimension": "egress",
                "required_for": ["audio.broadcast_voice"],
                "evidence_refs": [],
                "satisfied": False,
                "missing_refs": ["egress_marker"],
            }
        ]
        _write_snapshot(snapshot_path, data, epoch=now)
        result = render_world_surface_prompt_block(snapshot_path=snapshot_path, now=now)
        assert "unsatisfied_obligations:" in result
        assert "egress" in result
        assert "egress_marker" in result
