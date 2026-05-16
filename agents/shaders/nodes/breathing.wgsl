struct Params {
    u_rate: f32,
    u_amplitude: f32,
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
    let center = vec2<f32>(0.5, 0.5);
    let phase = sin(uniforms.time * clamp(global.u_rate, 0.05, 0.75) * 6.2831853);
    let scale = 1.0 + (phase * clamp(global.u_amplitude, 0.0, 0.026));
    let uv = ((v_texcoord_1 - center) / vec2<f32>(scale)) + center;
    let source = textureSample(tex, tex_sampler, v_texcoord_1);
    let warped = textureSample(tex, tex_sampler, clamp(uv, vec2(0.0), vec2(1.0)));
    let luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.008, 0.09, luma);
    let strength = surface_presence * clamp(abs(phase) * global.u_amplitude * 9.5, 0.0, 0.18);
    fragColor = vec4<f32>(mix(source.xyz, warped.xyz, vec3<f32>(strength)), source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
