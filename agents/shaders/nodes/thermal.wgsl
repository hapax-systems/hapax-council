struct Params {
    u_time: f32,
    u_width: f32,
    u_height: f32,
    u_edge_glow: f32,
    u_palette_shift: f32,
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

    p_1 = p;
    let _e16 = p_1;
    return fract((sin(dot(_e16, vec2<f32>(12.9898f, 78.233f))) * 43758.547f));
}

fn thermal_palette(t: f32) -> vec3<f32> {
    var t_1: f32;

    t_1 = t;
    let _e16 = t_1;
    t_1 = clamp(_e16, 0f, 1f);
    let _e20 = t_1;
    if (_e20 < 0.15f) {
        let _e29 = t_1;
        return mix(vec3(0f), vec3<f32>(0f, 0f, 0.6f), vec3((_e29 / 0.15f)));
    }
    let _e34 = t_1;
    if (_e34 < 0.3f) {
        let _e45 = t_1;
        return mix(vec3<f32>(0f, 0f, 0.6f), vec3<f32>(0.5f, 0f, 0.7f), vec3(((_e45 - 0.15f) / 0.15f)));
    }
    let _e52 = t_1;
    if (_e52 < 0.5f) {
        let _e63 = t_1;
        return mix(vec3<f32>(0.5f, 0f, 0.7f), vec3<f32>(0.9f, 0.1f, 0.1f), vec3(((_e63 - 0.3f) / 0.2f)));
    }
    let _e70 = t_1;
    if (_e70 < 0.65f) {
        let _e81 = t_1;
        return mix(vec3<f32>(0.9f, 0.1f, 0.1f), vec3<f32>(1f, 0.5f, 0f), vec3(((_e81 - 0.5f) / 0.15f)));
    }
    let _e88 = t_1;
    if (_e88 < 0.8f) {
        let _e99 = t_1;
        return mix(vec3<f32>(1f, 0.5f, 0f), vec3<f32>(1f, 1f, 0f), vec3(((_e99 - 0.65f) / 0.15f)));
    }
    let _e114 = t_1;
    return mix(vec3<f32>(1f, 1f, 0f), vec3<f32>(1f, 1f, 1f), vec3(((_e114 - 0.8f) / 0.2f)));
}

fn main_1() {
    var uv: vec2<f32>;
    var quantRes: vec2<f32>;
    var texel: vec2<f32>;
    var lum: f32 = 0f;
    var totalWeight: f32 = 0f;
    var dy: f32 = -2f;
    var dx: f32;
    var w: f32;
    var sampleUV: vec2<f32>;
    var palIdx: f32;
    var color: vec3<f32>;
    var bloom: f32;
    var noise: f32;

    let _e14 = v_texcoord_1;
    uv = _e14;
    let _e16 = global.u_edge_glow;
    if (_e16 < -0.5f) {
        {
            let _e20 = uv;
            let _e21 = textureSample(tex, tex_sampler, _e20);
            fragColor = _e21;
            return;
        }
    }
    let _e22 = global.u_width;
    let _e23 = global.u_height;
    quantRes = (vec2<f32>(_e22, _e23) * 0.25f);
    let _e28 = uv;
    let _e29 = quantRes;
    let _e32 = quantRes;
    uv = (floor((_e28 * _e29)) / _e32);
    let _e35 = global.u_width;
    let _e38 = global.u_height;
    texel = vec2<f32>((1f / _e35), (1f / _e38));
    loop {
        let _e49 = dy;
        if !((_e49 <= 2f)) {
            break;
        }
        {
            dx = -2f;
            loop {
                let _e59 = dx;
                if !((_e59 <= 2f)) {
                    break;
                }
                {
                    let _e66 = dx;
                    let _e67 = dx;
                    let _e69 = dy;
                    let _e70 = dy;
                    w = exp((-(((_e66 * _e67) + (_e69 * _e70))) / 4.5f));
                    let _e78 = uv;
                    let _e79 = dx;
                    let _e80 = dy;
                    let _e82 = texel;
                    sampleUV = (_e78 + ((vec2<f32>(_e79, _e80) * _e82) * 2f));
                    let _e88 = lum;
                    let _e89 = sampleUV;
                    let _e90 = textureSample(tex, tex_sampler, _e89);
                    let _e97 = w;
                    lum = (_e88 + (dot(_e90.xyz, vec3<f32>(0.299f, 0.587f, 0.114f)) * _e97));
                    let _e100 = totalWeight;
                    let _e101 = w;
                    totalWeight = (_e100 + _e101);
                }
                continuing {
                    let _e63 = dx;
                    dx = (_e63 + 1f);
                }
            }
        }
        continuing {
            let _e53 = dy;
            dy = (_e53 + 1f);
        }
    }
    let _e103 = lum;
    let _e104 = totalWeight;
    lum = (_e103 / _e104);
    let _e106 = lum;
    let _e107 = global.u_palette_shift;
    palIdx = fract((_e106 + _e107));
    let _e111 = palIdx;
    let _e112 = thermal_palette(_e111);
    color = _e112;
    let _e116 = lum;
    let _e118 = global.u_edge_glow;
    bloom = ((smoothstep(0.7f, 1f, _e116) * _e118) * 0.4f);
    let _e123 = color;
    let _e124 = bloom;
    color = (_e123 + (_e124 * vec3<f32>(1f, 0.9f, 0.7f)));
    let _e131 = uv;
    let _e134 = global.u_time;
    let _e137 = global.u_time;
    let _e142 = hash(((_e131 * 40f) + vec2<f32>((_e134 * 0.3f), (_e137 * 0.2f))));
    noise = _e142;
    let _e144 = noise;
    noise = ((_e144 - 0.5f) * 0.04f);
    let _e149 = color;
    let _e150 = noise;
    color = (_e149 + vec3(_e150));
    let _e153 = color;
    let _e158 = clamp(_e153, vec3(0f), vec3(1f));
    fragColor = vec4<f32>(_e158.x, _e158.y, _e158.z, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
