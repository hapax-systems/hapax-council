"""Token-pole path geometry — operator directive 2026-05-07.

Pins:
  - SPIRAL is the default path mode (golden spiral with z-layers)
  - Linear path reachable via HAPAX_TOKEN_POLE_PATH=navel_to_cranium
  - Explosion fires at the path's terminal anchor (centre in spiral,
    cranium in linear)
"""

from __future__ import annotations

import pytest

from agents.studio_compositor import token_pole
from agents.studio_compositor.token_pole import (
    CRANIUM_X,
    CRANIUM_Y,
    NAVEL_X,
    NAVEL_Y,
    NUM_POINTS,
    PathMode,
    _build_linear_path,
    _resolve_path_mode,
)


class TestPathModeResolution:
    def test_default_is_spiral(self, monkeypatch):
        monkeypatch.delenv("HAPAX_TOKEN_POLE_PATH", raising=False)
        assert _resolve_path_mode() is PathMode.SPIRAL

    def test_env_spiral_forces_spiral(self, monkeypatch):
        monkeypatch.setenv("HAPAX_TOKEN_POLE_PATH", "spiral")
        assert _resolve_path_mode() is PathMode.SPIRAL

    def test_env_spiral_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("HAPAX_TOKEN_POLE_PATH", "SPIRAL")
        assert _resolve_path_mode() is PathMode.SPIRAL

    def test_unknown_value_falls_back_to_spiral(self, monkeypatch):
        monkeypatch.setenv("HAPAX_TOKEN_POLE_PATH", "diagonal")
        assert _resolve_path_mode() is PathMode.SPIRAL


class TestLinearPath:
    def test_starts_at_navel_ends_at_cranium(self):
        size = 500
        path = _build_linear_path(size, NUM_POINTS)
        assert len(path) == NUM_POINTS
        x0, y0 = path[0]
        xn, yn = path[-1]
        assert x0 == pytest.approx(NAVEL_X * size)
        assert y0 == pytest.approx(NAVEL_Y * size)
        assert xn == pytest.approx(CRANIUM_X * size)
        assert yn == pytest.approx(CRANIUM_Y * size)

    def test_y_monotonically_decreases(self):
        # Path goes bottom→top on the figure; pixel y decreases.
        path = _build_linear_path(500, NUM_POINTS)
        ys = [y for _, y in path]
        assert all(ys[i + 1] <= ys[i] for i in range(len(ys) - 1))

    def test_scales_with_size(self):
        p100 = _build_linear_path(100, NUM_POINTS)
        p500 = _build_linear_path(500, NUM_POINTS)
        assert p500[0][0] == pytest.approx(p100[0][0] * 5)
        assert p500[-1][1] == pytest.approx(p100[-1][1] * 5)


class TestConstructorHonoursMode:
    def test_default_constructor_uses_spiral_path(self, monkeypatch):
        monkeypatch.delenv("HAPAX_TOKEN_POLE_PATH", raising=False)
        src = token_pole.TokenPoleCairoSource()
        assert src._path_mode is PathMode.SPIRAL
        ys = [p[1] for p in src._spiral]
        non_monotonic = any(ys[i + 1] > ys[i] for i in range(len(ys) - 1))
        assert non_monotonic, "spiral expected to wind — not monotonic in y"

    def test_env_override_selects_linear(self, monkeypatch):
        monkeypatch.setenv("HAPAX_TOKEN_POLE_PATH", "navel_to_cranium")
        src = token_pole.TokenPoleCairoSource()
        assert src._path_mode is PathMode.NAVEL_TO_CRANIUM
        x0, y0 = src._spiral[0]
        xn, yn = src._spiral[-1]
        assert y0 > yn


class TestExplosionLocation:
    def test_default_spiral_explodes_at_centre(self, monkeypatch):
        monkeypatch.delenv("HAPAX_TOKEN_POLE_PATH", raising=False)
        src = token_pole.TokenPoleCairoSource()
        src._particles.clear()
        src._spawn_explosion()
        cx = token_pole.NATURAL_SIZE * token_pole.SPIRAL_CENTER_X
        cy = token_pole.NATURAL_SIZE * token_pole.SPIRAL_CENTER_Y
        for p in src._particles:
            assert p.x == pytest.approx(cx)
            assert p.y == pytest.approx(cy)

    def test_linear_mode_explodes_at_cranium(self, monkeypatch):
        monkeypatch.setenv("HAPAX_TOKEN_POLE_PATH", "navel_to_cranium")
        src = token_pole.TokenPoleCairoSource()
        src._particles.clear()
        src._spawn_explosion()
        cx = token_pole.NATURAL_SIZE * CRANIUM_X
        cy = token_pole.NATURAL_SIZE * CRANIUM_Y
        for p in src._particles:
            assert p.x == pytest.approx(cx)
            assert p.y == pytest.approx(cy)
