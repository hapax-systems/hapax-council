struct Params {
    u_axis: f32,
    u_position: f32,
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

fn main_1() {
    var uv: vec2<f32>;
    var original: vec4<f32>;
    var mirrored: vec4<f32>;
    var fold_dist: f32;
    var fold_glint: f32;
    var edge_presence: f32;
    var strength: f32;

    let _e8 = v_texcoord_1;
    uv = _e8;
    original = textureSample(tex, tex_sampler, uv);
    let _e10 = global.u_axis;
    let _e13 = global.u_axis;
    if ((_e10 < 0.5f) || (_e13 > 1.5f)) {
        {
            let _e17 = uv;
            let _e19 = global.u_position;
            if (_e17.x > _e19) {
                {
                    let _e23 = global.u_position;
                    let _e25 = uv;
                    uv.x = ((2f * _e23) - _e25.x);
                }
            }
        }
    }
    let _e28 = global.u_axis;
    if (_e28 > 0.5f) {
        {
            let _e31 = uv;
            let _e33 = global.u_position;
            if (_e31.y > _e33) {
                {
                    let _e37 = global.u_position;
                    let _e39 = uv;
                    uv.y = ((2f * _e37) - _e39.y);
                }
            }
        }
    }
    uv = clamp(uv, vec2(0.001f), vec2(0.999f));
    let _e42 = uv;
    let _e43 = textureSample(tex, tex_sampler, _e42);
    mirrored = _e43;
    fold_dist = abs(select(v_texcoord_1.x, v_texcoord_1.y, global.u_axis > 0.5f) - global.u_position);
    fold_glint = 1.0f - smoothstep(0.0f, 0.14f, fold_dist);
    edge_presence = smoothstep(0.08f, 0.42f, length(mirrored.xyz - original.xyz));
    strength = clamp((1.0f - global.u_position) * 0.26f, 0.0f, 0.26f);
    // Mirror is repaired as a fold/glint operator, not a full-frame scene
    // clone. It can add local light and edge tension, but it must not project
    // a second livestream layout onto the viewer plane.
    let fold_tint = vec3<f32>(0.20f, 0.62f, 0.95f);
    let detail_lift = max(mirrored.xyz - original.xyz, vec3<f32>(0.0f)) * edge_presence;
    let lifted = original.xyz + (detail_lift * 0.55f + fold_tint * fold_glint * 0.18f) * strength;
    fragColor = vec4<f32>(max(original.xyz, lifted), original.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e15 = fragColor;
    return FragmentOutput(_e15);
}
