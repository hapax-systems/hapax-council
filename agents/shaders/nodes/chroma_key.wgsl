struct Params {
    u_key_r: f32,
    u_key_g: f32,
    u_key_b: f32,
    u_tolerance: f32,
    u_softness: f32,
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
    let key_color = vec3<f32>(global.u_key_r, global.u_key_g, global.u_key_b);
    let dist = distance(b.xyz, key_color);
    let mask = smoothstep(global.u_tolerance - global.u_softness, global.u_tolerance + global.u_softness, dist);
    let luma = dot(a.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.025, 0.14, luma);
    let strength = mask * surface_presence * clamp(global.u_tolerance, 0.0, 0.28);
    let out_rgb = mix(a.xyz, b.xyz, vec3<f32>(strength));
    fragColor = vec4<f32>(out_rgb, a.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
