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
    var color: vec4<f32>;
    var center: vec2<f32> = vec2<f32>(0.5f, 0.5f);
    var dist: f32;
    var mask: f32;

    let _e8 = v_texcoord_1;
    let _e9 = textureSample(tex, tex_sampler, _e8);
    color = _e9;
    let _e15 = v_texcoord_1;
    let _e16 = center;
    dist = distance(_e15, _e16);
    let _e20 = global.u_radius;
    let _e21 = global.u_softness;
    let _e23 = global.u_radius;
    let _e24 = dist;
    mask = (1f - smoothstep((_e20 - _e21), _e23, _e24));
    let _e28 = color;
    let _e29 = _e28.xyz;
    let _e30 = color;
    let _e32 = mask;
    fragColor = vec4<f32>(_e29.x, _e29.y, _e29.z, (_e30.w * _e32));
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e15 = fragColor;
    return FragmentOutput(_e15);
}
