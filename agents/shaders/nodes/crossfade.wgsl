struct Params {
    u_mix: f32,
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

    let _e8 = v_texcoord_1;
    let _e9 = textureSample(tex, tex_sampler, _e8);
    a = _e9;
    let _e11 = v_texcoord_1;
    let _e12 = textureSample(tex_b, tex_b_sampler, _e11);
    b = _e12;
    let _e14 = a;
    let _e15 = b;
    let _e16 = global.u_mix;
    fragColor = mix(_e14, _e15, vec4(_e16));
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e17 = fragColor;
    return FragmentOutput(_e17);
}
