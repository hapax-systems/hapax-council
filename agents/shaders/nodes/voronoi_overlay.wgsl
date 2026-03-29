struct Params {
    u_cell_count: f32,
    u_edge_width: f32,
    u_animation_speed: f32,
    u_jitter: f32,
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

fn hash2_(p: vec2<f32>) -> vec2<f32> {
    var p_1: vec2<f32>;

    p_1 = p;
    let _e16 = p_1;
    let _e21 = p_1;
    p_1 = vec2<f32>(dot(_e16, vec2<f32>(127.1f, 311.7f)), dot(_e21, vec2<f32>(269.5f, 183.3f)));
    let _e27 = p_1;
    return fract((sin(_e27) * 43758.547f));
}

fn main_1() {
    var color: vec4<f32>;
    var uv: vec2<f32>;
    var cell: vec2<f32>;
    var frac_uv: vec2<f32>;
    var minDist: f32 = 10f;
    var secondDist: f32 = 10f;
    var y: i32 = -1i;
    var x: i32;
    var neighbor: vec2<f32>;
    var point: vec2<f32>;
    var d: f32;
    var edge: f32;

    let _e14 = v_texcoord_1;
    let _e15 = textureSample(tex, tex_sampler, _e14);
    color = _e15;
    let _e17 = v_texcoord_1;
    let _e18 = global.u_cell_count;
    uv = (_e17 * _e18);
    let _e21 = uv;
    cell = floor(_e21);
    let _e24 = uv;
    frac_uv = fract(_e24);
    loop {
        let _e34 = y;
        if !((_e34 <= 1i)) {
            break;
        }
        {
            x = -1i;
            loop {
                let _e44 = x;
                if !((_e44 <= 1i)) {
                    break;
                }
                {
                    let _e51 = x;
                    let _e53 = y;
                    neighbor = vec2<f32>(f32(_e51), f32(_e53));
                    let _e57 = cell;
                    let _e58 = neighbor;
                    let _e60 = hash2_((_e57 + _e58));
                    point = _e60;
                    let _e63 = global.u_jitter;
                    let _e66 = global.u_time;
                    let _e67 = global.u_animation_speed;
                    let _e70 = point;
                    point = (vec2(0.5f) + ((_e63 * 0.5f) * sin((vec2((_e66 * _e67)) + (6.2831f * _e70)))));
                    let _e78 = neighbor;
                    let _e79 = point;
                    let _e81 = frac_uv;
                    d = length(((_e78 + _e79) - _e81));
                    let _e85 = d;
                    let _e86 = minDist;
                    if (_e85 < _e86) {
                        {
                            let _e88 = minDist;
                            secondDist = _e88;
                            let _e89 = d;
                            minDist = _e89;
                        }
                    } else {
                        let _e90 = d;
                        let _e91 = secondDist;
                        if (_e90 < _e91) {
                            {
                                let _e93 = d;
                                secondDist = _e93;
                            }
                        }
                    }
                }
                continuing {
                    let _e48 = x;
                    x = (_e48 + 1i);
                }
            }
        }
        continuing {
            let _e38 = y;
            y = (_e38 + 1i);
        }
    }
    let _e95 = global.u_edge_width;
    let _e96 = secondDist;
    let _e97 = minDist;
    edge = smoothstep(0f, _e95, (_e96 - _e97));
    let _e101 = color;
    let _e103 = edge;
    let _e104 = (_e101.xyz * _e103);
    let _e105 = color;
    fragColor = vec4<f32>(_e104.x, _e104.y, _e104.z, _e105.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
