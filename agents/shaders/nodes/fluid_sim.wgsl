struct Params {
    u_viscosity: f32,
    u_vorticity: f32,
    u_dissipation: f32,
    u_speed: f32,
    u_amount: f32,
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
var tex_accum: texture_2d<f32>;
@group(1) @binding(3)
var tex_accum_sampler: sampler;
@group(2) @binding(0)
var<uniform> global: Params;

fn main_1() {
    let uv = v_texcoord_1;
    let source = textureSample(tex, tex_sampler, uv);
    let texel = vec2<f32>(1.0 / uniforms.resolution.x, 1.0 / uniforms.resolution.y);
    let prev = textureSample(tex_accum, tex_accum_sampler, uv);
    let vel = (prev.xy * 2.0) - vec2<f32>(1.0);
    let advected_uv = uv - (vel * texel * clamp(global.u_speed, 0.0, 1.0));
    let advected = textureSample(tex_accum, tex_accum_sampler, advected_uv);
    let l = textureSample(tex_accum, tex_accum_sampler, uv - vec2<f32>(texel.x, 0.0));
    let r = textureSample(tex_accum, tex_accum_sampler, uv + vec2<f32>(texel.x, 0.0));
    let t = textureSample(tex_accum, tex_accum_sampler, uv - vec2<f32>(0.0, texel.y));
    let b = textureSample(tex_accum, tex_accum_sampler, uv + vec2<f32>(0.0, texel.y));
    let diffused = mix(advected, (l + r + t + b) * 0.25, vec4<f32>(clamp(global.u_viscosity * 10.0, 0.0, 0.12)));
    let curl = (r.y - l.y) - (t.x - b.x);
    let vort_raw = vec2<f32>(abs(t.x) - abs(b.x), abs(r.y) - abs(l.y));
    let vort = normalize(vort_raw + vec2<f32>(0.0001)) * curl * clamp(global.u_vorticity, 0.0, 1.0) * texel.x;
    let new_vel = (((diffused.xy * 2.0) - vec2<f32>(1.0)) + vort) * clamp(global.u_dissipation, 0.90, 1.0);
    let flow_uv = clamp(uv - (new_vel * texel * 10.0), vec2(0.0), vec2(1.0));
    let flowed = textureSample(tex, tex_sampler, flow_uv);
    let source_luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence =         smoothstep(0.008, 0.09, source_luma);
    let strength = surface_presence * clamp(global.u_amount, 0.0, 0.15);
    fragColor = vec4<f32>(mix(source.xyz, flowed.xyz, vec3<f32>(strength)), source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
