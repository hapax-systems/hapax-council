"""Smoketest for D-25 / OQ-01: neon GPU preset palette cycling.

Asserts the shipped `presets/neon.json` references the new `palette_remap` node,
that the node manifest exists and declares the synthwave-cycle params, and that
colorgrade.brightness is capped (bound-2 OQ-02 ceiling) below saturation-to-white.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
NODES_DIR = REPO_ROOT / "agents" / "shaders" / "nodes"
PRESETS_DIR = REPO_ROOT / "presets"


def test_palette_remap_node_exists():
    frag = NODES_DIR / "palette_remap.frag"
    manifest = NODES_DIR / "palette_remap.json"
    wgsl = NODES_DIR / "palette_remap.wgsl"
    assert frag.exists(), "palette_remap.frag missing"
    assert manifest.exists(), "palette_remap.json missing"
    assert wgsl.exists(), "palette_remap.wgsl missing — re-run wgsl_transpiler"


def test_palette_remap_declares_synthwave_params():
    manifest = json.loads((NODES_DIR / "palette_remap.json").read_text())
    params = manifest["params"]
    assert "palette_id" in params
    assert "cycle_rate" in params
    assert "n_bands" in params
    assert "blend" in params
    assert params["cycle_rate"]["default"] == 0.3, (
        "cycle_rate default must match CPU agents/studio_fx/effects/neon.py time*0.3"
    )
    assert params["n_bands"]["default"] == 12.0, (
        "n_bands default must match 12-color synthwave palette"
    )


def test_palette_remap_shader_contains_synthwave_palette():
    src = (NODES_DIR / "palette_remap.frag").read_text()
    assert "synthwavePalette" in src
    assert "u_time" in src, "shader must read u_time for cycling"
    assert "u_cycle_rate" in src
    assert src.count("vec3(") >= 12, "must declare ≥12 palette colors"


def test_neon_preset_wires_palette_between_edge_and_colorgrade():
    preset = json.loads((PRESETS_DIR / "neon.json").read_text())
    assert "palette" in preset["nodes"], "neon preset must include palette node"
    assert preset["nodes"]["palette"]["type"] == "palette_remap"

    edges = [tuple(e) for e in preset["edges"]]
    assert ("edge", "palette") in edges, "edge → palette wiring missing"
    assert ("palette", "colorgrade") in edges, "palette → colorgrade wiring missing"


def test_neon_preset_brightness_ceiling():
    """OQ-02 bound-2: colorgrade.brightness must be ≤ 1.0 to prevent
    saturation-to-white that violates the scrim-translucency bound."""
    preset = json.loads((PRESETS_DIR / "neon.json").read_text())
    brightness = preset["nodes"]["colorgrade"]["params"]["brightness"]
    assert brightness <= 1.0, (
        f"colorgrade.brightness={brightness} exceeds bound-2 ceiling 1.0; "
        "would saturate to white when combined with bloom (this was the original "
        "OQ-01 white-edge symptom). See alpha.yaml OQ-02 §triple_constraint."
    )


def test_neon_preset_audio_modulates_cycle_rate_softly():
    """OQ-02 bound-3 (anti-visualizer): audio modulation on cycle_rate must be
    soft (scale ≤ 1.0), not 1:1 driving the geometry.

    Scoped to ``cycle_rate`` (a normalized 0..1 param). Other audio mods
    (e.g. ``hue_rotate``, expressed in degrees) live on different scales
    and are bound-checked elsewhere — the test name and OQ-02 bound-3
    are cycle-rate-specific.
    """
    preset = json.loads((PRESETS_DIR / "neon.json").read_text())
    mods = preset.get("modulations", [])
    cycle_rate_audio_mods = [
        m for m in mods if m.get("source") == "audio_energy" and m.get("param") == "cycle_rate"
    ]
    assert cycle_rate_audio_mods, "expected audio_energy modulation on cycle_rate for reactivity"
    for m in cycle_rate_audio_mods:
        assert m["scale"] <= 1.0, (
            f"audio modulation on cycle_rate scale={m['scale']} too aggressive — "
            "risks visualizer-register output (OQ-02 bound-3)"
        )
