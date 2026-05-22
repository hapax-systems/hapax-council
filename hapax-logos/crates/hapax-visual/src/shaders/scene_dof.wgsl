// Depth-of-field post-process — separable Gaussian blur.
// Blur increases with distance from screen center (vignette DoF).

struct DofUniforms {
    focus_depth: f32,
    blur_scale: f32,
    direction_x: f32,
    direction_y: f32,
    texel_size_x: f32,
    texel_size_y: f32,
    _pad0: f32,
    _pad1: f32,
};

@group(0) @binding(0) var color_tex: texture_2d<f32>;
@group(0) @binding(1) var tex_sampler: sampler;
@group(0) @binding(2) var<uniform> dof: DofUniforms;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VertexOutput {
    var pos = array<vec2<f32>, 3>(
        vec2(-1.0, -1.0),
        vec2(3.0, -1.0),
        vec2(-1.0, 3.0),
    );
    var out: VertexOutput;
    out.position = vec4<f32>(pos[vi], 0.0, 1.0);
    out.uv = pos[vi] * vec2(0.5, -0.5) + vec2(0.5, 0.5);
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let center_color = textureSample(color_tex, tex_sampler, in.uv);

    let from_center = length(in.uv - vec2(0.5, 0.5)) * 2.0;
    let blur_radius = clamp(from_center * from_center * dof.blur_scale, 0.0, 10.0);

    if blur_radius < 0.4 {
        return center_color;
    }

    let direction = vec2<f32>(dof.direction_x, dof.direction_y);
    let pixel_step = direction * vec2<f32>(dof.texel_size_x, dof.texel_size_y);

    let weights = array<f32, 5>(0.227027, 0.194596, 0.121622, 0.054054, 0.016216);

    var result = center_color * weights[0];
    for (var i = 1; i < 5; i = i + 1) {
        let offset = pixel_step * f32(i) * blur_radius;
        result += textureSample(color_tex, tex_sampler, in.uv + offset) * weights[i];
        result += textureSample(color_tex, tex_sampler, in.uv - offset) * weights[i];
    }

    return result;
}
