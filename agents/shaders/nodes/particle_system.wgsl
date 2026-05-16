struct Params {
    u_emit_rate: f32,
    u_lifetime: f32,
    u_size: f32,
    u_color_r: f32,
    u_color_g: f32,
    u_color_b: f32,
    u_gravity_y: f32,
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

fn hash(n: f32) -> f32 {
    return fract(sin(n) * 43758.547);
}

fn main_1() {
    let uv = v_texcoord_1;
    let base = textureSample(tex, tex_sampler, uv);
    let pixel = uv * vec2<f32>(uniforms.resolution.x, uniforms.resolution.y);
    let particle_count = min(global.u_emit_rate, 96.0);
    var glow = 0.0;

    for (var i = 0; i < 96; i = i + 1) {
        let fi = f32(i);
        if fi >= particle_count {
            break;
        }
        let lifetime = clamp(global.u_lifetime, 1.0, 4.0);
        let age = fract((uniforms.time / lifetime) + hash(fi * 7.31));
        let spawn_x = hash(fi * 13.7) * uniforms.resolution.x;
        let spawn_y = hash(fi * 23.1) * uniforms.resolution.y;
        let vel_x = (hash(fi * 37.3) - 0.5) * 64.0;
        let vel_y = (hash(fi * 41.7) - 0.5) * 64.0;
        let px = spawn_x + (vel_x * age);
        let py = spawn_y + (vel_y * age) + ((0.5 * clamp(global.u_gravity_y, 0.0, 60.0)) * age * age);
        let dist = length(pixel - vec2<f32>(px, py));
        let fade = 1.0 - age;
        glow = glow + (fade * smoothstep(clamp(global.u_size, 1.0, 3.0), 0.0, dist));
    }

    let particle_color = vec3<f32>(global.u_color_r, global.u_color_g, global.u_color_b) * min(glow, 1.4);
    let base_luma = dot(base.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.008, 0.09, base_luma);
    let strength = surface_presence * clamp(global.u_emit_rate / 600.0, 0.0, 0.16);
    let out_rgb = clamp(base.xyz + (particle_color * strength), vec3(0.0), vec3(1.0));
    fragColor = vec4<f32>(out_rgb, base.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
