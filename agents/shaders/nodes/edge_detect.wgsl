struct Params {
    u_threshold: f32,
    u_color_mode: f32,
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

fn luminance(c: vec3<f32>) -> f32 {
    var c_1: vec3<f32>;

    c_1 = c;
    let _e14 = c_1;
    return dot(_e14, vec3<f32>(0.299f, 0.587f, 0.114f));
}

fn main_1() {
    var texel: vec2<f32>;
    var tl: f32;
    var t: f32;
    var tr: f32;
    var l: f32;
    var r: f32;
    var bl: f32;
    var b: f32;
    var br: f32;
    var gx: f32;
    var gy: f32;
    var edge: f32;
    var color: vec4<f32>;

    texel = vec2<f32>((1f / uniforms.resolution.x), (1f / uniforms.resolution.y));
    let _e20 = v_texcoord_1;
    let _e21 = texel;
    let _e24 = texel;
    let _e28 = textureSample(tex, tex_sampler, (_e20 + vec2<f32>(-(_e21.x), _e24.y)));
    let _e30 = luminance(_e28.xyz);
    tl = _e30;
    let _e32 = v_texcoord_1;
    let _e34 = texel;
    let _e38 = textureSample(tex, tex_sampler, (_e32 + vec2<f32>(0f, _e34.y)));
    let _e40 = luminance(_e38.xyz);
    t = _e40;
    let _e42 = v_texcoord_1;
    let _e43 = texel;
    let _e45 = texel;
    let _e49 = textureSample(tex, tex_sampler, (_e42 + vec2<f32>(_e43.x, _e45.y)));
    let _e51 = luminance(_e49.xyz);
    tr = _e51;
    let _e53 = v_texcoord_1;
    let _e54 = texel;
    let _e60 = textureSample(tex, tex_sampler, (_e53 + vec2<f32>(-(_e54.x), 0f)));
    let _e62 = luminance(_e60.xyz);
    l = _e62;
    let _e64 = v_texcoord_1;
    let _e65 = texel;
    let _e70 = textureSample(tex, tex_sampler, (_e64 + vec2<f32>(_e65.x, 0f)));
    let _e72 = luminance(_e70.xyz);
    r = _e72;
    let _e74 = v_texcoord_1;
    let _e75 = texel;
    let _e78 = texel;
    let _e83 = textureSample(tex, tex_sampler, (_e74 + vec2<f32>(-(_e75.x), -(_e78.y))));
    let _e85 = luminance(_e83.xyz);
    bl = _e85;
    let _e87 = v_texcoord_1;
    let _e89 = texel;
    let _e94 = textureSample(tex, tex_sampler, (_e87 + vec2<f32>(0f, -(_e89.y))));
    let _e96 = luminance(_e94.xyz);
    b = _e96;
    let _e98 = v_texcoord_1;
    let _e99 = texel;
    let _e101 = texel;
    let _e106 = textureSample(tex, tex_sampler, (_e98 + vec2<f32>(_e99.x, -(_e101.y))));
    let _e108 = luminance(_e106.xyz);
    br = _e108;
    let _e110 = tl;
    let _e113 = l;
    let _e116 = bl;
    let _e118 = tr;
    let _e121 = r;
    let _e124 = br;
    gx = (((((-(_e110) - (2f * _e113)) - _e116) + _e118) + (2f * _e121)) + _e124);
    let _e127 = tl;
    let _e130 = t;
    let _e133 = tr;
    let _e135 = bl;
    let _e138 = b;
    let _e141 = br;
    gy = (((((-(_e127) - (2f * _e130)) - _e133) + _e135) + (2f * _e138)) + _e141);
    let _e144 = gx;
    let _e145 = gx;
    let _e147 = gy;
    let _e148 = gy;
    edge = sqrt(((_e144 * _e145) + (_e147 * _e148)));
    let _e153 = global.u_threshold;
    let _e154 = edge;
    edge = step(_e153, _e154);
    let _e159 = v_texcoord_1;
    let _e160 = textureSample(tex, tex_sampler, _e159);
    color = _e160;
    let strength = clamp(global.u_color_mode, 0.0f, 1.0f) * edge;
    let edged = max(color.xyz, vec3(edge));
    let mixed = mix(color.xyz, edged, vec3(strength * 0.28f));
    fragColor = vec4<f32>(mixed.x, mixed.y, mixed.z, color.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
