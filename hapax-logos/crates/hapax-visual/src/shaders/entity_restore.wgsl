// Post-Reverie entity restoration pass.
// Composites original entity colors back onto the Reverie-processed output
// so AoA pane heatmap colors and entity identity survive the effect chain.

@group(0) @binding(0)
var reverie_output: texture_2d<f32>;
@group(0) @binding(1)
var scene_source: texture_2d<f32>;
@group(0) @binding(2)
var tex_sampler: sampler;

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
    let reverie = textureSample(reverie_output, tex_sampler, in.uv);
    let scene = textureSample(scene_source, tex_sampler, in.uv);

    // Entity presence: where the scene has bright, saturated content
    let scene_luma = dot(scene.rgb, vec3<f32>(0.299, 0.587, 0.114));
    let scene_chroma = length(scene.rgb - vec3<f32>(scene_luma));
    let entity_strength = smoothstep(0.08, 0.35, scene_luma) * smoothstep(0.02, 0.12, scene_chroma);

    // Restore entity hue and saturation from the scene, keep Reverie luminance structure
    let rev_luma = dot(reverie.rgb, vec3<f32>(0.299, 0.587, 0.114));
    let restored_color = scene.rgb * (rev_luma / max(scene_luma, 0.01));
    let blend = mix(reverie.rgb, restored_color, entity_strength * 0.55);

    return vec4<f32>(blend, max(reverie.a, scene.a));
}
