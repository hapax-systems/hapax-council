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
    _pad1: f32,
    _pad2: f32,
};

@group(0) @binding(0)
var<uniform> scene: SceneUniforms;

@group(1) @binding(0)
var quad_texture: texture_2d<f32>;
@group(1) @binding(1)
var quad_sampler: sampler;

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
const AOA_TOTAL_PANE_COUNT: u32 = AOA_OUTER_PANE_COUNT + AOA_INNER_PANE_COUNT_DEPTH_1;

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

fn pane_information_grid(local_uv: vec2<f32>, inside: f32) -> f32 {
    let grid = fract(local_uv * vec2<f32>(7.0, 7.0));
    let edge_dist = min(min(grid.x, 1.0 - grid.x), min(grid.y, 1.0 - grid.y));
    return inside * (1.0 - smoothstep(0.010, 0.026, edge_dist));
}

fn line_mask(dist: f32, width: f32, feather: f32) -> f32 {
    return 1.0 - smoothstep(width, width + feather, dist);
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
    let child_idx = inner_idx / 4u;
    let face_idx = inner_idx % 4u;
    let ca = child_tetra_vertex(a, b, c, d, child_idx, 0u);
    let cb = child_tetra_vertex(a, b, c, d, child_idx, 1u);
    let cc = child_tetra_vertex(a, b, c, d, child_idx, 2u);
    let cd = child_tetra_vertex(a, b, c, d, child_idx, 3u);
    return aoa_face_vertex(ca, cb, cc, cd, face_idx, corner_idx);
}

fn aoa_vertex(vi: u32) -> VertexOutput {
    let a = vec3<f32>(-0.58, 0.00, -0.34);
    let b = vec3<f32>( 0.58, 0.00, -0.34);
    let c = vec3<f32>( 0.00, 0.00,  0.58);
    let d = vec3<f32>( 0.00, 0.92,  0.00);

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
        select(0.0, 1.0, pane_idx >= AOA_OUTER_PANE_COUNT),
        f32(pane_idx),
        1.0,
    );
    out.local_pos = local;
    return out;
}

fn aoa_face_tint(face: f32, inner_pane: f32, local_pos: vec3<f32>) -> vec3<f32> {
    var tint = vec3<f32>(1.0, 0.28, 0.74);
    if face > 0.5 && face < 1.5 {
        tint = vec3<f32>(0.30, 0.84, 1.0);
    } else if face > 1.5 && face < 2.5 {
        tint = vec3<f32>(0.74, 0.42, 1.0);
    } else if face > 2.5 {
        tint = vec3<f32>(1.0, 0.58, 0.20);
    }
    let depth_signal = clamp((local_pos.z + 0.58) / 1.16, 0.0, 1.0);
    let height_signal = clamp((local_pos.y + 0.05) / 0.92, 0.0, 1.0);
    return tint * (0.72 + depth_signal * 0.20 + height_signal * 0.18) * (1.0 - inner_pane * 0.12);
}

fn aoa_fragment(in: VertexOutput) -> vec4<f32> {
    let bary = in.barycentric;
    let edge_dist = min(min(bary.x, bary.y), bary.z);
    let edge = 1.0 - smoothstep(0.012, 0.045, edge_dist);
    let inner_pane = in.pane_info.y;
    let info_uv = pane_information_uv_from_barycentric(bary);
    let info_grid = pane_information_grid(info_uv, 1.0);
    let local_lattice = (1.0 - smoothstep(0.018, 0.042, abs(bary.x - bary.y)))
        * (1.0 - smoothstep(0.018, 0.042, bary.z));
    let tint = aoa_face_tint(in.pane_info.x, inner_pane, in.local_pos);
    let fill = 0.055 + inner_pane * 0.020;
    let line = edge * (0.74 - inner_pane * 0.16);
    let address = info_grid * (0.12 + inner_pane * 0.05);
    let lattice = local_lattice * (0.11 + inner_pane * 0.07);
    let pane_energy = fill + line + address + lattice;
    let aura = smoothstep(0.0, 0.9, line + address);
    let color = tint * pane_energy + vec3<f32>(0.72, 0.38, 1.0) * aura * 0.12;
    let alpha = clamp(fill * 0.70 + line * 0.62 + address * 0.42 + lattice * 0.36, 0.0, 0.88)
        * scene.opacity;
    return vec4<f32>(color, alpha);
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    if scene.shader_kind > 0.5 {
        return aoa_fragment(in);
    }

    let tex_color = textureSample(quad_texture, quad_sampler, in.uv);
    return vec4<f32>(tex_color.rgb, tex_color.a * scene.opacity);
}
