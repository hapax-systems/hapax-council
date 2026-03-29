struct Params {
    u_level: f32,
    u_softness: f32,
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
    var color: vec4<f32>;
    var lum: f32;
    var edge: f32;
    var t: f32;

    let _e8 = v_texcoord_1;
    let _e9 = textureSample(tex, tex_sampler, _e8);
    color = _e9;
    let _e11 = color;
    lum = dot(_e11.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e19 = global.u_softness;
    edge = (_e19 * 0.5f);
    let _e23 = global.u_level;
    let _e24 = edge;
    let _e26 = global.u_level;
    let _e27 = edge;
    let _e29 = lum;
    t = smoothstep((_e23 - _e24), (_e26 + _e27), _e29);
    let _e32 = t;
    let _e33 = vec3(_e32);
    let _e34 = color;
    fragColor = vec4<f32>(_e33.x, _e33.y, _e33.z, _e34.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e15 = fragColor;
    return FragmentOutput(_e15);
}
