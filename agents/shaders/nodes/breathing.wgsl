struct Params {
    u_rate: f32,
    u_amplitude: f32,
    u_time: f32,
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
    var scale: f32;
    var center: vec2<f32> = vec2<f32>(0.5f, 0.5f);
    var uv: vec2<f32>;

    let _e11 = global.u_time;
    let _e12 = global.u_rate;
    let _e19 = global.u_amplitude;
    scale = (1f + (sin((((_e11 * _e12) * 2f) * 3.1415927f)) * _e19));
    let _e27 = v_texcoord_1;
    let _e28 = center;
    let _e30 = scale;
    let _e33 = center;
    uv = (((_e27 - _e28) / vec2(_e30)) + _e33);
    let _e36 = uv;
    let _e40 = uv;
    let _e45 = uv;
    let _e50 = uv;
    if ((((_e36.x < 0f) || (_e40.x > 1f)) || (_e45.y < 0f)) || (_e50.y > 1f)) {
        {
            fragColor = vec4<f32>(0f, 0f, 0f, 1f);
            return;
        }
    } else {
        {
            let _e60 = uv;
            let _e61 = textureSample(tex, tex_sampler, _e60);
            fragColor = _e61;
            return;
        }
    }
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e17 = fragColor;
    return FragmentOutput(_e17);
}
