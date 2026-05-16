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

fn aoa_orient(v: vec3<f32>) -> vec3<f32> {
    let cy = cos(0.47);
    let sy = sin(0.47);
    let y_rot = vec3<f32>(
        v.x * cy + v.z * sy,
        v.y,
        -v.x * sy + v.z * cy,
    );
    let cx = cos(-0.18);
    let sx = sin(-0.18);
    return vec3<f32>(
        y_rot.x,
        y_rot.y * cx - y_rot.z * sx,
        y_rot.y * sx + y_rot.z * cx,
    );
}

fn aoa_project(v: vec3<f32>) -> vec2<f32> {
    let oriented = aoa_orient(v);
    let perspective = 1.48 / (1.48 + oriented.z * 0.54);
    return vec2<f32>(
        0.5 + oriented.x * 0.68 * perspective,
        0.47 + oriented.y * 0.76 * perspective,
    );
}

fn tetra_edge_distance(
    p: vec2<f32>,
    a: vec3<f32>,
    b: vec3<f32>,
    c: vec3<f32>,
    d: vec3<f32>,
) -> f32 {
    let pa = aoa_project(a);
    let pb = aoa_project(b);
    let pc = aoa_project(c);
    let pd = aoa_project(d);

    var dist = 1.0;
    dist = min(dist, segment_distance(p, pa, pb));
    dist = min(dist, segment_distance(p, pa, pc));
    dist = min(dist, segment_distance(p, pa, pd));
    dist = min(dist, segment_distance(p, pb, pc));
    dist = min(dist, segment_distance(p, pb, pd));
    dist = min(dist, segment_distance(p, pc, pd));
    return dist;
}

fn aoa_tetrix_distances(p: vec2<f32>) -> vec3<f32> {
    let a = vec3<f32>(-0.58, -0.42, -0.38);
    let b = vec3<f32>( 0.58, -0.42, -0.38);
    let c = vec3<f32>( 0.00, -0.42,  0.66);
    let d = vec3<f32>( 0.00,  0.66,  0.02);

    let root = tetra_edge_distance(p, a, b, c, d);
    var level1 = 1.0;
    var level2 = 1.0;

    for (var child: u32 = 0u; child < 4u; child = child + 1u) {
        let ca = child_tetra_vertex(a, b, c, d, child, 0u);
        let cb = child_tetra_vertex(a, b, c, d, child, 1u);
        let cc = child_tetra_vertex(a, b, c, d, child, 2u);
        let cd = child_tetra_vertex(a, b, c, d, child, 3u);
        level1 = min(level1, tetra_edge_distance(p, ca, cb, cc, cd));

        for (var grandchild: u32 = 0u; grandchild < 4u; grandchild = grandchild + 1u) {
            let ga = child_tetra_vertex(ca, cb, cc, cd, grandchild, 0u);
            let gb = child_tetra_vertex(ca, cb, cc, cd, grandchild, 1u);
            let gc = child_tetra_vertex(ca, cb, cc, cd, grandchild, 2u);
            let gd = child_tetra_vertex(ca, cb, cc, cd, grandchild, 3u);
            level2 = min(level2, tetra_edge_distance(p, ga, gb, gc, gd));
        }
    }

    return vec3<f32>(root, level1, level2);
}

fn aoa_color(uv: vec2<f32>) -> vec3<f32> {
    let cyan = vec3<f32>(0.26, 0.82, 1.0);
    let magenta = vec3<f32>(1.0, 0.24, 0.78);
    let violet = vec3<f32>(0.68, 0.38, 1.0);
    let sweep = clamp(uv.x * 0.72 + uv.y * 0.28, 0.0, 1.0);
    return mix(mix(magenta, violet, smoothstep(0.0, 0.55, sweep)), cyan, smoothstep(0.45, 1.0, sweep));
}

fn authored_aoa(uv_in: vec2<f32>) -> vec4<f32> {
    let p = vec2<f32>(uv_in.x, 1.0 - uv_in.y);
    let distances = aoa_tetrix_distances(p);
    let root_core = smoothstep(0.014, 0.003, distances.x);
    let inner_core = smoothstep(0.011, 0.002, distances.y);
    let deep_core = smoothstep(0.008, 0.0015, distances.z);
    let glow = smoothstep(0.075, 0.004, min(distances.x, min(distances.y, distances.z)));
    let alpha = clamp(root_core * 0.58 + inner_core * 0.62 + deep_core * 0.76 + glow * 0.30, 0.0, 0.96) * scene.opacity;
    let color = aoa_color(p) * (0.36 + glow * 0.58 + root_core * 0.30 + inner_core * 0.42 + deep_core * 0.54);
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
