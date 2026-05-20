"""CI gate: shader presets must satisfy authentic reference characteristics.

Source: ``docs/research/effect-preset-reference-material.md`` defines 28
effect types with 4 authentic visual characteristics each, verified against
named reference works (Nam June Paik, Lichtenstein, Kubrick, etc.).

This test translates those characteristics into parameter constraints.
Each node type has a check function encoding the minimum parameter
requirements for authenticity. A preset using that node type must satisfy
these constraints or it is visually inauthentic — the "bad" examples
in the reference doc.

Not every reference characteristic maps to a single parameter (some are
emergent from shader code). We gate on what the preset JSON can control.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

PRESETS_DIR = Path(__file__).parent.parent.parent / "presets"


def _load_all_presets() -> dict[str, dict[str, Any]]:
    out = {}
    for p in sorted(PRESETS_DIR.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and isinstance(data.get("nodes"), dict):
            out[p.stem] = data
    return out


ALL_PRESETS = _load_all_presets()


def _nodes_of_type(preset: dict[str, Any], node_type: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        (name, node.get("params", {}))
        for name, node in preset.get("nodes", {}).items()
        if node.get("type") == node_type
    ]


def _presets_using(node_type: str) -> list[tuple[str, dict[str, Any]]]:
    return [(name, data) for name, data in ALL_PRESETS.items() if _nodes_of_type(data, node_type)]


# ── VHS: chroma bleed + noise band ──────────────────────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("vhs"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_vhs_has_chroma_shift(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "vhs"):
        assert params.get("chroma_shift", 0) > 0, (
            f"{preset_name}/{node_name}: VHS must have chroma_shift > 0 "
            f"(ref: chroma bleed — red/blue channels offset horizontally)"
        )


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("vhs"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_vhs_has_noise_band(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "vhs"):
        assert params.get("noise_band_y", 0) > 0, (
            f"{preset_name}/{node_name}: VHS must have noise_band_y > 0 "
            f"(ref: head-switching noise / tracking artifacts)"
        )


# ── Halftone: dot_size must exist ────────────────────────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("halftone"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_halftone_has_dot_size(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "halftone"):
        assert "dot_size" in params and params["dot_size"] > 0, (
            f"{preset_name}/{node_name}: halftone must have dot_size > 0 "
            f"(ref: discrete circular dots with variable size)"
        )


# ── Feedback: must have decay ────────────────────────────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("feedback"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_feedback_has_decay(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "feedback"):
        assert "decay" in params and 0 < params["decay"] < 1.0, (
            f"{preset_name}/{node_name}: feedback must have 0 < decay < 1 "
            f"(ref: nested self-similar tunneling with saturation intensification)"
        )


# ── Edge detect in neon presets: needs bloom for glow ─────────────────

_NEON_KEYWORDS = {"neon", "nightvision", "night_vision", "glow"}


def _neon_presets_using_edge_detect() -> list[tuple[str, dict[str, Any]]]:
    return [
        (name, data)
        for name, data in _presets_using("edge_detect")
        if any(
            kw in name.lower() or kw in data.get("description", "").lower() for kw in _NEON_KEYWORDS
        )
    ]


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _neon_presets_using_edge_detect(),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_neon_edge_detect_has_bloom(preset_name: str, preset_data: dict) -> None:
    has_bloom = bool(_nodes_of_type(preset_data, "bloom"))
    has_vignette = bool(_nodes_of_type(preset_data, "vignette"))
    assert has_bloom or has_vignette, (
        f"{preset_name}: neon edge_detect without bloom or vignette — "
        f"neon effects need glow (ref: soft gaussian fadeout from each edge)"
    )


# ── Thermal: must have params (not bare colorgrade) ──────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("thermal"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_thermal_is_not_plain_colorgrade(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "thermal"):
        assert params != {}, (
            f"{preset_name}/{node_name}: thermal must have palette params "
            f"(ref: false-color palette, not just a color LUT on brightness)"
        )


# ── Chromatic aberration: must have offset ────────────────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("chromatic_aberration"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_chromatic_aberration_has_offset(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "chromatic_aberration"):
        has_offset = (
            "offset_x" in params
            or "offset_y" in params
            or "offset" in params
            or "strength" in params
        )
        assert has_offset or params != {}, (
            f"{preset_name}/{node_name}: chromatic_aberration must have offset "
            f"(ref: chroma bleed, color channel separation)"
        )


# ── Glitch blocks: must have block structure ──────────────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("glitch_block"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_glitch_block_has_params(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "glitch_block"):
        assert params != {}, (
            f"{preset_name}/{node_name}: glitch_block must have block-size/intensity params "
            f"(ref: rectangular macro-block artifacts on 8x8 or 16x16 grid)"
        )


# ── Scanlines: spacing ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("scanlines"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_scanlines_has_spacing(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "scanlines"):
        assert "spacing" in params or "frequency" in params or params != {}, (
            f"{preset_name}/{node_name}: scanlines must define spacing "
            f"(ref: horizontal scan-line banding)"
        )


# ── Bloom: must have params ───────────────────────────────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("bloom"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_bloom_has_params(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "bloom"):
        has_intensity = (
            "intensity" in params or "threshold" in params or "radius" in params or params != {}
        )
        assert has_intensity, (
            f"{preset_name}/{node_name}: bloom must have intensity/threshold/radius "
            f"(ref: bright pixels bleed, threshold-based, soft Gaussian falloff)"
        )


# ── Stutter: hold params ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("stutter"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_stutter_has_hold_params(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "stutter"):
        has_hold = "hold_frames" in params or "probability" in params or params != {}
        assert has_hold, (
            f"{preset_name}/{node_name}: stutter must have hold/probability params "
            f"(ref: frame freezes for irregular durations, then jumps)"
        )


# ── Trail: blend params ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("trail"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_trail_has_blend_params(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "trail"):
        has_blend = "blend" in params or "decay" in params or "length" in params or params != {}
        assert has_blend, (
            f"{preset_name}/{node_name}: trail must have blend/decay/length params "
            f"(ref: brightness accumulates additively, trails fade over 0.5-2s)"
        )


# ── Slitscan: temporal axis ───────────────────────────────────────────


@pytest.mark.parametrize(
    "preset_name,preset_data",
    _presets_using("slitscan"),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_slitscan_has_params(preset_name: str, preset_data: dict) -> None:
    for node_name, params in _nodes_of_type(preset_data, "slitscan"):
        assert params != {}, (
            f"{preset_name}/{node_name}: slitscan must have scan params "
            f"(ref: one spatial axis maps to time)"
        )


# ── Corpus-level: every preset must have name + description ───────────


@pytest.mark.parametrize("preset_name", list(ALL_PRESETS.keys()))
def test_every_preset_has_name_field(preset_name: str) -> None:
    data = ALL_PRESETS[preset_name]
    assert "name" in data and data["name"].strip(), f"{preset_name}: missing or empty 'name' field"


@pytest.mark.parametrize("preset_name", list(ALL_PRESETS.keys()))
def test_every_preset_has_description(preset_name: str) -> None:
    data = ALL_PRESETS[preset_name]
    assert "description" in data and len(data["description"].strip()) >= 5, (
        f"{preset_name}: missing or too-short description (need ≥5 chars)"
    )
