struct Params {
    u_axis: f32,
    u_position: f32,
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
    var uv: vec2<f32>;

    let _e8 = v_texcoord_1;
    uv = _e8;
    let _e10 = global.u_axis;
    let _e13 = global.u_axis;
    if ((_e10 < 0.5f) || (_e13 > 1.5f)) {
        {
            let _e17 = uv;
            let _e19 = global.u_position;
            if (_e17.x > _e19) {
                {
                    let _e23 = global.u_position;
                    let _e25 = uv;
                    uv.x = ((2f * _e23) - _e25.x);
                }
            }
        }
    }
    let _e28 = global.u_axis;
    if (_e28 > 0.5f) {
        {
            let _e31 = uv;
            let _e33 = global.u_position;
            if (_e31.y > _e33) {
                {
                    let _e37 = global.u_position;
                    let _e39 = uv;
                    uv.y = ((2f * _e37) - _e39.y);
                }
            }
        }
    }
    let _e42 = uv;
    let _e43 = textureSample(tex, tex_sampler, _e42);
    fragColor = _e43;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e15 = fragColor;
    return FragmentOutput(_e15);
}
