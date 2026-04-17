"""Tests for agents.studio_compositor.objective_hero_switcher (Phase 8 item 5)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

_COUNTER = {"n": 0}


def _write_obj(
    path: Path,
    title: str,
    status: str,
    priority: str,
    activities: list[str],
    opened_offset_s: float = 0.0,
) -> None:
    _COUNTER["n"] += 1
    opened = datetime.now(UTC)
    fm = {
        "objective_id": f"obj-{_COUNTER['n']:03d}",
        "title": title,
        "status": status,
        "priority": priority,
        "activities_that_advance": activities,
        "success_criteria": ["stub"],
        "opened_at": opened.isoformat(),
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
    path.write_text("\n".join(lines), encoding="utf-8")


class TestHeroForActiveObjectives:
    def test_no_active_objectives_returns_none(self, tmp_path):
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        assert hero_for_active_objectives(objectives_dir=tmp_path) is None

    def test_missing_dir_returns_none(self, tmp_path):
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        assert hero_for_active_objectives(objectives_dir=tmp_path / "nope") is None

    def test_vinyl_activity_maps_to_hardware(self, tmp_path):
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        _write_obj(tmp_path / "obj-a.md", "Spin that record", "active", "high", ["vinyl"])
        assert hero_for_active_objectives(objectives_dir=tmp_path) == "hardware"

    def test_study_activity_maps_to_operator(self, tmp_path):
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        _write_obj(tmp_path / "obj-a.md", "Read Bachelard", "active", "normal", ["study"])
        assert hero_for_active_objectives(objectives_dir=tmp_path) == "operator"

    def test_chat_activity_maps_to_operator(self, tmp_path):
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        _write_obj(tmp_path / "obj-a.md", "Guest Q&A", "active", "high", ["chat"])
        assert hero_for_active_objectives(objectives_dir=tmp_path) == "operator"

    def test_observe_activity_returns_none(self, tmp_path):
        """observe = balanced grid, no hero."""
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        _write_obj(tmp_path / "obj-a.md", "Ambient", "active", "normal", ["observe"])
        assert hero_for_active_objectives(objectives_dir=tmp_path) is None

    def test_silence_activity_returns_none(self, tmp_path):
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        _write_obj(tmp_path / "obj-a.md", "Quiet", "active", "normal", ["silence"])
        assert hero_for_active_objectives(objectives_dir=tmp_path) is None

    def test_highest_priority_wins(self, tmp_path):
        """If two objectives are active, the higher-priority one sets the hero."""
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        _write_obj(tmp_path / "obj-low.md", "Low-p", "active", "low", ["vinyl"])
        _write_obj(tmp_path / "obj-high.md", "High-p", "active", "high", ["study"])

        # high-priority 'study' wins → operator
        assert hero_for_active_objectives(objectives_dir=tmp_path) == "operator"

    def test_closed_objective_skipped(self, tmp_path):
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        _write_obj(tmp_path / "obj-closed.md", "Closed", "closed", "high", ["vinyl"])
        assert hero_for_active_objectives(objectives_dir=tmp_path) is None

    def test_allowed_roles_filters(self, tmp_path):
        """When the hardware camera isn't currently available, vinyl →
        hardware gets filtered; next activity or None wins."""
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        _write_obj(tmp_path / "obj-a.md", "Spin", "active", "high", ["vinyl", "chat"])
        # hardware not in allowed; vinyl filtered → next activity 'chat' → operator
        result = hero_for_active_objectives(
            objectives_dir=tmp_path, allowed_roles=frozenset({"operator"})
        )
        assert result == "operator"

    def test_unmapped_activity_falls_through(self, tmp_path):
        """An objective with only unmapped activities returns None."""
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        _write_obj(tmp_path / "obj-a.md", "Unknown", "active", "high", ["observe", "silence"])
        assert hero_for_active_objectives(objectives_dir=tmp_path) is None

    def test_first_mapped_activity_within_objective_wins(self, tmp_path):
        """Within a single objective, the first mapped activity wins (order
        from activities_that_advance is preserved in the YAML)."""
        from agents.studio_compositor.objective_hero_switcher import (
            hero_for_active_objectives,
        )

        _write_obj(
            tmp_path / "obj-a.md",
            "Multi-activity",
            "active",
            "high",
            ["vinyl", "study"],  # vinyl first → hardware
        )
        assert hero_for_active_objectives(objectives_dir=tmp_path) == "hardware"


class TestActivityHeroMap:
    def test_map_is_frozen_expected_keys(self):
        """The map's key set should match the Objective schema's
        activities_that_advance whitelist. Regression pin."""
        from agents.studio_compositor.objective_hero_switcher import ACTIVITY_HERO_MAP

        expected = {"react", "chat", "vinyl", "study", "observe", "silence"}
        assert set(ACTIVITY_HERO_MAP.keys()) == expected
