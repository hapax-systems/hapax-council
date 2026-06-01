"""goal-map.canvas reader + orientation consumption (OQ-9 feeders repair).

``vault_canvas_writer`` WRITES a JSON Canvas goal-dependency map but nothing read it
back. ``read_goal_map`` parses it and the orientation panel surfaces the goals that
are blocked by an incomplete dependency.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from logos.data import orientation
from logos.data.vault_goals import GoalMap, GoalMapEdge, read_goal_map


def _write_canvas(path: Path, nodes: list[dict], edges: list[dict]) -> None:
    path.write_text(json.dumps({"nodes": nodes, "edges": edges}), encoding="utf-8")


def test_read_goal_map_parses_nodes_and_edges(tmp_path: Path) -> None:
    canvas = tmp_path / "goal-map.canvas"
    _write_canvas(
        canvas,
        [{"id": "g1", "text": "Goal one"}, {"id": "g2", "text": "Goal two"}],
        [{"id": "e1", "fromNode": "g1", "toNode": "g2", "fromSide": "right", "toSide": "left"}],
    )
    gm = read_goal_map(canvas)
    assert gm is not None
    assert gm.nodes == {"g1": "Goal one", "g2": "Goal two"}
    assert gm.edges == [GoalMapEdge("g1", "g2")]
    assert gm.dependencies_of("g2") == ["g1"]
    assert gm.blocked_node_ids() == ["g2"]


def test_read_goal_map_missing_returns_none(tmp_path: Path) -> None:
    assert read_goal_map(tmp_path / "absent.canvas") is None


def test_read_goal_map_malformed_returns_none(tmp_path: Path) -> None:
    bad = tmp_path / "bad.canvas"
    bad.write_text("this is not json {", encoding="utf-8")
    assert read_goal_map(bad) is None


def test_read_goal_map_skips_malformed_entries(tmp_path: Path) -> None:
    canvas = tmp_path / "c.canvas"
    canvas.write_text(
        json.dumps(
            {
                "nodes": [{"id": "g1", "text": "ok"}, {"no_id": 1}, "junk"],
                "edges": [{"fromNode": "g1"}, {"fromNode": "g1", "toNode": "g2"}],
            }
        ),
        encoding="utf-8",
    )
    gm = read_goal_map(canvas)
    assert gm is not None
    assert gm.nodes == {"g1": "ok"}
    assert gm.edges == [GoalMapEdge("g1", "g2")]


def test_no_incoming_edge_is_not_blocked(tmp_path: Path) -> None:
    canvas = tmp_path / "c.canvas"
    _write_canvas(canvas, [{"id": "g1", "text": "free"}], [])
    gm = read_goal_map(canvas)
    assert gm is not None
    assert gm.blocked_node_ids() == []


def test_collect_orientation_surfaces_blocked_goals() -> None:
    """The orientation panel reads goal-map.canvas and exposes blocked goal ids."""
    gm = GoalMap(nodes={"g1": "", "g2": ""}, edges=[GoalMapEdge("g1", "g2")])
    with (
        patch.object(orientation, "read_goal_map", return_value=gm),
        patch.object(orientation, "_load_domain_registry", return_value={}),
        patch.object(orientation, "infer_session", return_value=MagicMock()),
        patch.object(orientation, "collect_vault_goals", return_value=[]),
        patch.object(orientation, "_get_briefing", return_value=(None, None)),
        patch.object(orientation, "_get_health_summary", return_value=("ok", 0)),
        patch.object(orientation, "_get_sprint_summary", return_value=None),
        patch.object(orientation, "_get_stimmung_stance", return_value="nominal"),
    ):
        state = orientation.collect_orientation()
    assert state.blocked_goal_ids == ["g2"]
