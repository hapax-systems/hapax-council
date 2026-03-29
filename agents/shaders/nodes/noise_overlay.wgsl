struct Params {
    u_intensity: f32,
    u_animated: f32,
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

fn hash(p: vec2<f32>) -> f32 {
    var p_1: vec2<f32>;
    var p3_: vec3<f32>;

    p_1 = p;
    let _e16 = p_1;
    p3_ = fract((vec3<f32>(_e16.xyx) * 0.1031f));
    let _e23 = p3_;
    let _e24 = p3_;
    let _e25 = p3_;
    p3_ = (_e23 + vec3(dot(_e24, (_e25.yzx + vec3(33.33f)))));
    let _e33 = p3_;
    let _e35 = p3_;
    let _e38 = p3_;
    return fract(((_e33.x + _e35.y) * _e38.z));
}

fn main_1() {
    var c: vec4<f32>;
    var uv: vec2<f32>;
    var local: f32;
    var n: f32;
    var r: vec3<f32>;

    let _e14 = v_texcoord_1;
    let _e15 = textureSample(tex, tex_sampler, _e14);
    c = _e15;
    let _e17 = v_texcoord_1;

    uv = floor(((_e17 * vec2<f32>(uniforms.resolution.x, uniforms.resolution.y)) / vec2(8f)));
    let _e27 = uv;
    let _e28 = global.u_animated;
    if (_e28 > 0.5f) {

        local = floor((uniforms.time * 10f));
    } else {
        local = 0f;
    }
    let _e37 = local;
    let _e40 = hash((_e27 + vec2(_e37)));
    n = _e40;
    let _e43 = c;
    let _e46 = n;
    let _e52 = c;
    let _e58 = n;
    let _e66 = c;
    r = mix(((2f * _e43.xyz) * vec3(_e46)), (vec3(1f) - ((2f * (vec3(1f) - _e52.xyz)) * (vec3(1f) - vec3(_e58)))), step(vec3(0.5f), _e66.xyz));
    let _e72 = c;
    let _e74 = c;
    let _e76 = r;
    let _e77 = global.u_intensity;
    let _e79 = mix(_e74.xyz, _e76, vec3(_e77));
    c.x = _e79.x;
    c.y = _e79.y;
    c.z = _e79.z;
    let _e86 = c;
    fragColor = _e86;
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
