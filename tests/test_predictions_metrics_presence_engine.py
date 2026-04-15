"""Smoke test for the `hapax_presence_*` metrics on /api/predictions/metrics.

Queue #224 adds three metrics that surface PresenceEngine state:

- `hapax_presence_signal_fired_total{signal="..."}` — counter per signal
- `hapax_presence_posterior` — Bayesian posterior gauge
- `hapax_presence_state` — hysteresis state enum (0/1/2)

This test drives the endpoint with a synthetic presence-metrics.json and
asserts each metric lands in the text output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from logos.api.routes import predictions as predictions_route


@pytest.fixture
def fake_shm(tmp_path: Path, monkeypatch):
    """Redirect every file the endpoint reads into tmp_path."""
    predictions_shm = tmp_path / "predictions.json"
    predictions_shm.write_text(json.dumps({"hours_since_deploy": 0, "predictions": []}))
    presence_metrics = tmp_path / "presence-metrics.json"
    monkeypatch.setattr(predictions_route, "PREDICTIONS_SHM", predictions_shm)
    monkeypatch.setattr(predictions_route, "PRESENCE_METRICS_FILE", presence_metrics)
    return {"presence_metrics": presence_metrics}


@pytest.mark.asyncio
async def test_presence_metrics_render(fake_shm):
    presence_metrics: Path = fake_shm["presence_metrics"]
    presence_metrics.write_text(
        json.dumps(
            {
                "signal_fire_counts": {
                    "keyboard_active": 42,
                    "desk_active": 7,
                    "operator_face": 0,
                },
                "posterior": 0.834,
                "state": "PRESENT",
                "state_enum": 2,
                "ts": 1_775_000_000.0,
            }
        )
    )

    response = await predictions_route.predictions_metrics()
    body = response.body.decode("utf-8")

    assert 'hapax_presence_signal_fired_total{signal="keyboard_active"} 42' in body
    assert 'hapax_presence_signal_fired_total{signal="desk_active"} 7' in body
    assert 'hapax_presence_signal_fired_total{signal="operator_face"} 0' in body
    assert "hapax_presence_posterior 0.834" in body
    assert "hapax_presence_state 2" in body


@pytest.mark.asyncio
async def test_presence_metrics_absent_when_file_missing(fake_shm):
    # File intentionally not written. Endpoint must render without raising
    # and without emitting value lines for the three gauges.
    response = await predictions_route.predictions_metrics()
    body = response.body.decode("utf-8")

    # Help/TYPE headers are always emitted for series stability.
    assert "# TYPE hapax_presence_signal_fired_total counter" in body
    assert "# TYPE hapax_presence_posterior gauge" in body
    assert "# TYPE hapax_presence_state gauge" in body
    # But no value lines.
    assert "hapax_presence_signal_fired_total{" not in body.replace("# TYPE", "")
    assert "\nhapax_presence_posterior " not in body
    assert "\nhapax_presence_state " not in body


@pytest.mark.asyncio
async def test_presence_metrics_skip_non_numeric_counts(fake_shm):
    """Garbage values should be skipped, not crash the endpoint."""
    presence_metrics: Path = fake_shm["presence_metrics"]
    presence_metrics.write_text(
        json.dumps(
            {
                "signal_fire_counts": {
                    "keyboard_active": "not a number",
                    "desk_active": 3,
                },
                "posterior": 0.5,
                "state": "UNCERTAIN",
                "state_enum": 1,
            }
        )
    )

    response = await predictions_route.predictions_metrics()
    body = response.body.decode("utf-8")

    assert 'hapax_presence_signal_fired_total{signal="desk_active"} 3' in body
    assert 'hapax_presence_signal_fired_total{signal="keyboard_active"}' not in body
    assert "hapax_presence_state 1" in body
