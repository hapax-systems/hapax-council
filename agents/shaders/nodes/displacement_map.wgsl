struct Params {
    u_strength_x: f32,
    u_strength_y: f32,
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
@group(0) @binding(2) 
var tex_b: texture_2d<f32>;
@group(0) @binding(3) 
var tex_b_sampler: sampler;
@group(1) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var uv: vec2<f32>;
    var disp: vec4<f32>;
    var offset: vec2<f32>;

    let _e10 = v_texcoord_1;
    uv = _e10;
    let _e12 = uv;
    let _e13 = textureSample(tex_b, tex_b_sampler, _e12);
    disp = _e13;
    let _e15 = disp;
    let _e22 = global.u_strength_x;
    let _e23 = global.u_strength_y;
    offset = ((((_e15.xy - vec2(0.5f)) * 2f) * vec2<f32>(_e22, _e23)) * 0.1f);
    let _e29 = uv;
    let _e30 = offset;
    let _e32 = textureSample(tex, tex_sampler, (_e29 + _e30));
    fragColor = _e32;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
