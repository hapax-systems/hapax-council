struct Params {
    u_color_r: f32,
    u_color_g: f32,
    u_color_b: f32,
    u_color_a: f32,
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
    let source = textureSample(tex, tex_sampler, v_texcoord_1);
    let wash = vec3<f32>(global.u_color_r, global.u_color_g, global.u_color_b);
    let luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.025, 0.14, luma);
    let alpha = surface_presence * clamp(global.u_color_a, 0.0, 0.10);
    fragColor = vec4<f32>(mix(source.xyz, wash, vec3<f32>(alpha)), source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
