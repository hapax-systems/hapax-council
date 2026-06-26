"""Tests for LRR Phase 6 §4.A per-route stream-mode redaction wiring.

Each test sets ``is_publicly_visible`` for the target route, calls the
route handler directly, and asserts the spec-required behavior. Pairs
each public-visible test with a private-visible negative to catch
over-redaction.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

# ── /api/stimmung — band 3 dims, omit 8, drop topology when public ──────────


@pytest.fixture
def stimmung_state(tmp_path, monkeypatch):
    """Fake stimmung shm state with all 11 dimensions populated."""
    state = {
        "overall_stance": "nominal",
        "timestamp": 1234567890,
        "operator_energy": {"value": 0.8, "trend": "rising", "freshness_s": 1.5},
        "physiological_coherence": {"value": 0.6, "trend": "stable", "freshness_s": 2.0},
        "operator_stress": {"value": 0.2, "trend": "falling", "freshness_s": 1.0},
        "health": {"value": 0.95, "trend": "stable", "freshness_s": 5.0},
        "resource_pressure": {"value": 0.4, "trend": "stable", "freshness_s": 3.0},
        "local_capacity_pressure": {"value": 0.75, "trend": "rising", "freshness_s": 2.0},
        "error_rate": {"value": 0.05, "trend": "stable", "freshness_s": 4.0},
        "processing_throughput": {"value": 0.85, "trend": "rising", "freshness_s": 2.0},
        "perception_confidence": {"value": 0.9, "trend": "stable", "freshness_s": 1.0},
        "llm_cost_pressure": {"value": 0.3, "trend": "stable", "freshness_s": 6.0},
        "grounding_quality": {"value": 0.75, "trend": "stable", "freshness_s": 1.5},
        "exploration_deficit": {"value": 0.4, "trend": "stable", "freshness_s": 2.5},
    }
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))
    monkeypatch.setattr("logos.api.routes.stimmung._SHM_STATE", state_file)
    return state


class TestStimmungRedaction:
    def test_missing_local_capacity_pressure_is_not_reported_fresh(self):
        from logos.api.routes.stimmung import _build_dimensions

        dimensions = _build_dimensions(
            {
                "health": {"value": 0.95, "trend": "stable", "freshness_s": 5.0},
                "resource_pressure": {"value": 0.4, "trend": "stable", "freshness_s": 3.0},
            }
        )
        assert "local_capacity_pressure" not in dimensions

    @pytest.mark.asyncio
    async def test_private_returns_full_dimensions(self, stimmung_state, monkeypatch):
        monkeypatch.setattr("logos.api.routes.stimmung.is_publicly_visible", lambda: False)
        # Stub topology/eigenform so the endpoint doesn't try real subsystems
        monkeypatch.setattr(
            "logos.api.routes.stimmung.compute_restriction_consistency",
            lambda: {"score": 1.0},
        )
        monkeypatch.setattr("logos.api.routes.stimmung.build_scm_graph", lambda: object())
        monkeypatch.setattr(
            "logos.api.routes.stimmung.compute_topological_stability",
            lambda g: {"score": 1.0},
        )
        monkeypatch.setattr(
            "logos.api.routes.stimmung.analyze_convergence",
            lambda: {"converged": True},
        )

        from logos.api.routes.stimmung import get_stimmung

        result = await get_stimmung()
        assert "operator_energy" in result["dimensions"]
        assert "health" in result["dimensions"]
        assert "local_capacity_pressure" in result["dimensions"]
        assert isinstance(result["dimensions"]["operator_energy"]["value"], float)
        assert "topology" in result
        assert "eigenform" in result

    @pytest.mark.asyncio
    async def test_public_bands_three_dims(self, stimmung_state, monkeypatch):
        monkeypatch.setattr("logos.api.routes.stimmung.is_publicly_visible", lambda: True)

        from logos.api.routes.stimmung import get_stimmung

        result = await get_stimmung()
        # only 3 dims present; each carries band label not value
        assert set(result["dimensions"].keys()) == {
            "operator_energy",
            "physiological_coherence",
            "operator_stress",
        }
        assert result["dimensions"]["operator_energy"]["band"] == "high"  # 0.8 > 0.66
        assert result["dimensions"]["physiological_coherence"]["band"] == "coherent"  # 0.6 > 0.5
        assert result["dimensions"]["operator_stress"]["band"] == "relaxed"  # 0.2 <= 0.33
        # numeric value field gone
        assert "value" not in result["dimensions"]["operator_energy"]
        # non-banded dims omitted
        assert "health" not in result["dimensions"]
        assert "resource_pressure" not in result["dimensions"]
        assert "local_capacity_pressure" not in result["dimensions"]
        # categorical stance retained
        assert result["overall_stance"] == "nominal"
        # system-internals dropped on public stream
        assert "topology" not in result
        assert "eigenform" not in result
        assert "sheaf_health" not in result


# ── /api/profile/{dimension} — 403 wholesale ────────────────────────────────


class TestProfileDimensionRedaction:
    def test_dependency_is_require_private_stream(self):
        """Verify the route declares require_private_stream as a dependency."""
        from fastapi.routing import APIRoute

        from logos.api.deps.stream_redaction import require_private_stream
        from logos.api.routes.profile import router

        get_dim_route = next(
            r
            for r in router.routes
            if isinstance(r, APIRoute) and r.path == "/api/profile/{dimension}"
        )
        dep_funcs = [d.dependency for d in get_dim_route.dependencies]
        assert require_private_stream in dep_funcs


# ── /api/management — 403 wholesale ─────────────────────────────────────────


class TestManagementRedaction:
    def test_dependency_is_require_private_stream(self):
        from fastapi.routing import APIRoute

        from logos.api.deps.stream_redaction import require_private_stream
        from logos.api.routes.data import router

        management_route = next(
            r for r in router.routes if isinstance(r, APIRoute) and r.path == "/api/management"
        )
        dep_funcs = [d.dependency for d in management_route.dependencies]
        assert require_private_stream in dep_funcs


# ── /api/studio/perception — band heart_rate + hrv, omit skin_temp + sleep ──


class TestPerceptionRedaction:
    def _fake_perception(self, tmp_path, monkeypatch):
        perc = {
            "operator_present": True,
            "presence_score": 0.92,
            "flow": 0.7,
            "heart_rate_bpm": 130,  # > 110 → critical
            "hrv_ms": 25,  # <= 30 → reduced
            "skin_temperature_c": 36.7,
            "sleep_stage": "awake",
        }
        perc_file = tmp_path / "perception-state.json"
        perc_file.write_text(json.dumps(perc))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path.parent)
        # Construct the path the route uses: home / .cache / hapax-daimonion / ...
        target = tmp_path.parent / ".cache" / "hapax-daimonion"
        target.mkdir(parents=True, exist_ok=True)
        (target / "perception-state.json").write_text(json.dumps(perc))

    @pytest.mark.asyncio
    async def test_private_returns_raw_biometrics(self, tmp_path, monkeypatch):
        self._fake_perception(tmp_path, monkeypatch)
        monkeypatch.setattr("logos.api.routes.studio.is_publicly_visible", lambda: False)

        from logos.api.routes.studio import get_perception_state

        result = await get_perception_state()
        assert result["heart_rate_bpm"] == 130
        assert result["hrv_ms"] == 25
        assert result["skin_temperature_c"] == 36.7
        assert result["sleep_stage"] == "awake"

    @pytest.mark.asyncio
    async def test_public_bands_and_omits(self, tmp_path, monkeypatch):
        self._fake_perception(tmp_path, monkeypatch)
        monkeypatch.setattr("logos.api.routes.studio.is_publicly_visible", lambda: True)
        # omit_if_public internally re-checks via the deps module — patch there too
        monkeypatch.setattr("logos.api.deps.stream_redaction._is_publicly_visible", lambda: True)

        from logos.api.routes.studio import get_perception_state

        result = await get_perception_state()
        # banded
        assert result["heart_rate_band"] == "critical"
        assert result["hrv_band"] == "reduced"
        assert "heart_rate_bpm" not in result
        assert "hrv_ms" not in result
        # omitted
        assert "skin_temperature_c" not in result
        assert "sleep_stage" not in result
        # categorical/structural pass-through
        assert result["operator_present"] is True
        assert result["presence_score"] == 0.92
        assert result["flow"] == 0.7


# ── require_private_stream dependency: 403 enumeration ─────────────────────


class TestRequirePrivateStreamRaises:
    """Sanity: when stream is publicly visible, the dep raises 403 and the
    routes that depend on it cannot be reached. Existing test coverage in
    test_stream_redaction.py exercises the dep itself; this test pins the
    integration with the new routes by direct call."""

    def test_raises_403_when_public(self, monkeypatch):
        monkeypatch.setattr("logos.api.deps.stream_redaction._is_publicly_visible", lambda: True)
        from logos.api.deps.stream_redaction import require_private_stream

        with pytest.raises(HTTPException) as exc:
            require_private_stream()
        assert exc.value.status_code == 403
        assert "redacted_stream_mode_public" in str(exc.value.detail)
