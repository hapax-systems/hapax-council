"""Regression pins for the mood-engine Grafana dashboard."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = REPO_ROOT / "grafana" / "dashboards" / "mood-engines.json"


def _load_dashboard() -> dict:
    with DASHBOARD_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def test_dashboard_file_exists_and_parses() -> None:
    assert DASHBOARD_PATH.is_file()
    _load_dashboard()


def test_dashboard_identity_routes_to_mood_engine_surface() -> None:
    dashboard = _load_dashboard()
    assert dashboard["uid"] == "hapax-mood-engines"
    assert "Mood" in dashboard["title"]
    assert "hapax" in dashboard["tags"]
    assert "mood" in dashboard["tags"]


def test_dashboard_covers_phase_d_metrics() -> None:
    dashboard = _load_dashboard()
    exprs = "\n".join(
        target.get("expr", "")
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    )
    for metric in (
        "mood_arousal_posterior_value",
        "mood_valence_posterior_value",
        "mood_coherence_posterior_value",
        "mood_engine_signals_contributed_total",
        "mood_engine_signals_observed_total",
    ):
        assert metric in exprs


def test_panel_ids_are_unique() -> None:
    dashboard = _load_dashboard()
    ids = [panel.get("id") for panel in dashboard["panels"] if panel.get("id") is not None]
    assert len(ids) == len(set(ids))
