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

    let dim = textureDimensions(tex);
    let w = f32(dim.x);
    let h = f32(dim.y);

    // The scan slit position cycles across the frame
    var slit_pos: f32;
    if (global.u_direction < 0.5) {
        // Horizontal: slit is a vertical line sweeping left-to-right
        slit_pos = fract(uniforms.time * global.u_speed * 0.02);
        let col = uv.x;
        // How far is this column from the current slit?
        let dist = abs(col - slit_pos);
        let wrap_dist = min(dist, 1.0 - dist);
        // Columns near the slit get the current frame; far columns keep the accumulator
        if (wrap_dist < (global.u_speed * 0.02)) {
            // This column is at the slit — sample current frame
            fragColor = current;
        } else {
            // This column retains its historical value from the accumulator
            fragColor = textureSample(tex_accum, tex_accum_sampler, uv);
        }
    } else {
        // Vertical: slit is a horizontal line sweeping top-to-bottom
        slit_pos = fract(uniforms.time * global.u_speed * 0.02);
        let row = uv.y;
        let dist = abs(row - slit_pos);
        let wrap_dist = min(dist, 1.0 - dist);
        if (wrap_dist < (global.u_speed * 0.02)) {
            fragColor = current;
        } else {
            fragColor = textureSample(tex_accum, tex_accum_sampler, uv);
        }
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
