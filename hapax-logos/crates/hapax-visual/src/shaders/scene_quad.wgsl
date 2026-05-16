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

fn min_sierpinski_distance(p: vec2<f32>) -> f32 {
    let a = vec2<f32>(0.50, 0.94);
    let b = vec2<f32>(0.06, 0.08);
    let c = vec2<f32>(0.94, 0.08);
    let ab = (a + b) * 0.5;
    let ac = (a + c) * 0.5;
    let bc = (b + c) * 0.5;

    var d = 1.0;
    d = min(d, segment_distance(p, a, b));
    d = min(d, segment_distance(p, a, c));
    d = min(d, segment_distance(p, b, c));
    d = min(d, segment_distance(p, ab, ac));
    d = min(d, segment_distance(p, ab, bc));
    d = min(d, segment_distance(p, ac, bc));

    let tab = (a + ab) * 0.5;
    let tac = (a + ac) * 0.5;
    let tbase = (ab + ac) * 0.5;
    d = min(d, segment_distance(p, tab, tac));
    d = min(d, segment_distance(p, tab, tbase));
    d = min(d, segment_distance(p, tac, tbase));

    let lab = (b + ab) * 0.5;
    let lbc = (b + bc) * 0.5;
    let lmid = (ab + bc) * 0.5;
    d = min(d, segment_distance(p, lab, lbc));
    d = min(d, segment_distance(p, lab, lmid));
    d = min(d, segment_distance(p, lbc, lmid));

    let rac = (c + ac) * 0.5;
    let rbc = (c + bc) * 0.5;
    let rmid = (ac + bc) * 0.5;
    d = min(d, segment_distance(p, rac, rbc));
    d = min(d, segment_distance(p, rac, rmid));
    d = min(d, segment_distance(p, rbc, rmid));

    return d;
}

fn sierpinski_color(uv: vec2<f32>) -> vec3<f32> {
    let cyan = vec3<f32>(0.26, 0.82, 1.0);
    let magenta = vec3<f32>(1.0, 0.24, 0.78);
    let violet = vec3<f32>(0.68, 0.38, 1.0);
    let sweep = clamp(uv.x * 0.72 + uv.y * 0.28, 0.0, 1.0);
    return mix(mix(magenta, violet, smoothstep(0.0, 0.55, sweep)), cyan, smoothstep(0.45, 1.0, sweep));
}

fn authored_sierpinski(uv_in: vec2<f32>) -> vec4<f32> {
    let p = vec2<f32>(uv_in.x, 1.0 - uv_in.y);
    let d = min_sierpinski_distance(p);
    let core = smoothstep(0.018, 0.003, d);
    let glow = smoothstep(0.070, 0.006, d);
    let alpha = clamp(core * 0.92 + glow * 0.34, 0.0, 0.96) * scene.opacity;
    let color = sierpinski_color(p) * (0.42 + glow * 0.66 + core * 0.44);
    return vec4<f32>(color, alpha);
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    if scene.shader_kind > 0.5 {
        return authored_sierpinski(in.uv);
    }

    let tex_color = textureSample(quad_texture, quad_sampler, in.uv);
    return vec4<f32>(tex_color.rgb, tex_color.a * scene.opacity);
}
