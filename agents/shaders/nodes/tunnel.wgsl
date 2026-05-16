struct Params {
    u_speed: f32,
    u_twist: f32,
    u_radius: f32,
    u_distortion: f32,
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
    let centered = uv0 - vec2<f32>(0.5);
    let radius = length(centered);
    let angle = atan2(centered.y, centered.x);
    let tunnel_r = (clamp(global.u_radius, 0.08, 0.24) / (radius + 0.001)) + (uniforms.time * clamp(global.u_speed, 0.0, 0.62));
    var tunnel_a = (angle / 3.1415927) + (clamp(global.u_twist, 0.0, 1.15) * tunnel_r * 0.1);
    tunnel_a = tunnel_a + (sin(tunnel_r * clamp(global.u_distortion, 0.0, 4.8)) * 0.075);
    let tunnel_uv = fract(vec2<f32>(tunnel_a, tunnel_r));
    let tunnel = textureSample(tex, tex_sampler, tunnel_uv);
    let source_luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence = smoothstep(0.025, 0.14, source_luma);
    let geometry_presence = max(surface_presence, 0.22);
    let edge_weight = smoothstep(0.08, 0.44, radius);
    let strength = geometry_presence * edge_weight * clamp(global.u_speed + (global.u_twist * 0.30), 0.0, 0.58);
    fragColor = vec4<f32>(mix(source.xyz, tunnel.xyz, vec3<f32>(strength)), source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
