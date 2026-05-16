struct Params {
    u_frequency_x: f32,
    u_frequency_y: f32,
    u_octaves: f32,
    u_amplitude: f32,
    u_speed: f32,
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
@group(2) @binding(0)
var<uniform> global: Params;

fn hash(p: vec2<f32>) -> f32 {
    return fract(sin(dot(p, vec2<f32>(127.1, 311.7))) * 43758.547);
}

fn noise(p: vec2<f32>) -> f32 {
    let i = floor(p);
    var f = fract(p);
    f = f * f * (vec2(3.0) - (2.0 * f));
    let a = hash(i);
    let b = hash(i + vec2<f32>(1.0, 0.0));
    let c = hash(i + vec2<f32>(0.0, 1.0));
    let d = hash(i + vec2<f32>(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

fn fbm(p_in: vec2<f32>, oct: f32) -> f32 {
    var p = p_in;
    var value = 0.0;
    var amp = 0.5;
    for (var i = 0; i < 8; i = i + 1) {
        if f32(i) >= oct {
            break;
        }
        value = value + (amp * noise(p));
        p = (p * 2.0) + vec2<f32>(100.0);
        amp = amp * 0.5;
    }
    return value;
}

fn main_1() {
    let uv = v_texcoord_1;
    let source = textureSample(tex, tex_sampler, uv);
    let noise_uv = (uv * vec2<f32>(clamp(global.u_frequency_x, 0.5, 8.0), clamp(global.u_frequency_y, 0.5, 8.0))) + vec2<f32>(uniforms.time * clamp(global.u_speed, 0.0, 0.35) * 0.1);
    let n = (fbm(noise_uv, clamp(global.u_octaves, 1.0, 4.0)) - 0.5) * 2.0;
    let source_luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence = smoothstep(0.035, 0.18, source_luma);
    let strength = surface_presence * clamp(global.u_amplitude, 0.0, 0.08);
    let out_rgb = clamp(source.xyz + vec3<f32>(n * strength), vec3(0.0), vec3(1.0));
    fragColor = vec4<f32>(out_rgb, source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
