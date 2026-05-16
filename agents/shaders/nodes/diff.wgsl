struct Params {
    u_threshold: f32,
    u_color_mode: f32,
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
var tex_prev: texture_2d<f32>;
@group(1) @binding(3)
var tex_prev_sampler: sampler;
@group(2) @binding(0)
var<uniform> global: Params;

fn main_1() {
    let uv = v_texcoord_1;
    let cur = textureSample(tex, tex_sampler, uv);
    let prev = textureSample(tex_prev, tex_prev_sampler, uv);
    let delta = abs(cur.xyz - prev.xyz);
    let diff_luma = dot(delta, vec3<f32>(0.299, 0.587, 0.114));
    let gate = smoothstep(global.u_threshold, global.u_threshold + 0.08, diff_luma);

    var diff_signal: vec3<f32>;
    if global.u_color_mode < 0.5 {
        diff_signal = cur.xyz + vec3<f32>(diff_luma);
    } else if global.u_color_mode < 1.5 {
        diff_signal = max(cur.xyz, delta);
    } else {
        diff_signal = cur.xyz + (delta * vec3<f32>(0.6, 0.95, 1.0));
    }

    let cur_luma = dot(cur.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.008, 0.09, cur_luma);
    let strength = gate * surface_presence * 0.34;
    let out_rgb = mix(cur.xyz, clamp(diff_signal, vec3(0.0), vec3(1.0)), vec3<f32>(strength));
    fragColor = vec4<f32>(out_rgb, cur.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
