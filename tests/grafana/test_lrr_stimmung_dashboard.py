"""Contract tests for the LRR Stimmung Grafana dashboard."""

from __future__ import annotations

import json
import re
from pathlib import Path

from shared.stimmung import _DIMENSION_NAMES

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = REPO_ROOT / "grafana" / "dashboards" / "lrr-stimmung.json"


def _dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))


def test_description_lists_canonical_dimensions() -> None:
    description = _dashboard()["description"]
    match = re.search(
        r"Dimensions \(per shared/stimmung\.py\):\n(?P<body>.*?)\n\nPhase 6",
        description,
        flags=re.DOTALL,
    )
    assert match is not None
    listed = [
        part.strip().rstrip(".") for part in match.group("body").replace("\n", " ").split(",")
    ]

    assert listed == _DIMENSION_NAMES


def test_local_capacity_panel_has_sustained_alert_rule() -> None:
    dashboard = _dashboard()
    panel = next(
        panel
        for panel in dashboard["panels"]
        if panel.get("title") == "Local capacity (non-$) — alert >0.7 for 5m"
    )

    targets = panel["targets"]
    assert targets == [
        {
            "expr": 'hapax_stimmung_value{dimension="local_capacity_pressure"}',
            "legendFormat": "local_capacity_pressure",
            "refId": "A",
        },
        {
            "expr": 'hapax_stimmung_freshness_s{dimension="local_capacity_pressure"}',
            "legendFormat": "local_capacity_freshness_s",
            "refId": "B",
        },
    ]

    alert = panel["alert"]
    assert alert["name"] == "local_capacity_pressure > 0.7 for 5m"
    assert alert["for"] == "5m"
    assert alert["noDataState"] == "ok"
    assert alert["conditions"] == [
        {
            "evaluator": {"params": [0.7], "type": "gt"},
            "operator": {"type": "and"},
            "query": {"params": ["A", "5m", "now"]},
            "reducer": {"params": [], "type": "last"},
            "type": "query",
        },
        {
            "evaluator": {"params": [120], "type": "lt"},
            "operator": {"type": "and"},
            "query": {"params": ["B", "5m", "now"]},
            "reducer": {"params": [], "type": "last"},
            "type": "query",
        },
    ]
