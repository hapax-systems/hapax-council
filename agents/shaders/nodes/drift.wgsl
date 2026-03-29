struct Params {
    u_speed: f32,
    u_amplitude: f32,
    u_frequency: f32,
    u_coherence: f32,
    u_time: f32,
    u_width: f32,
    u_height: f32,
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

fn hash(p: vec2<f32>) -> f32 {
    var p_1: vec2<f32>;

    p_1 = p;
    let _e20 = p_1;
    return fract((sin(dot(_e20, vec2<f32>(127.1f, 311.7f))) * 43758.547f));
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
    let _e20 = p_3;
    i = floor(_e20);
    let _e23 = p_3;
    f = fract(_e23);
    let _e26 = f;
    let _e27 = f;
    let _e31 = f;
    f = ((_e26 * _e27) * (vec2(3f) - (2f * _e31)));
    let _e36 = i;
    let _e37 = hash(_e36);
    a = _e37;
    let _e39 = i;
    let _e44 = hash((_e39 + vec2<f32>(1f, 0f)));
    b = _e44;
    let _e46 = i;
    let _e51 = hash((_e46 + vec2<f32>(0f, 1f)));
    c = _e51;
    let _e53 = i;
    let _e58 = hash((_e53 + vec2<f32>(1f, 1f)));
    d = _e58;
    let _e60 = a;
    let _e61 = b;
    let _e62 = f;
    let _e65 = c;
    let _e66 = d;
    let _e67 = f;
    let _e70 = f;
    return mix(mix(_e60, _e61, _e62.x), mix(_e65, _e66, _e67.x), _e70.y);
}

fn main_1() {
    var uv: vec2<f32>;
    var t: f32;
    var n1_: f32;
    var n2_: f32;
    var n3_: f32;
    var dx: f32;
    var dy: f32;
    var offset: vec2<f32>;

    let _e18 = v_texcoord_1;
    uv = _e18;
    let _e20 = global.u_time;
    let _e21 = global.u_speed;
    t = (_e20 * _e21);
    let _e24 = uv;
    let _e25 = global.u_frequency;
    let _e27 = t;
    let _e30 = noise(((_e24 * _e25) + vec2(_e27)));
    n1_ = _e30;
    let _e32 = uv;
    let _e33 = global.u_frequency;
    let _e37 = t;
    let _e42 = noise((((_e32 * _e33) * 2f) + vec2((_e37 * 1.3f))));
    n2_ = _e42;
    let _e44 = uv;
    let _e45 = global.u_frequency;
    let _e49 = t;
    let _e54 = noise((((_e44 * _e45) * 0.5f) + vec2((_e49 * 0.7f))));
    n3_ = _e54;
    let _e56 = n1_;
    let _e57 = n1_;
    let _e58 = n2_;
    let _e62 = n3_;
    let _e68 = global.u_coherence;
    dx = (mix(_e56, (((_e57 + (_e58 * 0.5f)) + (_e62 * 0.25f)) / 1.75f), _e68) - 0.5f);
    let _e73 = n2_;
    let _e74 = n2_;
    let _e75 = n3_;
    let _e79 = n1_;
    let _e85 = global.u_coherence;
    dy = (mix(_e73, (((_e74 + (_e75 * 0.5f)) + (_e79 * 0.25f)) / 1.75f), _e85) - 0.5f);
    let _e90 = dx;
    let _e91 = dy;
    let _e93 = global.u_amplitude;
    offset = ((vec2<f32>(_e90, _e91) * _e93) * 0.1f);
    let _e98 = uv;
    let _e99 = offset;
    let _e101 = textureSample(tex, tex_sampler, (_e98 + _e99));
    fragColor = _e101;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e25 = fragColor;
    return FragmentOutput(_e25);
}
