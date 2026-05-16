struct Params {
    u_pos_x: f32,
    u_pos_y: f32,
    u_scale_x: f32,
    u_scale_y: f32,
    u_rotation: f32,
    u_pivot_x: f32,
    u_pivot_y: f32,
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
    var pivot: vec2<f32>;
    var uv: vec2<f32>;
    var original: vec4<f32>;
    var transformed: vec4<f32>;
    var strength: f32;
    var c: f32;
    var s: f32;

    original = textureSample(tex, tex_sampler, v_texcoord_1);
    let _e18 = global.u_pivot_x;
    let _e19 = global.u_pivot_y;
    pivot = vec2<f32>(_e18, _e19);
    let _e22 = v_texcoord_1;
    let _e23 = pivot;
    uv = (_e22 - _e23);
    let _e26 = global.u_rotation;
    c = cos(_e26);
    let _e29 = global.u_rotation;
    s = sin(_e29);
    let _e32 = c;
    let _e33 = s;
    let _e34 = s;
    let _e36 = c;
    let _e40 = uv;
    uv = (mat2x2<f32>(vec2<f32>(_e32, _e33), vec2<f32>(-(_e34), _e36)) * _e40);
    let _e42 = uv;
    let _e43 = global.u_scale_x;
    let _e44 = global.u_scale_y;
    uv = (_e42 / vec2<f32>(_e43, _e44));
    let _e47 = uv;
    let _e48 = global.u_pos_x;
    let _e49 = global.u_pos_y;
    uv = (_e47 - vec2<f32>(_e48, _e49));
    let _e52 = uv;
    let _e53 = pivot;
    uv = (_e52 + _e53);
    uv = clamp(uv, vec2(0.001f), vec2(0.999f));
    let _e79 = uv;
    let _e80 = textureSample(tex, tex_sampler, _e79);
    transformed = _e80;
    strength = clamp(
        (abs(global.u_pos_x) * 12.0f) +
        (abs(global.u_pos_y) * 12.0f) +
        (abs(global.u_scale_x - 1.0f) * 5.0f) +
        (abs(global.u_scale_y - 1.0f) * 5.0f) +
        (abs(global.u_rotation) * 6.0f),
        0.0f,
        0.55f,
    );
    // Transform contributes registration tension/detail without turning the
    // whole output into a displaced duplicate layer.
    let original_luma = dot(original.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let surface_presence = smoothstep(0.025f, 0.14f, original_luma);
    let geometry_presence = max(surface_presence, 0.22f);
    let delta = transformed.xyz - original.xyz;
    let edge_presence = smoothstep(0.06f, 0.42f, length(delta));
    let pivot_dist = length(v_texcoord_1 - pivot);
    let pivot_glint = 1.0f - smoothstep(0.0f, 0.36f, pivot_dist);
    let spectral_tint = vec3<f32>(0.52f, 0.30f, 0.95f);
    let detail_lift = max(delta, vec3<f32>(0.0f)) * edge_presence * 0.64f;
    let lifted = original.xyz + (detail_lift + spectral_tint * pivot_glint * 0.030f) * strength * geometry_presence;
    fragColor = vec4<f32>(max(original.xyz, lifted), original.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e25 = fragColor;
    return FragmentOutput(_e25);
}
