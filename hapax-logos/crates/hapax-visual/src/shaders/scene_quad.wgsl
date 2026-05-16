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
};

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VertexOutput {
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

fn aoa_project_pane_preserving(v: vec3<f32>) -> vec2<f32> {
    // A stable isometric-like projection, not a camera-perspective squeeze.
    // The rear base vertex remains displaced from the front face so every
    // tetrahedral face can read as a usable triangular information pane.
    return vec2<f32>(
        0.5 + v.x * 0.50 + v.z * 0.24,
        0.25 + v.y * 0.72 + v.z * 0.27,
    );
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

fn central_aperture_distance(p: vec2<f32>, a: vec2<f32>, b: vec2<f32>, c: vec2<f32>) -> f32 {
    let ab = (a + b) * 0.5;
    let bc = (b + c) * 0.5;
    let ca = (c + a) * 0.5;
    return triangle_edge_distance(p, ab, bc, ca);
}

fn aoa_pane_lattice_distance(p: vec2<f32>, a: vec2<f32>, b: vec2<f32>, c: vec2<f32>) -> f32 {
    let ab = (a + b) * 0.5;
    let bc = (b + c) * 0.5;
    let ca = (c + a) * 0.5;

    var dist = triangle_edge_distance(p, a, b, c);
    dist = min(dist, central_aperture_distance(p, a, b, c));
    dist = min(dist, central_aperture_distance(p, a, ab, ca));
    dist = min(dist, central_aperture_distance(p, ab, b, bc));
    dist = min(dist, central_aperture_distance(p, ca, bc, c));
    return dist;
}

fn line_mask(dist: f32, width: f32, feather: f32) -> f32 {
    return 1.0 - smoothstep(width, width + feather, dist);
}

fn compose_pane(acc: vec4<f32>, pane: vec4<f32>) -> vec4<f32> {
    let alpha = clamp(acc.a + pane.a * (1.0 - acc.a * 0.22), 0.0, 0.98);
    let rgb = min(acc.rgb + pane.rgb * pane.a, vec3<f32>(3.0, 3.0, 3.0));
    return vec4<f32>(rgb, alpha);
}

fn pane_sample(
    p: vec2<f32>,
    a: vec2<f32>,
    b: vec2<f32>,
    c: vec2<f32>,
    tint: vec3<f32>,
    fill_strength: f32,
    line_strength: f32,
    inner_pane: f32,
) -> vec4<f32> {
    let bary = triangle_barycentric(p, a, b, c);
    let inside = triangle_inside_mask_from_barycentric(bary);
    let info_uv = pane_information_uv_from_barycentric(bary);
    let info_grid = pane_information_grid(info_uv, inside);
    let edge_dist = triangle_edge_distance(p, a, b, c);
    let edge = line_mask(edge_dist, 0.0048, 0.010);
    var lattice = 0.0;
    if inner_pane < 0.5 {
        let lattice_dist = aoa_pane_lattice_distance(p, a, b, c);
        lattice = line_mask(lattice_dist, 0.0027, 0.007);
    } else {
        let aperture_dist = central_aperture_distance(p, a, b, c);
        lattice = line_mask(aperture_dist, 0.0024, 0.006) * 0.36;
    }
    let fill = inside * fill_strength;
    let address_energy = info_grid * (0.070 + inner_pane * 0.040);
    let pane_energy = fill * 0.42 + edge * line_strength + lattice * (0.50 + inner_pane * 0.18) + address_energy;
    let alpha = clamp(fill + edge * 0.70 + lattice * (0.42 + inner_pane * 0.12) + address_energy * 0.45, 0.0, 0.92);
    return vec4<f32>(tint * pane_energy, alpha);
}

fn tetra_pane_sample(
    p: vec2<f32>,
    a: vec3<f32>,
    b: vec3<f32>,
    c: vec3<f32>,
    d: vec3<f32>,
    opacity_scale: f32,
    inner_pane: f32,
) -> vec4<f32> {
    let pa = aoa_project_pane_preserving(a);
    let pb = aoa_project_pane_preserving(b);
    let pc = aoa_project_pane_preserving(c);
    let pd = aoa_project_pane_preserving(d);

    let fill = 0.060 * opacity_scale;
    let line = 0.88 * opacity_scale;
    var acc = vec4<f32>(0.0, 0.0, 0.0, 0.0);
    acc = compose_pane(acc, pane_sample(p, pa, pb, pd, vec3<f32>(1.0, 0.28, 0.74), fill, line, inner_pane));
    acc = compose_pane(acc, pane_sample(p, pb, pc, pd, vec3<f32>(0.30, 0.84, 1.0), fill, line, inner_pane));
    acc = compose_pane(acc, pane_sample(p, pc, pa, pd, vec3<f32>(0.74, 0.42, 1.0), fill, line, inner_pane));
    acc = compose_pane(acc, pane_sample(p, pa, pc, pb, vec3<f32>(1.0, 0.58, 0.20), fill * 0.72, line * 0.72, inner_pane));
    return acc;
}

fn authored_aoa(uv_in: vec2<f32>) -> vec4<f32> {
    let p = vec2<f32>(uv_in.x, 1.0 - uv_in.y);
    let a = vec3<f32>(-0.58, 0.00, -0.34);
    let b = vec3<f32>( 0.58, 0.00, -0.34);
    let c = vec3<f32>( 0.00, 0.00,  0.58);
    let d = vec3<f32>( 0.00, 0.92,  0.00);

    var acc = tetra_pane_sample(p, a, b, c, d, 1.0, 0.0);
    for (var child: u32 = 0u; child < 4u; child = child + 1u) {
        let ca = child_tetra_vertex(a, b, c, d, child, 0u);
        let cb = child_tetra_vertex(a, b, c, d, child, 1u);
        let cc = child_tetra_vertex(a, b, c, d, child, 2u);
        let cd = child_tetra_vertex(a, b, c, d, child, 3u);
        acc = compose_pane(acc, tetra_pane_sample(p, ca, cb, cc, cd, 0.54, 1.0));
    }

    let aura = smoothstep(0.01, 0.68, acc.a);
    let color = acc.rgb + vec3<f32>(0.72, 0.38, 1.0) * aura * 0.22;
    let alpha = clamp(acc.a + aura * 0.18, 0.0, 0.96) * scene.opacity;
    return vec4<f32>(color, alpha);
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    if scene.shader_kind > 0.5 {
        return authored_aoa(in.uv);
    }

    let tex_color = textureSample(quad_texture, quad_sampler, in.uv);
    return vec4<f32>(tex_color.rgb, tex_color.a * scene.opacity);
}
