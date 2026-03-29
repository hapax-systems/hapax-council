// Content layer — 9-dimensional spatial modulation, screen blend
//
// Samples up to 4 content texture slots, modulates their UV coordinates
// and appearance using 9 expressive dimensions, then screen-blends
// onto the compositor output.
//
// Bachelardian phenomenology:
// - Content materializes FROM the procedural field (noise-gated crystallization)
// - Low salience incubates at periphery, migrates inward with salience
// - Content arrives from off-screen (intimate immensity)
// - The rendering IS the reverie, not a report of it

struct ContentUniforms {
    slot_opacities: vec4<f32>,
    intensity: f32,
    tension: f32,
    depth: f32,
    coherence: f32,
    spectral_color: f32,
    temporal_distortion: f32,
    degradation: f32,
    pitch_displacement: f32,
    formant_character: f32,
    time: f32,
    _pad0: f32,
    _pad1: f32,
};

@group(0) @binding(0) var<uniform> u: ContentUniforms;
@group(0) @binding(1) var composite_tex: texture_2d<f32>;
@group(0) @binding(2) var slot0_tex: texture_2d<f32>;
@group(0) @binding(3) var slot1_tex: texture_2d<f32>;
@group(0) @binding(4) var slot2_tex: texture_2d<f32>;
@group(0) @binding(5) var slot3_tex: texture_2d<f32>;
@group(0) @binding(6) var samp: sampler;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

// --- Vertex ---

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VertexOutput {
    // Full-screen triangle
    let x = f32(i32(vi & 1u)) * 4.0 - 1.0;
    let y = f32(i32(vi >> 1u)) * 4.0 - 1.0;
    var out: VertexOutput;
    out.position = vec4<f32>(x, y, 0.0, 1.0);
    out.uv = vec2<f32>((x + 1.0) * 0.5, 1.0 - (y + 1.0) * 0.5);
    return out;
}

// --- Utility ---

fn hash21(p: vec2<f32>) -> f32 {
    var p3 = fract(vec3<f32>(p.x, p.y, p.x) * 0.1031);
    p3 = p3 + dot(p3, vec3<f32>(p3.y + 33.33, p3.z + 33.33, p3.x + 33.33));
    return fract((p3.x + p3.y) * p3.z);
}

// --- UV Modulation ---
// intensity: scale (0 → 40% size, 1 → full)
// depth: recession (push content away from center)
// pitch_displacement: slow drift
// temporal_distortion: breathing oscillation

fn modulate_uv(uv: vec2<f32>, slot_index: u32, base_opacity: f32) -> vec2<f32> {
    // Scale: mix(0.4, 1.0, intensity) — centered
    let scale = mix(0.4, 1.0, u.intensity);
    var muv = (uv - 0.5) / scale + 0.5;

    // Corner incubation (Bachelard): low salience → peripheral placement
    // High salience → center. Content migrates inward as it materializes.
    let center_pull = base_opacity;
    let corner_offset = (1.0 - center_pull) * 0.3;
    muv = muv + (muv - 0.5) * corner_offset;

    // Immensity (Bachelard): content arrives from off-screen space
    // Entry progress tracks materialization; content slides in from beyond viewport
    let entry_progress = smoothstep(0.0, 0.5, base_opacity);
    let entry_offset = (1.0 - entry_progress) * 0.4;
    let slot_f = f32(slot_index);
    let entry_direction = vec2<f32>(
        sin(slot_f * 2.1 + u.time * 0.03),
        cos(slot_f * 1.7 + u.time * 0.02)
    );
    muv = muv + entry_direction * entry_offset;

    // Depth recession: push outward from center
    let recession = u.depth * 0.15;
    let center_offset_depth = muv - 0.5;
    muv = muv + center_offset_depth * recession;

    // Pitch displacement: slow directional drift per slot
    let drift_angle = slot_f * 1.5708 + u.time * 0.1;
    let drift = u.pitch_displacement * 0.05;
    muv = muv + vec2<f32>(cos(drift_angle), sin(drift_angle)) * drift;

    // Temporal distortion: breathing
    let breath = sin(u.time * 0.8 + slot_f * 0.7) * 0.5 + 0.5;
    let breath_scale = 1.0 + u.temporal_distortion * 0.03 * breath;
    muv = (muv - 0.5) * breath_scale + 0.5;

    return muv;
}

// --- Opacity computation ---
// tension: edge sharpness (feather width)
// coherence: dissolution via noise
// depth: darkening

fn content_opacity(uv: vec2<f32>, muv: vec2<f32>, base_opacity: f32) -> f32 {
    // Out of bounds check
    if muv.x < 0.0 || muv.x > 1.0 || muv.y < 0.0 || muv.y > 1.0 {
        return 0.0;
    }

    var alpha = base_opacity;

    // Materialization from substrate (Bachelard): content crystallizes from
    // the procedural noise field. Where noise is bright, content appears first.
    // As opacity increases (fragment strengthens), the threshold drops until
    // all content is visible. The image doesn't appear — it condenses.
    let mat_noise = hash21(uv * 30.0 + u.time * 0.05);
    let mat_threshold = 1.0 - base_opacity;
    let materialization = smoothstep(mat_threshold, mat_threshold + 0.3, mat_noise);
    alpha = alpha * materialization;

    // Tension → feather width (0 = wide soft edge, 1 = hard edge)
    let feather = mix(0.3, 0.02, u.tension);
    let edge_dist = min(min(muv.x, 1.0 - muv.x), min(muv.y, 1.0 - muv.y));
    alpha = alpha * smoothstep(0.0, feather, edge_dist);

    // Coherence → dissolution (0 = fully dissolved, 1 = solid)
    // Time-based drift for smooth shimmer, not per-frame flicker
    let dissolve_noise = hash21(uv * 50.0 + u.time * 0.1 + u.coherence * 10.0);
    let dissolution_threshold = 1.0 - u.coherence;
    let dissolve = smoothstep(dissolution_threshold - 0.1, dissolution_threshold + 0.1, dissolve_noise);
    alpha = alpha * mix(dissolve, 1.0, u.coherence * 0.5 + 0.5);

    // Depth → darkening (reduce opacity at high depth)
    alpha = alpha * mix(1.0, 0.6, u.depth);

    return alpha;
}

// --- Color modulation ---
// spectral_color: warmth shift
// degradation: noise/glitch overlay

fn modulate_color(color: vec3<f32>, uv: vec2<f32>) -> vec3<f32> {
    var c = color;

    // Spectral color → warm/cool shift
    // 0 = neutral, positive = warm (boost red, reduce blue)
    let warmth = u.spectral_color;
    c.r = c.r + warmth * 0.1;
    c.b = c.b - warmth * 0.08;
    c = clamp(c, vec3<f32>(0.0), vec3<f32>(1.0));

    // Degradation → additive noise
    let noise = hash21(uv * 100.0 + u.time * 2.0);
    let glitch = u.degradation * noise * 0.15;
    c = c + vec3<f32>(glitch);

    return clamp(c, vec3<f32>(0.0), vec3<f32>(1.0));
}

// --- Blending ---

fn blend_screen(base: vec3<f32>, layer: vec3<f32>) -> vec3<f32> {
    return 1.0 - (1.0 - base) * (1.0 - layer);
}

// --- Per-slot sampling ---

fn sample_slot(tex: texture_2d<f32>, uv: vec2<f32>, muv: vec2<f32>, base_opacity: f32) -> vec4<f32> {
    let alpha = content_opacity(uv, muv, base_opacity);
    if alpha < 0.001 {
        return vec4<f32>(0.0);
    }
    let color = textureSample(tex, samp, muv).rgb;
    let modulated = modulate_color(color, uv);
    return vec4<f32>(modulated * alpha, alpha);
}

// --- Fragment ---

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let composite = textureSample(composite_tex, samp, in.uv).rgb;
    var result = composite;

    // Slot 0
    if u.slot_opacities.x > 0.001 {
        let muv = modulate_uv(in.uv, 0u, u.slot_opacities.x);
        let s = sample_slot(slot0_tex, in.uv, muv, u.slot_opacities.x);
        result = mix(result, blend_screen(result, s.rgb), s.a);
    }

    // Slot 1
    if u.slot_opacities.y > 0.001 {
        let muv = modulate_uv(in.uv, 1u, u.slot_opacities.y);
        let s = sample_slot(slot1_tex, in.uv, muv, u.slot_opacities.y);
        result = mix(result, blend_screen(result, s.rgb), s.a);
    }

    // Slot 2
    if u.slot_opacities.z > 0.001 {
        let muv = modulate_uv(in.uv, 2u, u.slot_opacities.z);
        let s = sample_slot(slot2_tex, in.uv, muv, u.slot_opacities.z);
        result = mix(result, blend_screen(result, s.rgb), s.a);
    }

    // Slot 3
    if u.slot_opacities.w > 0.001 {
        let muv = modulate_uv(in.uv, 3u, u.slot_opacities.w);
        let s = sample_slot(slot3_tex, in.uv, muv, u.slot_opacities.w);
        result = mix(result, blend_screen(result, s.rgb), s.a);
    }

    return vec4<f32>(result, 1.0);
}
