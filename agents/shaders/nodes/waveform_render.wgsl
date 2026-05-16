struct Params {
    u_shape: f32,
    u_thickness: f32,
    u_color_r: f32,
    u_color_g: f32,
    u_color_b: f32,
    u_color_a: f32,
    u_scale: f32,
}

struct FragmentOutput {
    @location(0) fragColor: vec4<f32>,
}

var<private> fragColor: vec4<f32>;
var<private> v_texcoord_1: vec2<f32>;
@group(1) @binding(0)
var tex: texture_2d<f32>;
@group(1) @binding(1)
var tex_sampler: sampler;
@group(2) @binding(0)
var<uniform> global: Params;

fn main_1() {
    let uv0 = v_texcoord_1;
    let source = textureSample(tex, tex_sampler, uv0);
    let uv = (uv0 * 2.0) - vec2<f32>(1.0);
    let radius = length(uv);
    let angle = atan2(uv.y, uv.x);
    var wave = 0.0;
    for (var i = 0; i < 8; i = i + 1) {
        let fi = f32(i);
        let freq = 3.0 + (fi * 2.0);
        let phase = uniforms.time * (0.35 + (fi * 0.08));
        wave = wave + ((sin((angle * freq) + phase) * 0.01) / (1.0 + (fi * 0.5)));
    }

    let ring = abs((radius - clamp(global.u_scale, 0.35, 0.8)) + wave);
    let px = 0.002 * clamp(global.u_thickness, 0.7, 2.5);
    let alpha = clamp((1.0 - smoothstep(0.0, px, ring)) + (exp((-ring * 80.0) / max(global.u_thickness, 0.7)) * 0.22), 0.0, 1.0);
    let color = vec3<f32>(global.u_color_r, global.u_color_g, global.u_color_b);
    let source_luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.025, 0.14, source_luma);
    let strength = alpha * surface_presence * clamp(global.u_color_a, 0.0, 0.16);
    fragColor = vec4<f32>(mix(source.xyz, color, vec3<f32>(strength)), source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
