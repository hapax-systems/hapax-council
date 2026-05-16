struct Params {
    u_zoom_speed: f32,
    u_spiral: f32,
    u_center_x: f32,
    u_center_y: f32,
    u_branches: f32,
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
    let uv0 = v_texcoord_1;
    let source = textureSample(tex, tex_sampler, uv0);
    let center = vec2<f32>(clamp(global.u_center_x, 0.45, 0.55), clamp(global.u_center_y, 0.45, 0.55));
    let uv = uv0 - center;
    let radius = length(uv);
    let theta = atan2(uv.y, uv.x);
    let logr = log(max(radius, 0.0001));
    let branches = clamp(global.u_branches, 1.0, 4.0);
    let spiral = clamp(global.u_spiral, 0.0, 0.90);
    let t = uniforms.time * clamp(global.u_zoom_speed, 0.0, 0.42);
    var angle = theta + (spiral * logr) - t;
    let scale_phase = logr - (t * 0.5);
    var scale = exp((scale_phase - (floor(scale_phase / 0.6931472) * 0.6931472)) - 0.6931472);
    let sector = 6.28318 / branches;
    angle = angle - (floor(angle / sector) * sector);
    let nuv = fract((vec2<f32>(cos(angle), sin(angle)) * scale) + center);
    let warped = textureSample(tex, tex_sampler, nuv);

    let source_luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence = smoothstep(0.025, 0.14, source_luma);
    let geometry_presence = max(surface_presence, 0.22);
    let outer_ring = smoothstep(0.12, 0.48, radius);
    let strength = geometry_presence * outer_ring * clamp((global.u_zoom_speed * 0.90) + (spiral * 0.35), 0.0, 0.56);
    fragColor = vec4<f32>(mix(source.xyz, warped.xyz, vec3<f32>(strength)), source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
