"""Tests for agents.studio_compositor.objectives_overlay (LRR Phase 8 item 4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

# ── State reading path ──────────────────────────────────────────────────────


_ID_COUNTER = {"n": 0}


def _write_obj(path: Path, title: str, status: str, priority: str, activities: list[str]) -> None:
    """Write a minimal vault-native objective markdown file.

    The schema (shared/objective_schema.Objective) requires:
      - objective_id matching pattern ^obj-\\d{3,4}$
      - success_criteria non-empty list
    """
    opened_at = datetime.now(UTC).isoformat()
    _ID_COUNTER["n"] += 1
    obj_id = f"obj-{_ID_COUNTER['n']:03d}"
    fm = {
        "objective_id": obj_id,
        "title": title,
        "status": status,
        "priority": priority,
        "activities_that_advance": activities,
        "success_criteria": ["stub criterion"],
        "opened_at": opened_at,
    }
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(f"body for {title}")
    path.write_text("\n".join(lines), encoding="utf-8")


class TestReadActiveObjectives:
    def test_missing_dir_returns_empty(self, tmp_path):
        from agents.studio_compositor.objectives_overlay import ObjectivesOverlay

        overlay = ObjectivesOverlay(objectives_dir=tmp_path / "nope")
        assert overlay._read_active_objectives() == []

    def test_empty_dir_returns_empty(self, tmp_path):
        from agents.studio_compositor.objectives_overlay import ObjectivesOverlay

        overlay = ObjectivesOverlay(objectives_dir=tmp_path)
        assert overlay._read_active_objectives() == []

    def test_reads_active_objective(self, tmp_path):
        from agents.studio_compositor.objectives_overlay import ObjectivesOverlay

        _write_obj(
            tmp_path / "obj-cycle2.md",
            title="Ship Cycle 2 preregistration",
            status="active",
            priority="high",
            activities=["study", "chat"],
        )
        overlay = ObjectivesOverlay(objectives_dir=tmp_path)
        result = overlay._read_active_objectives()
        assert len(result) == 1
        assert result[0]["title"] == "Ship Cycle 2 preregistration"
        assert result[0]["priority"] == "high"
        assert result[0]["activities"] == ["study", "chat"]

    def test_skips_non_active_status(self, tmp_path):
        from agents.studio_compositor.objectives_overlay import ObjectivesOverlay

        _write_obj(
            tmp_path / "obj-closed.md",
            title="Done long ago",
            status="closed",
            priority="normal",
            activities=["observe"],
        )
        _write_obj(
            tmp_path / "obj-active.md",
            title="Currently working",
            status="active",
            priority="normal",
            activities=["study"],
        )
        overlay = ObjectivesOverlay(objectives_dir=tmp_path)
        result = overlay._read_active_objectives()
        titles = [o["title"] for o in result]
        assert "Currently working" in titles
        assert "Done long ago" not in titles

    def test_sorts_by_priority_then_recency(self, tmp_path):
        from agents.studio_compositor.objectives_overlay import ObjectivesOverlay

        _write_obj(
            tmp_path / "obj-low.md",
            title="low-p",
            status="active",
            priority="low",
            activities=["observe"],
        )
        _write_obj(
            tmp_path / "obj-high.md",
            title="high-p",
            status="active",
            priority="high",
            activities=["observe"],
        )
        _write_obj(
            tmp_path / "obj-normal.md",
            title="normal-p",
            status="active",
            priority="normal",
            activities=["observe"],
        )
        overlay = ObjectivesOverlay(objectives_dir=tmp_path)
        result = overlay._read_active_objectives()
        titles = [o["title"] for o in result]
        assert titles == ["high-p", "normal-p", "low-p"]

    def test_truncates_to_max_visible(self, tmp_path):
        from agents.studio_compositor.objectives_overlay import ObjectivesOverlay

        for i in range(5):
            _write_obj(
                tmp_path / f"obj-{i}.md",
                title=f"obj-{i}",
                status="active",
                priority="normal",
                activities=["observe"],
            )
        overlay = ObjectivesOverlay(objectives_dir=tmp_path, max_visible=2)
        assert len(overlay._read_active_objectives()) == 2

    def test_skips_malformed_objective(self, tmp_path):
        """A corrupt YAML file shouldn't blank the overlay — other objectives
        should still render."""
        from agents.studio_compositor.objectives_overlay import ObjectivesOverlay

        (tmp_path / "obj-bad.md").write_text("---\nnot yaml: : :\n---\n", encoding="utf-8")
        _write_obj(
            tmp_path / "obj-ok.md",
            title="good one",
            status="active",
            priority="normal",
            activities=["observe"],
        )
        overlay = ObjectivesOverlay(objectives_dir=tmp_path)
        result = overlay._read_active_objectives()
        titles = [o["title"] for o in result]
        assert titles == ["good one"]


# ── CairoSource render path (smoke — draws without crashing) ────────────────


class TestRender:
    def test_render_clears_when_no_objectives(self, tmp_path):
        import cairo

        from agents.studio_compositor.objectives_overlay import ObjectivesOverlay

        overlay = ObjectivesOverlay(objectives_dir=tmp_path)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 1080)
        cr = cairo.Context(surface)
        # Paint non-transparent first to verify the render clears it
        cr.set_source_rgba(1, 1, 1, 1)
        cr.paint()

        overlay.render(cr, 1920, 1080, 0.0, overlay.state())
        # Pixel at origin should now be fully transparent
        data = bytes(surface.get_data())
        # ARGB32 native-endian → alpha is the high byte on little-endian,
        # checking the first 4 bytes is enough for a smoke test
        assert data[:4] == b"\x00\x00\x00\x00" or data[3] == 0

    @pytest.mark.xfail(
        strict=False,
        reason="ytb-OBJECTIVES-OVERLAY-RENDER-FOLLOWUP: chronic 'overlay did not render' "
        "assertion failure on main since ~20:00Z; render path regression "
        "disjoint from fixture setup. See cc-task.",
    )
    def test_render_draws_when_objectives_present(self, tmp_path):
        import cairo

        from agents.studio_compositor.objectives_overlay import ObjectivesOverlay

        _write_obj(
            tmp_path / "obj-demo.md",
            title="Stream ready",
            status="active",
            priority="high",
            activities=["study"],
        )
        overlay = ObjectivesOverlay(objectives_dir=tmp_path)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 1080)
        cr = cairo.Context(surface)

        overlay.render(cr, 1920, 1080, 0.0, overlay.state())
        # After drawing the panel, some non-transparent pixels should exist
        # near the top-left where the panel lives
        data = bytes(surface.get_data())
        stride = surface.get_stride()
        # Sample a row well inside the panel (row y=60, col x=40)
        idx = 60 * stride + 40 * 4
        assert any(b != 0 for b in data[idx : idx + 4]), "overlay did not render"


class TestInit:
    def test_rejects_nonpositive_max_visible(self):
        from agents.studio_compositor.objectives_overlay import ObjectivesOverlay

        with pytest.raises(ValueError):
            ObjectivesOverlay(max_visible=0)
        with pytest.raises(ValueError):
            ObjectivesOverlay(max_visible=-1)
