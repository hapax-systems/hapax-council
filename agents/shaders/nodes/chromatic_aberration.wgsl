struct Params {
    u_offset_x: f32,
    u_offset_y: f32,
    u_intensity: f32,
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
    var uv: vec2<f32>;
    var offset: vec2<f32>;
    var r: f32;
    var g: f32;
    var b: f32;
    var a: f32;

    let _e10 = v_texcoord_1;
    uv = _e10;
    let _e12 = global.u_offset_x;
    let _e13 = global.u_offset_y;
    let _e15 = global.u_intensity;
    offset = ((vec2<f32>(_e12, _e13) * _e15) * 0.01f);
    let _e20 = uv;
    let _e21 = offset;
    let _e23 = textureSample(tex, tex_sampler, (_e20 + _e21));
    r = _e23.x;
    let _e26 = uv;
    let _e27 = textureSample(tex, tex_sampler, _e26);
    g = _e27.y;
    let _e30 = uv;
    let _e31 = offset;
    let _e33 = textureSample(tex, tex_sampler, (_e30 - _e31));
    b = _e33.z;
    let _e36 = uv;
    let _e37 = textureSample(tex, tex_sampler, _e36);
    a = _e37.w;
    let _e40 = r;
    let _e41 = g;
    let _e42 = b;
    let _e43 = a;
    fragColor = vec4<f32>(_e40, _e41, _e42, _e43);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e17 = fragColor;
    return FragmentOutput(_e17);
}
