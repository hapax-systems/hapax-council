struct Params {
    u_strength: f32,
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
    var c: vec4<f32>;
    var d: f32;

    let _e10 = v_texcoord_1;
    let _e11 = textureSample(tex, tex_sampler, _e10);
    c = _e11;
    let _e13 = v_texcoord_1;
    d = (length((_e13 - vec2(0.5f))) * 2f);
    let _e21 = c;
    let _e23 = c;
    let _e26 = global.u_radius;
    let _e27 = global.u_radius;
    let _e28 = global.u_softness;
    let _e30 = d;
    let _e32 = global.u_strength;
    let _e35 = (_e23.xyz * (1f - (smoothstep(_e26, (_e27 + _e28), _e30) * _e32)));
    c.x = _e35.x;
    c.y = _e35.y;
    c.z = _e35.z;
    let _e42 = c;
    fragColor = _e42;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e17 = fragColor;
    return FragmentOutput(_e17);
}
