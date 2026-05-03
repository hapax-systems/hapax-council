"""Regression pin for the dub/granular/modulation/liquid preset family pool.

cc-task ``jr-dub-granular-modulation-preset-family-pool``: 8 new preset
files across 4 aesthetic lineages, continuation of the vinyl-tape-glitch
pool (#2399). This test mirrors the prior pool's regression pattern
(inventory, schema, WGSL node validity, encoder safety) so a future edit
dropping a preset or referencing a non-existent shader node fails at CI
rather than at livestream time.

Phase 0 (this PR): the preset files + regression. Phase 1 captures a
30s livestream clip rotating through the 8 + validates encoder safety
(operator-side; not in CI).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRESETS_DIR = REPO_ROOT / "presets"
NODES_DIR = REPO_ROOT / "agents" / "shaders" / "nodes"

#: The 8 preset files this PR ships, by basename + lineage tag.
EXPECTED_PRESETS: tuple[tuple[str, str], ...] = (
    ("dub_echo_spatial", "dub-spectral"),
    ("dub_tunnel_chamber", "dub-spectral"),
    ("granular_stutter", "granular-loop"),
    ("granular_tile_grid", "granular-loop"),
    ("modulation_pulse_strobe", "modulation-pulse"),
    ("modulation_pulse_warp", "modulation-pulse"),
    ("liquid_flow_fluid", "liquid-flow"),
    ("liquid_flow_breath", "liquid-flow"),
)

EXPECTED_LINEAGE_COUNTS: dict[str, int] = {
    "dub-spectral": 2,
    "granular-loop": 2,
    "modulation-pulse": 2,
    "liquid-flow": 2,
}


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
            assert counts.get(lineage, 0) >= expected, (
                f"lineage {lineage!r} expected ≥{expected} presets, got {counts.get(lineage, 0)}"
            )

    def test_no_duplicate_with_vinyl_tape_glitch_pool(self) -> None:
        """The earlier pool shipped 8 presets in the same dir; pin
        non-overlap so a rename collision is caught."""
        prior_pool = {
            "vinyl_dust",
            "vinyl_pop_static",
            "tape_warmth",
            "tape_wow_flutter",
            "glitch_y2k_block",
            "glitch_y2k_chroma",
            "antivapor_grit",
            "antivapor_thresh",
        }
        new_pool = {name for name, _ in EXPECTED_PRESETS}
        overlap = prior_pool & new_pool
        assert not overlap, f"name collision with prior pool: {overlap}"


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
            assert preset.get("lineage") == expected_lineage, (
                f"preset {basename!r}: expected lineage {expected_lineage!r}, "
                f"got {preset.get('lineage')!r}"
            )

    def test_each_preset_includes_output_node(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            types = {node["type"] for node in preset["nodes"].values()}
            assert "output" in types, f"preset {basename!r} missing output node"

    def test_each_preset_includes_content_layer(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            types = {node["type"] for node in preset["nodes"].values()}
            assert "content_layer" in types, f"preset {basename!r} missing content_layer node"

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
                    f"unknown WGSL type {node_type!r}; "
                    f"available types: {sorted(available)[:20]}..."
                )


class TestEncoderSafety:
    """Same encoder-safety contract as the vinyl-tape-glitch pool: no
    high-frequency-noise node combines high intensity with micro scale."""

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
                        f"combines high intensity {intensity} with micro scale "
                        f"{scale} — encoder bitrate-starve risk"
                    )


class TestLineageDistinctness:
    """Each lineage occupies a distinct aesthetic axis; pin via a
    lineage→primary-node assertion so a future edit blurring lineages
    is caught."""

    LINEAGE_PRIMARY_NODES: dict[str, frozenset[str]] = {
        "dub-spectral": frozenset({"echo", "tunnel", "trail", "droste"}),
        "granular-loop": frozenset({"stutter", "tile", "slitscan"}),
        "modulation-pulse": frozenset({"strobe", "breathing", "warp"}),
        "liquid-flow": frozenset({"fluid_sim", "fisheye", "syrup", "drift"}),
    }

    def test_each_preset_carries_at_least_one_lineage_signature_node(self) -> None:
        """Each preset must include at least one node from its lineage's
        primary-node set. Otherwise the lineage tag is decorative."""
        for basename, lineage in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            preset_types = {node["type"] for node in preset["nodes"].values()}
            primary = self.LINEAGE_PRIMARY_NODES[lineage]
            overlap = preset_types & primary
            assert overlap, (
                f"preset {basename!r} (lineage {lineage!r}) has no "
                f"signature node from {primary}; lineage tag is decorative"
            )
