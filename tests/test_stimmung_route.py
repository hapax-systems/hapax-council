"""Tests for logos API stimmung endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from logos.api.app import app


@pytest.fixture(autouse=True)
def _force_private_stream():
    """Pin the stream-mode predicate to private for the full-fidelity tests.

    ``/api/stimmung`` redacts to three banded dimensions when
    ``is_publicly_visible()`` returns True, which is its fail-closed
    default when the shared stream-mode state file is absent (CI, test
    hosts without a warmed-up Council). All four tests in this module
    assert the pre-redaction shape, so pin the predicate here rather
    than duplicate the patch in every test.
    """
    with patch("logos.api.routes.stimmung.is_publicly_visible", return_value=False):
        yield


# Nested format matching SystemStimmung.model_dump_json() output
_SAMPLE_STATE = {
    "overall_stance": "cautious",
    "timestamp": 1743300000,
    "health": {"value": 0.072, "trend": "declining", "freshness_s": 5.0},
    "resource_pressure": {"value": 0.45, "trend": "stable", "freshness_s": 3.0},
    "error_rate": {"value": 0.12, "trend": "stable", "freshness_s": 8.0},
    "processing_throughput": {"value": 0.88, "trend": "rising", "freshness_s": 2.0},
    "perception_confidence": {"value": 0.71, "trend": "stable", "freshness_s": 4.0},
    "llm_cost_pressure": {"value": 0.30, "trend": "falling", "freshness_s": 10.0},
    "grounding_quality": {"value": 0.65, "trend": "stable", "freshness_s": 15.0},
    "operator_stress": {"value": 0.55, "trend": "rising", "freshness_s": 6.0},
    "operator_energy": {"value": 0.60, "trend": "stable", "freshness_s": 7.0},
    "physiological_coherence": {"value": 0.78, "trend": "falling", "freshness_s": 9.0},
}


@pytest.mark.asyncio
async def test_get_stimmung_with_shm(tmp_path: Path) -> None:
    """Returns structured stimmung state from nested shm file."""
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(_SAMPLE_STATE), encoding="utf-8")

    with (
        patch("logos.api.routes.stimmung._SHM_STATE", state_file),
        patch("logos.api.cache.start_refresh_loop", new_callable=AsyncMock),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stimmung")

    assert resp.status_code == 200
    data = resp.json()

    assert data["overall_stance"] == "cautious"
    assert data["timestamp"] == 1743300000
    assert "dimensions" in data

    dims = data["dimensions"]
    assert "health" in dims
    assert dims["health"]["value"] == pytest.approx(0.072)
    assert dims["health"]["trend"] == "declining"
    assert dims["health"]["freshness_s"] == pytest.approx(5.0)

    assert "resource_pressure" in dims
    assert dims["resource_pressure"]["value"] == pytest.approx(0.45)
    assert dims["resource_pressure"]["trend"] == "stable"

    # Verify all 10 dimension keys present
    expected_keys = [
        "health",
        "resource_pressure",
        "error_rate",
        "processing_throughput",
        "perception_confidence",
        "llm_cost_pressure",
        "grounding_quality",
        "operator_stress",
        "operator_energy",
        "physiological_coherence",
    ]
    for key in expected_keys:
        assert key in dims, f"Missing dimension: {key}"
        assert "value" in dims[key], f"Missing value in {key}"
        assert "trend" in dims[key], f"Missing trend in {key}"
        assert "freshness_s" in dims[key], f"Missing freshness_s in {key}"


@pytest.mark.asyncio
async def test_get_stimmung_missing_shm(tmp_path: Path) -> None:
    """Returns unknown state when shm file is absent."""
    missing_file = tmp_path / "nonexistent.json"

    with (
        patch("logos.api.routes.stimmung._SHM_STATE", missing_file),
        patch("logos.api.cache.start_refresh_loop", new_callable=AsyncMock),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stimmung")

    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_stance"] == "unknown"
    assert data["dimensions"] == {}
    assert data["timestamp"] == 0


@pytest.mark.asyncio
async def test_get_stimmung_nested_format_parsed_correctly(tmp_path: Path) -> None:
    """Regression: API must parse nested DimensionReading dicts, not flat keys."""
    state = {
        "overall_stance": "degraded",
        "timestamp": 999,
        "health": {"value": 0.9, "trend": "rising", "freshness_s": 2.0},
        "resource_pressure": {"value": 0.1, "trend": "falling", "freshness_s": 5.0},
    }
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")

    with (
        patch("logos.api.routes.stimmung._SHM_STATE", state_file),
        patch("logos.api.cache.start_refresh_loop", new_callable=AsyncMock),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stimmung")

    data = resp.json()
    dims = data["dimensions"]

    # Must extract nested values, not return 0.0 defaults
    assert dims["health"]["value"] == pytest.approx(0.9)
    assert dims["health"]["trend"] == "rising"
    assert dims["health"]["freshness_s"] == pytest.approx(2.0)
    assert dims["resource_pressure"]["value"] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_get_stimmung_missing_dimension_values_default_to_zero(tmp_path: Path) -> None:
    """Dimensions not present in shm state default to 0.0."""
    state = {"overall_stance": "recovering", "timestamp": 1234}
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")

    with (
        patch("logos.api.routes.stimmung._SHM_STATE", state_file),
        patch("logos.api.cache.start_refresh_loop", new_callable=AsyncMock),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stimmung")

    data = resp.json()
    assert data["overall_stance"] == "recovering"
    dims = data["dimensions"]
    assert dims["health"]["value"] == 0.0
    assert dims["health"]["trend"] == "stable"
    assert dims["health"]["freshness_s"] == 0.0
    assert dims["operator_energy"]["value"] == 0.0
