struct Params {
    u_color_r: f32,
    u_color_g: f32,
    u_color_b: f32,
    u_top_alpha: f32,
    u_bottom_alpha: f32,
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
    let color = textureSample(tex, tex_sampler, uv);
    let raw_alpha = mix(clamp(global.u_bottom_alpha, 0.0, 0.20), clamp(global.u_top_alpha, 0.0, 0.20), uv.y);
    let overlay = vec3<f32>(global.u_color_r, global.u_color_g, global.u_color_b);
    let luma = dot(color.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.008, 0.09, luma);
    let alpha = raw_alpha * surface_presence;
    fragColor = vec4<f32>(mix(color.xyz, overlay, vec3<f32>(alpha)), color.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
