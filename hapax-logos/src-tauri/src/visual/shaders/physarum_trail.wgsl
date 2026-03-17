// Physarum trail map processing: 3x3 blur + decay
// Reads from deposit_map (with new deposits), writes blurred+decayed result to trail_out

struct Params {
    width: u32,
    height: u32,
    decay_rate: f32,  // 0.0-1.0, how much trail fades per step (default: 0.02)
    _pad: u32,
}

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var deposit_map: texture_2d<f32>;
@group(0) @binding(2) var trail_out: texture_storage_2d<r32float, write>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let pos = vec2<i32>(gid.xy);
    if gid.x >= params.width || gid.y >= params.height {
        return;
    }

    // 3x3 box blur
    var sum = 0.0;
    for (var dy = -1; dy <= 1; dy++) {
        for (var dx = -1; dx <= 1; dx++) {
            let np = vec2<i32>(
                clamp(pos.x + dx, 0, i32(params.width) - 1),
                clamp(pos.y + dy, 0, i32(params.height) - 1),
            );
            sum += textureLoad(deposit_map, np, 0).x;
        }
    }
    let blurred = sum / 9.0;

    // Apply decay
    let decayed = max(blurred - params.decay_rate, 0.0);

    textureStore(trail_out, pos, vec4<f32>(decayed, 0.0, 0.0, 1.0));
}
