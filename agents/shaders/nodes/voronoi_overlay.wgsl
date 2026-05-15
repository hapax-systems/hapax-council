struct Params {
    u_cell_count: f32,
    u_edge_width: f32,
    u_animation_speed: f32,
    u_jitter: f32,
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

fn hash2(p: vec2<f32>) -> vec2<f32> {
    return fract(sin(vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)))) * 43758.5453);
}

fn main_1() {
    let uv = v_texcoord_1;
    let src = textureSample(tex, tex_sampler, uv);
    let edge_width = max(global.u_edge_width, 0.0);
    if src.a < 0.01 || edge_width <= 0.0001 {
        fragColor = src;
        return;
    }

    let sc = max(global.u_cell_count, 1.0);
    let p = uv * sc;
    let ip = floor(p);
    let fp = fract(p);
    let jitter = clamp(global.u_jitter, 0.0, 1.0);
    let speed = max(global.u_animation_speed, 0.0);

    var md = 8.0;
    var md2 = 8.0;
    for (var j = -1; j <= 1; j++) {
        for (var i = -1; i <= 1; i++) {
            let g = vec2<f32>(f32(i), f32(j));
            let seed = hash2(ip + g);
            let still = seed * 0.5 + vec2(0.25);
            let animated =
                vec2(0.5) + ((seed - vec2(0.5)) * sin(vec2(uniforms.time * speed) + 6.2831 * seed));
            let o = mix(still, animated, vec2(jitter));
            let d = length(g + o - fp);
            if d < md {
                md2 = md;
                md = d;
            } else if d < md2 {
                md2 = d;
            }
        }
    }

    let interior = smoothstep(0.0, max(edge_width, 0.0001), md2 - md);
    let line = 1.0 - interior;

    // Keep the cell structure inside already-visible scene energy. A
    // uniform full-frame crack mask reads as a detached pane over the
    // livestream instead of a material modulation of the scene.
    let luma = dot(src.rgb, vec3<f32>(0.299, 0.587, 0.114));
    let surface_presence = smoothstep(0.04, 0.28, luma);
    let strength = min(0.055, edge_width * 4.0) * line * surface_presence;
    let integrated = mix(src.rgb, src.rgb * 0.88 + vec3(0.012, 0.018, 0.024), vec3(strength));
    fragColor = vec4<f32>(integrated, src.a);
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    return FragmentOutput(fragColor);
}
