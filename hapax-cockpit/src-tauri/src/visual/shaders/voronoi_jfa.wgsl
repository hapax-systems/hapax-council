// Jump Flooding Algorithm (JFA) for Voronoi diagram
// Each texel stores the position of its nearest seed (as rg = x,y in pixels)
// Pass 0: seed initialization (seeds write their own position)
// Pass 1-N: JFA steps with decreasing step_size

struct Params {
    step_size: i32,
    width: u32,
    height: u32,
    seed_count: u32,
}

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var src: texture_2d<f32>;
@group(0) @binding(2) var dst: texture_storage_2d<rg32float, write>;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let pos = vec2<i32>(gid.xy);
    if gid.x >= params.width || gid.y >= params.height {
        return;
    }

    var best_seed = textureLoad(src, pos, 0).xy;
    var best_dist = distance_sq(vec2<f32>(pos), best_seed);

    // If no seed assigned yet (sentinel = -1,-1), set distance very high
    if best_seed.x < 0.0 {
        best_dist = 1e18;
    }

    let step = params.step_size;

    // 9-neighbor JFA kernel
    for (var dy = -1; dy <= 1; dy++) {
        for (var dx = -1; dx <= 1; dx++) {
            if dx == 0 && dy == 0 { continue; }
            let neighbor = pos + vec2<i32>(dx * step, dy * step);
            if neighbor.x < 0 || neighbor.y < 0 ||
               neighbor.x >= i32(params.width) || neighbor.y >= i32(params.height) {
                continue;
            }
            let n_seed = textureLoad(src, neighbor, 0).xy;
            if n_seed.x < 0.0 { continue; } // no seed
            let d = distance_sq(vec2<f32>(pos), n_seed);
            if d < best_dist {
                best_dist = d;
                best_seed = n_seed;
            }
        }
    }

    textureStore(dst, pos, vec4<f32>(best_seed, 0.0, 1.0));
}

fn distance_sq(a: vec2<f32>, b: vec2<f32>) -> f32 {
    let d = a - b;
    return d.x * d.x + d.y * d.y;
}
