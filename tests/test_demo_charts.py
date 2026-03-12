"""Tests for Matplotlib chart generation."""

import json

import pytest

pytest.importorskip("matplotlib", reason="matplotlib not installed")

from agents.demo_pipeline.charts import MPLSTYLE_PATH, _normalize_chart_spec, render_chart  # noqa: E402, I001


class TestCharts:
    def test_render_bar_chart(self, tmp_path):
        spec = json.dumps(
            {
                "type": "bar",
                "title": "Test Bar",
                "data": {"labels": ["A", "B", "C"], "values": [10, 20, 30]},
            }
        )
        output = tmp_path / "bar.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_render_line_chart(self, tmp_path):
        spec = json.dumps(
            {
                "type": "line",
                "title": "Test Line",
                "data": {"x": [1, 2, 3, 4, 5], "y": [10, 20, 15, 25, 30], "label": "metric"},
            }
        )
        output = tmp_path / "line.png"
        result = render_chart(spec, output)
        assert result.exists()

    def test_render_gauge_chart(self, tmp_path):
        spec = json.dumps(
            {
                "type": "gauge",
                "title": "Health Score",
                "data": {"value": 74, "max": 75, "label": "System Health"},
            }
        )
        output = tmp_path / "gauge.png"
        result = render_chart(spec, output)
        assert result.exists()

    def test_gruvbox_style_exists(self):
        assert MPLSTYLE_PATH.exists(), f"Missing gruvbox.mplstyle at {MPLSTYLE_PATH}"

    def test_unknown_chart_type_falls_back_to_bar(self, tmp_path):
        spec = json.dumps(
            {
                "type": "scatter",
                "title": "Fallback",
                "data": {"labels": ["A", "B"], "values": [10, 20]},
            }
        )
        output = tmp_path / "fallback.png"
        result = render_chart(spec, output)
        assert result.exists()

    def test_render_horizontal_bar_chart(self, tmp_path):
        spec = json.dumps(
            {
                "type": "horizontal-bar",
                "title": "Test Horizontal Bar",
                "data": {"labels": ["Fast", "Balanced", "Reasoning"], "values": [95, 80, 70]},
            }
        )
        output = tmp_path / "hbar.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_render_area_chart(self, tmp_path):
        spec = json.dumps(
            {
                "type": "area",
                "title": "Test Area",
                "data": {
                    "labels": ["Jan", "Feb", "Mar", "Apr"],
                    "values": [10, 25, 15, 30],
                    "label": "Queries",
                },
            }
        )
        output = tmp_path / "area.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_render_pie_chart(self, tmp_path):
        spec = json.dumps(
            {
                "type": "pie",
                "title": "Test Pie",
                "data": {"labels": ["Agents", "Timers", "Services"], "values": [13, 9, 12]},
            }
        )
        output = tmp_path / "pie.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_render_stacked_bar_chart(self, tmp_path):
        spec = json.dumps(
            {
                "type": "stacked-bar",
                "title": "Cost Breakdown",
                "data": {
                    "labels": ["Mon", "Tue", "Wed"],
                    "datasets": [
                        {"label": "Anthropic", "data": [20, 25, 18]},
                        {"label": "Ollama", "data": [5, 3, 7]},
                    ],
                },
            }
        )
        output = tmp_path / "stacked.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_render_stacked_bar_fallback_no_datasets(self, tmp_path):
        """Stacked bar with no datasets falls back to regular bar."""
        spec = json.dumps(
            {
                "type": "stacked-bar",
                "title": "Fallback",
                "data": {"labels": ["A", "B"], "values": [10, 20]},
            }
        )
        output = tmp_path / "stacked_fb.png"
        result = render_chart(spec, output)
        assert result.exists()

    def test_render_network_chart_with_nodes_edges(self, tmp_path):
        spec = json.dumps(
            {
                "type": "network",
                "title": "Knowledge Flow",
                "data": {
                    "nodes": ["RAG Pipeline", "Qdrant", "Profiler", "Briefing", "Vault"],
                    "edges": [
                        {"source": "RAG Pipeline", "target": "Qdrant"},
                        {"source": "Qdrant", "target": "Profiler"},
                        {"source": "Qdrant", "target": "Briefing"},
                        {"source": "Briefing", "target": "Vault"},
                    ],
                },
            }
        )
        output = tmp_path / "network.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_render_network_chart_labels_values_fallback(self, tmp_path):
        """Network chart with labels/values (no nodes/edges) creates a star graph."""
        spec = json.dumps(
            {
                "type": "network",
                "title": "Connections",
                "data": {"labels": ["A", "B", "C", "D"], "values": [10, 20, 30, 40]},
            }
        )
        output = tmp_path / "network_star.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_render_graph_alias(self, tmp_path):
        """'graph' type should render the same as 'network'."""
        spec = json.dumps(
            {
                "type": "graph",
                "title": "Graph Alias",
                "data": {
                    "nodes": ["X", "Y", "Z"],
                    "edges": [{"source": "X", "target": "Y"}, {"source": "Y", "target": "Z"}],
                },
            }
        )
        output = tmp_path / "graph.png"
        result = render_chart(spec, output)
        assert result.exists()

    def test_render_network_dict_nodes(self, tmp_path):
        """Network with dict-format nodes (id/label)."""
        spec = json.dumps(
            {
                "type": "network",
                "title": "Labeled Network",
                "data": {
                    "nodes": [
                        {"id": "a", "label": "Agent A"},
                        {"id": "b", "label": "Agent B"},
                    ],
                    "edges": [{"from": "a", "to": "b"}],
                },
            }
        )
        output = tmp_path / "network_dict.png"
        result = render_chart(spec, output)
        assert result.exists()

    def test_chartjs_format_renders(self, tmp_path):
        """Chart.js format with datasets should be auto-normalized and render."""
        spec = json.dumps(
            {
                "type": "bar",
                "title": "Chart.js Format",
                "data": {
                    "labels": ["Agents", "Timers", "Checks"],
                    "datasets": [{"label": "Count", "data": [13, 9, 75]}],
                },
            }
        )
        output = tmp_path / "chartjs.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0


class TestChartNormalization:
    def test_chartjs_bar_normalized(self):
        spec = {
            "type": "bar",
            "data": {
                "labels": ["A", "B"],
                "datasets": [{"label": "Series", "data": [10, 20]}],
            },
        }
        result = _normalize_chart_spec(spec)
        assert result["data"]["labels"] == ["A", "B"]
        assert result["data"]["values"] == [10, 20]
        assert "datasets" not in result["data"]

    def test_chartjs_with_colors(self):
        spec = {
            "type": "bar",
            "data": {
                "labels": ["X"],
                "datasets": [{"data": [5], "backgroundColor": ["#ff0000"]}],
            },
        }
        result = _normalize_chart_spec(spec)
        assert result["data"]["colors"] == ["#ff0000"]

    def test_chartjs_options_extracted(self):
        spec = {
            "type": "bar",
            "data": {"labels": ["A"], "datasets": [{"data": [1]}]},
            "options": {
                "scales": {
                    "x": {"title": {"text": "Category"}},
                    "y": {"title": {"text": "Value"}},
                },
            },
        }
        result = _normalize_chart_spec(spec)
        assert result["xlabel"] == "Category"
        assert result["ylabel"] == "Value"
        assert "options" not in result

    def test_matplotlib_format_unchanged(self):
        spec = {
            "type": "bar",
            "data": {"labels": ["A", "B"], "values": [10, 20]},
        }
        result = _normalize_chart_spec(spec)
        assert result["data"]["labels"] == ["A", "B"]
        assert result["data"]["values"] == [10, 20]

    def test_empty_datasets_safe(self):
        spec = {"type": "bar", "data": {"labels": [], "datasets": []}}
        result = _normalize_chart_spec(spec)
        # Should not crash
        assert "labels" in result["data"]

    def test_stacked_bar_preserves_datasets(self):
        """Stacked-bar chart.js format should NOT be flattened to labels/values."""
        spec = {
            "type": "stacked-bar",
            "data": {
                "labels": ["Mon", "Tue"],
                "datasets": [
                    {"label": "A", "data": [10, 20]},
                    {"label": "B", "data": [5, 15]},
                ],
            },
        }
        result = _normalize_chart_spec(spec)
        assert "datasets" in result["data"]
        assert len(result["data"]["datasets"]) == 2

    def test_render_multi_line_chart(self, tmp_path):
        spec = json.dumps(
            {
                "type": "stacked-line",
                "title": "Health Trends",
                "data": {
                    "labels": ["Day 1", "Day 2", "Day 3"],
                    "datasets": [
                        {"label": "Healthy", "values": [76, 78, 78]},
                        {"label": "Auto-Fixed", "values": [2, 0, 1]},
                    ],
                },
            }
        )
        output = tmp_path / "multiline.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_render_timeline_chart(self, tmp_path):
        spec = json.dumps(
            {
                "type": "timeline",
                "title": "Daily Schedule",
                "data": {
                    "events": [
                        {"time": "07:00", "event": "Briefing"},
                        {"time": "07:15", "event": "Health Check"},
                        {"time": "12:00", "event": "Profile Update"},
                    ],
                },
            }
        )
        output = tmp_path / "timeline.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_dataset_values_key_normalized(self, tmp_path):
        """Datasets using 'values' instead of 'data' should work for line charts."""
        spec = json.dumps(
            {
                "type": "line",
                "title": "Cost Trend",
                "data": {
                    "labels": ["Day 1", "Day 2", "Day 3"],
                    "datasets": [{"label": "Cost", "values": [6.2, 8.4, 7.3]}],
                },
            }
        )
        output = tmp_path / "values_key.png"
        result = render_chart(spec, output)
        assert result.exists()
        assert result.stat().st_size > 0


class TestChartMalformedJson:
    """Malformed LLM JSON should produce a fallback image, not crash."""

    def test_malformed_json_produces_fallback(self, tmp_path):
        out = tmp_path / "bad.png"
        result = render_chart("{invalid json, trailing", out)
        assert result == out
        assert out.exists()

    def test_empty_string_produces_fallback(self, tmp_path):
        out = tmp_path / "empty.png"
        result = render_chart("", out)
        assert result == out
        assert out.exists()

    def test_truncated_json_produces_fallback(self, tmp_path):
        out = tmp_path / "trunc.png"
        result = render_chart('{"type": "bar", "data": {"labels": ["A"', out)
        assert result == out
        assert out.exists()
