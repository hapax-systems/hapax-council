struct Params {
    u_frequency_x: f32,
    u_frequency_y: f32,
    u_octaves: f32,
    u_amplitude: f32,
    u_speed: f32,
    u_time: f32,
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
    let _e16 = p_1;
    return fract((sin(dot(_e16, vec2<f32>(127.1f, 311.7f))) * 43758.547f));
}

fn noise(p_2: vec2<f32>) -> f32 {
    var p_3: vec2<f32>;
    var i: vec2<f32>;
    var f: vec2<f32>;
    var a: f32;
    var b: f32;
    var c: f32;
    var d: f32;

    p_3 = p_2;
    let _e16 = p_3;
    i = floor(_e16);
    let _e19 = p_3;
    f = fract(_e19);
    let _e22 = f;
    let _e23 = f;
    let _e27 = f;
    f = ((_e22 * _e23) * (vec2(3f) - (2f * _e27)));
    let _e32 = i;
    let _e33 = hash(_e32);
    a = _e33;
    let _e35 = i;
    let _e40 = hash((_e35 + vec2<f32>(1f, 0f)));
    b = _e40;
    let _e42 = i;
    let _e47 = hash((_e42 + vec2<f32>(0f, 1f)));
    c = _e47;
    let _e49 = i;
    let _e54 = hash((_e49 + vec2<f32>(1f, 1f)));
    d = _e54;
    let _e56 = a;
    let _e57 = b;
    let _e58 = f;
    let _e61 = c;
    let _e62 = d;
    let _e63 = f;
    let _e66 = f;
    return mix(mix(_e56, _e57, _e58.x), mix(_e61, _e62, _e63.x), _e66.y);
}

fn fbm(p_4: vec2<f32>, oct: f32) -> f32 {
    var p_5: vec2<f32>;
    var oct_1: f32;
    var v: f32 = 0f;
    var a_1: f32 = 0.5f;
    var shift: vec2<f32> = vec2(100f);
    var i_1: i32 = 0i;

    p_5 = p_4;
    oct_1 = oct;
    loop {
        let _e27 = i_1;
        if !((_e27 < 8i)) {
            break;
        }
        {
            let _e34 = i_1;
            let _e36 = oct_1;
            if (f32(_e34) >= _e36) {
                break;
            }
            let _e38 = v;
            let _e39 = a_1;
            let _e40 = p_5;
            let _e41 = noise(_e40);
            v = (_e38 + (_e39 * _e41));
            let _e44 = p_5;
            let _e47 = shift;
            p_5 = ((_e44 * 2f) + _e47);
            let _e49 = a_1;
            a_1 = (_e49 * 0.5f);
        }
        continuing {
            let _e31 = i_1;
            i_1 = (_e31 + 1i);
        }
    }
    let _e52 = v;
    return _e52;
}

fn main_1() {
    var uv: vec2<f32>;
    var n: f32;

    let _e14 = v_texcoord_1;
    let _e15 = global.u_frequency_x;
    let _e16 = global.u_frequency_y;
    uv = (_e14 * vec2<f32>(_e15, _e16));
    let _e20 = uv;
    let _e21 = global.u_time;
    let _e22 = global.u_speed;
    uv = (_e20 + vec2(((_e21 * _e22) * 0.1f)));
    let _e28 = uv;
    let _e29 = global.u_octaves;
    let _e30 = fbm(_e28, _e29);
    let _e31 = global.u_amplitude;
    n = (_e30 * _e31);
    let _e34 = n;
    let _e35 = vec3(_e34);
    fragColor = vec4<f32>(_e35.x, _e35.y, _e35.z, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
