"""Tests for shared.shader_bounds — Phase 1 of the 2026-04-21
pixel-sort intensity cap amendment."""

from __future__ import annotations

import json
from pathlib import Path

from shared.shader_bounds import NodeCap, clamp_params, load_bounds


def _write_bounds(path: Path, caps: dict) -> None:
    path.write_text(json.dumps({"node_caps": caps}), encoding="utf-8")


def test_load_bounds_returns_node_caps_from_production_file() -> None:
    """Production bounds file ships with pixsort cap — regression pin.

    Tier D of the 2026-04-21 livestream-crispness research tightened
    the pixel-sort family to reduce shader density competing with ward
    chrome. Updated assertions track the production file; reverting the
    bounds requires reverting both the JSON and these expectations together.
    """
    load_bounds.cache_clear()
    bounds = load_bounds()
    assert "pixsort" in bounds
    cap = bounds["pixsort"]
    assert cap.max_strength == 0.85
    assert cap.spatial_coverage_max_pct == 0.35
    assert "threshold_high" in cap.clamp_params
    assert bounds["noise_gen"].max_strength == 0.25
    assert bounds["noise_gen"].clamp_params == ("amplitude",)


def test_load_bounds_missing_file_returns_empty(tmp_path: Path) -> None:
    load_bounds.cache_clear()
    missing = tmp_path / "does-not-exist.json"
    assert load_bounds(missing) == {}


def test_load_bounds_malformed_json_returns_empty(tmp_path: Path) -> None:
    load_bounds.cache_clear()
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    assert load_bounds(bad) == {}


def test_clamp_params_clamps_over_cap() -> None:
    bounds = {
        "pixsort": NodeCap(
            node_type="pixsort",
            max_strength=0.55,
            spatial_coverage_max_pct=0.40,
            clamp_params=("strength", "intensity"),
        )
    }
    out, was_clamped = clamp_params("pixsort", {"strength": 0.9, "intensity": 0.3}, bounds=bounds)
    assert was_clamped is True
    assert out["strength"] == 0.55
    assert out["intensity"] == 0.3  # below cap, passes through


def test_clamp_params_no_clamp_when_under_cap() -> None:
    bounds = {
        "pixsort": NodeCap(
            node_type="pixsort",
            max_strength=0.55,
            spatial_coverage_max_pct=0.40,
            clamp_params=("strength",),
        )
    }
    inp = {"strength": 0.3}
    out, was_clamped = clamp_params("pixsort", inp, bounds=bounds)
    assert was_clamped is False
    # Identity preserved to avoid log spam on hot path
    assert out is inp


def test_clamp_params_unknown_node_type_no_clamp() -> None:
    bounds = {
        "pixsort": NodeCap(
            node_type="pixsort",
            max_strength=0.55,
            spatial_coverage_max_pct=0.40,
            clamp_params=("strength",),
        )
    }
    inp = {"strength": 10.0}
    out, was_clamped = clamp_params("unknown_node", inp, bounds=bounds)
    assert was_clamped is False
    assert out is inp


def test_clamp_params_only_affects_declared_params() -> None:
    """A param not in clamp_params must pass through even if > max_strength."""
    bounds = {
        "pixsort": NodeCap(
            node_type="pixsort",
            max_strength=0.55,
            spatial_coverage_max_pct=0.40,
            clamp_params=("strength",),  # NOT "undeclared_knob"
        )
    }
    out, was_clamped = clamp_params(
        "pixel_sort", {"strength": 0.2, "undeclared_knob": 99.0}, bounds=bounds
    )
    assert was_clamped is False
    assert out["undeclared_knob"] == 99.0


def test_clamp_params_non_numeric_passes_through() -> None:
    bounds = {
        "pixsort": NodeCap(
            node_type="pixsort",
            max_strength=0.55,
            spatial_coverage_max_pct=0.40,
            clamp_params=("strength",),
        )
    }
    out, was_clamped = clamp_params(
        "pixsort",
        {"strength": "not_a_number"},  # type: ignore[dict-item]
        bounds=bounds,
    )
    assert was_clamped is False
    assert out["strength"] == "not_a_number"


def test_load_bounds_roundtrip_custom_file(tmp_path: Path) -> None:
    load_bounds.cache_clear()
    custom = tmp_path / "custom.json"
    _write_bounds(
        custom,
        {
            "my_shader": {
                "max_strength": 0.42,
                "spatial_coverage_max_pct": 0.5,
                "clamp_params": ["amount"],
            }
        },
    )
    bounds = load_bounds(custom)
    assert "my_shader" in bounds
    assert bounds["my_shader"].max_strength == 0.42
    assert bounds["my_shader"].clamp_params == ("amount",)
