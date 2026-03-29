struct Params {
    u_threshold_low: f32,
    u_threshold_high: f32,
    u_sort_length: f32,
    u_direction: f32,
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

fn luma(c: vec3<f32>) -> f32 {
    var c_1: vec3<f32>;

    c_1 = c;
    let _e20 = c_1;
    return dot(_e20, vec3<f32>(0.299f, 0.587f, 0.114f));
}

fn main_1() {
    var uv: vec2<f32>;
    var orig: vec4<f32>;
    var lum: f32;
    var angle: f32;
    var dir: vec2<f32>;
    var texel: vec2<f32>;
    var intervalStart: i32 = 0i;
    var i: i32 = 1i;
    var sUV: vec2<f32>;
    var sLum: f32;
    var intervalEnd: i32 = 0i;
    var i_1: i32 = 1i;
    var sUV_1: vec2<f32>;
    var sLum_1: f32;
    var intervalLen: i32;
    var samples: array<vec3<f32>, 12>;
    var sampleLums: array<f32, 12>;
    var stepSize: f32;
    var i_2: i32 = 0i;
    var pos: f32;
    var sUV_2: vec2<f32>;
    var pass_: i32 = 0i;
    var j: i32;
    var tmpC: vec3<f32>;
    var tmpL: f32;
    var posInInterval: f32;
    var idx: f32;
    var idxLow: i32;
    var idxHigh: i32;
    var frac: f32;
    var valLow: vec3<f32>;
    var valHigh: vec3<f32>;
    var k: i32 = 0i;
    var sorted: vec3<f32>;

    let _e18 = v_texcoord_1;
    uv = _e18;
    let _e20 = global.u_sort_length;
    if (_e20 < 1f) {
        {
            let _e23 = uv;
            let _e24 = textureSample(tex, tex_sampler, _e23);
            fragColor = _e24;
            return;
        }
    }
    let _e25 = uv;
    let _e26 = textureSample(tex, tex_sampler, _e25);
    orig = _e26;
    let _e28 = orig;
    let _e30 = luma(_e28.xyz);
    lum = _e30;
    let _e32 = lum;
    let _e33 = global.u_threshold_low;
    let _e35 = lum;
    let _e36 = global.u_threshold_high;
    if ((_e32 < _e33) || (_e35 > _e36)) {
        {
            let _e39 = orig;
            fragColor = _e39;
            return;
        }
    }
    let _e40 = global.u_direction;
    angle = ((_e40 * 3.14159f) * 0.5f);
    let _e46 = angle;
    let _e48 = angle;
    dir = vec2<f32>(cos(_e46), sin(_e48));

    texel = vec2<f32>((1f / uniforms.resolution.x), (1f / uniforms.resolution.y));
    loop {
        let _e64 = i;
        if !((_e64 < 64i)) {
            break;
        }
        {
            let _e71 = uv;
            let _e72 = dir;
            let _e73 = texel;
            let _e75 = i;
            sUV = (_e71 - ((_e72 * _e73) * f32(_e75)));
            let _e80 = sUV;
            let _e84 = sUV;
            let _e89 = sUV;
            let _e94 = sUV;
            if ((((_e80.x < 0f) || (_e84.x > 1f)) || (_e89.y < 0f)) || (_e94.y > 1f)) {
                break;
            }
            let _e99 = sUV;
            let _e100 = textureSample(tex, tex_sampler, _e99);
            let _e102 = luma(_e100.xyz);
            sLum = _e102;
            let _e104 = sLum;
            let _e105 = global.u_threshold_low;
            let _e107 = sLum;
            let _e108 = global.u_threshold_high;
            if ((_e104 < _e105) || (_e107 > _e108)) {
                break;
            }
            let _e111 = i;
            intervalStart = _e111;
        }
        continuing {
            let _e68 = i;
            i = (_e68 + 1i);
        }
    }
    loop {
        let _e116 = i_1;
        if !((_e116 < 64i)) {
            break;
        }
        {
            let _e123 = uv;
            let _e124 = dir;
            let _e125 = texel;
            let _e127 = i_1;
            sUV_1 = (_e123 + ((_e124 * _e125) * f32(_e127)));
            let _e132 = sUV_1;
            let _e136 = sUV_1;
            let _e141 = sUV_1;
            let _e146 = sUV_1;
            if ((((_e132.x < 0f) || (_e136.x > 1f)) || (_e141.y < 0f)) || (_e146.y > 1f)) {
                break;
            }
            let _e151 = sUV_1;
            let _e152 = textureSample(tex, tex_sampler, _e151);
            let _e154 = luma(_e152.xyz);
            sLum_1 = _e154;
            let _e156 = sLum_1;
            let _e157 = global.u_threshold_low;
            let _e159 = sLum_1;
            let _e160 = global.u_threshold_high;
            if ((_e156 < _e157) || (_e159 > _e160)) {
                break;
            }
            let _e163 = i_1;
            intervalEnd = _e163;
        }
        continuing {
            let _e120 = i_1;
            i_1 = (_e120 + 1i);
        }
    }
    let _e164 = intervalStart;
    let _e165 = intervalEnd;
    intervalLen = ((_e164 + _e165) + 1i);
    let _e170 = intervalLen;
    if (_e170 < 3i) {
        {
            let _e173 = orig;
            fragColor = _e173;
            return;
        }
    }
    let _e176 = intervalLen;
    stepSize = (f32(_e176) / 12f);
    loop {
        let _e183 = i_2;
        if !((_e183 < 12i)) {
            break;
        }
        {
            let _e190 = intervalStart;
            let _e193 = stepSize;
            let _e194 = i_2;
            pos = (-(f32(_e190)) + (_e193 * f32(_e194)));
            let _e199 = uv;
            let _e200 = dir;
            let _e201 = texel;
            let _e203 = pos;
            sUV_2 = (_e199 + ((_e200 * _e201) * _e203));
            let _e207 = sUV_2;
            sUV_2 = clamp(_e207, vec2(0f), vec2(1f));
            let _e213 = i_2;
            let _e215 = sUV_2;
            let _e216 = textureSample(tex, tex_sampler, _e215);
            samples[_e213] = _e216.xyz;
            let _e218 = i_2;
            let _e220 = i_2;
            let _e222 = samples[_e220];
            let _e223 = luma(_e222);
            sampleLums[_e218] = _e223;
        }
        continuing {
            let _e187 = i_2;
            i_2 = (_e187 + 1i);
        }
    }
    loop {
        let _e226 = pass_;
        if !((_e226 < 11i)) {
            break;
        }
        {
            j = 0i;
            loop {
                let _e235 = j;
                if !((_e235 < 11i)) {
                    break;
                }
                {
                    let _e242 = j;
                    let _e244 = pass_;
                    if (_e242 >= (11i - _e244)) {
                        break;
                    }
                    let _e247 = j;
                    let _e249 = sampleLums[_e247];
                    let _e250 = j;
                    let _e254 = sampleLums[(_e250 + 1i)];
                    if (_e249 > _e254) {
                        {
                            let _e256 = j;
                            let _e258 = samples[_e256];
                            tmpC = _e258;
                            let _e260 = j;
                            let _e262 = j;
                            let _e266 = samples[(_e262 + 1i)];
                            samples[_e260] = _e266;
                            let _e267 = j;
                            let _e271 = tmpC;
                            samples[(_e267 + 1i)] = _e271;
                            let _e272 = j;
                            let _e274 = sampleLums[_e272];
                            tmpL = _e274;
                            let _e276 = j;
                            let _e278 = j;
                            let _e282 = sampleLums[(_e278 + 1i)];
                            sampleLums[_e276] = _e282;
                            let _e283 = j;
                            let _e287 = tmpL;
                            sampleLums[(_e283 + 1i)] = _e287;
                        }
                    }
                }
                continuing {
                    let _e239 = j;
                    j = (_e239 + 1i);
                }
            }
        }
        continuing {
            let _e230 = pass_;
            pass_ = (_e230 + 1i);
        }
    }
    let _e288 = intervalStart;
    let _e290 = intervalLen;
    posInInterval = (f32(_e288) / f32(_e290));
    let _e294 = posInInterval;
    idx = (_e294 * 11f);
    let _e298 = idx;
    idxLow = i32(floor(_e298));
    let _e302 = idx;
    idxHigh = i32(ceil(_e302));
    let _e306 = idxHigh;
    if (_e306 > 11i) {
        idxHigh = 11i;
    }
    let _e310 = idxLow;
    if (_e310 < 0i) {
        idxLow = 0i;
    }
    let _e314 = idx;
    let _e315 = idxLow;
    frac = (_e314 - f32(_e315));
    let _e321 = samples[0];
    valLow = _e321;
    let _e325 = samples[0];
    valHigh = _e325;
    loop {
        let _e329 = k;
        if !((_e329 < 12i)) {
            break;
        }
        {
            let _e336 = k;
            let _e337 = idxLow;
            if (_e336 == _e337) {
                let _e339 = k;
                let _e341 = samples[_e339];
                valLow = _e341;
            }
            let _e342 = k;
            let _e343 = idxHigh;
            if (_e342 == _e343) {
                let _e345 = k;
                let _e347 = samples[_e345];
                valHigh = _e347;
            }
        }
        continuing {
            let _e333 = k;
            k = (_e333 + 1i);
        }
    }
    let _e348 = valLow;
    let _e349 = valHigh;
    let _e350 = frac;
    sorted = mix(_e348, _e349, vec3(_e350));
    let _e354 = sorted;
    fragColor = vec4<f32>(_e354.x, _e354.y, _e354.z, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e25 = fragColor;
    return FragmentOutput(_e25);
}
