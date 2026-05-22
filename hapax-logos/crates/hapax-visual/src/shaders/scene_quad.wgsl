// Scene quad vertex+fragment shader for 3D compositor Phase 0.
//
// Renders textured quads in 3D space using model/view/projection matrices.
// The fragment shader samples the bound texture and applies per-quad opacity.

struct SceneUniforms {
    model: mat4x4<f32>,
    view: mat4x4<f32>,
    projection: mat4x4<f32>,
    opacity: f32,
    shader_kind: f32,
    payload_pane_ordinal: f32,
    payload_mode: f32,
    local_effect_kind: f32,
    local_effect_mix: f32,
    local_effect_param_a: f32,
    local_effect_param_b: f32,
};

@group(0) @binding(0)
var<uniform> scene: SceneUniforms;

@group(1) @binding(0)
var quad_texture: texture_2d<f32>;
@group(1) @binding(1)
var quad_sampler: sampler;

struct HeatmapEntry {
    heat: f32,
    hue: f32,
    sat: f32,
    _pad: f32,
};
@group(2) @binding(0)
var<storage, read> heatmap: array<HeatmapEntry>;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
    @location(1) barycentric: vec3<f32>,
    @location(2) pane_info: vec4<f32>,
    @location(3) local_pos: vec3<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VertexOutput {
    if scene.shader_kind > 0.5 {
        return aoa_vertex(vi);
    }

    // Unit quad: two triangles covering [-0.5, 0.5] in XY.
    var positions = array<vec2<f32>, 6>(
        vec2<f32>(-0.5, -0.5),
        vec2<f32>( 0.5, -0.5),
        vec2<f32>( 0.5,  0.5),
        vec2<f32>(-0.5, -0.5),
        vec2<f32>( 0.5,  0.5),
        vec2<f32>(-0.5,  0.5),
    );

    let pos = positions[vi];
    let world_pos = scene.model * vec4<f32>(pos.x, pos.y, 0.0, 1.0);
    let clip_pos = scene.projection * scene.view * world_pos;

    var out: VertexOutput;
    out.position = clip_pos;
    // UV: map [-0.5, 0.5] to [0, 1], flip Y for texture convention
    out.uv = vec2<f32>(pos.x + 0.5, 1.0 - (pos.y + 0.5));
    out.barycentric = vec3<f32>(0.0, 0.0, 0.0);
    out.pane_info = vec4<f32>(0.0, 0.0, 0.0, 0.0);
    out.local_pos = vec3<f32>(pos.x, pos.y, 0.0);
    return out;
}

fn segment_distance(p: vec2<f32>, a: vec2<f32>, b: vec2<f32>) -> f32 {
    let pa = p - a;
    let ba = b - a;
    let h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}

fn pick_tetra_vertex(a: vec3<f32>, b: vec3<f32>, c: vec3<f32>, d: vec3<f32>, idx: u32) -> vec3<f32> {
    if idx == 0u {
        return a;
    }
    if idx == 1u {
        return b;
    }
    if idx == 2u {
        return c;
    }
    return d;
}

fn child_tetra_vertex(
    a: vec3<f32>,
    b: vec3<f32>,
    c: vec3<f32>,
    d: vec3<f32>,
    child_idx: u32,
    vertex_idx: u32,
) -> vec3<f32> {
    let anchor = pick_tetra_vertex(a, b, c, d, child_idx);
    let corner = pick_tetra_vertex(a, b, c, d, vertex_idx);
    return mix(anchor, corner, 0.5);
}

const AOA_OUTER_PANE_COUNT: u32 = 4u;
const AOA_INNER_PANE_COUNT_DEPTH_1: u32 = 16u;
const AOA_INNER_PANE_COUNT_DEPTH_2: u32 = 64u;
const AOA_INNER_PANE_COUNT_DEPTH_3: u32 = 256u;
const AOA_DEPTH_2_PANES_PER_CHILD: u32 = 16u;
const AOA_DEPTH_3_PANES_PER_CHILD: u32 = 64u;
const AOA_TOTAL_PANE_COUNT: u32 = AOA_OUTER_PANE_COUNT
    + AOA_INNER_PANE_COUNT_DEPTH_1
    + AOA_INNER_PANE_COUNT_DEPTH_2
    + AOA_INNER_PANE_COUNT_DEPTH_3;

fn aoa_barycentric(corner_idx: u32) -> vec3<f32> {
    if corner_idx == 0u {
        return vec3<f32>(1.0, 0.0, 0.0);
    }
    if corner_idx == 1u {
        return vec3<f32>(0.0, 1.0, 0.0);
    }
    return vec3<f32>(0.0, 0.0, 1.0);
}

fn triangle_edge_distance(p: vec2<f32>, a: vec2<f32>, b: vec2<f32>, c: vec2<f32>) -> f32 {
    return min(
        segment_distance(p, a, b),
        min(segment_distance(p, b, c), segment_distance(p, c, a)),
    );
}

fn triangle_barycentric(p: vec2<f32>, a: vec2<f32>, b: vec2<f32>, c: vec2<f32>) -> vec3<f32> {
    let v0 = b - a;
    let v1 = c - a;
    let v2 = p - a;
    let denom = v0.x * v1.y - v1.x * v0.y;
    if abs(denom) < 0.00001 {
        return vec3<f32>(-1.0, -1.0, -1.0);
    }
    let u = (v2.x * v1.y - v1.x * v2.y) / denom;
    let v = (v0.x * v2.y - v2.x * v0.y) / denom;
    let w = 1.0 - u - v;
    return vec3<f32>(u, v, w);
}

fn triangle_inside_mask_from_barycentric(bary: vec3<f32>) -> f32 {
    return step(-0.001, bary.x) * step(-0.001, bary.y) * step(-0.001, bary.z);
}

fn pane_information_uv_from_barycentric(bary: vec3<f32>) -> vec2<f32> {
    // Stable local coordinates for a triangular information surface. Each
    // pane can use the same barycentric address space regardless of which
    // tetrahedral face or recursive inner face produced it.
    return vec2<f32>(bary.y + bary.z * 0.5, bary.z * 0.8660254);
}

fn aa_feather(value: f32, floor_value: f32) -> f32 {
    return max(fwidth(value) * 1.75, floor_value);
}

fn aa_line_mask(dist: f32, core_width: f32, outer_width: f32) -> f32 {
    let feather = aa_feather(dist, 0.0015);
    return 1.0 - smoothstep(core_width, max(outer_width, core_width + feather), dist);
}

fn pane_information_grid(local_uv: vec2<f32>, inside: f32) -> f32 {
    let grid = fract(local_uv * vec2<f32>(7.0, 7.0));
    let edge_dist = min(min(grid.x, 1.0 - grid.x), min(grid.y, 1.0 - grid.y));
    return inside * aa_line_mask(edge_dist, 0.010, 0.026);
}

fn pane_payload_sample_uv(local_uv: vec2<f32>) -> vec2<f32> {
    return vec2<f32>(
        clamp(local_uv.x, 0.0, 1.0),
        clamp(1.0 - local_uv.y / 0.8660254, 0.0, 1.0),
    );
}

fn quantized_payload_sample_uv(uv: vec2<f32>, cells: f32) -> vec2<f32> {
    let safe_cells = max(cells, 1.0);
    let max_cell = safe_cells - 1.0;
    let clamped_uv = clamp(uv, vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 1.0));
    let cell = clamp(
        floor(clamped_uv * safe_cells),
        vec2<f32>(0.0, 0.0),
        vec2<f32>(max_cell, max_cell),
    );
    return (cell + vec2<f32>(0.5, 0.5)) / safe_cells;
}

fn payload_luma(color: vec3<f32>) -> f32 {
    return dot(color, vec3<f32>(0.2126, 0.7152, 0.0722));
}

fn line_mask(dist: f32, width: f32, feather: f32) -> f32 {
    let derivative = aa_feather(dist, feather);
    return 1.0 - smoothstep(width, width + derivative, dist);
}

fn local_effect_geometry_presence(color: vec3<f32>) -> f32 {
    let luma = dot(color, vec3<f32>(0.299, 0.587, 0.114));
    return max(smoothstep(0.025, 0.14, luma), 0.22);
}

fn local_effect_noise(p: vec2<f32>) -> f32 {
    return fract(sin(dot(p, vec2<f32>(127.1, 311.7))) * 43758.547);
}

fn entity_local_mirror(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    var folded_uv = uv;
    let axis = scene.local_effect_param_a;
    let position = clamp(scene.local_effect_param_b, 0.30, 0.70);
    if axis < 0.5 {
        if uv.x > position {
            folded_uv.x = (2.0 * position) - uv.x;
        }
    } else {
        if uv.y > position {
            folded_uv.y = (2.0 * position) - uv.y;
        }
    }
    folded_uv = clamp(folded_uv, vec2<f32>(0.001), vec2<f32>(0.999));
    let folded = textureSample(quad_texture, quad_sampler, folded_uv);
    let fold_dist = abs(select(uv.x, uv.y, axis > 0.5) - position);
    let fold_glint = 1.0 - smoothstep(0.0, 0.11, fold_dist);
    let delta = folded.rgb - original.rgb;
    let edge_presence = smoothstep(0.06, 0.38, length(delta));
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let tint = vec3<f32>(0.18, 0.68, 0.96);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * edge_presence * 0.58 + tint * fold_glint * 0.12)
        * scene.local_effect_mix
        * geometry_presence;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn entity_local_kaleidoscope(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    let center = vec2<f32>(0.5, 0.5);
    let centered = uv - center;
    var angle = atan2(centered.y, centered.x) + scene.local_effect_param_b * 0.18;
    let radius = length(centered);
    let segments = clamp(scene.local_effect_param_a, 3.0, 7.0);
    let segment_angle = 6.2831853 / segments;
    angle = angle - floor(angle / segment_angle) * segment_angle;
    if angle > segment_angle * 0.5 {
        angle = segment_angle - angle;
    }
    let warped_uv = clamp(center + radius * vec2<f32>(cos(angle), sin(angle)), vec2<f32>(0.001), vec2<f32>(0.999));
    let warped = textureSample(quad_texture, quad_sampler, warped_uv);
    let segment_line = 1.0 - smoothstep(0.0, 0.040, abs(angle - segment_angle * 0.5));
    let delta = warped.rgb - original.rgb;
    let edge_presence = smoothstep(0.06, 0.40, length(delta));
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let tint = vec3<f32>(0.82, 0.22, 0.96);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * edge_presence * 0.54 + tint * segment_line * 0.07)
        * scene.local_effect_mix
        * geometry_presence;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn entity_local_warp(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    let slices = clamp(scene.local_effect_param_a, 4.0, 11.0);
    let slice_idx = floor(uv.y * slices);
    let slice_phase = scene.local_effect_param_b + slice_idx * 0.47;
    let shift = (sin(slice_phase) * 0.026) + (sin(slice_phase * 2.31) * 0.012);
    let shear = (uv.y - 0.5) * sin(scene.local_effect_param_b * 0.7) * 0.030;
    let warped_uv = clamp(vec2<f32>(uv.x + shift + shear, uv.y), vec2<f32>(0.001), vec2<f32>(0.999));
    let warped = textureSample(quad_texture, quad_sampler, warped_uv);
    let slice_line = smoothstep(0.965, 1.0, fract(uv.y * slices));
    let delta = warped.rgb - original.rgb;
    let edge_presence = smoothstep(0.05, 0.36, length(delta));
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let tint = vec3<f32>(0.12, 0.78, 0.68);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * edge_presence * 0.62 + tint * slice_line * 0.045)
        * scene.local_effect_mix
        * geometry_presence;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn entity_local_fisheye(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    let center = vec2<f32>(0.5, 0.5) + vec2<f32>(cos(scene.local_effect_param_b), sin(scene.local_effect_param_b * 0.83)) * 0.055;
    let centered = uv - center;
    let radius = length(centered);
    let theta = atan2(centered.y, centered.x);
    let strength = clamp(scene.local_effect_param_a, 0.10, 0.58);
    let rd = radius * (1.0 + strength * radius * radius);
    let zoom = 1.0 + sin(scene.local_effect_param_b * 0.71) * 0.035;
    let warped_uv = clamp(center + (rd * vec2<f32>(cos(theta), sin(theta)) / vec2<f32>(zoom)), vec2<f32>(0.001), vec2<f32>(0.999));
    let warped = textureSample(quad_texture, quad_sampler, warped_uv);
    let delta = warped.rgb - original.rgb;
    let edge_presence = smoothstep(0.06, 0.40, length(delta));
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let radial_glint = smoothstep(0.08, 0.42, radius) * (1.0 - smoothstep(0.42, 0.76, radius));
    let tint = vec3<f32>(0.20, 0.62, 0.95);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * edge_presence * 0.64 + tint * radial_glint * 0.045)
        * scene.local_effect_mix
        * geometry_presence
        * strength;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn entity_local_transform(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    let pivot = vec2<f32>(0.5, 0.5) + vec2<f32>(sin(scene.local_effect_param_b), cos(scene.local_effect_param_b * 0.73)) * 0.055;
    var p = uv - pivot;
    let rotation = sin(scene.local_effect_param_b) * clamp(scene.local_effect_param_a, 0.0, 0.12);
    let c = cos(rotation);
    let s = sin(rotation);
    p = mat2x2<f32>(vec2<f32>(c, s), vec2<f32>(-s, c)) * p;
    let scale = vec2<f32>(
        1.0 + abs(sin(scene.local_effect_param_b * 0.61)) * 0.055,
        1.0 + abs(cos(scene.local_effect_param_b * 0.47)) * 0.042,
    );
    let offset = vec2<f32>(sin(scene.local_effect_param_b * 1.7), cos(scene.local_effect_param_b * 1.3)) * 0.020;
    let transformed_uv = clamp((p / scale) + pivot - offset, vec2<f32>(0.001), vec2<f32>(0.999));
    let transformed = textureSample(quad_texture, quad_sampler, transformed_uv);
    let delta = transformed.rgb - original.rgb;
    let edge_presence = smoothstep(0.06, 0.42, length(delta));
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let pivot_glint = 1.0 - smoothstep(0.0, 0.36, length(uv - pivot));
    let tint = vec3<f32>(0.52, 0.30, 0.95);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * edge_presence * 0.64 + tint * pivot_glint * 0.030)
        * scene.local_effect_mix
        * geometry_presence;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn entity_local_displacement_map(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    let frequency = 5.0 + scene.local_effect_param_a * 28.0;
    let n1 = local_effect_noise(uv * frequency + vec2<f32>(scene.local_effect_param_b, 0.0));
    let n2 = local_effect_noise(uv * (frequency * 1.7) + vec2<f32>(0.0, scene.local_effect_param_b * 1.3));
    let offset = (vec2<f32>(n1, n2) - vec2<f32>(0.5)) * scene.local_effect_param_a * 0.18;
    let warped_uv = clamp(uv + offset, vec2<f32>(0.001), vec2<f32>(0.999));
    let warped = textureSample(quad_texture, quad_sampler, warped_uv);
    let delta = warped.rgb - original.rgb;
    let edge_presence = smoothstep(0.05, 0.38, length(delta));
    let offset_energy = smoothstep(0.002, 0.045, length(offset));
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let tint = vec3<f32>(0.95, 0.36, 0.14);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * edge_presence * 0.72 + tint * offset_energy * 0.035)
        * scene.local_effect_mix
        * geometry_presence;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn entity_local_droste(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    let center = vec2<f32>(0.5, 0.5);
    let p = uv - center;
    let radius = length(p);
    let theta = atan2(p.y, p.x);
    let logr = log(max(radius, 0.0001));
    let spiral = 0.22 + 0.66 * abs(sin(scene.local_effect_param_b * 0.37));
    let zoom_phase = scene.local_effect_param_b * clamp(scene.local_effect_param_a, 0.12, 0.42);
    var angle = theta + spiral * logr - zoom_phase;
    let scale_phase = logr - zoom_phase * 0.5;
    let branch_count = 1.0 + floor(abs(sin(scene.local_effect_param_b * 0.53)) * 4.0);
    let sector = 6.2831853 / branch_count;
    angle = angle - floor(angle / sector) * sector;
    let scale = exp((scale_phase - floor(scale_phase / 0.6931472) * 0.6931472) - 0.6931472);
    let warped_uv = fract(vec2<f32>(cos(angle), sin(angle)) * scale + center);
    let warped = textureSample(quad_texture, quad_sampler, warped_uv);
    let delta = warped.rgb - original.rgb;
    let edge_presence = smoothstep(0.06, 0.42, length(delta));
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let outer_ring = smoothstep(0.12, 0.48, radius);
    let ring_glint = 1.0 - smoothstep(0.0, 0.055, abs(fract(logr / 0.6931472) - 0.5));
    let tint = vec3<f32>(0.88, 0.20, 0.58);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * edge_presence * 0.62 + tint * ring_glint * 0.035)
        * scene.local_effect_mix
        * geometry_presence
        * outer_ring;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn entity_local_tunnel(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    let centered = uv - vec2<f32>(0.5);
    let radius = length(centered);
    let angle = atan2(centered.y, centered.x);
    let tunnel_r = (0.08 + scene.local_effect_param_a * 0.20) / (radius + 0.001) + scene.local_effect_param_b * 0.08;
    var tunnel_a = (angle / 3.1415927) + scene.local_effect_param_a * tunnel_r * 0.10;
    tunnel_a = tunnel_a + sin(tunnel_r * (1.2 + scene.local_effect_param_a * 4.8)) * 0.075;
    let warped_uv = fract(vec2<f32>(tunnel_a, tunnel_r));
    let tunnel = textureSample(quad_texture, quad_sampler, warped_uv);
    let delta = tunnel.rgb - original.rgb;
    let edge_presence = smoothstep(0.06, 0.42, length(delta));
    let edge_weight = smoothstep(0.08, 0.44, radius);
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let ray = pow(max(0.0, sin(tunnel_a * 18.0) * 0.5 + 0.5), 5.0);
    let tint = vec3<f32>(0.10, 0.78, 0.72);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * edge_presence * 0.64 + tint * ray * 0.028)
        * scene.local_effect_mix
        * geometry_presence
        * edge_weight;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn entity_local_tile(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    let counts = vec2<f32>(clamp(scene.local_effect_param_a, 1.8, 5.5));
    let tiled_space = uv * counts;
    let cell = floor(tiled_space);
    var f = fract(tiled_space);
    if scene.local_effect_param_b > 0.5 {
        if (cell.x - floor(cell.x / 2.0) * 2.0) > 0.5 {
            f.x = 1.0 - f.x;
        }
        if (cell.y - floor(cell.y / 2.0) * 2.0) > 0.5 {
            f.y = 1.0 - f.y;
        }
    }
    let gap = 0.018 + 0.018 * abs(sin(scene.local_effect_param_b * 6.2831853));
    let edge = max(
        1.0 - smoothstep(0.0, gap, min(f.x, 1.0 - f.x)),
        1.0 - smoothstep(0.0, gap, min(f.y, 1.0 - f.y)),
    );
    let tiled = textureSample(quad_texture, quad_sampler, clamp(f, vec2<f32>(0.001), vec2<f32>(0.999)));
    let delta = tiled.rgb - original.rgb;
    let detail_presence = smoothstep(0.08, 0.46, length(delta));
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let tint = vec3<f32>(0.10, 0.58, 0.72);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * detail_presence * 0.62 + tint * edge * 0.055)
        * scene.local_effect_mix
        * geometry_presence;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn entity_local_drift(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    let frequency = 2.5 + scene.local_effect_param_a * 70.0;
    let n1 = local_effect_noise(uv * frequency + vec2<f32>(scene.local_effect_param_b * 0.17));
    let n2 = local_effect_noise(uv * frequency * 1.61 + vec2<f32>(scene.local_effect_param_b * 0.29, scene.local_effect_param_b * 0.11));
    let drift_vector = vec2<f32>(n1, n2) - vec2<f32>(0.5);
    let offset = drift_vector * scene.local_effect_param_a * 0.80;
    let drifted = textureSample(quad_texture, quad_sampler, clamp(uv + offset, vec2<f32>(0.001), vec2<f32>(0.999)));
    let delta = drifted.rgb - original.rgb;
    let edge_presence = smoothstep(0.05, 0.34, length(delta));
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let tint = vec3<f32>(0.30, 0.88, 0.34);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * edge_presence * 0.62 + tint * length(offset) * 0.70)
        * scene.local_effect_mix
        * geometry_presence;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn entity_local_breathing(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    let center = vec2<f32>(0.5, 0.5);
    let scale = 1.0 + sin(scene.local_effect_param_b) * clamp(scene.local_effect_param_a, 0.0, 0.026);
    let warped_uv = clamp(((uv - center) / vec2<f32>(scale)) + center, vec2<f32>(0.001), vec2<f32>(0.999));
    let warped = textureSample(quad_texture, quad_sampler, warped_uv);
    let delta = warped.rgb - original.rgb;
    let edge_presence = smoothstep(0.04, 0.30, length(delta));
    let geometry_presence = local_effect_geometry_presence(original.rgb);
    let tint = vec3<f32>(0.95, 0.62, 0.18);
    let lifted = original.rgb + (max(delta, vec3<f32>(0.0)) * edge_presence * 0.48 + tint * abs(scale - 1.0) * 0.50)
        * scene.local_effect_mix
        * geometry_presence;
    return vec4<f32>(max(original.rgb, lifted), original.a);
}

fn apply_entity_local_spatial_effect(uv: vec2<f32>, original: vec4<f32>) -> vec4<f32> {
    if scene.local_effect_mix <= 0.001 {
        return original;
    }
    if scene.local_effect_kind > 0.5 && scene.local_effect_kind < 1.5 {
        return entity_local_mirror(uv, original);
    }
    if scene.local_effect_kind > 1.5 && scene.local_effect_kind < 2.5 {
        return entity_local_kaleidoscope(uv, original);
    }
    if scene.local_effect_kind > 2.5 && scene.local_effect_kind < 3.5 {
        return entity_local_warp(uv, original);
    }
    if scene.local_effect_kind > 3.5 && scene.local_effect_kind < 4.5 {
        return entity_local_fisheye(uv, original);
    }
    if scene.local_effect_kind > 4.5 && scene.local_effect_kind < 5.5 {
        return entity_local_transform(uv, original);
    }
    if scene.local_effect_kind > 5.5 && scene.local_effect_kind < 6.5 {
        return entity_local_displacement_map(uv, original);
    }
    if scene.local_effect_kind > 6.5 && scene.local_effect_kind < 7.5 {
        return entity_local_droste(uv, original);
    }
    if scene.local_effect_kind > 7.5 && scene.local_effect_kind < 8.5 {
        return entity_local_tunnel(uv, original);
    }
    if scene.local_effect_kind > 8.5 && scene.local_effect_kind < 9.5 {
        return entity_local_tile(uv, original);
    }
    if scene.local_effect_kind > 9.5 && scene.local_effect_kind < 10.5 {
        return entity_local_drift(uv, original);
    }
    if scene.local_effect_kind > 10.5 && scene.local_effect_kind < 11.5 {
        return entity_local_breathing(uv, original);
    }
    return original;
}

fn aoa_face_vertex(a: vec3<f32>, b: vec3<f32>, c: vec3<f32>, d: vec3<f32>, face_idx: u32, corner_idx: u32) -> vec3<f32> {
    if face_idx == 0u {
        return pick_tetra_vertex(a, b, d, c, corner_idx);
    }
    if face_idx == 1u {
        return pick_tetra_vertex(b, c, d, a, corner_idx);
    }
    if face_idx == 2u {
        return pick_tetra_vertex(c, a, d, b, corner_idx);
    }
    return pick_tetra_vertex(a, c, b, d, corner_idx);
}

fn aoa_pane_vertex(
    a: vec3<f32>,
    b: vec3<f32>,
    c: vec3<f32>,
    d: vec3<f32>,
    pane_idx: u32,
    corner_idx: u32,
) -> vec3<f32> {
    if pane_idx < AOA_OUTER_PANE_COUNT {
        return aoa_face_vertex(a, b, c, d, pane_idx, corner_idx);
    }

    let inner_idx = pane_idx - AOA_OUTER_PANE_COUNT;
    if inner_idx < AOA_INNER_PANE_COUNT_DEPTH_1 {
        let child_idx = inner_idx / 4u;
        let face_idx = inner_idx % 4u;
        let ca = child_tetra_vertex(a, b, c, d, child_idx, 0u);
        let cb = child_tetra_vertex(a, b, c, d, child_idx, 1u);
        let cc = child_tetra_vertex(a, b, c, d, child_idx, 2u);
        let cd = child_tetra_vertex(a, b, c, d, child_idx, 3u);
        return aoa_face_vertex(ca, cb, cc, cd, face_idx, corner_idx);
    }

    let depth_2_idx = inner_idx - AOA_INNER_PANE_COUNT_DEPTH_1;
    if depth_2_idx < AOA_INNER_PANE_COUNT_DEPTH_2 {
        let child_idx = depth_2_idx / AOA_DEPTH_2_PANES_PER_CHILD;
        let grandchild_idx = (depth_2_idx / 4u) % 4u;
        let face_idx = depth_2_idx % 4u;
        let ca = child_tetra_vertex(a, b, c, d, child_idx, 0u);
        let cb = child_tetra_vertex(a, b, c, d, child_idx, 1u);
        let cc = child_tetra_vertex(a, b, c, d, child_idx, 2u);
        let cd = child_tetra_vertex(a, b, c, d, child_idx, 3u);
        let ga = child_tetra_vertex(ca, cb, cc, cd, grandchild_idx, 0u);
        let gb = child_tetra_vertex(ca, cb, cc, cd, grandchild_idx, 1u);
        let gc = child_tetra_vertex(ca, cb, cc, cd, grandchild_idx, 2u);
        let gd = child_tetra_vertex(ca, cb, cc, cd, grandchild_idx, 3u);
        return aoa_face_vertex(ga, gb, gc, gd, face_idx, corner_idx);
    }

    let depth_3_idx = depth_2_idx - AOA_INNER_PANE_COUNT_DEPTH_2;
    let child_idx = depth_3_idx / AOA_DEPTH_3_PANES_PER_CHILD;
    let grandchild_idx = (depth_3_idx / AOA_DEPTH_2_PANES_PER_CHILD) % 4u;
    let great_grandchild_idx = (depth_3_idx / 4u) % 4u;
    let face_idx = depth_3_idx % 4u;
    let ca = child_tetra_vertex(a, b, c, d, child_idx, 0u);
    let cb = child_tetra_vertex(a, b, c, d, child_idx, 1u);
    let cc = child_tetra_vertex(a, b, c, d, child_idx, 2u);
    let cd = child_tetra_vertex(a, b, c, d, child_idx, 3u);
    let ga = child_tetra_vertex(ca, cb, cc, cd, grandchild_idx, 0u);
    let gb = child_tetra_vertex(ca, cb, cc, cd, grandchild_idx, 1u);
    let gc = child_tetra_vertex(ca, cb, cc, cd, grandchild_idx, 2u);
    let gd = child_tetra_vertex(ca, cb, cc, cd, grandchild_idx, 3u);
    let ha = child_tetra_vertex(ga, gb, gc, gd, great_grandchild_idx, 0u);
    let hb = child_tetra_vertex(ga, gb, gc, gd, great_grandchild_idx, 1u);
    let hc = child_tetra_vertex(ga, gb, gc, gd, great_grandchild_idx, 2u);
    let hd = child_tetra_vertex(ga, gb, gc, gd, great_grandchild_idx, 3u);
    return aoa_face_vertex(ha, hb, hc, hd, face_idx, corner_idx);
}

fn aoa_pane_depth(pane_idx: u32) -> f32 {
    if pane_idx < AOA_OUTER_PANE_COUNT {
        return 0.0;
    }
    let inner_idx = pane_idx - AOA_OUTER_PANE_COUNT;
    if inner_idx < AOA_INNER_PANE_COUNT_DEPTH_1 {
        return 1.0;
    }
    if inner_idx < AOA_INNER_PANE_COUNT_DEPTH_1 + AOA_INNER_PANE_COUNT_DEPTH_2 {
        return 2.0;
    }
    return 3.0;
}

fn aoa_primary_child_index(pane_idx: u32) -> u32 {
    if pane_idx < AOA_OUTER_PANE_COUNT {
        return pane_idx;
    }
    let inner_idx = pane_idx - AOA_OUTER_PANE_COUNT;
    if inner_idx < AOA_INNER_PANE_COUNT_DEPTH_1 {
        return inner_idx / 4u;
    }
    let depth_2_idx = inner_idx - AOA_INNER_PANE_COUNT_DEPTH_1;
    if depth_2_idx < AOA_INNER_PANE_COUNT_DEPTH_2 {
        return depth_2_idx / AOA_DEPTH_2_PANES_PER_CHILD;
    }
    let depth_3_idx = depth_2_idx - AOA_INNER_PANE_COUNT_DEPTH_2;
    return depth_3_idx / AOA_DEPTH_3_PANES_PER_CHILD;
}

fn aoa_secondary_child_index(pane_idx: u32) -> u32 {
    if pane_idx < AOA_OUTER_PANE_COUNT + AOA_INNER_PANE_COUNT_DEPTH_1 {
        return pane_idx % 4u;
    }
    let inner_idx = pane_idx - AOA_OUTER_PANE_COUNT;
    let depth_2_idx = inner_idx - AOA_INNER_PANE_COUNT_DEPTH_1;
    if depth_2_idx < AOA_INNER_PANE_COUNT_DEPTH_2 {
        return (depth_2_idx / 4u) % 4u;
    }
    let depth_3_idx = depth_2_idx - AOA_INNER_PANE_COUNT_DEPTH_2;
    return (depth_3_idx / AOA_DEPTH_2_PANES_PER_CHILD) % 4u;
}

fn aoa_neon_palette(idx: u32) -> vec3<f32> {
    if idx == 1u {
        return vec3<f32>(0.28, 0.86, 1.0);
    }
    if idx == 2u {
        return vec3<f32>(0.78, 0.40, 1.0);
    }
    if idx == 3u {
        return vec3<f32>(1.0, 0.62, 0.18);
    }
    return vec3<f32>(1.0, 0.24, 0.74);
}

fn aoa_vertex(vi: u32) -> VertexOutput {
    // Front triangular face is parallel to the output/viewer plane; the fourth
    // tetrahedral point recedes into scene depth so all exterior and interior
    // panes remain legible as information surfaces.
    let a = vec3<f32>(-0.58, -0.44,  0.34);
    let b = vec3<f32>( 0.58, -0.44,  0.34);
    let c = vec3<f32>( 0.00,  0.60,  0.34);
    let d = vec3<f32>( 0.00, -0.095, -0.62);

    let pane_idx = (vi / 3u) % AOA_TOTAL_PANE_COUNT;
    let corner_idx = vi % 3u;
    let local = aoa_pane_vertex(a, b, c, d, pane_idx, corner_idx);
    let world_pos = scene.model * vec4<f32>(local, 1.0);

    var out: VertexOutput;
    out.position = scene.projection * scene.view * world_pos;
    out.uv = vec2<f32>(0.0, 0.0);
    out.barycentric = aoa_barycentric(corner_idx);
    out.pane_info = vec4<f32>(
        f32(pane_idx % 4u),
        aoa_pane_depth(pane_idx),
        f32(pane_idx),
        1.0,
    );
    out.local_pos = local;
    return out;
}

fn aoa_face_tint(face: f32, inner_pane: f32, local_pos: vec3<f32>, pane_idx: f32) -> vec3<f32> {
    // Four maximally distinct hues for structural differentiation.
    var tint = vec3<f32>(1.0, 0.12, 0.58);   // Face 0: hot pink (Composition)
    if face > 0.5 && face < 1.5 {
        tint = vec3<f32>(0.08, 0.92, 1.0);   // Face 1: electric cyan (Modulation)
    } else if face > 1.5 && face < 2.5 {
        tint = vec3<f32>(0.58, 0.18, 1.0);   // Face 2: deep violet (Surface)
    } else if face > 2.5 {
        tint = vec3<f32>(1.0, 0.72, 0.04);   // Face 3: vivid amber (Programme)
    }
    let pane_u = u32(pane_idx + 0.5);
    let primary = aoa_neon_palette(aoa_primary_child_index(pane_u));
    let secondary = aoa_neon_palette(aoa_secondary_child_index(pane_u));
    let lineage_mix = clamp(inner_pane * 0.18, 0.0, 0.42);
    tint = mix(mix(tint, primary, clamp(inner_pane * 0.28, 0.0, 0.52)), secondary, lineage_mix);
    let depth_signal = clamp((local_pos.z + 0.62) / 0.96, 0.0, 1.0);
    let height_signal = clamp((local_pos.y + 0.44) / 1.04, 0.0, 1.0);
    return tint * (0.82 + depth_signal * 0.22 + height_signal * 0.18) * (1.0 - inner_pane * 0.03);
}

fn aoa_fragment(in: VertexOutput) -> vec4<f32> {
    let bary = in.barycentric;
    let edge_dist = min(min(bary.x, bary.y), bary.z);
    let edge = aa_line_mask(edge_dist, 0.012, 0.045);
    let inner_pane = in.pane_info.y;
    let info_uv = pane_information_uv_from_barycentric(bary);
    let inside = triangle_inside_mask_from_barycentric(bary);

    if scene.payload_mode > 0.5 {
        let target_pane = u32(max(scene.payload_pane_ordinal, 0.0) + 0.5);
        let current_pane = u32(in.pane_info.z + 0.5);
        if current_pane != target_pane {
            return vec4<f32>(0.0, 0.0, 0.0, 0.0);
        }
        let sample_uv = pane_payload_sample_uv(info_uv);
        let payload = textureSample(quad_texture, quad_sampler, sample_uv);
        let tint = aoa_face_tint(in.pane_info.x, inner_pane, in.local_pos, in.pane_info.z);
        let info_grid = pane_information_grid(info_uv, inside);
        let luma = payload_luma(payload.rgb);

        if scene.payload_mode < 1.5 {
            let accent = edge * 0.42 + info_grid * 0.18 + smoothstep(0.42, 0.72, luma) * 0.10;
            let color = tint * accent + vec3<f32>(0.95, 0.32, 0.82) * edge * 0.16;
            let alpha = inside * scene.opacity * payload.a * clamp(accent, 0.0, 0.62);
            return vec4<f32>(color, alpha);
        }

        if scene.payload_mode < 2.5 {
            let glyph_payload = textureSample(
                quad_texture,
                quad_sampler,
                quantized_payload_sample_uv(sample_uv, 4.0),
            );
            let glyph = smoothstep(0.32, 0.68, payload_luma(glyph_payload.rgb));
            let color = mix(tint * (0.42 + info_grid * 0.22), glyph_payload.rgb, 0.32) + tint * edge * 0.16;
            let alpha = inside * scene.opacity * glyph_payload.a * (0.20 + glyph * 0.34 + edge * 0.12);
            return vec4<f32>(color, alpha);
        }

        if scene.payload_mode < 3.5 {
            let data_payload = textureSample(
                quad_texture,
                quad_sampler,
                quantized_payload_sample_uv(sample_uv, 8.0),
            );
            let color = mix(tint * (0.24 + info_grid * 0.18), data_payload.rgb, 0.52)
                + tint * (edge * 0.18 + info_grid * 0.08);
            let alpha = data_payload.a * inside * scene.opacity * (0.42 + edge * 0.14);
            return vec4<f32>(color, alpha);
        }

        let edge_emphasis = edge * 0.18 + info_grid * 0.10;
        let color = payload.rgb * (0.82 + edge * 0.12) + tint * edge_emphasis;
        let alpha = payload.a * inside * scene.opacity * 0.78;
        return vec4<f32>(color, alpha);
    }

    let info_grid = pane_information_grid(info_uv, 1.0);
    let local_lattice = aa_line_mask(abs(bary.x - bary.y), 0.018, 0.042)
        * aa_line_mask(bary.z, 0.018, 0.042);
    let tint = aoa_face_tint(in.pane_info.x, inner_pane, in.local_pos, in.pane_info.z);

    // Per-pane heatmap — live impingement/recruitment activity.
    let pane_ord = u32(in.pane_info.z + 0.5);
    let pane_hash = fract(sin(f32(pane_ord) * 127.1 + 311.7) * 43758.5453);
    var heat_pulse = 0.3 + pane_hash * 0.4;
    var heat_hue = 0.0;
    if pane_ord < arrayLength(&heatmap) {
        let entry = heatmap[pane_ord];
        heat_pulse = max(entry.heat, 0.05 + pane_hash * 0.15);
        heat_hue = entry.hue;
    }

    let fill = 0.08 + inner_pane * 0.03 + heat_pulse * 0.10;
    let line = edge * (0.88 - inner_pane * 0.08);
    let address = info_grid * (0.18 + inner_pane * 0.06);
    let lattice = local_lattice * (0.14 + inner_pane * 0.06);
    let pane_energy = fill + line + address + lattice;
    let aura = smoothstep(0.0, 0.7, line + address);
    // Modulate tint by heatmap hue + saturate for effect survival.
    let h6 = heat_hue * 6.0;
    let heat_rgb = vec3<f32>(
        clamp(abs(h6 - 3.0) - 1.0, 0.0, 1.0),
        clamp(2.0 - abs(h6 - 2.0), 0.0, 1.0),
        clamp(2.0 - abs(h6 - 4.0), 0.0, 1.0),
    );
    let heat_blend = clamp(heat_pulse * 0.6 + 0.08, 0.08, 0.50);
    let heat_tint = mix(tint, heat_rgb, heat_blend);
    let sat_tint = heat_tint * (1.3 + heat_pulse * 0.8);
    let tint_luma = dot(sat_tint, vec3<f32>(0.299, 0.587, 0.114));
    let hyper_sat = mix(vec3<f32>(tint_luma), sat_tint, 1.8);
    let color = hyper_sat * pane_energy + tint * aura * 0.22;
    let alpha = clamp(fill * 0.78 + line * 0.68 + address * 0.46 + lattice * 0.38, 0.0, 0.90)
        * scene.opacity;
    return vec4<f32>(color, alpha);
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    if scene.shader_kind > 0.5 {
        return aoa_fragment(in);
    }

    let tex_color = textureSample(quad_texture, quad_sampler, in.uv);
    let treated = apply_entity_local_spatial_effect(in.uv, tex_color);
    // Emissive base: entities always push and influence effects.
    let luma = dot(treated.rgb, vec3<f32>(0.299, 0.587, 0.114));
    let saturated = mix(vec3<f32>(luma), treated.rgb, 2.0) * 1.6;
    return vec4<f32>(saturated, treated.a * scene.opacity);
}
