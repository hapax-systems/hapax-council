// screwm_drift_field.wgsl — encode the live reverie substrate into a Screwm drift field.
//
// The DarkPlaces engine (R_HapaxDriftField_Update + the HAPAXDRIFT fragment stage)
// samples this 256x256 field by world XY and folds it into the luminous-wire color:
//     color = mix(base, base * (0.6 + 0.8 * field), 0.85)
// so a field value of 0.5 is NEUTRAL (no change). This encoder therefore outputs each
// channel CENTERED at ~0.5: flat / dark reverie leaves the wire at its baseline, while
// reverie STRUCTURE (luma, edges, chroma) modulates it spatially + temporally. The
// reverie is the existing evolving RD/fluid/feedback substrate, so the field — and thus
// the wire — never exactly repeats (endless variety) without a second DynamicPipeline.
//
// Anti-visualizer: bounded output (never blows out or goes dark), no global temporal
// envelope — all variation is spatial (reverie content) + slow (reverie cadence).

@group(0) @binding(0) var t_in: texture_2d<f32>;
@group(0) @binding(1) var s_in: sampler;

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
    let currency = clamp(0.42 + activity * 0.5, 0.2, 1.0);

    var out: FragOut;
    out.field = vec4<f32>(field, presence);
    out.currency = vec4<f32>(vec3<f32>(currency), 1.0);
    return out;
}
