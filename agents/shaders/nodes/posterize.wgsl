struct Params {
    u_levels: f32,
    u_gamma: f32,
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
    var c: vec3<f32>;

    let _e8 = v_texcoord_1;
    let _e9 = textureSample(tex, tex_sampler, _e8);
    color = _e9;
    let _e11 = color;
    let _e13 = global.u_gamma;
    c = pow(_e11.xyz, vec3(_e13));
    let _e17 = c;
    let _e18 = global.u_levels;
    let _e24 = global.u_levels;
    c = (floor(((_e17 * _e18) + vec3(0.5f))) / vec3(_e24));
    let _e27 = c;
    let _e29 = global.u_gamma;
    c = pow(_e27, vec3((1f / _e29)));
    let _e33 = c;
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
