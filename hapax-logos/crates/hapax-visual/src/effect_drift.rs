//! Slot-pool drift engine — Rust port of slot_drift.py + parameter_drift.py.
//!
//! 5-slot pool with staggered lifecycles: IDLE→RISING→PEAK→FALLING.
//! Drives plan.json + uniforms.json for the wgpu DynamicPipeline.

use std::collections::VecDeque;
use std::path::{Path, PathBuf};

// ── Lifecycle timing (matching 2D) ─────────────────────────────
const FADE_IN_S: f32 = 14.0;
const PEAK_HOLD_S: f32 = 7.0;
const FADE_OUT_S: f32 = 14.0;
const FAST_FADE_IN_S: f32 = 6.0;
const FAST_PEAK_HOLD_S: f32 = 3.5;
const FAST_FADE_OUT_S: f32 = 6.0;
const STAGGER_S: f32 = 6.0;
const POOL_SIZE: usize = 5; // Five visible slots: four active, one rotating/recruiting.
const ACTIVE_SLOT_TARGET: usize = 4;
const TICK_DIVISOR: u64 = 5; // ~6Hz at 30fps
const SPATIAL_PEAK_RANGE: (f32, f32) = (0.82, 0.98);
const NONSPATIAL_PEAK_RANGE: (f32, f32) = (0.96, 1.0);
const RETIRE_INTENSITY_FLOOR: f32 = 0.28;
const FAST_RETIRE_INTENSITY_FLOOR: f32 = 0.32;
const RECRUIT_WARM_PROGRESS: f32 = 0.48;
const FAST_RECRUIT_WARM_PROGRESS: f32 = 0.40;
const INITIAL_VISIBLE_FLOOR: f32 = 0.46;
const ASSERTIVE_TARGET_DEPARTURE_FRACTION: f32 = 0.45;
const MIN_ACTIVE_ANCHOR_EFFECTS: usize = 3;
const MAX_ACTIVE_CONDITIONAL_EFFECTS: usize = 1;
const MIN_ACTIVE_HIGH_IMPINGEMENT_EFFECTS: usize = 3;
const MIN_ACTIVE_DRAMATIC_VARIATION_EFFECTS: usize = 3;
const MIN_ACTIVE_PUNCTUATION_EFFECTS: usize = 2;
const MIN_ACTIVE_GENERATED_CHAIN_SLOTS: usize = 3;
const MIN_GENERATED_CHAIN_NODES: usize = 3;
const MAX_GENERATED_CHAIN_NODES: usize = 5;
const RECENT_EFFECT_MEMORY: usize = 36;
const COVERAGE_EVENT_MEMORY: usize = 192;
const PARAM_REGIME_MIN_HOLD_S: f32 = 1.35;
const PARAM_REGIME_MAX_HOLD_S: f32 = 3.40;
const PARAM_REGIME_CROSSFADE_FRACTION: f32 = 0.16;

fn shader_nodes_dir() -> PathBuf {
    if let Ok(path) = std::env::var("HAPAX_SHADER_NODES_DIR") {
        return PathBuf::from(path);
    }

    let compile_time_root =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");
    if compile_time_root.is_dir() {
        return compile_time_root;
    }

    if let Ok(current_dir) = std::env::current_dir() {
        for ancestor in current_dir.ancestors() {
            let candidate = ancestor.join("agents/shaders/nodes");
            if candidate.is_dir() {
                return candidate;
            }
        }
    }

    compile_time_root
}

// ── Shader definitions ─────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct ShaderDef {
    pub name: &'static str,
    pub shader_file: &'static str,
    pub family: &'static str,
    pub is_spatial: bool,
    pub passthrough: &'static [(&'static str, f32)],
    pub active_ranges: &'static [(&'static str, f32, f32)], // (name, lo, hi)
    pub param_order: &'static [&'static str],
}

#[derive(Clone, Debug)]
struct ChainSeed {
    id: &'static str,
    lineage: &'static str,
    topology_signature: &'static str,
    anchor: &'static str,
    nodes: &'static [&'static str],
}

#[derive(Clone, Debug)]
struct GeneratedChain {
    id: String,
    lineage: String,
    structural_signature: String,
    topology_signature: String,
    anchor: &'static str,
    nodes: Vec<&'static str>,
    param_seed: u64,
}

static CHAIN_SEEDS: &[ChainSeed] = &[
    ChainSeed {
        id: "kaleido-fractal-mirror",
        lineage: "kaleidoscope-fractal",
        topology_signature: "tonal:kaleidoscope:mirror:droste",
        anchor: "kaleidoscope",
        nodes: &["colorgrade", "kaleidoscope", "mirror", "droste"],
    },
    ChainSeed {
        id: "ghost-trace-print",
        lineage: "chronophotographic-temporal",
        topology_signature: "posterize:trail:bloom:noise",
        anchor: "trail",
        nodes: &["posterize", "trail", "bloom", "noise_overlay"],
    },
    ChainSeed {
        id: "tape-chroma-decay",
        lineage: "broadcast-decay",
        topology_signature: "vhs:scanlines:chromatic_aberration",
        anchor: "vhs",
        nodes: &["vhs", "scanlines", "chromatic_aberration"],
    },
    ChainSeed {
        id: "glitch-sort-separation",
        lineage: "digital-breakage",
        topology_signature: "glitch_block:pixsort:chromatic_aberration",
        anchor: "glitch_block",
        nodes: &["glitch_block", "pixsort", "chromatic_aberration"],
    },
    ChainSeed {
        id: "print-threshold-map",
        lineage: "printmaker-halftone",
        topology_signature: "halftone:dither:palette",
        anchor: "halftone",
        nodes: &["halftone", "dither", "palette"],
    },
    ChainSeed {
        id: "thermal-poster-map",
        lineage: "sensor-falsecolor",
        topology_signature: "thermal:posterize:color_map",
        anchor: "thermal",
        nodes: &["thermal", "posterize", "color_map"],
    },
    ChainSeed {
        id: "slitscan-rgba-slice",
        lineage: "temporal-slicing",
        topology_signature: "slitscan:chromatic_aberration:edge_detect",
        anchor: "slitscan",
        nodes: &["slitscan", "chromatic_aberration", "edge_detect"],
    },
    ChainSeed {
        id: "fluid-displacement-map",
        lineage: "liquid-field",
        topology_signature: "fluid_sim:displacement_map:palette_remap",
        anchor: "fluid_sim",
        nodes: &["fluid_sim", "displacement_map", "palette_remap"],
    },
    ChainSeed {
        id: "tunnel-vortex-ca",
        lineage: "vortex-depth",
        topology_signature: "tunnel:kaleidoscope:chromatic_aberration",
        anchor: "tunnel",
        nodes: &["tunnel", "kaleidoscope", "chromatic_aberration"],
    },
    ChainSeed {
        id: "pixsort-palette-scan",
        lineage: "ordered-corruption",
        topology_signature: "pixsort:palette_remap:scanlines",
        anchor: "pixsort",
        nodes: &["pixsort", "palette_remap", "scanlines"],
    },
    ChainSeed {
        id: "mirror-dub-recursion",
        lineage: "reflection-recursion",
        topology_signature: "mirror:droste:chromatic_aberration",
        anchor: "mirror",
        nodes: &["mirror", "droste", "chromatic_aberration"],
    },
    ChainSeed {
        id: "edge-palette-carve",
        lineage: "edge-extraction",
        topology_signature: "edge_detect:threshold:palette",
        anchor: "edge_detect",
        nodes: &["edge_detect", "threshold", "palette"],
    },
    ChainSeed {
        id: "displacement-chroma-drift",
        lineage: "spatial-reprojection",
        topology_signature: "displacement_map:chromatic_aberration:drift",
        anchor: "displacement_map",
        nodes: &["displacement_map", "chromatic_aberration", "drift"],
    },
    ChainSeed {
        id: "waveform-sensor-map",
        lineage: "signal-render",
        topology_signature: "waveform_render:palette_remap:scanlines",
        anchor: "waveform_render",
        nodes: &["waveform_render", "palette_remap", "scanlines"],
    },
];

pub static SHADERS: &[ShaderDef] = &[
    ShaderDef {
        name: "colorgrade",
        shader_file: "colorgrade.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[
            ("saturation", 1.0),
            ("brightness", 1.0),
            ("contrast", 1.0),
            ("sepia", 0.0),
            ("hue_rotate", 0.0),
        ],
        active_ranges: &[
            ("saturation", 0.6, 1.35),
            ("brightness", 1.0, 1.12),
            ("contrast", 0.9, 1.25),
            ("sepia", 0.0, 0.35),
            ("hue_rotate", 0.0, 0.65),
        ],
        param_order: &[
            "saturation",
            "brightness",
            "contrast",
            "sepia",
            "hue_rotate",
        ],
    },
    ShaderDef {
        name: "bloom",
        shader_file: "bloom.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[("threshold", 0.8), ("radius", 0.0), ("alpha", 0.0)],
        active_ranges: &[
            ("threshold", 0.55, 0.9),
            ("radius", 0.75, 2.0),
            ("alpha", 0.04, 0.18),
        ],
        param_order: &["threshold", "radius", "alpha"],
    },
    ShaderDef {
        name: "invert",
        shader_file: "invert.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[("strength", 0.0)],
        active_ranges: &[("strength", 0.06, 0.28)],
        param_order: &["strength"],
    },
    ShaderDef {
        name: "drift",
        shader_file: "drift.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[
            ("speed", 0.15),
            ("amplitude", 0.0),
            ("frequency", 1.5),
            ("coherence", 0.7),
        ],
        active_ranges: &[
            ("speed", 0.16, 0.34),
            ("amplitude", 0.20, 0.50),
            ("frequency", 0.8, 1.8),
            ("coherence", 0.55, 0.9),
        ],
        param_order: &["speed", "amplitude", "frequency", "coherence"],
    },
    ShaderDef {
        name: "ascii",
        shader_file: "ascii.wgsl",
        family: "texture",
        is_spatial: false,
        // ascii.wgsl has a true source passthrough below cell_size 2.0.
        passthrough: &[("cell_size", 1.0), ("color_mode", 1.0)],
        active_ranges: &[("cell_size", 6.0, 18.0), ("color_mode", 0.0, 1.0)],
        param_order: &["cell_size", "color_mode"],
    },
    ShaderDef {
        name: "vhs",
        shader_file: "vhs.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[
            ("chroma_shift", 0.0),
            ("head_switch_y", -1.0),
            ("noise_band_y", -1.0),
        ],
        active_ranges: &[
            ("chroma_shift", 0.25, 2.0),
            ("head_switch_y", 0.94, 0.99),
            ("noise_band_y", 0.15, 0.85),
        ],
        param_order: &["chroma_shift", "head_switch_y", "noise_band_y"],
    },
    ShaderDef {
        name: "glitch_block",
        shader_file: "glitch_block.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[("block_size", 16.0), ("intensity", 0.0), ("rgb_split", 0.0)],
        active_ranges: &[
            ("block_size", 8.0, 28.0),
            ("intensity", 0.10, 0.34),
            ("rgb_split", 0.10, 0.36),
        ],
        param_order: &["block_size", "intensity", "rgb_split"],
    },
    // ── New shaders ──
    ShaderDef {
        name: "vignette",
        shader_file: "vignette.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[("strength", 0.0), ("radius", 0.7), ("softness", 0.3)],
        active_ranges: &[
            ("strength", 0.2, 0.7),
            ("radius", 0.4, 0.8),
            ("softness", 0.2, 0.5),
        ],
        param_order: &["strength", "radius", "softness"],
    },
    ShaderDef {
        name: "edge_detect",
        shader_file: "edge_detect.wgsl",
        family: "edge",
        is_spatial: false,
        passthrough: &[("threshold", 1.0), ("color_mode", 0.0)],
        active_ranges: &[("threshold", 0.04, 0.28), ("color_mode", 0.45, 0.95)],
        param_order: &["threshold", "color_mode"],
    },
    ShaderDef {
        name: "rutt_etra",
        shader_file: "rutt_etra.wgsl",
        family: "edge",
        is_spatial: false,
        passthrough: &[
            ("displacement", 0.0),
            ("line_density", 8.0),
            ("line_width", 1.0),
            ("color_mode", 0.0),
        ],
        active_ranges: &[
            ("displacement", 5.0, 28.0),
            ("line_density", 4.0, 16.0),
            ("line_width", 1.2, 3.4),
            ("color_mode", 0.0, 1.0),
        ],
        param_order: &["displacement", "line_density", "line_width", "color_mode"],
    },
    ShaderDef {
        name: "chromatic_aberration",
        shader_file: "chromatic_aberration.wgsl",
        family: "atmospheric",
        is_spatial: false,
        passthrough: &[("offset_x", 0.0), ("offset_y", 0.0), ("intensity", 0.0)],
        active_ranges: &[
            ("offset_x", -4.8, 4.8),
            ("offset_y", -2.2, 2.2),
            ("intensity", 0.42, 0.95),
        ],
        param_order: &["offset_x", "offset_y", "intensity"],
    },
    ShaderDef {
        name: "scanlines",
        shader_file: "scanlines.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[("opacity", 0.0), ("spacing", 7.0), ("thickness", 1.0)],
        active_ranges: &[
            ("opacity", 0.08, 0.22),
            ("spacing", 5.0, 10.0),
            ("thickness", 1.0, 2.2),
        ],
        param_order: &["opacity", "spacing", "thickness"],
    },
    ShaderDef {
        name: "emboss",
        shader_file: "emboss.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[("angle", 0.785), ("strength", 0.0), ("blend", 0.0)],
        active_ranges: &[
            ("angle", 0.0, 6.28),
            ("strength", 0.10, 0.35),
            ("blend", 0.05, 0.18),
        ],
        param_order: &["angle", "strength", "blend"],
    },
    ShaderDef {
        name: "thermal",
        shader_file: "thermal.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[("edge_glow", -1.0), ("palette_shift", 0.0)],
        active_ranges: &[("edge_glow", 0.35, 0.85), ("palette_shift", 0.0, 1.0)],
        param_order: &["edge_glow", "palette_shift"],
    },
    ShaderDef {
        name: "halftone",
        shader_file: "halftone.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[("dot_size", 0.5), ("color_mode", 1.0)],
        active_ranges: &[("dot_size", 1.6, 5.2), ("color_mode", 1.0, 1.0)],
        param_order: &["dot_size", "color_mode"],
    },
    ShaderDef {
        name: "posterize",
        shader_file: "posterize.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[("levels", 256.0), ("gamma", 1.0)],
        active_ranges: &[("levels", 3.0, 10.0), ("gamma", 0.85, 1.2)],
        param_order: &["levels", "gamma"],
    },
    ShaderDef {
        name: "sharpen",
        shader_file: "sharpen.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[("amount", 0.0), ("radius", 1.0)],
        active_ranges: &[("amount", 0.12, 0.55), ("radius", 0.75, 1.8)],
        param_order: &["amount", "radius"],
    },
    ShaderDef {
        name: "kaleidoscope",
        shader_file: "kaleidoscope.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[
            ("segments", 1.0),
            ("center_x", 0.5),
            ("center_y", 0.5),
            ("rotation", 0.0),
        ],
        active_ranges: &[
            ("segments", 2.5, 7.0),
            ("center_x", 0.47, 0.53),
            ("center_y", 0.47, 0.53),
            ("rotation", 0.18, 1.15),
        ],
        param_order: &["segments", "center_x", "center_y", "rotation"],
    },
    ShaderDef {
        name: "kuwahara",
        shader_file: "kuwahara.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[("radius", 0.0), ("width", 1280.0), ("height", 720.0)],
        active_ranges: &[
            ("radius", 0.6, 2.0),
            ("width", 1280.0, 1280.0),
            ("height", 720.0, 720.0),
        ],
        param_order: &["radius", "width", "height"],
    },
    ShaderDef {
        name: "noise_overlay",
        shader_file: "noise_overlay.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[("intensity", 0.0), ("animated", 0.0)],
        active_ranges: &[("intensity", 0.02, 0.10), ("animated", 0.0, 0.0)],
        param_order: &["intensity", "animated"],
    },
    ShaderDef {
        name: "grain_bump",
        shader_file: "grain_bump.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[("strength", 0.0)],
        active_ranges: &[("strength", 0.12, 0.42)],
        param_order: &["strength"],
    },
    ShaderDef {
        name: "fisheye",
        shader_file: "fisheye.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[
            ("strength", 0.0),
            ("center_x", 0.5),
            ("center_y", 0.5),
            ("zoom", 1.0),
        ],
        active_ranges: &[
            ("strength", 0.20, 0.58),
            ("center_x", 0.42, 0.58),
            ("center_y", 0.42, 0.58),
            ("zoom", 0.94, 1.06),
        ],
        param_order: &["strength", "center_x", "center_y", "zoom"],
    },
    ShaderDef {
        name: "mirror",
        shader_file: "mirror.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[("axis", 0.0), ("position", 1.0)],
        active_ranges: &[("axis", 0.0, 1.0), ("position", 0.22, 0.68)],
        param_order: &["axis", "position"],
    }, // ── Batch 2: remaining 2D parity effects ──
    ShaderDef {
        name: "dither",
        shader_file: "dither.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[
            ("matrix_size", 4.0),
            ("color_levels", 256.0),
            ("monochrome", 0.0),
        ],
        active_ranges: &[
            ("matrix_size", 4.0, 4.0),
            ("color_levels", 3.0, 10.0),
            ("monochrome", 0.0, 0.0),
        ],
        param_order: &["matrix_size", "color_levels", "monochrome"],
    },
    ShaderDef {
        name: "color_map",
        shader_file: "color_map.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[("blend", 0.0)],
        active_ranges: &[("blend", 0.18, 0.55)],
        param_order: &["blend"],
    },
    ShaderDef {
        name: "transform",
        shader_file: "transform.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[
            ("pos_x", 0.0),
            ("pos_y", 0.0),
            ("scale_x", 1.0),
            ("scale_y", 1.0),
            ("rotation", 0.0),
            ("pivot_x", 0.5),
            ("pivot_y", 0.5),
        ],
        active_ranges: &[
            ("pos_x", -0.026, 0.026),
            ("pos_y", -0.018, 0.018),
            ("scale_x", 1.0, 1.08),
            ("scale_y", 1.0, 1.08),
            ("rotation", -0.12, 0.12),
            ("pivot_x", 0.5, 0.5),
            ("pivot_y", 0.5, 0.5),
        ],
        param_order: &[
            "pos_x", "pos_y", "scale_x", "scale_y", "rotation", "pivot_x", "pivot_y",
        ],
    },
    ShaderDef {
        name: "voronoi_overlay",
        shader_file: "voronoi_overlay.wgsl",
        family: "edge",
        is_spatial: false,
        passthrough: &[
            ("cell_count", 7.0),
            ("edge_width", 0.0),
            ("animation_speed", 0.0),
            ("jitter", 0.0),
        ],
        active_ranges: &[
            ("cell_count", 4.0, 9.0),
            ("edge_width", 0.004, 0.014),
            ("animation_speed", 0.02, 0.10),
            ("jitter", 0.10, 0.35),
        ],
        param_order: &["cell_count", "edge_width", "animation_speed", "jitter"],
    },
    ShaderDef {
        name: "palette",
        shader_file: "palette.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[("saturation", 1.0), ("brightness", 1.0), ("contrast", 1.0)],
        active_ranges: &[
            ("saturation", 0.65, 1.35),
            ("brightness", 1.0, 1.12),
            ("contrast", 0.9, 1.25),
        ],
        param_order: &["saturation", "brightness", "contrast"],
    },
    ShaderDef {
        name: "palette_remap",
        shader_file: "palette_remap.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[
            ("palette_id", 0.0),
            ("cycle_rate", 0.0),
            ("n_bands", 8.0),
            ("blend", 0.0),
            ("time", 0.0),
        ],
        active_ranges: &[
            ("palette_id", 0.0, 0.0),
            ("cycle_rate", 0.006, 0.020),
            ("n_bands", 5.0, 12.0),
            ("blend", 0.08, 0.18),
            ("time", 0.0, 120.0),
        ],
        param_order: &["palette_id", "cycle_rate", "n_bands", "blend", "time"],
    },
    ShaderDef {
        name: "palette_extract",
        shader_file: "palette_extract.wgsl",
        family: "atmospheric",
        is_spatial: false,
        passthrough: &[
            ("swatch_count", 6.0),
            ("strip_height", 0.1),
            ("strip_opacity", 0.0),
            ("width", 1280.0),
            ("height", 720.0),
        ],
        active_ranges: &[
            ("swatch_count", 5.0, 9.0),
            ("strip_height", 0.035, 0.10),
            ("strip_opacity", 0.14, 0.38),
            ("width", 1280.0, 1280.0),
            ("height", 720.0, 720.0),
        ],
        param_order: &[
            "swatch_count",
            "strip_height",
            "strip_opacity",
            "width",
            "height",
        ],
    },
    ShaderDef {
        name: "slitscan",
        shader_file: "slitscan.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[("direction", 0.0), ("speed", 0.0)],
        active_ranges: &[("direction", 0.0, 1.0), ("speed", 0.35, 0.85)],
        param_order: &["direction", "speed"],
    },
    ShaderDef {
        name: "trail",
        shader_file: "trail.wgsl",
        family: "temporal",
        is_spatial: false,
        passthrough: &[
            ("fade", 1.0),
            ("opacity", 0.0),
            ("blend_mode", 1.0),
            ("drift_x", 0.0),
            ("drift_y", 0.0),
        ],
        active_ranges: &[
            ("fade", 0.16, 0.34),
            ("opacity", 0.08, 0.26),
            ("blend_mode", 1.0, 1.0),
            ("drift_x", -2.5, 2.5),
            ("drift_y", -1.5, 1.5),
        ],
        param_order: &["fade", "opacity", "blend_mode", "drift_x", "drift_y"],
    },
    ShaderDef {
        name: "echo",
        shader_file: "echo.wgsl",
        family: "temporal",
        is_spatial: false,
        passthrough: &[
            ("frame_count", 1.0),
            ("decay_curve", 1.0),
            ("blend_mode", 1.0),
        ],
        active_ranges: &[
            ("frame_count", 2.0, 4.0),
            ("decay_curve", 0.6, 1.4),
            ("blend_mode", 1.0, 1.0),
        ],
        param_order: &["frame_count", "decay_curve", "blend_mode"],
    },
    ShaderDef {
        name: "stutter",
        shader_file: "stutter.wgsl",
        family: "temporal",
        is_spatial: false,
        passthrough: &[
            ("check_interval", 60.0),
            ("freeze_chance", 0.0),
            ("freeze_min", 1.0),
            ("freeze_max", 1.0),
            ("replay_frames", 0.0),
        ],
        active_ranges: &[
            ("check_interval", 20.0, 45.0),
            ("freeze_chance", 0.02, 0.07),
            ("freeze_min", 1.0, 1.0),
            ("freeze_max", 1.0, 2.0),
            ("replay_frames", 0.0, 1.0),
        ],
        param_order: &[
            "check_interval",
            "freeze_chance",
            "freeze_min",
            "freeze_max",
            "replay_frames",
        ],
    },
    ShaderDef {
        name: "warp",
        shader_file: "warp.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[
            ("slice_count", 0.0),
            ("slice_amplitude", 0.0),
            ("pan_x", 0.0),
            ("pan_y", 0.0),
            ("rotation", 0.0),
            ("zoom", 1.0),
            ("zoom_breath", 0.0),
        ],
        active_ranges: &[
            ("slice_count", 6.0, 18.0),
            ("slice_amplitude", 12.0, 46.0),
            ("pan_x", -28.0, 28.0),
            ("pan_y", -18.0, 18.0),
            ("rotation", -0.12, 0.12),
            ("zoom", 0.94, 1.08),
            ("zoom_breath", 0.018, 0.060),
        ],
        param_order: &[
            "slice_count",
            "slice_amplitude",
            "pan_x",
            "pan_y",
            "rotation",
            "zoom",
            "zoom_breath",
        ],
    },
    ShaderDef {
        name: "displacement_map",
        shader_file: "displacement_map.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[("strength_x", 0.0), ("strength_y", 0.0)],
        active_ranges: &[("strength_x", 0.05, 0.18), ("strength_y", 0.05, 0.18)],
        param_order: &["strength_x", "strength_y"],
    },
    ShaderDef {
        name: "pixsort",
        shader_file: "pixsort.wgsl",
        family: "atmospheric",
        is_spatial: false,
        passthrough: &[
            ("threshold_low", 1.0),
            ("threshold_high", 1.0),
            ("sort_length", 0.0),
            ("direction", 0.0),
        ],
        active_ranges: &[
            ("threshold_low", 0.25, 0.50),
            ("threshold_high", 0.58, 0.88),
            ("sort_length", 20.0, 72.0),
            ("direction", 0.0, 1.0),
        ],
        param_order: &[
            "threshold_low",
            "threshold_high",
            "sort_length",
            "direction",
        ],
    },
    ShaderDef {
        name: "blend",
        shader_file: "blend.wgsl",
        family: "compositing",
        is_spatial: false,
        passthrough: &[("alpha", 0.0), ("mode", 0.0)],
        active_ranges: &[("alpha", 0.04, 0.16), ("mode", 0.0, 4.0)],
        param_order: &["alpha", "mode"],
    },
    ShaderDef {
        name: "chroma_key",
        shader_file: "chroma_key.wgsl",
        family: "compositing",
        is_spatial: false,
        passthrough: &[
            ("key_r", 0.0),
            ("key_g", 1.0),
            ("key_b", 0.0),
            ("tolerance", 0.0),
            ("softness", 0.08),
        ],
        active_ranges: &[
            ("key_r", 0.0, 0.1),
            ("key_g", 0.85, 1.0),
            ("key_b", 0.0, 0.1),
            ("tolerance", 0.18, 0.35),
            ("softness", 0.04, 0.12),
        ],
        param_order: &["key_r", "key_g", "key_b", "tolerance", "softness"],
    },
    ShaderDef {
        name: "circular_mask",
        shader_file: "circular_mask.wgsl",
        family: "atmospheric",
        is_spatial: false,
        passthrough: &[("radius", 1.0), ("softness", 0.12)],
        active_ranges: &[("radius", 0.58, 0.90), ("softness", 0.08, 0.24)],
        param_order: &["radius", "softness"],
    },
    ShaderDef {
        name: "crossfade",
        shader_file: "crossfade.wgsl",
        family: "compositing",
        is_spatial: false,
        passthrough: &[("mix", 0.0)],
        active_ranges: &[("mix", 0.03, 0.18)],
        param_order: &["mix"],
    },
    ShaderDef {
        name: "diff",
        shader_file: "diff.wgsl",
        family: "temporal",
        is_spatial: false,
        passthrough: &[("threshold", 0.3), ("color_mode", 0.0)],
        active_ranges: &[("threshold", 0.03, 0.12), ("color_mode", 0.0, 2.0)],
        param_order: &["threshold", "color_mode"],
    },
    ShaderDef {
        name: "droste",
        shader_file: "droste.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[
            ("zoom_speed", 0.0),
            ("spiral", 0.0),
            ("center_x", 0.5),
            ("center_y", 0.5),
            ("branches", 1.0),
        ],
        active_ranges: &[
            ("zoom_speed", 0.16, 0.42),
            ("spiral", 0.22, 0.88),
            ("center_x", 0.48, 0.52),
            ("center_y", 0.48, 0.52),
            ("branches", 1.0, 4.0),
        ],
        param_order: &["zoom_speed", "spiral", "center_x", "center_y", "branches"],
    },
    ShaderDef {
        name: "luma_key",
        shader_file: "luma_key.wgsl",
        family: "compositing",
        is_spatial: false,
        passthrough: &[("threshold", 1.0), ("softness", 0.08), ("invert", 0.0)],
        active_ranges: &[
            ("threshold", 0.42, 0.68),
            ("softness", 0.04, 0.12),
            ("invert", 0.0, 0.0),
        ],
        param_order: &["threshold", "softness", "invert"],
    },
    ShaderDef {
        name: "nightvision_tint",
        shader_file: "nightvision_tint.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[
            ("green_intensity", 0.0),
            ("brightness", 1.0),
            ("contrast", 1.0),
        ],
        active_ranges: &[
            ("green_intensity", 0.35, 0.70),
            ("brightness", 1.0, 1.08),
            ("contrast", 1.0, 1.15),
        ],
        param_order: &["green_intensity", "brightness", "contrast"],
    },
    ShaderDef {
        name: "noise_gen",
        shader_file: "noise_gen.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[
            ("frequency_x", 3.0),
            ("frequency_y", 3.0),
            ("octaves", 2.0),
            ("amplitude", 0.0),
            ("speed", 0.0),
        ],
        active_ranges: &[
            ("frequency_x", 1.5, 6.0),
            ("frequency_y", 1.5, 6.0),
            ("octaves", 2.0, 4.0),
            ("amplitude", 0.015, 0.08),
            ("speed", 0.02, 0.30),
        ],
        param_order: &[
            "frequency_x",
            "frequency_y",
            "octaves",
            "amplitude",
            "speed",
        ],
    },
    ShaderDef {
        name: "particle_system",
        shader_file: "particle_system.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[
            ("emit_rate", 0.0),
            ("lifetime", 2.0),
            ("size", 1.5),
            ("color_r", 0.4),
            ("color_g", 0.8),
            ("color_b", 1.0),
            ("gravity_y", 0.0),
        ],
        active_ranges: &[
            ("emit_rate", 24.0, 96.0),
            ("lifetime", 1.5, 4.0),
            ("size", 1.0, 3.0),
            ("color_r", 0.25, 1.0),
            ("color_g", 0.25, 1.0),
            ("color_b", 0.25, 1.0),
            ("gravity_y", 0.0, 60.0),
        ],
        param_order: &[
            "emit_rate",
            "lifetime",
            "size",
            "color_r",
            "color_g",
            "color_b",
            "gravity_y",
        ],
    },
    ShaderDef {
        name: "solid",
        shader_file: "solid.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[
            ("color_r", 0.0),
            ("color_g", 0.0),
            ("color_b", 0.0),
            ("color_a", 0.0),
        ],
        active_ranges: &[
            ("color_r", 0.1, 0.8),
            ("color_g", 0.1, 0.8),
            ("color_b", 0.1, 0.8),
            ("color_a", 0.02, 0.10),
        ],
        param_order: &["color_r", "color_g", "color_b", "color_a"],
    },
    ShaderDef {
        name: "strobe",
        shader_file: "strobe.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[
            ("active", 0.0),
            ("color_r", 1.0),
            ("color_g", 1.0),
            ("color_b", 1.0),
            ("color_a", 0.0),
        ],
        active_ranges: &[
            ("active", 0.22, 0.58),
            ("color_r", 0.2, 1.0),
            ("color_g", 0.2, 1.0),
            ("color_b", 0.2, 1.0),
            ("color_a", 0.05, 0.14),
        ],
        param_order: &["active", "color_r", "color_g", "color_b", "color_a"],
    },
    ShaderDef {
        name: "threshold",
        shader_file: "threshold.wgsl",
        family: "edge",
        is_spatial: false,
        passthrough: &[("level", 1.0), ("softness", 0.30)],
        active_ranges: &[("level", 0.35, 0.65), ("softness", 0.10, 0.30)],
        param_order: &["level", "softness"],
    },
    ShaderDef {
        name: "tile",
        shader_file: "tile.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[
            ("count_x", 1.0),
            ("count_y", 1.0),
            ("mirror", 0.0),
            ("gap", 0.0),
        ],
        active_ranges: &[
            ("count_x", 1.8, 5.5),
            ("count_y", 1.8, 5.5),
            ("mirror", 0.0, 1.0),
            ("gap", 0.0, 0.050),
        ],
        param_order: &["count_x", "count_y", "mirror", "gap"],
    },
    ShaderDef {
        name: "tunnel",
        shader_file: "tunnel.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[
            ("speed", 0.0),
            ("twist", 0.0),
            ("radius", 0.16),
            ("distortion", 1.0),
        ],
        active_ranges: &[
            ("speed", 0.18, 0.62),
            ("twist", 0.35, 1.15),
            ("radius", 0.08, 0.22),
            ("distortion", 1.2, 4.8),
        ],
        param_order: &["speed", "twist", "radius", "distortion"],
    },
    ShaderDef {
        name: "waveform_render",
        shader_file: "waveform_render.wgsl",
        family: "edge",
        is_spatial: false,
        passthrough: &[
            ("shape", 0.0),
            ("thickness", 1.2),
            ("color_r", 0.2),
            ("color_g", 0.8),
            ("color_b", 1.0),
            ("color_a", 0.0),
            ("scale", 0.5),
        ],
        active_ranges: &[
            ("shape", 0.0, 2.0),
            ("thickness", 0.9, 3.2),
            ("color_r", 0.2, 1.0),
            ("color_g", 0.2, 1.0),
            ("color_b", 0.2, 1.0),
            ("color_a", 0.08, 0.28),
            ("scale", 0.45, 0.95),
        ],
        param_order: &[
            "shape",
            "thickness",
            "color_r",
            "color_g",
            "color_b",
            "color_a",
            "scale",
        ],
    },
    ShaderDef {
        name: "breathing",
        shader_file: "breathing.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[("rate", 0.2), ("amplitude", 0.0)],
        active_ranges: &[("rate", 0.08, 0.75), ("amplitude", 0.010, 0.026)],
        param_order: &["rate", "amplitude"],
    },
    ShaderDef {
        name: "syrup",
        shader_file: "syrup.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[
            ("color_r", 0.0),
            ("color_g", 0.0),
            ("color_b", 0.0),
            ("top_alpha", 0.0),
            ("bottom_alpha", 0.0),
        ],
        active_ranges: &[
            ("color_r", 0.1, 0.8),
            ("color_g", 0.1, 0.8),
            ("color_b", 0.1, 0.8),
            ("top_alpha", 0.04, 0.18),
            ("bottom_alpha", 0.04, 0.18),
        ],
        param_order: &["color_r", "color_g", "color_b", "top_alpha", "bottom_alpha"],
    },
    ShaderDef {
        name: "fluid_sim",
        shader_file: "fluid_sim.wgsl",
        family: "temporal",
        is_spatial: false,
        passthrough: &[
            ("viscosity", 0.001),
            ("vorticity", 0.0),
            ("dissipation", 0.98),
            ("speed", 0.0),
            ("amount", 0.0),
        ],
        active_ranges: &[
            ("viscosity", 0.001, 0.006),
            ("vorticity", 0.45, 1.6),
            ("dissipation", 0.94, 0.995),
            ("speed", 0.4, 1.4),
            ("amount", 0.08, 0.28),
        ],
        param_order: &["viscosity", "vorticity", "dissipation", "speed", "amount"],
    },
    ShaderDef {
        name: "reaction_diffusion",
        shader_file: "reaction_diffusion.wgsl",
        family: "temporal",
        is_spatial: false,
        passthrough: &[
            ("feed_rate", 0.055),
            ("kill_rate", 0.062),
            ("diffusion_a", 1.0),
            ("diffusion_b", 0.5),
            ("speed", 0.0),
            ("amount", 0.0),
        ],
        active_ranges: &[
            ("feed_rate", 0.035, 0.070),
            ("kill_rate", 0.045, 0.066),
            ("diffusion_a", 0.8, 1.2),
            ("diffusion_b", 0.35, 0.65),
            ("speed", 0.4, 1.3),
            ("amount", 0.08, 0.25),
        ],
        param_order: &[
            "feed_rate",
            "kill_rate",
            "diffusion_a",
            "diffusion_b",
            "speed",
            "amount",
        ],
    },
];

// Always-on bookends (not in drift pool)
pub static FEEDBACK_DEF: ShaderDef = ShaderDef {
    name: "feedback",
    shader_file: "feedback.wgsl",
    family: "temporal",
    is_spatial: false,
    passthrough: &[
        ("decay", 0.0),
        ("zoom", 1.0),
        ("rotate", 0.0),
        ("blend_mode", 3.0),
        ("hue_shift", 0.0),
        ("trace_center_x", 0.5),
        ("trace_center_y", 0.5),
        ("trace_radius", 0.0),
        ("trace_strength", 0.0),
    ],
    active_ranges: &[
        ("decay", 0.012, 0.055),
        ("zoom", 1.000, 1.006),
        ("rotate", -0.004, 0.004),
        ("blend_mode", 3.0, 3.0),
        ("hue_shift", 0.002, 0.010),
    ],
    param_order: &[
        "decay",
        "zoom",
        "rotate",
        "blend_mode",
        "hue_shift",
        "trace_center_x",
        "trace_center_y",
        "trace_radius",
        "trace_strength",
    ],
};

pub static POSTPROCESS_DEF: ShaderDef = ShaderDef {
    name: "post",
    shader_file: "postprocess.wgsl",
    family: "atmospheric",
    is_spatial: false,
    passthrough: &[
        ("vignette_strength", 0.0),
        ("sediment_strength", 0.0),
        ("master_opacity", 1.0),
        ("anonymize", 0.34),
    ],
    active_ranges: &[
        ("vignette_strength", 0.04, 0.18),
        ("sediment_strength", 0.008, 0.028),
        ("master_opacity", 1.0, 1.0),
        ("anonymize", 0.34, 0.34),
    ],
    param_order: &[
        "vignette_strength",
        "sediment_strength",
        "master_opacity",
        "anonymize",
    ],
};

// Family affinity
fn families_affine(a: &str, b: &str) -> bool {
    match a {
        "tonal" => matches!(b, "tonal" | "atmospheric" | "texture"),
        "texture" => matches!(b, "texture" | "tonal" | "edge"),
        "edge" => matches!(b, "edge" | "texture" | "atmospheric"),
        "atmospheric" => matches!(b, "atmospheric" | "tonal" | "edge"),
        "temporal" => matches!(b, "temporal" | "texture" | "compositing"),
        "compositing" => matches!(b, "compositing" | "temporal" | "tonal"),
        _ => true,
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum EvictionCadence {
    Slow,
    Fast,
}

fn eviction_cadence(def: &ShaderDef) -> EvictionCadence {
    match def.name {
        // These effects can be useful, but they tend to seize the whole
        // surface or dominate other treatments. They are transient inflections,
        // not long-dwell atmospheres.
        "ascii"
        | "blend"
        | "breathing"
        | "chroma_key"
        | "chromatic_aberration"
        | "color_map"
        | "crossfade"
        | "dither"
        | "displacement_map"
        | "diff"
        | "droste"
        | "edge_detect"
        | "echo"
        | "fisheye"
        | "fluid_sim"
        | "glitch_block"
        | "halftone"
        | "kaleidoscope"
        | "luma_key"
        | "mirror"
        | "noise_gen"
        | "palette_extract"
        | "palette_remap"
        | "particle_system"
        | "pixsort"
        | "posterize"
        | "reaction_diffusion"
        | "rutt_etra"
        | "scanlines"
        | "slitscan"
        | "strobe"
        | "stutter"
        | "thermal"
        | "threshold"
        | "tile"
        | "transform"
        | "tunnel"
        | "trail"
        | "vhs"
        | "warp"
        | "waveform_render" => EvictionCadence::Fast,
        _ => EvictionCadence::Slow,
    }
}

fn eviction_cadence_label(def: &ShaderDef) -> &'static str {
    match eviction_cadence(def) {
        EvictionCadence::Slow => "slow",
        EvictionCadence::Fast => "fast",
    }
}

fn is_fast_evict(def: &ShaderDef) -> bool {
    eviction_cadence(def) == EvictionCadence::Fast
}

fn fade_in_duration(def: &ShaderDef, rng: &mut SimpleRng) -> f32 {
    let base = if is_fast_evict(def) {
        FAST_FADE_IN_S
    } else {
        FADE_IN_S
    };
    base * rng.range(0.8, 1.2)
}

fn peak_hold_duration(def: &ShaderDef, rng: &mut SimpleRng) -> f32 {
    let base = if is_fast_evict(def) {
        FAST_PEAK_HOLD_S
    } else {
        PEAK_HOLD_S
    };
    base * rng.range(0.6, 1.4)
}

fn fade_out_duration(def: &ShaderDef, rng: &mut SimpleRng) -> f32 {
    let base = if is_fast_evict(def) {
        FAST_FADE_OUT_S
    } else {
        FADE_OUT_S
    };
    base * rng.range(0.8, 1.2)
}

fn retire_intensity_floor(def: &ShaderDef) -> f32 {
    if is_fast_evict(def) {
        FAST_RETIRE_INTENSITY_FLOOR
    } else {
        RETIRE_INTENSITY_FLOOR
    }
}

fn recruit_warm_progress(def: &ShaderDef) -> f32 {
    if is_fast_evict(def) {
        FAST_RECRUIT_WARM_PROGRESS
    } else {
        RECRUIT_WARM_PROGRESS
    }
}

fn lifecycle_rise_intensity(def: &ShaderDef, progress: f32, peak: f32) -> f32 {
    let progress = progress.clamp(0.0, 1.0);
    if is_fast_evict(def) || is_punctuation_anchor(def) {
        let attack = (progress / 0.28).clamp(0.0, 1.0);
        let attack = attack * attack * (3.0 - 2.0 * attack);
        let floor = peak * 0.72;
        let late = ((progress - 0.28) / 0.72).clamp(0.0, 1.0);
        let late = late * late * (3.0 - 2.0 * late);
        return floor * attack + (peak - floor) * late;
    }

    let staged = if progress < 0.42 {
        0.62 * (progress / 0.42).clamp(0.0, 1.0)
    } else if progress < 0.78 {
        0.62
    } else {
        0.62 + 0.38 * ((progress - 0.78) / 0.22).clamp(0.0, 1.0)
    };
    peak * staged
}

fn lifecycle_fall_intensity(def: &ShaderDef, progress: f32, peak: f32) -> f32 {
    let progress = progress.clamp(0.0, 1.0);
    if is_fast_evict(def) || is_punctuation_anchor(def) {
        if progress < 0.55 {
            return peak;
        }
        let drop = ((progress - 0.55) / 0.45).clamp(0.0, 1.0);
        let drop = drop * drop * (3.0 - 2.0 * drop);
        return peak * (1.0 - drop);
    }

    if progress < 0.40 {
        return peak * 0.86;
    }
    let drop = ((progress - 0.40) / 0.60).clamp(0.0, 1.0);
    let drop = drop * drop * (3.0 - 2.0 * drop);
    peak * (0.86 * (1.0 - drop))
}

fn lifecycle_warm_intensity(def: &ShaderDef, progress: f32, peak: f32) -> f32 {
    lifecycle_rise_intensity(def, progress, peak).max(INITIAL_VISIBLE_FLOOR.min(peak))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn shader_params(shader_file: &str) -> Vec<String> {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../agents/shaders/nodes")
            .join(shader_file);
        let source = std::fs::read_to_string(&path)
            .unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
        let start = source
            .find("struct Params")
            .unwrap_or_else(|| panic!("{} has no Params struct", shader_file));
        let open = source[start..]
            .find('{')
            .map(|idx| start + idx + 1)
            .unwrap_or_else(|| panic!("{} Params has no opening brace", shader_file));
        let close = source[open..]
            .find('}')
            .map(|idx| open + idx)
            .unwrap_or_else(|| panic!("{} Params has no closing brace", shader_file));

        source[open..close]
            .lines()
            .filter_map(|line| {
                let trimmed = line.trim();
                let name_start = trimmed.find("u_")?;
                let name_end = trimmed[name_start..].find(':')? + name_start;
                Some(trimmed[name_start + 2..name_end].trim().to_string())
            })
            .collect()
    }

    fn generated_chain_for_test(anchor: &'static str, nodes: Vec<&'static str>) -> GeneratedChain {
        GeneratedChain {
            id: format!("rng-chain:{anchor}:test:0000"),
            lineage: "rng-constrained:test".to_string(),
            structural_signature: chain_structural_signature(anchor, &nodes),
            topology_signature: format!("rng:{}:{}:vtest", anchor, nodes.join(":")),
            anchor,
            nodes,
            param_seed: 0xC0FFEE,
        }
    }

    #[test]
    fn autonomous_shader_param_orders_match_wgsl_contracts() {
        for def in SHADERS.iter().chain([&FEEDBACK_DEF, &POSTPROCESS_DEF]) {
            assert_eq!(
                def.param_order,
                shader_params(def.shader_file).as_slice(),
                "{} param order must match {}",
                def.name,
                def.shader_file
            );
        }
    }

    #[test]
    fn autonomous_peak_intensity_reaches_safe_active_ranges() {
        let spatial = SHADERS.iter().find(|def| def.name == "fisheye").unwrap();
        let nonspatial = SHADERS.iter().find(|def| def.name == "posterize").unwrap();
        let mut rng = SimpleRng::new(42);

        for _ in 0..16 {
            let spatial_peak = random_peak_intensity(&mut rng, spatial);
            assert!(
                (SPATIAL_PEAK_RANGE.0..=SPATIAL_PEAK_RANGE.1).contains(&spatial_peak),
                "spatial peak {spatial_peak} outside safe visible range"
            );
            assert!(
                spatial_peak >= 0.45,
                "spatial drift must not spend peak in near-noop range"
            );

            let nonspatial_peak = random_peak_intensity(&mut rng, nonspatial);
            assert!(
                (NONSPATIAL_PEAK_RANGE.0..=NONSPATIAL_PEAK_RANGE.1).contains(&nonspatial_peak),
                "nonspatial peak {nonspatial_peak} outside safe visible range"
            );
            assert!(
                nonspatial_peak >= 0.75,
                "nonspatial drift must reach the bounded active range at peak"
            );
        }
    }

    #[test]
    fn autonomous_targets_are_pushed_away_from_passthrough() {
        let mut rng = SimpleRng::new(42);

        for def in SHADERS
            .iter()
            .filter(|def| is_autonomous_drift_candidate(def))
        {
            let target = SlotDriftEngine::random_target(&mut rng, def);
            for &(name, lo, hi) in def.active_ranges {
                if (hi - lo).abs() <= f32::EPSILON {
                    continue;
                }
                let passthrough = def
                    .passthrough
                    .iter()
                    .find(|(candidate, _)| *candidate == name)
                    .map(|(_, value)| *value)
                    .unwrap_or(lo);
                let value = target
                    .iter()
                    .find(|(candidate, _)| candidate == name)
                    .map(|(_, value)| *value)
                    .unwrap_or_else(|| panic!("missing target {}.{}", def.name, name));
                let range = hi - lo;
                let expected_delta = range * target_departure_fraction(def);
                let actual_delta = (value - passthrough).abs();

                assert!(
                    actual_delta + 0.0001 >= expected_delta
                        || (passthrough - lo).abs() < expected_delta
                        || (hi - passthrough).abs() < expected_delta,
                    "{}.{} target {} is too close to passthrough {} for assertive drift",
                    def.name,
                    name,
                    value,
                    passthrough
                );
            }
        }
    }

    #[test]
    fn brightness_targets_never_dim_the_live_surface() {
        let mut rng = SimpleRng::new(42);

        for def in SHADERS
            .iter()
            .filter(|def| is_autonomous_drift_candidate(def))
        {
            let target = SlotDriftEngine::random_target(&mut rng, def);
            for (name, value) in target {
                if name == "brightness" {
                    assert!(
                        value >= 1.0,
                        "{}.brightness target must amplify or preserve brightness, got {}",
                        def.name,
                        value
                    );
                }
            }
        }
    }

    #[test]
    fn punctuation_targets_do_not_land_in_low_driver_regions() {
        let mut rng = SimpleRng::new(42);

        for def in SHADERS
            .iter()
            .filter(|def| is_composed_surface_drift_candidate(def))
            .filter(|def| is_punctuation_anchor(def))
        {
            let target = SlotDriftEngine::random_target(&mut rng, def);
            for (name, value) in target {
                if assertive_min_normalized(def, &name).is_some() {
                    assert_ne!(
                        parameter_region(def, &name, value),
                        "low",
                        "{}.{} punctuation driver target {} must not satisfy the scheduler while reading as low-impact",
                        def.name,
                        name,
                        value
                    );
                }
            }
        }
    }

    #[test]
    fn punctuation_lifecycle_attacks_and_retires_as_an_inflection_not_a_breath() {
        let def = SHADERS
            .iter()
            .find(|def| def.name == "glitch_block")
            .expect("glitch block effect");
        let peak = 0.98;

        assert!(
            lifecycle_rise_intensity(def, 0.30, peak) >= peak * 0.70,
            "punctuation effects should become visible early instead of spending most of fade-in near passthrough"
        );
        assert!(
            lifecycle_fall_intensity(def, 0.50, peak) >= peak * 0.95,
            "punctuation effects should hold identity before dropping out"
        );
        assert!(
            lifecycle_fall_intensity(def, 0.90, peak) <= peak * 0.30,
            "punctuation effects should exit decisively after the hold"
        );
    }

    #[test]
    fn parameter_regimes_hold_values_instead_of_continuously_sine_sweeping() {
        let shader_idx = shader_idx_by_name("glitch_block").expect("glitch block");
        let def = &SHADERS[shader_idx];
        let param_index = def
            .param_order
            .iter()
            .position(|name| *name == "intensity")
            .expect("intensity param");
        let seed = parameter_regime_seed(1, 0, shader_idx, param_index);
        let hold = parameter_regime_hold_seconds(seed);
        let phase = parameter_regime_phase_offset(seed, hold);
        let bucket_start = hold * 4.0 - phase;
        let first = held_parameter_regime(
            def,
            1,
            0,
            shader_idx,
            param_index,
            bucket_start + hold * 0.34,
        );
        let second = held_parameter_regime(
            def,
            1,
            0,
            shader_idx,
            param_index,
            bucket_start + hold * 0.52,
        );

        assert!(
            (first - second).abs() < 0.0001,
            "parameter regimes should plateau inside a hold bucket instead of continuously tracing a sine; {first} vs {second}"
        );
    }

    #[test]
    fn dominant_effects_use_fast_evict_cadence() {
        let fast_names = [
            "ascii",
            "chromatic_aberration",
            "color_map",
            "dither",
            "displacement_map",
            "droste",
            "edge_detect",
            "fisheye",
            "fluid_sim",
            "glitch_block",
            "halftone",
            "kaleidoscope",
            "mirror",
            "noise_gen",
            "palette_extract",
            "palette_remap",
            "particle_system",
            "pixsort",
            "posterize",
            "reaction_diffusion",
            "rutt_etra",
            "scanlines",
            "slitscan",
            "strobe",
            "stutter",
            "thermal",
            "threshold",
            "tile",
            "transform",
            "tunnel",
            "vhs",
            "warp",
            "waveform_render",
        ];

        for name in fast_names {
            let def = SHADERS
                .iter()
                .find(|def| def.name == name)
                .unwrap_or_else(|| panic!("missing fast-evict effect {name}"));
            assert!(
                is_fast_evict(def),
                "{name} should be a fast-evict effect because it can dominate the surface"
            );
        }
    }

    #[test]
    fn dramatic_effects_are_high_impingement_anchors() {
        for name in ["slitscan", "fluid_sim"] {
            let def = SHADERS
                .iter()
                .find(|def| def.name == name)
                .unwrap_or_else(|| panic!("missing dramatic temporal effect {name}"));
            assert!(
                is_high_impingement_anchor(def),
                "{name} must count as a high-impingement anchor so intensity repair can actively restore it"
            );
        }
    }

    #[test]
    fn operator_facing_dramatic_aliases_are_discoverable() {
        for name in ["fluid_sim", "tunnel", "droste", "kaleidoscope"] {
            let def = SHADERS
                .iter()
                .find(|def| def.name == name)
                .unwrap_or_else(|| panic!("missing vortex-capable effect {name}"));
            assert!(
                effect_aliases(def).contains(&"vortex"),
                "{name} must be discoverable as an operator-facing vortex behavior"
            );
        }
    }

    #[test]
    fn slot_drift_plan_exposes_live_surface_effect_metadata() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-metadata-{}.json",
            std::process::id()
        ));
        let _engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);
        let raw = std::fs::read_to_string(&path).expect("read SlotDrift plan");
        let plan: serde_json::Value = serde_json::from_str(&raw).expect("plan json parses");
        let passes = plan["targets"]["main"]["passes"]
            .as_array()
            .expect("main passes are present");
        let coverage = &plan["slotdrift_coverage"];
        assert_eq!(
            coverage["schema"].as_str(),
            Some("slotdrift-coverage-v1"),
            "SlotDrift plan must carry a machine-readable coverage ledger"
        );
        assert!(
            coverage["effect_counts"]
                .as_array()
                .is_some_and(|counts| counts.len() >= SHADERS.len() - 1),
            "coverage ledger must account for the autonomous effect inventory"
        );
        assert!(
            coverage["family_counts"].as_array().is_some(),
            "coverage ledger must expose family coverage debt"
        );
        assert!(
            coverage["visibility_group_counts"].as_array().is_some(),
            "coverage ledger must expose visibility-group coverage debt"
        );
        assert!(
            coverage["alias_counts"].as_array().is_some(),
            "coverage ledger must expose operator-facing alias coverage debt"
        );
        assert!(
            coverage["parameter_region_counts"].as_array().is_some(),
            "coverage ledger must expose parameter-region coverage debt"
        );

        for node_id in ["fb", "post"] {
            let pass = passes
                .iter()
                .find(|pass| pass["node_id"].as_str() == Some(node_id))
                .unwrap_or_else(|| panic!("{node_id} bookend pass must be present"));
            assert_eq!(
                pass["source_bound"].as_bool(),
                Some(true),
                "{node_id} bookend must be accounted as source-bound"
            );
            assert_eq!(
                pass["full_surface"].as_bool(),
                Some(true),
                "{node_id} bookend must be accounted as full-surface"
            );
            assert_eq!(
                pass["fourth_wall_policy"].as_str(),
                Some("forbid_foreground_overlay"),
                "{node_id} bookend must forbid foreground/fourth-wall overlay"
            );
            assert_eq!(
                pass["effect_binding"].as_str(),
                Some("bounded_bookend"),
                "{node_id} bookend must be classified as a bounded control stage"
            );
            assert!(
                pass["effect_application_plane"]
                    .as_str()
                    .is_some_and(|plane| plane.starts_with("entity_field_")),
                "{node_id} bookend must declare an entity-field application plane"
            );
        }

        let effect_passes: Vec<&serde_json::Value> = passes
            .iter()
            .filter(|pass| {
                let node = pass["node_id"].as_str().unwrap_or_default();
                node != "fb" && node != "post"
            })
            .collect();

        assert!(
            effect_passes.len() >= POOL_SIZE,
            "SlotDrift should publish at least one metadata-bearing pass per effect slot"
        );
        let mut slot_indices = Vec::new();
        for pass in &effect_passes {
            let Some(slot_index) = pass["slot_index"].as_u64() else {
                panic!("effect pass must carry slot_index");
            };
            if !slot_indices.contains(&slot_index) {
                slot_indices.push(slot_index);
            }
        }
        assert_eq!(
            slot_indices.len(),
            POOL_SIZE,
            "expanded motifs must still account for all five SlotDrift slots"
        );
        let mut generated_slot_chains: Vec<(u64, &str)> = Vec::new();
        for pass in &effect_passes {
            let slot_index = pass["slot_index"]
                .as_u64()
                .expect("effect pass must carry slot_index");
            let chain_id = pass["preset_chain_id"].as_str().unwrap_or_default();
            let slot_phase = pass["slot_phase"].as_str().unwrap_or_default();
            if chain_id.starts_with("rng-chain:")
                && slot_phase != "idle"
                && !generated_slot_chains
                    .iter()
                    .any(|(existing_slot, _)| *existing_slot == slot_index)
            {
                generated_slot_chains.push((slot_index, chain_id));
            }
        }
        assert!(
            generated_slot_chains.len() >= MIN_ACTIVE_GENERATED_CHAIN_SLOTS,
            "SlotDrift must synthesize a generated-chain variation floor, not mostly single-node slots: {generated_slot_chains:?}"
        );
        let mut generated_chain_ids = Vec::new();
        for (_, chain_id) in &generated_slot_chains {
            assert!(
                !generated_chain_ids.contains(chain_id),
                "simultaneous generated chains should not duplicate when alternatives exist"
            );
            generated_chain_ids.push(*chain_id);
        }

        for pass in effect_passes {
            assert_eq!(
                pass["effect_scope"].as_str(),
                Some("composed_live_surface"),
                "effect passes must declare that they operate on the composed livestream surface"
            );
            assert_eq!(
                pass["source_bound"].as_bool(),
                Some(true),
                "effect passes must declare source-bound semantics"
            );
            assert_eq!(
                pass["full_surface"].as_bool(),
                Some(true),
                "effect passes must declare full-surface execution"
            );
            assert_eq!(
                pass["effect_binding"].as_str(),
                Some("source_presence_gated"),
                "effect passes must declare source/entity gating, not foreground-pane authority"
            );
            assert_eq!(
                pass["route_authority"].as_str(),
                Some("composed_surface_drift"),
                "effect passes must only use the composed-surface route after route gating"
            );
            assert_eq!(
                pass["fourth_wall_policy"].as_str(),
                Some("forbid_foreground_overlay"),
                "effect passes must fail closed against fourth-wall/glass-pane overlays"
            );
            let plane = pass["effect_application_plane"].as_str().unwrap_or("");
            let node_id = pass["node_id"].as_str().unwrap_or("");
            let is_spatial_safe = node_id.contains("drift")
                || node_id.contains("kaleidoscope")
                || node_id.contains("mirror");
            assert!(
                matches!(plane, "entity_field_surface_treatment" | "entity_field_temporal_treatment")
                    || (plane == "entity_field_spatial_reprojection" && is_spatial_safe),
                "composed-surface effect pass {node_id} must not claim spatial reprojection unless source-bound-safe"
            );
            assert!(
                matches!(
                    pass["coverage_role"].as_str(),
                    Some(
                        "high_impingement_anchor"
                            | "visible_anchor"
                            | "supporting_conditional"
                            | "supporting_effect"
                    )
                ),
                "effect passes must declare their drift coverage role"
            );
            assert!(
                pass["effect_family"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty()),
                "effect family must be machine-checkable"
            );
            assert!(
                pass["visibility_group"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty()),
                "visibility group must be machine-checkable"
            );
            assert!(
                matches!(pass["eviction_cadence"].as_str(), Some("fast" | "slow")),
                "eviction cadence must be machine-checkable"
            );
            assert!(
                pass["effect_aliases"].as_array().is_some(),
                "operator-facing aliases must be present even when empty"
            );
            assert!(
                pass["selection_count"].as_u64().is_some(),
                "effect passes must publish selection counts for coverage-aware routing"
            );
            assert!(
                pass["coverage_window_count"].as_u64().is_some(),
                "effect passes must publish rolling coverage counts"
            );
            assert!(
                pass["parameter_regions"].as_array().is_some(),
                "effect passes must publish target parameter regions"
            );
            assert!(
                pass["preset_chain_id"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty()),
                "effect passes must publish preset/motif chain identity"
            );
            assert!(
                pass["structural_signature"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty()),
                "effect passes must publish structural signature for real chain diversity evidence"
            );
            assert!(
                pass["topology_signature"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty()),
                "effect passes must publish topology signature for variance evidence"
            );
        }

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn generated_chains_avoid_structural_duplicates_not_only_variant_ids() {
        let pixsort = shader_idx_by_name("pixsort").unwrap();
        let active_structural_signature = chain_structural_signature(
            "pixsort",
            &["pixsort", "chromatic_aberration", "glitch_block"],
        );
        let active_structural_signatures = vec![active_structural_signature.clone()];
        let active_node_names = vec![
            "chromatic_aberration",
            "glitch_block",
            "scanlines",
            "edge_detect",
        ];
        let mut rng = SimpleRng::new(0x5A1E);
        let chain = synthesize_chain_for_shader_avoiding(
            &mut rng,
            pixsort,
            &active_structural_signatures,
            &active_node_names,
        );

        assert_ne!(
            chain.structural_signature, active_structural_signature,
            "a new param/topology variant is not enough if the node set duplicates an active chain"
        );
        let reused_companions = chain
            .nodes
            .iter()
            .filter(|node| **node != "pixsort" && active_node_names.contains(node))
            .count();
        assert!(
            reused_companions < chain.nodes.len().saturating_sub(1),
            "generated chains should prefer fresh companion nodes when the active surface already uses {:?}",
            active_node_names
        );
    }

    #[test]
    fn generated_chain_seed_selection_prefers_low_active_node_overlap() {
        let pixsort = shader_idx_by_name("pixsort").unwrap();
        let active_node_names = vec!["chromatic_aberration", "glitch_block"];
        let mut rng = SimpleRng::new(0x51A7);
        let chain =
            synthesize_chain_for_shader_avoiding(&mut rng, pixsort, &[], &active_node_names);

        assert!(
            chain.nodes.contains(&"palette_remap") || chain.nodes.contains(&"scanlines"),
            "pixsort should choose a low-overlap seed/companion set, got {:?}",
            chain.nodes
        );
        assert!(
            !chain.nodes.contains(&"glitch_block")
                && !chain.nodes.contains(&"chromatic_aberration"),
            "active companion reuse flattens apparent variety; got {:?}",
            chain.nodes
        );
    }

    #[test]
    fn generated_chains_limit_serial_tonal_stacks() {
        let thermal = shader_idx_by_name("thermal").unwrap();
        let mut rng = SimpleRng::new(0x70A1);

        for _ in 0..24 {
            let chain = synthesize_chain_for_shader_avoiding(&mut rng, thermal, &[], &[]);
            let tonal_count = chain_family_count(&chain.nodes, "tonal");
            assert!(
                tonal_count <= chain_family_limit("tonal"),
                "serial tonal stacks read as luma pumping, got {:?}",
                chain.nodes
            );
        }
    }

    #[test]
    fn spatial_reprojection_effects_do_not_emit_as_composed_surface_passes() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-no-fourth-wall-spatial-{}.json",
            std::process::id()
        ));
        let _engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);
        let plan: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&path).expect("read plan"))
                .expect("effect drift plan should be valid JSON");
        let passes = plan["targets"]["main"]["passes"]
            .as_array()
            .expect("main passes are present");

        let illegal_spatial_passes: Vec<String> = passes
            .iter()
            .filter(|pass| pass["slot_index"].as_u64().is_some())
            .filter(|pass| {
                let plane = pass["effect_application_plane"].as_str();
                let route = pass["route_authority"].as_str();
                plane == Some("entity_field_spatial_reprojection")
                    || route == Some("entity_local_route_required")
            })
            .map(|pass| pass["node_id"].as_str().unwrap_or_default().to_string())
            .collect();

        assert!(
            illegal_spatial_passes.is_empty(),
            "spatial reprojection effects must not be composed-surface passes until they have an entity-local route: {illegal_spatial_passes:?}"
        );

        let route_blocked = plan["slotdrift_coverage"]["route_blocked_effects"]
            .as_array()
            .expect("coverage ledger should publish route-blocked effects");
        let blocked_names: std::collections::HashSet<&str> = route_blocked
            .iter()
            .filter_map(|entry| entry["name"].as_str())
            .collect();

        for def in SHADERS
            .iter()
            .filter(|def| requires_entity_local_route(def))
        {
            assert!(
                blocked_names.contains(def.name),
                "{} must remain inventoried as blocked route debt, not silently discarded",
                def.name
            );
        }

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn dramatic_effects_have_short_dwell_authority_not_polite_caps() {
        let required = [
            ("chromatic_aberration", "intensity", 0.70),
            ("displacement_map", "strength_x", 0.16),
            ("droste", "zoom_speed", 0.40),
            ("fisheye", "strength", 0.50),
            ("kaleidoscope", "segments", 6.0),
            ("mirror", "position", 0.65),
            ("slitscan", "speed", 0.80),
            ("tile", "count_x", 5.0),
            ("transform", "rotation", 0.10),
            ("tunnel", "twist", 1.0),
            ("warp", "slice_amplitude", 40.0),
        ];

        for (shader_name, param_name, min_hi) in required {
            let def = SHADERS
                .iter()
                .find(|def| def.name == shader_name)
                .unwrap_or_else(|| panic!("missing dramatic effect {shader_name}"));
            let (_, _, hi) = def
                .active_ranges
                .iter()
                .find(|(name, _, _)| *name == param_name)
                .copied()
                .unwrap_or_else(|| panic!("missing dramatic range {shader_name}.{param_name}"));
            assert!(
                hi >= min_hi,
                "{shader_name}.{param_name} high range {hi} is too polite for fast-evict authority"
            );
            assert!(
                is_fast_evict(def),
                "{shader_name} must be short-dwell if it has dramatic authority"
            );
        }
    }

    #[test]
    fn dramatic_shader_blend_caps_are_visible_but_bounded() {
        let shader_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");
        for (shader, expected_cap) in [
            ("displacement_map.wgsl", "0.55f"),
            ("fisheye.wgsl", "0.58f"),
            ("kaleidoscope.wgsl", "0.60f"),
            ("mirror.wgsl", "0.26f"),
            ("transform.wgsl", "0.55f"),
            ("warp.wgsl", "0.62f"),
        ] {
            let source = std::fs::read_to_string(shader_root.join(shader))
                .unwrap_or_else(|err| panic!("read {shader}: {err}"));
            assert!(
                source.contains(expected_cap),
                "{shader} must expose an assertive cap ({expected_cap}) for short-dwell dramatic use"
            );
        }
    }

    #[test]
    fn fast_evict_duration_window_is_shorter_than_slow_window() {
        let fast = SHADERS.iter().find(|def| def.name == "tunnel").unwrap();
        let slow = SHADERS.iter().find(|def| def.name == "colorgrade").unwrap();
        let mut fast_rng = SimpleRng::new(7);
        let mut slow_rng = SimpleRng::new(7);

        let fast_total = fade_in_duration(fast, &mut fast_rng)
            + peak_hold_duration(fast, &mut fast_rng)
            + fade_out_duration(fast, &mut fast_rng);
        let slow_total = fade_in_duration(slow, &mut slow_rng)
            + peak_hold_duration(slow, &mut slow_rng)
            + fade_out_duration(slow, &mut slow_rng);

        assert!(
            fast_total < slow_total * 0.55,
            "fast-evict effects should be brief inflections, not full-dwell layers"
        );
        assert!(
            fast_total > slow_total * 0.25,
            "fast-evict effects should not churn fast enough to read as periodic whole-frame pumping"
        );
        assert!(
            slow_total < 42.0 && fast_total < 20.0 && STAGGER_S <= 6.5,
            "effect traversal must not hang near baseline for long static dwell windows; slow_total={slow_total}, fast_total={fast_total}, stagger={STAGGER_S}"
        );
        assert!(
            INITIAL_VISIBLE_FLOOR >= 0.44
                && RETIRE_INTENSITY_FLOOR >= 0.26
                && FAST_RETIRE_INTENSITY_FLOOR >= 0.30,
            "drift lifecycle must stay visibly above near-noop intensity floors"
        );
        assert!(
            retire_intensity_floor(fast) > retire_intensity_floor(slow),
            "fast-evict effects should retire earlier on the fade-down"
        );
        assert!(
            recruit_warm_progress(fast) < recruit_warm_progress(slow),
            "fast-evict replacement should warm near its retirement floor, not jump over it"
        );
    }

    #[test]
    fn conditional_support_effects_are_short_dwell_inflections() {
        let slow_conditionals: Vec<&str> = SHADERS
            .iter()
            .filter(|def| is_conditionally_low_salience(def) && !is_fast_evict(def))
            .map(|def| def.name)
            .collect();

        assert!(
            slow_conditionals.is_empty(),
            "support-only effects should not hang as slow-dwell layers: {slow_conditionals:?}"
        );
    }

    #[test]
    fn parameter_regime_is_visible_without_brightness_pumping() {
        let representative = SHADERS.iter().find(|def| def.name == "warp").unwrap();
        let seed = parameter_regime_seed(0, 0, shader_idx_by_name("warp").unwrap(), 1);

        assert!(
            parameter_regime_hold_seconds(seed) <= PARAM_REGIME_MAX_HOLD_S,
            "structural parameter regimes must turn over fast enough to be witnessed inside a one-minute sample"
        );
        assert_eq!(parameter_regime_depth(representative, "brightness"), 0.0);
        assert!(
            parameter_regime_depth(representative, "slice_amplitude") >= 0.20,
            "structural parameters should carry visible held-regime variation"
        );
    }

    #[test]
    fn fast_evict_replacement_reenters_as_visible_inflection() {
        for def in SHADERS.iter().filter(|def| is_fast_evict(def)) {
            let peak_range = if def.is_spatial {
                SPATIAL_PEAK_RANGE
            } else {
                NONSPATIAL_PEAK_RANGE
            };
            let min_warm_intensity =
                lifecycle_warm_intensity(def, recruit_warm_progress(def), peak_range.0);
            assert!(
                min_warm_intensity >= peak_range.0 * 0.68,
                "{} warm-start minimum {:.3} is too close to passthrough for punctuation repair",
                def.name,
                min_warm_intensity
            );
        }
    }

    #[test]
    fn multi_input_autonomous_shaders_get_valid_inputs() {
        for name in [
            "slitscan",
            "trail",
            "echo",
            "stutter",
            "diff",
            "fluid_sim",
            "reaction_diffusion",
            "blend",
            "chroma_key",
            "crossfade",
            "luma_key",
        ] {
            let def = SHADERS
                .iter()
                .find(|def| def.name == name)
                .unwrap_or_else(|| panic!("missing autonomous shader {name}"));
            let (inputs, temporal) = pass_inputs_for(def, "layer_prev");
            assert_eq!(
                inputs,
                vec!["layer_prev".to_string(), format!("@accum_{name}")]
            );
            assert!(temporal, "{name} should bind a safe temporal/history input");
        }

        let displacement = SHADERS
            .iter()
            .find(|def| def.name == "displacement_map")
            .unwrap();
        let (inputs, temporal) = pass_inputs_for(displacement, "layer_prev");
        assert_eq!(inputs, vec!["layer_prev", "layer_prev"]);
        assert!(!temporal);
    }

    #[test]
    fn postprocess_bookend_defaults_do_not_pump_or_dim() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for time in [0.0, 600.0, 1800.0] {
            let uniforms = engine.interpolate_all(time);
            for &(name, expected) in POSTPROCESS_DEF.passthrough {
                let key = format!("post.{name}");
                let actual = uniforms
                    .iter()
                    .find(|(uniform, _)| uniform == &key)
                    .map(|(_, value)| *value)
                    .unwrap_or_else(|| panic!("missing {key}"));
                assert_eq!(
                    actual, expected,
                    "{key} must stay at passthrough; no time-driven pumping"
                );
            }
        }

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn postprocess_bookend_keeps_stable_mediation() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        let first = engine.interpolate_all(0.0);
        let later = engine.interpolate_all(1800.0);
        let first_anonymize = first
            .iter()
            .find(|(uniform, _)| uniform == "post.anonymize")
            .map(|(_, value)| *value)
            .expect("post.anonymize present");
        let later_anonymize = later
            .iter()
            .find(|(uniform, _)| uniform == "post.anonymize")
            .map(|(_, value)| *value)
            .expect("post.anonymize present later");

        assert!(
            first_anonymize >= 0.25,
            "livestream must not expose a clean transparent postprocess surface"
        );
        assert_eq!(
            first_anonymize, later_anonymize,
            "mediation is stable; no time-driven pumping"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn postprocess_default_mediation_is_static_not_time_pumped() {
        let source = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../../agents/shaders/nodes/postprocess.wgsl"),
        )
        .expect("read postprocess shader");

        assert!(
            source.contains("u_anonymize"),
            "postprocess must retain stable mediation for anti-parasocial surface treatment"
        );
        assert!(
            !source.contains("uniforms.time"),
            "default postprocess mediation must not carry time-varying scan/hash pumping"
        );
    }

    #[test]
    fn strobe_is_soft_sine_with_luma_floor() {
        let source = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes/strobe.wgsl"),
        )
        .expect("read strobe shader");

        assert!(
            source.contains("soft_wave = 0.86 + 0.14 * sin"),
            "strobe may modulate as a soft sine, not as a hard flash gate"
        );
        assert!(
            !source.contains("0.5 + (0.5 * sin"),
            "strobe must not swing from zero to full authority"
        );
        assert!(
            source.contains("source.xyz * 0.92"),
            "strobe tint must preserve a source luminance floor instead of dark-pulsing"
        );
    }

    #[test]
    fn autonomous_drift_uses_five_slots_with_four_active_initially() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-{}.json",
            std::process::id()
        ));
        let engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);
        let active = engine
            .slots
            .iter()
            .filter(|slot| slot.phase != Phase::Idle)
            .count();

        assert_eq!(engine.slots.len(), POOL_SIZE);
        assert_eq!(
            active, ACTIVE_SLOT_TARGET,
            "initial conditions should have four active effects and one rotating/recruiting slot"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn autonomous_initial_active_slots_cover_visible_effect_groups() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-visible-groups-{}.json",
            std::process::id()
        ));
        let engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);
        let active_groups: std::collections::HashSet<&str> = engine
            .slots
            .iter()
            .filter(|slot| slot.phase != Phase::Idle)
            .map(|slot| visibility_group(&SHADERS[slot.shader_idx]))
            .collect();

        for group in COMPOSED_SURFACE_BASELINE_GROUPS {
            assert!(
                active_groups.contains(group),
                "initial active effects must include visible {group} coverage; got {active_groups:?}"
            );
        }

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn autonomous_initial_active_slots_are_not_low_presence_secondaries() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-visible-only-{}.json",
            std::process::id()
        ));
        let engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for slot in engine.slots.iter().filter(|slot| slot.phase != Phase::Idle) {
            let def = &SHADERS[slot.shader_idx];
            assert!(
                is_baseline_visible(def),
                "initial active effect {} is eligible but too low-presence for baseline repair",
                def.name
            );
        }

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn autonomous_initial_active_slots_start_visibly_assertive() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-visible-intensity-{}.json",
            std::process::id()
        ));
        let engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for slot in engine.slots.iter().filter(|slot| slot.phase != Phase::Idle) {
            assert!(
                slot.intensity >= INITIAL_VISIBLE_FLOOR,
                "{} active slot starts below visible floor: {}",
                SHADERS[slot.shader_idx].name,
                slot.intensity
            );
        }

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn slot_runtime_metadata_reports_current_lifecycle_state() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-runtime-metadata-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        engine.slots[0].phase = Phase::Falling;
        engine.slots[0].intensity = 0.37;
        let shader_idx = engine.slots[0].shader_idx;
        engine.selection_counts[shader_idx] = 12;

        let metadata = engine.slot_runtime_metadata();
        let primary_suffix = format!("_{}", SHADERS[shader_idx].name);
        let first = metadata
            .iter()
            .find(|entry| entry.slot_index == 0 && entry.node_id.ends_with(&primary_suffix))
            .expect("runtime metadata should include the primary shader node for slot 0");

        assert_eq!(first.slot_index, 0);
        assert!(
            first.node_id.starts_with("slot0_"),
            "slot-managed effect nodes must have unique plan node IDs"
        );
        assert_eq!(first.slot_phase, "falling");
        assert!(
            (first.slot_intensity - 0.37).abs() < 0.0001,
            "runtime metadata must report current intensity, not last plan-reload metadata"
        );
        assert_eq!(first.selection_count, 12);
        assert!(
            !first.parameter_regions.is_empty(),
            "runtime metadata must retain target-region evidence for visual witnesses"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn autonomous_initial_active_slots_have_salience_anchors() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-salience-anchors-{}.json",
            std::process::id()
        ));
        let engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);
        let active: Vec<&ShaderDef> = engine
            .slots
            .iter()
            .filter(|slot| slot.phase != Phase::Idle)
            .map(|slot| &SHADERS[slot.shader_idx])
            .collect();
        let anchor_count = active.iter().filter(|def| is_visible_anchor(def)).count();
        let conditional_count = active
            .iter()
            .filter(|def| is_conditionally_low_salience(def))
            .count();
        let high_impingement_count = active
            .iter()
            .filter(|def| is_high_impingement_anchor(def))
            .count();
        let dramatic_variation_count = active
            .iter()
            .filter(|def| is_dramatic_variation_anchor(def))
            .count();
        let punctuation_count = active
            .iter()
            .filter(|def| is_punctuation_anchor(def))
            .count();

        assert!(
            anchor_count >= MIN_ACTIVE_ANCHOR_EFFECTS,
            "active set needs independent visible anchors; got {:?}",
            active.iter().map(|def| def.name).collect::<Vec<&str>>()
        );
        assert!(
            conditional_count <= MAX_ACTIVE_CONDITIONAL_EFFECTS,
            "conditional effects must be supporting layers, not the active set; got {:?}",
            active.iter().map(|def| def.name).collect::<Vec<&str>>()
        );
        assert!(
            high_impingement_count >= MIN_ACTIVE_HIGH_IMPINGEMENT_EFFECTS,
            "active set needs multiple high-impingement anchors; got {:?}",
            active.iter().map(|def| def.name).collect::<Vec<&str>>()
        );
        assert!(
            dramatic_variation_count >= MIN_ACTIVE_DRAMATIC_VARIATION_EFFECTS,
            "active set needs multiple dramatic variation anchors; got {:?}",
            active.iter().map(|def| def.name).collect::<Vec<&str>>()
        );
        assert!(
            punctuation_count >= MIN_ACTIVE_PUNCTUATION_EFFECTS,
            "active set needs punctuation anchors that break broad sameyness; got {:?}",
            active.iter().map(|def| def.name).collect::<Vec<&str>>()
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn configured_allowed_set_must_sustain_live_surface_invariants() {
        let valid = configured_shader_indices_from_raw(
            "halftone,color_map,fluid_sim,glitch_block,posterize",
        )
        .expect("valid constrained set should be accepted");
        let mut rng = SimpleRng::new(42);
        let pool = choose_initial_pool(&mut rng, &valid);
        let active = pool.iter().take(ACTIVE_SLOT_TARGET);
        let active_groups: std::collections::HashSet<&str> = active
            .clone()
            .map(|idx| visibility_group(&SHADERS[*idx]))
            .collect();
        let active_high_impingement = pool
            .iter()
            .take(ACTIVE_SLOT_TARGET)
            .filter(|idx| is_high_impingement_anchor(&SHADERS[**idx]))
            .count();
        let active_dramatic_variation = pool
            .iter()
            .take(ACTIVE_SLOT_TARGET)
            .filter(|idx| is_dramatic_variation_anchor(&SHADERS[**idx]))
            .count();
        let active_punctuation = pool
            .iter()
            .take(ACTIVE_SLOT_TARGET)
            .filter(|idx| is_punctuation_anchor(&SHADERS[**idx]))
            .count();

        for group in COMPOSED_SURFACE_BASELINE_GROUPS {
            assert!(
                active_groups.contains(group),
                "accepted allowed set must still initialize visible {group} coverage; got {active_groups:?}"
            );
        }
        assert!(
            active_high_impingement >= MIN_ACTIVE_HIGH_IMPINGEMENT_EFFECTS,
            "accepted allowed set must retain high-impingement anchors"
        );
        assert!(
            active_dramatic_variation >= MIN_ACTIVE_DRAMATIC_VARIATION_EFFECTS,
            "accepted allowed set must retain dramatic-variation anchors"
        );
        assert!(
            active_punctuation >= MIN_ACTIVE_PUNCTUATION_EFFECTS,
            "accepted allowed set must retain punctuation anchors"
        );
    }

    #[test]
    fn configured_allowed_set_falls_back_when_too_thin_or_too_quiet() {
        assert!(
            configured_shader_indices_from_raw("blend,crossfade,chroma_key,luma_key,breathing")
                .is_none(),
            "five legal nodes are not enough if they cannot provide visible anchor coverage"
        );
        assert!(
            configured_shader_indices_from_raw("drift,warp,mirror,kaleidoscope,fisheye").is_none(),
            "a narrow spatial-only set is route-ineligible for the composed-surface drift path"
        );
    }

    #[test]
    fn shader_caps_do_not_discard_assertive_breathing_ranges() {
        let source = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../../agents/shaders/nodes/breathing.wgsl"),
        )
        .expect("read breathing shader");

        assert!(
            source.contains("clamp(global.u_rate, 0.05, 0.75)"),
            "breathing shader must accept the full scheduled rate range"
        );
        assert!(
            source.contains("clamp(global.u_amplitude, 0.0, 0.026)"),
            "breathing shader must not silently cap the assertive amplitude range"
        );
    }

    #[test]
    fn autonomous_drift_pool_never_uses_solid_as_a_slot() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-no-solid-{}.json",
            std::process::id()
        ));
        let engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        assert!(
            engine
                .slots
                .iter()
                .all(|slot| SHADERS[slot.shader_idx].name != "solid"),
            "solid is a fallback shader, not a recruited drift slot"
        );

        let plan = std::fs::read_to_string(&path).expect("effect drift plan should be written");
        assert!(
            !plan.contains("\"node_id\": \"solid\""),
            "autonomous drift plan must not spend the fifth slot on a no-op solid pass"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn autonomous_drift_plan_is_effect_slots_plus_bookends() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-shape-{}.json",
            std::process::id()
        ));
        let _engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        let plan: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&path).expect("read plan"))
                .expect("effect drift plan should be valid JSON");
        let passes = plan["targets"]["main"]["passes"]
            .as_array()
            .expect("v2 plan should expose main passes");
        let node_ids: Vec<&str> = passes
            .iter()
            .map(|pass| {
                pass["node_id"]
                    .as_str()
                    .expect("each pass should carry node_id")
            })
            .collect();

        assert!(
            passes.len() >= POOL_SIZE + 2,
            "SlotDrift owns five effect slots plus feedback/postprocess bookends; slots may expand into generated source-bound chains"
        );
        assert_eq!(
            &node_ids[node_ids.len() - 2..],
            &["fb", "post"],
            "feedback and postprocess are required bookends after the rotating slots"
        );
        for content_node in ["content_layer", "sierpinski_content", "sierpinski_lines"] {
            assert!(
                !node_ids.contains(&content_node),
                "{content_node} is scene/content infrastructure, not a SlotDrift effect slot"
            );
        }

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn autonomous_drift_refills_under_target_without_waiting_for_stagger() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        engine.tick_count = TICK_DIVISOR - 1;
        engine.last_activation = 999.0;
        engine.next_stagger = 999.0;
        for slot in engine.slots.iter_mut().take(2) {
            slot.phase = Phase::Idle;
            slot.intensity = 0.0;
        }

        engine.tick(1000.0, 1.0 / 30.0);
        let active = engine
            .slots
            .iter()
            .filter(|slot| slot.phase != Phase::Idle)
            .count();

        assert!(
            active >= ACTIVE_SLOT_TARGET,
            "drift must refill below-target active slots immediately"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn autonomous_drift_has_only_one_retiring_slot_at_a_time() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-one-retiring-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for slot in engine
            .slots
            .iter_mut()
            .filter(|slot| slot.phase != Phase::Idle)
        {
            slot.phase = Phase::Peak;
            slot.phase_start = 0.0;
            slot.phase_duration = 1.0;
            slot.intensity = slot.peak_intensity;
            slot.needs_recycle = false;
        }

        engine.tick_count = TICK_DIVISOR - 1;
        engine.tick(2.0, 1.0 / 30.0);

        let falling = engine
            .slots
            .iter()
            .filter(|slot| slot.phase == Phase::Falling)
            .count();
        let peak = engine
            .slots
            .iter()
            .filter(|slot| slot.phase == Phase::Peak)
            .count();

        assert_eq!(
            falling, 1,
            "only one effect should rotate out at a time; synchronized retirement creates visible quiet valleys"
        );
        assert!(
            peak >= ACTIVE_SLOT_TARGET - 1,
            "non-retiring active effects should hold their visible peak while another slot rotates"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn overdue_support_effect_gets_next_rotation_without_second_falling_slot() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-overdue-support-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for (slot, shader_name) in
            engine
                .slots
                .iter_mut()
                .take(4)
                .zip(["pixsort", "edge_detect", "color_map", "echo"])
        {
            slot.shader_idx = shader_idx_by_name(shader_name).unwrap();
            slot.phase = Phase::Peak;
            slot.phase_start = 0.0;
            slot.phase_duration = 1.0;
            slot.intensity = slot.peak_intensity;
            slot.needs_recycle = false;
        }

        engine.tick_count = TICK_DIVISOR - 1;
        engine.tick(2.0, 1.0 / 30.0);

        let falling: Vec<&str> = engine
            .slots
            .iter()
            .filter(|slot| slot.phase == Phase::Falling)
            .map(|slot| SHADERS[slot.shader_idx].name)
            .collect();

        assert_eq!(
            falling,
            vec!["echo"],
            "overdue support effects should not hang behind anchor churn, but the one-falling-slot rule must still hold"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn recycle_restores_high_impingement_when_active_set_is_quiet() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-high-impingement-recycle-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for (slot, shader_name) in
            engine
                .slots
                .iter_mut()
                .take(4)
                .zip(["posterize", "scanlines", "kuwahara", "trail"])
        {
            slot.shader_idx = shader_idx_by_name(shader_name).unwrap();
            slot.phase = Phase::Peak;
            slot.needs_recycle = false;
        }
        engine.slots[4].shader_idx = shader_idx_by_name("blend").unwrap();
        engine.slots[4].phase = Phase::Falling;
        engine.slots[4].needs_recycle = true;

        engine.recycle_slot(4);

        assert!(
            is_high_impingement_anchor(&SHADERS[engine.slots[4].shader_idx]),
            "recycling must restore a high-impingement anchor when the active set is otherwise quiet"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn recycle_preserves_three_high_impingement_anchor_floor() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-high-floor-recycle-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for (slot, shader_name) in
            engine
                .slots
                .iter_mut()
                .take(4)
                .zip(["glitch_block", "grain_bump", "color_map", "diff"])
        {
            slot.shader_idx = shader_idx_by_name(shader_name).unwrap();
            slot.phase = Phase::Peak;
            slot.needs_recycle = false;
        }
        engine.slots[4].shader_idx = shader_idx_by_name("kuwahara").unwrap();
        engine.slots[4].phase = Phase::Falling;
        engine.slots[4].needs_recycle = true;
        engine.allowed_shader_indices = Some(
            [
                "glitch_block",
                "grain_bump",
                "color_map",
                "diff",
                "kuwahara",
                "pixsort",
            ]
            .iter()
            .map(|name| shader_idx_by_name(name).unwrap())
            .collect(),
        );

        engine.recycle_slot(4);

        assert_eq!(
            SHADERS[engine.slots[4].shader_idx].name, "pixsort",
            "when the active set has only two high-impingement anchors, recycling must choose a third anchor over quieter visible support"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn recycle_preserves_dramatic_variation_floor_not_only_tonal_activity() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-dramatic-floor-recycle-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for (slot, shader_name) in engine.slots.iter_mut().take(4).zip([
            "glitch_block",
            "color_map",
            "thermal",
            "kuwahara",
        ]) {
            slot.shader_idx = shader_idx_by_name(shader_name).unwrap();
            slot.phase = Phase::Peak;
            slot.needs_recycle = false;
        }
        engine.slots[4].shader_idx = shader_idx_by_name("blend").unwrap();
        engine.slots[4].phase = Phase::Falling;
        engine.slots[4].needs_recycle = true;
        engine.allowed_shader_indices = Some(
            [
                "glitch_block",
                "color_map",
                "thermal",
                "kuwahara",
                "blend",
                "posterize",
                "palette_remap",
            ]
            .iter()
            .map(|name| shader_idx_by_name(name).unwrap())
            .collect(),
        );

        engine.recycle_slot(4);

        assert!(
            is_dramatic_variation_anchor(&SHADERS[engine.slots[4].shader_idx]),
            "recycling must preserve the dramatic-variation floor instead of selecting a quieter tonal/support node"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn recycle_restores_missing_visible_group_even_when_recently_used() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-missing-group-recycle-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);
        for slot in &mut engine.slots {
            slot.chain = None;
        }

        for (slot, shader_name) in engine.slots.iter_mut().take(4).zip([
            "glitch_block",
            "halftone",
            "color_map",
            "thermal",
        ]) {
            slot.shader_idx = shader_idx_by_name(shader_name).unwrap();
            slot.phase = Phase::Peak;
            slot.needs_recycle = false;
        }
        engine.slots[4].shader_idx = shader_idx_by_name("kuwahara").unwrap();
        engine.slots[4].phase = Phase::Falling;
        engine.slots[4].needs_recycle = true;
        engine.recently_used = [
            "trail",
            "echo",
            "diff",
            "stutter",
            "fluid_sim",
            "reaction_diffusion",
        ]
        .iter()
        .map(|name| shader_idx_by_name(name).unwrap())
        .collect();

        engine.recycle_slot(4);

        assert_eq!(
            visibility_group(&SHADERS[engine.slots[4].shader_idx]),
            "temporal",
            "visible-group repair must outrank recency so the live surface cannot rotate into a legal but non-temporal stack"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn recycle_prefers_undercovered_candidates_after_invariants_hold() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-novelty-debt-recycle-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for (slot, shader_name) in engine.slots.iter_mut().take(4).zip([
            "glitch_block",
            "halftone",
            "color_map",
            "fluid_sim",
        ]) {
            slot.shader_idx = shader_idx_by_name(shader_name).unwrap();
            slot.phase = Phase::Peak;
            slot.needs_recycle = false;
            slot.chain = None;
        }
        engine.slots[4].shader_idx = shader_idx_by_name("kuwahara").unwrap();
        engine.slots[4].phase = Phase::Falling;
        engine.slots[4].needs_recycle = true;
        engine.slots[4].chain = None;

        let pixsort = shader_idx_by_name("pixsort").unwrap();
        let thermal = shader_idx_by_name("thermal").unwrap();
        let posterize = shader_idx_by_name("posterize").unwrap();
        engine.allowed_shader_indices = Some(
            [
                "glitch_block",
                "halftone",
                "color_map",
                "fluid_sim",
                "kuwahara",
                "pixsort",
                "thermal",
                "posterize",
            ]
            .iter()
            .map(|name| shader_idx_by_name(name).unwrap())
            .collect(),
        );
        engine.selection_counts[thermal] = 40;
        engine.selection_counts[posterize] = 40;
        engine.selection_counts[pixsort] = 0;
        engine.coverage_events.clear();
        for idx in [thermal, posterize].into_iter().cycle().take(60) {
            engine.record_selection(idx, "single-node".to_string(), Vec::new());
        }
        engine.selection_counts[thermal] = 40;
        engine.selection_counts[posterize] = 40;
        engine.selection_counts[pixsort] = 0;

        engine.recycle_slot(4);

        assert_eq!(
            engine.slots[4].shader_idx, pixsort,
            "once hard live-surface invariants are satisfied, recycling should pay coverage debt instead of randomly reusing over-covered families"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn recycle_avoids_primary_already_present_inside_active_chain() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-chain-primary-overlap-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);
        for slot in &mut engine.slots {
            slot.chain = None;
            slot.phase = Phase::Peak;
            slot.needs_recycle = false;
        }

        for (slot, shader_name) in engine.slots.iter_mut().take(4).zip([
            "scanlines",
            "glitch_block",
            "color_map",
            "fluid_sim",
        ]) {
            slot.shader_idx = shader_idx_by_name(shader_name).unwrap();
        }
        engine.slots[0].chain = Some(generated_chain_for_test(
            "scanlines",
            vec!["scanlines", "pixsort", "vhs"],
        ));
        engine.slots[4].shader_idx = shader_idx_by_name("kuwahara").unwrap();
        engine.slots[4].phase = Phase::Falling;
        engine.slots[4].needs_recycle = true;
        engine.allowed_shader_indices = Some(
            [
                "scanlines",
                "glitch_block",
                "color_map",
                "fluid_sim",
                "kuwahara",
                "pixsort",
                "thermal",
            ]
            .iter()
            .map(|name| shader_idx_by_name(name).unwrap())
            .collect(),
        );

        let thermal = shader_idx_by_name("thermal").unwrap();
        engine.selection_counts[thermal] = 80;
        engine.coverage_events.clear();
        for _ in 0..80 {
            engine.record_selection(thermal, "single-node".to_string(), Vec::new());
        }

        engine.recycle_slot(4);

        assert_eq!(
            SHADERS[engine.slots[4].shader_idx].name, "thermal",
            "candidate primaries already present as active chain companions should not be reselected as if they were fresh"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn recycle_can_select_supporting_effects_after_anchor_floor_is_met() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-supporting-recycle-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for (slot, shader_name) in engine.slots.iter_mut().take(4).zip([
            "glitch_block",
            "halftone",
            "color_map",
            "fluid_sim",
        ]) {
            slot.shader_idx = shader_idx_by_name(shader_name).unwrap();
            slot.phase = Phase::Peak;
            slot.needs_recycle = false;
        }
        engine.slots[4].shader_idx = shader_idx_by_name("kuwahara").unwrap();
        engine.slots[4].phase = Phase::Falling;
        engine.slots[4].needs_recycle = true;
        engine.allowed_shader_indices = Some(
            [
                "glitch_block",
                "halftone",
                "color_map",
                "fluid_sim",
                "kuwahara",
                "blend",
            ]
            .iter()
            .map(|name| shader_idx_by_name(name).unwrap())
            .collect(),
        );
        for name in [
            "glitch_block",
            "halftone",
            "color_map",
            "fluid_sim",
            "kuwahara",
        ] {
            let idx = shader_idx_by_name(name).unwrap();
            engine.selection_counts[idx] = 20;
        }

        engine.recycle_slot(4);

        assert_eq!(
            SHADERS[engine.slots[4].shader_idx].name, "blend",
            "supporting effects must get rotation authority once existing active anchors satisfy the surface floor"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn composed_surface_inventory_gets_selection_authority_over_time() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-full-coverage-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);

        for (slot, shader_name) in engine.slots.iter_mut().take(4).zip([
            "glitch_block",
            "halftone",
            "color_map",
            "fluid_sim",
        ]) {
            slot.shader_idx = shader_idx_by_name(shader_name).unwrap();
            slot.phase = Phase::Peak;
            slot.needs_recycle = false;
        }

        let composed_surface_count = SHADERS
            .iter()
            .filter(|def| is_composed_surface_drift_candidate(def))
            .count();
        for iteration in 0..(composed_surface_count * 12) {
            let slot_idx = iteration % POOL_SIZE;
            engine.slots[slot_idx].phase = Phase::Falling;
            engine.slots[slot_idx].needs_recycle = true;
            engine.recycle_slot(slot_idx);
            engine.record_selection_for_slot(slot_idx);
        }

        let never_selected: Vec<&str> = SHADERS
            .iter()
            .enumerate()
            .filter(|(_, def)| is_composed_surface_drift_candidate(def))
            .filter(|(idx, _)| engine.selection_counts[*idx] == 0)
            .map(|(_, def)| def.name)
            .collect();

        assert!(
            never_selected.is_empty(),
            "composed-surface drift must eventually exercise every route-eligible repaired effect; missing {never_selected:?}"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn active_effect_parameters_orbit_safe_range_not_only_fixed_target_corridor() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-param-orbit-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);
        let colorgrade = shader_idx_by_name("colorgrade").unwrap();
        engine.slots[0].shader_idx = colorgrade;
        engine.slots[0].chain = None;
        engine.slots[0].phase = Phase::Peak;
        engine.slots[0].intensity = 1.0;
        engine.slots[0].peak_intensity = 1.0;
        engine.slots[0].active_target = vec![
            ("saturation".to_string(), 1.1),
            ("brightness".to_string(), 1.05),
            ("contrast".to_string(), 1.05),
            ("sepia".to_string(), 0.2),
            ("hue_rotate".to_string(), 0.3),
        ];
        engine.slots[0].current_params = SHADERS[colorgrade]
            .passthrough
            .iter()
            .map(|&(n, v)| (n.to_string(), v))
            .collect();

        let mut saturation_values = Vec::new();
        for step in 0..80 {
            let uniforms = engine.interpolate_all(step as f32 * 12.0);
            let saturation = uniforms
                .iter()
                .find(|(name, _)| name.ends_with("colorgrade.saturation"))
                .map(|(_, value)| *value)
                .expect("colorgrade.saturation uniform present");
            saturation_values.push(saturation);
        }
        let max_value = saturation_values
            .iter()
            .copied()
            .fold(f32::NEG_INFINITY, f32::max);
        let min_value = saturation_values
            .iter()
            .copied()
            .fold(f32::INFINITY, f32::min);
        let spread = max_value - min_value;

        assert!(
            max_value > 1.20 && spread > 0.24,
            "active effects should continuously travel through safe parameter volume instead of staying inside the original passthrough→target corridor; min={min_value}, max={max_value}, spread={spread}"
        );

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn palette_remap_has_bounded_luma_authority_and_free_running_time() {
        let path = std::env::temp_dir().join(format!(
            "hapax-effect-drift-test-plan-palette-carrier-{}.json",
            std::process::id()
        ));
        let mut engine = SlotDriftEngine::new(path.to_str().unwrap(), 42);
        let palette_remap = shader_idx_by_name("palette_remap").unwrap();
        let def = &SHADERS[palette_remap];
        let (_, _, blend_hi) = def
            .active_ranges
            .iter()
            .find(|(name, _, _)| *name == "blend")
            .copied()
            .expect("palette_remap blend range");
        let (_, cycle_lo, cycle_hi) = def
            .active_ranges
            .iter()
            .find(|(name, _, _)| *name == "cycle_rate")
            .copied()
            .expect("palette_remap cycle range");

        assert!(
            blend_hi <= 0.18,
            "palette_remap must not regain enough blend authority to brighten or darken the whole surface"
        );
        assert!(
            cycle_hi <= 0.020 && cycle_lo >= 0.006,
            "palette_remap cycle rate must stay slow enough to read as continuous variation"
        );

        engine.slots[0].shader_idx = palette_remap;
        engine.slots[0].chain = None;
        engine.slots[0].phase = Phase::Peak;
        engine.slots[0].intensity = 1.0;
        engine.slots[0].peak_intensity = 1.0;
        engine.slots[0].active_target = vec![
            ("palette_id".to_string(), 0.0),
            ("cycle_rate".to_string(), 0.018),
            ("n_bands".to_string(), 10.0),
            ("blend".to_string(), 0.16),
            ("time".to_string(), 120.0),
        ];
        engine.slots[0].current_params = def
            .passthrough
            .iter()
            .map(|&(n, v)| (n.to_string(), v))
            .collect();

        for time in [10.0, 37.5, 96.0] {
            let uniforms = engine.interpolate_all(time);
            let observed_time = uniforms
                .iter()
                .find(|(name, _)| name.ends_with("palette_remap.time"))
                .map(|(_, value)| *value)
                .expect("palette_remap.time uniform present");
            assert_eq!(
                observed_time, time,
                "time is a free-running carrier; it must not be randomized or orbited as an effect target"
            );
        }

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn autonomous_drift_library_keeps_all_effect_families_eligible() {
        let families: std::collections::HashSet<&str> =
            SHADERS.iter().map(|def| def.family).collect();
        for family in [
            "tonal",
            "texture",
            "edge",
            "atmospheric",
            "temporal",
            "compositing",
        ] {
            assert!(
                families.contains(family),
                "effect family {family} must remain in the autonomous drift library"
            );
        }
    }

    #[test]
    fn every_autonomous_effect_has_a_live_visibility_axis() {
        let unassigned: Vec<&str> = SHADERS
            .iter()
            .filter(|def| is_autonomous_drift_candidate(def))
            .filter(|def| !EFFECT_VISIBILITY_GROUPS.contains(&visibility_group(def)))
            .map(|def| def.name)
            .collect();

        assert!(
            unassigned.is_empty(),
            "autonomous effects without a visibility axis cannot be routed by the drift engine: {unassigned:?}"
        );
    }

    #[test]
    fn shader_inventory_contains_the_repaired_live_surface_inventory() {
        let names: std::collections::HashSet<&str> = SHADERS.iter().map(|def| def.name).collect();
        for name in [
            "blend",
            "breathing",
            "chroma_key",
            "circular_mask",
            "crossfade",
            "diff",
            "droste",
            "fluid_sim",
            "grain_bump",
            "luma_key",
            "nightvision_tint",
            "noise_gen",
            "particle_system",
            "reaction_diffusion",
            "solid",
            "strobe",
            "syrup",
            "threshold",
            "tile",
            "tunnel",
            "waveform_render",
        ] {
            assert!(
                names.contains(name),
                "repaired live-surface node {name} must remain available in the shader inventory"
            );
        }
    }

    #[test]
    fn shader_inventory_accounts_for_every_effect_node_metadata_file() {
        let shader_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");
        let autonomous: std::collections::HashSet<&str> =
            SHADERS.iter().map(|def| def.name).collect();
        let explicitly_non_autonomous = std::collections::HashSet::from([
            "content_layer",
            "feedback",
            "output",
            "postprocess",
            "sierpinski_content",
            "sierpinski_lines",
        ]);

        for entry in std::fs::read_dir(&shader_root).expect("read shader node directory") {
            let path = entry.expect("shader node entry").path();
            if path.extension().and_then(|ext| ext.to_str()) != Some("json") {
                continue;
            }
            let stem = path
                .file_stem()
                .and_then(|stem| stem.to_str())
                .expect("shader metadata stem");
            assert!(
                autonomous.contains(stem) || explicitly_non_autonomous.contains(stem),
                "{stem} has shader metadata but is neither autonomous nor explicitly classified"
            );
        }
    }

    #[test]
    fn surface_presence_gates_do_not_use_full_frame_alpha() {
        let shader_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");
        for shader in [
            "ascii.wgsl",
            "blend.wgsl",
            "bloom.wgsl",
            "breathing.wgsl",
            "chroma_key.wgsl",
            "circular_mask.wgsl",
            "color_map.wgsl",
            "colorgrade.wgsl",
            "crossfade.wgsl",
            "diff.wgsl",
            "dither.wgsl",
            "emboss.wgsl",
            "droste.wgsl",
            "echo.wgsl",
            "fluid_sim.wgsl",
            "grain_bump.wgsl",
            "halftone.wgsl",
            "invert.wgsl",
            "kuwahara.wgsl",
            "luma_key.wgsl",
            "nightvision_tint.wgsl",
            "noise_gen.wgsl",
            "noise_overlay.wgsl",
            "palette.wgsl",
            "palette_extract.wgsl",
            "palette_remap.wgsl",
            "particle_system.wgsl",
            "pixsort.wgsl",
            "posterize.wgsl",
            "postprocess.wgsl",
            "reaction_diffusion.wgsl",
            "rutt_etra.wgsl",
            "scanlines.wgsl",
            "sharpen.wgsl",
            "slitscan.wgsl",
            "solid.wgsl",
            "strobe.wgsl",
            "stutter.wgsl",
            "syrup.wgsl",
            "thermal.wgsl",
            "threshold.wgsl",
            "tile.wgsl",
            "tunnel.wgsl",
            "vhs.wgsl",
            "vignette.wgsl",
            "voronoi_overlay.wgsl",
            "waveform_render.wgsl",
        ] {
            let source = std::fs::read_to_string(shader_root.join(shader))
                .unwrap_or_else(|err| panic!("read {shader}: {err}"));
            assert!(
                source.contains("surface_presence")
                    || source.contains("surfacePresence")
                    || source.contains("head_surface_presence"),
                "{shader} must gate source-bound effect pressure by existing scene energy"
            );
            assert!(
                !source.contains("smoothstep(0.004"),
                "{shader} must not use alpha as a source-presence proxy; post-FX full-frame \
                 alpha turns empty space into a paintable fourth-wall surface"
            );
            assert!(
                !source.contains("smoothstep(0.008"),
                "{shader} uses the old permissive source gate; faint background/grid energy \
                 can become a fourth-wall pane"
            );
        }
    }

    #[test]
    fn pane_forming_shaders_require_assertive_luma_gates() {
        let shader_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");
        for shader in [
            "color_map.wgsl",
            "colorgrade.wgsl",
            "dither.wgsl",
            "invert.wgsl",
            "halftone.wgsl",
            "kuwahara.wgsl",
            "noise_gen.wgsl",
            "noise_overlay.wgsl",
            "palette.wgsl",
            "palette_extract.wgsl",
            "palette_remap.wgsl",
            "posterize.wgsl",
            "postprocess.wgsl",
            "scanlines.wgsl",
            "thermal.wgsl",
            "vignette.wgsl",
            "voronoi_overlay.wgsl",
        ] {
            let source = std::fs::read_to_string(shader_root.join(shader))
                .unwrap_or_else(|err| panic!("read {shader}: {err}"));
            assert!(
                source.contains("smoothstep(0.025")
                    || source.contains("smoothstep(0.035")
                    || source.contains("smoothstep(0.04")
                    || source.contains("smoothstep(0.045")
                    || source.contains("smoothstep(0.055")
                    || source.contains("smoothstep(0.07"),
                "{shader} must require substantial scene luminance before applying \
                 screen-space texture/color pressure"
            );
            assert!(
                !source.contains("smoothstep(0.008"),
                "{shader} uses the old permissive source gate; faint background/grid energy \
                 can become a fourth-wall pane"
            );
        }
    }

    #[test]
    fn reprojection_effects_do_not_clone_the_livestream_scene() {
        let shader_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");
        let mirror =
            std::fs::read_to_string(shader_root.join("mirror.wgsl")).expect("read mirror shader");
        let tile =
            std::fs::read_to_string(shader_root.join("tile.wgsl")).expect("read tile shader");

        assert!(
            mirror.contains("fold_glint") && mirror.contains("detail_lift"),
            "mirror must be a bounded fold/detail operator, not a second scene projection"
        );
        assert!(
            !mirror.contains("mix(original.xyz, mirrored.xyz"),
            "mirror must not directly blend a full mirrored frame over the livestream surface"
        );
        assert!(
            tile.contains("detail_lift") && tile.contains("cell_edge"),
            "tile must extract bounded detail/cell energy, not reproject tiled copies"
        );
        assert!(
            !tile.contains("mix(source.xyz, tiled_bound"),
            "tile must not blend a cloned tiled frame over the livestream surface"
        );

        for shader in [
            "displacement_map.wgsl",
            "droste.wgsl",
            "fisheye.wgsl",
            "kaleidoscope.wgsl",
            "transform.wgsl",
            "tunnel.wgsl",
            "warp.wgsl",
        ] {
            let source = std::fs::read_to_string(shader_root.join(shader))
                .unwrap_or_else(|err| panic!("read {shader}: {err}"));
            assert!(
                source.contains("detail_lift") && source.contains("max("),
                "{shader} must lift bounded detail from warped samples instead of replacing the source"
            );
            for banned in [
                "mix(original.xyz, warped.xyz",
                "mix(original.xyz, transformed.xyz",
                "mix(source.xyz, warped.xyz",
                "mix(source.xyz, tunnel.xyz",
            ] {
                assert!(
                    !source.contains(banned),
                    "{shader} must not directly blend a full warped scene via {banned}"
                );
            }
        }
    }

    #[test]
    fn feedback_shader_has_true_passthrough_guard() {
        let source = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../../agents/shaders/nodes/feedback.wgsl"),
        )
        .expect("read feedback shader");

        assert!(
            source.contains("global.u_decay <= 0.0001") && source.contains("fragColor = current"),
            "feedback zero state must return the current frame, not blend with accumulation"
        );
        assert!(
            source.contains("current.a") && !source.contains("_e215.z, 1f"),
            "feedback must preserve current alpha; forcing alpha=1 turns empty space into a fourth-wall surface"
        );
        assert!(
            source.contains("feedback_weight") && source.contains("mix(current.xyz, r"),
            "feedback must be bounded as source-bound entity treatment, not a screen/add glass pane"
        );
    }

    #[test]
    fn content_bookend_shaders_preserve_input_alpha() {
        let shader_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");
        for shader in [
            "content_layer.wgsl",
            "sierpinski_content.wgsl",
            "sierpinski_lines.wgsl",
        ] {
            let source = std::fs::read_to_string(shader_root.join(shader))
                .unwrap_or_else(|err| panic!("read {shader}: {err}"));
            assert!(
                source.contains("base_sample.a"),
                "{shader} must pass through input alpha instead of creating a full-frame pane"
            );
            assert!(
                !source.contains("fragColor = vec4<f32>(result, 1.0)")
                    && !source.contains("fragColor = vec4<f32>(base, 1.0)"),
                "{shader} must not force alpha=1 on the full output"
            );
        }
    }

    #[test]
    fn slitscan_shader_has_true_passthrough_guard() {
        let source = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../../agents/shaders/nodes/slitscan.wgsl"),
        )
        .expect("read slitscan shader");

        assert!(
            source.contains("global.u_speed <= 0.0001") && source.contains("fragColor = current"),
            "slitscan speed-zero state must return the current frame, not the accumulator"
        );
    }

    #[test]
    fn slitscan_temporal_state_does_not_replace_live_surface() {
        let source = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../../agents/shaders/nodes/slitscan.wgsl"),
        )
        .expect("read slitscan shader");

        assert!(
            source.contains("surface_presence")
                && source.contains("temporal_strength")
                && source.contains("mix(current, temporal"),
            "slitscan must blend temporal history into live content instead of freezing the surface"
        );
        assert!(
            !source.contains("fragColor = textureSample(tex_accum"),
            "slitscan must not replace most pixels with the temporal accumulator"
        );
    }

    #[test]
    fn temporal_and_palette_nodes_do_not_create_foreground_panes_or_freezes() {
        let shader_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");
        let stutter =
            std::fs::read_to_string(shader_root.join("stutter.wgsl")).expect("read stutter shader");
        let palette_extract = std::fs::read_to_string(shader_root.join("palette_extract.wgsl"))
            .expect("read palette_extract shader");
        let rutt_etra = std::fs::read_to_string(shader_root.join("rutt_etra.wgsl"))
            .expect("read rutt_etra shader");

        assert!(
            stutter.contains("surface_presence")
                && stutter.contains("base_strength")
                && !stutter.contains("fragColor = held")
                && !stutter.contains("fragColor = held_slip"),
            "stutter must keep a live-current floor instead of freezing to tex_accum"
        );
        assert!(
            palette_extract.contains("no viewport banner")
                && palette_extract.contains("surface_presence")
                && !palette_extract.contains("if (_e21 > _e22)")
                && !palette_extract.contains("fragColor = vec4<f32>(_e63"),
            "palette_extract must not paint an autonomous top-of-frame swatch strip"
        );
        assert!(
            rutt_etra.contains("line_strength")
                && rutt_etra.contains("mix(color.xyz")
                && !rutt_etra.contains("result = (_e73.xyz * _e75)")
                && !rutt_etra.contains("result = vec3((_e77 * _e78))"),
            "rutt_etra must blend line displacement over source instead of blacking non-line rows"
        );
    }

    #[test]
    fn dormant_effect_nodes_keep_source_bound_floor() {
        let shader_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");
        let ascii =
            std::fs::read_to_string(shader_root.join("ascii.wgsl")).expect("read ascii shader");
        let glitch = std::fs::read_to_string(shader_root.join("glitch_block.wgsl"))
            .expect("read glitch_block shader");
        let trail =
            std::fs::read_to_string(shader_root.join("trail.wgsl")).expect("read trail shader");
        let echo =
            std::fs::read_to_string(shader_root.join("echo.wgsl")).expect("read echo shader");
        let vhs = std::fs::read_to_string(shader_root.join("vhs.wgsl")).expect("read vhs shader");

        assert!(
            ascii.contains("sourceColor")
                && ascii.contains("glyph_signal")
                && ascii.contains("surface_presence")
                && !ascii.contains("bgColor"),
            "ascii must blend glyph pressure over source instead of replacing the frame with a terminal pane"
        );
        assert!(
            glitch.contains("var source")
                && glitch.contains("mix(source, glitch_signal")
                && !glitch.contains("fragColor = vec4<f32>(_e268"),
            "glitch_block must keep a source floor, including generated pattern branches"
        );
        assert!(
            trail.contains("temporal_strength")
                && trail.contains("mix(cur.xyz")
                && echo.contains("echo_strength")
                && echo.contains("mix(cur.xyz"),
            "temporal trail/echo nodes must blend history into current content"
        );
        assert!(
            vhs.contains("head_switch_y = clamp(global.u_head_switch_y")
                && !vhs.contains("uv.y > 0.93f"),
            "vhs head-switch disturbance must use the drifted parameter, not a hardcoded viewport band"
        );
        assert!(
            vhs.contains("sourceAlpha = _e54.w")
                && vhs.contains("_e131.z, sourceAlpha")
                && !vhs.contains("_e131.z, 1f"),
            "vhs must preserve source alpha; forcing alpha=1 lets postprocess paint the fourth wall"
        );
    }

    #[test]
    fn thermal_shader_blends_instead_of_snapping_full_frame() {
        let source = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../../agents/shaders/nodes/thermal.wgsl"),
        )
        .expect("read thermal shader");

        assert!(
            source.contains("thermal_strength")
                && source.contains("mix(source_color.xyz")
                && !source.contains("global.u_edge_glow < -0.5f"),
            "thermal must blend from source color instead of threshold-snapping the full frame"
        );
    }

    #[test]
    fn quantizing_shaders_blend_instead_of_replacing_full_frame() {
        for shader in ["dither.wgsl", "halftone.wgsl", "posterize.wgsl"] {
            let source = std::fs::read_to_string(
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../../../agents/shaders/nodes")
                    .join(shader),
            )
            .unwrap_or_else(|err| panic!("read {shader}: {err}"));

            assert!(
                source.contains("mix("),
                "{shader} must blend its stylization with the source surface"
            );
            assert!(
                source.contains("strength") || source.contains("_strength"),
                "{shader} must derive a bounded effect strength"
            );
            assert!(
                source.contains("surface_presence"),
                "{shader} must gate quantization by source presence so it cannot paint the empty field"
            );
        }
    }

    #[test]
    fn fourth_wall_sensitive_shaders_do_not_paint_empty_field() {
        for shader in [
            "color_map.wgsl",
            "colorgrade.wgsl",
            "kuwahara.wgsl",
            "noise_overlay.wgsl",
            "palette.wgsl",
            "postprocess.wgsl",
            "thermal.wgsl",
            "voronoi_overlay.wgsl",
        ] {
            let source = std::fs::read_to_string(
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../../../agents/shaders/nodes")
                    .join(shader),
            )
            .unwrap_or_else(|err| panic!("read {shader}: {err}"));

            assert!(
                source.contains("surface_presence"),
                "{shader} must gate screen-space generated pressure by existing scene energy"
            );
        }
    }

    #[test]
    fn repaired_live_surface_shaders_are_source_bound() {
        for shader in [
            "blend.wgsl",
            "bloom.wgsl",
            "breathing.wgsl",
            "chroma_key.wgsl",
            "circular_mask.wgsl",
            "crossfade.wgsl",
            "diff.wgsl",
            "droste.wgsl",
            "emboss.wgsl",
            "fluid_sim.wgsl",
            "invert.wgsl",
            "luma_key.wgsl",
            "nightvision_tint.wgsl",
            "noise_gen.wgsl",
            "pixsort.wgsl",
            "particle_system.wgsl",
            "reaction_diffusion.wgsl",
            "sharpen.wgsl",
            "solid.wgsl",
            "strobe.wgsl",
            "syrup.wgsl",
            "threshold.wgsl",
            "tile.wgsl",
            "tunnel.wgsl",
            "vignette.wgsl",
            "waveform_render.wgsl",
        ] {
            let source = std::fs::read_to_string(
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../../../agents/shaders/nodes")
                    .join(shader),
            )
            .unwrap_or_else(|err| panic!("read {shader}: {err}"));

            assert!(
                source.contains("surface_presence") || source.contains("surfacePresence"),
                "{shader} must gate effect pressure by existing scene energy"
            );
            assert!(
                source.contains("mix(")
                    || source.contains("base.xyz +")
                    || source.contains("c.xyz +")
                    || source.contains("source.xyz +"),
                "{shader} must preserve a source floor instead of replacing the surface"
            );
        }
    }

    #[test]
    fn palette_remap_is_content_gated_not_viewport_pane() {
        let source = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../../agents/shaders/nodes/palette_remap.wgsl"),
        )
        .expect("read palette_remap shader");

        assert!(
            source.contains("surface_presence") && source.contains("effective_blend"),
            "palette remap must gate recoloring by existing scene/content energy"
        );
        assert!(
            !source.contains("time_offset = floor") && source.contains("idx_mix = smoothstep"),
            "palette remap cycle must be continuous, not a frame-wide stepped palette pump"
        );
        assert!(
            !source.contains("floor((_e33.x * _e35))")
                && !source.contains("floor((v_texcoord_1.x *"),
            "palette remap must not create vertical viewport-column panes"
        );
    }

    #[test]
    fn vhs_dropout_does_not_paint_empty_space_bars() {
        let source = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes/vhs.wgsl"),
        )
        .expect("read vhs shader");

        assert!(
            source.contains("surfacePresence")
                && source.contains("dropStrength = 0.16f * surfacePresence")
                && !source.contains("mix(_e455.xyz, vec3(1f), vec3(0.8f))"),
            "vhs dropout must be bounded and content-gated, not full-width white bars"
        );
    }

    #[test]
    fn darkening_prone_shaders_preserve_source_luma_floor() {
        let shader_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");

        for shader in [
            "nightvision_tint.wgsl",
            "reaction_diffusion.wgsl",
            "threshold.wgsl",
            "vhs.wgsl",
        ] {
            let source = std::fs::read_to_string(shader_root.join(shader))
                .unwrap_or_else(|err| panic!("read {shader}: {err}"));

            assert!(
                source.contains("luma_deficit"),
                "{shader} must lift output back to a source luminance floor instead of dimming the scene"
            );
        }
    }

    #[test]
    fn alpha_preservation_nodes_do_not_create_fourth_wall_surfaces() {
        let shader_root =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../agents/shaders/nodes");
        let pixsort =
            std::fs::read_to_string(shader_root.join("pixsort.wgsl")).expect("read pixsort shader");
        let feedback = std::fs::read_to_string(shader_root.join("feedback.wgsl"))
            .expect("read feedback shader");

        assert!(
            pixsort.contains("orig.a") && !pixsort.contains(", 1f)"),
            "pixsort must preserve source alpha; sorted pixels cannot declare the empty field present"
        );
        assert!(
            feedback.contains("_e215.z, current.a") && !feedback.contains("_e215.z, 1f"),
            "feedback must preserve source alpha after temporal blending"
        );
    }
}

// ── Lifecycle ──────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Phase {
    Idle,
    Rising,
    Peak,
    Falling,
}

#[derive(Debug, Clone)]
pub struct SlotState {
    pub shader_idx: usize,
    chain: Option<GeneratedChain>,
    pub phase: Phase,
    pub intensity: f32,
    pub phase_start: f32,
    pub phase_duration: f32,
    pub peak_intensity: f32,
    pub idle_since: f32,
    pub needs_recycle: bool,
    pub rerise_after: f32,
    pub active_target: Vec<(String, f32)>,
    pub current_params: Vec<(String, f32)>,
}

#[derive(Debug, Clone)]
struct CoverageEvent {
    shader_idx: usize,
    chain_id: String,
    parameter_regions: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct SlotRuntimeMetadata {
    pub slot_index: usize,
    pub node_id: String,
    pub slot_phase: &'static str,
    pub slot_intensity: f64,
    pub selection_count: u32,
    pub coverage_window_count: u64,
    pub parameter_regions: Vec<serde_json::Value>,
}

#[derive(Debug, Clone)]
struct SlotPlanNode {
    shader_idx: usize,
    node_id: String,
    chain_node_index: usize,
    preset_chain_id: String,
    chain_lineage: String,
    structural_signature: String,
    topology_signature: String,
    graph_motif: String,
    param_seed: u64,
}

// ── Simple RNG ─────────────────────────────────────────────────

struct SimpleRng(u64);
impl SimpleRng {
    fn new(seed: u64) -> Self {
        Self(seed)
    }
    fn next_u64(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        self.0
    }
    fn next_f32(&mut self) -> f32 {
        self.next_u64();
        ((self.0 >> 33) as f32) / (u32::MAX as f32)
    }
    fn range(&mut self, lo: f32, hi: f32) -> f32 {
        lo + self.next_f32() * (hi - lo)
    }
    fn gauss(&mut self) -> f32 {
        // Box-Muller
        let u1 = self.next_f32().max(1e-10);
        let u2 = self.next_f32();
        (-2.0 * u1.ln()).sqrt() * (2.0 * std::f32::consts::TAU * u2).cos()
    }
}

fn pass_inputs_for(def: &ShaderDef, prev_output: &str) -> (Vec<String>, bool) {
    pass_inputs_for_node(def, def.name, prev_output)
}

fn pass_inputs_for_node(def: &ShaderDef, node_id: &str, prev_output: &str) -> (Vec<String>, bool) {
    if matches!(
        def.name,
        "slitscan"
            | "trail"
            | "echo"
            | "stutter"
            | "diff"
            | "fluid_sim"
            | "reaction_diffusion"
            | "blend"
            | "chroma_key"
            | "crossfade"
            | "luma_key"
    ) {
        return (
            vec![prev_output.to_string(), format!("@accum_{}", node_id)],
            true,
        );
    }
    if def.name == "displacement_map" {
        // The displacement shader consumes a second texture as its map.
        // In autonomous drift mode, reuse the current surface as that map
        // so the bind-group contract stays valid without adding an
        // unrelated source.
        return (
            vec![prev_output.to_string(), prev_output.to_string()],
            false,
        );
    }
    (vec![prev_output.to_string()], false)
}

fn chain_seed_candidates_for_shader(shader_idx: usize) -> Vec<usize> {
    let anchor = SHADERS[shader_idx].name;
    CHAIN_SEEDS
        .iter()
        .enumerate()
        .filter(|(_, seed)| {
            seed.anchor == anchor
                || seed
                    .nodes
                    .iter()
                    .any(|node_name| *node_name == anchor && seed.anchor != "colorgrade")
        })
        .map(|(idx, _)| idx)
        .collect()
}

fn choose_chain_seed_from_candidates(rng: &mut SimpleRng, candidates: &[usize]) -> Option<usize> {
    if candidates.is_empty() {
        return None;
    }
    let idx = (rng.next_f32() * candidates.len() as f32) as usize % candidates.len();
    Some(candidates[idx])
}

fn push_unique_node(nodes: &mut Vec<&'static str>, node_name: &'static str) {
    if !nodes.contains(&node_name) {
        nodes.push(node_name);
    }
}

fn chain_family_count(nodes: &[&'static str], family: &str) -> usize {
    nodes
        .iter()
        .filter_map(|node_name| shader_idx_by_name(node_name))
        .filter(|node_idx| SHADERS[*node_idx].family == family)
        .count()
}

fn chain_family_limit(family: &str) -> usize {
    match family {
        // Tonal nodes are useful as companions, but serial tonal stacks read
        // as whole-frame luma pumping rather than material variation.
        "tonal" => 1,
        // Compositing and temporal nodes are high-risk support layers in the
        // flattened composed-surface route.
        "compositing" => 1,
        "temporal" => 2,
        _ => 3,
    }
}

fn can_add_chain_node(nodes: &[&'static str], node_name: &'static str) -> bool {
    let Some(node_idx) = shader_idx_by_name(node_name) else {
        return false;
    };
    let family = SHADERS[node_idx].family;
    chain_family_count(nodes, family) < chain_family_limit(family)
}

fn push_unique_chain_node(nodes: &mut Vec<&'static str>, node_name: &'static str) {
    if !nodes.contains(&node_name) && can_add_chain_node(nodes, node_name) {
        nodes.push(node_name);
    }
}

fn seed_nodes_for_shader(shader_idx: usize, seed: &ChainSeed) -> Vec<&'static str> {
    let anchor = SHADERS[shader_idx].name;
    let mut seeded_nodes = vec![anchor];
    for node_name in seed.nodes {
        if shader_idx_by_name(node_name)
            .map(|idx| is_composed_surface_drift_candidate(&SHADERS[idx]))
            .unwrap_or(false)
        {
            push_unique_chain_node(&mut seeded_nodes, node_name);
        }
    }
    seeded_nodes
}

fn active_node_overlap(nodes: &[&'static str], active_node_names: &[&'static str]) -> usize {
    nodes
        .iter()
        .filter(|node_name| active_node_names.contains(node_name))
        .count()
}

fn low_overlap_seed_candidates(
    seed_candidates: &[usize],
    active_structural_signatures: &[String],
    active_node_names: &[&'static str],
    anchor_idx: usize,
    require_structural_freshness: bool,
) -> Vec<usize> {
    let anchor = SHADERS[anchor_idx].name;
    let scored: Vec<(usize, usize)> = seed_candidates
        .iter()
        .copied()
        .filter_map(|seed_idx| {
            let seed = &CHAIN_SEEDS[seed_idx];
            let seeded_nodes = seed_nodes_for_shader(anchor_idx, seed);
            let structural_signature = chain_structural_signature(anchor, &seeded_nodes);
            if require_structural_freshness
                && active_structural_signatures.contains(&structural_signature)
            {
                return None;
            }
            Some((
                seed_idx,
                active_node_overlap(&seeded_nodes, active_node_names),
            ))
        })
        .collect();

    let Some(min_overlap) = scored.iter().map(|(_, overlap)| *overlap).min() else {
        return Vec::new();
    };
    scored
        .into_iter()
        .filter(|(_, overlap)| *overlap == min_overlap)
        .map(|(seed_idx, _)| seed_idx)
        .collect()
}

fn chain_companion_candidates(
    anchor_idx: usize,
    nodes: &[&'static str],
    active_node_names: &[&'static str],
) -> Vec<usize> {
    let anchor_family = SHADERS[anchor_idx].family;
    let candidates: Vec<usize> = SHADERS
        .iter()
        .enumerate()
        .filter(|(idx, def)| {
            *idx != anchor_idx
                && is_composed_surface_drift_candidate(def)
                && !nodes.contains(&def.name)
                && can_add_chain_node(nodes, def.name)
        })
        .filter(|(_, def)| {
            def.family != anchor_family
                || nodes
                    .iter()
                    .filter_map(|node_name| shader_idx_by_name(node_name))
                    .filter(|node_idx| SHADERS[*node_idx].family == anchor_family)
                    .count()
                    < 2
        })
        .map(|(idx, _)| idx)
        .collect();

    let fresh: Vec<usize> = candidates
        .iter()
        .copied()
        .filter(|idx| !active_node_names.contains(&SHADERS[*idx].name))
        .collect();
    if fresh.len() >= MIN_GENERATED_CHAIN_NODES.saturating_sub(nodes.len()).max(1) {
        fresh
    } else {
        candidates
    }
}

fn chain_structural_signature(anchor: &str, nodes: &[&'static str]) -> String {
    let mut canonical_nodes = nodes.to_vec();
    canonical_nodes.sort_unstable();
    format!("rng:{}:{}", anchor, canonical_nodes.join("+"))
}

fn synthesize_chain_once(
    rng: &mut SimpleRng,
    shader_idx: usize,
    active_structural_signatures: &[String],
    active_node_names: &[&'static str],
) -> GeneratedChain {
    let anchor = SHADERS[shader_idx].name;
    let seed_candidates = chain_seed_candidates_for_shader(shader_idx);
    let fresh_seed_candidates = low_overlap_seed_candidates(
        &seed_candidates,
        active_structural_signatures,
        active_node_names,
        shader_idx,
        true,
    );
    let low_overlap_seed_candidates = low_overlap_seed_candidates(
        &seed_candidates,
        active_structural_signatures,
        active_node_names,
        shader_idx,
        false,
    );
    let seed_idx = if !fresh_seed_candidates.is_empty() {
        choose_chain_seed_from_candidates(rng, &fresh_seed_candidates)
    } else if !low_overlap_seed_candidates.is_empty() {
        choose_chain_seed_from_candidates(rng, &low_overlap_seed_candidates)
    } else {
        choose_chain_seed_from_candidates(rng, &seed_candidates)
    };

    let mut nodes = Vec::new();
    push_unique_node(&mut nodes, anchor);
    if let Some(seed_idx) = seed_idx {
        let seed = &CHAIN_SEEDS[seed_idx];
        let mut seed_order: Vec<usize> = (0..seed.nodes.len()).collect();
        shuffle_indices(rng, &mut seed_order);
        for seed_node_idx in seed_order {
            if nodes.len() >= MAX_GENERATED_CHAIN_NODES {
                break;
            }
            let node_name = seed.nodes[seed_node_idx];
            if shader_idx_by_name(node_name)
                .map(|idx| !is_composed_surface_drift_candidate(&SHADERS[idx]))
                .unwrap_or(true)
            {
                continue;
            }
            if rng.next_f32() < 0.72 || nodes.len() < MIN_GENERATED_CHAIN_NODES {
                push_unique_chain_node(&mut nodes, node_name);
            }
        }
    }

    while nodes.len() < MIN_GENERATED_CHAIN_NODES {
        let candidates = chain_companion_candidates(shader_idx, &nodes, active_node_names);
        if candidates.is_empty() {
            break;
        }
        let candidate_idx = (rng.next_f32() * candidates.len() as f32) as usize % candidates.len();
        push_unique_chain_node(&mut nodes, SHADERS[candidates[candidate_idx]].name);
    }

    if nodes.len() < MAX_GENERATED_CHAIN_NODES && rng.next_f32() < 0.68 {
        let candidates = chain_companion_candidates(shader_idx, &nodes, active_node_names);
        if !candidates.is_empty() {
            let candidate_idx =
                (rng.next_f32() * candidates.len() as f32) as usize % candidates.len();
            push_unique_chain_node(&mut nodes, SHADERS[candidates[candidate_idx]].name);
        }
    }

    let param_seed = rng.next_u64();
    let seed_label = seed_idx
        .and_then(|idx| CHAIN_SEEDS.get(idx))
        .map(|seed| seed.id)
        .unwrap_or("freeform");
    let lineage = seed_idx
        .and_then(|idx| CHAIN_SEEDS.get(idx))
        .map(|seed| format!("rng-constrained:{}", seed.lineage))
        .unwrap_or_else(|| format!("rng-constrained:{}", SHADERS[shader_idx].family));
    let node_signature = nodes.join(":");
    let structural_signature = chain_structural_signature(anchor, &nodes);
    let variant = param_seed % 9973;
    let topology_signature = format!("rng:{}:{}:v{}", anchor, node_signature, variant);
    let id = format!(
        "rng-chain:{}:{}:{:04x}",
        anchor,
        seed_label,
        param_seed & 0xffff
    );

    GeneratedChain {
        id,
        lineage,
        structural_signature,
        topology_signature,
        anchor,
        nodes,
        param_seed,
    }
}

fn synthesize_chain_for_shader_avoiding(
    rng: &mut SimpleRng,
    shader_idx: usize,
    active_structural_signatures: &[String],
    active_node_names: &[&'static str],
) -> GeneratedChain {
    let mut fallback = synthesize_chain_once(
        rng,
        shader_idx,
        active_structural_signatures,
        active_node_names,
    );
    for _ in 0..8 {
        if !active_structural_signatures.contains(&fallback.structural_signature) {
            return fallback;
        }
        fallback = synthesize_chain_once(
            rng,
            shader_idx,
            active_structural_signatures,
            active_node_names,
        );
    }
    fallback
}

fn shader_can_generate_fresh_chain(
    shader_idx: usize,
    active_structural_signatures: &[String],
) -> bool {
    if chain_seed_candidates_for_shader(shader_idx).is_empty() {
        return true;
    }
    let anchor = SHADERS[shader_idx].name;
    let seed_signatures: Vec<String> = chain_seed_candidates_for_shader(shader_idx)
        .iter()
        .filter_map(|idx| CHAIN_SEEDS.get(*idx))
        .map(|seed| {
            let seeded_nodes = seed_nodes_for_shader(shader_idx, seed);
            chain_structural_signature(anchor, &seeded_nodes)
        })
        .collect();
    seed_signatures.is_empty()
        || seed_signatures
            .iter()
            .any(|signature| !active_structural_signatures.contains(signature))
}

fn slot_chain_id(slot: &SlotState) -> String {
    if let Some(chain) = &slot.chain {
        chain.id.clone()
    } else {
        "single-node".to_string()
    }
}

fn slot_plan_nodes(slot_index: usize, slot: &SlotState) -> Vec<SlotPlanNode> {
    let mut nodes = Vec::new();
    if let Some(chain) = &slot.chain {
        for (chain_node_index, node_name) in chain.nodes.iter().enumerate() {
            if let Some(shader_idx) = shader_idx_by_name(node_name) {
                let def = &SHADERS[shader_idx];
                if !is_composed_surface_drift_candidate(def) {
                    continue;
                }
                nodes.push(SlotPlanNode {
                    shader_idx,
                    node_id: format!("slot{}_{}_{}", slot_index, chain_node_index, def.name),
                    chain_node_index,
                    preset_chain_id: chain.id.clone(),
                    chain_lineage: chain.lineage.clone(),
                    structural_signature: chain.structural_signature.clone(),
                    topology_signature: chain.topology_signature.clone(),
                    graph_motif: chain.anchor.to_string(),
                    param_seed: chain
                        .param_seed
                        .wrapping_add((chain_node_index as u64).wrapping_mul(7919)),
                });
            }
        }
    }

    if nodes.is_empty() || !nodes.iter().any(|node| node.shader_idx == slot.shader_idx) {
        let def = &SHADERS[slot.shader_idx];
        if is_composed_surface_drift_candidate(def) {
            nodes.insert(
                0,
                SlotPlanNode {
                    shader_idx: slot.shader_idx,
                    node_id: format!("slot{}_0_{}", slot_index, def.name),
                    chain_node_index: 0,
                    preset_chain_id: "single-node".to_string(),
                    chain_lineage: def.family.to_string(),
                    structural_signature: def.name.to_string(),
                    topology_signature: def.name.to_string(),
                    graph_motif: def.name.to_string(),
                    param_seed: ((slot_index as u64) << 32) ^ (slot.shader_idx as u64),
                },
            );
        }
    }

    nodes
}

fn random_peak_intensity(rng: &mut SimpleRng, def: &ShaderDef) -> f32 {
    let (lo, hi) = if def.is_spatial {
        SPATIAL_PEAK_RANGE
    } else {
        NONSPATIAL_PEAK_RANGE
    };
    rng.range(lo, hi)
}

fn target_departure_fraction(def: &ShaderDef) -> f32 {
    if is_punctuation_anchor(def) {
        0.68
    } else if is_fast_evict(def) {
        0.60
    } else if def.is_spatial {
        0.50
    } else {
        ASSERTIVE_TARGET_DEPARTURE_FRACTION
    }
}

fn assertive_target_value(
    rng: &mut SimpleRng,
    def: &ShaderDef,
    param_name: &str,
    passthrough: f32,
    lo: f32,
    hi: f32,
) -> f32 {
    if (hi - lo).abs() <= f32::EPSILON {
        return lo;
    }

    let raw = rng.range(lo, hi);
    let range = hi - lo;
    let min_delta = range * target_departure_fraction(def);
    let value = if (raw - passthrough).abs() >= min_delta {
        raw
    } else {
        let lower = (passthrough - min_delta).clamp(lo, hi);
        let upper = (passthrough + min_delta).clamp(lo, hi);
        let lower_delta = (lower - passthrough).abs();
        let upper_delta = (upper - passthrough).abs();

        if lower_delta >= min_delta && upper_delta >= min_delta {
            if rng.next_f32() < 0.5 {
                lower
            } else {
                upper
            }
        } else if lower_delta >= min_delta {
            lower
        } else if upper_delta >= min_delta {
            upper
        } else if lower_delta > upper_delta {
            lower
        } else {
            upper
        }
    };

    let value = bias_assertive_target_region(def, param_name, value, lo, hi);

    if param_name == "brightness" {
        value.max(1.0).clamp(lo, hi)
    } else {
        value
    }
}

fn deterministic_assertive_target_value(
    def: &ShaderDef,
    param_name: &str,
    passthrough: f32,
    lo: f32,
    hi: f32,
    seed: usize,
) -> f32 {
    if (hi - lo).abs() <= f32::EPSILON {
        return lo;
    }

    let fractions = [0.14, 0.32, 0.58, 0.78, 0.92];
    let raw = lo + (hi - lo) * fractions[seed % fractions.len()];
    let range = hi - lo;
    let min_delta = range * target_departure_fraction(def);
    let value = if (raw - passthrough).abs() >= min_delta {
        raw
    } else if raw >= passthrough {
        (passthrough + min_delta).clamp(lo, hi)
    } else {
        (passthrough - min_delta).clamp(lo, hi)
    };

    let value = bias_assertive_target_region(def, param_name, value, lo, hi);

    if param_name == "brightness" {
        value.max(1.0).clamp(lo, hi)
    } else {
        value
    }
}

fn motif_node_target(
    slot: &SlotState,
    slot_index: usize,
    plan_node: &SlotPlanNode,
) -> Vec<(String, f32)> {
    if plan_node.shader_idx == slot.shader_idx {
        return slot.active_target.clone();
    }

    let def = &SHADERS[plan_node.shader_idx];
    def.active_ranges
        .iter()
        .enumerate()
        .map(|(param_index, &(name, lo, hi))| {
            let passthrough = def
                .passthrough
                .iter()
                .find(|(candidate, _)| *candidate == name)
                .map(|(_, value)| *value)
                .unwrap_or(lo);
            let seed = slot_index * 37
                + slot.shader_idx * 19
                + plan_node.shader_idx * 13
                + plan_node.chain_node_index * 7
                + param_index * 5
                + (plan_node.param_seed as usize);
            (
                name.to_string(),
                deterministic_assertive_target_value(def, name, passthrough, lo, hi, seed),
            )
        })
        .collect()
}

fn interpolated_param_value(
    def: &ShaderDef,
    slot_index: usize,
    node_index: usize,
    shader_idx: usize,
    param_index: usize,
    param_name: &str,
    passthrough: f32,
    active_value: f32,
    intensity: f32,
    now: f32,
) -> f32 {
    let span = (active_value - passthrough).abs();
    let mut interpolated = passthrough + (active_value - passthrough) * intensity;

    if intensity > 0.05 && span > 0.001 {
        let (lo, hi) = active_range_for(def, param_name)
            .unwrap_or((passthrough.min(active_value), passthrough.max(active_value)));
        let active_span = (hi - lo).abs();
        let regime_depth = parameter_regime_depth(def, param_name);
        if regime_depth > 0.0 && active_span > 0.0 {
            let regime =
                held_parameter_regime(def, slot_index, node_index, shader_idx, param_index, now);
            interpolated += regime * regime_depth * active_span * intensity;
        }
        let lo = if param_name == "brightness" {
            lo.max(1.0)
        } else {
            lo
        };
        if let Some(min_norm) = assertive_min_normalized(def, param_name) {
            let min_value = lo + (hi - lo) * min_norm;
            let runtime_floor = passthrough + (min_value - passthrough) * intensity;
            if runtime_floor > passthrough {
                interpolated = interpolated.max(runtime_floor);
            }
        }
        interpolated = interpolated.clamp(lo, hi);
    }

    interpolated
}

const COMPOSED_SURFACE_BASELINE_GROUPS: &[&str] = &["texture", "tonal", "temporal"];
const EFFECT_VISIBILITY_GROUPS: &[&str] = &["spatial", "texture", "tonal", "temporal"];

fn shuffle_indices(rng: &mut SimpleRng, indices: &mut [usize]) {
    for i in (1..indices.len()).rev() {
        let j = (rng.next_f32() * (i + 1) as f32) as usize % (i + 1);
        indices.swap(i, j);
    }
}

fn visibility_group(def: &ShaderDef) -> &'static str {
    match def.name {
        "trail" | "echo" | "stutter" | "diff" | "slitscan" | "fluid_sim" | "reaction_diffusion"
        | "pixsort" | "blend" | "chroma_key" | "crossfade" | "luma_key" => "temporal",
        "bloom" | "color_map" | "colorgrade" | "invert" | "palette" | "palette_extract"
        | "palette_remap" | "posterize" | "syrup" | "thermal" | "vignette" | "nightvision_tint" => {
            "tonal"
        }
        "ascii"
        | "vhs"
        | "glitch_block"
        | "edge_detect"
        | "emboss"
        | "grain_bump"
        | "kuwahara"
        | "rutt_etra"
        | "scanlines"
        | "dither"
        | "halftone"
        | "noise_gen"
        | "noise_overlay"
        | "particle_system"
        | "sharpen"
        | "strobe"
        | "threshold"
        | "voronoi_overlay"
        | "waveform_render"
        | "chromatic_aberration" => "texture",
        "circular_mask" => "spatial",
        _ if def.is_spatial => "spatial",
        _ => "secondary",
    }
}

fn effect_aliases(def: &ShaderDef) -> &'static [&'static str] {
    match def.name {
        // "Vortex" is an operator-facing dramatic-effect identity, not a
        // single historical shader name. Keep the behavior discoverable
        // without cloning another effect node.
        "fluid_sim" | "tunnel" | "droste" | "kaleidoscope" => &["vortex"],
        "chromatic_aberration" | "glitch_block" => &["rgba_separation"],
        "warp" | "slitscan" => &["slicing"],
        "mirror" => &["reflection"],
        _ => &[],
    }
}

fn phase_label(phase: Phase) -> &'static str {
    match phase {
        Phase::Idle => "idle",
        Phase::Rising => "rising",
        Phase::Peak => "peak",
        Phase::Falling => "falling",
    }
}

fn active_range_for(def: &ShaderDef, param_name: &str) -> Option<(f32, f32)> {
    def.active_ranges
        .iter()
        .find(|(name, _, _)| *name == param_name)
        .map(|(_, lo, hi)| (*lo, *hi))
}

fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9E3779B97F4A7C15);
    let mut mixed = value;
    mixed = (mixed ^ (mixed >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    mixed = (mixed ^ (mixed >> 27)).wrapping_mul(0x94D049BB133111EB);
    mixed ^ (mixed >> 31)
}

fn unit_hash(seed: u64) -> f32 {
    ((splitmix64(seed) >> 40) as f32) / 16_777_215.0
}

fn smoothstep01(value: f32) -> f32 {
    let t = value.clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

fn parameter_regime_seed(
    slot_index: usize,
    node_index: usize,
    shader_idx: usize,
    param_index: usize,
) -> u64 {
    0xD1B54A32D192ED03u64
        ^ (slot_index as u64).wrapping_mul(0x9E3779B185EBCA87)
        ^ (node_index as u64).wrapping_mul(0xC2B2AE3D27D4EB4F)
        ^ (shader_idx as u64).wrapping_mul(0x165667B19E3779F9)
        ^ (param_index as u64).wrapping_mul(0x85EBCA77C2B2AE63)
}

fn parameter_regime_hold_seconds(seed: u64) -> f32 {
    PARAM_REGIME_MIN_HOLD_S
        + unit_hash(seed ^ 0xA24BAED4963EE407) * (PARAM_REGIME_MAX_HOLD_S - PARAM_REGIME_MIN_HOLD_S)
}

fn parameter_regime_phase_offset(seed: u64, hold_seconds: f32) -> f32 {
    unit_hash(seed ^ 0x9FB21C651E98DF25) * hold_seconds
}

fn regime_level(def: &ShaderDef, seed: u64, bucket: u64) -> f32 {
    let u = unit_hash(seed ^ bucket.wrapping_mul(0xD6E8FEB86659FD93));
    if is_punctuation_anchor(def) {
        match u {
            x if x < 0.14 => -0.78,
            x if x < 0.30 => -0.28,
            x if x < 0.54 => 0.38,
            x if x < 0.80 => 0.78,
            _ => 1.0,
        }
    } else {
        match u {
            x if x < 0.18 => -0.82,
            x if x < 0.38 => -0.42,
            x if x < 0.62 => 0.0,
            x if x < 0.82 => 0.46,
            _ => 0.84,
        }
    }
}

fn held_parameter_regime(
    def: &ShaderDef,
    slot_index: usize,
    node_index: usize,
    shader_idx: usize,
    param_index: usize,
    now: f32,
) -> f32 {
    let seed = parameter_regime_seed(slot_index, node_index, shader_idx, param_index);
    let hold_seconds = parameter_regime_hold_seconds(seed);
    let shifted = (now.max(0.0) + parameter_regime_phase_offset(seed, hold_seconds)) / hold_seconds;
    let bucket = shifted.floor().max(0.0) as u64;
    let local = shifted - bucket as f32;
    let current = regime_level(def, seed, bucket);
    if local >= PARAM_REGIME_CROSSFADE_FRACTION || bucket == 0 {
        return current;
    }

    let previous = regime_level(def, seed, bucket - 1);
    let t = smoothstep01(local / PARAM_REGIME_CROSSFADE_FRACTION);
    previous + (current - previous) * t
}

fn parameter_regime_depth(def: &ShaderDef, param_name: &str) -> f32 {
    match param_name {
        // Brightness reads as global pumping when its safe range is traversed
        // broadly. Let structural and source-gated parameters carry variety.
        "brightness" | "time" => 0.0,
        "alpha" | "opacity" | "color_a" => {
            if is_punctuation_anchor(def) {
                0.10
            } else {
                0.0
            }
        }
        "strength" | "intensity" | "blend" => {
            if is_punctuation_anchor(def) {
                0.20
            } else if def.is_spatial {
                0.14
            } else if is_fast_evict(def) {
                0.18
            } else {
                0.14
            }
        }
        _ if def.is_spatial => 0.22,
        _ if is_punctuation_anchor(def) => 0.30,
        _ if is_fast_evict(def) => 0.34,
        _ => 0.26,
    }
}

fn assertive_min_normalized(def: &ShaderDef, param_name: &str) -> Option<f32> {
    if !is_punctuation_anchor(def) {
        return None;
    }

    match param_name {
        "active" | "amount" | "alpha" | "blend" | "chroma_shift" | "color_a" | "dot_size"
        | "edge_glow" | "intensity" | "opacity" | "rgb_split" | "sort_length" | "speed"
        | "strength" | "thickness" | "vorticity" => Some(0.62),
        "scale" => Some(0.54),
        _ => None,
    }
}

fn bias_assertive_target_region(
    def: &ShaderDef,
    param_name: &str,
    value: f32,
    lo: f32,
    hi: f32,
) -> f32 {
    let Some(min_norm) = assertive_min_normalized(def, param_name) else {
        return value;
    };
    if (hi - lo).abs() <= f32::EPSILON {
        return value;
    }
    let min_value = lo + (hi - lo) * min_norm;
    value.max(min_value).clamp(lo, hi)
}

fn parameter_region(def: &ShaderDef, param_name: &str, value: f32) -> &'static str {
    let Some((lo, hi)) = active_range_for(def, param_name) else {
        return "unranged";
    };
    if (hi - lo).abs() <= f32::EPSILON {
        return "fixed";
    }
    let normalized = ((value - lo) / (hi - lo)).clamp(0.0, 1.0);
    if normalized < 0.33 {
        "low"
    } else if normalized < 0.66 {
        "mid"
    } else {
        "high"
    }
}

fn parameter_region_labels(def: &ShaderDef, target: &[(String, f32)]) -> Vec<String> {
    target
        .iter()
        .map(|(name, value)| {
            format!(
                "{}.{}:{}",
                def.name,
                name,
                parameter_region(def, name, *value)
            )
        })
        .collect()
}

fn parameter_regions_json(def: &ShaderDef, target: &[(String, f32)]) -> Vec<serde_json::Value> {
    target
        .iter()
        .map(|(name, value)| {
            serde_json::json!({
                "param": name,
                "region": parameter_region(def, name, *value),
                "target": *value as f64,
            })
        })
        .collect()
}

fn label_counts_json(labels: Vec<String>) -> Vec<serde_json::Value> {
    let mut counts: Vec<(String, usize)> = Vec::new();
    for label in labels {
        if let Some((_, count)) = counts.iter_mut().find(|(candidate, _)| *candidate == label) {
            *count += 1;
        } else {
            counts.push((label, 1));
        }
    }
    counts.sort_by(|a, b| a.0.cmp(&b.0));
    counts
        .into_iter()
        .map(|(label, count)| serde_json::json!({ "label": label, "count": count }))
        .collect()
}

fn is_conditionally_low_salience(def: &ShaderDef) -> bool {
    matches!(
        def.name,
        // These effects can be valuable in a chain, but their visible force
        // depends on motion, history, line placement, or scene coincidence.
        // They should not be allowed to satisfy the active-slot invariant by
        // themselves.
        "blend"
            | "breathing"
            | "chroma_key"
            | "crossfade"
            | "diff"
            | "echo"
            | "luma_key"
            | "rutt_etra"
            | "stutter"
            | "trail"
    )
}

fn is_visible_anchor(def: &ShaderDef) -> bool {
    is_baseline_visible(def) && !is_conditionally_low_salience(def)
}

fn is_high_impingement_anchor(def: &ShaderDef) -> bool {
    matches!(
        def.name,
        // Bounded, source-gated treatments that still read immediately.
        // Multiple anchors must be active so group coverage cannot collapse
        // into a legal but visually quiet chain.
        "ascii"
            | "chromatic_aberration"
            | "color_map"
            | "displacement_map"
            | "dither"
            | "drift"
            | "edge_detect"
            | "fisheye"
            | "glitch_block"
            | "halftone"
            | "kaleidoscope"
            | "mirror"
            | "nightvision_tint"
            | "noise_gen"
            | "palette_remap"
            | "pixsort"
            | "particle_system"
            | "posterize"
            | "rutt_etra"
            | "scanlines"
            | "slitscan"
            | "fluid_sim"
            | "strobe"
            | "thermal"
            | "threshold"
            | "transform"
            | "tunnel"
            | "vhs"
            | "warp"
            | "waveform_render"
    )
}

fn is_dramatic_variation_anchor(def: &ShaderDef) -> bool {
    matches!(
        def.name,
        "ascii"
            | "chromatic_aberration"
            | "dither"
            | "diff"
            | "edge_detect"
            | "fluid_sim"
            | "glitch_block"
            | "grain_bump"
            | "halftone"
            | "noise_gen"
            | "particle_system"
            | "pixsort"
            | "posterize"
            | "reaction_diffusion"
            | "rutt_etra"
            | "scanlines"
            | "strobe"
            | "thermal"
            | "threshold"
            | "vhs"
            | "waveform_render"
    )
}

fn is_punctuation_anchor(def: &ShaderDef) -> bool {
    matches!(
        def.name,
        // These are composed-surface effects that visibly change the scene's
        // identity at 1080p. They are allowed to be short-dwell and assertive;
        // quieter texture helpers cannot satisfy this floor by themselves.
        "ascii"
            | "chromatic_aberration"
            | "color_map"
            | "dither"
            | "edge_detect"
            | "fluid_sim"
            | "glitch_block"
            | "halftone"
            | "noise_gen"
            | "particle_system"
            | "pixsort"
            | "posterize"
            | "strobe"
            | "thermal"
            | "threshold"
            | "vhs"
            | "waveform_render"
    )
}

fn is_baseline_visible(def: &ShaderDef) -> bool {
    matches!(
        def.name,
        "bloom"
            | "colorgrade"
            | "drift"
            | "invert"
            | "vignette"
            | "chromatic_aberration"
            | "displacement_map"
            | "fisheye"
            | "kaleidoscope"
            | "mirror"
            | "warp"
            | "droste"
            | "tile"
            | "transform"
            | "tunnel"
            | "breathing"
            | "ascii"
            | "vhs"
            | "glitch_block"
            | "edge_detect"
            | "emboss"
            | "rutt_etra"
            | "scanlines"
            | "dither"
            | "grain_bump"
            | "halftone"
            | "kuwahara"
            | "noise_gen"
            | "noise_overlay"
            | "particle_system"
            | "sharpen"
            | "strobe"
            | "threshold"
            | "voronoi_overlay"
            | "waveform_render"
            | "color_map"
            | "palette"
            | "palette_extract"
            | "thermal"
            | "nightvision_tint"
            | "palette_remap"
            | "posterize"
            | "syrup"
            | "pixsort"
            | "blend"
            | "chroma_key"
            | "circular_mask"
            | "crossfade"
            | "trail"
            | "echo"
            | "diff"
            | "luma_key"
            | "slitscan"
            | "stutter"
            | "fluid_sim"
            | "reaction_diffusion"
    )
}

fn is_autonomous_drift_candidate(def: &ShaderDef) -> bool {
    // `solid` is a useful shader-level fallback and test fixture, but it is
    // not an effect authority. If autonomous drift recruits it, the fifth
    // slot becomes a permanent no-op and the surface reads like fewer than
    // four active treatments even when telemetry says otherwise.
    def.name != "solid"
}

fn requires_entity_local_route(def: &ShaderDef) -> bool {
    def.is_spatial
}

fn is_composed_surface_drift_candidate(def: &ShaderDef) -> bool {
    is_autonomous_drift_candidate(def) && !requires_entity_local_route(def)
}

fn effect_coverage_role(def: &ShaderDef) -> &'static str {
    if !is_autonomous_drift_candidate(def) {
        "non_autonomous"
    } else if requires_entity_local_route(def) {
        "blocked_pending_entity_local_route"
    } else if is_conditionally_low_salience(def) {
        "supporting_conditional"
    } else if is_high_impingement_anchor(def) {
        "high_impingement_anchor"
    } else if is_visible_anchor(def) {
        "visible_anchor"
    } else {
        "supporting_effect"
    }
}

fn effect_route_authority(def: &ShaderDef) -> &'static str {
    if !is_autonomous_drift_candidate(def) {
        "non_autonomous"
    } else if requires_entity_local_route(def) {
        "entity_local_route_required"
    } else {
        "composed_surface_drift"
    }
}

fn effect_application_plane(def: &ShaderDef) -> &'static str {
    if def.is_spatial {
        "entity_field_spatial_reprojection"
    } else if matches!(def.family, "temporal" | "compositing") {
        "entity_field_temporal_treatment"
    } else {
        "entity_field_surface_treatment"
    }
}

fn shader_idx_by_name(name: &str) -> Option<usize> {
    SHADERS.iter().position(|def| def.name == name)
}

fn drift_pool_invariant_failures(indices: &[usize]) -> Vec<String> {
    let mut failures = Vec::new();
    if indices.len() < POOL_SIZE {
        failures.push(format!(
            "has {} valid node(s), need at least {}",
            indices.len(),
            POOL_SIZE
        ));
    }

    let visible_anchor_count = indices
        .iter()
        .filter(|idx| is_visible_anchor(&SHADERS[**idx]))
        .count();
    if visible_anchor_count < MIN_ACTIVE_ANCHOR_EFFECTS {
        failures.push(format!(
            "has {} visible anchor(s), need at least {}",
            visible_anchor_count, MIN_ACTIVE_ANCHOR_EFFECTS
        ));
    }

    let high_impingement_count = indices
        .iter()
        .filter(|idx| is_high_impingement_anchor(&SHADERS[**idx]))
        .count();
    if high_impingement_count < MIN_ACTIVE_HIGH_IMPINGEMENT_EFFECTS {
        failures.push(format!(
            "has {} high-impingement anchor(s), need at least {}",
            high_impingement_count, MIN_ACTIVE_HIGH_IMPINGEMENT_EFFECTS
        ));
    }

    let dramatic_variation_count = indices
        .iter()
        .filter(|idx| is_dramatic_variation_anchor(&SHADERS[**idx]))
        .count();
    if dramatic_variation_count < MIN_ACTIVE_DRAMATIC_VARIATION_EFFECTS {
        failures.push(format!(
            "has {} dramatic-variation anchor(s), need at least {}",
            dramatic_variation_count, MIN_ACTIVE_DRAMATIC_VARIATION_EFFECTS
        ));
    }

    let punctuation_count = indices
        .iter()
        .filter(|idx| is_punctuation_anchor(&SHADERS[**idx]))
        .count();
    if punctuation_count < MIN_ACTIVE_PUNCTUATION_EFFECTS {
        failures.push(format!(
            "has {} punctuation anchor(s), need at least {}",
            punctuation_count, MIN_ACTIVE_PUNCTUATION_EFFECTS
        ));
    }

    let missing_groups: Vec<&str> = COMPOSED_SURFACE_BASELINE_GROUPS
        .iter()
        .copied()
        .filter(|group| {
            !indices.iter().any(|idx| {
                let def = &SHADERS[*idx];
                is_visible_anchor(def) && visibility_group(def) == *group
            })
        })
        .collect();
    if !missing_groups.is_empty() {
        failures.push(format!(
            "missing visible anchor coverage for group(s): {:?}",
            missing_groups
        ));
    }

    failures
}

fn configured_shader_indices_from_raw(raw: &str) -> Option<Vec<usize>> {
    let mut indices = Vec::new();
    let mut unknown = Vec::new();
    let mut non_autonomous = Vec::new();
    let mut route_ineligible = Vec::new();

    for name in raw
        .split(',')
        .map(str::trim)
        .filter(|name| !name.is_empty())
    {
        match shader_idx_by_name(name) {
            Some(idx) if !is_autonomous_drift_candidate(&SHADERS[idx]) => {
                non_autonomous.push(name.to_string())
            }
            Some(idx) if !is_composed_surface_drift_candidate(&SHADERS[idx]) => {
                route_ineligible.push(name.to_string())
            }
            Some(idx) if !indices.contains(&idx) => indices.push(idx),
            Some(_) => {}
            None => unknown.push(name.to_string()),
        }
    }

    if !unknown.is_empty() {
        log::warn!(
            "SlotDrift: ignoring unknown HAPAX_EFFECT_DRIFT_ALLOWED_SET node(s): {:?}",
            unknown
        );
    }
    if !non_autonomous.is_empty() {
        log::warn!(
            "SlotDrift: ignoring non-autonomous HAPAX_EFFECT_DRIFT_ALLOWED_SET node(s): {:?}",
            non_autonomous
        );
    }
    if !route_ineligible.is_empty() {
        log::warn!(
            "SlotDrift: ignoring route-ineligible HAPAX_EFFECT_DRIFT_ALLOWED_SET node(s): {:?}",
            route_ineligible
        );
    }
    let failures = drift_pool_invariant_failures(&indices);
    if !failures.is_empty() {
        log::warn!(
            "SlotDrift: HAPAX_EFFECT_DRIFT_ALLOWED_SET cannot satisfy live-surface drift invariants ({:?}); using full library",
            failures
        );
        return None;
    }

    log::info!(
        "SlotDrift: constrained to {} sampled node(s): {:?}",
        indices.len(),
        indices
            .iter()
            .map(|idx| SHADERS[*idx].name)
            .collect::<Vec<&str>>()
    );
    Some(indices)
}

fn configured_shader_indices_from_env() -> Option<Vec<usize>> {
    let raw = std::env::var("HAPAX_EFFECT_DRIFT_ALLOWED_SET").ok()?;
    configured_shader_indices_from_raw(&raw)
}

fn choose_initial_pool(rng: &mut SimpleRng, selectable: &[usize]) -> Vec<usize> {
    let mut shuffled: Vec<usize> = selectable
        .iter()
        .copied()
        .filter(|idx| is_composed_surface_drift_candidate(&SHADERS[*idx]))
        .collect();
    shuffle_indices(rng, &mut shuffled);

    let mut selected = Vec::new();
    for &group in COMPOSED_SURFACE_BASELINE_GROUPS {
        if let Some(idx) = shuffled.iter().copied().find(|idx| {
            !selected.contains(idx)
                && is_visible_anchor(&SHADERS[*idx])
                && is_high_impingement_anchor(&SHADERS[*idx])
                && visibility_group(&SHADERS[*idx]) == group
        }) {
            selected.push(idx);
        } else if let Some(idx) = shuffled.iter().copied().find(|idx| {
            !selected.contains(idx)
                && is_visible_anchor(&SHADERS[*idx])
                && visibility_group(&SHADERS[*idx]) == group
        }) {
            selected.push(idx);
        } else if let Some(idx) = shuffled.iter().copied().find(|idx| {
            !selected.contains(idx)
                && is_baseline_visible(&SHADERS[*idx])
                && visibility_group(&SHADERS[*idx]) == group
        }) {
            selected.push(idx);
        }
    }

    for idx in shuffled.iter().copied() {
        if selected
            .iter()
            .take(ACTIVE_SLOT_TARGET)
            .filter(|idx| is_visible_anchor(&SHADERS[**idx]))
            .count()
            >= MIN_ACTIVE_ANCHOR_EFFECTS
        {
            break;
        }
        if !selected.contains(&idx) && is_visible_anchor(&SHADERS[idx]) {
            selected.push(idx);
        }
    }

    for idx in shuffled.iter().copied() {
        if selected
            .iter()
            .take(ACTIVE_SLOT_TARGET)
            .filter(|idx| is_high_impingement_anchor(&SHADERS[**idx]))
            .count()
            >= MIN_ACTIVE_HIGH_IMPINGEMENT_EFFECTS
        {
            break;
        }
        if !selected.contains(&idx) && is_high_impingement_anchor(&SHADERS[idx]) {
            selected.push(idx);
        }
    }
    if selected
        .iter()
        .take(ACTIVE_SLOT_TARGET)
        .filter(|idx| is_high_impingement_anchor(&SHADERS[**idx]))
        .count()
        < MIN_ACTIVE_HIGH_IMPINGEMENT_EFFECTS
    {
        let replacement = shuffled
            .iter()
            .copied()
            .filter(|idx| !selected.contains(idx) && is_high_impingement_anchor(&SHADERS[*idx]))
            .find_map(|idx| {
                selected
                    .iter()
                    .take(ACTIVE_SLOT_TARGET)
                    .position(|selected_idx| {
                        !is_high_impingement_anchor(&SHADERS[*selected_idx])
                            && visibility_group(&SHADERS[*selected_idx])
                                == visibility_group(&SHADERS[idx])
                    })
                    .map(|pos| (pos, idx))
            });
        if let Some((pos, idx)) = replacement {
            selected[pos] = idx;
        }
    }

    for idx in shuffled.iter().copied() {
        if selected
            .iter()
            .take(ACTIVE_SLOT_TARGET)
            .filter(|idx| is_dramatic_variation_anchor(&SHADERS[**idx]))
            .count()
            >= MIN_ACTIVE_DRAMATIC_VARIATION_EFFECTS
        {
            break;
        }
        if !selected.contains(&idx) && is_dramatic_variation_anchor(&SHADERS[idx]) {
            selected.push(idx);
        }
    }
    if selected
        .iter()
        .take(ACTIVE_SLOT_TARGET)
        .filter(|idx| is_dramatic_variation_anchor(&SHADERS[**idx]))
        .count()
        < MIN_ACTIVE_DRAMATIC_VARIATION_EFFECTS
    {
        let replacement = shuffled
            .iter()
            .copied()
            .filter(|idx| !selected.contains(idx) && is_dramatic_variation_anchor(&SHADERS[*idx]))
            .find_map(|idx| {
                selected
                    .iter()
                    .take(ACTIVE_SLOT_TARGET)
                    .position(|selected_idx| {
                        !is_dramatic_variation_anchor(&SHADERS[*selected_idx])
                            && visibility_group(&SHADERS[*selected_idx])
                                == visibility_group(&SHADERS[idx])
                    })
                    .map(|pos| (pos, idx))
            });
        if let Some((pos, idx)) = replacement {
            selected[pos] = idx;
        }
    }

    for idx in shuffled.iter().copied() {
        if selected
            .iter()
            .take(ACTIVE_SLOT_TARGET)
            .filter(|idx| is_punctuation_anchor(&SHADERS[**idx]))
            .count()
            >= MIN_ACTIVE_PUNCTUATION_EFFECTS
        {
            break;
        }
        if !selected.contains(&idx) && is_punctuation_anchor(&SHADERS[idx]) {
            selected.push(idx);
        }
    }
    if selected
        .iter()
        .take(ACTIVE_SLOT_TARGET)
        .filter(|idx| is_punctuation_anchor(&SHADERS[**idx]))
        .count()
        < MIN_ACTIVE_PUNCTUATION_EFFECTS
    {
        let replacement = shuffled
            .iter()
            .copied()
            .filter(|idx| !selected.contains(idx) && is_punctuation_anchor(&SHADERS[*idx]))
            .find_map(|idx| {
                selected
                    .iter()
                    .take(ACTIVE_SLOT_TARGET)
                    .position(|selected_idx| !is_punctuation_anchor(&SHADERS[*selected_idx]))
                    .map(|pos| (pos, idx))
            });
        if let Some((pos, idx)) = replacement {
            selected[pos] = idx;
        }
    }

    for idx in shuffled {
        if selected.len() >= POOL_SIZE {
            break;
        }
        if !selected.contains(&idx) {
            selected.push(idx);
        }
    }

    selected.truncate(POOL_SIZE);
    selected
}

// ── Engine ─────────────────────────────────────────────────────

pub struct SlotDriftEngine {
    slots: Vec<SlotState>,
    rng: SimpleRng,
    tick_count: u64,
    last_activation: f32,
    next_stagger: f32,
    recently_used: VecDeque<usize>,
    selection_counts: Vec<u32>,
    coverage_events: VecDeque<CoverageEvent>,
    plan_path: String,
    plan_dirty: bool,
    // Feedback bookend state
    fb_intensity: f32,
    fb_target: Vec<(String, f32)>,
    fb_current: Vec<(String, f32)>,
    allowed_shader_indices: Option<Vec<usize>>,
}

impl SlotDriftEngine {
    pub fn new(plan_path: &str, seed: u64) -> Self {
        let base_seed = std::env::var("HAPAX_EFFECT_DRIFT_SEED")
            .ok()
            .and_then(|raw| raw.parse::<u64>().ok())
            .unwrap_or(seed);
        let deterministic = std::env::var("HAPAX_EFFECT_DRIFT_DETERMINISTIC")
            .map(|raw| matches!(raw.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"))
            .unwrap_or(false);
        // Mix seed with current time for unique boot randomization
        let time_seed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0);
        let rng_seed = if deterministic {
            base_seed
        } else {
            base_seed ^ time_seed
        };
        let mut rng = SimpleRng::new(rng_seed);
        let allowed_shader_indices = configured_shader_indices_from_env();
        let all_indices: Vec<usize> = (0..SHADERS.len())
            .filter(|idx| is_composed_surface_drift_candidate(&SHADERS[*idx]))
            .collect();
        let selectable = allowed_shader_indices
            .as_deref()
            .filter(|indices| indices.len() >= POOL_SIZE)
            .unwrap_or(&all_indices);

        // Pick a constrained-random pool from the full library. The first
        // four slots are not arbitrary: they must cover visibly distinct
        // source-bound effect groups, otherwise the drift engine can satisfy
        // "active pass" telemetry while the livestream reads as unmediated.
        let pool = choose_initial_pool(&mut rng, selectable);

        let now = 0.0f32;
        let mut slots = Vec::new();
        for &shader_idx in &pool {
            let def = &SHADERS[shader_idx];
            let current_params: Vec<(String, f32)> = def
                .passthrough
                .iter()
                .map(|&(n, v)| (n.to_string(), v))
                .collect();
            let active_target = Self::random_target(&mut rng, def);

            let mut state = SlotState {
                shader_idx,
                chain: None,
                phase: Phase::Idle,
                intensity: 0.0,
                phase_start: now,
                phase_duration: 0.0,
                peak_intensity: 0.6,
                idle_since: now,
                needs_recycle: false,
                rerise_after: 0.0,
                active_target,
                current_params,
            };

            // Slots start Idle; 5 will be activated with staggered phases below
            state.idle_since = now;

            slots.push(state);
        }

        let mut initial_chain_signatures = Vec::new();
        let mut initial_chain_node_names = Vec::new();
        for slot in &mut slots {
            let chain = synthesize_chain_for_shader_avoiding(
                &mut rng,
                slot.shader_idx,
                &initial_chain_signatures,
                &initial_chain_node_names,
            );
            initial_chain_signatures.push(chain.structural_signature.clone());
            initial_chain_node_names.extend(chain.nodes.iter().copied());
            slot.chain = Some(chain);
        }

        // Activate the four baseline-visible slots at staggered lifecycle phases; the
        // fifth slot remains available for continuous zero-crossing
        // recruitment. This keeps the surface mediated without turning
        // the graph into a static all-on stack.
        {
            let mut activate_indices: Vec<usize> = (0..ACTIVE_SLOT_TARGET).collect();
            shuffle_indices(&mut rng, &mut activate_indices);
            for (ai, &slot_i) in activate_indices.iter().take(ACTIVE_SLOT_TARGET).enumerate() {
                let def = &SHADERS[slots[slot_i].shader_idx];
                slots[slot_i].peak_intensity = random_peak_intensity(&mut rng, def);
                slots[slot_i].active_target = Self::random_target(&mut rng, def);
                // Stagger across phases for immediate visual variety
                match ai % 4 {
                    0 => {
                        slots[slot_i].phase = Phase::Rising;
                        slots[slot_i].phase_duration = fade_in_duration(def, &mut rng);
                        slots[slot_i].phase_start =
                            now - slots[slot_i].phase_duration * rng.range(0.2, 0.6);
                        slots[slot_i].intensity = (slots[slot_i].peak_intensity
                            * rng.range(0.4, 0.7))
                        .max(INITIAL_VISIBLE_FLOOR);
                    }
                    1 => {
                        slots[slot_i].phase = Phase::Peak;
                        slots[slot_i].phase_duration = peak_hold_duration(def, &mut rng);
                        slots[slot_i].phase_start =
                            now - slots[slot_i].phase_duration * rng.range(0.1, 0.4);
                        slots[slot_i].intensity = slots[slot_i].peak_intensity;
                    }
                    2 => {
                        slots[slot_i].phase = Phase::Falling;
                        slots[slot_i].phase_duration = fade_out_duration(def, &mut rng);
                        slots[slot_i].phase_start =
                            now - slots[slot_i].phase_duration * rng.range(0.1, 0.5);
                        slots[slot_i].intensity = (slots[slot_i].peak_intensity
                            * rng.range(0.45, 0.8))
                        .max(INITIAL_VISIBLE_FLOOR);
                    }
                    _ => {
                        slots[slot_i].phase = Phase::Rising;
                        slots[slot_i].phase_duration = fade_in_duration(def, &mut rng);
                        slots[slot_i].phase_start =
                            now - slots[slot_i].phase_duration * rng.range(0.05, 0.3);
                        slots[slot_i].intensity = (slots[slot_i].peak_intensity
                            * rng.range(0.25, 0.5))
                        .max(INITIAL_VISIBLE_FLOOR);
                    }
                }
                slots[slot_i].idle_since = 0.0;
            }
        }

        // Init feedback bookend
        let fb_target: Vec<(String, f32)> = FEEDBACK_DEF
            .passthrough
            .iter()
            .map(|&(n, v)| (n.to_string(), v))
            .collect();
        let fb_current: Vec<(String, f32)> = FEEDBACK_DEF
            .passthrough
            .iter()
            .map(|&(n, v)| (n.to_string(), v))
            .collect();

        let mut engine = Self {
            slots,
            rng,
            tick_count: 0,
            last_activation: 0.0,
            next_stagger: STAGGER_S * 0.8,
            recently_used: VecDeque::with_capacity(RECENT_EFFECT_MEMORY),
            selection_counts: vec![0; SHADERS.len()],
            coverage_events: VecDeque::with_capacity(COVERAGE_EVENT_MEMORY),
            plan_path: plan_path.to_string(),
            plan_dirty: false,
            fb_intensity: 0.0,
            fb_target,
            fb_current,
            allowed_shader_indices,
        };
        for slot_idx in 0..engine.slots.len() {
            engine.record_selection_for_slot(slot_idx);
        }
        engine.write_plan(); // Write once at boot
        engine
    }

    fn record_selection(
        &mut self,
        shader_idx: usize,
        chain_id: String,
        parameter_regions: Vec<String>,
    ) {
        if let Some(count) = self.selection_counts.get_mut(shader_idx) {
            *count = count.saturating_add(1);
        }
        self.coverage_events.push_back(CoverageEvent {
            shader_idx,
            chain_id,
            parameter_regions,
        });
        while self.coverage_events.len() > COVERAGE_EVENT_MEMORY {
            self.coverage_events.pop_front();
        }
    }

    fn record_selection_for_slot(&mut self, slot_idx: usize) {
        let (shader_idx, chain_id, parameter_regions) = {
            let slot = &self.slots[slot_idx];
            let def = &SHADERS[slot.shader_idx];
            (
                slot.shader_idx,
                slot_chain_id(slot),
                parameter_region_labels(def, &slot.active_target),
            )
        };
        self.record_selection(shader_idx, chain_id, parameter_regions);
    }

    fn coverage_window_count(&self, shader_idx: usize) -> usize {
        self.coverage_events
            .iter()
            .filter(|event| event.shader_idx == shader_idx)
            .count()
    }

    pub fn slot_runtime_metadata(&self) -> Vec<SlotRuntimeMetadata> {
        self.slots
            .iter()
            .enumerate()
            .flat_map(|(slot_index, slot)| {
                slot_plan_nodes(slot_index, slot)
                    .into_iter()
                    .map(move |node| {
                        let def = &SHADERS[node.shader_idx];
                        let target = motif_node_target(slot, slot_index, &node);
                        SlotRuntimeMetadata {
                            slot_index,
                            node_id: node.node_id,
                            slot_phase: phase_label(slot.phase),
                            slot_intensity: slot.intensity as f64,
                            selection_count: self
                                .selection_counts
                                .get(node.shader_idx)
                                .copied()
                                .unwrap_or(0),
                            coverage_window_count: self.coverage_window_count(node.shader_idx)
                                as u64,
                            parameter_regions: parameter_regions_json(def, &target),
                        }
                    })
            })
            .collect()
    }

    fn candidate_novelty_score(&self, candidate_idx: usize, retiring_slot_idx: usize) -> f32 {
        let def = &SHADERS[candidate_idx];
        let visibility = visibility_group(def);
        let aliases = effect_aliases(def);
        let effect_window = self.coverage_window_count(candidate_idx) as f32;
        let lifetime = self
            .selection_counts
            .get(candidate_idx)
            .copied()
            .unwrap_or(0) as f32;
        let family_window = self
            .coverage_events
            .iter()
            .filter(|event| SHADERS[event.shader_idx].family == def.family)
            .count() as f32;
        let visibility_window = self
            .coverage_events
            .iter()
            .filter(|event| visibility_group(&SHADERS[event.shader_idx]) == visibility)
            .count() as f32;
        let alias_window = if aliases.is_empty() {
            0.0
        } else {
            self.coverage_events
                .iter()
                .filter(|event| {
                    effect_aliases(&SHADERS[event.shader_idx])
                        .iter()
                        .any(|alias| aliases.contains(alias))
                })
                .count() as f32
        };
        let active_same_family = self
            .slots
            .iter()
            .enumerate()
            .filter(|(slot_idx, slot)| {
                *slot_idx != retiring_slot_idx
                    && slot.phase != Phase::Idle
                    && SHADERS[slot.shader_idx].family == def.family
            })
            .count() as f32;
        let active_same_visibility = self
            .slots
            .iter()
            .enumerate()
            .filter(|(slot_idx, slot)| {
                *slot_idx != retiring_slot_idx
                    && slot.phase != Phase::Idle
                    && visibility_group(&SHADERS[slot.shader_idx]) == visibility
            })
            .count() as f32;
        let recent_penalty = self
            .recently_used
            .iter()
            .rev()
            .position(|idx| *idx == candidate_idx)
            .map(|pos| (RECENT_EFFECT_MEMORY.saturating_sub(pos)) as f32)
            .unwrap_or(0.0);

        let mut score = 500.0;
        if lifetime == 0.0 {
            score += 180.0;
        }
        if effect_window == 0.0 {
            score += 65.0;
        }
        score -= lifetime * 7.5;
        score -= effect_window * 12.0;
        score -= family_window * 1.4;
        score -= visibility_window * 2.0;
        score -= alias_window * 5.0;
        score -= active_same_family * 5.5;
        score -= active_same_visibility * 3.5;
        score -= recent_penalty * 3.0;
        if is_high_impingement_anchor(def) {
            score += 5.0;
        }
        if is_dramatic_variation_anchor(def) {
            score += 22.0;
        }
        if is_punctuation_anchor(def) {
            score += 18.0;
        }
        if is_baseline_visible(def) && !is_visible_anchor(def) && lifetime == 0.0 {
            score += 20.0;
        }
        if !aliases.is_empty() && alias_window <= 1.0 {
            score += 8.0;
        }
        score
    }

    fn pick_candidate_by_coverage(
        &mut self,
        candidates: &[usize],
        retiring_slot_idx: usize,
    ) -> usize {
        let mut best_idx = candidates[0];
        let mut best_score = f32::NEG_INFINITY;
        for &candidate_idx in candidates {
            let jitter = self.rng.next_f32() * 0.001;
            let score = self.candidate_novelty_score(candidate_idx, retiring_slot_idx) + jitter;
            if score > best_score {
                best_score = score;
                best_idx = candidate_idx;
            }
        }
        best_idx
    }

    fn random_target(rng: &mut SimpleRng, def: &ShaderDef) -> Vec<(String, f32)> {
        def.active_ranges
            .iter()
            .map(|&(n, lo, hi)| {
                let passthrough = def
                    .passthrough
                    .iter()
                    .find(|(name, _)| *name == n)
                    .map(|(_, value)| *value)
                    .unwrap_or(lo);
                (
                    n.to_string(),
                    assertive_target_value(rng, def, n, passthrough, lo, hi),
                )
            })
            .collect()
    }

    /// Call every frame. Writes plan.json on shader swaps, returns
    /// uniform overrides for uniforms.json.
    pub fn tick(&mut self, time: f32, _dt: f32) -> Vec<(String, f32)> {
        self.tick_count += 1;
        // Lifecycle advances every 5th frame, but interpolation runs every frame
        let advance_lifecycle = self.tick_count % TICK_DIVISOR == 0;

        // Phase 1: Advance lifecycles (every Nth frame)
        if advance_lifecycle {
            for i in 0..self.slots.len() {
                self.advance_lifecycle(i, time);
            }
            // Phase 2: Maybe activate next
            self.maybe_activate_next(time);
        }

        // Phase 3: Zero-crossing rotation — swap shaders that have faded to 0
        if advance_lifecycle {
            let mut plan_dirty = false;
            for i in 0..self.slots.len() {
                if self.slots[i].needs_recycle {
                    self.recycle_slot(i);
                    plan_dirty = true;
                    // Immediately begin rising with the new shader
                    let def = &SHADERS[self.slots[i].shader_idx];
                    self.slots[i].phase = Phase::Rising;
                    self.slots[i].phase_duration = fade_in_duration(def, &mut self.rng);
                    self.slots[i].active_target = Self::random_target(&mut self.rng, def);
                    self.slots[i].peak_intensity = random_peak_intensity(&mut self.rng, def);
                    let warm_progress = recruit_warm_progress(def);
                    self.slots[i].phase_start = time - self.slots[i].phase_duration * warm_progress;
                    self.slots[i].intensity =
                        lifecycle_warm_intensity(def, warm_progress, self.slots[i].peak_intensity);
                    self.record_selection_for_slot(i);
                    log::info!(
                        "SlotDrift: zero-crossing → slot {} now {} (fading in)",
                        i,
                        def.name
                    );
                }
            }
            if plan_dirty {
                self.write_plan();
            }
        }

        // Phase 5: Interpolate params and collect uniforms
        self.interpolate_all(time)
    }

    fn advance_lifecycle(&mut self, idx: usize, now: f32) {
        let another_slot_is_rotating = self.slots.iter().enumerate().any(|(slot_idx, slot)| {
            slot_idx != idx && (slot.phase == Phase::Falling || slot.needs_recycle)
        });
        let current_is_conditional =
            is_conditionally_low_salience(&SHADERS[self.slots[idx].shader_idx]);
        let overdue_conditional_waiting = !current_is_conditional
            && self.slots.iter().enumerate().any(|(slot_idx, slot)| {
                slot_idx != idx
                    && slot.phase == Phase::Peak
                    && is_conditionally_low_salience(&SHADERS[slot.shader_idx])
                    && now - slot.phase_start >= slot.phase_duration
            });
        let slot = &mut self.slots[idx];
        match slot.phase {
            Phase::Idle => {
                // Idle slots wait to be activated by maybe_activate_next
            }
            Phase::Rising => {
                let elapsed = now - slot.phase_start;
                let progress = (elapsed / slot.phase_duration).min(1.0);
                let def = &SHADERS[slot.shader_idx];
                slot.intensity = lifecycle_rise_intensity(def, progress, slot.peak_intensity);
                if progress >= 1.0 {
                    slot.phase = Phase::Peak;
                    slot.phase_start = now;
                    slot.phase_duration = peak_hold_duration(def, &mut self.rng);
                    log::info!(
                        "SlotDrift: slot {} ({}) → PEAK ({:.0}s, intensity={:.2})",
                        idx,
                        SHADERS[slot.shader_idx].name,
                        slot.phase_duration,
                        slot.peak_intensity
                    );
                }
            }
            Phase::Peak => {
                slot.intensity = slot.peak_intensity;
                let elapsed = now - slot.phase_start;
                if elapsed >= slot.phase_duration {
                    if another_slot_is_rotating {
                        return;
                    }
                    if overdue_conditional_waiting {
                        return;
                    }
                    slot.phase = Phase::Falling;
                    slot.phase_start = now;
                    let def = &SHADERS[slot.shader_idx];
                    slot.phase_duration = fade_out_duration(def, &mut self.rng);
                    log::info!(
                        "SlotDrift: slot {} ({}) → FALLING ({:.0}s)",
                        idx,
                        SHADERS[slot.shader_idx].name,
                        slot.phase_duration
                    );
                }
            }
            Phase::Falling => {
                let elapsed = now - slot.phase_start;
                let progress = (elapsed / slot.phase_duration).min(1.0);
                let def = &SHADERS[slot.shader_idx];
                slot.intensity = lifecycle_fall_intensity(def, progress, slot.peak_intensity);
                if progress >= 1.0 || slot.intensity <= retire_intensity_floor(def) {
                    // Near-zero crossing: effect is now below the visible
                    // baseline, so recycle it before a slot spends long
                    // wall-clock time counted as active but absent.
                    slot.intensity = 0.0;
                    slot.needs_recycle = true;
                    slot.idle_since = now;
                }
            }
        }
    }

    fn maybe_activate_next(&mut self, now: f32) {
        loop {
            let active_count = self.slots.iter().filter(|s| s.phase != Phase::Idle).count();
            if active_count >= ACTIVE_SLOT_TARGET {
                return;
            }

            // Find idle slots
            let idle: Vec<usize> = self
                .slots
                .iter()
                .enumerate()
                .filter(|(_, s)| s.phase == Phase::Idle)
                .map(|(i, _)| i)
                .collect();
            if idle.is_empty() {
                return;
            }

            // Spatial effects are eligible, but serially compounding too many
            // geometry transforms destroys the readable scene. Permit two so
            // the atmospheric family is not artificially sidelined while still
            // preserving recognizable geometry.
            let active_spatial_count = self
                .slots
                .iter()
                .filter(|s| s.phase != Phase::Idle && SHADERS[s.shader_idx].is_spatial)
                .count();

            // Filter idle slots: if two spatials are already active, exclude spatial idles.
            let idle: Vec<usize> = if active_spatial_count >= 2 {
                idle.into_iter()
                    .filter(|&i| !SHADERS[self.slots[i].shader_idx].is_spatial)
                    .collect()
            } else {
                idle
            };
            if idle.is_empty() {
                return;
            }

            // Pick family-affine slot
            let active_families: Vec<&str> = self
                .slots
                .iter()
                .filter(|s| s.phase != Phase::Idle)
                .map(|s| SHADERS[s.shader_idx].family)
                .collect();

            let chosen_idx = if !active_families.is_empty() && self.rng.next_f32() < 0.7 {
                let affine: Vec<usize> = idle
                    .iter()
                    .copied()
                    .filter(|&i| {
                        active_families
                            .iter()
                            .any(|af| families_affine(af, SHADERS[self.slots[i].shader_idx].family))
                    })
                    .collect();
                if !affine.is_empty() {
                    affine[(self.rng.next_f32() * affine.len() as f32) as usize % affine.len()]
                } else {
                    idle[(self.rng.next_f32() * idle.len() as f32) as usize % idle.len()]
                }
            } else {
                idle[(self.rng.next_f32() * idle.len() as f32) as usize % idle.len()]
            };

            let active_structural_signatures: Vec<String> = self
                .slots
                .iter()
                .enumerate()
                .filter(|(slot_idx, slot)| {
                    *slot_idx != chosen_idx && slot.phase != Phase::Idle && slot.chain.is_some()
                })
                .filter_map(|(_, slot)| {
                    slot.chain
                        .as_ref()
                        .map(|chain| chain.structural_signature.clone())
                })
                .collect();
            let active_node_names: Vec<&'static str> = self
                .slots
                .iter()
                .enumerate()
                .filter(|(slot_idx, slot)| {
                    *slot_idx != chosen_idx && slot.phase != Phase::Idle && slot.chain.is_some()
                })
                .flat_map(|(_, slot)| {
                    slot.chain
                        .as_ref()
                        .into_iter()
                        .flat_map(|chain| chain.nodes.iter().copied())
                })
                .collect();
            let slot = &mut self.slots[chosen_idx];
            let def = &SHADERS[slot.shader_idx];
            slot.chain = Some(synthesize_chain_for_shader_avoiding(
                &mut self.rng,
                slot.shader_idx,
                &active_structural_signatures,
                &active_node_names,
            ));
            slot.phase = Phase::Rising;
            slot.phase_duration = fade_in_duration(def, &mut self.rng);
            slot.active_target = Self::random_target(&mut self.rng, def);
            slot.peak_intensity = random_peak_intensity(&mut self.rng, def);
            let warm_progress = recruit_warm_progress(def);
            slot.phase_start = now - slot.phase_duration * warm_progress;
            slot.intensity = lifecycle_warm_intensity(def, warm_progress, slot.peak_intensity);
            self.record_selection_for_slot(chosen_idx);
            self.last_activation = now;
            self.next_stagger = STAGGER_S * self.rng.range(0.7, 1.3);
            log::info!(
                "SlotDrift: activating slot {} ({}), {} now active",
                chosen_idx,
                def.name,
                active_count + 1
            );
        }
    }

    fn recycle_slot(&mut self, idx: usize) {
        let current_types: Vec<usize> = self.slots.iter().map(|s| s.shader_idx).collect();
        let recently: Vec<usize> = self.recently_used.iter().copied().collect();
        let base_candidates: Vec<usize> =
            self.allowed_shader_indices.clone().unwrap_or_else(|| {
                (0..SHADERS.len())
                    .filter(|idx| is_composed_surface_drift_candidate(&SHADERS[*idx]))
                    .collect()
            });
        let non_current_candidates: Vec<usize> = base_candidates
            .iter()
            .copied()
            .filter(|i| is_composed_surface_drift_candidate(&SHADERS[*i]))
            .filter(|i| !current_types.contains(i))
            .collect();
        if non_current_candidates.is_empty() {
            self.slots[idx].needs_recycle = false;
            return;
        }
        let hard_floor_candidates = non_current_candidates.clone();

        let active_visible_groups: Vec<&str> = self
            .slots
            .iter()
            .enumerate()
            .filter(|(slot_idx, slot)| *slot_idx != idx && slot.phase != Phase::Idle)
            .map(|(_, slot)| visibility_group(&SHADERS[slot.shader_idx]))
            .collect();
        let missing_groups: Vec<&str> = COMPOSED_SURFACE_BASELINE_GROUPS
            .iter()
            .copied()
            .filter(|group| !active_visible_groups.contains(group))
            .collect();
        let active_anchor_count = self
            .slots
            .iter()
            .enumerate()
            .filter(|(slot_idx, slot)| {
                *slot_idx != idx
                    && slot.phase != Phase::Idle
                    && is_visible_anchor(&SHADERS[slot.shader_idx])
            })
            .count();
        let active_conditional_count = self
            .slots
            .iter()
            .enumerate()
            .filter(|(slot_idx, slot)| {
                *slot_idx != idx
                    && slot.phase != Phase::Idle
                    && is_conditionally_low_salience(&SHADERS[slot.shader_idx])
            })
            .count();
        let active_high_impingement_count = self
            .slots
            .iter()
            .enumerate()
            .filter(|(slot_idx, slot)| {
                *slot_idx != idx
                    && slot.phase != Phase::Idle
                    && is_high_impingement_anchor(&SHADERS[slot.shader_idx])
            })
            .count();
        let active_dramatic_variation_count = self
            .slots
            .iter()
            .enumerate()
            .filter(|(slot_idx, slot)| {
                *slot_idx != idx
                    && slot.phase != Phase::Idle
                    && is_dramatic_variation_anchor(&SHADERS[slot.shader_idx])
            })
            .count();
        let active_punctuation_count = self
            .slots
            .iter()
            .enumerate()
            .filter(|(slot_idx, slot)| {
                *slot_idx != idx
                    && slot.phase != Phase::Idle
                    && is_punctuation_anchor(&SHADERS[slot.shader_idx])
            })
            .count();
        let active_structural_signatures: Vec<String> = self
            .slots
            .iter()
            .enumerate()
            .filter(|(slot_idx, slot)| {
                *slot_idx != idx && slot.phase != Phase::Idle && slot.chain.is_some()
            })
            .filter_map(|(_, slot)| {
                slot.chain
                    .as_ref()
                    .map(|chain| chain.structural_signature.clone())
            })
            .collect();
        let mut active_node_names: Vec<&'static str> = self
            .slots
            .iter()
            .enumerate()
            .filter(|(slot_idx, slot)| {
                *slot_idx != idx && slot.phase != Phase::Idle && slot.chain.is_some()
            })
            .flat_map(|(_, slot)| {
                slot.chain
                    .as_ref()
                    .into_iter()
                    .flat_map(|chain| chain.nodes.iter().copied())
            })
            .collect();
        if let Some(retiring_chain) = &self.slots[idx].chain {
            active_node_names.extend(retiring_chain.nodes.iter().copied());
        }
        let chain_fresh_non_current_candidates: Vec<usize> = non_current_candidates
            .iter()
            .copied()
            .filter(|i| {
                !active_node_names.contains(&SHADERS[*i].name)
                    && shader_can_generate_fresh_chain(*i, &active_structural_signatures)
            })
            .collect();
        let non_current_candidates = if chain_fresh_non_current_candidates.is_empty() {
            non_current_candidates
        } else {
            chain_fresh_non_current_candidates
        };
        let fresh_candidates: Vec<usize> = non_current_candidates
            .iter()
            .copied()
            .filter(|i| !recently.contains(i))
            .collect();
        let candidates = if fresh_candidates.is_empty() {
            non_current_candidates.clone()
        } else {
            fresh_candidates
        };
        let active_generated_chain_count = active_structural_signatures.len();
        let candidate_preserves_hard_floor = |idx: usize| {
            let def = &SHADERS[idx];
            let candidate_anchor = usize::from(is_visible_anchor(def));
            let candidate_high_impingement = usize::from(is_high_impingement_anchor(def));
            let candidate_dramatic_variation = usize::from(is_dramatic_variation_anchor(def));
            let candidate_punctuation = usize::from(is_punctuation_anchor(def));
            let candidate_conditional = usize::from(is_conditionally_low_salience(def));
            active_anchor_count + candidate_anchor >= MIN_ACTIVE_ANCHOR_EFFECTS
                && active_high_impingement_count + candidate_high_impingement
                    >= MIN_ACTIVE_HIGH_IMPINGEMENT_EFFECTS
                && active_dramatic_variation_count + candidate_dramatic_variation
                    >= MIN_ACTIVE_DRAMATIC_VARIATION_EFFECTS
                && active_punctuation_count + candidate_punctuation
                    >= MIN_ACTIVE_PUNCTUATION_EFFECTS
                && active_conditional_count + candidate_conditional
                    <= MAX_ACTIVE_CONDITIONAL_EFFECTS
        };
        let preferred: Vec<usize> = hard_floor_candidates
            .iter()
            .copied()
            .filter(|i| {
                let def = &SHADERS[*i];
                is_baseline_visible(def)
                    && missing_groups.contains(&visibility_group(def))
                    && candidate_preserves_hard_floor(*i)
            })
            .collect();
        let preferred: Vec<usize> = if preferred.is_empty()
            && active_high_impingement_count < MIN_ACTIVE_HIGH_IMPINGEMENT_EFFECTS
        {
            hard_floor_candidates
                .iter()
                .copied()
                .filter(|i| {
                    is_high_impingement_anchor(&SHADERS[*i]) && candidate_preserves_hard_floor(*i)
                })
                .collect()
        } else {
            preferred
        };
        let preferred: Vec<usize> = if preferred.is_empty()
            && active_dramatic_variation_count < MIN_ACTIVE_DRAMATIC_VARIATION_EFFECTS
        {
            hard_floor_candidates
                .iter()
                .copied()
                .filter(|i| {
                    is_dramatic_variation_anchor(&SHADERS[*i]) && candidate_preserves_hard_floor(*i)
                })
                .collect()
        } else {
            preferred
        };
        let preferred: Vec<usize> =
            if preferred.is_empty() && active_punctuation_count < MIN_ACTIVE_PUNCTUATION_EFFECTS {
                hard_floor_candidates
                    .iter()
                    .copied()
                    .filter(|i| {
                        is_punctuation_anchor(&SHADERS[*i]) && candidate_preserves_hard_floor(*i)
                    })
                    .collect()
            } else {
                preferred
            };
        let preferred: Vec<usize> = if preferred.is_empty() {
            candidates
                .iter()
                .copied()
                .filter(|i| {
                    let def = &SHADERS[*i];
                    is_visible_anchor(def)
                        && (active_anchor_count + 1 >= MIN_ACTIVE_ANCHOR_EFFECTS)
                        && candidate_preserves_hard_floor(*i)
                })
                .collect()
        } else {
            preferred
        };
        let preferred: Vec<usize> = if preferred.is_empty() {
            candidates
                .iter()
                .copied()
                .filter(|i| {
                    let def = &SHADERS[*i];
                    is_baseline_visible(def)
                        && candidate_preserves_hard_floor(*i)
                        && (self.selection_counts.get(*i).copied().unwrap_or(0) == 0
                            || self.coverage_window_count(*i) == 0)
                })
                .collect()
        } else {
            preferred
        };
        let preferred: Vec<usize> = if preferred.is_empty() {
            candidates
                .iter()
                .copied()
                .filter(|i| {
                    let def = &SHADERS[*i];
                    is_baseline_visible(def)
                        && candidate_preserves_hard_floor(*i)
                        && (!is_conditionally_low_salience(def)
                            || active_conditional_count < MAX_ACTIVE_CONDITIONAL_EFFECTS)
                })
                .collect()
        } else {
            preferred
        };
        let preferred: Vec<usize> = if preferred.is_empty()
            && active_generated_chain_count < MIN_ACTIVE_GENERATED_CHAIN_SLOTS
        {
            candidates
                .iter()
                .copied()
                .filter(|i| {
                    is_baseline_visible(&SHADERS[*i])
                        && candidate_preserves_hard_floor(*i)
                        && shader_can_generate_fresh_chain(*i, &active_structural_signatures)
                })
                .collect()
        } else {
            preferred
        };
        let candidates = if preferred.is_empty() {
            candidates
        } else {
            preferred
        };

        let old_idx = self.slots[idx].shader_idx;
        let new_idx = self.pick_candidate_by_coverage(&candidates, idx);
        let def = &SHADERS[new_idx];
        let selected_chain = synthesize_chain_for_shader_avoiding(
            &mut self.rng,
            new_idx,
            &active_structural_signatures,
            &active_node_names,
        );

        self.slots[idx].shader_idx = new_idx;
        self.slots[idx].chain = Some(selected_chain);
        self.slots[idx].current_params = def
            .passthrough
            .iter()
            .map(|&(n, v)| (n.to_string(), v))
            .collect();
        self.slots[idx].intensity = 0.0;
        self.slots[idx].needs_recycle = false;
        self.slots[idx].rerise_after = self.slots[idx].idle_since + 2.0;
        self.recently_used.push_back(old_idx);
        if self.recently_used.len() > RECENT_EFFECT_MEMORY {
            self.recently_used.pop_front();
        }

        log::info!(
            "SlotDrift: recycle slot {} {} → {} (rerise in 2s)",
            idx,
            SHADERS[old_idx].name,
            def.name
        );
    }

    fn interpolate_all(&mut self, now: f32) -> Vec<(String, f32)> {
        let mut uniforms = Vec::new();

        for slot_idx in 0..self.slots.len() {
            let plan_nodes = slot_plan_nodes(slot_idx, &self.slots[slot_idx]);
            let slot_intensity = self.slots[slot_idx].intensity;
            let primary_shader_idx = self.slots[slot_idx].shader_idx;

            for node in plan_nodes {
                let def = &SHADERS[node.shader_idx];
                let target = motif_node_target(&self.slots[slot_idx], slot_idx, &node);

                for (pi, &(pname, pt_val)) in def.passthrough.iter().enumerate() {
                    if pname == "time" {
                        let time_value = now.max(0.0);
                        if node.shader_idx == primary_shader_idx {
                            self.slots[slot_idx]
                                .current_params
                                .iter_mut()
                                .find(|(n, _)| n == pname)
                                .map(|(_, v)| *v = time_value);
                        }
                        uniforms.push((format!("{}.{}", node.node_id, pname), time_value));
                        continue;
                    }

                    let act_val = target
                        .iter()
                        .find(|(n, _)| n == pname)
                        .map(|(_, v)| *v)
                        .unwrap_or(pt_val);
                    let interpolated = interpolated_param_value(
                        def,
                        slot_idx,
                        node.chain_node_index,
                        node.shader_idx,
                        pi,
                        pname,
                        pt_val,
                        act_val,
                        slot_intensity,
                        now,
                    );

                    if node.shader_idx == primary_shader_idx {
                        self.slots[slot_idx]
                            .current_params
                            .iter_mut()
                            .find(|(n, _)| n == pname)
                            .map(|(_, v)| *v = interpolated);
                    }
                    uniforms.push((format!("{}.{}", node.node_id, pname), interpolated));
                }
            }
        }

        // Feedback bookend: slowly evolve toward target
        let alpha = 0.002; // slow convergence
        for (i, &(ref name, _)) in self.fb_current.clone().iter().enumerate() {
            if let Some((_, tgt)) = self.fb_target.iter().find(|(n, _)| n == name) {
                let cur = self.fb_current[i].1;
                let new_val = cur + (*tgt - cur) * alpha;
                self.fb_current[i].1 = new_val;
                uniforms.push((format!("fb.{}", name), new_val));
            }
        }

        // Postprocess bookend must be a true no-op unless a governed
        // director decision deliberately moves it. Time-driven opacity
        // modulation reads as whole-frame pumping/dimming on the livestream.
        for &(name, val) in POSTPROCESS_DEF.passthrough.iter() {
            uniforms.push((format!("post.{}", name), val));
        }

        uniforms
    }

    fn coverage_snapshot(&self) -> serde_json::Value {
        let effect_counts: Vec<serde_json::Value> = SHADERS
            .iter()
            .enumerate()
            .filter(|(_, def)| is_autonomous_drift_candidate(def))
            .map(|(idx, def)| {
                serde_json::json!({
                    "name": def.name,
                    "family": def.family,
                    "visibility_group": visibility_group(def),
                    "coverage_role": effect_coverage_role(def),
                    "route_authority": effect_route_authority(def),
                    "aliases": effect_aliases(def),
                    "selection_count": self.selection_counts.get(idx).copied().unwrap_or(0),
                    "coverage_window_count": self.coverage_window_count(idx),
                })
            })
            .collect();
        let route_blocked_effects: Vec<serde_json::Value> = SHADERS
            .iter()
            .filter(|def| {
                is_autonomous_drift_candidate(def) && !is_composed_surface_drift_candidate(def)
            })
            .map(|def| {
                serde_json::json!({
                    "name": def.name,
                    "family": def.family,
                    "visibility_group": visibility_group(def),
                    "coverage_role": effect_coverage_role(def),
                    "route_authority": effect_route_authority(def),
                    "blocked_reason": "requires entity-local spatial routing before activation",
                })
            })
            .collect();
        let recent_effects: Vec<&str> = self
            .coverage_events
            .iter()
            .map(|event| SHADERS[event.shader_idx].name)
            .collect();
        let recent_motifs: Vec<String> = self
            .coverage_events
            .iter()
            .map(|event| event.chain_id.clone())
            .collect();
        let family_counts = label_counts_json(
            self.coverage_events
                .iter()
                .map(|event| SHADERS[event.shader_idx].family.to_string())
                .collect(),
        );
        let visibility_counts = label_counts_json(
            self.coverage_events
                .iter()
                .map(|event| visibility_group(&SHADERS[event.shader_idx]).to_string())
                .collect(),
        );
        let alias_counts = label_counts_json(
            self.coverage_events
                .iter()
                .flat_map(|event| {
                    effect_aliases(&SHADERS[event.shader_idx])
                        .iter()
                        .map(|alias| alias.to_string())
                })
                .collect(),
        );
        let parameter_region_counts = label_counts_json(
            self.coverage_events
                .iter()
                .flat_map(|event| event.parameter_regions.iter().cloned())
                .collect(),
        );
        let motif_counts = label_counts_json(
            self.coverage_events
                .iter()
                .map(|event| event.chain_id.clone())
                .collect(),
        );

        serde_json::json!({
            "schema": "slotdrift-coverage-v1",
            "window_limit": COVERAGE_EVENT_MEMORY,
            "recent_effects": recent_effects,
            "recent_motifs": recent_motifs,
            "effect_counts": effect_counts,
            "route_blocked_effects": route_blocked_effects,
            "family_counts": family_counts,
            "visibility_group_counts": visibility_counts,
            "alias_counts": alias_counts,
            "parameter_region_counts": parameter_region_counts,
            "motif_counts": motif_counts,
        })
    }

    fn write_plan(&self) {
        let mut passes = Vec::new();
        let mut prev_output = "@live".to_string();
        let mut layer_index = 0usize;
        let plan_dir = Path::new(&self.plan_path)
            .parent()
            .unwrap_or_else(|| Path::new("."));

        for (i, slot) in self.slots.iter().enumerate() {
            for node in slot_plan_nodes(i, slot) {
                let def = &SHADERS[node.shader_idx];
                copy_shader_to_plan_dir(def, plan_dir);
                let layer = format!("layer_{}", layer_index);
                layer_index += 1;
                let mut uniforms_map = serde_json::Map::new();
                let param_order: Vec<String> =
                    def.param_order.iter().map(|s| s.to_string()).collect();
                let (inputs, temporal) = pass_inputs_for_node(def, &node.node_id, &prev_output);
                let target = motif_node_target(slot, i, &node);

                for &(name, val) in def.passthrough.iter() {
                    uniforms_map.insert(name.to_string(), serde_json::Value::from(val as f64));
                }

                let mut pass = serde_json::json!({
                    "node_id": node.node_id,
                    "shader": def.shader_file,
                    "type": "render",
                    "backend": "wgsl_render",
                    "inputs": inputs,
                    "output": layer,
                    "uniforms": uniforms_map,
                    "param_order": param_order,
                    "effect_scope": "composed_live_surface",
                    "effect_family": def.family,
                    "visibility_group": visibility_group(def),
                    "eviction_cadence": eviction_cadence_label(def),
                    "source_bound": true,
                    "full_surface": true,
                    "effect_binding": "source_presence_gated",
                    "route_authority": effect_route_authority(def),
                    "effect_application_plane": effect_application_plane(def),
                    "fourth_wall_policy": "forbid_foreground_overlay",
                    "coverage_role": effect_coverage_role(def),
                    "effect_aliases": effect_aliases(def),
                    "slot_index": i,
                    "slot_phase": phase_label(slot.phase),
                    "slot_intensity": slot.intensity as f64,
                    "selection_count": self.selection_counts.get(node.shader_idx).copied().unwrap_or(0),
                    "coverage_window_count": self.coverage_window_count(node.shader_idx),
                    "parameter_regions": parameter_regions_json(def, &target),
                    "preset_chain_id": node.preset_chain_id,
                    "chain_lineage": node.chain_lineage,
                    "structural_signature": node.structural_signature,
                    "topology_signature": node.topology_signature,
                    "graph_motif": node.graph_motif,
                    "motif_node_index": node.chain_node_index,
                });
                if temporal {
                    pass.as_object_mut()
                        .expect("effect pass is a JSON object")
                        .insert("temporal".to_string(), serde_json::Value::Bool(true));
                }
                passes.push(pass);
                prev_output = layer;
            }
        }

        // Feedback bookend
        {
            copy_shader_to_plan_dir(&FEEDBACK_DEF, plan_dir);
            let layer = format!("layer_{}", layer_index);
            let mut u = serde_json::Map::new();
            for &(name, val) in FEEDBACK_DEF.passthrough.iter() {
                u.insert(name.to_string(), serde_json::Value::from(val as f64));
            }
            let po: Vec<String> = FEEDBACK_DEF
                .param_order
                .iter()
                .map(|s| s.to_string())
                .collect();
            passes.push(serde_json::json!({
                "node_id": "fb",
                "shader": FEEDBACK_DEF.shader_file,
                "type": "render", "backend": "wgsl_render",
                "inputs": [prev_output, "@accum_fb"],
                "output": layer,
                "uniforms": u, "param_order": po,
                "temporal": true,
                "effect_scope": "composed_live_surface",
                "effect_family": FEEDBACK_DEF.family,
                "visibility_group": "temporal",
                "eviction_cadence": "slow",
                "source_bound": true,
                "full_surface": true,
                "effect_binding": "bounded_bookend",
                "effect_application_plane": "entity_field_temporal_treatment",
                "fourth_wall_policy": "forbid_foreground_overlay",
                "coverage_role": "supporting_conditional",
                "effect_aliases": ["feedback_bookend"],
                "slot_phase": "bookend",
                "slot_intensity": 0.0,
                "preset_chain_id": "bookend:feedback",
                "chain_lineage": "slotdrift-bookend:feedback",
                "structural_signature": "bookend:feedback",
                "topology_signature": "bookend:feedback",
                "graph_motif": "feedback_bookend",
            }));
            prev_output = layer;
        }

        // Postprocess bookend
        {
            copy_shader_to_plan_dir(&POSTPROCESS_DEF, plan_dir);
            let mut u = serde_json::Map::new();
            for &(name, val) in POSTPROCESS_DEF.passthrough.iter() {
                u.insert(name.to_string(), serde_json::Value::from(val as f64));
            }
            let po: Vec<String> = POSTPROCESS_DEF
                .param_order
                .iter()
                .map(|s| s.to_string())
                .collect();
            passes.push(serde_json::json!({
                "node_id": "post",
                "shader": POSTPROCESS_DEF.shader_file,
                "type": "render", "backend": "wgsl_render",
                "inputs": [prev_output], "output": "final",
                "uniforms": u, "param_order": po,
                "effect_scope": "composed_live_surface",
                "effect_family": POSTPROCESS_DEF.family,
                "visibility_group": "postprocess",
                "eviction_cadence": "slow",
                "source_bound": true,
                "full_surface": true,
                "effect_binding": "bounded_bookend",
                "effect_application_plane": "entity_field_surface_treatment",
                "fourth_wall_policy": "forbid_foreground_overlay",
                "coverage_role": "supporting_conditional",
                "effect_aliases": ["postprocess_bookend", "anti_parasocial_bookend"],
                "slot_phase": "bookend",
                "slot_intensity": 0.0,
                "preset_chain_id": "bookend:postprocess",
                "chain_lineage": "slotdrift-bookend:postprocess",
                "structural_signature": "bookend:postprocess",
                "topology_signature": "bookend:postprocess",
                "graph_motif": "postprocess_bookend",
            }));
        }

        let plan = serde_json::json!({
            "version": 2,
            "slotdrift_coverage": self.coverage_snapshot(),
            "targets": { "main": { "passes": passes } }
        });

        let chain: Vec<&str> = self
            .slots
            .iter()
            .map(|s| SHADERS[s.shader_idx].name)
            .collect();
        let motifs: Vec<String> = self.slots.iter().map(slot_chain_id).collect();
        log::info!(
            "SlotDrift: writing plan chain={:?} motifs={:?}",
            chain,
            motifs
        );

        if let Err(e) = std::fs::write(
            Path::new(&self.plan_path),
            serde_json::to_string_pretty(&plan).unwrap(),
        ) {
            log::warn!("SlotDrift: plan write failed: {}", e);
        }
    }
}

fn copy_shader_to_plan_dir(def: &ShaderDef, plan_dir: &Path) {
    let src = shader_nodes_dir().join(def.shader_file);
    let dst = plan_dir.join(def.shader_file);
    if let Err(e) = std::fs::create_dir_all(plan_dir) {
        log::warn!(
            "SlotDrift: failed to create shader plan dir {}: {}",
            plan_dir.display(),
            e
        );
        return;
    }
    if let Err(e) = std::fs::copy(&src, &dst) {
        log::warn!(
            "SlotDrift: failed to copy shader {} → {}: {}",
            src.display(),
            dst.display(),
            e
        );
    }
}
