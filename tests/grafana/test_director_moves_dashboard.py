"""Regression pin for the director-moves Grafana dashboard JSON.

cc-task ``director-moves-grafana-panel``: the dashboard surfaces 5
goal-defining metrics. This test pins the JSON shape so a future edit
that drops a panel or breaks a query is caught at CI rather than at
operator screenshot time.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = REPO_ROOT / "grafana" / "dashboards" / "director-moves.json"


def _load_dashboard() -> dict:
    with DASHBOARD_PATH.open() as f:
        return json.load(f)


class TestDashboardLoads:
    def test_file_exists(self) -> None:
        assert DASHBOARD_PATH.is_file()

    def test_json_parses(self) -> None:
        _load_dashboard()  # raises if invalid

    def test_has_top_level_required_fields(self) -> None:
        dashboard = _load_dashboard()
        for field in ("title", "description", "panels", "tags"):
            assert field in dashboard, f"dashboard missing field {field!r}"

    def test_title_is_director_moves(self) -> None:
        dashboard = _load_dashboard()
        assert "Director" in dashboard["title"]
        assert "Moves" in dashboard["title"]


class TestPanelInventory:
    """Cc-task acceptance: 5 panels each surfacing a goal-defining metric."""

    def test_has_at_least_5_panels(self) -> None:
        dashboard = _load_dashboard()
        assert len(dashboard["panels"]) >= 5

    def test_each_panel_has_a_unique_id(self) -> None:
        dashboard = _load_dashboard()
        ids = [p.get("id") for p in dashboard["panels"]]
        # Filter Nones (row panels often have null IDs).
        non_null = [i for i in ids if i is not None]
        assert len(non_null) == len(set(non_null)), f"duplicate panel IDs: {ids}"

    def test_each_panel_has_a_title(self) -> None:
        dashboard = _load_dashboard()
        for panel in dashboard["panels"]:
            if panel.get("type") == "row":
                continue  # row panels can be untitled
            assert panel.get("title"), f"panel {panel.get('id')} has no title"


class TestRequiredMetricsCovered:
    """Each of the 5 acceptance metrics must appear in at least one panel
    query (PromQL targets[].expr)."""

    REQUIRED_METRICS = (
        "hapax_random_mode_transition_total",  # transition picks (covers panel 1)
        "hapax_compositor_layout_active",  # layout active gauge
        "hapax_micromove_advance_total",  # u4 micromove counter
        "hapax_semantic_verb_consumed_total",  # u5 verb counter
        "hapax_novelty_shift_impingement_total",  # u3 novelty emitter
    )

    def test_every_required_metric_appears_in_a_query(self) -> None:
        dashboard = _load_dashboard()
        all_exprs: list[str] = []
        for panel in dashboard["panels"]:
            for target in panel.get("targets", []):
                expr = target.get("expr", "")
                if expr:
                    all_exprs.append(expr)
        joined = "\n".join(all_exprs)
        for metric in self.REQUIRED_METRICS:
            assert metric in joined, (
                f"metric {metric!r} not referenced in any panel query; "
                f"cc-task acceptance requires it"
            )


class TestPanelTitlesSemantic:
    """Each panel title must convey what the metric means without 'pending
    consumer' deferrals — those existed before u4/u5 shipped (#2368/#2371)
    and have been resolved."""

    def test_no_pending_u4_marker(self) -> None:
        """U4 shipped via #2368; the dashboard description must not still
        mark micromove panel as pending."""
        dashboard = _load_dashboard()
        for panel in dashboard["panels"]:
            title = panel.get("title", "")
            assert "pending u4" not in title, (
                f"panel {panel.get('id')} still marked 'pending u4' but #2368 merged"
            )

    def test_no_pending_u5_marker(self) -> None:
        """U5 shipped via #2371; the dashboard description must not still
        mark verb panel as pending."""
        dashboard = _load_dashboard()
        for panel in dashboard["panels"]:
            title = panel.get("title", "")
            assert "pending u5" not in title, (
                f"panel {panel.get('id')} still marked 'pending u5' but #2371 merged"
            )


class TestRoutingTags:
    """Folder routing is via tags (operator-managed in Grafana DB)."""

    def test_has_hapax_director_tag(self) -> None:
        dashboard = _load_dashboard()
        tags = set(dashboard.get("tags", []))
        # Either an explicit director tag or the dashboard title routes
        # via the "Hapax / Director / *" naming convention.
        assert "hapax" in tags or "Hapax" in dashboard.get("title", "")
        # Director-related routing is the cc-task's intent; allow either tag
        # form ("director", "directors", "director-moves").
        director_tag = any("director" in t.lower() for t in tags)
        assert director_tag or "Director" in dashboard.get("title", ""), (
            f"dashboard tags {tags!r} don't route to Director folder"
        )
