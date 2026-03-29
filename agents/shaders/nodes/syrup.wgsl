struct Params {
    u_color_r: f32,
    u_color_g: f32,
    u_color_b: f32,
    u_top_alpha: f32,
    u_bottom_alpha: f32,
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
    var alpha: f32;
    var overlay: vec3<f32>;

    let _e14 = v_texcoord_1;
    let _e15 = textureSample(tex, tex_sampler, _e14);
    color = _e15;
    let _e17 = global.u_bottom_alpha;
    let _e18 = global.u_top_alpha;
    let _e19 = v_texcoord_1;
    alpha = mix(_e17, _e18, _e19.y);
    let _e23 = global.u_color_r;
    let _e24 = global.u_color_g;
    let _e25 = global.u_color_b;
    overlay = vec3<f32>(_e23, _e24, _e25);
    let _e28 = color;
    let _e30 = overlay;
    let _e31 = alpha;
    let _e33 = mix(_e28.xyz, _e30, vec3(_e31));
    let _e34 = color;
    fragColor = vec4<f32>(_e33.x, _e33.y, _e33.z, _e34.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
