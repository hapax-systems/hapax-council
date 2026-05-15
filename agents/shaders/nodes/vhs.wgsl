struct Params {
    u_chroma_shift: f32,
    u_head_switch_y: f32,
    u_noise_band_y: f32,
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

fn hash(p: vec2<f32>) -> f32 {
    var p_1: vec2<f32>;

    p_1 = p;
    let _e18 = p_1;
    return fract((sin(dot(_e18, vec2<f32>(12.9898f, 78.233f))) * 43758.547f));
}

fn main_1() {
    var uv: vec2<f32>;
    var px: f32;
    var lineNoise: f32;
    var jitter: f32;
    var luma: f32;
    var chromaSum: vec3<f32> = vec3(0f);
    var chromaWeightTotal: f32 = 0f;
    var i: f32 = -2f;
    var weight: f32;
    var offset: f32;
    var s: vec3<f32>;
    var sLuma: f32;
    var chroma: vec3<f32>;
    var color: vec4<f32>;
    var subcarrier: f32;
    var edgeDetect: f32;
    var crosstalk: f32;
    var brightShift: f32;
    var gray: f32;
    var cool: vec3<f32>;
    var blur: vec4<f32>;
    var bandDist: f32;
    var bandWidth: f32 = 0.04f;
    var noise: f32;
    var bandIntensity: f32;
    var disp: f32;
    var displaced: vec3<f32>;
    var band2Y: f32;
    var band2Dist: f32;
    var band2Width: f32;
    var noise2_: f32;
    var band2Intensity: f32;
    var dropHash: f32;
    var lineJitter: f32;
    var scanPos: f32;
    var scanBright: f32;
    var localBright: f32;
    var gapFill: f32;
    var scanMult: f32;
    var surfacePresence: f32;
    var dropStrength: f32;

    let _e16 = v_texcoord_1;
    uv = _e16;
    let _e18 = global.u_chroma_shift;
    if (_e18 < 0.01f) {
        {
            let _e21 = uv;
            let _e22 = textureSample(tex, tex_sampler, _e21);
            fragColor = _e22;
            return;
        }
    }

    px = (1f / uniforms.resolution.x);
    let head_switch_y = clamp(global.u_head_switch_y, 0.88f, 0.995f);
    let _e27 = uv;
    if (_e27.y > head_switch_y) {
        {
            let _e31 = uv;

            let _e38 = hash(vec2<f32>(floor((_e31.y * uniforms.resolution.y)), uniforms.time));
            lineNoise = _e38;
            let _e40 = lineNoise;
            let _e45 = px;
            let head_gate = smoothstep(head_switch_y, 1f, uv.y);
            jitter = (((_e40 - 0.5f) * 12f) * _e45 * head_gate);
            let _e49 = uv;
            let _e51 = jitter;
            uv.x = (_e49.x + _e51);
        }
    }
    let _e53 = uv;
    let _e54 = textureSample(tex, tex_sampler, _e53);
    luma = dot(_e54.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    loop {
        let _e70 = i;
        if !((_e70 <= 6f)) {
            break;
        }
        {
            let _e77 = i;
            let _e79 = i;
            weight = exp(((-(_e77) * _e79) / 8f));
            let _e85 = i;
            let _e88 = global.u_chroma_shift;
            let _e92 = px;
            offset = ((((_e85 + 1f) * _e88) * 0.5f) * _e92);
            let _e95 = uv;
            let _e97 = offset;
            let _e99 = uv;
            let _e102 = textureSample(tex, tex_sampler, vec2<f32>((_e95.x + _e97), _e99.y));
            s = _e102.xyz;
            let _e105 = s;
            sLuma = dot(_e105, vec3<f32>(0.299f, 0.587f, 0.114f));
            let _e112 = chromaSum;
            let _e113 = s;
            let _e114 = sLuma;
            let _e117 = weight;
            chromaSum = (_e112 + ((_e113 - vec3(_e114)) * _e117));
            let _e120 = chromaWeightTotal;
            let _e121 = weight;
            chromaWeightTotal = (_e120 + _e121);
        }
        continuing {
            let _e74 = i;
            i = (_e74 + 1f);
        }
    }
    let _e123 = chromaSum;
    let _e124 = chromaWeightTotal;
    chroma = (_e123 / vec3(_e124));
    let _e128 = luma;
    let _e130 = chroma;
    let _e131 = (vec3(_e128) + _e130);
    color = vec4<f32>(_e131.x, _e131.y, _e131.z, 1f);
    let _e138 = uv;

    let _e148 = uv;

    subcarrier = sin(((((((_e138.x * uniforms.resolution.x) * 3.14159f) * 2f) / 4f) + ((_e148.y * uniforms.resolution.y) * 0.5f)) + (uniforms.time * 2f)));
    let _e161 = uv;
    let _e162 = px;
    let _e166 = textureSample(tex, tex_sampler, (_e161 + vec2<f32>(_e162, 0f)));
    let _e173 = uv;
    let _e174 = px;
    let _e178 = textureSample(tex, tex_sampler, (_e173 - vec2<f32>(_e174, 0f)));
    edgeDetect = abs((dot(_e166.xyz, vec3<f32>(0.299f, 0.587f, 0.114f)) - dot(_e178.xyz, vec3<f32>(0.299f, 0.587f, 0.114f))));
    let _e188 = subcarrier;
    let _e189 = edgeDetect;
    crosstalk = ((_e188 * _e189) * 0.15f);
    let _e195 = color;
    let _e197 = crosstalk;
    color.x = (_e195.x + _e197);
    let _e200 = color;
    let _e202 = crosstalk;
    color.z = (_e200.z - _e202);
    let _e204 = uv;
    if (_e204.y > head_switch_y) {
        {

            let _e209 = uv;

            let _e215 = hash(vec2<f32>(uniforms.time, floor((_e209.y * uniforms.resolution.y))));
            let head_surface_presence = smoothstep(0.025f, 0.20f, luma);
            let head_gate = smoothstep(head_switch_y, 1f, uv.y);
            brightShift = (((_e215 * 0.18f) - 0.09f) * head_surface_presence * head_gate);
            let _e221 = color;
            let _e223 = color;
            let _e225 = brightShift;
            let _e227 = (_e223.xyz + vec3(_e225));
            color.x = _e227.x;
            color.y = _e227.y;
            color.z = _e227.z;
        }
    }
    let _e234 = color;
    gray = dot(_e234.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e242 = gray;
    let _e245 = gray;
    let _e248 = gray;
    cool = vec3<f32>((_e242 * 0.85f), (_e245 * 0.95f), (_e248 * 1.1f));
    let _e253 = color;
    let _e255 = color;
    let _e257 = cool;
    let _e260 = mix(_e255.xyz, _e257, vec3(0.3f));
    color.x = _e260.x;
    color.y = _e260.y;
    color.z = _e260.z;
    let _e267 = uv;
    let _e268 = px;
    let _e272 = textureSample(tex, tex_sampler, (_e267 + vec2<f32>(_e268, 0f)));
    let _e273 = uv;
    let _e274 = px;
    let _e278 = textureSample(tex, tex_sampler, (_e273 - vec2<f32>(_e274, 0f)));
    blur = (_e272 + _e278);
    let _e281 = color;
    let _e283 = color;
    let _e285 = blur;
    let _e291 = mix(_e283.xyz, (_e285.xyz * 0.5f), vec3(0.1f));
    color.x = _e291.x;
    color.y = _e291.y;
    color.z = _e291.z;
    let _e298 = color;
    let _e300 = color;
    let _e309 = (((_e300.xyz - vec3(0.5f)) * 1.2f) + vec3(0.5f));
    color.x = _e309.x;
    color.y = _e309.y;
    color.z = _e309.z;
    surfacePresence = smoothstep(0.025f, 0.20f, luma);
    let _e316 = uv;
    let _e318 = global.u_noise_band_y;
    bandDist = abs((_e316.y - _e318));
    let _e324 = bandDist;
    let _e325 = bandWidth;
    if (_e324 < _e325) {
        {
            let _e327 = uv;

            let _e332 = hash(((_e327 * uniforms.time) * 100f));
            noise = _e332;
            let _e335 = bandDist;
            let _e336 = bandWidth;
            bandIntensity = (1f - (_e335 / _e336));
            let _e340 = uv;

            let _e349 = hash(vec2<f32>(floor((_e340.y * uniforms.resolution.y)), (uniforms.time * 5f)));
            let _e354 = px;
            disp = (((_e349 - 0.5f) * 6f) * _e354);
            let _e357 = uv;
            let _e359 = disp;
            let _e361 = uv;
            let _e364 = textureSample(tex, tex_sampler, vec2<f32>((_e357.x + _e359), _e361.y));
            displaced = _e364.xyz;
            let _e367 = color;
            let _e369 = color;
            let _e371 = displaced;
            let _e372 = noise;
            let _e378 = bandIntensity;
            let _e381 = mix(_e369.xyz, mix(_e371, vec3(_e372), vec3(0.35f)), vec3((0.22f * _e378 * surfacePresence)));
            color.x = _e381.x;
            color.y = _e381.y;
            color.z = _e381.z;
        }
    }
    let _e388 = global.u_noise_band_y;
    band2Y = fract(((_e388 * 0.7f) + 0.4f));
    let _e395 = uv;
    let _e397 = band2Y;
    band2Dist = abs((_e395.y - _e397));
    let _e401 = bandWidth;
    band2Width = (_e401 * 0.6f);
    let _e405 = band2Dist;
    let _e406 = band2Width;
    if (_e405 < _e406) {
        {
            let _e408 = uv;

            let _e413 = hash(((_e408 * uniforms.time) * 77f));
            noise2_ = _e413;
            let _e416 = band2Dist;
            let _e417 = band2Width;
            band2Intensity = (1f - (_e416 / _e417));
            let _e421 = color;
            let _e423 = color;
            let _e425 = noise2_;
            let _e428 = band2Intensity;
            let _e431 = mix(_e423.xyz, vec3(_e425), vec3((0.14f * _e428 * surfacePresence)));
            color.x = _e431.x;
            color.y = _e431.y;
            color.z = _e431.z;
        }
    }
    let _e438 = uv;

    let _e448 = hash(vec2<f32>(floor((_e438.y * uniforms.resolution.y)), floor((uniforms.time * 8f))));
    dropHash = _e448;
    let _e450 = dropHash;
    if (_e450 < 0.003f) {
        {
            let _e453 = color;
            let _e455 = color;
            dropStrength = 0.16f * surfacePresence;
            let _e461 = mix(_e455.xyz, min((_e455.xyz + vec3(0.16f)), vec3(1f)), vec3(dropStrength));
            color.x = _e461.x;
            color.y = _e461.y;
            color.z = _e461.z;
        }
    }
    let _e468 = uv;

    let _e479 = hash(vec2<f32>(floor(((_e468.y * uniforms.resolution.y) * 0.5f)), (uniforms.time * 3f)));
    lineJitter = (((_e479 - 0.5f) * 0.012f) * surfacePresence);
    let _e485 = color;
    let _e487 = color;
    let _e489 = lineJitter;
    let _e491 = (_e487.xyz + vec3(_e489));
    color.x = _e491.x;
    color.y = _e491.y;
    color.z = _e491.z;
    let _e499 = gl_FragCoord_1;
    scanPos = (_e499.y - (floor((_e499.y / 4f)) * 4f));
    let _e509 = scanPos;
    scanBright = (0.5f + (0.5f * cos(((_e509 * 3.14159f) / 2f))));
    let _e518 = color;
    localBright = dot(_e518.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e526 = localBright;
    gapFill = (_e526 * 0.3f);
    let _e531 = gapFill;
    let _e534 = scanBright;
    scanMult = mix((0.92f + (_e531 * 0.15f)), 1f, _e534);
    let _e537 = color;
    let _e539 = color;
    let _e541 = scanMult;
    let _e542 = (_e539.xyz * _e541);
    color.x = _e542.x;
    color.y = _e542.y;
    color.z = _e542.z;
    let _e549 = color;
    fragColor = clamp(_e549, vec4(0f), vec4(1f));
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>, @builtin(position) gl_FragCoord: vec4<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    gl_FragCoord_1 = gl_FragCoord;
    main_1();
    let _e25 = fragColor;
    return FragmentOutput(_e25);
}
