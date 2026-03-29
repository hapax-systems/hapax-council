struct Params {
    u_vignette_strength: f32,
    u_sediment_strength: f32,
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
    var uv: vec2<f32>;
    var d: f32;
    var vig: f32;
    var sed: f32;

    let _e8 = v_texcoord_1;
    let _e9 = textureSample(tex, tex_sampler, _e8);
    c = _e9;
    let _e11 = v_texcoord_1;
    uv = ((_e11 * 2f) - vec2(1f));
    let _e18 = uv;
    d = length(_e18);
    let _e23 = d;
    let _e25 = global.u_vignette_strength;
    vig = (smoothstep(0.8f, 1.8f, _e23) * _e25);
    let _e28 = c;
    let _e30 = c;
    let _e33 = vig;
    let _e35 = (_e30.xyz * (1f - _e33));
    c.x = _e35.x;
    c.y = _e35.y;
    c.z = _e35.z;
    let _e44 = v_texcoord_1;
    let _e47 = global.u_sediment_strength;
    sed = (smoothstep(0.95f, 1f, _e44.y) * _e47);
    let _e50 = c;
    let _e52 = c;
    let _e55 = sed;
    let _e57 = (_e52.xyz * (1f - _e55));
    c.x = _e57.x;
    c.y = _e57.y;
    c.z = _e57.z;
    let _e64 = c;
    fragColor = _e64;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e15 = fragColor;
    return FragmentOutput(_e15);
}
