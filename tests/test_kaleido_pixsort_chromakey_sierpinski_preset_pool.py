"""Regression pin for the kaleidoscope/pixsort/chromakey/sierpinski preset pool.

6th pool in the operator-directed continuation train.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRESETS_DIR = REPO_ROOT / "presets"
NODES_DIR = REPO_ROOT / "agents" / "shaders" / "nodes"

EXPECTED_PRESETS: tuple[tuple[str, str], ...] = (
    ("kaleido_fractal_mirror", "kaleidoscope-fractal"),
    ("kaleido_fractal_dense", "kaleidoscope-fractal"),
    ("pixsort_glitch_horizontal", "pixsort-glitch"),
    ("pixsort_glitch_vertical", "pixsort-glitch"),
    ("chromakey_lift", "chromatic-key"),
    ("chromakey_luma_split", "chromatic-key"),
    ("sierpinski_recursive", "sierpinski"),
    ("sierpinski_line_overlay", "sierpinski"),
)

EXPECTED_LINEAGE_COUNTS: dict[str, int] = {
    "kaleidoscope-fractal": 2,
    "pixsort-glitch": 2,
    "chromatic-key": 2,
    "sierpinski": 2,
}

# 40 names from prior 5 pools (#2399, #2402, #2406, #2410, #2412).
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
        # monochrome-bloom-arcane-broadcast (#2406)
        "mono_print_woodcut",
        "mono_print_newsprint",
        "bloom_neon_night",
        "bloom_solar_flare",
        "arcane_ascii_glyph",
        "arcane_dither_sigil",
        "broadcast_vhs_decay",
        "broadcast_static_carrier",
        # drone-arcade-cellular-electromagnetic (#2410)
        "drone_static_drift",
        "drone_dense_static",
        "arcade_8bit_pixel",
        "arcade_palette_remap",
        "cellular_reaction",
        "cellular_kuwahara_paint",
        "electromag_thermal_field",
        "electromag_rutt_etra",
        # xerox-neon-paper-water (#2412)
        "xerox_photocopy_decay",
        "xerox_smudge_streak",
        "neon_grid_arcade",
        "neon_grid_tunnel",
        "paper_fold_origami",
        "paper_fold_crumple",
        "water_ripple_surface",
        "water_ripple_caustic",
    }
)

COMPOSITOR_NODES: frozenset[str] = frozenset({"output", "content_layer"})


def _load_preset(basename: str) -> dict:
    path = PRESETS_DIR / f"{basename}.json"
    with path.open() as f:
        return json.load(f)


def _available_node_types() -> set[str]:
    if not NODES_DIR.is_dir():
        return set()
    return {p.stem for p in NODES_DIR.glob("*.wgsl")}


class TestExpectedInventory:
    def test_each_preset_file_exists(self) -> None:
        for name, _ in EXPECTED_PRESETS:
            assert (PRESETS_DIR / f"{name}.json").is_file()

    def test_expected_count_is_eight(self) -> None:
        assert len(EXPECTED_PRESETS) == 8

    def test_each_lineage_has_at_least_two_presets(self) -> None:
        counts: dict[str, int] = {}
        for _, lineage in EXPECTED_PRESETS:
            counts[lineage] = counts.get(lineage, 0) + 1
        for lineage, expected in EXPECTED_LINEAGE_COUNTS.items():
            assert counts.get(lineage, 0) >= expected

    def test_no_collision_with_prior_pools(self) -> None:
        new = {n for n, _ in EXPECTED_PRESETS}
        overlap = PRIOR_POOLS & new
        assert not overlap, f"name collision: {overlap}"


class TestPresetSchema:
    def test_each_preset_has_required_top_level_keys(self) -> None:
        required = {"name", "description", "transition_ms", "nodes"}
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            assert not (required - set(preset.keys()))

    def test_each_preset_carries_lineage(self) -> None:
        for basename, lineage in EXPECTED_PRESETS:
            assert _load_preset(basename).get("lineage") == lineage

    def test_each_preset_has_output_and_content_layer(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            types = {n["type"] for n in preset["nodes"].values()}
            assert "output" in types
            assert "content_layer" in types

    def test_transition_ms_is_positive(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            assert _load_preset(basename)["transition_ms"] > 0


class TestWGSLNodeReferences:
    def test_every_referenced_node_type_exists(self) -> None:
        available = _available_node_types() | COMPOSITOR_NODES
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            for node_id, node in preset["nodes"].items():
                assert node["type"] in available, (
                    f"preset {basename!r} node {node_id!r} unknown type {node['type']!r}"
                )


class TestEncoderSafety:
    HF_NOISE_TYPES: frozenset[str] = frozenset({"noise_overlay", "grain_bump", "noise_gen"})

    def test_no_high_intensity_micro_scale(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            for node in preset["nodes"].values():
                if node["type"] not in self.HF_NOISE_TYPES:
                    continue
                params = node.get("params", {})
                intensity = params.get("intensity", params.get("amount", 0.0))
                scale = params.get("scale", 1000)
                assert not (intensity > 0.5 and scale < 200)


class TestLineageDistinctness:
    LINEAGE_PRIMARY_NODES: dict[str, frozenset[str]] = {
        "kaleidoscope-fractal": frozenset({"kaleidoscope", "droste"}),
        "pixsort-glitch": frozenset({"pixsort", "slitscan"}),
        "chromatic-key": frozenset({"chroma_key", "luma_key", "color_map"}),
        "sierpinski": frozenset({"sierpinski_content", "sierpinski_lines"}),
    }

    def test_each_preset_carries_signature_node(self) -> None:
        for basename, lineage in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            preset_types = {n["type"] for n in preset["nodes"].values()}
            primary = self.LINEAGE_PRIMARY_NODES[lineage]
            assert preset_types & primary, (
                f"preset {basename!r} (lineage {lineage!r}) has no signature node"
            )


class TestRecruitabilityViaFamilyPresets:
    """Audit-pool fix 2026-05-03: every preset MUST be reachable via the
    director's preset-family recruitment dispatcher (``FAMILY_PRESETS``).
    Without this, presets exist as JSON files but no autonomous director
    path can pick them — only the chat-keyword regex in chat_reactor.
    """

    def test_every_preset_in_family_presets(self) -> None:
        from agents.studio_compositor.preset_family_selector import FAMILY_PRESETS

        recruitable = {p for fam in FAMILY_PRESETS.values() for p in fam}
        for name, _ in EXPECTED_PRESETS:
            assert name in recruitable, (
                f"preset {name!r} is not in FAMILY_PRESETS — "
                "director recruitment cannot pick it. Add to a family "
                "in agents/studio_compositor/preset_family_selector.py."
            )
