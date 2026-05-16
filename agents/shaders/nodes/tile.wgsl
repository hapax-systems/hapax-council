struct Params {
    u_count_x: f32,
    u_count_y: f32,
    u_mirror: f32,
    u_gap: f32,
}

struct FragmentOutput {
    @location(0) fragColor: vec4<f32>,
}

var<private> fragColor: vec4<f32>;
var<private> v_texcoord_1: vec2<f32>;
@group(1) @binding(0)
var tex: texture_2d<f32>;
@group(1) @binding(1)
var tex_sampler: sampler;
@group(2) @binding(0)
var<uniform> global: Params;

fn main_1() {
    let source = textureSample(tex, tex_sampler, v_texcoord_1);
    let counts = vec2<f32>(clamp(global.u_count_x, 1.0, 5.5), clamp(global.u_count_y, 1.0, 5.5));
    let uv = v_texcoord_1 * counts;
    let cell = floor(uv);
    var f = fract(uv);
    if global.u_mirror > 0.5 {
        if (cell.x - (floor(cell.x / 2.0) * 2.0)) > 0.5 {
            f.x = 1.0 - f.x;
        }
        if (cell.y - (floor(cell.y / 2.0) * 2.0)) > 0.5 {
            f.y = 1.0 - f.y;
        }
    }

    let gap = clamp(global.u_gap, 0.0, 0.050);
    var gap_gate = 1.0;
    if gap > 0.0 {
        let half_gap = gap * 0.5;
        let in_gap = f.x < half_gap || f.x > (1.0 - half_gap) || f.y < half_gap || f.y > (1.0 - half_gap);
        if in_gap {
            gap_gate = 0.74;
        }
        f = clamp((f - vec2<f32>(half_gap)) / vec2<f32>(max(1.0 - gap, 0.001)), vec2(0.0), vec2(1.0));
    }

    let tiled = textureSample(tex, tex_sampler, f);
    let source_luma = dot(source.xyz, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence = smoothstep(0.025, 0.14, source_luma);
    let geometry_presence = max(surface_presence, 0.26);
    let strength = geometry_presence * clamp((counts.x + counts.y - 2.0) * 0.10, 0.0, 0.48);
    let tiled_bound = mix(source.xyz * gap_gate, tiled.xyz, vec3<f32>(0.72));
    fragColor = vec4<f32>(mix(source.xyz, tiled_bound, vec3<f32>(strength)), source.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
