struct Params {
    u_count_x: f32,
    u_count_y: f32,
    u_mirror: f32,
    u_gap: f32,
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
    var cell: vec2<f32>;
    var f: vec2<f32>;
    var half_gap: f32;

    let _e12 = v_texcoord_1;
    let _e13 = global.u_count_x;
    let _e14 = global.u_count_y;
    uv = (_e12 * vec2<f32>(_e13, _e14));
    let _e18 = uv;
    cell = floor(_e18);
    let _e21 = uv;
    f = fract(_e21);
    let _e24 = global.u_mirror;
    if (_e24 > 0.5f) {
        {
            let _e27 = cell;
            if ((_e27.x - (floor((_e27.x / 2f)) * 2f)) > 0.5f) {
                let _e38 = f;
                f.x = (1f - _e38.x);
            }
            let _e41 = cell;
            if ((_e41.y - (floor((_e41.y / 2f)) * 2f)) > 0.5f) {
                let _e52 = f;
                f.y = (1f - _e52.y);
            }
        }
    }
    let _e55 = global.u_gap;
    if (_e55 > 0f) {
        {
            let _e58 = global.u_gap;
            half_gap = (_e58 * 0.5f);
            let _e62 = f;
            let _e64 = half_gap;
            let _e66 = f;
            let _e69 = half_gap;
            let _e73 = f;
            let _e75 = half_gap;
            let _e78 = f;
            let _e81 = half_gap;
            if ((((_e62.x < _e64) || (_e66.x > (1f - _e69))) || (_e73.y < _e75)) || (_e78.y > (1f - _e81))) {
                {
                    fragColor = vec4<f32>(0f, 0f, 0f, 1f);
                    return;
                }
            }
            let _e90 = f;
            let _e91 = half_gap;
            let _e95 = global.u_gap;
            f = ((_e90 - vec2(_e91)) / vec2((1f - _e95)));
        }
    }
    let _e99 = f;
    let _e100 = textureSample(tex, tex_sampler, _e99);
    fragColor = _e100;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
