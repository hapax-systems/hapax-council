struct Params {
    u_threshold: f32,
    u_softness: f32,
    u_invert: f32,
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
@group(1) @binding(2) 
var tex_b: texture_2d<f32>;
@group(1) @binding(3) 
var tex_b_sampler: sampler;
@group(2) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var a: vec4<f32>;
    var b: vec4<f32>;
    var luma: f32;
    var key: f32;

    let _e12 = v_texcoord_1;
    let _e13 = textureSample(tex, tex_sampler, _e12);
    a = _e13;
    let _e15 = v_texcoord_1;
    let _e16 = textureSample(tex_b, tex_b_sampler, _e15);
    b = _e16;
    let _e18 = b;
    luma = dot(_e18.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e26 = global.u_threshold;
    let _e27 = global.u_softness;
    let _e29 = global.u_threshold;
    let _e30 = global.u_softness;
    let _e32 = luma;
    key = smoothstep((_e26 - _e27), (_e29 + _e30), _e32);
    let _e35 = global.u_invert;
    if (_e35 > 0.5f) {
        let _e39 = key;
        key = (1f - _e39);
    }
    let _e41 = a;
    let _e43 = b;
    let _e45 = key;
    let _e47 = mix(_e41.xyz, _e43.xyz, vec3(_e45));
    fragColor = vec4<f32>(_e47.x, _e47.y, _e47.z, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
