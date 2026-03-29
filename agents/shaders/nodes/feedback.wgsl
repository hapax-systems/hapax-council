struct Params {
    u_decay: f32,
    u_zoom: f32,
    u_rotate: f32,
    u_blend_mode: f32,
    u_hue_shift: f32,
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
@group(0) @binding(2) 
var tex_accum: texture_2d<f32>;
@group(0) @binding(3) 
var tex_accum_sampler: sampler;
@group(1) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var center: vec2<f32> = vec2(0.5f);
    var uv: vec2<f32>;
    var cs: f32;
    var sn: f32;
    var acc: vec4<f32>;
    var a: f32;
    var c: f32;
    var s: f32;
    var hue: mat3x3<f32>;
    var cur: vec4<f32>;
    var r: vec3<f32>;

    let _e19 = v_texcoord_1;
    let _e20 = center;
    uv = (_e19 - _e20);
    let _e23 = global.u_rotate;
    cs = cos(_e23);
    let _e26 = global.u_rotate;
    sn = sin(_e26);
    let _e29 = cs;
    let _e30 = sn;
    let _e32 = sn;
    let _e33 = cs;
    let _e37 = uv;
    uv = (mat2x2<f32>(vec2<f32>(_e29, -(_e30)), vec2<f32>(_e32, _e33)) * _e37);
    let _e39 = uv;
    let _e40 = global.u_zoom;
    uv = (_e39 / vec2(_e40));
    let _e43 = uv;
    let _e44 = center;
    uv = (_e43 + _e44);
    let _e46 = uv;
    let _e47 = textureSample(tex_accum, tex_accum_sampler, _e46);
    acc = _e47;
    let _e49 = acc;
    let _e51 = acc;
    let _e54 = global.u_decay;
    let _e56 = (_e51.xyz * (1f - _e54));
    acc.x = _e56.x;
    acc.y = _e56.y;
    acc.z = _e56.z;
    let _e63 = global.u_hue_shift;
    if (_e63 > 0f) {
        {
            let _e66 = global.u_hue_shift;
            a = ((_e66 * 3.14159f) / 180f);
            let _e72 = a;
            c = cos(_e72);
            let _e75 = a;
            s = sin(_e75);
            let _e80 = c;
            let _e84 = s;
            let _e89 = c;
            let _e93 = s;
            let _e98 = c;
            let _e102 = s;
            let _e107 = c;
            let _e111 = s;
            let _e116 = c;
            let _e120 = s;
            let _e125 = c;
            let _e129 = s;
            let _e134 = c;
            let _e138 = s;
            let _e143 = c;
            let _e147 = s;
            let _e152 = c;
            let _e156 = s;
            hue = mat3x3<f32>(vec3<f32>(((0.213f + (0.787f * _e80)) - (0.213f * _e84)), ((0.213f - (0.213f * _e89)) + (0.143f * _e93)), ((0.213f - (0.213f * _e98)) - (0.787f * _e102))), vec3<f32>(((0.715f - (0.715f * _e107)) - (0.715f * _e111)), ((0.715f + (0.285f * _e116)) + (0.14f * _e120)), ((0.715f - (0.715f * _e125)) + (0.715f * _e129))), vec3<f32>(((0.072f - (0.072f * _e134)) + (0.928f * _e138)), ((0.072f - (0.072f * _e143)) - (0.283f * _e147)), ((0.072f + (0.928f * _e152)) + (0.072f * _e156))));
            let _e164 = acc;
            let _e166 = hue;
            let _e167 = acc;
            let _e169 = (_e166 * _e167.xyz);
            acc.x = _e169.x;
            acc.y = _e169.y;
            acc.z = _e169.z;
        }
    }
    let _e176 = v_texcoord_1;
    let _e177 = textureSample(tex, tex_sampler, _e176);
    cur = _e177;
    let _e180 = global.u_blend_mode;
    if (_e180 < 0.5f) {
        let _e183 = acc;
        let _e185 = cur;
        r = max(_e183.xyz, _e185.xyz);
    } else {
        let _e188 = global.u_blend_mode;
        if (_e188 < 1.5f) {
            let _e193 = acc;
            let _e198 = cur;
            r = (vec3(1f) - ((vec3(1f) - _e193.xyz) * (vec3(1f) - _e198.xyz)));
        } else {
            let _e205 = acc;
            let _e207 = cur;
            r = (_e205.xyz + _e207.xyz);
        }
    }
    let _e210 = r;
    let _e215 = clamp(_e210, vec3(0f), vec3(1f));
    fragColor = vec4<f32>(_e215.x, _e215.y, _e215.z, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e25 = fragColor;
    return FragmentOutput(_e25);
}
