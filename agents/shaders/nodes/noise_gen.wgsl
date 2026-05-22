struct Params {
    u_frequency_x: f32,
    u_frequency_y: f32,
    u_octaves: f32,
    u_amplitude: f32,
    u_speed: f32,
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

fn hash3d(p: vec3<f32>) -> f32 {
    let s = dot(p, vec3<f32>(127.1, 311.7, 74.7));
    return fract(sin(s) * 43758.5453123);
}

fn noise3d(p: vec3<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    
    let u = f * f * (3.0 - 2.0 * f);
    
    let n000 = hash3d(i + vec3<f32>(0.0, 0.0, 0.0));
    let n100 = hash3d(i + vec3<f32>(1.0, 0.0, 0.0));
    let n010 = hash3d(i + vec3<f32>(0.0, 1.0, 0.0));
    let n110 = hash3d(i + vec3<f32>(1.0, 1.0, 0.0));
    let n001 = hash3d(i + vec3<f32>(0.0, 0.0, 1.0));
    let n101 = hash3d(i + vec3<f32>(1.0, 0.0, 1.0));
    let n011 = hash3d(i + vec3<f32>(0.0, 1.0, 1.0));
    let n111 = hash3d(i + vec3<f32>(1.0, 1.0, 1.0));
    
    let mix_x00 = mix(n000, n100, u.x);
    let mix_x10 = mix(n010, n110, u.x);
    let mix_x01 = mix(n001, n101, u.x);
    let mix_x11 = mix(n011, n111, u.x);
    
    let mix_y0 = mix(mix_x00, mix_x10, u.y);
    let mix_y1 = mix(mix_x01, mix_x11, u.y);
    
    return mix(mix_y0, mix_y1, u.z);
}

fn fbm3d(p_in: vec3<f32>, oct: f32) -> f32 {
    var p = p_in;
    var value = 0.0;
    var amp = 0.5;
    for (var i = 0; i < 8; i = i + 1) {
        if f32(i) >= oct {
            break;
        }
        value = value + (amp * noise3d(p));
        p = (p * 2.0) + vec3<f32>(100.0, 100.0, 100.0);
        amp = amp * 0.5;
    }
    return value;
}

fn main_1() {
    let uv = v_texcoord_1;
    let source = textureSample(tex, tex_sampler, uv);
    
    let PI = 3.14159265;
    let theta = uv.x * 2.0 * PI - PI;
    let phi = uv.y * PI;
    let sphere_pos = vec3<f32>(sin(phi) * sin(theta), cos(phi), sin(phi) * cos(theta));
    
    let freq = vec3<f32>(
        clamp(global.u_frequency_x, 0.5, 8.0),
        clamp(global.u_frequency_y, 0.5, 8.0),
        (clamp(global.u_frequency_x, 0.5, 8.0) + clamp(global.u_frequency_y, 0.5, 8.0)) * 0.5
    );
    let noise_pos = sphere_pos * freq + vec3<f32>(uniforms.time * clamp(global.u_speed, 0.0, 0.35) * 0.1);
    
    let n = (fbm3d(noise_pos, clamp(global.u_octaves, 1.0, 4.0)) - 0.5) * 2.0;
    let source_luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence = smoothstep(0.035, 0.18, source_luma);
    let strength = surface_presence * clamp(global.u_amplitude, 0.0, 0.08);
    let out_rgb = clamp(source.xyz + vec3<f32>(n * strength), vec3(0.0), vec3(1.0));
    fragColor = vec4<f32>(out_rgb, source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
