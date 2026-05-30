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
// v1 (this file): intensity gate, reverie tonemap, chroma-roll, edge, saturation,
//                 hash-noise, scanlines, tonal-pulse.
// v2 (TODO): feedback-trails + glitch-blocks — both need the per-slot previous
//            frame (ping-pong). Wire when the service holds a prev texture.

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
const RC_REVERIE: u32 = 4u;

struct DriftUniforms {
    scalars: array<vec4<f32>, 7>, // 28 slots; [0..27) = DriftState, [27] unused
    frame_meta: vec4<f32>,        // (now, frame, intensity_scale, min_chroma_px)
    slot_dims: vec4<u32>,         // (receiver_class, width, height, _pad)
};

@group(0) @binding(0) var<uniform> U: DriftUniforms;
@group(0) @binding(1) var src_tex: texture_2d<f32>;
@group(0) @binding(2) var src_samp: sampler;

fn S(i: u32) -> f32 { return U.scalars[i / 4u][i % 4u]; }
fn clamp01(v: f32) -> f32 { return clamp(v, 0.0, 1.0); }

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
        case 0u: { return 1.12; } // camera
        case 1u: { return 1.38; } // oarb
        case 2u: { return 1.62; } // ticker
        case 3u: { return 1.42; } // atlas
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
    let texel = vec2<f32>(1.0 / w, 1.0 / h);
    let min_dim = max(1.0, min(w, h));

    let src = textureSample(src_tex, src_samp, in.uv);
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
    let chroma_cap = select(72.0, 34.0, is_camera);
    var chroma_px = round(min_dim * (0.0040 + 0.0100 * intensity + 0.0065 * S(I_COMPOSITING)
        + 0.0045 * S(I_ACTIVE_SLOT_RATIO) + 0.0050 * mutation_pressure + 0.0035 * S(I_MODE_ATMOSPHERIC)));
    chroma_px = max(min_chroma_px, min(chroma_cap, chroma_px));
    let dx = round(sin(phase) * chroma_px);
    let dy = round(cos(phase * 0.73) * max(1.0, chroma_px * 0.5));
    let red = textureSample(src_tex, src_samp, in.uv + vec2<f32>(dx, dy) * texel).r;
    let blue = textureSample(src_tex, src_samp, in.uv - vec2<f32>(dx, dy) * texel).b;
    var chroma_mix = min(0.88, 0.30 + S(I_VISUAL_COLOR) * 0.20 + S(I_COMPOSITING) * 0.22
        + S(I_MODE_COMPOSITING) * 0.14 + S(I_MODE_ATMOSPHERIC) * 0.10 + intensity * 0.24);
    if (is_camera) { chroma_mix = min(chroma_mix, 0.52); }
    rgb.r = rgb.r * (1.0 - chroma_mix) + red * chroma_mix;
    rgb.b = rgb.b * (1.0 - chroma_mix) + blue * chroma_mix;

    // TODO v2: feedback-trails (needs per-slot previous frame, ping-pong).

    // ── saturation ───────────────────────────────────────────────────────────
    var luma = rgb.r * 0.299 + rgb.g * 0.587 + rgb.b * 0.114;
    var saturation = 1.0 + intensity * (0.18 + S(I_TONAL) * 0.16 + S(I_VISUAL_COLOR) * 0.14 + S(I_MODE_TONAL) * 0.14);
    if (is_camera) { saturation = min(saturation, 1.34); }
    rgb = vec3<f32>(luma) + (rgb - vec3<f32>(luma)) * saturation;

    // ── edge accent (luma gradient → R/B) ────────────────────────────────────
    luma = rgb.r * 0.299 + rgb.g * 0.587 + rgb.b * 0.114;
    let lx = textureSample(src_tex, src_samp, in.uv + vec2<f32>(texel.x, 0.0));
    let ly = textureSample(src_tex, src_samp, in.uv + vec2<f32>(0.0, texel.y));
    let lumx = lx.r * 0.299 + lx.g * 0.587 + lx.b * 0.114;
    let lumy = ly.r * 0.299 + ly.g * 0.587 + ly.b * 0.114;
    let edge_gain = select(1.0, 0.58, is_camera);
    let edge_cap = select(48.0, 28.0, is_camera) * K8;
    let edge = clamp((abs(lumx - luma) + abs(lumy - luma)) * edge_gain
        * (0.012 + S(I_EDGE) * 0.021 + S(I_MODE_EDGE) * 0.016 + intensity * 0.012), 0.0, edge_cap);
    rgb.r += edge * (1.8 + S(I_VISUAL_DRIFT));
    rgb.b += edge * (1.1 + S(I_TONAL));

    // TODO v2: glitch-blocks (hash-seeded block displacement).

    // ── noise ────────────────────────────────────────────────────────────────
    if (S(I_VISUAL_NOISE) > 0.02 || S(I_TEXTURE) > 0.02 || S(I_MODE_TEXTURE) > 0.02) {
        var noise_amp = 2.0 + 14.0 * min(1.0, S(I_VISUAL_NOISE) * 0.55 + S(I_TEXTURE) * 0.45);
        noise_amp += 8.0 * S(I_MODE_TEXTURE) + 4.0 * fast_wave * S(I_FAST_RATIO);
        if (is_camera) { noise_amp *= 0.28; }
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
            if (is_camera) { line_strength *= 0.35; }
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

    return vec4<f32>(clamp(rgb, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0);
}
