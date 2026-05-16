struct Params {
    u_fade: f32,
    u_opacity: f32,
    u_blend_mode: f32,
    u_drift_x: f32,
    u_drift_y: f32,
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
    var t: f32;
    var dx: f32;
    var dy: f32;
    var acc: vec4<f32>;
    var cur: vec4<f32>;
    var r: vec3<f32>;

    t = (uniforms.time * 0.015f);
    let _e26 = global.u_drift_x;
    let _e27 = t;

    dx = (((_e26 * sin(_e27)) * 0.15f) / uniforms.resolution.x);
    let _e35 = global.u_drift_y;
    let _e36 = t;

    dy = (((_e35 * cos((_e36 * 0.7f))) * 0.15f) / uniforms.resolution.y);
    let _e46 = v_texcoord_1;
    let _e47 = dx;
    let _e48 = dy;
    let _e51 = textureSample(tex_accum, tex_accum_sampler, (_e46 + vec2<f32>(_e47, _e48)));
    acc = _e51;
    let _e53 = acc;
    let _e55 = acc;
    let _e58 = global.u_fade;
    let _e60 = (_e55.xyz * (1f - _e58));
    acc.x = _e60.x;
    acc.y = _e60.y;
    acc.z = _e60.z;
    let _e67 = v_texcoord_1;
    let _e68 = textureSample(tex, tex_sampler, _e67);
    cur = _e68;
    let _e71 = global.u_blend_mode;
    if (_e71 < 0.5f) {
        let _e74 = acc;
        let _e76 = cur;
        let _e78 = global.u_opacity;
        r = (_e74.xyz + (_e76.xyz * _e78));
    } else {
        let _e81 = global.u_blend_mode;
        if (_e81 < 1.5f) {
            let _e86 = acc;
            let _e91 = cur;
            let _e93 = global.u_opacity;
            r = (vec3(1f) - ((vec3(1f) - _e86.xyz) * (vec3(1f) - (_e91.xyz * _e93))));
        } else {
            let _e100 = global.u_blend_mode;
            if (_e100 < 2.5f) {
                let _e103 = acc;
                let _e105 = cur;
                let _e108 = global.u_opacity;
                r = ((_e103.xyz * _e105.xyz) * _e108);
            } else {
                let _e110 = global.u_blend_mode;
                if (_e110 < 3.5f) {
                    let _e113 = acc;
                    let _e115 = cur;
                    let _e117 = global.u_opacity;
                    r = abs((_e113.xyz - (_e115.xyz * _e117)));
                } else {
                    let _e122 = acc;
                    let _e125 = cur;
                    let _e128 = global.u_opacity;
                    let _e133 = acc;
                    let _e139 = cur;
                    let _e141 = global.u_opacity;
                    let _e149 = acc;
                    r = mix((((2f * _e122.xyz) * _e125.xyz) * _e128), (vec3(1f) - ((2f * (vec3(1f) - _e133.xyz)) * (vec3(1f) - (_e139.xyz * _e141)))), step(vec3(0.5f), _e149.xyz));
                }
            }
        }
    }
    let _e154 = r;
    let _e159 = clamp(_e154, vec3(0f), vec3(1f));
    let cur_luma = dot(cur.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let surface_presence =         smoothstep(0.025f, 0.14f, cur_luma);
    let temporal_strength = surface_presence
        * clamp(global.u_opacity, 0f, 0.34f)
        * clamp((1f - global.u_fade), 0f, 0.80f);
    let live_bound = mix(cur.xyz, _e159, vec3<f32>(temporal_strength));
    fragColor = vec4<f32>(live_bound.x, live_bound.y, live_bound.z, cur.a);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e31 = fragColor;
    return FragmentOutput(_e31);
}
