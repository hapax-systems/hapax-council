struct Params {
    u_opacity: f32,
    u_spacing: f32,
    u_thickness: f32,
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
    var c: vec4<f32>;
    var line: f32;

    let _e12 = v_texcoord_1;
    let _e13 = textureSample(tex, tex_sampler, _e12);
    c = _e13;
    let _e15 = global.u_spacing;
    let _e16 = global.u_thickness;
    let _e18 = v_texcoord_1;

    let _e21 = (_e18.y * uniforms.resolution.y);
    let _e22 = global.u_spacing;
    let spacing = max(_e15, 3.0);
    let thickness = clamp(_e16, 0.25, 1.1);
    let phase = _e21 - (floor(_e21 / spacing) * spacing);
    line = 1.0 - smoothstep(thickness * 0.35, thickness, phase);
    let _e29 = c;
    let _e31 = c;
    let _e34 = line;
    let _e35 = min(global.u_opacity, 0.055);
    let surface_presence = smoothstep(0.025, 0.20, dot(_e31.xyz, vec3<f32>(0.299, 0.587, 0.114)));
    let _e38 = (_e31.xyz * (1f - (_e34 * _e35 * surface_presence)));
    c.x = _e38.x;
    c.y = _e38.y;
    c.z = _e38.z;
    let _e45 = c;
    fragColor = _e45;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
