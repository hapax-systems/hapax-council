#!/usr/bin/env python3
"""Provision Grafana dashboards for Hapax operational health and behavioral predictions."""

import base64
import json
import sys
import urllib.request

GRAFANA_URL = "http://localhost:3001"
AUTH = base64.b64encode(b"admin:hapax").decode()
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Basic {AUTH}",
}


def api(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{GRAFANA_URL}{path}", data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_datasource_uid() -> str:
    ds_list = api("GET", "/api/datasources")
    for ds in ds_list:
        if ds["name"] == "Prometheus":
            return ds["uid"]
    print("ERROR: Prometheus datasource not found")
    sys.exit(1)


def prom_target(expr: str, legend: str = "") -> dict:
    return {
        "refId": "A",
        "expr": expr,
        "legendFormat": legend,
        "datasource": {"type": "prometheus", "uid": DS_UID},
    }


def timeseries_panel(
    title: str,
    targets: list[dict],
    grid_pos: dict,
    thresholds: list[dict] | None = None,
    override_time_range: dict | None = None,
) -> dict:
    panel = {
        "type": "timeseries",
        "title": title,
        "gridPos": grid_pos,
        "targets": targets,
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "fillOpacity": 10,
                    "pointSize": 5,
                    "showPoints": "auto",
                },
            },
            "overrides": [],
        },
        "options": {
            "tooltip": {"mode": "multi"},
            "legend": {"displayMode": "table", "placement": "bottom"},
        },
    }
    if thresholds:
        panel["fieldConfig"]["defaults"]["thresholds"] = {
            "mode": "absolute",
            "steps": thresholds,
        }
        panel["fieldConfig"]["defaults"]["custom"]["thresholdsStyle"] = {"mode": "line"}
    if override_time_range:
        panel["timeFrom"] = override_time_range.get("from")
    return panel


def stat_panel(
    title: str,
    targets: list[dict],
    grid_pos: dict,
    thresholds: list[dict] | None = None,
) -> dict:
    th = thresholds or [{"color": "green", "value": None}]
    return {
        "type": "stat",
        "title": title,
        "gridPos": grid_pos,
        "targets": targets,
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "fieldConfig": {
            "defaults": {
                "thresholds": {"mode": "absolute", "steps": th},
            },
            "overrides": [],
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background"},
    }


def bargauge_panel(
    title: str,
    targets: list[dict],
    grid_pos: dict,
) -> dict:
    return {
        "type": "bargauge",
        "title": title,
        "gridPos": grid_pos,
        "targets": targets,
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "fieldConfig": {
            "defaults": {
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "yellow", "value": 50},
                        {"color": "red", "value": 100},
                    ],
                },
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "displayMode": "gradient",
            "orientation": "horizontal",
        },
    }


def row_panel(title: str, y: int, collapsed: bool = True) -> dict:
    return {
        "type": "row",
        "title": title,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": collapsed,
        "panels": [],
    }


def make_target(expr: str, legend: str, ref_id: str = "A") -> dict:
    return {
        "refId": ref_id,
        "expr": expr,
        "legendFormat": legend,
        "datasource": {"type": "prometheus", "uid": DS_UID},
    }


# ─── Dashboard 1: Operational Health ─────────────────────────────────────────


def build_operational_health() -> dict:
    panels = []
    y = 0

    # Row 1: SCM Mesh Health
    row1 = row_panel("SCM Mesh Health", y)
    y += 1
    row1["panels"] = [
        timeseries_panel(
            "Mesh Error",
            [make_target("hapax_mesh_error", "{{component}}")],
            {"h": 8, "w": 12, "x": 0, "y": y},
            thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 0.5}],
        ),
        timeseries_panel(
            "Mesh Perception",
            [make_target("hapax_mesh_perception", "{{component}}")],
            {"h": 8, "w": 12, "x": 12, "y": y},
        ),
    ]
    panels.append(row1)
    y += 9

    # Row 2: Stimmung
    row2 = row_panel("Stimmung", y)
    y += 1
    row2["panels"] = [
        timeseries_panel(
            "Stimmung Dimensions",
            [make_target("hapax_stimmung_value", "{{dimension}}")],
            {"h": 8, "w": 10, "x": 0, "y": y},
        ),
        stat_panel(
            "Stance",
            [make_target("hapax_stimmung_stance", "")],
            {"h": 8, "w": 4, "x": 10, "y": y},
            thresholds=[
                {"color": "green", "value": None},
                {"color": "yellow", "value": 0.1},
                {"color": "orange", "value": 0.25},
                {"color": "#EF843C", "value": 0.5},
                {"color": "red", "value": 1.0},
            ],
        ),
        timeseries_panel(
            "Dimension Freshness",
            [make_target("hapax_stimmung_freshness_s", "{{dimension}}")],
            {"h": 8, "w": 10, "x": 14, "y": y},
        ),
    ]
    panels.append(row2)
    y += 9

    # Row 3: Exploration Signals
    row3 = row_panel("Exploration Signals", y)
    y += 1
    row3["panels"] = [
        timeseries_panel(
            "Boredom by Component",
            [make_target("hapax_exploration_boredom", "{{component}}")],
            {"h": 8, "w": 8, "x": 0, "y": y},
        ),
        timeseries_panel(
            "Curiosity by Component",
            [make_target("hapax_exploration_curiosity", "{{component}}")],
            {"h": 8, "w": 8, "x": 8, "y": y},
        ),
        timeseries_panel(
            "Chronic Error",
            [make_target("hapax_exploration_error", "{{component}}")],
            {"h": 8, "w": 8, "x": 16, "y": y},
        ),
    ]
    panels.append(row3)
    y += 9

    # Row 4: Content & Sources
    row4 = row_panel("Content & Sources", y)
    y += 1
    row4["panels"] = [
        stat_panel(
            "Active Sources",
            [make_target("hapax_content_sources_active", "")],
            {"h": 6, "w": 8, "x": 0, "y": y},
        ),
        stat_panel(
            "DMN Buffer",
            [make_target("hapax_dmn_buffer_entries", "")],
            {"h": 6, "w": 8, "x": 8, "y": y},
        ),
        stat_panel(
            "Satellites Active",
            [make_target("hapax_dmn_satellites_active", "")],
            {"h": 6, "w": 8, "x": 16, "y": y},
        ),
    ]
    panels.append(row4)
    y += 7

    # Row 5: CPAL
    row5 = row_panel("CPAL", y)
    y += 1
    row5["panels"] = [
        timeseries_panel(
            "CPAL Gain",
            [make_target("hapax_cpal_gain", "")],
            {"h": 8, "w": 12, "x": 0, "y": y},
        ),
        timeseries_panel(
            "CPAL Errors",
            [make_target("hapax_cpal_error", "{{domain}}")],
            {"h": 8, "w": 12, "x": 12, "y": y},
        ),
    ]
    panels.append(row5)
    y += 9

    # Row 6: Feature Flags
    row6 = row_panel("Feature Flags", y)
    y += 1
    row6["panels"] = [
        stat_panel(
            "World Routing",
            [make_target('hapax_feature_flag{flag="world_routing"}', "")],
            {"h": 6, "w": 8, "x": 0, "y": y},
            thresholds=[
                {"color": "red", "value": None},
                {"color": "green", "value": 1},
            ],
        ),
    ]
    panels.append(row6)

    return {
        "dashboard": {
            "uid": "hapax-operational-health",
            "title": "Hapax \u2014 Operational Health",
            "tags": ["hapax", "operational"],
            "timezone": "browser",
            "schemaVersion": 39,
            "refresh": "30s",
            "time": {"from": "now-1h", "to": "now"},
            "panels": panels,
        },
        "overwrite": True,
    }


# ─── Dashboard 2: Behavioral Predictions ─────────────────────────────────────


def build_behavioral_predictions() -> dict:
    panels = []
    y = 0

    # Row 1: Realtime (seconds) — open by default
    row1 = row_panel("Realtime (seconds)", y, collapsed=False)
    panels.append(row1)
    y += 1

    panels.append(
        timeseries_panel(
            "Shader Uniforms",
            [make_target("topk(10, hapax_uniform_deviation)", "{{__name__}}")],
            {"h": 8, "w": 6, "x": 0, "y": y},
        )
    )
    panels.append(
        timeseries_panel(
            "Imagination Dimensions",
            [make_target("hapax_imagination_dimension", "{{dim}}")],
            {"h": 8, "w": 6, "x": 6, "y": y},
        )
    )
    panels.append(
        timeseries_panel(
            "Imagination Salience",
            [make_target("hapax_imagination_salience", "")],
            {"h": 8, "w": 6, "x": 12, "y": y},
            thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 0.55}],
        )
    )
    panels.append(
        timeseries_panel(
            "Technique Confidence",
            [make_target("reverie_technique_confidence", "{{technique}}")],
            {"h": 8, "w": 6, "x": 18, "y": y},
        )
    )
    y += 9

    # Row 2: Fast (minutes)
    row2 = row_panel("Fast (minutes)", y)
    panels.append(row2)
    y += 1
    row2["panels"] = [
        timeseries_panel(
            "Technique Rate",
            [make_target("reverie_technique_rate", "{{technique}}")],
            {"h": 8, "w": 12, "x": 0, "y": y},
        ),
        timeseries_panel(
            "Presence Posterior",
            [make_target("reverie_presence_posterior", "")],
            {"h": 8, "w": 12, "x": 12, "y": y},
        ),
    ]
    y += 9

    # Row 3: Slow (hours)
    row3 = row_panel("Slow (hours)", y)
    y += 1
    row3["panels"] = [
        timeseries_panel(
            "Thompson Convergence",
            [make_target("topk(15, hapax_thompson_mean)", "{{__name__}}")],
            {"h": 8, "w": 8, "x": 0, "y": y},
        ),
        bargauge_panel(
            "Capability Uses",
            [make_target("topk(15, hapax_capability_uses)", "{{__name__}}")],
            {"h": 8, "w": 8, "x": 8, "y": y},
        ),
        stat_panel(
            "Hebbian Associations",
            [make_target("hapax_hebbian_associations", "")],
            {"h": 8, "w": 8, "x": 16, "y": y},
        ),
    ]
    y_inner = y + 8
    row3["panels"].append(
        timeseries_panel(
            "Original Predictions (P1-P6)",
            [make_target("reverie_prediction_actual", "{{prediction}}")],
            {"h": 8, "w": 24, "x": 0, "y": y_inner},
        ),
    )
    panels.append(row3)
    y = y_inner + 9

    # Row 4: Structural (days) — 7d time range
    row4 = row_panel("Structural (days)", y)
    y += 1
    row4["panels"] = [
        stat_panel(
            "Prediction Health",
            [make_target("reverie_prediction_healthy", "{{prediction}}")],
            {"h": 6, "w": 24, "x": 0, "y": y},
            thresholds=[
                {"color": "red", "value": None},
                {"color": "green", "value": 1},
            ],
        ),
    ]
    # Override time range for this panel
    row4["panels"][0]["timeFrom"] = "7d"
    panels.append(row4)

    return {
        "dashboard": {
            "uid": "hapax-behavioral-predictions",
            "title": "Hapax \u2014 Behavioral Predictions",
            "tags": ["hapax", "predictions", "reverie"],
            "timezone": "browser",
            "schemaVersion": 39,
            "refresh": "10s",
            "time": {"from": "now-30m", "to": "now"},
            "panels": panels,
        },
        "overwrite": True,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    DS_UID = get_datasource_uid()
    print(f"Prometheus datasource UID: {DS_UID}")

    for name, builder in [
        ("Operational Health", build_operational_health),
        ("Behavioral Predictions", build_behavioral_predictions),
    ]:
        payload = builder()
        result = api("POST", "/api/dashboards/db", payload)
        uid = payload["dashboard"]["uid"]
        print(f"  {name}: {result.get('status', 'ok')} — {GRAFANA_URL}/d/{uid}")

    print("\nDone. Both dashboards provisioned.")
