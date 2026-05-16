struct Params {
    u_saturation: f32,
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
    let c = textureSample(tex, tex_sampler, uv);
    if c.a < 0.01 {
        fragColor = c;
        return;
    }

    let lum = dot(c.rgb, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence = smoothstep(0.045, 0.18, lum);
    var col = mix(vec3(lum), c.rgb, global.u_saturation);
    col = (col - 0.5) * global.u_contrast + 0.5;
    col = col * global.u_brightness;
    let bounded = clamp(col, vec3(0.0), vec3(1.0));
    fragColor = vec4<f32>(mix(c.rgb, bounded, vec3(surface_presence)), c.a);
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
