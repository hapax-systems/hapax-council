// Post-processing: vignette + color grading + sediment strip

struct Params {
    vignette_strength: f32,   // default: 0.4
    vignette_radius: f32,     // default: 0.7
    sediment_height: f32,     // fraction of screen (default: 0.05)
    episode_count: f32,       // affects sediment complexity
    time: f32,
    _pad0: f32,
    _pad1: f32,
    _pad2: f32,
}

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var src: texture_2d<f32>;
@group(0) @binding(2) var samp: sampler;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
}

@vertex
fn vs_main(@builtin(vertex_index) idx: u32) -> VertexOutput {
    var out: VertexOutput;
    let x = f32(i32(idx & 1u)) * 4.0 - 1.0;
    let y = f32(i32(idx >> 1u)) * 4.0 - 1.0;
    out.position = vec4<f32>(x, y, 0.0, 1.0);
    out.uv = vec2<f32>((x + 1.0) * 0.5, (1.0 - y) * 0.5);
    return out;
}

fn hash11(p: f32) -> f32 {
    return fract(sin(p * 127.1) * 43758.5453);
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let uv = in.uv;
    var color = textureSample(src, samp, uv).rgb;

    // Vignette
    let dist = distance(uv, vec2<f32>(0.5, 0.5));
    let vig = smoothstep(params.vignette_radius, params.vignette_radius - 0.3, dist);
    color *= mix(1.0 - params.vignette_strength, 1.0, vig);

    // Sediment strip (bottom of screen)
    let sed_start = 1.0 - params.sediment_height;
    if uv.y > sed_start {
        let sed_uv = (uv.y - sed_start) / params.sediment_height;
        // Strata: horizontal bands with slight noise
        let band = floor(sed_uv * (4.0 + params.episode_count * 0.1));
        let band_hash = hash11(band);
        // Muted strata colors
        let strata_color = vec3<f32>(
            0.04 + band_hash * 0.08,
            0.06 + fract(band_hash * 3.7) * 0.06,
            0.05 + fract(band_hash * 7.3) * 0.10,
        );
        // Noise texture on strata
        let noise = hash11(band + uv.x * 100.0 + params.time * 0.01) * 0.02;
        let sed_color = strata_color + noise;
        // Fade in at top edge of sediment
        let fade = smoothstep(0.0, 0.15, sed_uv);
        color = mix(color, sed_color, fade * 0.8);
    }

    return vec4<f32>(color, 1.0);
}
