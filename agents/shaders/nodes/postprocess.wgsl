struct Params {
    u_vignette_strength: f32,
    u_sediment_strength: f32,
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

    let _e8 = v_texcoord_1;
    let _e9 = textureSample(tex, tex_sampler, _e8);
    c = _e9;

    // Elliptical vignette: UV mapped to centered -1..1 on both axes.
    // No aspect correction — uniform edge darkening at all screen edges.
    let uv = (v_texcoord_1 * 2.0) - vec2(1.0);
    let d = length(uv);
    let vig = smoothstep(1.0, 2.0, d) * global.u_vignette_strength;
    c = vec4<f32>(c.xyz * (1.0 - vig), c.w);

    // Sediment: bottom-edge darkening
    let sed = smoothstep(0.95, 1.0, v_texcoord_1.y) * global.u_sediment_strength;
    c = vec4<f32>(c.xyz * (1.0 - sed), c.w);

    fragColor = c;
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e15 = fragColor;
    return FragmentOutput(_e15);
}
