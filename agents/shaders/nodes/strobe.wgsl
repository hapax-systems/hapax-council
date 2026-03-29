struct Params {
    u_active: f32,
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
var tex: texture_2d<f32>;
@group(1) @binding(1) 
var tex_sampler: sampler;
@group(2) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var color: vec4<f32>;
    var flash: vec4<f32>;

    let _e14 = v_texcoord_1;
    let _e15 = textureSample(tex, tex_sampler, _e14);
    color = _e15;
    let _e17 = global.u_active;
    if (_e17 > 0.5f) {
        {
            let _e20 = global.u_color_r;
            let _e21 = global.u_color_g;
            let _e22 = global.u_color_b;
            let _e23 = global.u_color_a;
            flash = vec4<f32>(_e20, _e21, _e22, _e23);
            let _e26 = color;
            let _e27 = flash;
            let _e28 = flash;
            fragColor = mix(_e26, _e27, vec4(_e28.w));
            return;
        }
    } else {
        {
            let _e32 = color;
            fragColor = _e32;
            return;
        }
    }
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
