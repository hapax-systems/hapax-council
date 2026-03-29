struct Params {
    u_direction: f32,
    u_speed: f32,
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
@group(1) @binding(2) 
var tex_accum: texture_2d<f32>;
@group(1) @binding(3) 
var tex_accum_sampler: sampler;
@group(2) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var uv: vec2<f32>;
    var offset: f32;

    let _e12 = v_texcoord_1;
    uv = _e12;
    let _e14 = global.u_speed;
    let _e15 = global.u_time;
    offset = ((_e14 * _e15) * 0.01f);
    let _e20 = global.u_direction;
    if (_e20 < 0.5f) {
        {
            let _e24 = uv;
            let _e26 = uv;
            let _e28 = offset;
            uv.x = fract((_e24.x + (_e26.y * _e28)));
        }
    } else {
        {
            let _e33 = uv;
            let _e35 = uv;
            let _e37 = offset;
            uv.y = fract((_e33.y + (_e35.x * _e37)));
        }
    }
    let _e41 = uv;
    let _e42 = textureSample(tex, tex_sampler, _e41);
    fragColor = _e42;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
