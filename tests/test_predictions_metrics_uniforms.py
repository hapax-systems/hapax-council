"""Smoke test for the uniforms coverage gauges on /api/predictions/metrics.

Delta PR-3 adds three gauges that specifically pin the bridge-drought
class of failure fixed by PR #696:

- ``reverie_uniforms_key_count`` — current numeric keys in uniforms.json
- ``reverie_uniforms_plan_defaults_count`` — keys the plan declares
- ``reverie_uniforms_key_deficit`` — max(0, plan - live), drought tripwire

This test drives the endpoint's text output with fake on-disk state and
asserts the gauges land.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from logos.api.routes import predictions as predictions_route


def _build_plan(passes: list[dict]) -> dict:
    return {"version": 2, "targets": {"main": {"passes": passes}}}


@pytest.fixture
def fake_shm(tmp_path: Path, monkeypatch):
    """Redirect the endpoint's file readers into tmp_path."""
    uniforms_file = tmp_path / "uniforms.json"
    plan_file = tmp_path / "plan.json"
    predictions_shm = tmp_path / "predictions.json"
    predictions_shm.write_text(json.dumps({"hours_since_deploy": 0, "predictions": []}))
    monkeypatch.setattr(predictions_route, "UNIFORMS_FILE", uniforms_file)
    monkeypatch.setattr(predictions_route, "PLAN_FILE", plan_file)
    monkeypatch.setattr(predictions_route, "PREDICTIONS_SHM", predictions_shm)
    return {"uniforms_file": uniforms_file, "plan_file": plan_file}


@pytest.mark.asyncio
async def test_coverage_gauges_in_text_output(fake_shm):
    uniforms_file: Path = fake_shm["uniforms_file"]
    plan_file: Path = fake_shm["plan_file"]

    uniforms_file.write_text(json.dumps({"noise.amplitude": 0.7, "color.brightness": 1.0}))
    plan_file.write_text(
        json.dumps(
            _build_plan(
                [
                    {"node_id": "noise", "uniforms": {"amplitude": 0.7}},
                    {"node_id": "color", "uniforms": {"brightness": 1.0}},
                    {"node_id": "drift", "uniforms": {"speed": 0.5}},
                ]
            )
        )
    )

    response = await predictions_route.predictions_metrics()
    body = response.body.decode("utf-8")

    assert "reverie_uniforms_key_count 2" in body
    assert "reverie_uniforms_plan_defaults_count 3" in body
    assert "reverie_uniforms_key_deficit 1" in body


@pytest.mark.asyncio
async def test_coverage_gauges_healthy_deficit_zero(fake_shm):
    uniforms_file: Path = fake_shm["uniforms_file"]
    plan_file: Path = fake_shm["plan_file"]

    uniforms_file.write_text(json.dumps({"noise.amplitude": 0.7}))
    plan_file.write_text(
        json.dumps(_build_plan([{"node_id": "noise", "uniforms": {"amplitude": 0.7}}]))
    )

    response = await predictions_route.predictions_metrics()
    body = response.body.decode("utf-8")

    assert "reverie_uniforms_key_count 1" in body
    assert "reverie_uniforms_plan_defaults_count 1" in body
    assert "reverie_uniforms_key_deficit 0" in body


@pytest.mark.asyncio
async def test_coverage_gauges_detect_drought(fake_shm):
    """The drought tripwire fires when deficit exceeds the plan by a lot."""
    uniforms_file: Path = fake_shm["uniforms_file"]
    plan_file: Path = fake_shm["plan_file"]

    # Plan declares 10 defaults, uniforms writes only 1 — a 9-key deficit.
    passes = [{"node_id": f"n{i}", "uniforms": {"p": 0.0}} for i in range(10)]
    plan_file.write_text(json.dumps(_build_plan(passes)))
    uniforms_file.write_text(json.dumps({"n0.p": 0.0}))

    response = await predictions_route.predictions_metrics()
    body = response.body.decode("utf-8")

    assert "reverie_uniforms_key_count 1" in body
    assert "reverie_uniforms_plan_defaults_count 10" in body
    assert "reverie_uniforms_key_deficit 9" in body
