struct Params {
    u_strength: f32,
    u_radius: f32,
    u_softness: f32,
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
    var c: vec4<f32>;
    var d: f32;

    let _e10 = v_texcoord_1;
    let _e11 = textureSample(tex, tex_sampler, _e10);
    c = _e11;
    let source_luma = dot(c.xyz, vec3<f32>(0.299f, 0.587f, 0.114f));
    let surface_presence = smoothstep(0.035f, 0.18f, source_luma);

    // Elliptical vignette: UV 0..1 mapped to centered -1..1 on both axes.
    // No aspect correction — distance is 1.0 at all four edges, ~1.414 at corners.
    // This produces uniform edge darkening regardless of aspect ratio.
    let centered = (v_texcoord_1 - vec2(0.5)) * 2.0;
    d = length(centered);

    let vig = smoothstep(global.u_radius, global.u_radius + global.u_softness, d) * global.u_strength * surface_presence;
    let darkened = c.xyz * (1.0 - vig);
    let mediated = mix(c.xyz, darkened, vec3<f32>(min(vig, 0.34f)));
    fragColor = vec4<f32>(mediated, c.w);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e17 = fragColor;
    return FragmentOutput(_e17);
}
