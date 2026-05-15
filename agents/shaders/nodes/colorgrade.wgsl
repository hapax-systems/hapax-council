struct Params {
    u_saturation: f32,
    u_brightness: f32,
    u_contrast: f32,
    u_sepia: f32,
    u_hue_rotate: f32,
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

fn rgb2hsv(c: vec3<f32>) -> vec3<f32> {
    var c_1: vec3<f32>;
    var K: vec4<f32> = vec4<f32>(0f, -0.33333334f, 0.6666667f, -1f);
    var p: vec4<f32>;
    var q: vec4<f32>;
    var d: f32;
    var e: f32 = 0.0000000001f;

    c_1 = c;
    let _e28 = c_1;
    let _e29 = _e28.zy;
    let _e30 = K;
    let _e31 = _e30.wz;
    let _e37 = c_1;
    let _e38 = _e37.yz;
    let _e39 = K;
    let _e40 = _e39.xy;
    let _e46 = c_1;
    let _e48 = c_1;
    p = mix(vec4<f32>(_e29.x, _e29.y, _e31.x, _e31.y), vec4<f32>(_e38.x, _e38.y, _e40.x, _e40.y), vec4(step(_e46.z, _e48.y)));
    let _e54 = p;
    let _e55 = _e54.xyw;
    let _e56 = c_1;
    let _e62 = c_1;
    let _e64 = p;
    let _e65 = _e64.yzx;
    let _e70 = p;
    let _e72 = c_1;
    q = mix(vec4<f32>(_e55.x, _e55.y, _e55.z, _e56.x), vec4<f32>(_e62.x, _e65.x, _e65.y, _e65.z), vec4(step(_e70.x, _e72.x)));
    let _e78 = q;
    let _e80 = q;
    let _e82 = q;
    d = (_e78.x - min(_e80.w, _e82.y));
    let _e89 = q;
    let _e91 = q;
    let _e93 = q;
    let _e97 = d;
    let _e99 = e;
    let _e104 = d;
    let _e105 = q;
    let _e107 = e;
    let _e110 = q;
    return vec3<f32>(abs((_e89.z + ((_e91.w - _e93.y) / ((6f * _e97) + _e99)))), (_e104 / (_e105.x + _e107)), _e110.x);
}

fn hsv2rgb(c_2: vec3<f32>) -> vec3<f32> {
    var c_3: vec3<f32>;
    var K_1: vec4<f32> = vec4<f32>(1f, 0.6666667f, 0.33333334f, 3f);
    var p_1: vec3<f32>;

    c_3 = c_2;
    let _e26 = c_3;
    let _e28 = K_1;
    let _e34 = K_1;
    p_1 = abs(((fract((_e26.xxx + _e28.xyz)) * 6f) - _e34.www));
    let _e39 = c_3;
    let _e41 = K_1;
    let _e43 = p_1;
    let _e44 = K_1;
    let _e52 = c_3;
    return (_e39.z * mix(_e41.xxx, clamp((_e43 - _e44.xxx), vec3(0f), vec3(1f)), vec3(_e52.y)));
}

fn main_1() {
    var color: vec4<f32>;
    var gray: f32;
    var sep: vec3<f32>;
    var hsv: vec3<f32>;
    var source_luma: f32;
    var surface_presence: f32;
    var graded: vec3<f32>;

    let _e14 = v_texcoord_1;
    let _e15 = textureSample(tex, tex_sampler, _e14);
    color = _e15;
    source_luma = dot(color.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    surface_presence = smoothstep(0.045f, 0.18f, source_luma);
    let _e17 = color;
    let _e19 = color;
    let _e24 = global.u_contrast;
    let _e28 = (((_e19.xyz - vec3(0.5f)) * _e24) + vec3(0.5f));
    color.x = _e28.x;
    color.y = _e28.y;
    color.z = _e28.z;
    let _e35 = color;
    let _e37 = color;
    let _e39 = global.u_brightness;
    let _e40 = (_e37.xyz * _e39);
    color.x = _e40.x;
    color.y = _e40.y;
    color.z = _e40.z;
    let _e47 = global.u_sepia;
    if (_e47 > 0f) {
        {
            let _e50 = color;
            gray = dot(_e50.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
            let _e58 = gray;
            let _e61 = gray;
            let _e64 = gray;
            sep = vec3<f32>((_e58 * 1.2f), (_e61 * 1f), (_e64 * 0.8f));
            let _e69 = color;
            let _e71 = color;
            let _e73 = sep;
            let _e74 = global.u_sepia;
            let _e76 = mix(_e71.xyz, _e73, vec3(_e74));
            color.x = _e76.x;
            color.y = _e76.y;
            color.z = _e76.z;
        }
    }
    let _e83 = color;
    let _e85 = rgb2hsv(_e83.xyz);
    hsv = _e85;
    let _e88 = hsv;
    let _e90 = global.u_hue_rotate;
    hsv.x = fract((_e88.x + (_e90 / 360f)));
    let _e96 = hsv;
    let _e98 = global.u_saturation;
    hsv.y = (_e96.y * _e98);
    let _e100 = color;
    let _e102 = hsv;
    let _e103 = hsv2rgb(_e102);
    color.x = _e103.x;
    color.y = _e103.y;
    color.z = _e103.z;
    let _e110 = color;
    let _e116 = clamp(_e110.xyz, vec3(0f), vec3(1f));
    let _e117 = color;
    graded = mix(_e117.xyz, _e116, vec3(surface_presence));
    fragColor = vec4<f32>(graded.x, graded.y, graded.z, _e117.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
