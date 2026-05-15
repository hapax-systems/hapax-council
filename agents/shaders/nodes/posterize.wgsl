struct Params {
    u_levels: f32,
    u_gamma: f32,
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
    var color: vec4<f32>;
    var c: vec3<f32>;
    var levels: f32;
    var gamma: f32;
    var posterize_strength: f32;
    var mixed: vec3<f32>;

    let _e8 = v_texcoord_1;
    let _e9 = textureSample(tex, tex_sampler, _e8);
    color = _e9;
    levels = clamp(global.u_levels, 2f, 256f);
    gamma = max(global.u_gamma, 0.01f);
    posterize_strength = clamp(((256f - levels) / 252f), 0f, 1f) * 0.35f;
    if (posterize_strength <= 0.001f) {
        fragColor = color;
        return;
    }
    let _e11 = color;
    c = pow(_e11.xyz, vec3(gamma));
    let _e17 = c;
    c = (floor(((_e17 * levels) + vec3(0.5f))) / vec3(levels));
    let _e27 = c;
    c = pow(_e27, vec3((1f / gamma)));
    let _e33 = c;
    mixed = mix(color.xyz, _e33, vec3(posterize_strength));
    fragColor = vec4<f32>(mixed.x, mixed.y, mixed.z, color.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e15 = fragColor;
    return FragmentOutput(_e15);
}
