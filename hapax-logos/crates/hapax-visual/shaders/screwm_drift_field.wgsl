// screwm_drift_field.wgsl — encode the live reverie substrate into a Screwm drift field.
//
// The DarkPlaces engine (R_HapaxDriftField_Update + the HAPAXDRIFT fragment stage)
// samples this 256x256 field by world XY and folds it into the luminous-wire color:
//     color = mix(base, base * (0.6 + 0.8 * field), 0.85)
// so a field value of 0.5 is NEUTRAL (no change). This encoder therefore outputs each
// channel CENTERED at ~0.5: flat / dark reverie leaves the wire at its baseline, while
// reverie STRUCTURE (luma, edges, chroma) modulates it spatially + temporally. The
// reverie is the existing evolving RD/fluid/feedback substrate; the field gains its OWN 2a
// (feedback/echo/trail/diff) + 2b (fluid advection + laplacian diffusion) temporal substrate, so it — and thus
// the wire — never exactly repeats (endless variety) without a second DynamicPipeline.
//
// Anti-visualizer: bounded output (never blows out or goes dark), no global temporal
// envelope — all variation is spatial (reverie content) + slow (reverie cadence).

@group(0) @binding(0) var t_in: texture_2d<f32>;
@group(0) @binding(1) var s_in: sampler;
@group(0) @binding(2) var prev_tex: texture_2d<f32>;

struct VsOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VsOut {
    // full-screen triangle
    var p = array<vec2<f32>, 3>(vec2<f32>(-1.0, -1.0), vec2<f32>(3.0, -1.0), vec2<f32>(-1.0, 3.0));
    var t = array<vec2<f32>, 3>(vec2<f32>(0.0, 1.0), vec2<f32>(2.0, 1.0), vec2<f32>(0.0, -1.0));
    var o: VsOut;
    o.pos = vec4<f32>(p[vi], 0.0, 1.0);
    o.uv = t[vi];
    return o;
}

const LUMA: vec3<f32> = vec3<f32>(0.299, 0.587, 0.114);

struct FragOut {
    @location(0) field: vec4<f32>,
    @location(1) currency: vec4<f32>,
};

@fragment
fn fs_main(@location(0) uv: vec2<f32>) -> FragOut {
    let px = vec2<f32>(1.0) / vec2<f32>(textureDimensions(t_in));
    let c = textureSample(t_in, s_in, uv).rgb;
    let l = dot(c, LUMA);

    // local luma gradient => edge amplitude (structure of the reverie)
    let lx = abs(dot(textureSample(t_in, s_in, uv + vec2<f32>(px.x, 0.0)).rgb, LUMA) - l);
    let ly = abs(dot(textureSample(t_in, s_in, uv + vec2<f32>(0.0, px.y)).rgb, LUMA) - l);
    let edge = clamp((lx + ly) * 4.0, 0.0, 1.0);

    // chroma deviation from luma (per channel) — the reverie's hue carried subtly
    let chroma = c - vec3<f32>(l);

    // HIGH-PASS detail = luma minus a wide-tap low-pass. Centered at ~0 regardless of
    // the reverie's ABSOLUTE brightness (it is a bright substrate), so the field is
    // brightness-invariant: flat regions => neutral, local structure => modulation.
    let r = 16.0 * px;
    let blur = 0.25 * (
        dot(textureSample(t_in, s_in, uv + vec2<f32>(r.x, 0.0)).rgb, LUMA)
        + dot(textureSample(t_in, s_in, uv - vec2<f32>(r.x, 0.0)).rgb, LUMA)
        + dot(textureSample(t_in, s_in, uv + vec2<f32>(0.0, r.y)).rgb, LUMA)
        + dot(textureSample(t_in, s_in, uv - vec2<f32>(0.0, r.y)).rgb, LUMA)
    );
    let detail = l - blur;

    // brightness modulator CENTERED at 0.5 (= neutral fold). The reverie's evolving
    // local structure (detail) + edges transit it +/- around baseline; bounded so the
    // wire never blows out or goes dark (anti_visualizer: spatial/cyclic, no flash).
    // Amplitude tuned for a VISIBLY alive wire ("full force") while the bounds keep it
    // a slow transit, never a strobe.
    let m = clamp(0.5 + detail * 2.6 + edge * 0.42, 0.26, 0.86);

    // per-channel = brightness + a reverie-chroma tint (desaturated baseline, small)
    let field = clamp(vec3<f32>(m) + chroma * 0.30, vec3<f32>(0.14), vec3<f32>(0.97));

    // presence in alpha (reserved for a future signal_presence gate)
    let presence = smoothstep(0.04, 0.25, l);

    // CURRENCY (target 1): a coarse, slowly-varying per-zone drift-AMPLITUDE envelope —
    // "how much is the reverie substrate doing in this zone" — that the DarkPlaces engine
    // multiplies into per-zone drift amplitude (Phase 1 modulation-currency wire). It is
    // LUMA-NEUTRAL: it modulates drift amount, not whole-frame luminance (anti_visualizer).
    // Wider taps than the field's high-pass so it is a smooth per-zone envelope, not detail.
    let wr = 40.0 * px;
    let an = dot(textureSample(t_in, s_in, uv + vec2<f32>(0.0, wr.y)).rgb, LUMA);
    let as_ = dot(textureSample(t_in, s_in, uv - vec2<f32>(0.0, wr.y)).rgb, LUMA);
    let ae = dot(textureSample(t_in, s_in, uv + vec2<f32>(wr.x, 0.0)).rgb, LUMA);
    let aw = dot(textureSample(t_in, s_in, uv - vec2<f32>(wr.x, 0.0)).rgb, LUMA);
    let activity = clamp((abs(l - an) + abs(l - as_) + abs(l - ae) + abs(l - aw)) * 2.0 + edge * 0.5, 0.0, 1.0);
    // bounded [0.2,1.0]; engine maps to an amplitude multiplier (0.2 = calm zone, 1.0 = active)
    let currency = clamp(0.2 + activity * 0.8, 0.2, 1.0);

    // ── Phase 2a temporal substrate: feedback / echo / trail / diff (prev-frame family) ──
    // prev_tex is the PREVIOUS field output (CPU round-trip). The field gains temporal memory
    // so it evolves + never exactly repeats (endless variety) beyond reverie's spatial content.
    // All sampled around the neutral 0.5 baseline + bounded, so it stays luma-neutral. Currency
    // modulates persistence (hybrid: active zones hold their drift longer).
    let prev_c = textureSample(prev_tex, s_in, uv).rgb;                                 // feedback
    let prev_trail = textureSample(prev_tex, s_in, uv + vec2<f32>(0.0018, 0.0011)).rgb; // trail (advected smear)
    let prev_echo = textureSample(prev_tex, s_in, uv + vec2<f32>(-0.0065, 0.0042)).rgb; // echo (offset ghost)
    let persisted = mix(vec3<f32>(0.5), mix(prev_trail, prev_echo, 0.35), 0.94);        // decay toward neutral
    let fdiff = abs(field - prev_c);                                                    // diff (motion/change)
    let fb = clamp(0.74 + currency * 0.18, 0.0, 0.94);                                  // currency-modulated persistence
    let field_evolved = clamp(mix(field, persisted, fb) + fdiff * 0.22, vec3<f32>(0.14), vec3<f32>(0.97));

    // ── Phase 2b temporal substrate: fluid advection + diffusion (organic, never-repeating) ──
    // 2a persists/echoes; 2b makes the substrate FLOW + SPREAD like a reaction-diffusion medium.
    // Advect the previous field along a flow PERPENDICULAR to the wide-tap reverie gradient (it
    // swirls along iso-luma contours, not a fixed offset), then gently diffuse it (4-neighbour
    // laplacian) so micro-structure grows + softens. Heavily bounded + neutral-centered; spatial +
    // slow (anti_visualizer: no global flash). Active zones (currency) evolve more (hybrid).
    let flow = clamp(vec2<f32>(-(an - as_), ae - aw), vec2<f32>(-0.6), vec2<f32>(0.6)) * 0.006;
    let advected = textureSample(prev_tex, s_in, uv - flow).rgb;
    // ── Phase 2c-A: slitscan (per-zone temporal-shear rake of prev) ──
    // Rake prev along a per-zone shear axis from the wide-tap reverie gradient, so each zone reads its
    // history at a different effective age — a continuous family of warped pasts (temporal slicing).
    // Currency scales the rake; bounded (reads bounded prev, feeds the egress clamp); ClampToEdge
    // sampler prevents wrap seams. Spatial + slow (anti_visualizer).
    let slit_phase = (an - as_) * 3.1 + (ae - aw) * 2.7;
    let slit = clamp(vec2<f32>(cos(slit_phase), sin(slit_phase)), vec2<f32>(-1.0), vec2<f32>(1.0)) * (0.004 + currency * 0.006);
    let scanned = textureSample(prev_tex, s_in, uv - flow - slit).rgb;
    let lap = (
        textureSample(prev_tex, s_in, uv + vec2<f32>(px.x, 0.0)).rgb
        + textureSample(prev_tex, s_in, uv - vec2<f32>(px.x, 0.0)).rgb
        + textureSample(prev_tex, s_in, uv + vec2<f32>(0.0, px.y)).rgb
        + textureSample(prev_tex, s_in, uv - vec2<f32>(0.0, px.y)).rgb
    ) * 0.25;
    let diffused = mix(mix(advected, lap, 0.5), scanned, 0.35);  // 2c-A slitscan blended in
    let evolve_amt = 0.18 + currency * 0.22;  // hybrid: active zones flow/spread more
    let field_2b = clamp(mix(field_evolved, diffused, evolve_amt), vec3<f32>(0.14), vec3<f32>(0.97));

    var out: FragOut;
    out.field = vec4<f32>(field_2b, presence);
    out.currency = vec4<f32>(vec3<f32>(currency), 1.0);
    return out;
}
