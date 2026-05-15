struct Params {
    u_pos_x: f32,
    u_pos_y: f32,
    u_scale_x: f32,
    u_scale_y: f32,
    u_rotation: f32,
    u_pivot_x: f32,
    u_pivot_y: f32,
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
    var pivot: vec2<f32>;
    var uv: vec2<f32>;
    var original: vec4<f32>;
    var transformed: vec4<f32>;
    var blend: f32;
    var c: f32;
    var s: f32;

    original = textureSample(tex, tex_sampler, v_texcoord_1);
    let _e18 = global.u_pivot_x;
    let _e19 = global.u_pivot_y;
    pivot = vec2<f32>(_e18, _e19);
    let _e22 = v_texcoord_1;
    let _e23 = pivot;
    uv = (_e22 - _e23);
    let _e26 = global.u_rotation;
    c = cos(_e26);
    let _e29 = global.u_rotation;
    s = sin(_e29);
    let _e32 = c;
    let _e33 = s;
    let _e34 = s;
    let _e36 = c;
    let _e40 = uv;
    uv = (mat2x2<f32>(vec2<f32>(_e32, _e33), vec2<f32>(-(_e34), _e36)) * _e40);
    let _e42 = uv;
    let _e43 = global.u_scale_x;
    let _e44 = global.u_scale_y;
    uv = (_e42 / vec2<f32>(_e43, _e44));
    let _e47 = uv;
    let _e48 = global.u_pos_x;
    let _e49 = global.u_pos_y;
    uv = (_e47 - vec2<f32>(_e48, _e49));
    let _e52 = uv;
    let _e53 = pivot;
    uv = (_e52 + _e53);
    uv = clamp(uv, vec2(0.001f), vec2(0.999f));
    let _e79 = uv;
    let _e80 = textureSample(tex, tex_sampler, _e79);
    transformed = _e80;
    blend = clamp(
        (abs(global.u_pos_x) * 12.0f) +
        (abs(global.u_pos_y) * 12.0f) +
        (abs(global.u_scale_x - 1.0f) * 5.0f) +
        (abs(global.u_scale_y - 1.0f) * 5.0f) +
        (abs(global.u_rotation) * 6.0f),
        0.0f,
        0.22f,
    );
    fragColor = vec4<f32>(mix(original.xyz, transformed.xyz, vec3(blend)), original.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e25 = fragColor;
    return FragmentOutput(_e25);
}
