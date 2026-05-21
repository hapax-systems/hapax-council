// 3D perspective grid — floor, back wall, and ceiling.
// Neon depth lines. They should read as spatial structure, not as a
// foreground scanner laid over the livestream surface.

const MAX_SHADOW_OCCLUDERS: u32 = 16u;

struct GridOccluder {
    center: vec4<f32>,
    axis_x: vec4<f32>,
    axis_y: vec4<f32>,
    normal: vec4<f32>,
};

struct GridUniforms {
    view: mat4x4<f32>,
    projection: mat4x4<f32>,
    light_position: vec4<f32>,
    light_color: vec4<f32>,
    time: f32,
    occluder_count: u32,
    _pad0: f32,
    _pad1: f32,
    occluders: array<GridOccluder, 16>,
};

@group(0) @binding(0)
var<uniform> grid: GridUniforms;

fn stipple_hash(p: vec2<f32>) -> f32 {
    let q = vec2<f32>(
        dot(p, vec2<f32>(127.1, 311.7)),
        dot(p, vec2<f32>(269.5, 183.3))
    );
    return fract(sin(q.x + q.y) * 43758.5453);
}

fn aa_feather(value: f32, floor_value: f32) -> f32 {
    return max(fwidth(value) * 1.75, floor_value);
}

fn grid_line_mask(dist: f32, core_width: f32, outer_width: f32) -> f32 {
    let feather = aa_feather(dist, 0.0025);
    return 1.0 - smoothstep(core_width, outer_width + feather, dist);
}

fn aa_disc_mask(dist: f32, radius: f32) -> f32 {
    let feather = aa_feather(dist, 0.0015);
    return 1.0 - smoothstep(radius - feather, radius + feather, dist);
}

fn scroom_material_pattern(gc: vec2<f32>, plane_kind: f32) -> f32 {
    // Persistent low-frequency nebulous scroom material. This is attached
    // to room planes, not to the output pane, so it reads as spatial
    // structure rather than as a fourth-wall overlay.
    let bias = plane_kind * 0.173;
    let p = gc * 0.34 + vec2<f32>(bias, -bias * 0.71);
    let diag_a = abs(fract(p.x + p.y * 0.50) - 0.5);
    let diag_b = abs(fract(p.x - p.y * 0.50 + 0.21) - 0.5);
    let cross = abs(fract(p.y * 0.62 + bias) - 0.5);
    let tri = max(
        max(smoothstep(0.040, 0.010, diag_a), smoothstep(0.040, 0.010, diag_b)),
        smoothstep(0.048, 0.014, cross) * 0.58,
    );
    let cell = floor(p);
    let facet = 0.5 + 0.5 * sin((cell.x * 1.37 + cell.y * 1.91) + plane_kind * 2.3);
    return clamp(0.22 + tri * 0.58 + facet * 0.10, 0.0, 1.0);
}

fn soft_shadow_at(world_pos: vec3<f32>, light_pos: vec3<f32>) -> f32 {
    let ray = light_pos - world_pos;
    var shadow = 1.0;

    for (var i = 0u; i < MAX_SHADOW_OCCLUDERS; i = i + 1u) {
        if i >= grid.occluder_count {
            break;
        }

        let occ = grid.occluders[i];
        let center = occ.center.xyz;
        let normal = normalize(occ.normal.xyz);
        let denom = dot(normal, ray);
        if abs(denom) < 0.0001 {
            continue;
        }

        let t = dot(normal, center - world_pos) / denom;
        if t <= 0.015 || t >= 0.985 {
            continue;
        }

        let hit = world_pos + ray * t;
        let rel = hit - center;
        let ux = normalize(occ.axis_x.xyz);
        let uy = normalize(occ.axis_y.xyz);
        let half_w = max(occ.axis_x.w, 0.001);
        let half_h = max(occ.axis_y.w, 0.001);
        let u = abs(dot(rel, ux));
        let v = abs(dot(rel, uy));
        if u > half_w || v > half_h {
            continue;
        }

        let edge_u = 1.0 - smoothstep(half_w * 0.72, half_w, u);
        let edge_v = 1.0 - smoothstep(half_h * 0.72, half_h, v);
        let softness = edge_u * edge_v;
        let distance_fade = smoothstep(0.0, 9.0, length(light_pos - center));
        let strength = clamp(occ.normal.w * 0.58 * softness * distance_fade, 0.0, 0.34);
        shadow = shadow * (1.0 - strength);
    }

    return clamp(shadow, 0.48, 1.0);
}

fn point_light_at(world_pos: vec3<f32>, normal: vec3<f32>) -> f32 {
    let to_light = grid.light_position.xyz - world_pos;
    let dist = length(to_light);
    let ldir = normalize(to_light);
    let lambert = max(dot(normalize(normal), ldir), 0.0);
    let attenuation = 1.0 / (1.0 + 0.16 * dist + 0.025 * dist * dist);
    return clamp(lambert * attenuation * 2.4, 0.0, 0.72);
}

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) world_pos: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) local_pos: vec2<f32>,
    @location(3) plane_kind: f32,
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
    } else if quad_idx == 3u {
        // Visible point-light marker. This is intentionally authored geometry,
        // not a hardware raytracing dependency.
        world = grid.light_position.xyz + vec3<f32>(lp.x * 0.28, lp.y * 0.28, 0.0);
        n = vec3<f32>(0.0, 0.0, 1.0);
    } else if quad_idx == 8u {
        // AoA inner sphere billboard at tetrix centroid.
        let center = vec3<f32>(0.0, -0.094, 0.10);
        let radius = 0.18;
        let view_right = normalize(vec3<f32>(grid.view[0][0], grid.view[1][0], grid.view[2][0]));
        let view_up = normalize(vec3<f32>(grid.view[0][1], grid.view[1][1], grid.view[2][1]));
        world = center + view_right * lp.x * radius + view_up * lp.y * radius;
        n = normalize(vec3<f32>(grid.view[0][2], grid.view[1][2], grid.view[2][2]));
    } else {
        // Soft volumetric beam billboards from the moving light into the room.
        let start = grid.light_position.xyz;
        var end: vec3<f32>;
        if quad_idx == 4u {
            end = vec3<f32>(0.0, 0.25, -4.6);
        } else if quad_idx == 5u {
            end = vec3<f32>(-3.2, -1.15, -3.2);
        } else if quad_idx == 6u {
            end = vec3<f32>(3.0, -1.05, -3.7);
        } else {
            end = vec3<f32>(0.0, 2.2, -5.8);
        }
        let along = normalize(end - start);
        var side = cross(along, vec3<f32>(0.0, 1.0, 0.0));
        if length(side) < 0.01 {
            side = vec3<f32>(1.0, 0.0, 0.0);
        }
        side = normalize(side);
        let progress = (lp.y + 1.0) * 0.5;
        let width = mix(0.12, 0.032, progress);
        world = mix(start, end, progress) + side * lp.x * width;
        n = vec3<f32>(0.0, 0.0, 1.0);
    }

    let clip = grid.projection * grid.view * vec4<f32>(world, 1.0);

    var out: VertexOutput;
    out.position = clip;
    out.world_pos = world;
    out.normal = n;
    out.local_pos = lp;
    out.plane_kind = f32(quad_idx);
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let wp = in.world_pos;
    let t = grid.time;
    let light_color = grid.light_color.rgb;

    if in.plane_kind > 7.5 {
        // AoA inner sphere — inscribed core at tetrix centroid.
        let d = length(in.local_pos);
        if d > 1.0 {
            discard;
        }
        let fresnel = pow(d, 2.2);
        let rim = smoothstep(0.62, 0.98, d);
        let inner_glow = smoothstep(0.58, 0.0, d) * 0.28;
        let sphere_alpha = clamp(rim * 0.42 + inner_glow + fresnel * 0.14, 0.0, 0.52);
        let shadow = soft_shadow_at(wp, grid.light_position.xyz);
        let room_light = point_light_at(wp, in.normal) * shadow;
        var sphere_color = light_color * (0.30 + rim * 0.65 + room_light * 0.18);
        sphere_color = sphere_color + vec3<f32>(0.04, 0.06, 0.12) * inner_glow * 3.0;
        return vec4<f32>(sphere_color, sphere_alpha * (0.82 + 0.18 * shadow));
    }

    if in.plane_kind > 2.5 {
        if in.plane_kind < 3.5 {
            let d = length(in.local_pos);
            let core = smoothstep(0.34, 0.02, d);
            let halo = smoothstep(1.0, 0.08, d);
            let alpha = clamp(core * 0.58 + halo * 0.22, 0.0, 0.72);
            let color = light_color * (0.85 + core * 1.4);
            return vec4<f32>(color, alpha);
        }

        let across = abs(in.local_pos.x);
        let progress = (in.local_pos.y + 1.0) * 0.5;
        let center = smoothstep(1.0, 0.0, across);
        let taper = (1.0 - progress * 0.82);
        let shimmer = 0.88;
        let alpha = center * taper * shimmer * 0.22;
        let color = light_color * (0.36 + 0.42 * center);
        return vec4<f32>(color, alpha);
    }

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
    let major_x = grid_line_mask(lx, 0.006, 0.090);
    let major_y = grid_line_mask(ly, 0.006, 0.090);
    let is_horizontal_plane = abs(in.normal.y) > 0.5;
    let is_floor_or_ceiling = is_horizontal_plane;
    let major = max(major_x, major_y);

    // Distance attenuation
    let dist = length(wp - vec3(0.0, 0.0, 2.0));
    let dist_fade = max(smoothstep(22.0, 1.5, dist), 0.30);

    if major < 0.003 {
        let cell = floor(gc * 2.15);
        let local = fract(gc * 2.15);
        let center = vec2<f32>(
            0.30 + 0.40 * stipple_hash(cell + vec2<f32>(11.0, 37.0)),
            0.30 + 0.40 * stipple_hash(cell + vec2<f32>(53.0, 19.0))
        );
        let density_gate = step(0.62, stipple_hash(cell));
        let dot_alpha = density_gate * aa_disc_mask(length(local - center), 0.175);
        let material = scroom_material_pattern(gc, in.plane_kind);
        let weave = 0.5 + 0.5 * sin(gc.x * 2.1 + gc.y * 1.7);
        let shadow = soft_shadow_at(wp, grid.light_position.xyz);
        let room_light = point_light_at(wp, in.normal) * shadow;
        var base_alpha = 0.200;
        if abs(in.normal.z) > 0.5 {
            base_alpha = 0.320;
        } else if is_floor_or_ceiling {
            base_alpha = 0.280;
        }
        let texture_signal = clamp(0.52 + 0.38 * material + 0.14 * weave + 0.24 * dot_alpha, 0.42, 1.0);
        var plane_color = vec3<f32>(0.120, 0.135, 0.190)
            + light_color * (0.060 + room_light * 0.20)
            + vec3<f32>(0.052, 0.068, 0.092) * material
            + vec3<f32>(0.022, 0.032, 0.048) * stipple_hash(cell + vec2<f32>(3.0, 7.0));
        plane_color = plane_color * (0.70 + 0.30 * shadow);
        let alpha = base_alpha * texture_signal * dist_fade * (0.86 + 0.14 * shadow);
        return vec4<f32>(plane_color * texture_signal, alpha);
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

    // Luminescence
    let shadow = soft_shadow_at(wp, grid.light_position.xyz);
    let room_light = point_light_at(wp, in.normal) * shadow;

    color = color * 0.72 * glow * dist_fade;
    color = color * (0.66 + 0.34 * shadow) + light_color * room_light * 0.22;
    var alpha = major * 0.50 * dist_fade * (0.82 + 0.18 * shadow + 0.12 * room_light);
    if abs(in.normal.y) > 0.5 {
        alpha = alpha * 1.16;
        color = color * 1.28;
    } else {
        alpha = alpha * 0.78;
        color = color * 0.88;
    }

    return vec4<f32>(color, alpha);
}
