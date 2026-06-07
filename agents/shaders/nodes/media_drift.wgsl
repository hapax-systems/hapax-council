// media_drift.wgsl — GPU port of quake_media_drift.apply_frame_drift.
//
// One fragment pass per screwm media slot: the screwm drift vocabulary applied
// to a camera/OARB/atlas/ticker/reverie texture, driven by the DriftState
// uniforms with per-receiver gain + camera damping. Reference (vocabulary, not
// a pixel oracle): scripts/quake_media_drift.py.
//
// The texture is sampled in RGB (the Bgra8Unorm format swizzles BGRA storage to
// RGBA in the sampler), so all math here is RGB 0..1; the Python's 0..255
// additive coefficients are scaled by 1/255 (K8 below).
//
// v2: intensity gate, reverie tonemap, chroma-roll, source-bound feedback
//     trails, edge, glitch blocks, saturation, hash-noise, scanlines, tonal-pulse.

const K8: f32 = 0.003921569; // 1/255 — scale Python 0..255 additive terms to 0..1

// DriftState scalar indices (must match media_drift.rs DriftState field order).
const I_REAL_SOURCE: u32 = 0u;
const I_ACTIVE_RATIO: u32 = 1u;
const I_ACTIVE_SLOT_RATIO: u32 = 2u;
const I_ACTIVE_EFFECT_RATIO: u32 = 3u;
const I_FAST_RATIO: u32 = 4u;
const I_SLOW_RATIO: u32 = 5u;
const I_KIND_VARIANCE: u32 = 6u;
const I_MAX_DELTA: u32 = 7u;
const I_REGION_COUNT: u32 = 8u;
const I_TONAL: u32 = 9u;
const I_ATMOSPHERIC: u32 = 10u;
const I_TEMPORAL: u32 = 11u;
const I_TEXTURE: u32 = 12u;
const I_EDGE: u32 = 13u;
const I_COMPOSITING: u32 = 14u;
const I_VISUAL_NOISE: u32 = 15u;
const I_VISUAL_DRIFT: u32 = 16u;
const I_VISUAL_COLOR: u32 = 17u;
const I_VISUAL_FEEDBACK: u32 = 18u;
const I_VISUAL_APERTURE: u32 = 19u;
const I_VISUAL_PARAM_PRESSURE: u32 = 20u;
const I_MODE_TONAL: u32 = 21u;
const I_MODE_ATMOSPHERIC: u32 = 22u;
const I_MODE_TEMPORAL: u32 = 23u;
const I_MODE_TEXTURE: u32 = 24u;
const I_MODE_EDGE: u32 = 25u;
const I_MODE_COMPOSITING: u32 = 26u;

// receiver_class codes (ReceiverClass::as_u32)
const RC_CAMERA: u32 = 0u;
const RC_OARB: u32 = 1u;
const RC_TICKER: u32 = 2u;
const RC_ATLAS: u32 = 3u;
const RC_REVERIE: u32 = 4u;
const PROJ_FLAT: u32 = 0u;
const PROJ_SPHERE_FRONT: u32 = 1u;

struct DriftUniforms {
    scalars: array<vec4<f32>, 7>, // 28 slots; [0..27) = DriftState, [27] unused
    frame_meta: vec4<f32>,        // (now, frame, intensity_scale, min_chroma_px)
    slot_dims: vec4<u32>,         // (receiver_class, width, height, _pad)
    projection: vec4<u32>,        // (projection_code, raw_width, raw_height, _pad)
    projection_color: vec4<f32>,  // (background_r, background_g, background_b, _pad)
};

@group(0) @binding(0) var<uniform> U: DriftUniforms;
@group(0) @binding(1) var src_tex: texture_2d<f32>;
@group(0) @binding(2) var src_samp: sampler;
@group(0) @binding(3) var prev_tex: texture_2d<f32>;

fn S(i: u32) -> f32 { return U.scalars[i / 4u][i % 4u]; }
fn clamp01(v: f32) -> f32 { return clamp(v, 0.0, 1.0); }

// Narkowicz ACES-fitted filmic tonemap. Maps scene-referred RGB (incl. >1 drift
// peaks) to display [0,1] with a smooth highlight shoulder instead of a hard clamp
// (the hard clamp flat-blew-out: any region >1 became flat white). aces(1.0)~=0.80,
// aces(3.0)~=0.95 -> bright drift rolls off, never flat-white (rich AND not blown).
fn aces_tonemap(x: vec3<f32>) -> vec3<f32> {
    let c = max(x, vec3<f32>(0.0));
    return clamp((c * (2.51 * c + 0.03)) / (c * (2.43 * c + 0.59) + 0.14),
                 vec3<f32>(0.0), vec3<f32>(1.0));
}

// DriftState.intensity property (quake_media_drift.py:71-93).
fn base_intensity() -> f32 {
    let mode_pressure = max(max(max(S(I_MODE_TONAL), S(I_MODE_ATMOSPHERIC)),
                                max(S(I_MODE_TEMPORAL), S(I_MODE_TEXTURE))),
                            max(S(I_MODE_EDGE), S(I_MODE_COMPOSITING)));
    return clamp01(0.34
        + S(I_ACTIVE_RATIO) * 0.20
        + S(I_ACTIVE_EFFECT_RATIO) * 0.14
        + S(I_KIND_VARIANCE) * 0.14
        + S(I_VISUAL_PARAM_PRESSURE) * 0.14
        + S(I_VISUAL_DRIFT) * 0.12
        + S(I_MAX_DELTA) * 0.10
        + S(I_FAST_RATIO) * 0.07
        + S(I_SLOW_RATIO) * 0.05
        + mode_pressure * 0.08
        + S(I_REAL_SOURCE) * 0.06);
}

// Receiver gain (_receiver_gain). receiver_class is the resolved enum; gain is
// passed implicitly via the class. We re-derive it here to keep the uniform lean.
fn receiver_gain(rc: u32) -> f32 {
    switch rc {
        case 0u: { return 1.26; } // camera
        case 1u: { return 1.52; } // oarb
        case 2u: { return 1.62; } // ticker
        case 3u: { return 1.66; } // atlas
        case 4u: { return 1.46; } // reverie
        default: { return 1.0; }  // other
    }
}

// Cheap hash → [0,1) for per-fragment stochastic noise (stands in for the
// Python rng; visually equivalent, not bit-identical).
fn hash21(p: vec2<f32>, seed: f32) -> f32 {
    let h = dot(p, vec2<f32>(127.1, 311.7)) + seed * 0.017;
    return fract(sin(h) * 43758.5453123);
}

// _apply_reverie_tonemap (quake_media_drift.py:172-183), RGB 0..1.
fn reverie_tonemap(rgb: vec3<f32>, intensity: f32) -> vec3<f32> {
    let luma = rgb.r * 0.299 + rgb.g * 0.587 + rgb.b * 0.114;
    let gray = vec3<f32>(luma);
    let saturation = 1.60 + intensity * 0.70;
    let contrast = 1.22 + intensity * 0.28;
    let pivot = (170.0 - intensity * 4.0) * K8;
    let lift = (22.0 + intensity * 8.0) * K8;
    var toned = gray + (rgb - gray) * saturation;
    toned = (toned - pivot) * contrast + lift;
    toned *= vec3<f32>(1.08, 0.68, 1.12);
    return clamp(toned, vec3<f32>(0.0), vec3<f32>(1.0));
}

fn sphere_background(uv: vec2<f32>) -> vec3<f32> {
    let out_w = f32(U.slot_dims.y);
    let out_h = f32(U.slot_dims.z);
    let y = clamp(uv.y, 0.0, 1.0);
    let shade = 0.54 + 0.30 * (1.0 - abs(y - 0.5) * 2.0);
    let x_px = floor(clamp(uv.x, 0.0, 0.999999) * out_w);
    let y_px = floor(y * out_h);
    let guide_period = max(8.0, floor(out_w / 16.0));
    let guide_rem = x_px - floor(x_px / guide_period) * guide_period;
    let guide = guide_rem < 1.0 || abs(y_px - floor(out_h * 0.5)) <= 1.0;
    let boost = select(1.0, 1.26, guide);
    return clamp(U.projection_color.rgb * shade * boost, vec3<f32>(0.0), vec3<f32>(1.0));
}

fn sample_projected(uv: vec2<f32>) -> vec4<f32> {
    let projection_code = U.projection.x;
    if (projection_code == PROJ_FLAT) {
        return textureSample(src_tex, src_samp, uv);
    }
    if (projection_code != PROJ_SPHERE_FRONT) {
        return textureSample(src_tex, src_samp, uv);
    }

    let out_w = f32(U.slot_dims.y);
    let out_h = f32(U.slot_dims.z);
    let raw_w = f32(U.projection.y);
    let raw_h = f32(U.projection.z);
    let bg = vec4<f32>(sphere_background(uv), 1.0);
    if (raw_w <= 0.0 || raw_h <= 0.0) {
        return bg;
    }
    if (uv.x < 0.0 || uv.x >= 1.0 || uv.y < 0.0 || uv.y >= 1.0) {
        return bg;
    }

    let px = floor(uv.x * out_w);
    let py = floor(uv.y * out_h);
    let offset_y = floor((out_h - raw_h) * 0.5);
    if (py < offset_y || py >= offset_y + raw_h) {
        return bg;
    }

    let seam_left_width = floor(raw_w * 0.5);
    let seam_right_width = raw_w - seam_left_width;
    let right_edge_x = out_w - seam_left_width;
    var sx = -1.0;
    if (px < seam_right_width) {
        sx = seam_left_width + px;
    } else if (px >= right_edge_x) {
        sx = px - right_edge_x;
    }
    if (sx < 0.0 || sx >= raw_w) {
        return bg;
    }

    let sy = py - offset_y;
    // Preserve the old CPU path's mirror+seam orientation without an FFmpeg hflip.
    // The producer now sends the raw media frame; sphere-front owns the mirror here.
    let mirrored_sx = raw_w - sx - 1.0;
    return textureSample(src_tex, src_samp, vec2<f32>((mirrored_sx + 0.5) / raw_w, (sy + 0.5) / raw_h));
}

struct VsOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VsOut {
    var p = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0), vec2<f32>(3.0, -1.0), vec2<f32>(-1.0, 3.0));
    var o: VsOut;
    o.pos = vec4<f32>(p[vi], 0.0, 1.0);
    // Flip V: clip-space is y-up, textures are y-down. Without this the slot
    // renders upside-down (verified 2026-05-30 headless test).
    o.uv = p[vi] * vec2<f32>(0.5, -0.5) + vec2<f32>(0.5, 0.5);
    return o;
}

@fragment
fn fs_main(in: VsOut) -> @location(0) vec4<f32> {
    let rc = U.slot_dims.x;
    let w = f32(U.slot_dims.y);
    let h = f32(U.slot_dims.z);
    let now = U.frame_meta.x;
    let frame = U.frame_meta.y;
    let intensity_scale = U.frame_meta.z;
    let min_chroma_px = U.frame_meta.w;
    let is_camera = rc == RC_CAMERA;
    let is_oarb = rc == RC_OARB;
    let is_atlas = rc == RC_ATLAS;
    let is_ticker = rc == RC_TICKER;
    let texel = vec2<f32>(1.0 / w, 1.0 / h);
    let min_dim = max(1.0, min(w, h));

    let src = sample_projected(in.uv);
    var rgb = src.rgb;

    // ── intensity (cadence-gated) ────────────────────────────────────────────
    let fast_wave = 0.5 + 0.5 * sin(now * (1.70 + S(I_FAST_RATIO) * 1.20) + frame * 0.31);
    let slow_wave = 0.5 + 0.5 * sin(now * (0.17 + S(I_SLOW_RATIO) * 0.18) + frame * 0.043);
    let mutation_pressure = clamp01(0.35 + S(I_KIND_VARIANCE) * 0.45 + S(I_ACTIVE_EFFECT_RATIO) * 0.20);
    let cadence_gain = clamp01(0.62 + S(I_FAST_RATIO) * fast_wave * 0.42 + S(I_SLOW_RATIO) * slow_wave * 0.26);
    let intensity = clamp01(base_intensity() * receiver_gain(rc) * intensity_scale * cadence_gain);
    if (intensity <= 0.02) {
        return vec4<f32>(rgb, 1.0);
    }

    // ── reverie tonemap (reverie receivers only) ─────────────────────────────
    if (rc == RC_REVERIE) {
        rgb = reverie_tonemap(rgb, intensity);
    }

    let phase = now * (0.34 + S(I_REGION_COUNT) * 0.42 + S(I_FAST_RATIO) * 0.28)
              + frame * (0.017 + S(I_KIND_VARIANCE) * 0.011);

    // ── chroma roll (R/B opposed shift) ──────────────────────────────────────
    var chroma_cap = select(96.0, 38.0, is_camera);
    if (is_oarb || is_atlas) { chroma_cap = 112.0; }
    var chroma_px = round(min_dim * (0.0040 + 0.0100 * intensity + 0.0065 * S(I_COMPOSITING)
        + 0.0045 * S(I_ACTIVE_SLOT_RATIO) + 0.0050 * mutation_pressure + 0.0035 * S(I_MODE_ATMOSPHERIC)));
    chroma_px = max(min_chroma_px, min(chroma_cap, chroma_px));
    let dx = round(sin(phase) * chroma_px);
    let dy = round(cos(phase * 0.73) * max(1.0, chroma_px * 0.5));
    let red = sample_projected(in.uv + vec2<f32>(dx, dy) * texel).r;
    let blue = sample_projected(in.uv - vec2<f32>(dx, dy) * texel).b;
    var chroma_mix = min(0.88, 0.30 + S(I_VISUAL_COLOR) * 0.20 + S(I_COMPOSITING) * 0.22
        + S(I_MODE_COMPOSITING) * 0.14 + S(I_MODE_ATMOSPHERIC) * 0.10 + intensity * 0.24);
    if (is_camera) { chroma_mix = min(chroma_mix, 0.60); }
    rgb.r = rgb.r * (1.0 - chroma_mix) + red * chroma_mix;
    rgb.b = rgb.b * (1.0 - chroma_mix) + blue * chroma_mix;

    // -- source-bound feedback trails ---------------------------------------
    // Previous-frame feedback is part of the media receiver vocabulary, not a
    // scene-wide glass pane. Keep it non-camera and brighten-biased so it cannot
    // become a global dim/fade over the fourth wall.
    let feedback_pressure = clamp01(S(I_VISUAL_FEEDBACK) * 0.46
        + S(I_TEMPORAL) * 0.24
        + S(I_MODE_TEMPORAL) * 0.24
        + S(I_COMPOSITING) * 0.16
        + intensity * 0.20);
    if (!is_camera && feedback_pressure > 0.03 && frame > 1.0) {
        let trail_px = round(min_dim * (0.004 + feedback_pressure * 0.030 + S(I_SLOW_RATIO) * 0.014));
        let trail_a = vec2<f32>(sin(phase * 0.83), cos(phase * 0.61)) * trail_px * texel;
        let trail_b = vec2<f32>(cos(phase * 0.47), sin(phase * 0.97)) * trail_px * 0.48 * texel;
        let prev_a = textureSample(prev_tex, src_samp, clamp(in.uv - trail_a, vec2<f32>(0.0), vec2<f32>(1.0))).rgb;
        let prev_b = textureSample(prev_tex, src_samp, clamp(in.uv + trail_b, vec2<f32>(0.0), vec2<f32>(1.0))).rgb;
        let feedback_rgb = max(prev_a * vec3<f32>(1.08, 0.92, 1.16), prev_b * vec3<f32>(0.92, 1.05, 1.12));
        let feedback_cap = select(0.48, 0.30, is_camera);
        let feedback_mix = min(feedback_cap, 0.060 + feedback_pressure * 0.32 + S(I_MODE_TEMPORAL) * 0.10);
        rgb = mix(rgb, max(rgb, feedback_rgb), vec3<f32>(feedback_mix));
    }

    // ── saturation ───────────────────────────────────────────────────────────
    var luma = rgb.r * 0.299 + rgb.g * 0.587 + rgb.b * 0.114;
    var saturation = 1.0 + intensity * (0.18 + S(I_TONAL) * 0.16 + S(I_VISUAL_COLOR) * 0.14 + S(I_MODE_TONAL) * 0.14);
    if (is_camera) { saturation = min(saturation, 1.42); }
    rgb = vec3<f32>(luma) + (rgb - vec3<f32>(luma)) * saturation;

    // ── edge accent (luma gradient → R/B) ────────────────────────────────────
    luma = rgb.r * 0.299 + rgb.g * 0.587 + rgb.b * 0.114;
    let lx = sample_projected(in.uv + vec2<f32>(texel.x, 0.0));
    let ly = sample_projected(in.uv + vec2<f32>(0.0, texel.y));
    let lumx = lx.r * 0.299 + lx.g * 0.587 + lx.b * 0.114;
    let lumy = ly.r * 0.299 + ly.g * 0.587 + ly.b * 0.114;
    var edge_gain = select(1.18, 0.72, is_camera);
    if (is_oarb || is_atlas) { edge_gain = 1.34; }
    var edge_cap = select(64.0, 34.0, is_camera) * K8;
    if (is_oarb || is_atlas) { edge_cap = 76.0 * K8; }
    let edge = clamp((abs(lumx - luma) + abs(lumy - luma)) * edge_gain
        * (0.018 + S(I_EDGE) * 0.029 + S(I_MODE_EDGE) * 0.022 + intensity * 0.018), 0.0, edge_cap);
    rgb.r += edge * (1.8 + S(I_VISUAL_DRIFT));
    rgb.b += edge * (1.1 + S(I_TONAL));

    // -- glitch blocks -------------------------------------------------------
    // Block displacement is receiver-local and hash-gated by drift pressure.
    // Cameras are damped; atlas/ticker/OARB get the fuller mutation vocabulary.
    let glitch_pressure = clamp01(S(I_TEXTURE) * 0.30
        + S(I_MODE_TEXTURE) * 0.28
        + S(I_COMPOSITING) * 0.20
        + S(I_MODE_COMPOSITING) * 0.20
        + S(I_FAST_RATIO) * 0.12
        + intensity * 0.18);
    if (glitch_pressure > 0.04) {
        let block_px = max(8.0, round(min_dim / (18.0 + S(I_REGION_COUNT) * 22.0 + glitch_pressure * 24.0)));
        let pixel = in.uv * vec2<f32>(w, h);
        let block = floor(pixel / block_px);
        let gate = hash21(block, frame + floor(phase * 5.0));
        let gate_floor = select(0.34, 0.14, is_camera);
        let gate_span = select(0.34, 0.20, is_camera);
        if (gate < gate_floor + glitch_pressure * gate_span) {
            let offset_seed = hash21(block + vec2<f32>(17.0, 29.0), frame);
            let offset_px = round((offset_seed - 0.5) * min(56.0, 10.0 + glitch_pressure * 72.0));
            let vertical_seed = hash21(block + vec2<f32>(41.0, 7.0), frame + 11.0);
            let vertical_px = round((vertical_seed - 0.5) * min(24.0, 4.0 + S(I_MODE_TEXTURE) * 38.0));
            let shifted_uv = clamp(in.uv + vec2<f32>(offset_px, vertical_px) * texel, vec2<f32>(0.0), vec2<f32>(1.0));
            let split_uv = clamp(in.uv - vec2<f32>(offset_px * 0.48, 0.0) * texel, vec2<f32>(0.0), vec2<f32>(1.0));
            let displaced = sample_projected(shifted_uv).rgb;
            let split = sample_projected(split_uv).rgb;
            let glitch_rgb = vec3<f32>(
                max(displaced.r, split.b * 0.82),
                displaced.g * (0.82 + S(I_TONAL) * 0.16),
                max(split.b, displaced.r * 0.58)
            );
            let glitch_mix = min(select(0.58, 0.24, is_camera), 0.10 + glitch_pressure * 0.44);
            rgb = mix(rgb, glitch_rgb, vec3<f32>(glitch_mix));
        }
    }

    // ── noise ────────────────────────────────────────────────────────────────
    if (S(I_VISUAL_NOISE) > 0.02 || S(I_TEXTURE) > 0.02 || S(I_MODE_TEXTURE) > 0.02) {
        var noise_amp = 2.0 + 14.0 * min(1.0, S(I_VISUAL_NOISE) * 0.55 + S(I_TEXTURE) * 0.45);
        noise_amp += 8.0 * S(I_MODE_TEXTURE) + 4.0 * fast_wave * S(I_FAST_RATIO);
        if (is_oarb || is_atlas || is_ticker) { noise_amp *= 1.24; }
        if (is_camera) { noise_amp *= 0.40; }
        let n = (hash21(in.uv * vec2<f32>(w, h), frame) - 0.5) * 2.0 * noise_amp * K8;
        rgb.r += n * 0.72;
        rgb.g += n * 0.32;
        rgb.b -= n * 0.55;
    }

    // ── scanlines ────────────────────────────────────────────────────────────
    if (S(I_TEXTURE) > 0.04 || S(I_MODE_TEXTURE) > 0.04) {
        let period = max(3.0, round(min_dim / (18.0 + 26.0 * S(I_TEXTURE) + 18.0 * S(I_MODE_TEXTURE))));
        let thickness = max(1.0, round(period * (0.06 + 0.05 * S(I_FAST_RATIO))));
        let offset = round((phase * 18.0) % period);
        let yrow = floor(in.uv.y * h);
        if (((yrow + offset) % period) < thickness) {
            var line_strength = (4.0 + 28.0 * intensity * (0.45 + S(I_TEXTURE) + S(I_MODE_TEXTURE))) * K8;
            if (is_oarb || is_atlas || is_ticker) { line_strength *= 1.28; }
            if (is_camera) { line_strength *= 0.50; }
            rgb.r += line_strength * 0.72;
            rgb.g += line_strength * 0.18;
            rgb.b -= line_strength * 0.36;
        }
    }

    // ── tonal pulse (cyan/magenta ↔ amber) ───────────────────────────────────
    let pulse = 0.5 + 0.5 * sin(phase * 0.67);
    let cyan_magenta = vec3<f32>(
        1.0 + S(I_VISUAL_DRIFT) * 0.12 + S(I_MODE_ATMOSPHERIC) * 0.08,
        0.94 + S(I_SLOW_RATIO) * 0.04,
        1.0 + S(I_COMPOSITING) * 0.15 + S(I_MODE_COMPOSITING) * 0.09);
    let amber = vec3<f32>(0.93, 1.0 + S(I_TONAL) * 0.06, 1.0 + S(I_TONAL) * 0.13);
    rgb *= cyan_magenta * pulse + amber * (1.0 - pulse);

    return vec4<f32>(aces_tonemap(rgb), 1.0);
}
