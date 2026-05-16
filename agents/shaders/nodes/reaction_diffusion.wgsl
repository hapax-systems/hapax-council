struct Params {
    u_feed_rate: f32,
    u_kill_rate: f32,
    u_diffusion_a: f32,
    u_diffusion_b: f32,
    u_speed: f32,
    u_amount: f32,
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
@group(1) @binding(2)
var tex_accum: texture_2d<f32>;
@group(1) @binding(3)
var tex_accum_sampler: sampler;
@group(2) @binding(0)
var<uniform> global: Params;

fn main_1() {
    let uv = v_texcoord_1;
    let source = textureSample(tex, tex_sampler, uv);
    let texel = vec2<f32>(1.0 / uniforms.resolution.x, 1.0 / uniforms.resolution.y);
    let c = textureSample(tex_accum, tex_accum_sampler, uv);
    var a = c.x;
    var b = c.y;
    let left = textureSample(tex_accum, tex_accum_sampler, uv - vec2<f32>(texel.x, 0.0));
    let right = textureSample(tex_accum, tex_accum_sampler, uv + vec2<f32>(texel.x, 0.0));
    let top = textureSample(tex_accum, tex_accum_sampler, uv - vec2<f32>(0.0, texel.y));
    let bottom = textureSample(tex_accum, tex_accum_sampler, uv + vec2<f32>(0.0, texel.y));
    let lap_a = left.x + right.x + top.x + bottom.x - (4.0 * a);
    let lap_b = left.y + right.y + top.y + bottom.y - (4.0 * b);
    let reaction = a * b * b;
    let speed = clamp(global.u_speed, 0.0, 1.0);
    let da = (clamp(global.u_diffusion_a, 0.5, 1.5) * lap_a) - reaction + (clamp(global.u_feed_rate, 0.01, 0.1) * (1.0 - a));
    let db = (clamp(global.u_diffusion_b, 0.1, 0.8) * lap_b) + reaction - ((clamp(global.u_kill_rate, 0.01, 0.07) + clamp(global.u_feed_rate, 0.01, 0.1)) * b);
    a = clamp(a + (da * speed * 0.1), 0.0, 1.0);
    b = clamp(b + (db * speed * 0.1), 0.0, 1.0);
    let source_luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let seed = smoothstep(0.20, 0.55, source_luma);
    b = max(b, seed * 0.10);
    let pattern = vec3<f32>(a - b, b * 0.65, b);
    let surface_presence =         smoothstep(0.025, 0.14, source_luma);
    let strength = surface_presence * clamp(global.u_amount, 0.0, 0.15);
    let mediated = mix(source.xyz, clamp(source.xyz + pattern, vec3(0.0), vec3(1.0)), vec3<f32>(strength));
    let mediated_luma = dot(mediated, vec3<f32>(0.299, 0.587, 0.114));
    let luma_deficit = max(0.0, source_luma - mediated_luma);
    let luma_floor = min(mediated + vec3<f32>(luma_deficit), vec3<f32>(1.0));
    fragColor = vec4<f32>(luma_floor, source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
