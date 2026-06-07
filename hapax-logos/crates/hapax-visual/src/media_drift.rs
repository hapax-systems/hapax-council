//! Screwm media-drift — GPU port of `scripts/quake_media_drift.py`.
//!
//! This module owns the CPU-side **drift contract**: it loads the 27 `DriftState`
//! scalars the engine writes to `data/*.txt` (the same files `load_drift_state`
//! reads in Python) and resolves a per-slot [`ReceiverClass`] (gain + damping).
//! The GPU pass (`media_drift.wgsl`) and the `screwm_media_drift` service bind to
//! these — the shader applies chroma-roll / feedback / edge / glitch / noise /
//! scanlines / tonal-pulse exactly as `apply_frame_drift` does, on the GPU.
//!
//! Reference (vocabulary, not a pixel oracle): `scripts/quake_media_drift.py`.

use std::path::Path;

/// Drift scalars mirroring `quake_media_drift.DriftState` (frozen dataclass).
/// Every field is clamped to `0.0..=1.0`, fallback `0.0`, read from the engine
/// `data/` directory. `source` (a string marker) is intentionally omitted — it
/// is not consumed by `apply_frame_drift`; `real_source` is the scalar used.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct DriftState {
    pub real_source: f32,
    pub active_ratio: f32,
    pub active_slot_ratio: f32,
    pub active_effect_ratio: f32,
    pub fast_ratio: f32,
    pub slow_ratio: f32,
    pub kind_variance: f32,
    pub max_delta: f32,
    pub region_count: f32,
    pub tonal: f32,
    pub atmospheric: f32,
    pub temporal: f32,
    pub texture: f32,
    pub edge: f32,
    pub compositing: f32,
    pub visual_noise: f32,
    pub visual_drift: f32,
    pub visual_color: f32,
    pub visual_feedback: f32,
    pub visual_aperture: f32,
    pub visual_param_pressure: f32,
    pub mode_tonal: f32,
    pub mode_atmospheric: f32,
    pub mode_temporal: f32,
    pub mode_texture: f32,
    pub mode_edge: f32,
    pub mode_compositing: f32,
}

impl DriftState {
    /// Base drift intensity, ported verbatim from `DriftState.intensity`
    /// (quake_media_drift.py:71-93). `mode_pressure` is the max of the six
    /// `mode_*` scalars. Result clamped `0.0..=1.0`.
    pub fn intensity(&self) -> f32 {
        let mode_pressure = self
            .mode_tonal
            .max(self.mode_atmospheric)
            .max(self.mode_temporal)
            .max(self.mode_texture)
            .max(self.mode_edge)
            .max(self.mode_compositing);
        clamp01(
            0.34 + self.active_ratio * 0.20
                + self.active_effect_ratio * 0.14
                + self.kind_variance * 0.14
                + self.visual_param_pressure * 0.14
                + self.visual_drift * 0.12
                + self.max_delta * 0.10
                + self.fast_ratio * 0.07
                + self.slow_ratio * 0.05
                + mode_pressure * 0.08
                + self.real_source * 0.06,
        )
    }
}

#[inline]
fn clamp01(v: f32) -> f32 {
    v.clamp(0.0, 1.0)
}

/// Read one `data/<name>` scalar, clamped `0.0..=1.0`, fallback on any error —
/// mirrors `_read_scalar`. The engine re-writes these files every frame.
fn read_scalar(game_data: &Path, name: &str, fallback: f32) -> f32 {
    match std::fs::read_to_string(game_data.join(name)) {
        Ok(text) => text.trim().parse::<f32>().map(clamp01).unwrap_or(fallback),
        Err(_) => fallback,
    }
}

/// Load the live `DriftState` from the engine `data/` dir. File names match
/// `load_drift_state` (quake_media_drift.py:96-126) exactly so the GPU pass
/// reads the same currency the Python producers did.
pub fn load_drift_state(game_data: &Path) -> DriftState {
    let s = |n: &str| read_scalar(game_data, n, 0.0);
    DriftState {
        real_source: s("effect-drift-real-source.txt"),
        active_ratio: s("effect-drift-active-ratio.txt"),
        active_slot_ratio: s("effect-drift-active-slot-ratio.txt"),
        active_effect_ratio: s("effect-drift-active-effect-ratio.txt"),
        fast_ratio: s("effect-drift-fast-ratio.txt"),
        slow_ratio: s("effect-drift-slow-ratio.txt"),
        kind_variance: s("effect-drift-kind-variance.txt"),
        max_delta: s("effect-drift-max-delta.txt"),
        region_count: s("effect-drift-region-count.txt"),
        tonal: s("effect-drift-tonal.txt"),
        atmospheric: s("effect-drift-atmospheric.txt"),
        temporal: s("effect-drift-temporal.txt"),
        texture: s("effect-drift-texture.txt"),
        edge: s("effect-drift-edge.txt"),
        compositing: s("effect-drift-compositing.txt"),
        visual_noise: s("visual-chain-noise.txt"),
        visual_drift: s("visual-chain-drift.txt"),
        visual_color: s("visual-chain-color.txt"),
        visual_feedback: s("visual-chain-feedback.txt"),
        visual_aperture: s("visual-chain-aperture.txt"),
        visual_param_pressure: s("visual-chain-param-pressure.txt"),
        mode_tonal: s("effect-drift-mode-tonal.txt"),
        mode_atmospheric: s("effect-drift-mode-atmospheric.txt"),
        mode_temporal: s("effect-drift-mode-temporal.txt"),
        mode_texture: s("effect-drift-mode-texture.txt"),
        mode_edge: s("effect-drift-mode-edge.txt"),
        mode_compositing: s("effect-drift-mode-compositing.txt"),
    }
}

/// Per-receiver drift character, mirroring `_receiver_gain` / `_receiver_is_camera`
/// / `_receiver_is_reverie` / `_receiver_min_chroma_px`. The shader branches on
/// `as_u32()`; cameras are damped, reverie gets the tonemap path.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReceiverClass {
    Camera,
    Oarb,
    Ticker,
    Atlas,
    Reverie,
    Other,
}

impl ReceiverClass {
    /// Classify by receiver name (case-insensitive substring), matching the
    /// Python helpers' precedence (oarb/youtube/yt -> ticker -> atlas/ward ->
    /// reverie -> direct IR BRIO/camera/cam).
    pub fn from_name(name: &str) -> Self {
        let n = name.to_lowercase();
        if n == "yt" || n.contains("oarb") || n.contains("youtube") {
            Self::Oarb
        } else if n.contains("ticker") {
            Self::Ticker
        } else if n.contains("atlas") || n.contains("ward") {
            Self::Atlas
        } else if n.contains("reverie") {
            Self::Reverie
        } else if n.starts_with("ir-brio-") || n.contains("camera") || n.contains("cam") {
            Self::Camera
        } else {
            Self::Other
        }
    }

    /// Drift gain (`_receiver_gain`).
    pub fn gain(self) -> f32 {
        match self {
            Self::Oarb => 1.52,
            Self::Ticker => 1.62,
            Self::Atlas => 1.66,
            Self::Reverie => 1.46,
            Self::Camera => 1.26,
            Self::Other => 1.0,
        }
    }

    /// Minimum chroma-shift floor in px (`_receiver_min_chroma_px`).
    pub fn min_chroma_px(self) -> u32 {
        match self {
            Self::Ticker => 6,
            Self::Camera => 16,
            Self::Oarb => 22,
            Self::Atlas | Self::Reverie => 18,
            Self::Other => 10,
        }
    }

    pub fn is_camera(self) -> bool {
        matches!(self, Self::Camera)
    }

    pub fn is_reverie(self) -> bool {
        matches!(self, Self::Reverie)
    }

    /// Stable code for the WGSL `receiver_class` uniform branch.
    pub fn as_u32(self) -> u32 {
        match self {
            Self::Camera => 0,
            Self::Oarb => 1,
            Self::Ticker => 2,
            Self::Atlas => 3,
            Self::Reverie => 4,
            Self::Other => 5,
        }
    }
}

/// GPU uniform mirroring `media_drift.wgsl`'s `DriftUniforms` (vec4-packed for
/// std140-safe 16-byte alignment; 176 bytes). The shader recomputes the derived
/// per-frame params (intensity, phase, chroma_px, …) from these raw scalars.
#[repr(C)]
#[derive(Clone, Copy, Debug, bytemuck::Pod, bytemuck::Zeroable)]
pub struct DriftUniforms {
    /// 28 slots: indices `[0,27)` are the 27 `DriftState` scalars in field order
    /// (matching the WGSL `I_*` index constants); slot `[27]` is unused padding.
    pub scalars: [[f32; 4]; 7],
    /// `(now, frame, intensity_scale, min_chroma_px)`.
    pub frame_meta: [f32; 4],
    /// `(receiver_class, width, height, _pad)`.
    pub slot_dims: [u32; 4],
    /// `(projection_code, raw_width, raw_height, _pad)`.
    pub projection: [u32; 4],
    /// `(background_r, background_g, background_b, _pad)`.
    pub projection_color: [f32; 4],
}

impl DriftUniforms {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        state: &DriftState,
        rc: ReceiverClass,
        now: f32,
        frame: f32,
        intensity_scale: f32,
        width: u32,
        height: u32,
        projection_code: u32,
        raw_width: u32,
        raw_height: u32,
        projection_background_rgb: [f32; 3],
    ) -> Self {
        // Field order MUST match the WGSL `I_*` constants and `DriftState`.
        let flat = [
            state.real_source,
            state.active_ratio,
            state.active_slot_ratio,
            state.active_effect_ratio,
            state.fast_ratio,
            state.slow_ratio,
            state.kind_variance,
            state.max_delta,
            state.region_count,
            state.tonal,
            state.atmospheric,
            state.temporal,
            state.texture,
            state.edge,
            state.compositing,
            state.visual_noise,
            state.visual_drift,
            state.visual_color,
            state.visual_feedback,
            state.visual_aperture,
            state.visual_param_pressure,
            state.mode_tonal,
            state.mode_atmospheric,
            state.mode_temporal,
            state.mode_texture,
            state.mode_edge,
            state.mode_compositing,
        ];
        let mut scalars = [[0.0f32; 4]; 7];
        for (i, v) in flat.iter().enumerate() {
            scalars[i / 4][i % 4] = *v;
        }
        Self {
            scalars,
            frame_meta: [now, frame, intensity_scale, rc.min_chroma_px() as f32],
            slot_dims: [rc.as_u32(), width, height, 0],
            projection: [projection_code, raw_width, raw_height, 0],
            projection_color: [
                projection_background_rgb[0],
                projection_background_rgb[1],
                projection_background_rgb[2],
                0.0,
            ],
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn load_reads_scalars_clamped_with_fallback() {
        let dir = tempdir().unwrap();
        let p = dir.path();
        fs::write(p.join("effect-drift-fast-ratio.txt"), "0.5").unwrap();
        fs::write(p.join("effect-drift-edge.txt"), "1.7").unwrap(); // clamps to 1.0
        fs::write(p.join("visual-chain-noise.txt"), "garbage").unwrap(); // -> 0.0
                                                                         // effect-drift-tonal.txt absent -> fallback 0.0
        let s = load_drift_state(p);
        assert_eq!(s.fast_ratio, 0.5);
        assert_eq!(s.edge, 1.0);
        assert_eq!(s.visual_noise, 0.0);
        assert_eq!(s.tonal, 0.0);
    }

    #[test]
    fn intensity_floor_and_scaling() {
        // All-zero state -> the 0.34 floor.
        assert!((DriftState::default().intensity() - 0.34).abs() < 1e-6);
        // active_ratio drives it up by 0.20.
        let s = DriftState {
            active_ratio: 1.0,
            ..Default::default()
        };
        assert!((s.intensity() - 0.54).abs() < 1e-6);
    }

    #[test]
    fn receiver_class_matches_python_precedence() {
        assert_eq!(ReceiverClass::from_name("oarb_sphere"), ReceiverClass::Oarb);
        assert_eq!(ReceiverClass::from_name("yt"), ReceiverClass::Oarb);
        assert_eq!(ReceiverClass::from_name("cam_bop"), ReceiverClass::Camera);
        assert_eq!(
            ReceiverClass::from_name("ir-brio-operator"),
            ReceiverClass::Camera
        );
        assert_eq!(ReceiverClass::from_name("ward_atlas"), ReceiverClass::Atlas);
        assert_eq!(
            ReceiverClass::from_name("brio-operator-ir-ward"),
            ReceiverClass::Atlas
        );
        assert_eq!(
            ReceiverClass::from_name("ticker-grounding"),
            ReceiverClass::Ticker
        );
        assert_eq!(ReceiverClass::from_name("reverie"), ReceiverClass::Reverie);
        assert!(ReceiverClass::Camera.is_camera());
        assert_eq!(ReceiverClass::Oarb.gain(), 1.52);
    }

    #[test]
    fn drift_uniforms_layout_matches_wgsl_indices() {
        assert_eq!(std::mem::size_of::<DriftUniforms>(), 176);
        let st = DriftState {
            real_source: 0.1,
            fast_ratio: 0.5,
            mode_compositing: 0.9,
            ..Default::default()
        };
        let u = DriftUniforms::new(
            &st,
            ReceiverClass::Atlas,
            2.0,
            7.0,
            1.0,
            1280,
            720,
            1,
            960,
            540,
            [0.1, 0.2, 0.3],
        );
        // I_REAL_SOURCE=0 -> scalars[0][0]; I_FAST_RATIO=4 -> scalars[1][0];
        // I_MODE_COMPOSITING=26 -> scalars[6][2].
        assert_eq!(u.scalars[0][0], 0.1);
        assert_eq!(u.scalars[1][0], 0.5);
        assert_eq!(u.scalars[6][2], 0.9);
        assert_eq!(
            u.frame_meta,
            [2.0, 7.0, 1.0, ReceiverClass::Atlas.min_chroma_px() as f32]
        );
        assert_eq!(u.slot_dims, [ReceiverClass::Atlas.as_u32(), 1280, 720, 0]);
        assert_eq!(u.projection, [1, 960, 540, 0]);
        assert_eq!(u.projection_color, [0.1, 0.2, 0.3, 0.0]);
    }

    /// Static-validate the drift shader (catches WGSL syntax/type errors without
    /// a GPU). Path mirrors gpu.rs::shader_nodes_dir (`../../../agents/shaders/nodes`).
    #[test]
    fn media_drift_wgsl_parses_and_validates() {
        let src = include_str!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../../agents/shaders/nodes/media_drift.wgsl"
        ));
        let module = naga::front::wgsl::parse_str(src).expect("media_drift.wgsl should parse");
        let mut validator = naga::valid::Validator::new(
            naga::valid::ValidationFlags::all(),
            naga::valid::Capabilities::all(),
        );
        validator
            .validate(&module)
            .expect("media_drift.wgsl should validate");
    }
}
