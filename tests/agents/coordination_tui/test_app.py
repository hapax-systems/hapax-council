"""Tests for coordination_tui.app — Textual app composition."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.coordination_tui.app import CoordinationApp
from agents.coordination_tui.data import (
    DashboardState,
    LaneInfo,
    PRInfo,
    QuotaState,
    TaskInfo,
)

MOCK_STATE = DashboardState(
    lanes=[
        LaneInfo("beta", "hapax-claude-beta", "claude", "active", 0, "some-task", "#3070"),
        LaneInfo("cx-red", "hapax-codex-cx-red", "codex", "idle", 900, "", ""),
    ],
    tasks=[
        TaskInfo(
            "task-a",
            "Build the thing",
            14.0,
            "offered",
            "max",
            "unassigned",
            ["claude"],
            "frontier_required",
        ),
        TaskInfo(
            "task-b", "Fix the bug", 8.0, "claimed", "standard", "beta", ["any"], "deterministic_ok"
        ),
    ],
    prs=[
        PRInfo(3070, "fix(watchdog): dispatch ALL idle lanes", "zeta/watchdog", "pass", "alpha"),
    ],
    quota=QuotaState(
        pressure=0.42,
        throttle_level="normal",
        window_24h_cost=21.0,
        budget=50.0,
        governance_healthy=True,
    ),
    task_counts={"offered": 80, "claimed": 20, "in_progress": 10, "done": 6},
)


@pytest.mark.asyncio
async def test_app_composes_without_error() -> None:
    with patch(
        "agents.coordination_tui.app.load_all", new_callable=AsyncMock, return_value=MOCK_STATE
    ):
        async with CoordinationApp().run_test(size=(120, 40)) as pilot:
            app = pilot.app
            assert app.query_one("#lane-table") is not None
            assert app.query_one("#task-table") is not None
            assert app.query_one("#pr-table") is not None
            assert app.query_one("#quota-panel") is not None


@pytest.mark.asyncio
async def test_refresh_populates_tables() -> None:
    with patch(
        "agents.coordination_tui.app.load_all", new_callable=AsyncMock, return_value=MOCK_STATE
    ):
        async with CoordinationApp().run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app = pilot.app
            lane_table = app.query_one("#lane-table")
            assert lane_table.row_count == 2
            task_table = app.query_one("#task-table")
            assert task_table.row_count == 2
            pr_table = app.query_one("#pr-table")
            assert pr_table.row_count == 1
