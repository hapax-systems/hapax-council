struct Params {
    u_shape: f32,
    u_thickness: f32,
    u_color_r: f32,
    u_color_g: f32,
    u_color_b: f32,
    u_color_a: f32,
    u_scale: f32,
}

struct FragmentOutput {
    @location(0) fragColor: vec4<f32>,
}

var<private> fragColor: vec4<f32>;
var<private> v_texcoord_1: vec2<f32>;
@group(2) @binding(0) 
var<uniform> global: Params;

fn hash(p: vec2<f32>) -> f32 {
    var p_1: vec2<f32>;

    p_1 = p;
    let _e20 = p_1;
    return fract((sin(dot(_e20, vec2<f32>(127.1f, 311.7f))) * 43758.547f));
}

fn main_1() {
    var uv: vec2<f32>;
    var r: f32;
    var angle: f32;
    var wave: f32 = 0f;
    var i: i32 = 0i;
    var fi: f32;
    var freq: f32;
    var phase: f32;
    var ring: f32;
    var px: f32;
    var alpha: f32;
    var glow: f32;
    var col: vec3<f32>;

    let _e18 = v_texcoord_1;
    uv = ((_e18 * 2f) - vec2(1f));
    let _e25 = uv;
    r = length(_e25);
    let _e28 = uv;
    let _e30 = uv;
    angle = atan2(_e28.y, _e30.x);
    loop {
        let _e38 = i;
        if !((_e38 < 8i)) {
            break;
        }
        {
            let _e45 = i;
            fi = f32(_e45);
            let _e49 = fi;
            freq = (3f + (_e49 * 2f));

            let _e56 = fi;
            phase = (uniforms.time * (1f + (_e56 * 0.3f)));
            let _e62 = wave;
            let _e63 = angle;
            let _e64 = freq;
            let _e66 = phase;
            let _e72 = fi;
            wave = (_e62 + ((sin(((_e63 * _e64) + _e66)) * 0.01f) / (1f + (_e72 * 0.5f))));
        }
        continuing {
            let _e42 = i;
            i = (_e42 + 1i);
        }
    }
    let _e78 = r;
    let _e79 = global.u_scale;
    let _e81 = wave;
    ring = abs(((_e78 - _e79) + _e81));
    let _e88 = global.u_thickness;
    px = (0.002f * _e88);
    let _e93 = px;
    let _e94 = ring;
    alpha = (1f - smoothstep(0f, _e93, _e94));
    let _e98 = ring;
    let _e102 = global.u_thickness;
    glow = (exp(((-(_e98) * 80f) / _e102)) * 0.4f);
    let _e108 = alpha;
    let _e109 = glow;
    alpha = clamp((_e108 + _e109), 0f, 1f);
    let _e114 = global.u_color_r;
    let _e115 = global.u_color_g;
    let _e116 = global.u_color_b;
    col = vec3<f32>(_e114, _e115, _e116);
    let _e119 = col;
    let _e120 = alpha;
    let _e121 = (_e119 * _e120);
    let _e122 = alpha;
    let _e123 = global.u_color_a;
    fragColor = vec4<f32>(_e121.x, _e121.y, _e121.z, (_e122 * _e123));
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e23 = fragColor;
    return FragmentOutput(_e23);
}
