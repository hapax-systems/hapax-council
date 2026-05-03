"""Regression pin for the vinyl/tape/glitch/anti-vaporwave preset family pool.

cc-task ``jr-vinyl-tape-glitch-preset-family-pool``: 8 new preset files
across 4 aesthetic lineages. This test pins the inventory + schema +
WGSL-node validity so a future edit dropping a preset or referencing a
non-existent shader node is caught at CI rather than at livestream time.

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

#: The 8 preset files this PR ships, by basename (no .json).
EXPECTED_PRESETS: tuple[tuple[str, str], ...] = (
    ("vinyl_dust", "vinyl-noise"),
    ("vinyl_pop_static", "vinyl-noise"),
    ("tape_warmth", "tape-saturation"),
    ("tape_wow_flutter", "tape-saturation"),
    ("glitch_y2k_block", "glitch-y2k"),
    ("glitch_y2k_chroma", "glitch-y2k"),
    ("antivapor_grit", "anti-vaporwave"),
    ("antivapor_thresh", "anti-vaporwave"),
)

#: Lineages → expected count. Cc-task spec asks for ≥2 per lineage.
EXPECTED_LINEAGE_COUNTS: dict[str, int] = {
    "vinyl-noise": 2,
    "tape-saturation": 2,
    "glitch-y2k": 2,
    "anti-vaporwave": 2,
}


def _load_preset(basename: str) -> dict:
    path = PRESETS_DIR / f"{basename}.json"
    with path.open() as f:
        return json.load(f)


def _available_node_types() -> set[str]:
    """All WGSL node names available in agents/shaders/nodes/."""
    if not NODES_DIR.is_dir():
        return set()
    return {p.stem for p in NODES_DIR.glob("*.wgsl")}


# Sentinel node names that are valid but live outside agents/shaders/nodes
# (handled by the compositor's render-graph layer rather than the WGSL
# compiler). Pin them here so tests don't reject them as unknown.
COMPOSITOR_NODES: frozenset[str] = frozenset({"output", "content_layer"})


class TestExpectedInventory:
    def test_each_preset_file_exists(self) -> None:
        for name, _ in EXPECTED_PRESETS:
            path = PRESETS_DIR / f"{name}.json"
            assert path.is_file(), f"preset file {path} missing"

    def test_expected_count_is_eight(self) -> None:
        """Audit acceptance: ≥8 presets across 3 lineages (cc-task spec
        says 'at least 8'; we ship exactly 8 across 4 lineages including
        anti-vaporwave alternatives)."""
        assert len(EXPECTED_PRESETS) == 8

    def test_each_lineage_has_at_least_two_presets(self) -> None:
        counts: dict[str, int] = {}
        for _, lineage in EXPECTED_PRESETS:
            counts[lineage] = counts.get(lineage, 0) + 1
        for lineage, expected in EXPECTED_LINEAGE_COUNTS.items():
            assert counts.get(lineage, 0) >= expected, (
                f"lineage {lineage!r} expected ≥{expected} presets, got {counts.get(lineage, 0)}"
            )


class TestPresetSchema:
    """Each shipped preset must follow the existing JSON schema."""

    def test_each_preset_has_required_top_level_keys(self) -> None:
        required = {"name", "description", "transition_ms", "nodes"}
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            missing = required - set(preset.keys())
            assert not missing, f"preset {basename!r} missing keys {missing}"

    def test_each_preset_carries_lineage_field(self) -> None:
        """Lineage tag enables downstream filtering / reporting per
        cc-task acceptance."""
        for basename, expected_lineage in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            assert preset.get("lineage") == expected_lineage, (
                f"preset {basename!r}: expected lineage {expected_lineage!r}, "
                f"got {preset.get('lineage')!r}"
            )

    def test_each_preset_has_at_least_one_node(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            assert len(preset["nodes"]) >= 1

    def test_each_preset_includes_output_node(self) -> None:
        """The compositor render path expects an 'output' sink in every
        preset; missing it would silently produce no frame."""
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            types = {node["type"] for node in preset["nodes"].values()}
            assert "output" in types, f"preset {basename!r} missing output node"

    def test_each_preset_includes_content_layer(self) -> None:
        """content_layer is the canonical surface for camera/album/sierpinski
        composition; presets without it cannot composite live content."""
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            types = {node["type"] for node in preset["nodes"].values()}
            assert "content_layer" in types, f"preset {basename!r} missing content_layer node"

    def test_transition_ms_is_positive(self) -> None:
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            assert preset["transition_ms"] > 0


class TestWGSLNodeReferences:
    """Audit acceptance: 'each preset declares its WGSL recipe (referencing
    existing nodes; do not require new shader code).'

    Pin: every node type referenced by any of the 8 presets must either
    exist as agents/shaders/nodes/<type>.wgsl, OR be one of the
    compositor sentinel nodes (output, content_layer).
    """

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
    """Audit acceptance: 'no preset produces high-frequency noise that
    bitrate-starves the HLS encoder.'

    CI cannot run the actual encoder; pin parametric proxies — no preset
    declares a noise/grain node with both very high intensity AND very
    low scale (which would create per-pixel high-frequency content the
    H.264 encoder fails to compress under a fixed-bitrate budget).
    """

    HF_NOISE_TYPES: frozenset[str] = frozenset(
        {
            "noise_overlay",
            "grain_bump",
            "noise_gen",
        }
    )

    def test_no_preset_combines_high_intensity_with_micro_scale(self) -> None:
        """High intensity (>0.5) + tiny scale (<200) = encoder-killer.
        We allow up to one of the two extremes per node, never both."""
        for basename, _ in EXPECTED_PRESETS:
            preset = _load_preset(basename)
            for node_id, node in preset["nodes"].items():
                if node["type"] not in self.HF_NOISE_TYPES:
                    continue
                params = node.get("params", {})
                intensity = params.get("intensity", params.get("amount", 0.0))
                scale = params.get("scale", 1000)  # default safe
                if intensity > 0.5 and scale < 200:
                    raise AssertionError(
                        f"preset {basename!r} node {node_id!r} ({node['type']}) "
                        f"combines high intensity {intensity} with micro scale "
                        f"{scale} — encoder bitrate-starve risk"
                    )
