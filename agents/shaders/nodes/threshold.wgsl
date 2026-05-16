struct Params {
    u_level: f32,
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
@group(2) @binding(0)
var<uniform> global: Params;

fn main_1() {
    let source = textureSample(tex, tex_sampler, v_texcoord_1);
    let lum = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let edge = max(global.u_softness * 0.5, 0.04);
    let t = smoothstep(global.u_level - edge, global.u_level + edge, lum);
    let threshold_signal = mix(source.xyz, max(source.xyz, vec3<f32>(t) * 0.92), vec3<f32>(0.65));
    let surface_presence =         smoothstep(0.025, 0.14, lum);
    let strength = surface_presence * clamp(global.u_softness, 0.0, 0.18);
    let candidate = mix(source.xyz, threshold_signal, vec3<f32>(strength));
    let candidate_luma = dot(candidate.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let luma_deficit = max(lum - candidate_luma, 0.0);
    fragColor = vec4<f32>(max(source.xyz, candidate + vec3<f32>(luma_deficit)), source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
