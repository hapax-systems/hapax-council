struct Params {
    u_green_intensity: f32,
    u_brightness: f32,
    u_contrast: f32,
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

fn main_1() {
    let uv = v_texcoord_1;
    let source = textureSample(tex, tex_sampler, uv);
    let lum = clamp(((dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114)) - 0.5) * clamp(global.u_contrast, 0.85, 1.15) + 0.5) * clamp(global.u_brightness, 0.95, 1.20), 0.0, 1.0);
    let green = vec3<f32>(lum * 0.18, lum * clamp(global.u_green_intensity, 0.35, 0.70), lum * 0.12);
    let source_luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.008, 0.09, source_luma);
    let strength = surface_presence * 0.14;
    let mediated = mix(source.xyz, green, vec3<f32>(strength));
    let mediated_luma = dot(mediated, vec3<f32>(0.299, 0.587, 0.114));
    let luma_deficit = max(0.0, source_luma - mediated_luma);
    let luma_floor = min(
        mediated + vec3<f32>(luma_deficit * 0.78, luma_deficit, luma_deficit * 0.70),
        vec3<f32>(1.0),
    );
    fragColor = vec4<f32>(luma_floor, source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
