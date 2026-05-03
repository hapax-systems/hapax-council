"""Regression pin for the drone/arcade/cellular/electromagnetic preset family pool.

cc-task ``jr-drone-arcade-cellular-electromagnetic-preset-family-pool``: 8
new preset files across 4 aesthetic lineages, 4th pool in the operator-
directed continuation train.

Pattern mirrors prior pools.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRESETS_DIR = REPO_ROOT / "presets"
NODES_DIR = REPO_ROOT / "agents" / "shaders" / "nodes"

EXPECTED_PRESETS: tuple[tuple[str, str], ...] = (
    ("drone_static_drift", "drone-noise-static"),
    ("drone_dense_static", "drone-noise-static"),
    ("arcade_8bit_pixel", "retro-arcade"),
    ("arcade_palette_remap", "retro-arcade"),
    ("cellular_reaction", "organic-cellular"),
    ("cellular_kuwahara_paint", "organic-cellular"),
    ("electromag_thermal_field", "electromagnetic-field"),
    ("electromag_rutt_etra", "electromagnetic-field"),
)

EXPECTED_LINEAGE_COUNTS: dict[str, int] = {
    "drone-noise-static": 2,
    "retro-arcade": 2,
    "organic-cellular": 2,
    "electromagnetic-field": 2,
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
        # monochrome-bloom-arcane-broadcast (#2406)
        "mono_print_woodcut",
        "mono_print_newsprint",
        "bloom_neon_night",
        "bloom_solar_flare",
        "arcane_ascii_glyph",
        "arcane_dither_sigil",
        "broadcast_vhs_decay",
        "broadcast_static_carrier",
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
            assert not missing

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
        "drone-noise-static": frozenset({"noise_overlay", "drift", "grain_bump"}),
        "retro-arcade": frozenset({"posterize", "palette_remap", "palette_extract", "scanlines"}),
        "organic-cellular": frozenset({"reaction_diffusion", "voronoi_overlay", "kuwahara"}),
        "electromagnetic-field": frozenset(
            {"thermal", "particle_system", "rutt_etra", "displacement_map"}
        ),
    }

    def test_each_preset_carries_at_least_one_lineage_signature_node(self) -> None:
        for basename, lineage in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            preset_types = {node["type"] for node in preset["nodes"].values()}
            primary = self.LINEAGE_PRIMARY_NODES[lineage]
            overlap = preset_types & primary
            assert overlap, f"preset {basename!r} (lineage {lineage!r}) has no signature node"


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
