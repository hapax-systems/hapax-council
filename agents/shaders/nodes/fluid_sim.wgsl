struct Params {
    u_viscosity: f32,
    u_vorticity: f32,
    u_dissipation: f32,
    u_speed: f32,
    u_time: f32,
    u_width: f32,
    u_height: f32,
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
    var prev: vec4<f32>;
    var vel: vec2<f32>;
    var advected_uv: vec2<f32>;
    var advected: vec4<f32>;
    var l: vec4<f32>;
    var r: vec4<f32>;
    var t: vec4<f32>;
    var b: vec4<f32>;
    var diffused: vec4<f32>;
    var curl: f32;
    var vort: vec2<f32>;
    var vort_len: f32;
    var inject: f32;
    var new_vel: vec2<f32>;
    var density: f32;

    let _e21 = global.u_width;
    let _e24 = global.u_height;
    texel = vec2<f32>((1f / _e21), (1f / _e24));
    let _e28 = v_texcoord_1;
    let _e29 = textureSample(tex_accum, tex_accum_sampler, _e28);
    prev = _e29;
    let _e31 = prev;
    vel = ((_e31.xy * 2f) - vec2(1f));
    let _e39 = v_texcoord_1;
    let _e40 = vel;
    let _e41 = texel;
    let _e43 = global.u_speed;
    advected_uv = (_e39 - ((_e40 * _e41) * _e43));
    let _e47 = advected_uv;
    let _e48 = textureSample(tex_accum, tex_accum_sampler, _e47);
    advected = _e48;
    let _e50 = v_texcoord_1;
    let _e51 = texel;
    let _e56 = textureSample(tex_accum, tex_accum_sampler, (_e50 - vec2<f32>(_e51.x, 0f)));
    l = _e56;
    let _e58 = v_texcoord_1;
    let _e59 = texel;
    let _e64 = textureSample(tex_accum, tex_accum_sampler, (_e58 + vec2<f32>(_e59.x, 0f)));
    r = _e64;
    let _e66 = v_texcoord_1;
    let _e68 = texel;
    let _e72 = textureSample(tex_accum, tex_accum_sampler, (_e66 - vec2<f32>(0f, _e68.y)));
    t = _e72;
    let _e74 = v_texcoord_1;
    let _e76 = texel;
    let _e80 = textureSample(tex_accum, tex_accum_sampler, (_e74 + vec2<f32>(0f, _e76.y)));
    b = _e80;
    let _e82 = advected;
    let _e83 = l;
    let _e84 = r;
    let _e86 = t;
    let _e88 = b;
    let _e92 = global.u_viscosity;
    diffused = mix(_e82, ((((_e83 + _e84) + _e86) + _e88) * 0.25f), vec4((_e92 * 10f)));
    let _e98 = r;
    let _e100 = l;
    let _e103 = t;
    let _e105 = b;
    curl = ((_e98.y - _e100.y) - (_e103.x - _e105.x));
    let _e110 = v_texcoord_1;
    let _e112 = texel;
    let _e116 = textureSample(tex_accum, tex_accum_sampler, (_e110 + vec2<f32>(0f, _e112.y)));
    let _e119 = v_texcoord_1;
    let _e121 = texel;
    let _e125 = textureSample(tex_accum, tex_accum_sampler, (_e119 - vec2<f32>(0f, _e121.y)));
    let _e129 = v_texcoord_1;
    let _e130 = texel;
    let _e135 = textureSample(tex_accum, tex_accum_sampler, (_e129 + vec2<f32>(_e130.x, 0f)));
    let _e138 = v_texcoord_1;
    let _e139 = texel;
    let _e144 = textureSample(tex_accum, tex_accum_sampler, (_e138 - vec2<f32>(_e139.x, 0f)));
    vort = vec2<f32>((abs(_e116.x) - abs(_e125.x)), (abs(_e135.y) - abs(_e144.y)));
    let _e150 = vort;
    vort_len = (length(_e150) + 0.0001f);
    let _e155 = vort;
    let _e157 = curl;
    let _e159 = global.u_vorticity;
    let _e161 = texel;
    vort = (((normalize(_e155) * _e157) * _e159) * _e161.x);
    let _e164 = v_texcoord_1;
    let _e165 = textureSample(tex, tex_sampler, _e164);
    inject = dot(_e165.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let _e173 = diffused;
    let _e180 = vort;
    let _e182 = global.u_dissipation;
    new_vel = ((((_e173.xy * 2f) - vec2(1f)) + _e180) * _e182);
    let _e185 = diffused;
    let _e187 = global.u_dissipation;
    let _e189 = inject;
    density = ((_e185.z * _e187) + (_e189 * 0.1f));
    let _e194 = new_vel;
    let _e199 = ((_e194 * 0.5f) + vec2(0.5f));
    let _e200 = density;
    fragColor = vec4<f32>(_e199.x, _e199.y, _e200, 1f);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e29 = fragColor;
    return FragmentOutput(_e29);
}
