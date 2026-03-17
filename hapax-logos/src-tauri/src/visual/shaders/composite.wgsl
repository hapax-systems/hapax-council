// 6-layer compositor
// L0: gradient (base), L1: voronoi (multiply), L2: R-D (screen),
// L3: wave (multiplicative), L4: physarum (additive), L5: feedback (soft-light)

struct CompositeUniforms {
    opacity_gradient: f32,
    opacity_voronoi: f32,
    opacity_rd: f32,
    opacity_wave: f32,
    opacity_physarum: f32,
    opacity_feedback: f32,
    _pad0: f32,
    _pad1: f32,
}

@group(0) @binding(0) var<uniform> u: CompositeUniforms;
@group(0) @binding(1) var tex_gradient: texture_2d<f32>;
@group(0) @binding(2) var tex_rd: texture_2d<f32>;
@group(0) @binding(3) var tex_voronoi: texture_2d<f32>;
@group(0) @binding(4) var tex_wave: texture_2d<f32>;
@group(0) @binding(5) var tex_physarum: texture_2d<f32>;
@group(0) @binding(6) var tex_feedback: texture_2d<f32>;
@group(0) @binding(7) var samp: sampler;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
}

@vertex
fn vs_main(@builtin(vertex_index) idx: u32) -> VertexOutput {
    var out: VertexOutput;
    let x = f32(i32(idx & 1u)) * 4.0 - 1.0;
    let y = f32(i32(idx >> 1u)) * 4.0 - 1.0;
    out.position = vec4<f32>(x, y, 0.0, 1.0);
    out.uv = vec2<f32>((x + 1.0) * 0.5, (1.0 - y) * 0.5);
    return out;
}

fn blend_screen(base: vec3<f32>, layer: vec3<f32>) -> vec3<f32> {
    return 1.0 - (1.0 - base) * (1.0 - layer);
}

fn blend_multiply(base: vec3<f32>, layer: vec3<f32>) -> vec3<f32> {
    return base * layer;
}

fn blend_soft_light(base: vec3<f32>, layer: vec3<f32>) -> vec3<f32> {
    // Pegtop soft light formula
    return (1.0 - 2.0 * layer) * base * base + 2.0 * layer * base;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let uv = in.uv;

    // L0: Gradient (base layer)
    var color = textureSample(tex_gradient, samp, uv).rgb;

    // L1: Voronoi (multiply blend)
    let voronoi = textureSample(tex_voronoi, samp, uv).rgb;
    color = mix(color, blend_multiply(color, voronoi), u.opacity_voronoi);

    // L2: Reaction-diffusion (screen blend)
    let rd_raw = textureSample(tex_rd, samp, uv);
    let rd_vis = vec3<f32>(rd_raw.y * 0.8, rd_raw.y * 0.6, rd_raw.y * 1.0);
    color = mix(color, blend_screen(color, rd_vis), u.opacity_rd);

    // L3: Wave (multiplicative modulation)
    let wave_val = textureSample(tex_wave, samp, uv).x;
    let wave_mod = 1.0 + wave_val * u.opacity_wave;
    color = color * clamp(wave_mod, 0.5, 1.5);

    // L4: Physarum (additive blend)
    let physarum_val = textureSample(tex_physarum, samp, uv).x;
    let physarum_color = vec3<f32>(physarum_val * 0.6, physarum_val * 0.8, physarum_val * 1.0);
    color = color + physarum_color * u.opacity_physarum;

    // L5: Feedback (soft-light blend)
    let feedback = textureSample(tex_feedback, samp, uv).rgb;
    color = mix(color, blend_soft_light(color, feedback), u.opacity_feedback);

    return vec4<f32>(clamp(color, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0);
}
