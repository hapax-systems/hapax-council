//! Slot-pool drift engine — Rust port of slot_drift.py + parameter_drift.py.
//!
//! 6-slot pool with staggered lifecycles: IDLE→RISING→PEAK→FALLING.
//! Drives plan.json + uniforms.json for the wgpu DynamicPipeline.

use std::collections::VecDeque;
use std::path::Path;

// ── Lifecycle timing (matching 2D) ─────────────────────────────
const FADE_IN_S: f32 = 18.0;
const PEAK_HOLD_S: f32 = 9.0;
const FADE_OUT_S: f32 = 18.0;
const STAGGER_S: f32 = 9.0;
const POOL_SIZE: usize = 5; // Five visible slots: four active, one rotating/recruiting.
const ACTIVE_SLOT_TARGET: usize = 4;
const PARAM_DRIFT_RATE: f32 = 0.015;
const TICK_DIVISOR: u64 = 5; // ~6Hz at 30fps
const SPATIAL_PEAK_RANGE: (f32, f32) = (0.55, 0.82);
const NONSPATIAL_PEAK_RANGE: (f32, f32) = (0.82, 1.0);

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
            ("brightness", 0.92, 1.12),
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
            ("speed", 0.08, 0.22),
            ("amplitude", 0.08, 0.32),
            ("frequency", 0.8, 1.8),
            ("coherence", 0.55, 0.9),
        ],
        param_order: &["speed", "amplitude", "frequency", "coherence"],
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
        active_ranges: &[("threshold", 0.08, 0.45), ("color_mode", 0.12, 0.32)],
        param_order: &["threshold", "color_mode"],
    },
    ShaderDef {
        name: "chromatic_aberration",
        shader_file: "chromatic_aberration.wgsl",
        family: "atmospheric",
        is_spatial: false,
        passthrough: &[("offset_x", 0.0), ("offset_y", 0.0), ("intensity", 0.0)],
        active_ranges: &[
            ("offset_x", -0.8, 0.8),
            ("offset_y", -0.35, 0.35),
            ("intensity", 0.05, 0.28),
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
            ("opacity", 0.03, 0.12),
            ("spacing", 5.0, 10.0),
            ("thickness", 0.8, 1.6),
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
        active_ranges: &[("edge_glow", 0.10, 0.35), ("palette_shift", 0.0, 1.0)],
        param_order: &["edge_glow", "palette_shift"],
    },
    ShaderDef {
        name: "halftone",
        shader_file: "halftone.wgsl",
        family: "texture",
        is_spatial: false,
        passthrough: &[("dot_size", 0.5), ("color_mode", 1.0)],
        active_ranges: &[("dot_size", 1.2, 3.4), ("color_mode", 1.0, 1.0)],
        param_order: &["dot_size", "color_mode"],
    },
    ShaderDef {
        name: "posterize",
        shader_file: "posterize.wgsl",
        family: "tonal",
        is_spatial: false,
        passthrough: &[("levels", 256.0), ("gamma", 1.0)],
        active_ranges: &[("levels", 4.0, 16.0), ("gamma", 0.85, 1.2)],
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
            ("segments", 1.5, 4.0),
            ("center_x", 0.47, 0.53),
            ("center_y", 0.47, 0.53),
            ("rotation", 0.0, 0.45),
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
            ("strength", 0.04, 0.18),
            ("center_x", 0.42, 0.58),
            ("center_y", 0.42, 0.58),
            ("zoom", 0.98, 1.02),
        ],
        param_order: &["strength", "center_x", "center_y", "zoom"],
    },
    ShaderDef {
        name: "mirror",
        shader_file: "mirror.wgsl",
        family: "atmospheric",
        is_spatial: true,
        passthrough: &[("axis", 0.0), ("position", 1.0)],
        active_ranges: &[("axis", 0.0, 1.0), ("position", 0.40, 0.70)],
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
            ("color_levels", 4.0, 16.0),
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
            ("pos_x", -0.006, 0.006),
            ("pos_y", -0.004, 0.004),
            ("scale_x", 0.985, 1.035),
            ("scale_y", 0.985, 1.035),
            ("rotation", 0.0, 0.025),
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
            ("brightness", 0.92, 1.12),
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
            ("cycle_rate", 0.015, 0.055),
            ("n_bands", 5.0, 12.0),
            ("blend", 0.06, 0.16),
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
        active_ranges: &[("direction", 0.0, 1.0), ("speed", 0.08, 0.22)],
        param_order: &["direction", "speed"],
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
            ("slice_count", 4.0, 12.0),
            ("slice_amplitude", 0.004, 0.020),
            ("pan_x", -2.0, 2.0),
            ("pan_y", -1.0, 1.0),
            ("rotation", 0.0, 0.012),
            ("zoom", 0.995, 1.015),
            ("zoom_breath", 0.0, 0.006),
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
        active_ranges: &[("strength_x", 0.012, 0.055), ("strength_y", 0.012, 0.055)],
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
            ("threshold_low", 0.35, 0.55),
            ("threshold_high", 0.62, 0.82),
            ("sort_length", 6.0, 24.0),
            ("direction", 0.0, 1.0),
        ],
        param_order: &[
            "threshold_low",
            "threshold_high",
            "sort_length",
            "direction",
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
        ("blend_mode", 1.0),
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
        ("blend_mode", 1.0, 1.0),
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
        _ => true,
    }
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
    fn multi_input_autonomous_shaders_get_valid_inputs() {
        let slitscan = SHADERS.iter().find(|def| def.name == "slitscan").unwrap();
        let (inputs, temporal) = pass_inputs_for(slitscan, "layer_prev");
        assert_eq!(inputs, vec!["layer_prev", "@accum_slitscan"]);
        assert!(temporal);

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
    fn autonomous_drift_library_keeps_all_effect_families_eligible() {
        let families: std::collections::HashSet<&str> =
            SHADERS.iter().map(|def| def.family).collect();
        for family in ["tonal", "texture", "edge", "atmospheric"] {
            assert!(
                families.contains(family),
                "effect family {family} must remain in the autonomous drift library"
            );
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

// ── Simple RNG ─────────────────────────────────────────────────

struct SimpleRng(u64);
impl SimpleRng {
    fn new(seed: u64) -> Self {
        Self(seed)
    }
    fn next_f32(&mut self) -> f32 {
        self.0 = self
            .0
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
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
    if def.name == "slitscan" {
        return (
            vec![prev_output.to_string(), format!("@accum_{}", def.name)],
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

fn random_peak_intensity(rng: &mut SimpleRng, def: &ShaderDef) -> f32 {
    let (lo, hi) = if def.is_spatial {
        SPATIAL_PEAK_RANGE
    } else {
        NONSPATIAL_PEAK_RANGE
    };
    rng.range(lo, hi)
}

// ── Engine ─────────────────────────────────────────────────────

pub struct SlotDriftEngine {
    slots: Vec<SlotState>,
    rng: SimpleRng,
    tick_count: u64,
    last_activation: f32,
    next_stagger: f32,
    recently_used: VecDeque<usize>,
    plan_path: String,
    plan_dirty: bool,
    // Feedback bookend state
    fb_intensity: f32,
    fb_target: Vec<(String, f32)>,
    fb_current: Vec<(String, f32)>,
}

impl SlotDriftEngine {
    pub fn new(plan_path: &str, seed: u64) -> Self {
        // Mix seed with current time for unique boot randomization
        let time_seed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0);
        let mut rng = SimpleRng::new(seed ^ time_seed);

        // Pick 6 random shaders from the full library
        let mut indices: Vec<usize> = (0..SHADERS.len()).collect();
        for i in (1..indices.len()).rev() {
            let j = (rng.next_f32() * (i + 1) as f32) as usize % (i + 1);
            indices.swap(i, j);
        }
        let pool: Vec<usize> = indices.into_iter().take(POOL_SIZE).collect();

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

        // Activate four random slots at staggered lifecycle phases; the
        // fifth slot remains available for continuous zero-crossing
        // recruitment. This keeps the surface mediated without turning
        // the graph into a static all-on stack.
        {
            let mut activate_indices: Vec<usize> = (0..slots.len()).collect();
            for i in (1..activate_indices.len()).rev() {
                let j = (rng.next_f32() * (i + 1) as f32) as usize % (i + 1);
                activate_indices.swap(i, j);
            }
            for (ai, &slot_i) in activate_indices.iter().take(ACTIVE_SLOT_TARGET).enumerate() {
                let def = &SHADERS[slots[slot_i].shader_idx];
                slots[slot_i].peak_intensity = random_peak_intensity(&mut rng, def);
                slots[slot_i].active_target = Self::random_target(&mut rng, def);
                // Stagger across phases for immediate visual variety
                match ai % 4 {
                    0 => {
                        slots[slot_i].phase = Phase::Rising;
                        slots[slot_i].phase_duration = FADE_IN_S * rng.range(0.8, 1.2);
                        slots[slot_i].phase_start =
                            now - slots[slot_i].phase_duration * rng.range(0.2, 0.6);
                        slots[slot_i].intensity =
                            slots[slot_i].peak_intensity * rng.range(0.4, 0.7);
                    }
                    1 => {
                        slots[slot_i].phase = Phase::Peak;
                        slots[slot_i].phase_duration = PEAK_HOLD_S * rng.range(0.6, 1.4);
                        slots[slot_i].phase_start =
                            now - slots[slot_i].phase_duration * rng.range(0.1, 0.4);
                        slots[slot_i].intensity = slots[slot_i].peak_intensity;
                    }
                    2 => {
                        slots[slot_i].phase = Phase::Falling;
                        slots[slot_i].phase_duration = FADE_OUT_S * rng.range(0.8, 1.2);
                        slots[slot_i].phase_start =
                            now - slots[slot_i].phase_duration * rng.range(0.1, 0.5);
                        slots[slot_i].intensity =
                            slots[slot_i].peak_intensity * rng.range(0.45, 0.8);
                    }
                    _ => {
                        slots[slot_i].phase = Phase::Rising;
                        slots[slot_i].phase_duration = FADE_IN_S * rng.range(0.8, 1.2);
                        slots[slot_i].phase_start =
                            now - slots[slot_i].phase_duration * rng.range(0.05, 0.3);
                        slots[slot_i].intensity =
                            slots[slot_i].peak_intensity * rng.range(0.25, 0.5);
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

        let engine = Self {
            slots,
            rng,
            tick_count: 0,
            last_activation: 0.0,
            next_stagger: STAGGER_S * 0.8,
            recently_used: VecDeque::with_capacity(18),
            plan_path: plan_path.to_string(),
            plan_dirty: false,
            fb_intensity: 0.0,
            fb_target,
            fb_current,
        };
        engine.write_plan(); // Write once at boot
        engine
    }

    fn random_target(rng: &mut SimpleRng, def: &ShaderDef) -> Vec<(String, f32)> {
        def.active_ranges
            .iter()
            .map(|&(n, lo, hi)| (n.to_string(), rng.range(lo, hi)))
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
                    self.slots[i].phase_duration = FADE_IN_S * self.rng.range(0.8, 1.2);
                    self.slots[i].active_target = Self::random_target(&mut self.rng, def);
                    self.slots[i].peak_intensity = random_peak_intensity(&mut self.rng, def);
                    let warm_progress = 0.12;
                    let warm_smooth = warm_progress * warm_progress * (3.0 - 2.0 * warm_progress);
                    self.slots[i].phase_start = time - self.slots[i].phase_duration * warm_progress;
                    self.slots[i].intensity = self.slots[i].peak_intensity * warm_smooth;
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
        let slot = &mut self.slots[idx];
        match slot.phase {
            Phase::Idle => {
                // Idle slots wait to be activated by maybe_activate_next
            }
            Phase::Rising => {
                let elapsed = now - slot.phase_start;
                let progress = (elapsed / slot.phase_duration).min(1.0);
                let smooth = progress * progress * (3.0 - 2.0 * progress);
                slot.intensity = smooth * slot.peak_intensity;
                if progress >= 1.0 {
                    slot.phase = Phase::Peak;
                    slot.phase_start = now;
                    slot.phase_duration = PEAK_HOLD_S * self.rng.range(0.6, 1.4);
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
                    slot.phase = Phase::Falling;
                    slot.phase_start = now;
                    slot.phase_duration = FADE_OUT_S * self.rng.range(0.8, 1.2);
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
                let inv = 1.0 - progress;
                slot.intensity = slot.peak_intensity * inv * inv * (3.0 - 2.0 * inv);
                if progress >= 1.0 {
                    // Zero-crossing: effect is now invisible → safe to swap shader
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

            let slot = &mut self.slots[chosen_idx];
            let def = &SHADERS[slot.shader_idx];
            slot.phase = Phase::Rising;
            slot.phase_duration = FADE_IN_S * self.rng.range(0.8, 1.2);
            slot.active_target = Self::random_target(&mut self.rng, def);
            slot.peak_intensity = random_peak_intensity(&mut self.rng, def);
            let warm_progress = 0.12;
            let warm_smooth = warm_progress * warm_progress * (3.0 - 2.0 * warm_progress);
            slot.phase_start = now - slot.phase_duration * warm_progress;
            slot.intensity = slot.peak_intensity * warm_smooth;
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
        let candidates: Vec<usize> = (0..SHADERS.len())
            .filter(|i| !current_types.contains(i) && !recently.contains(i))
            .collect();
        let candidates = if candidates.is_empty() {
            (0..SHADERS.len())
                .filter(|i| !current_types.contains(i))
                .collect::<Vec<_>>()
        } else {
            candidates
        };
        if candidates.is_empty() {
            self.slots[idx].needs_recycle = false;
            return;
        }

        let old_idx = self.slots[idx].shader_idx;
        let new_idx =
            candidates[(self.rng.next_f32() * candidates.len() as f32) as usize % candidates.len()];
        let def = &SHADERS[new_idx];

        self.slots[idx].shader_idx = new_idx;
        self.slots[idx].current_params = def
            .passthrough
            .iter()
            .map(|&(n, v)| (n.to_string(), v))
            .collect();
        self.slots[idx].intensity = 0.0;
        self.slots[idx].needs_recycle = false;
        self.slots[idx].rerise_after = self.slots[idx].idle_since + 2.0;
        self.recently_used.push_back(old_idx);
        if self.recently_used.len() > 18 {
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

        for (slot_idx, slot) in self.slots.iter_mut().enumerate() {
            let def = &SHADERS[slot.shader_idx];

            for (pi, &(pname, pt_val)) in def.passthrough.iter().enumerate() {
                let act_val = slot
                    .active_target
                    .iter()
                    .find(|(n, _)| n == pname)
                    .map(|(_, v)| *v)
                    .unwrap_or(pt_val);
                let span = (act_val - pt_val).abs();
                let mut interpolated = pt_val + (act_val - pt_val) * slot.intensity;

                if slot.intensity > 0.05 && span > 0.001 {
                    let phase_seed = (slot_idx * 17 + pi * 7) as f32 * 0.1;
                    let freq = 0.08 + 0.05 * ((slot_idx * 3 + pi * 11) % 7) as f32;
                    let sine = (now * freq + phase_seed).sin();
                    let mod_depth = if def.is_spatial { 0.10 } else { 0.30 };
                    interpolated += sine * mod_depth * span * slot.intensity;

                    let drift_scale = PARAM_DRIFT_RATE * if def.is_spatial { 0.3 } else { 1.0 };
                    // Use deterministic noise instead of gaussian for reproducibility
                    let noise = ((now * 1.7 + phase_seed * 3.1).sin() * 0.5) * drift_scale * span;
                    interpolated += noise;

                    let lo = pt_val.min(act_val);
                    let hi = pt_val.max(act_val);
                    interpolated = interpolated.clamp(lo, hi);
                }

                slot.current_params
                    .iter_mut()
                    .find(|(n, _)| n == pname)
                    .map(|(_, v)| *v = interpolated);
                uniforms.push((format!("{}.{}", def.name, pname), interpolated));
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

    fn write_plan(&self) {
        let mut passes = Vec::new();
        let mut prev_output = "@live".to_string();
        let plan_dir = Path::new(&self.plan_path)
            .parent()
            .unwrap_or_else(|| Path::new("."));

        for (i, slot) in self.slots.iter().enumerate() {
            let def = &SHADERS[slot.shader_idx];
            copy_shader_to_plan_dir(def, plan_dir);
            let layer = format!("layer_{}", i);
            let mut uniforms_map = serde_json::Map::new();
            let param_order: Vec<String> = def.param_order.iter().map(|s| s.to_string()).collect();
            let (inputs, temporal) = pass_inputs_for(def, &prev_output);

            for &(name, val) in def.passthrough.iter() {
                uniforms_map.insert(name.to_string(), serde_json::Value::from(val as f64));
            }

            let mut pass = serde_json::json!({
                "node_id": def.name,
                "shader": def.shader_file,
                "type": "render",
                "backend": "wgsl_render",
                "inputs": inputs,
                "output": layer,
                "uniforms": uniforms_map,
                "param_order": param_order,
            });
            if temporal {
                pass.as_object_mut()
                    .expect("effect pass is a JSON object")
                    .insert("temporal".to_string(), serde_json::Value::Bool(true));
            }
            passes.push(pass);
            prev_output = layer;
        }

        // Feedback bookend
        {
            copy_shader_to_plan_dir(&FEEDBACK_DEF, plan_dir);
            let layer = format!("layer_{}", self.slots.len());
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
            }));
        }

        let plan = serde_json::json!({
            "version": 2,
            "targets": { "main": { "passes": passes } }
        });

        let chain: Vec<&str> = self
            .slots
            .iter()
            .map(|s| SHADERS[s.shader_idx].name)
            .collect();
        log::warn!("SlotDrift: writing plan chain={:?}", chain);

        if let Err(e) = std::fs::write(
            Path::new(&self.plan_path),
            serde_json::to_string_pretty(&plan).unwrap(),
        ) {
            log::warn!("SlotDrift: plan write failed: {}", e);
        }
    }
}

fn copy_shader_to_plan_dir(def: &ShaderDef, plan_dir: &Path) {
    let src = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../agents/shaders/nodes")
        .join(def.shader_file);
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
