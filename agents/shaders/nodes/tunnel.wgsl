struct Params {
    u_speed: f32,
    u_twist: f32,
    u_radius: f32,
    u_distortion: f32,
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
    var uv: vec2<f32>;
    var r: f32;
    var angle: f32;
    var tunnel_r: f32;
    var tunnel_a: f32;
    var tunnelUV: vec2<f32>;
    var color: vec4<f32>;
    var fade: f32;

    let _e14 = v_texcoord_1;
    uv = (_e14 - vec2(0.5f));
    let _e19 = uv;
    r = length(_e19);
    let _e22 = uv;
    let _e24 = uv;
    angle = atan2(_e22.y, _e24.x);
    let _e28 = global.u_radius;
    let _e29 = r;
    tunnel_r = (_e28 / (_e29 + 0.001f));
    let _e34 = angle;
    tunnel_a = (_e34 / 3.1415927f);
    let _e38 = tunnel_r;

    let _e40 = global.u_speed;
    tunnel_r = (_e38 + (uniforms.time * _e40));
    let _e43 = tunnel_a;
    let _e44 = global.u_twist;
    let _e45 = tunnel_r;
    tunnel_a = (_e43 + ((_e44 * _e45) * 0.1f));
    let _e50 = tunnel_a;
    let _e51 = tunnel_r;
    let _e52 = global.u_distortion;
    tunnel_a = (_e50 + (sin((_e51 * _e52)) * 0.1f));
    let _e58 = tunnel_a;
    let _e59 = tunnel_r;
    tunnelUV = vec2<f32>(_e58, fract(_e59));
    let _e63 = tunnelUV;
    tunnelUV = fract(_e63);
    let _e65 = tunnelUV;
    let _e66 = textureSample(tex, tex_sampler, _e65);
    color = _e66;
    let _e70 = r;
    fade = smoothstep(0f, 0.1f, _e70);
    let _e73 = color;
    let _e75 = fade;
    let _e76 = (_e73.xyz * _e75);
    let _e77 = color;
    fragColor = vec4<f32>(_e76.x, _e76.y, _e76.z, _e77.w);
    return;
}

@fragment 
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e21 = fragColor;
    return FragmentOutput(_e21);
}
