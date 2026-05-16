struct Params {
    u_threshold: f32,
    u_softness: f32,
    u_invert: f32,
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
@group(1) @binding(2)
var tex_b: texture_2d<f32>;
@group(1) @binding(3)
var tex_b_sampler: sampler;
@group(2) @binding(0)
var<uniform> global: Params;

fn main_1() {
    let uv = v_texcoord_1;
    let a = textureSample(tex, tex_sampler, uv);
    let b = textureSample(tex_b, tex_b_sampler, uv);
    let b_luma = dot(b.xyz, vec3<f32>(0.299, 0.587, 0.114));
    var key = smoothstep(global.u_threshold - global.u_softness, global.u_threshold + global.u_softness, b_luma);
    if global.u_invert > 0.5 {
        key = 1.0 - key;
    }
    let a_luma = dot(a.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.008, 0.09, a_luma);
    let strength = key * surface_presence * 0.24;
    fragColor = vec4<f32>(mix(a.xyz, b.xyz, vec3<f32>(strength)), a.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
