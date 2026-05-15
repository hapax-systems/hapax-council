struct Params {
    u_swatch_count: f32,
    u_strip_height: f32,
    u_strip_opacity: f32,
    u_width: f32,
    u_height: f32,
}

struct FragmentOutput {
    @location(0) fragColor: vec4<f32>,
}

const SAMPLE_ROWS: f32 = 8f;

var<private> fragColor: vec4<f32>;
var<private> v_texcoord_1: vec2<f32>;
@group(1) @binding(0) 
var tex: texture_2d<f32>;
@group(1) @binding(1) 
var tex_sampler: sampler;
@group(2) @binding(0) 
var<uniform> global: Params;

fn sample_column_mean(col_u0_: f32, col_u1_: f32) -> vec3<f32> {
    var col_u0_1: f32;
    var col_u1_1: f32;
    var sum: vec3<f32> = vec3(0f);
    var count: f32 = 0f;
    var r: f32 = 0f;
    var v: f32;
    var c: f32;
    var u: f32;

    col_u0_1 = col_u0_;
    col_u1_1 = col_u1_;
    loop {
        let _e26 = r;
        if !((_e26 < SAMPLE_ROWS)) {
            break;
        }
        {
            let _e32 = r;
            v = ((_e32 + 0.5f) / SAMPLE_ROWS);
            c = 0f;
            loop {
                let _e39 = c;
                if !((_e39 < 4f)) {
                    break;
                }
                {
                    let _e46 = col_u0_1;
                    let _e47 = col_u1_1;
                    let _e48 = c;
                    u = mix(_e46, _e47, ((_e48 + 0.5f) / 4f));
                    let _e55 = sum;
                    let _e56 = u;
                    let _e57 = v;
                    let _e59 = textureSample(tex, tex_sampler, vec2<f32>(_e56, _e57));
                    sum = (_e55 + _e59.xyz);
                    let _e62 = count;
                    count = (_e62 + 1f);
                }
                continuing {
                    let _e43 = c;
                    c = (_e43 + 1f);
                }
            }
        }
        continuing {
            let _e29 = r;
            r = (_e29 + 1f);
        }
    }
    let _e65 = sum;
    let _e66 = count;
    return (_e65 / vec3(_e66));
}

fn main_1() {
    let uv = v_texcoord_1;
    let source = textureSample(tex, tex_sampler, uv);
    if (global.u_strip_opacity <= 0.0001f) {
        fragColor = source;
        return;
    }

    // This node used to paint a top-of-frame palette strip. In live autonomous
    // drift that reads as a foreground diagnostic pane. It now projects palette
    // pressure back into source-bearing pixels: no viewport banner, no independent
    // swatch surface.
    let count = clamp(floor(global.u_swatch_count), 3f, 12f);
    let diagonal = fract((uv.x * 0.73f + uv.y * 0.41f) * count);
    let idx = clamp(floor(diagonal * count), 0f, count - 1f);
    let u0 = idx / count;
    let u1 = (idx + 1f) / count;
    let swatch = sample_column_mean(u0, u1);

    let luma = dot(source.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let hi = max(max(source.r, source.g), source.b);
    let lo = min(min(source.r, source.g), source.b);
    let saturation = clamp(hi - lo, 0f, 1f);
    let surface_presence = smoothstep(0.025f, 0.18f, luma);
    let chroma_gate = smoothstep(0.02f, 0.20f, saturation);
    let weave = 0.55f + 0.45f * smoothstep(0.18f, 0.82f, diagonal);
    let strength = clamp(global.u_strip_opacity, 0f, 0.22f)
        * surface_presence
        * (0.35f + 0.65f * chroma_gate)
        * weave;

    let blended = mix(source.xyz, swatch, vec3<f32>(strength));
    fragColor = vec4<f32>(blended, source.a);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e23 = fragColor;
    return FragmentOutput(_e23);
}
