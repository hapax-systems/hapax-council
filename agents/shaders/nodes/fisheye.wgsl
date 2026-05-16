struct Params {
    u_strength: f32,
    u_center_x: f32,
    u_center_y: f32,
    u_zoom: f32,
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
    var original: vec4<f32>;
    var center: vec2<f32>;
    var uv: vec2<f32>;
    var r: f32;
    var theta: f32;
    var rd: f32;
    var distorted: vec2<f32>;
    var warped: vec4<f32>;
    var blend: f32;

    original = textureSample(tex, tex_sampler, v_texcoord_1);
    let _e12 = global.u_center_x;
    let _e13 = global.u_center_y;
    center = vec2<f32>(_e12, _e13);
    let _e16 = v_texcoord_1;
    let _e17 = center;
    uv = (_e16 - _e17);
    let _e20 = uv;
    r = length(_e20);
    let _e23 = uv;
    let _e25 = uv;
    theta = atan2(_e23.y, _e25.x);
    let _e29 = r;
    let _e31 = global.u_strength;
    let _e32 = r;
    let _e34 = r;
    rd = (_e29 * (1f + ((_e31 * _e32) * _e34)));
    let _e39 = center;
    let _e40 = rd;
    let _e41 = theta;
    let _e43 = theta;
    let _e47 = global.u_zoom;
    distorted = (_e39 + ((_e40 * vec2<f32>(cos(_e41), sin(_e43))) / vec2(_e47)));
    distorted = clamp(distorted, vec2(0.001f), vec2(0.999f));
    let _e76 = distorted;
    let _e77 = textureSample(tex, tex_sampler, _e76);
    warped = _e77;
    blend = clamp(abs(global.u_strength) * 1.1f, 0.0f, 0.58f);
    fragColor = vec4<f32>(mix(original.xyz, warped.xyz, vec3(blend)), original.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
