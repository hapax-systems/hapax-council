struct Params {
    u_segments: f32,
    u_center_x: f32,
    u_center_y: f32,
    u_rotation: f32,
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
    var original: vec4<f32>;
    var center: vec2<f32>;
    var uv: vec2<f32>;
    var angle: f32;
    var r: f32;
    var segAngle: f32;
    var newUV: vec2<f32>;
    var warped: vec4<f32>;
    var strength: f32;

    original = textureSample(tex, tex_sampler, v_texcoord_1);
    let _e12 = global.u_center_x;
    let _e13 = global.u_center_y;
    center = vec2<f32>(_e12, _e13);
    let _e16 = v_texcoord_1;
    let _e17 = center;
    uv = (_e16 - _e17);
    let _e20 = uv;
    let _e22 = uv;
    let _e25 = global.u_rotation;
    angle = (atan2(_e20.y, _e22.x) + _e25);
    let _e28 = uv;
    r = length(_e28);
    let _e34 = global.u_segments;
    segAngle = (6.2831855f / _e34);
    let _e37 = angle;
    let _e38 = segAngle;
    angle = (_e37 - (floor((_e37 / _e38)) * _e38));
    let _e43 = angle;
    let _e44 = segAngle;
    if (_e43 > (_e44 * 0.5f)) {
        {
            let _e48 = segAngle;
            let _e49 = angle;
            angle = (_e48 - _e49);
        }
    }
    let _e51 = center;
    let _e52 = r;
    let _e53 = angle;
    let _e55 = angle;
    newUV = (_e51 + (_e52 * vec2<f32>(cos(_e53), sin(_e55))));
    let _e61 = newUV;
    newUV = clamp(_e61, vec2(0f), vec2(1f));
    let _e67 = newUV;
    let _e68 = textureSample(tex, tex_sampler, _e67);
    warped = _e68;
    strength = clamp(((global.u_segments - 1.0f) * 0.09f) + (abs(global.u_rotation) * 0.22f), 0.0f, 0.60f);
    // Kaleidoscope is a source-bound refraction/detail operator. It must not
    // project a second full livestream scene onto the viewer plane.
    let original_luma = dot(original.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let surface_presence = smoothstep(0.025f, 0.14f, original_luma);
    let geometry_presence = max(surface_presence, 0.22f);
    let delta = warped.xyz - original.xyz;
    let edge_presence = smoothstep(0.08f, 0.44f, length(delta));
    let segment_line = 1.0f - smoothstep(0.0f, 0.055f, abs(angle - (segAngle * 0.5f)));
    let spectral_tint = vec3<f32>(0.78f, 0.18f, 0.95f);
    let detail_lift = max(delta, vec3<f32>(0.0f)) * edge_presence * 0.62f;
    let line_lift = spectral_tint * segment_line * 0.075f;
    let lifted = original.xyz + (detail_lift + line_lift) * strength * geometry_presence;
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
