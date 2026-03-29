struct Params {
    u_strength: f32,
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
    var inverted: vec3<f32>;

    let _e6 = v_texcoord_1;
    let _e7 = textureSample(tex, tex_sampler, _e6);
    color = _e7;
    let _e11 = color;
    inverted = (vec3(1f) - _e11.xyz);
    let _e15 = color;
    let _e17 = inverted;
    let _e18 = global.u_strength;
    let _e20 = mix(_e15.xyz, _e17, vec3(_e18));
    let _e21 = color;
    fragColor = vec4<f32>(_e20.x, _e20.y, _e20.z, _e21.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e13 = fragColor;
    return FragmentOutput(_e13);
}
