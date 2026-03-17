// Gray-Scott reaction-diffusion compute shader
// Ping-pong between two textures: read from src, write to dst

struct Params {
    f: f32,         // feed rate
    k: f32,         // kill rate
    du: f32,        // diffusion rate U (default 0.2097)
    dv: f32,        // diffusion rate V (default 0.105)
    dt: f32,        // timestep (default 1.0)
    width: u32,
    height: u32,
    _pad: u32,
}

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var src: texture_2d<f32>;
@group(0) @binding(2) var dst: texture_storage_2d<rgba16float, write>;

// 5-point Laplacian stencil
fn laplacian(pos: vec2<i32>) -> vec2<f32> {
    let center = textureLoad(src, pos, 0).xy;
    let left   = textureLoad(src, pos + vec2<i32>(-1, 0), 0).xy;
    let right  = textureLoad(src, pos + vec2<i32>( 1, 0), 0).xy;
    let up     = textureLoad(src, pos + vec2<i32>( 0,-1), 0).xy;
    let down   = textureLoad(src, pos + vec2<i32>( 0, 1), 0).xy;
    return left + right + up + down - 4.0 * center;
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let pos = vec2<i32>(gid.xy);
    if gid.x >= params.width || gid.y >= params.height {
        return;
    }

    let uv = textureLoad(src, pos, 0).xy;
    let u = uv.x;
    let v = uv.y;
    let lap = laplacian(pos);

    let reaction = u * v * v;
    let new_u = u + params.dt * (params.du * lap.x - reaction + params.f * (1.0 - u));
    let new_v = v + params.dt * (params.dv * lap.y + reaction - (params.f + params.k) * v);

    textureStore(dst, pos, vec4<f32>(clamp(new_u, 0.0, 1.0), clamp(new_v, 0.0, 1.0), 0.0, 1.0));
}
