struct Params {
    u_radius: f32,
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
    let uv = v_texcoord_1;
    let color = textureSample(tex, tex_sampler, uv);
    let dist = distance(uv, vec2<f32>(0.5, 0.5));
    let focus = 1.0 - smoothstep(global.u_radius - global.u_softness, global.u_radius, dist);
    let luma = dot(color.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.025, 0.14, luma);
    let edge_signal = clamp(color.xyz + vec3<f32>(0.12, 0.04, 0.18) * (1.0 - focus), vec3(0.0), vec3(1.0));
    let edge_tint = mix(edge_signal, color.xyz, vec3<f32>(focus));
    let strength = surface_presence * clamp((1.0 - global.u_radius) * 0.55, 0.0, 0.28);
    let out_rgb = mix(color.xyz, edge_tint, vec3<f32>(strength));
    fragColor = vec4<f32>(out_rgb, color.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
