struct Params {
    u_feed_rate: f32,
    u_kill_rate: f32,
    u_diffusion_a: f32,
    u_diffusion_b: f32,
    u_speed: f32,
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
    var texel: vec2<f32>;
    var c: vec4<f32>;
    var A: f32;
    var B: f32;
    var l: vec4<f32>;
    var r: vec4<f32>;
    var t: vec4<f32>;
    var b: vec4<f32>;
    var lap_A: f32;
    var lap_B: f32;
    var reaction: f32;
    var dA: f32;
    var dB: f32;
    var seed: f32;

    texel = vec2<f32>((1f / uniforms.resolution.x), (1f / uniforms.resolution.y));
    let _e28 = v_texcoord_1;
    let _e29 = textureSample(tex_accum, tex_accum_sampler, _e28);
    c = _e29;
    let _e31 = c;
    A = _e31.x;
    let _e34 = c;
    B = _e34.y;
    let _e37 = v_texcoord_1;
    let _e38 = texel;
    let _e43 = textureSample(tex_accum, tex_accum_sampler, (_e37 - vec2<f32>(_e38.x, 0f)));
    l = _e43;
    let _e45 = v_texcoord_1;
    let _e46 = texel;
    let _e51 = textureSample(tex_accum, tex_accum_sampler, (_e45 + vec2<f32>(_e46.x, 0f)));
    r = _e51;
    let _e53 = v_texcoord_1;
    let _e55 = texel;
    let _e59 = textureSample(tex_accum, tex_accum_sampler, (_e53 - vec2<f32>(0f, _e55.y)));
    t = _e59;
    let _e61 = v_texcoord_1;
    let _e63 = texel;
    let _e67 = textureSample(tex_accum, tex_accum_sampler, (_e61 + vec2<f32>(0f, _e63.y)));
    b = _e67;
    let _e69 = l;
    let _e71 = r;
    let _e74 = t;
    let _e77 = b;
    let _e81 = A;
    lap_A = ((((_e69.x + _e71.x) + _e74.x) + _e77.x) - (4f * _e81));
    let _e85 = l;
    let _e87 = r;
    let _e90 = t;
    let _e93 = b;
    let _e97 = B;
    lap_B = ((((_e85.y + _e87.y) + _e90.y) + _e93.y) - (4f * _e97));
    let _e101 = A;
    let _e102 = B;
    let _e104 = B;
    reaction = ((_e101 * _e102) * _e104);
    let _e107 = global.u_diffusion_a;
    let _e108 = lap_A;
    let _e110 = reaction;
    let _e112 = global.u_feed_rate;
    let _e114 = A;
    dA = (((_e107 * _e108) - _e110) + (_e112 * (1f - _e114)));
    let _e119 = global.u_diffusion_b;
    let _e120 = lap_B;
    let _e122 = reaction;
    let _e124 = global.u_kill_rate;
    let _e125 = global.u_feed_rate;
    let _e127 = B;
    dB = (((_e119 * _e120) + _e122) - ((_e124 + _e125) * _e127));
    let _e131 = A;
    let _e132 = dA;
    let _e133 = global.u_speed;
    A = (_e131 + ((_e132 * _e133) * 0.1f));
    let _e138 = B;
    let _e139 = dB;
    let _e140 = global.u_speed;
    B = (_e138 + ((_e139 * _e140) * 0.1f));
    let _e145 = v_texcoord_1;
    let _e146 = textureSample(tex, tex_sampler, _e145);
    seed = dot(_e146.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e154 = A;
    let _e157 = seed;
    if ((_e154 < 0.01f) && (_e157 > 0.8f)) {
        {
            B = 0.25f;
        }
    }
    let _e162 = A;
    let _e166 = B;
    fragColor = vec4<f32>(clamp(_e162, 0f, 1f), clamp(_e166, 0f, 1f), 0f, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e29 = fragColor;
    return FragmentOutput(_e29);
}
