// Simple fullscreen texture blit — copies source to target with no processing.

@group(0) @binding(0)
var src_texture: texture_2d<f32>;
@group(0) @binding(1)
var src_sampler: sampler;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VertexOutput {
    var pos = array<vec2<f32>, 6>(
        vec2(-1.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
        vec2(-1.0, -1.0), vec2(1.0, 1.0), vec2(-1.0, 1.0),
    );
    var out: VertexOutput;
    out.position = vec4<f32>(pos[vi], 0.0, 1.0);
    out.uv = pos[vi] * vec2<f32>(0.5, -0.5) + 0.5;
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    return textureSample(src_texture, src_sampler, in.uv);
}
