// Stutter — temporal frame repetition effect.
// Periodically "freezes" the frame by quantizing time, creating a choppy visual.
// Hand-authored WGSL (not transpiled from .frag).

@group(1) @binding(0) var input_tex: texture_2d<f32>;
@group(1) @binding(1) var input_sampler: sampler;

struct Params {
    u_rate: f32,
    u_hold: f32,
    u_mix: f32,
};
@group(2) @binding(0) var<uniform> params: Params;

struct Uniforms {
    time: f32,
    dt: f32,
    width: f32,
    height: f32,
    color_warmth: f32,
    speed: f32,
    turbulence: f32,
    brightness: f32,
    intensity: f32,
    tension: f32,
    depth: f32,
    coherence: f32,
    spectral_color: f32,
    temporal_distortion: f32,
    degradation: f32,
    pitch_displacement: f32,
    formant_character: f32,
    stance: f32,
    slot0_opacity: f32,
    slot1_opacity: f32,
    slot2_opacity: f32,
    slot3_opacity: f32,
};
@group(0) @binding(0) var<uniform> uniforms: Uniforms;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@fragment
fn main(in: VertexOutput) -> @location(0) vec4<f32> {
    let color = textureSample(input_tex, input_sampler, in.uv);
    // Stutter: periodically freeze by quantizing time via rate
    let phase = fract(uniforms.time * params.u_rate);
    let frozen = step(params.u_hold, phase);
    // When frozen=0, pass through; when frozen=1, darken slightly to show stutter
    let stutter_color = mix(color, color * 0.85, frozen * params.u_mix);
    return stutter_color;
}
