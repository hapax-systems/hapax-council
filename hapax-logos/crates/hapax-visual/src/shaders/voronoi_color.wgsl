// Voronoi colorization pass
// Reads JFA result (nearest seed positions) and produces colored cells with edge darkening

struct Params {
    width: u32,
    height: u32,
    seed_count: u32,
    edge_width: f32,
}

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var jfa_result: texture_2d<f32>;
@group(0) @binding(2) var dst: texture_storage_2d<rgba8unorm, write>;

// Simple hash for seed → color
fn seed_color(seed: vec2<f32>) -> vec3<f32> {
    let h = fract(sin(dot(seed * 0.001, vec2<f32>(127.1, 311.7))) * 43758.5453);
    let h2 = fract(sin(dot(seed * 0.001, vec2<f32>(269.5, 183.3))) * 43758.5453);
    // Muted, dark colors (matching ambient aesthetic)
    return vec3<f32>(
        0.05 + h * 0.15,
        0.05 + h2 * 0.12,
        0.08 + fract(h + h2) * 0.15,
    );
}

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let pos = vec2<i32>(gid.xy);
    if gid.x >= params.width || gid.y >= params.height {
        return;
    }

    let my_seed = textureLoad(jfa_result, pos, 0).xy;
    let my_dist = distance(vec2<f32>(pos), my_seed);

    // Find distance to nearest different seed (for edge detection)
    var min_other_dist = 1e18f;
    for (var dy = -2; dy <= 2; dy++) {
        for (var dx = -2; dx <= 2; dx++) {
            let np = pos + vec2<i32>(dx, dy);
            if np.x < 0 || np.y < 0 || np.x >= i32(params.width) || np.y >= i32(params.height) {
                continue;
            }
            let n_seed = textureLoad(jfa_result, np, 0).xy;
            if distance(n_seed, my_seed) > 1.0 {
                let d = distance(vec2<f32>(pos), n_seed);
                min_other_dist = min(min_other_dist, d);
            }
        }
    }

    // Edge factor: darken near cell boundaries
    let edge_proximity = 1.0 - smoothstep(0.0, params.edge_width, min_other_dist - my_dist);

    let cell_color = seed_color(my_seed);
    let edge_darken = mix(1.0, 0.3, edge_proximity);

    textureStore(dst, pos, vec4<f32>(cell_color * edge_darken, 1.0));
}
