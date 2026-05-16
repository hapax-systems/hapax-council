struct Params {
    u_strength_x: f32,
    u_strength_y: f32,
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
var tex_b: texture_2d<f32>;
@group(1) @binding(3) 
var tex_b_sampler: sampler;
@group(2) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var uv: vec2<f32>;
    var original: vec4<f32>;
    var disp: vec4<f32>;
    var offset: vec2<f32>;
    var warped: vec4<f32>;
    var strength: f32;

    let _e10 = v_texcoord_1;
    uv = _e10;
    original = textureSample(tex, tex_sampler, uv);
    let _e12 = uv;
    let _e13 = textureSample(tex_b, tex_b_sampler, _e12);
    disp = _e13;
    let _e15 = disp;
    let _e22 = global.u_strength_x;
    let _e23 = global.u_strength_y;
    offset = ((((_e15.xy - vec2(0.5f)) * 2f) * vec2<f32>(_e22, _e23)) * 0.1f);
    let _e29 = uv;
    let _e30 = offset;
    let sample_uv = clamp((_e29 + _e30), vec2(0.001f), vec2(0.999f));
    let _e32 = textureSample(tex, tex_sampler, sample_uv);
    warped = _e32;
    strength = clamp((abs(global.u_strength_x) + abs(global.u_strength_y)) * 3.0f, 0.0f, 0.55f);
    // Displacement may reveal pressure/offset detail, but it must not replace
    // the source with a whole shifted scene copy.
    let original_luma = dot(original.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let surface_presence = smoothstep(0.025f, 0.14f, original_luma);
    let geometry_presence = max(surface_presence, 0.22f);
    let delta = warped.xyz - original.xyz;
    let edge_presence = smoothstep(0.05f, 0.38f, length(delta));
    let offset_energy = smoothstep(0.002f, 0.045f, length(offset));
    let spectral_tint = vec3<f32>(0.95f, 0.36f, 0.14f);
    let detail_lift = max(delta, vec3<f32>(0.0f)) * edge_presence * 0.72f;
    let lifted = original.xyz + (detail_lift + spectral_tint * offset_energy * 0.035f) * strength * geometry_presence;
    fragColor = vec4<f32>(max(original.xyz, lifted), original.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
