"""Regression pin for the monochrome/bloom/arcane/broadcast preset family pool.

cc-task ``jr-monochrome-bloom-arcane-broadcast-preset-family-pool``: 8 new
preset files across 4 aesthetic lineages, continuation of the
vinyl-tape-glitch (#2399) + dub-granular-modulation (#2402) pools.

Pattern mirrors prior pools: inventory + schema + WGSL validity + encoder
safety + lineage distinctness + no-collision-with-prior-pools.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRESETS_DIR = REPO_ROOT / "presets"
NODES_DIR = REPO_ROOT / "agents" / "shaders" / "nodes"

EXPECTED_PRESETS: tuple[tuple[str, str], ...] = (
    ("mono_print_woodcut", "monochrome-print"),
    ("mono_print_newsprint", "monochrome-print"),
    ("bloom_neon_night", "chromatic-bloom"),
    ("bloom_solar_flare", "chromatic-bloom"),
    ("arcane_ascii_glyph", "arcane-glyph"),
    ("arcane_dither_sigil", "arcane-glyph"),
    ("broadcast_vhs_decay", "broadcast-degraded"),
    ("broadcast_static_carrier", "broadcast-degraded"),
)

EXPECTED_LINEAGE_COUNTS: dict[str, int] = {
    "monochrome-print": 2,
    "chromatic-bloom": 2,
    "arcane-glyph": 2,
    "broadcast-degraded": 2,
}

PRIOR_POOLS: frozenset[str] = frozenset(
    {
        # vinyl-tape-glitch (#2399)
        "vinyl_dust",
        "vinyl_pop_static",
        "tape_warmth",
        "tape_wow_flutter",
        "glitch_y2k_block",
        "glitch_y2k_chroma",
        "antivapor_grit",
        "antivapor_thresh",
        # dub-granular-modulation-liquid (#2402)
        "dub_echo_spatial",
        "dub_tunnel_chamber",
        "granular_stutter",
        "granular_tile_grid",
        "modulation_pulse_strobe",
        "modulation_pulse_warp",
        "liquid_flow_fluid",
        "liquid_flow_breath",
    }
)


def _load_preset(basename: str) -> dict:
    path = PRESETS_DIR / f"{basename}.json"
    with path.open() as f:
        return json.load(f)


def _available_node_types() -> set[str]:
    if not NODES_DIR.is_dir():
        return set()
    return {p.stem for p in NODES_DIR.glob("*.wgsl")}


COMPOSITOR_NODES: frozenset[str] = frozenset({"output", "content_layer"})


class TestExpectedInventory:
    def test_each_preset_file_exists(self) -> None:
        for name, _ in EXPECTED_PRESETS:
            path = PRESETS_DIR / f"{name}.json"
            assert path.is_file(), f"preset file {path} missing"

    def test_expected_count_is_eight(self) -> None:
        assert len(EXPECTED_PRESETS) == 8

    def test_each_lineage_has_at_least_two_presets(self) -> None:
        counts: dict[str, int] = {}
        for _, lineage in EXPECTED_PRESETS:
            counts[lineage] = counts.get(lineage, 0) + 1
        for lineage, expected in EXPECTED_LINEAGE_COUNTS.items():
            assert counts.get(lineage, 0) >= expected

    def test_no_collision_with_prior_pools(self) -> None:
        new_pool = {name for name, _ in EXPECTED_PRESETS}
        overlap = PRIOR_POOLS & new_pool
        assert not overlap, f"name collision with prior pools: {overlap}"


class TestPresetSchema:
    def test_each_preset_has_required_top_level_keys(self) -> None:
        required = {"name", "description", "transition_ms", "nodes"}
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            missing = required - set(preset.keys())
            assert not missing, f"preset {basename!r} missing keys {missing}"

    def test_each_preset_carries_lineage_field(self) -> None:
        for basename, expected_lineage in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            assert preset.get("lineage") == expected_lineage

    def test_each_preset_includes_output_node(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            types = {node["type"] for node in preset["nodes"].values()}
            assert "output" in types

    def test_each_preset_includes_content_layer(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            types = {node["type"] for node in preset["nodes"].values()}
            assert "content_layer" in types

    def test_transition_ms_is_positive(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            assert preset["transition_ms"] > 0


class TestWGSLNodeReferences:
    def test_every_referenced_node_type_exists(self) -> None:
        available = _available_node_types() | COMPOSITOR_NODES
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            for node_id, node in preset["nodes"].items():
                node_type = node["type"]
                assert node_type in available, (
                    f"preset {basename!r} node {node_id!r} references "
                    f"unknown WGSL type {node_type!r}"
                )


class TestEncoderSafety:
    HF_NOISE_TYPES: frozenset[str] = frozenset(
        {
            "noise_overlay",
            "grain_bump",
            "noise_gen",
        }
    )

    def test_no_preset_combines_high_intensity_with_micro_scale(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            for node_id, node in preset["nodes"].items():
                if node["type"] not in self.HF_NOISE_TYPES:
                    continue
                params = node.get("params", {})
                intensity = params.get("intensity", params.get("amount", 0.0))
                scale = params.get("scale", 1000)
                if intensity > 0.5 and scale < 200:
                    raise AssertionError(
                        f"preset {basename!r} node {node_id!r} ({node['type']}) "
                        f"combines high intensity {intensity} with micro scale {scale}"
                    )


class TestLineageDistinctness:
    LINEAGE_PRIMARY_NODES: dict[str, frozenset[str]] = {
        "monochrome-print": frozenset({"halftone", "threshold", "posterize"}),
        "chromatic-bloom": frozenset({"bloom", "emboss"}),
        "arcane-glyph": frozenset({"ascii", "dither"}),
        "broadcast-degraded": frozenset({"vhs", "scanlines", "thermal"}),
    }

    def test_each_preset_carries_at_least_one_lineage_signature_node(self) -> None:
        for basename, lineage in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            preset_types = {node["type"] for node in preset["nodes"].values()}
            primary = self.LINEAGE_PRIMARY_NODES[lineage]
            overlap = preset_types & primary
            assert overlap, (
                f"preset {basename!r} (lineage {lineage!r}) has no signature node from {primary}"
            )
