struct Params {
    u_zoom_speed: f32,
    u_spiral: f32,
    u_center_x: f32,
    u_center_y: f32,
    u_branches: f32,
    u_time: f32,
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
    var center: vec2<f32>;
    var uv: vec2<f32>;
    var r: f32;
    var theta: f32;
    var logr: f32;
    var n: f32;
    var p: f32;
    var t: f32;
    var angle: f32;
    var scale: f32;
    var nuv: vec2<f32>;

    let _e16 = global.u_center_x;
    let _e17 = global.u_center_y;
    center = vec2<f32>(_e16, _e17);
    let _e20 = v_texcoord_1;
    let _e21 = center;
    uv = (_e20 - _e21);
    let _e24 = uv;
    r = length(_e24);
    let _e27 = uv;
    let _e29 = uv;
    theta = atan2(_e27.y, _e29.x);
    let _e33 = r;
    logr = log(max(_e33, 0.0001f));
    let _e38 = global.u_branches;
    n = _e38;
    let _e40 = global.u_spiral;
    p = _e40;
    let _e42 = global.u_time;
    let _e43 = global.u_zoom_speed;
    t = (_e42 * _e43);
    let _e46 = theta;
    let _e47 = p;
    let _e48 = logr;
    let _e51 = t;
    angle = ((_e46 + (_e47 * _e48)) - _e51);
    let _e54 = logr;
    let _e55 = t;
    let _e58 = (_e54 - (_e55 * 0.5f));
    scale = exp(((_e58 - (floor((_e58 / 0.6931472f)) * 0.6931472f)) - 0.6931472f));
    let _e70 = angle;
    let _e72 = n;
    let _e73 = (6.28318f / _e72);
    angle = (_e70 - (floor((_e70 / _e73)) * _e73));
    let _e78 = angle;
    let _e80 = angle;
    let _e83 = scale;
    let _e85 = center;
    nuv = ((vec2<f32>(cos(_e78), sin(_e80)) * _e83) + _e85);
    let _e88 = nuv;
    nuv = fract(_e88);
    let _e90 = nuv;
    let _e91 = textureSample(tex, tex_sampler, _e90);
    fragColor = _e91;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e23 = fragColor;
    return FragmentOutput(_e23);
}
