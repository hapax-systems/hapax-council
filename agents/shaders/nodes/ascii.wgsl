struct Params {
    u_cell_size: f32,
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

fn charFill(lum: f32, cellPos: vec2<f32>) -> f32 {
    var lum_1: f32;
    var cellPos_1: vec2<f32>;
    var cx: f32;
    var cy: f32;
    var dx: f32;
    var dy: f32;
    var d: f32;
    var local: f32;
    var local_1: f32;
    var local_2: f32;
    var cross_: f32;
    var local_3: f32;
    var local_4: f32;
    var local_5: f32;
    var local_6: f32;
    var local_7: f32;
    var local_8: f32;

    lum_1 = lum;
    cellPos_1 = cellPos;
    let _e18 = cellPos_1;
    cx = _e18.x;
    let _e21 = cellPos_1;
    cy = _e21.y;
    let _e24 = cx;
    dx = (_e24 - 0.5f);
    let _e28 = cy;
    dy = (_e28 - 0.5f);
    let _e32 = dx;
    let _e33 = dx;
    let dy_val = dy;
    let _e36 = dy;
    d = sqrt(((_e32 * _e33) + (dy_val * _e36)));
    let _e41 = lum_1;
    if (_e41 < 0.05f) {
        return 0f;
    }
    let _e45 = lum_1;
    if (_e45 < 0.15f) {
        {
            let _e48 = d;
            if (_e48 < 0.15f) {
                local = 1f;
            } else {
                local = 0f;
            }
            let _e54 = local;
            return _e54;
        }
    }
    let _e55 = lum_1;
    if (_e55 < 0.25f) {
        {
            let _e58 = d;
            if (_e58 < 0.22f) {
                local_1 = 1f;
            } else {
                local_1 = 0f;
            }
            let _e64 = local_1;
            return _e64;
        }
    }
    let _e65 = lum_1;
    if (_e65 < 0.35f) {
        {
            let _e68 = dy;
            let _e72 = dx;
            if ((abs(_e68) < 0.12f) && (abs(_e72) < 0.35f)) {
                local_2 = 1f;
            } else {
                local_2 = 0f;
            }
            let _e80 = local_2;
            return _e80;
        }
    }
    let _e81 = lum_1;
    if (_e81 < 0.45f) {
        {
            let _e84 = dx;
            let _e86 = dy;
            cross_ = min(abs(_e84), abs(_e86));
            let _e90 = cross_;
            if (_e90 < 0.15f) {
                local_3 = 1f;
            } else {
                local_3 = 0f;
            }
            let _e96 = local_3;
            return _e96;
        }
    }
    let _e97 = lum_1;
    if (_e97 < 0.55f) {
        {
            let _e100 = dx;
            let _e102 = dy;
            if ((abs(_e100) + abs(_e102)) < 0.4f) {
                local_4 = 1f;
            } else {
                local_4 = 0f;
            }
            let _e110 = local_4;
            return _e110;
        }
    }
    let _e111 = lum_1;
    if (_e111 < 0.65f) {
        {
            let _e114 = d;
            if (_e114 < 0.35f) {
                local_5 = 1f;
            } else {
                local_5 = 0f;
            }
            let _e120 = local_5;
            return _e120;
        }
    }
    let _e121 = lum_1;
    if (_e121 < 0.75f) {
        {
            let _e124 = dx;
            let _e128 = dy;
            if ((abs(_e124) < 0.35f) && (abs(_e128) < 0.35f)) {
                local_6 = 1f;
            } else {
                local_6 = 0f;
            }
            let _e136 = local_6;
            return _e136;
        }
    }
    let _e137 = lum_1;
    if (_e137 < 0.85f) {
        {
            let _e140 = d;
            if (_e140 < 0.45f) {
                local_7 = 1f;
            } else {
                local_7 = 0f;
            }
            let _e146 = local_7;
            return _e146;
        }
    }
    let _e147 = lum_1;
    if (_e147 < 0.95f) {
        {
            let _e150 = dx;
            let _e154 = dy;
            if ((abs(_e150) < 0.45f) && (abs(_e154) < 0.45f)) {
                local_8 = 1f;
            } else {
                local_8 = 0f;
            }
            let _e162 = local_8;
            return _e162;
        }
    }
    return 1f;
}

fn main_1() {
    var uv: vec2<f32>;
    var cellW: f32;
    var cellH: f32;
    var pixel: vec2<f32>;
    var cellIdx: vec2<f32>;
    var cellCenter: vec2<f32>;
    var centerUV: vec2<f32>;
    var centerColor: vec3<f32>;
    var texel: vec2<f32>;
    var c2_: vec3<f32>;
    var c3_: vec3<f32>;
    var lum_2: f32;
    var posInCell: vec2<f32>;
    var bit: f32;
    var fgColor: vec3<f32>;
    var color: vec3<f32>;
    var sourceColor: vec4<f32>;

    let _e14 = v_texcoord_1;
    uv = _e14;
    sourceColor = textureSample(tex, tex_sampler, uv);
    let _e16 = global.u_cell_size;
    if (_e16 < 2f) {
        {
            fragColor = sourceColor;
            return;
        }
    }
    let _e21 = global.u_cell_size;
    cellW = floor(_e21);
    let _e24 = global.u_cell_size;
    cellH = floor((_e24 * 1.5f));
    let _e29 = uv;

    let _e33 = uv;

    pixel = vec2<f32>((_e29.x * uniforms.resolution.x), (_e33.y * uniforms.resolution.y));
    let _e39 = pixel;
    let _e40 = cellW;
    let _e41 = cellH;
    cellIdx = floor((_e39 / vec2<f32>(_e40, _e41)));
    let _e46 = cellIdx;
    let _e50 = cellW;
    let _e51 = cellH;
    cellCenter = ((_e46 + vec2(0.5f)) * vec2<f32>(_e50, _e51));
    let _e55 = cellCenter;

    centerUV = (_e55 / vec2<f32>(uniforms.resolution.x, uniforms.resolution.y));
    let _e61 = centerUV;
    let _e62 = textureSample(tex, tex_sampler, _e61);
    centerColor = _e62.xyz;

    texel = vec2<f32>((1f / uniforms.resolution.x), (1f / uniforms.resolution.y));
    let _e73 = centerUV;
    let _e74 = texel;
    let _e82 = textureSample(tex, tex_sampler, (_e73 + (_e74 * vec2<f32>(-1f, -1f))));
    c2_ = _e82.xyz;
    let _e85 = centerUV;
    let _e86 = texel;
    let _e92 = textureSample(tex, tex_sampler, (_e85 + (_e86 * vec2<f32>(1f, 1f))));
    c3_ = _e92.xyz;
    let _e95 = centerColor;
    let _e98 = c2_;
    let _e102 = c3_;
    lum_2 = dot((((_e95 * 0.5f) + (_e98 * 0.25f)) + (_e102 * 0.25f)), vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e112 = pixel;
    let _e113 = cellW;
    let _e114 = cellH;
    let _e115 = vec2<f32>(_e113, _e114);
    let _e120 = cellW;
    let _e121 = cellH;
    posInCell = ((_e112 - (floor((_e112 / _e115)) * _e115)) / vec2<f32>(_e120, _e121));
    let _e125 = lum_2;
    let _e126 = posInCell;
    let _e127 = charFill(_e125, _e126);
    bit = _e127;
    let _e130 = global.u_color_mode;
    if (_e130 < 0.5f) {
        {
            fgColor = vec3<f32>(0.2f, 1f, 0.3f);
        }
    } else {
        {
            let _e137 = centerColor;
            fgColor = _e137;
        }
    }
    let _e143 = sourceColor;
    let _e144 = fgColor;
    let _e145 = bit;
    let surface_presence =         smoothstep(0.025f, 0.14f, lum_2);
    let glyph_signal = mix(_e143.xyz, _e144, vec3(_e145 * 0.82f));
    color = mix(_e143.xyz, glyph_signal, vec3(surface_presence * 0.62f));
    let _e149 = color;
    fragColor = vec4<f32>(_e149.x, _e149.y, _e149.z, sourceColor.a);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
