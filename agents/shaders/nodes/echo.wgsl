struct Params {
    u_frame_count: f32,
    u_decay_curve: f32,
    u_blend_mode: f32,
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
    var cur: vec4<f32>;
    var acc: vec4<f32>;
    var w: f32;
    var decay: f32;
    var r: vec3<f32>;

    let _e12 = v_texcoord_1;
    let _e13 = textureSample(tex, tex_sampler, _e12);
    cur = _e13;
    let _e15 = v_texcoord_1;
    let _e16 = textureSample(tex_accum, tex_accum_sampler, _e15);
    acc = _e16;
    let _e19 = global.u_frame_count;
    if (_e19 <= 1.0f) {
        fragColor = cur;
        return;
    }
    w = max((1f / clamp(_e19, 2f, 18f)), 0.12f);
    let _e23 = w;
    let _e25 = global.u_decay_curve;
    decay = pow((1f - _e23), _e25);
    let _e29 = global.u_blend_mode;
    if (_e29 < 0.5f) {
        {
            let _e32 = acc;
            let _e34 = decay;
            let _e36 = cur;
            let _e38 = w;
            r = ((_e32.xyz * _e34) + (_e36.xyz * _e38));
        }
    } else {
        let _e41 = global.u_blend_mode;
        if (_e41 < 1.5f) {
            {
                let _e44 = acc;
                let _e46 = decay;
                let _e48 = cur;
                let _e50 = w;
                r = max((_e44.xyz * _e46), (_e48.xyz * _e50));
            }
        } else {
            {
                let _e55 = acc;
                let _e57 = decay;
                let _e62 = cur;
                let _e64 = w;
                r = (vec3(1f) - ((vec3(1f) - (_e55.xyz * _e57)) * (vec3(1f) - (_e62.xyz * _e64))));
            }
        }
    }
    let _e71 = r;
    let _e76 = clamp(_e71, vec3(0f), vec3(1f));
    let cur_luma = dot(cur.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let surface_presence =         smoothstep(0.008f, 0.09f, cur_luma);
    let echo_strength = surface_presence * clamp((1f - w) * 0.46f, 0f, 0.38f);
    let live_bound = mix(cur.xyz, _e76, vec3<f32>(echo_strength));
    fragColor = vec4<f32>(live_bound.x, live_bound.y, live_bound.z, cur.a);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
