// 3D perspective grid — floor, back wall, ceiling, and a mid-field plane
// for spatial depth through the occupied volume.
// Neon depth lines. They should read as spatial structure, not as a
// foreground scanner laid over the livestream surface.

struct GridUniforms {
    view: mat4x4<f32>,
    projection: mat4x4<f32>,
    time: f32,
    _pad0: f32,
    _pad1: f32,
    _pad2: f32,
};

@group(0) @binding(0)
var<uniform> grid: GridUniforms;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) world_pos: vec3<f32>,
    @location(1) normal: vec3<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VertexOutput {
    let quad_idx = vi / 6u;
    let local_vi = vi % 6u;

    var local_pos = array<vec2<f32>, 6>(
        vec2(-1.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
        vec2(-1.0, -1.0), vec2(1.0,  1.0), vec2(-1.0, 1.0),
    );
    let lp = local_pos[local_vi];

    var world: vec3<f32>;
    var n: vec3<f32>;

    if quad_idx == 0u {
        world = vec3<f32>(lp.x * 15.0, -2.0, lp.y * 8.0 - 4.0);
        n = vec3<f32>(0.0, 1.0, 0.0);
    } else if quad_idx == 1u {
        world = vec3<f32>(lp.x * 15.0, lp.y * 2.5 + 0.25, -9.0);
        n = vec3<f32>(0.0, 0.0, 1.0);
    } else if quad_idx == 2u {
        world = vec3<f32>(lp.x * 15.0, 2.5, lp.y * 8.0 - 4.0);
        n = vec3<f32>(0.0, -1.0, 0.0);
    } else {
        world = vec3<f32>(lp.x * 12.0, 0.35, lp.y * 6.5 - 4.2);
        n = vec3<f32>(0.0, 1.0, 0.0);
    }

    let clip = grid.projection * grid.view * vec4<f32>(world, 1.0);

    var out: VertexOutput;
    out.position = clip;
    out.world_pos = world;
    out.normal = n;
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let wp = in.world_pos;
    let t = grid.time;

    var gc: vec2<f32>;
    if abs(in.normal.y) > 0.5 {
        gc = vec2<f32>(wp.x, wp.z);
    } else {
        gc = vec2<f32>(wp.x, wp.y);
    }

    // Grid lines — present enough to establish depth, but narrow enough
    // not to become full-width horizontal bars under post effects.
    let sp = vec2<f32>(2.5, 1.8);
    let lx = abs(fract(gc.x / sp.x + 0.5) - 0.5) * sp.x;
    let ly = abs(fract(gc.y / sp.y + 0.5) - 0.5) * sp.y;
    let major_x = smoothstep(0.055, 0.009, lx);
    let major_y = smoothstep(0.055, 0.009, ly);
    let is_mid_field = abs(wp.y - 0.35) < 0.02;
    let major = select(
        max(major_x, major_y),
        max(major_x * 0.72, major_y * 0.16),
        is_mid_field,
    );

    if major < 0.01 {
        discard;
    }

    // Synthwave neon: cycle cyan → magenta → blue
    let hue = fract(gc.x * 0.035 + gc.y * 0.025 + t * 0.01);
    let h6 = hue * 6.0;
    var color = vec3<f32>(
        clamp(abs(h6 - 3.0) - 1.0, 0.0, 1.0),
        clamp(2.0 - abs(h6 - 2.0), 0.0, 1.0),
        clamp(2.0 - abs(h6 - 4.0), 0.0, 1.0)
    );
    // Boost blue/cyan
    color = color * vec3<f32>(0.5, 0.7, 1.0) + vec3<f32>(0.0, 0.05, 0.15);

    // Intersection glow nodes
    let glow = 1.0 + major_x * major_y * 2.6;

    // Distance attenuation
    let dist = length(wp - vec3(0.0, 0.0, 2.0));
    let dist_fade = smoothstep(22.0, 1.5, dist);

    // Luminescence
    let pulse = 0.96 + 0.04 * sin(t * 0.18 + gc.y * 0.2);

    color = color * 0.24 * glow * dist_fade * pulse;
    var alpha = major * 0.22 * dist_fade;
    if is_mid_field {
        alpha = alpha * 0.16;
        color = color * 0.38;
    } else if abs(in.normal.y) > 0.5 {
        alpha = alpha * 0.56;
        color = color * 0.66;
    } else {
        alpha = alpha * 0.08;
        color = color * 0.16;
    }

    return vec4<f32>(color, alpha);
}
