// Content layer — Bachelard phenomenology surface (Reverie substrate).
// Slot-family contract (yt-content-reverie-sierpinski-separation 2026-04-21):
// this node is tagged `slot_family: "narrative"` so the Rust runtime binds
// only narrative-content sources here. YouTube frames flow to Sierpinski
// via `sierpinski_content.wgsl` (slot_family: "youtube_pip"). Do NOT add
// YT-frame consumption logic to this shader — it would re-bleed YT into
// Reverie's generative substrate.
// Reads procedural field as input, composites 4 content texture slots over it.
// Bachelard effects:
// 1. Materialization from substrate (noise-gated crystallization)
// 2. Corner incubation (low salience → peripheral)
// 3. Off-screen entry / immensity (per-slot direction, slide in from beyond viewport)
// 4. Material quality (water/fire/earth/air/void UV + color modulation)
// 5. Dwelling trace boost (luminance boost during fadeout for feedback persistence)

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
var content_slot_0: texture_2d<f32>;
@group(1) @binding(3)
var content_slot_1: texture_2d<f32>;
@group(1) @binding(4)
var content_slot_2: texture_2d<f32>;
@group(1) @binding(5)
var content_slot_3: texture_2d<f32>;

// --- Noise ---

fn hash21(p: vec2<f32>) -> f32 {
    return fract(sin(dot(p, vec2<f32>(127.1, 311.7))) * 43758.547);
}

// --- Effects ---

fn smooth_noise(p: vec2<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    let u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash21(i), hash21(i + vec2(1.0, 0.0)), u.x),
               mix(hash21(i + vec2(0.0, 1.0)), hash21(i + vec2(1.0, 1.0)), u.x), u.y);
}

fn materialization(uv: vec2<f32>, salience: f32, time: f32) -> f32 {
    // Smooth organic regions — no grid, no per-pixel speckle, no time flicker.
    let noise = smooth_noise(uv * 3.0);
    return smoothstep(1.0 - salience, 1.0 - salience + 0.2, noise);
}

fn corner_incubation(uv: vec2<f32>, intensity: f32) -> vec2<f32> {
    let center_pull = intensity;
    let corner_offset = (1.0 - center_pull) * 0.3;
    return uv + (uv - 0.5) * corner_offset;
}

fn immensity_entry(uv: vec2<f32>, salience: f32, slot_index: f32) -> vec2<f32> {
    let entry_progress = smoothstep(0.0, 0.5, salience);
    let entry_offset = (1.0 - entry_progress) * 0.4;
    let entry_dir = vec2<f32>(sin(slot_index * 2.1), cos(slot_index * 1.7));
    return uv + entry_dir * entry_offset;
}

fn material_uv(uv: vec2<f32>, material_id: u32, time: f32) -> vec2<f32> {
    var muv = uv;
    switch material_id {
        case 0u: {
            // water: dissolve at edges, flow downward
            muv.y += sin(uv.x * 6.28 + time * 0.3) * 0.02;
            muv.y += time * 0.005;
        }
        case 1u: {
            // fire: burn outward from center
            let d = length(uv - 0.5);
            muv += normalize(uv - 0.5 + 0.001) * d * 0.05 * sin(time * 2.0);
        }
        case 2u: {
            // earth: minimal distortion
        }
        case 3u: {
            // air: drift upward, dispersal
            muv.y -= time * 0.008;
            muv.x += sin(uv.y * 4.0 + time * 0.5) * 0.015;
        }
        case 4u: {
            // void: inward pull
            muv = mix(muv, vec2<f32>(0.5), 0.05);
        }
        default: {}
    }
    return muv;
}

fn material_color(color: vec3<f32>, material_id: u32) -> vec3<f32> {
    switch material_id {
        case 0u: {
            return mix(color, color * vec3<f32>(0.85, 0.92, 1.1), 0.3);
        }
        case 1u: {
            return mix(color, color * vec3<f32>(1.15, 1.0, 0.85), 0.3);
        }
        case 2u: {
            let lum = dot(color, vec3<f32>(0.299, 0.587, 0.114));
            return mix(color, vec3<f32>(lum), 0.15);
        }
        case 3u: {
            return mix(color, vec3<f32>(1.0), 0.1);
        }
        case 4u: {
            return color * 0.7;
        }
        default: {
            return color;
        }
    }
}

fn dwelling_trace_boost(salience: f32) -> f32 {
    return 1.0 + (1.0 - smoothstep(0.3, 0.7, salience)) * 0.15;
}

// --- Per-slot blending with per-slot UV ---

fn sample_and_blend_slot(
    slot_tex: texture_2d<f32>,
    samp: sampler,
    uv_raw: vec2<f32>,
    opacity: f32,
    material_id: u32,
    time: f32,
    slot_index: f32,
    base: vec3<f32>,
) -> vec3<f32> {
    if opacity < 0.001 {
        return base;
    }
    // Per-slot UV: corner incubation + per-slot immensity direction + material
    var uv = corner_incubation(uv_raw, opacity);
    uv = immensity_entry(uv, opacity, slot_index);
    uv = material_uv(uv, material_id, time);

    let content = textureSample(slot_tex, samp, uv);
    // Content-aware fade: use the content's own luminance to drive blending.
    // Dark/black pixels (empty areas, edges of undersized sources) contribute
    // nothing. No hard boundary artifacts regardless of source size.
    let lum = dot(content.rgb, vec3(0.299, 0.587, 0.114));
    let content_presence = smoothstep(0.02, 0.08, lum);
    let gated = content.rgb * materialization(uv_raw, opacity, time) * content_presence;
    let colored = material_color(gated, material_id);
    let weighted = colored * opacity;
    // Screen blend: adds light to dark base. Content emerges from darkness.
    return 1.0 - (1.0 - base) * (1.0 - weighted);
}

// --- Main ---

fn main_1() {
    let uv_raw = v_texcoord_1;
    let time = uniforms.time;
    let material_id = u32(round(uniforms.custom[0][0]));

    // Sample procedural field at original UV (background unaffected by content distortion)
    let base_sample = textureSample(tex, tex_sampler, uv_raw);
    var base = base_sample.rgb;

    // Screen-blend each content slot — per-slot UV with distinct immensity direction
    base = sample_and_blend_slot(content_slot_0, tex_sampler, uv_raw,
        uniforms.slot_opacities[0], material_id, time, 0.0, base);
    base = sample_and_blend_slot(content_slot_1, tex_sampler, uv_raw,
        uniforms.slot_opacities[1], material_id, time, 1.0, base);
    base = sample_and_blend_slot(content_slot_2, tex_sampler, uv_raw,
        uniforms.slot_opacities[2], material_id, time, 2.0, base);
    base = sample_and_blend_slot(content_slot_3, tex_sampler, uv_raw,
        uniforms.slot_opacities[3], material_id, time, 3.0, base);

    // Dwelling trace boost on final composited result
    let max_salience = max(max(uniforms.slot_opacities[0], uniforms.slot_opacities[1]),
                           max(uniforms.slot_opacities[2], uniforms.slot_opacities[3]));
    let trace_boost = dwelling_trace_boost(max_salience);
    base *= trace_boost;

    fragColor = vec4<f32>(base, base_sample.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e11 = fragColor;
    return FragmentOutput(_e11);
}
