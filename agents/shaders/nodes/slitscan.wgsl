// Slit-scan — temporal-to-spatial axis replacement.
//
// Each column (or row) of the output represents a different moment in time.
// The accumulator stores the previous output; each frame, one slice is
// replaced with the current input while the rest shift. This creates the
// authentic Douglas Trumbull effect: static objects render normally while
// moving objects undergo directional size distortion proportional to their
// velocity relative to the scan direction.
//
// direction < 0.5: horizontal scan (columns represent time)
// direction >= 0.5: vertical scan (rows represent time)
// speed: how many pixels the scan slit moves per frame (1.0 = 1px/frame)

struct Params {
    u_direction: f32,
    u_speed: f32,
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
    let uv = v_texcoord_1;
    let current = textureSample(tex, tex_sampler, uv);
    if (global.u_speed <= 0.0001) {
        fragColor = current;
        return;
    }

    let luma = dot(current.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence = smoothstep(0.025, 0.14, luma);
    let geometry_presence = max(surface_presence, 0.20);
    let speed = clamp(global.u_speed, 0.0, 0.85);

    // The scan slit position cycles across the frame. Slitscan must not
    // replace the scene with the accumulator: that freezes the livestream
    // and reads as a screen pane. The accumulator is now a bounded temporal
    // smear blended back into the live surface.
    let slit_pos = fract(uniforms.time * (0.10 + speed * 0.65));
    let scan_coord = select(uv.x, uv.y, global.u_direction >= 0.5);
    let dist = abs(scan_coord - slit_pos);
    let wrap_dist = min(dist, 1.0 - dist);
    let slit_width = max(0.035, speed * 0.28);
    let slit_mask = 1.0 - smoothstep(slit_width * 0.35, slit_width, wrap_dist);

    let accumulated = textureSample(tex_accum, tex_accum_sampler, uv);
    let temporal = mix(accumulated, current, vec4<f32>(slit_mask));
    let temporal_strength = geometry_presence * clamp(0.18 + speed * 0.75, 0.0, 0.62);

    if (global.u_direction < 0.5) {
        // Horizontal scan: vertical temporal smear, but live motion remains.
        fragColor = mix(current, temporal, vec4<f32>(temporal_strength));
    } else {
        // Vertical scan: horizontal temporal smear, but live motion remains.
        fragColor = mix(current, temporal, vec4<f32>(temporal_strength));
    }

    fragColor = clamp(fragColor, vec4(0.0), vec4(1.0));
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
