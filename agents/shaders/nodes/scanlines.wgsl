struct Params {
    u_opacity: f32,
    u_spacing: f32,
    u_thickness: f32,
    u_height: f32,
}

struct FragmentOutput {
    @location(0) fragColor: vec4<f32>,
}

var<private> fragColor: vec4<f32>;
var<private> v_texcoord_1: vec2<f32>;
@group(0) @binding(0) 
var tex: texture_2d<f32>;
@group(0) @binding(1) 
var tex_sampler: sampler;
@group(1) @binding(0) 
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
    let _e20 = global.u_height;
    let _e21 = (_e18.y * _e20);
    let _e22 = global.u_spacing;
    line = step((_e15 - _e16), (_e21 - (floor((_e21 / _e22)) * _e22)));
    let _e29 = c;
    let _e31 = c;
    let _e34 = line;
    let _e35 = global.u_opacity;
    let _e38 = (_e31.xyz * (1f - (_e34 * _e35)));
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
