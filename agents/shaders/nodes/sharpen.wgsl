struct Params {
    u_amount: f32,
    u_radius: f32,
    u_width: f32,
    u_height: f32,
}

struct FragmentOutput {
    @location(0) fragColor: vec4<f32>,
}

var<private> fragColor: vec4<f32>;
var<private> v_texcoord_1: vec2<f32>;
@group(0) @binding(0) 
var tex: texture_2d<f32>;
@group(0) @binding(1) 
var tex_sampler: sampler;
@group(1) @binding(0) 
var<uniform> global: Params;

fn main_1() {
    var texel: vec2<f32>;
    var color: vec4<f32>;
    var blur: vec4<f32>;

    let _e13 = global.u_width;
    let _e16 = global.u_height;
    let _e19 = global.u_radius;
    texel = (vec2<f32>((1f / _e13), (1f / _e16)) * _e19);
    let _e22 = v_texcoord_1;
    let _e23 = textureSample(tex, tex_sampler, _e22);
    color = _e23;
    let _e25 = v_texcoord_1;
    let _e26 = texel;
    let _e29 = texel;
    let _e34 = textureSample(tex, tex_sampler, (_e25 + vec2<f32>(-(_e26.x), -(_e29.y))));
    let _e35 = v_texcoord_1;
    let _e36 = texel;
    let _e38 = texel;
    let _e43 = textureSample(tex, tex_sampler, (_e35 + vec2<f32>(_e36.x, -(_e38.y))));
    let _e45 = v_texcoord_1;
    let _e46 = texel;
    let _e49 = texel;
    let _e53 = textureSample(tex, tex_sampler, (_e45 + vec2<f32>(-(_e46.x), _e49.y)));
    let _e55 = v_texcoord_1;
    let _e56 = texel;
    let _e58 = texel;
    let _e62 = textureSample(tex, tex_sampler, (_e55 + vec2<f32>(_e56.x, _e58.y)));
    blur = (((_e34 + _e43) + _e53) + _e62);
    let _e65 = blur;
    blur = (_e65 * 0.25f);
    let _e68 = color;
    let _e70 = color;
    let _e72 = blur;
    let _e75 = global.u_amount;
    let _e77 = (_e68.xyz + ((_e70.xyz - _e72.xyz) * _e75));
    let _e78 = color;
    fragColor = vec4<f32>(_e77.x, _e77.y, _e77.z, _e78.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e19 = fragColor;
    return FragmentOutput(_e19);
}
