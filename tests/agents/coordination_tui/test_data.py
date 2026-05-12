"""Tests for coordination_tui.data — data loading functions."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agents.coordination_tui.data import (
    load_prs,
    load_quota,
    load_task_counts,
    load_tasks,
)


class TestLoadTasks:
    def test_sorts_by_wsjf_descending(self, tmp_path: Path) -> None:
        for name, wsjf in [("low", 2.0), ("high", 14.0), ("mid", 8.0)]:
            (tmp_path / f"{name}.md").write_text(
                textwrap.dedent(f"""\
                    ---
                    title: "{name} task"
                    status: offered
                    wsjf: {wsjf}
                    effort_class: standard
                    assigned_to: unassigned
                    platform_suitability: [claude]
                    quality_floor: deterministic_ok
                    ---
                    Body text.
                """)
            )

        with patch("agents.coordination_tui.data.TASK_ROOT", tmp_path):
            tasks = load_tasks()

        assert len(tasks) == 3
        assert tasks[0].wsjf == 14.0
        assert tasks[1].wsjf == 8.0
        assert tasks[2].wsjf == 2.0

    def test_filters_to_active_statuses(self, tmp_path: Path) -> None:
        for name, status in [("a", "offered"), ("b", "done"), ("c", "claimed"), ("d", "closed")]:
            (tmp_path / f"{name}.md").write_text(
                textwrap.dedent(f"""\
                    ---
                    title: "{name}"
                    status: {status}
                    wsjf: 5.0
                    effort_class: standard
                    assigned_to: unassigned
                    platform_suitability: [any]
                    quality_floor: deterministic_ok
                    ---
                """)
            )

        with patch("agents.coordination_tui.data.TASK_ROOT", tmp_path):
            tasks = load_tasks()

        ids = {t.task_id for t in tasks}
        assert "a" in ids
        assert "c" in ids
        assert "b" not in ids
        assert "d" not in ids

    def test_handles_missing_dir(self, tmp_path: Path) -> None:
        with patch("agents.coordination_tui.data.TASK_ROOT", tmp_path / "nonexistent"):
            tasks = load_tasks()
        assert tasks == []

    def test_handles_bad_frontmatter(self, tmp_path: Path) -> None:
        (tmp_path / "bad.md").write_text("no frontmatter here")
        with patch("agents.coordination_tui.data.TASK_ROOT", tmp_path):
            tasks = load_tasks()
        assert tasks == []


class TestLoadQuota:
    def test_reads_from_pressure_json(self, tmp_path: Path) -> None:
        pressure_file = tmp_path / "pressure.json"
        pressure_file.write_text(
            json.dumps(
                {
                    "pressure": 0.42,
                    "throttle_level": "normal",
                    "window_24h_cost": 21.0,
                    "governance_healthy": True,
                }
            )
        )

        with patch("agents.coordination_tui.data.PRESSURE_PATH", pressure_file):
            quota = load_quota()

        assert quota is not None
        assert quota.pressure == 0.42
        assert quota.throttle_level == "normal"
        assert quota.window_24h_cost == 21.0

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        with (
            patch("agents.coordination_tui.data.PRESSURE_PATH", tmp_path / "nope.json"),
            patch(
                "agents.coordination_tui.data.quota_pressure", side_effect=ImportError, create=True
            ),
        ):
            quota = load_quota()
        assert quota is None


class TestLoadPRs:
    @pytest.mark.asyncio
    async def test_parses_gh_json(self) -> None:
        mock_data = json.dumps(
            [
                {
                    "number": 3070,
                    "title": "fix(watchdog): dispatch ALL idle lanes",
                    "headRefName": "zeta/watchdog-dispatch",
                    "statusCheckRollup": [
                        {"conclusion": "SUCCESS", "status": "COMPLETED"},
                    ],
                    "author": {"login": "alpha"},
                },
                {
                    "number": 3076,
                    "title": "feat(durf): reveal operator sessions",
                    "headRefName": "alpha/durf-reveal",
                    "statusCheckRollup": [
                        {"conclusion": None, "status": "IN_PROGRESS"},
                    ],
                    "author": {"login": "alpha"},
                },
            ]
        )

        with patch(
            "agents.coordination_tui.data._run", new_callable=AsyncMock, return_value=mock_data
        ):
            prs = await load_prs()

        assert len(prs) == 2
        assert prs[0].number == 3070
        assert prs[0].ci_status == "pass"
        assert prs[1].ci_status == "pending"

    @pytest.mark.asyncio
    async def test_handles_empty_response(self) -> None:
        with patch("agents.coordination_tui.data._run", new_callable=AsyncMock, return_value=""):
            prs = await load_prs()
        assert prs == []


class TestLoadTaskCounts:
    def test_counts_statuses(self, tmp_path: Path) -> None:
        for i, status in enumerate(["offered", "offered", "claimed", "done"]):
            (tmp_path / f"task-{i}.md").write_text(f"---\nstatus: {status}\n---\n")

        with patch("agents.coordination_tui.data.TASK_ROOT", tmp_path):
            counts = load_task_counts()

        assert counts["offered"] == 2
        assert counts["claimed"] == 1
        assert counts["done"] == 1
