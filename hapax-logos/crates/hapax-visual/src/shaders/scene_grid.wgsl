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
    sphere_warmth: f32,
    _pad1: f32,
    occluders: array<GridOccluder, 16>,
};

@group(0) @binding(0)
var<uniform> grid: GridUniforms;

@group(1) @binding(0)
var reverie_texture: texture_2d<f32>;
@group(1) @binding(1)
var reverie_sampler: sampler;

const AOA_PI: f32 = 3.14159265358979;

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

fn scroom_material_pattern(gc: vec2<f32>, plane_kind: f32, world_dist: f32) -> f32 {
    // Multi-scale architectural material attached to room planes, not to the output pane.
    // Three frequency bands: structural, surface, grain.
    let bias = plane_kind * 0.173;
    let depth_freq = 1.0 + clamp(1.0 / (world_dist * 0.08 + 0.5), 0.0, 2.0);

    // Plane-aligned anisotropy: floor=horizontal, wall=vertical, ceiling=radial
    var aniso: vec2<f32>;
    if plane_kind < 0.5 {
        aniso = vec2<f32>(1.0, 0.4);
    } else if plane_kind < 1.5 {
        aniso = vec2<f32>(0.4, 1.0);
    } else {
        aniso = vec2<f32>(0.8, 0.8);
    }

    // Band 1: structural (low freq) — original cross-hatch
    let p = gc * 0.34 * depth_freq + vec2<f32>(bias, -bias * 0.71);
    let sp = p * aniso;
    let diag_a = abs(fract(sp.x + sp.y * 0.50) - 0.5);
    let diag_b = abs(fract(sp.x - sp.y * 0.50 + 0.21) - 0.5);
    let cross = abs(fract(sp.y * 0.62 + bias) - 0.5);
    let structural = max(
        max(smoothstep(0.040, 0.010, diag_a), smoothstep(0.040, 0.010, diag_b)),
        smoothstep(0.048, 0.014, cross) * 0.58,
    );

    // Band 2: surface roughness (mid freq) — Worley-like cellularization
    let cell = floor(p * 2.8);
    let facet = 0.5 + 0.5 * sin((cell.x * 1.37 + cell.y * 1.91) + plane_kind * 2.3);
    let cell_edge = min(
        abs(fract(p.x * 2.8) - 0.5),
        abs(fract(p.y * 2.8) - 0.5)
    );
    let surface = facet * 0.6 + smoothstep(0.08, 0.02, cell_edge) * 0.3;

    // Band 3: grain (high freq) — prevents flat reads under compression
    let grain_p = gc * 4.2 * depth_freq;
    let grain = fract(sin(dot(floor(grain_p), vec2<f32>(127.1, 311.7))) * 43758.5453);

    return clamp(0.18 + structural * 0.48 + surface * 0.22 + grain * 0.12, 0.0, 1.0);
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
        world = vec3<f32>(lp.x * 12.0, -2.0, lp.y * 12.0);
        n = vec3<f32>(0.0, 1.0, 0.0);
    } else if quad_idx == 1u {
        world = vec3<f32>(lp.x * 12.0, lp.y * 7.5 + 5.5, -8.0);
        n = vec3<f32>(0.0, 0.0, 1.0);
    } else if quad_idx == 2u {
        world = vec3<f32>(lp.x * 12.0, 13.0, lp.y * 12.0);
        n = vec3<f32>(0.0, -1.0, 0.0);
    } else if quad_idx == 3u {
        // Visible point-light marker. This is intentionally authored geometry,
        // not a hardware raytracing dependency.
        world = grid.light_position.xyz + vec3<f32>(lp.x * 0.28, lp.y * 0.28, 0.0);
        n = vec3<f32>(0.0, 0.0, 1.0);
    } else if quad_idx == 8u {
        // AoA insphere — ray-marched in fragment shader.
        // Billboard oversized to contain the sphere from any angle.
        let sphere_center = vec3<f32>(0.0, -0.4875, -1.36);
        let extent = 0.56;
        let vr = normalize(vec3<f32>(grid.view[0][0], grid.view[1][0], grid.view[2][0]));
        let vu = normalize(vec3<f32>(grid.view[0][1], grid.view[1][1], grid.view[2][1]));
        world = sphere_center + vr * lp.x * extent + vu * lp.y * extent;
        n = -normalize(vec3<f32>(grid.view[0][2], grid.view[1][2], grid.view[2][2]));
    } else {
        // Soft volumetric beam billboards from the moving light into the room.
        let start = grid.light_position.xyz;
        var end: vec3<f32>;
        // Beam endpoints at dual tetrahedron vertices (stella octangula)
        if quad_idx == 4u {
            end = vec3<f32>(1.160, 0.205, -2.340);
        } else if quad_idx == 5u {
            end = vec3<f32>(-1.160, 0.205, -2.340);
        } else if quad_idx == 6u {
            end = vec3<f32>(0.0, -1.875, -2.340);
        } else {
            end = vec3<f32>(0.0, -0.490, -3.300);
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

struct FragOutput {
    @location(0) color: vec4<f32>,
    @builtin(frag_depth) depth: f32,
};

@fragment
fn fs_main(in: VertexOutput) -> FragOutput {
    let wp = in.world_pos;
    let t = grid.time;
    let light_color = grid.light_color.rgb;
    let raster_depth = in.position.z;

    if in.plane_kind > 7.5 {
        // AoA insphere — ray-sphere intersection for perspective-correct 3D shading.
        let sphere_center = vec3<f32>(0.0, -0.4875, -1.36);
        let sphere_radius = 0.4777;

        let vt = grid.view[3].xyz;
        let cam_pos = -vec3<f32>(
            grid.view[0][0] * vt.x + grid.view[1][0] * vt.y + grid.view[2][0] * vt.z,
            grid.view[0][1] * vt.x + grid.view[1][1] * vt.y + grid.view[2][1] * vt.z,
            grid.view[0][2] * vt.x + grid.view[1][2] * vt.y + grid.view[2][2] * vt.z,
        );
        let ray_dir = normalize(wp - cam_pos);

        let oc = cam_pos - sphere_center;
        let b = dot(oc, ray_dir);
        let c = dot(oc, oc) - sphere_radius * sphere_radius;
        let discriminant = b * b - c;
        if discriminant < 0.0 {
            discard;
        }
        let t_hit = -b - sqrt(discriminant);
        if t_hit < 0.0 {
            discard;
        }
        let hit = cam_pos + ray_dir * t_hit;
        let sn = normalize(hit - sphere_center);

        // Project hit point to clip space for correct depth.
        let hit_clip = grid.projection * grid.view * vec4<f32>(hit, 1.0);
        let sphere_depth = hit_clip.z / hit_clip.w;

        // Equirectangular UV from world-space normal — full sphere coverage.
        // Content wraps the sphere stably in world space.
        let theta = atan2(sn.x, sn.z);
        let phi = acos(clamp(sn.y, -1.0, 1.0));
        let sphere_uv = vec2<f32>(
            (theta + AOA_PI) / (2.0 * AOA_PI),
            phi / AOA_PI,
        );
        let reverie = textureSample(reverie_texture, reverie_sampler, sphere_uv);

        let view_dir = normalize(cam_pos - hit);
        let fresnel = pow(1.0 - max(dot(sn, view_dir), 0.0), 2.0);
        let rim_hue = fract(hit.x * 0.035 + hit.z * 0.025 + grid.time * 0.01);
        let rh6 = rim_hue * 6.0;
        let rim_tint = vec3<f32>(
            clamp(abs(rh6 - 3.0) - 1.0, 0.0, 1.0),
            clamp(2.0 - abs(rh6 - 2.0), 0.0, 1.0),
            clamp(2.0 - abs(rh6 - 4.0), 0.0, 1.0),
        ) * vec3<f32>(0.5, 0.7, 1.0) + vec3<f32>(0.3, 0.3, 0.4);
        let rim = rim_tint * fresnel * 0.28;
        let shadow = soft_shadow_at(hit, grid.light_position.xyz);
        let ndotl = max(dot(sn, normalize(grid.light_position.xyz - hit)), 0.0);

        let w = clamp(grid.sphere_warmth, 0.0, 1.0);
        let floor_cool = vec3<f32>(0.06, 0.10, 0.22);
        let floor_warm = vec3<f32>(0.22, 0.12, 0.06);
        let emissive_floor = mix(floor_cool, floor_warm, w);
        let rev_content = reverie.rgb * 4.0 + emissive_floor;
        let shading = 0.55 + ndotl * 0.45 * shadow;
        var sphere_color = rev_content * shading + rim;
        let sphere_alpha = clamp(0.88 + fresnel * 0.08, 0.86, 0.95);
        return FragOutput(vec4<f32>(sphere_color, sphere_alpha), 0.999);
    }

    if in.plane_kind > 2.5 {
        if in.plane_kind < 3.5 {
            let d = length(in.local_pos);
            let core = smoothstep(0.34, 0.02, d);
            let halo = smoothstep(1.0, 0.08, d);
            let alpha = clamp(core * 0.58 + halo * 0.22, 0.0, 0.72);
            let color = light_color * (0.85 + core * 1.4);
            return FragOutput(vec4<f32>(color, alpha), 0.999);
        }

        let across = abs(in.local_pos.x);
        let progress = (in.local_pos.y + 1.0) * 0.5;
        let center = smoothstep(1.0, 0.0, across);
        let taper = (1.0 - progress * 0.82);
        let shimmer = 0.88;
        let alpha = center * taper * shimmer * 0.22;
        let color = light_color * (0.36 + 0.42 * center);
        return FragOutput(vec4<f32>(color, alpha), 1.0);
    }

    var gc: vec2<f32>;
    if abs(in.normal.y) > 0.5 {
        gc = vec2<f32>(wp.x, wp.z);
    } else {
        gc = vec2<f32>(wp.x, wp.y);
    }

    let is_horizontal_plane = abs(in.normal.y) > 0.5;
    let is_floor_or_ceiling = is_horizontal_plane;
    let sp = vec2<f32>(2.32, 2.32);
    var major: f32;
    var major_x: f32;
    var major_y: f32;
    if is_floor_or_ceiling {
        let s = sp.x;
        let la = abs(fract(gc.x / s + 0.5) - 0.5) * s;
        let lb = abs(fract((gc.x * 0.5 + gc.y * 0.866) / s + 0.5) - 0.5) * s;
        let lc = abs(fract((gc.x * 0.5 - gc.y * 0.866) / s + 0.5) - 0.5) * s;
        let ma = grid_line_mask(la, 0.006, 0.090);
        let mb = grid_line_mask(lb, 0.006, 0.090);
        let mc = grid_line_mask(lc, 0.006, 0.090);
        major = max(max(ma, mb), mc);
        major_x = max(ma, mb);
        major_y = max(mb, mc);
    } else {
        let lx = abs(fract(gc.x / sp.x + 0.5) - 0.5) * sp.x;
        let ly = abs(fract(gc.y / sp.y + 0.5) - 0.5) * sp.y;
        let ld = abs(fract((gc.x + gc.y) / (sp.x * 1.414) + 0.5) - 0.5) * sp.x * 1.414;
        major_x = grid_line_mask(lx, 0.006, 0.090);
        major_y = grid_line_mask(ly, 0.006, 0.090);
        let major_d = grid_line_mask(ld, 0.006, 0.060) * 0.6;
        major = max(max(major_x, major_y), major_d);
    }

    // Distance attenuation + atmospheric perspective
    let dist = length(wp - vec3(0.0, 0.0, 2.0));
    let dist_fade = max(smoothstep(14.0, 1.5, dist), 0.12);
    let atmospheric = 1.0 / (1.0 + 0.04 * dist);
    let depth_desat = clamp(1.0 - dist * 0.04, 0.5, 1.0);

    if major < 0.003 {
        let cell = floor(gc * 2.15);
        let local = fract(gc * 2.15);
        let center = vec2<f32>(
            0.30 + 0.40 * stipple_hash(cell + vec2<f32>(11.0, 37.0)),
            0.30 + 0.40 * stipple_hash(cell + vec2<f32>(53.0, 19.0))
        );
        let density_gate = step(0.62, stipple_hash(cell));
        let dot_alpha = density_gate * aa_disc_mask(length(local - center), 0.175);
        let material = scroom_material_pattern(gc, in.plane_kind, dist);
        let weave = 0.5 + 0.5 * sin(gc.x * 2.1 + gc.y * 1.7);
        let shadow = soft_shadow_at(wp, grid.light_position.xyz);
        let room_light = point_light_at(wp, in.normal) * shadow;
        var base_alpha = 0.32;
        if abs(in.normal.z) > 0.5 {
            base_alpha = 0.48;
        } else if is_floor_or_ceiling {
            base_alpha = 0.42;
        }
        let texture_signal = clamp(0.52 + 0.38 * material + 0.14 * weave + 0.24 * dot_alpha, 0.42, 1.0);
        // Per-surface tint: floor warm, ceiling cool, walls neutral.
        var surface_tint = vec3<f32>(0.18, 0.20, 0.30);
        if is_floor_or_ceiling && in.normal.y > 0.5 {
            surface_tint = vec3<f32>(0.22, 0.18, 0.16); // floor: warm
        } else if is_floor_or_ceiling {
            surface_tint = vec3<f32>(0.14, 0.18, 0.28); // ceiling: cool
        } else if abs(in.normal.z) > 0.5 {
            surface_tint = vec3<f32>(0.16, 0.20, 0.26); // back wall: blue
        }
        var plane_color = surface_tint
            + light_color * (0.10 + room_light * 0.32)
            + vec3<f32>(0.08, 0.10, 0.14) * material
            + vec3<f32>(0.04, 0.05, 0.08) * stipple_hash(cell + vec2<f32>(3.0, 7.0));
        plane_color = plane_color * (0.70 + 0.30 * shadow);
        let alpha = base_alpha * texture_signal * dist_fade * (0.86 + 0.14 * shadow);
        let pc_luma = dot(plane_color, vec3<f32>(0.299, 0.587, 0.114));
        let atmo_color = mix(vec3<f32>(pc_luma), plane_color, depth_desat) * atmospheric;
        return FragOutput(vec4<f32>(atmo_color * texture_signal * 1.6, alpha * (0.7 + 0.3 * atmospheric)), raster_depth);
    }

    // Synthwave neon: cycle cyan → magenta → blue
    let hue = fract(gc.x * 0.035 + gc.y * 0.025 + t * 0.01 + 0.55);
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

    let grid_luma = dot(color, vec3<f32>(0.299, 0.587, 0.114));
    color = mix(vec3<f32>(grid_luma), color, 1.8) * 1.2 * glow * dist_fade;
    color = color * (0.66 + 0.34 * shadow) + light_color * room_light * 0.32;
    var alpha = major * 0.50 * dist_fade * (0.82 + 0.18 * shadow + 0.12 * room_light);
    if abs(in.normal.y) > 0.5 {
        alpha = alpha * 1.16;
        color = color * 1.28;
    } else {
        alpha = alpha * 0.78;
        color = color * 0.88;
    }

    let grid_luma_final = dot(color, vec3<f32>(0.299, 0.587, 0.114));
    color = mix(vec3<f32>(grid_luma_final), color, depth_desat) * atmospheric;
    alpha = alpha * (0.7 + 0.3 * atmospheric);
    return FragOutput(vec4<f32>(color, alpha), raster_depth);
}
