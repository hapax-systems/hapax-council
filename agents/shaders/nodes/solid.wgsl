struct Params {
    u_color_r: f32,
    u_color_g: f32,
    u_color_b: f32,
    u_color_a: f32,
}

struct FragmentOutput {
    @location(0) fragColor: vec4<f32>,
}

var<private> fragColor: vec4<f32>;
var<private> v_texcoord_1: vec2<f32>;
@group(1) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    let _e10 = global.u_color_r;
    let _e11 = global.u_color_g;
    let _e12 = global.u_color_b;
    let _e13 = global.u_color_a;
    fragColor = vec4<f32>(_e10, _e11, _e12, _e13);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e15 = fragColor;
    return FragmentOutput(_e15);
}
