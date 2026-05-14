// Scene quad vertex+fragment shader for 3D compositor Phase 0.
//
// Renders textured quads in 3D space using model/view/projection matrices.
// The fragment shader samples the bound texture and applies per-quad opacity.

struct SceneUniforms {
    model: mat4x4<f32>,
    view: mat4x4<f32>,
    projection: mat4x4<f32>,
    opacity: f32,
    _pad0: f32,
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

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let tex_color = textureSample(quad_texture, quad_sampler, in.uv);
    return vec4<f32>(tex_color.rgb, tex_color.a * scene.opacity);
}
