// 2D damped wave equation compute shader
// Uses 3-texture rotation: prev (t-1), curr (t), next (t+1)
// Wave equation: next = 2*curr - prev + c²*(Laplacian(curr)) - damping*(curr - prev)

struct Params {
    c_sq: f32,      // propagation speed squared (default: 16.0 for ~4 px/frame)
    damping: f32,   // damping factor (0.1-0.2, default: 0.15)
    width: u32,
    height: u32,
}

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var prev_tex: texture_2d<f32>;
@group(0) @binding(2) var curr_tex: texture_2d<f32>;
@group(0) @binding(3) var next_tex: texture_storage_2d<r32float, write>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let pos = vec2<i32>(gid.xy);
    if gid.x >= params.width || gid.y >= params.height {
        return;
    }

    let prev = textureLoad(prev_tex, pos, 0).x;
    let curr = textureLoad(curr_tex, pos, 0).x;

    // 5-point Laplacian
    let left  = textureLoad(curr_tex, pos + vec2<i32>(-1, 0), 0).x;
    let right = textureLoad(curr_tex, pos + vec2<i32>( 1, 0), 0).x;
    let up    = textureLoad(curr_tex, pos + vec2<i32>( 0,-1), 0).x;
    let down  = textureLoad(curr_tex, pos + vec2<i32>( 0, 1), 0).x;
    let laplacian = left + right + up + down - 4.0 * curr;

    let next = 2.0 * curr - prev + params.c_sq * laplacian - params.damping * (curr - prev);

    textureStore(next_tex, pos, vec4<f32>(clamp(next, -1.0, 1.0), 0.0, 0.0, 1.0));
}
