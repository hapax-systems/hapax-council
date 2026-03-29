struct Params {
    u_angle: f32,
    u_strength: f32,
    u_blend: f32,
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
    var texel: vec2<f32>;
    var c: f32;
    var s: f32;
    var dir: vec2<f32>;
    var color: vec4<f32>;
    var s1_: vec4<f32>;
    var s2_: vec4<f32>;
    var embossed: vec3<f32>;

    texel = vec2<f32>((1f / uniforms.resolution.x), (1f / uniforms.resolution.y));
    let _e22 = global.u_angle;
    c = cos(_e22);
    let _e25 = global.u_angle;
    s = sin(_e25);
    let _e28 = c;
    let _e29 = s;
    let _e31 = texel;
    dir = (vec2<f32>(_e28, _e29) * _e31);
    let _e34 = v_texcoord_1;
    let _e35 = textureSample(tex, tex_sampler, _e34);
    color = _e35;
    let _e37 = v_texcoord_1;
    let _e38 = dir;
    let _e40 = textureSample(tex, tex_sampler, (_e37 + _e38));
    s1_ = _e40;
    let _e42 = v_texcoord_1;
    let _e43 = dir;
    let _e45 = textureSample(tex, tex_sampler, (_e42 - _e43));
    s2_ = _e45;
    let _e47 = s1_;
    let _e49 = s2_;
    let _e52 = global.u_strength;
    embossed = (((_e47.xyz - _e49.xyz) * _e52) + vec3(0.5f));
    let _e58 = color;
    let _e60 = embossed;
    let _e61 = global.u_blend;
    let _e63 = mix(_e58.xyz, _e60, vec3(_e61));
    let _e64 = color;
    fragColor = vec4<f32>(_e63.x, _e63.y, _e63.z, _e64.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
