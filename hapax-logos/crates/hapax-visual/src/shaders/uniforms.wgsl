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
    diffusion: f32,
    // Padding to align slot_opacities to 16-byte boundary (std140 vec4 alignment).
    align_pad0: f32,
    align_pad1: f32,
    // Content layer
    slot_opacities: vec4<f32>,
    // Per-node custom params (32 floats packed as 8 vec4s for uniform alignment)
    custom: array<vec4<f32>, 8>,
};

@group(0) @binding(0)
var<uniform> uniforms: Uniforms;
