struct Uniforms {
    time: f32,
    dt: f32,
    resolution: vec2<f32>,
    // Stimmung
    stance: u32,
    color_warmth: f32,
    speed: f32,
    turbulence: f32,
    brightness: f32,
    // 9 expressive dimensions
    intensity: f32,
    tension: f32,
    depth: f32,
    coherence: f32,
    spectral_color: f32,
    temporal_distortion: f32,
    degradation: f32,
    pitch_displacement: f32,
    formant_character: f32,
    // Content layer
    slot_opacities: vec4<f32>,
    // Per-node custom params (32 floats)
    custom: array<f32, 32>,
};

@group(0) @binding(0)
var<uniform> uniforms: Uniforms;
