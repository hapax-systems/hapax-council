// Stutter — VHS-style temporal freeze / hold / replay.
//
// Uses tex_accum (previous output via temporal buffer) as the "held" frame.
// A deterministic hash on quantized time decides whether to freeze, pass through,
// or replay (rapid alternation) — giving a stuttering, tape-dropout feel.
//
// Shared uniforms (group 0) are prepended automatically by DynamicPipeline.
// We use uniforms.time from group(0) so time doesn't need to be in param_order.

struct Params {
    u_check_interval: f32,
    u_freeze_chance: f32,
    u_freeze_min: f32,
    u_freeze_max: f32,
    u_replay_frames: f32,
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

fn hash21(p: vec2<f32>) -> f32 {
    return fract(sin(dot(p, vec2<f32>(12.9898, 78.233))) * 43758.547);
}

fn hash11(x: f32) -> f32 {
    return fract(sin(x * 127.1) * 43758.547);
}

fn main_1() {
    let uv = v_texcoord_1;

    // Current frame from upstream (glitch_block output)
    let current = textureSample(tex, tex_sampler, uv);
    // Previous stutter output (temporal feedback)
    let held = textureSample(tex_accum, tex_accum_sampler, uv);

    // Quantize time into frame-rate slots (~30fps)
    let frame = floor(uniforms.time * 30.0);

    // Guard: if check_interval is tiny, just pass through
    let interval = max(global.u_check_interval, 1.0);

    // Which check slot are we in? Each slot spans `interval` frames.
    let slot = floor(frame / interval);

    // Position within the current check slot (0 .. interval-1)
    let pos = frame - (slot * interval);

    // Hash this slot to decide: do we freeze?
    let h_freeze = hash11(slot * 31.7);
    let do_freeze = h_freeze < global.u_freeze_chance;

    // Freeze duration: hash-derived, clamped to [freeze_min, freeze_max]
    let h_dur = hash11(slot * 53.3 + 7.0);
    let dur_range = max(global.u_freeze_max - global.u_freeze_min, 0.0);
    let freeze_dur = global.u_freeze_min + h_dur * dur_range;

    // Are we inside a freeze window?
    let in_freeze = do_freeze && (pos < freeze_dur);

    // Replay zone: last `replay_frames` of the freeze — rapid stutter
    let replay_start = max(freeze_dur - global.u_replay_frames, 0.0);
    let in_replay = in_freeze && (pos >= replay_start) && (global.u_replay_frames > 0.0);

    if in_replay {
        // Stutter: alternate between held and current every other frame
        // for a VHS fast-forward / rewind jitter feel
        let flicker = (frame % 2.0) < 1.0;
        // Add a subtle vertical shift on held frames for tape-slip feel
        let slip = hash21(vec2<f32>(slot, pos)) * 0.008 - 0.004;
        let slip_uv = vec2<f32>(uv.x, clamp(uv.y + slip, 0.0, 1.0));
        let held_slip = textureSample(tex_accum, tex_accum_sampler, slip_uv);
        if flicker {
            fragColor = held_slip;
        } else {
            fragColor = current;
        }
    } else if in_freeze {
        // Full freeze: hold the accumulated (previous) frame
        fragColor = held;
    } else {
        // Pass through: no stutter active
        fragColor = current;
    }

    // Clamp for Rgba8Unorm output
    fragColor = clamp(fragColor, vec4(0.0), vec4(1.0));
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let out = fragColor;
    return FragmentOutput(out);
}
