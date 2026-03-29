struct Params {
    u_key_r: f32,
    u_key_g: f32,
    u_key_b: f32,
    u_tolerance: f32,
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
@group(1) @binding(2) 
var tex_b: texture_2d<f32>;
@group(1) @binding(3) 
var tex_b_sampler: sampler;
@group(2) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var a: vec4<f32>;
    var b: vec4<f32>;
    var key_color: vec3<f32>;
    var dist: f32;
    var mask: f32;

    let _e16 = v_texcoord_1;
    let _e17 = textureSample(tex, tex_sampler, _e16);
    a = _e17;
    let _e19 = v_texcoord_1;
    let _e20 = textureSample(tex_b, tex_b_sampler, _e19);
    b = _e20;
    let _e22 = global.u_key_r;
    let _e23 = global.u_key_g;
    let _e24 = global.u_key_b;
    key_color = vec3<f32>(_e22, _e23, _e24);
    let _e27 = b;
    let _e29 = key_color;
    dist = distance(_e27.xyz, _e29);
    let _e32 = global.u_tolerance;
    let _e33 = global.u_softness;
    let _e35 = global.u_tolerance;
    let _e36 = global.u_softness;
    let _e38 = dist;
    mask = smoothstep((_e32 - _e33), (_e35 + _e36), _e38);
    let _e41 = a;
    let _e43 = b;
    let _e45 = mask;
    let _e47 = mix(_e41.xyz, _e43.xyz, vec3(_e45));
    fragColor = vec4<f32>(_e47.x, _e47.y, _e47.z, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e25 = fragColor;
    return FragmentOutput(_e25);
}
