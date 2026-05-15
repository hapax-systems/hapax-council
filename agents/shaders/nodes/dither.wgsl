struct Params {
    u_matrix_size: f32,
    u_color_levels: f32,
    u_monochrome: f32,
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
var<private> gl_FragCoord_1: vec4<f32>;

fn bayer4x4_(pos: vec2<f32>) -> f32 {
    var pos_1: vec2<f32>;
    var x: i32;
    var y: i32;
    var idx: i32;

    pos_1 = pos;
    let _e12 = pos_1;
    x = i32((_e12.x - (floor((_e12.x / 4f)) * 4f)));
    let _e21 = pos_1;
    y = i32((_e21.y - (floor((_e21.y / 4f)) * 4f)));
    let _e30 = x;
    let _e31 = y;
    idx = (_e30 + (_e31 * 4i));
    let _e36 = idx;
    if (_e36 == 0i) {
        return 0f;
    }
    let _e42 = idx;
    if (_e42 == 1i) {
        return 0.5f;
    }
    let _e48 = idx;
    if (_e48 == 2i) {
        return 0.125f;
    }
    let _e54 = idx;
    if (_e54 == 3i) {
        return 0.625f;
    }
    let _e60 = idx;
    if (_e60 == 4i) {
        return 0.75f;
    }
    let _e66 = idx;
    if (_e66 == 5i) {
        return 0.25f;
    }
    let _e72 = idx;
    if (_e72 == 6i) {
        return 0.875f;
    }
    let _e78 = idx;
    if (_e78 == 7i) {
        return 0.375f;
    }
    let _e84 = idx;
    if (_e84 == 8i) {
        return 0.1875f;
    }
    let _e90 = idx;
    if (_e90 == 9i) {
        return 0.6875f;
    }
    let _e96 = idx;
    if (_e96 == 10i) {
        return 0.0625f;
    }
    let _e102 = idx;
    if (_e102 == 11i) {
        return 0.5625f;
    }
    let _e108 = idx;
    if (_e108 == 12i) {
        return 0.9375f;
    }
    let _e114 = idx;
    if (_e114 == 13i) {
        return 0.4375f;
    }
    let _e120 = idx;
    if (_e120 == 14i) {
        return 0.8125f;
    }
    return 0.3125f;
}

fn main_1() {
    var color: vec4<f32>;
    var pixPos: vec2<f32>;
    var threshold: f32;
    var levels: f32;
    var c: vec3<f32>;
    var lum: f32;
    var dither_strength: f32;
    var source_luma: f32;
    var surface_presence: f32;
    var effective_strength: f32;
    var mixed: vec3<f32>;

    let _e10 = v_texcoord_1;
    let _e11 = textureSample(tex, tex_sampler, _e10);
    color = _e11;
    levels = clamp(global.u_color_levels, 2f, 256f);
    dither_strength = clamp(((256f - levels) / 252f), 0f, 1f) * 0.38f;
    source_luma = dot(color.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    surface_presence = smoothstep(0.055f, 0.22f, source_luma);
    effective_strength = dither_strength * surface_presence;
    if (effective_strength <= 0.001f) {
        fragColor = color;
        return;
    }
    let _e14 = gl_FragCoord_1;
    let _e16 = global.u_matrix_size;
    pixPos = (_e14.xy / vec2(max(_e16, 1f)));
    let _e20 = pixPos;
    let _e21 = bayer4x4_(_e20);
    threshold = _e21;
    let _e25 = color;
    c = _e25.xyz;
    let _e28 = global.u_monochrome;
    if (_e28 > 0.5f) {
        {
            let _e31 = c;
            lum = dot(_e31, vec3<f32>(0.299f, 0.587f, 0.114f));
            let _e38 = lum;
            let _e39 = levels;
            let _e41 = threshold;
            let _e44 = levels;
            lum = (floor(((_e38 * _e39) + _e41)) / _e44);
            mixed = mix(color.xyz, vec3(lum), vec3(effective_strength));
            fragColor = vec4<f32>(mixed.x, mixed.y, mixed.z, color.w);
            return;
        }
    } else {
        {
            let _e54 = c;
            let _e55 = levels;
            let _e57 = threshold;
            let _e61 = levels;
            c = (floor(((_e54 * _e55) + vec3(_e57))) / vec3(_e61));
            mixed = mix(color.xyz, c, vec3(effective_strength));
            fragColor = vec4<f32>(mixed.x, mixed.y, mixed.z, color.w);
            return;
        }
    }
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>, @builtin(position) gl_FragCoord: vec4<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    gl_FragCoord_1 = gl_FragCoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
