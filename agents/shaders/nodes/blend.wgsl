struct Params {
    u_alpha: f32,
    u_mode: f32,
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
var tex_b: texture_2d<f32>;
@group(1) @binding(3)
var tex_b_sampler: sampler;
@group(2) @binding(0)
var<uniform> global: Params;

fn main_1() {
    let uv = v_texcoord_1;
    let a = textureSample(tex, tex_sampler, uv);
    let b = textureSample(tex_b, tex_b_sampler, uv);

    var blended: vec3<f32>;
    if global.u_mode < 0.5 {
        blended = vec3(1.0) - ((vec3(1.0) - a.xyz) * (vec3(1.0) - b.xyz));
    } else if global.u_mode < 1.5 {
        blended = min(a.xyz + b.xyz, vec3(1.0));
    } else if global.u_mode < 2.5 {
        blended = a.xyz * b.xyz;
    } else if global.u_mode < 3.5 {
        blended = abs(a.xyz - b.xyz);
    } else {
        blended = mix((2.0 * a.xyz) * b.xyz, vec3(1.0) - ((2.0 * (vec3(1.0) - a.xyz)) * (vec3(1.0) - b.xyz)), step(vec3(0.5), a.xyz));
    }

    let luma = dot(a.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.025, 0.14, luma);
    let alpha = surface_presence * clamp(global.u_alpha, 0.0, 0.24);
    let out_rgb = mix(a.xyz, blended, vec3<f32>(alpha));
    fragColor = vec4<f32>(out_rgb, a.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
