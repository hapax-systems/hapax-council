"""Reverie prediction monitor — Prometheus metrics + JSON endpoint.

Reads prediction samples from /dev/shm/hapax-reverie/predictions.json
(written by agents/reverie_prediction_monitor.py every 5 minutes) and
exposes as Prometheus gauges on /api/predictions/metrics and JSON on
/api/predictions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Response

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/predictions", tags=["predictions"])

PREDICTIONS_SHM = Path("/dev/shm/hapax-reverie/predictions.json")


def _read_predictions() -> dict:
    try:
        return json.loads(PREDICTIONS_SHM.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@router.get("")
async def get_predictions() -> dict:
    """Return latest prediction monitor sample as JSON."""
    return _read_predictions()


@router.get("/metrics")
async def predictions_metrics() -> Response:
    """Expose prediction metrics in Prometheus text format."""
    data = _read_predictions()
    if not data:
        return Response("# no prediction data available\n", media_type="text/plain")

    lines: list[str] = []
    lines.append("# HELP reverie_prediction_actual Current actual value of each prediction metric")
    lines.append("# TYPE reverie_prediction_actual gauge")
    lines.append(
        "# HELP reverie_prediction_healthy Whether prediction is within expected range (1=yes)"
    )
    lines.append("# TYPE reverie_prediction_healthy gauge")
    lines.append("# HELP reverie_hours_since_deploy Hours elapsed since PR #570 deployment")
    lines.append("# TYPE reverie_hours_since_deploy gauge")
    lines.append("# HELP reverie_alert_count Number of active prediction alerts")
    lines.append("# TYPE reverie_alert_count gauge")

    hours = data.get("hours_since_deploy", 0)
    lines.append(f"reverie_hours_since_deploy {hours}")
    lines.append(f"reverie_alert_count {data.get('alert_count', 0)}")

    for p in data.get("predictions", []):
        name = p.get("name", "unknown")
        actual = p.get("actual", 0)
        healthy = 1 if p.get("healthy", False) else 0
        lines.append(f'reverie_prediction_actual{{prediction="{name}"}} {actual}')
        lines.append(f'reverie_prediction_healthy{{prediction="{name}"}} {healthy}')

    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
