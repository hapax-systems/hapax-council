#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;
uniform float u_check_interval;
uniform float u_freeze_chance;
uniform float u_freeze_min;
uniform float u_freeze_max;
uniform float u_replay_frames;
uniform float u_time;

// Deterministic hash functions for per-slot randomness
float hash11(float x) {
    return fract(sin(x * 127.1) * 43758.547);
}
float hash21(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.547);
}

void main() {
    vec2 uv = v_texcoord;

    // Current frame from upstream
    vec4 current = texture2D(tex, uv);
    // Previous stutter output (temporal feedback)
    vec4 held = texture2D(tex_accum, uv);

    // Quantize time into frame-rate slots (~30fps)
    float frame = floor(u_time * 30.0);

    // Guard: if check_interval is tiny, just pass through
    float interval = max(u_check_interval, 1.0);

    // Which check slot are we in?
    float slot = floor(frame / interval);

    // Position within the current check slot
    float pos = frame - (slot * interval);

    // Hash this slot to decide: do we freeze?
    float h_freeze = hash11(slot * 31.7);
    bool do_freeze = h_freeze < u_freeze_chance;

    // Freeze duration: hash-derived, clamped to [freeze_min, freeze_max]
    float h_dur = hash11(slot * 53.3 + 7.0);
    float dur_range = max(u_freeze_max - u_freeze_min, 0.0);
    float freeze_dur = u_freeze_min + h_dur * dur_range;

    // Are we inside a freeze window?
    bool in_freeze = do_freeze && (pos < freeze_dur);

    // Replay zone: last replay_frames of the freeze — rapid stutter
    float replay_start = max(freeze_dur - u_replay_frames, 0.0);
    bool in_replay = in_freeze && (pos >= replay_start) && (u_replay_frames > 0.0);

    if (in_replay) {
        // Stutter: alternate between held and current every other frame
        float flicker = mod(frame, 2.0);
        // Subtle vertical shift on held frames for tape-slip feel
        float slip = hash21(vec2(slot, pos)) * 0.008 - 0.004;
        vec2 slip_uv = vec2(uv.x, clamp(uv.y + slip, 0.0, 1.0));
        vec4 held_slip = texture2D(tex_accum, slip_uv);
        if (flicker < 1.0) {
            gl_FragColor = held_slip;
        } else {
            gl_FragColor = current;
        }
    } else if (in_freeze) {
        // Full freeze: hold the accumulated (previous) frame
        gl_FragColor = held;
    } else {
        // Pass through: no stutter active
        gl_FragColor = current;
    }

    gl_FragColor = clamp(gl_FragColor, 0.0, 1.0);
}
