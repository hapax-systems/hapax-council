// Sierpinski lines — fractal triangle line work overlay.
// 2-3 levels of subdivision, synthwave color palette.
// Audio-reactive line width and glow via intensity param.

struct Params {
    u_opacity: f32,
    u_line_width: f32,
    u_glow_radius: f32,
    u_time: f32,
    u_intensity: f32,
    u_spectral_color: f32,
    u_tri_scale: f32,
    u_tri_y_offset: f32,
}

struct FragmentOutput {
    @location(0) fragColor: vec4<f32>,
}

var<private> fragColor: vec4<f32>;
var<private> v_texcoord_1: vec2<f32>;

@group(1) @binding(0) var tex: texture_2d<f32>;
@group(1) @binding(1) var tex_sampler: sampler;

@group(2) @binding(0) var<uniform> global: Params;

// --- Synthwave palette ---

fn synthwave_color(t: f32, time: f32) -> vec3<f32> {
    let phase = t + time * 0.1;
    let r = 0.5 + 0.5 * sin(phase * 6.283);
    let g = 0.5 + 0.5 * sin(phase * 6.283 + 2.094);
    let b = 0.5 + 0.5 * sin(phase * 6.283 + 4.189);
    return vec3<f32>(mix(0.8, 1.0, r), mix(0.0, 1.0, g), mix(0.6, 1.0, b));
}

// --- Distance to line segment ---

fn dist_seg(p: vec2<f32>, ax: f32, ay: f32, bx: f32, by: f32) -> f32 {
    let pax = p.x - ax; let pay = p.y - ay;
    let bax = bx - ax; let bay = by - ay;
    let t = clamp((pax * bax + pay * bay) / (bax * bax + bay * bay), 0.0, 1.0);
    let dx = pax - bax * t; let dy = pay - bay * t;
    return sqrt(dx * dx + dy * dy);
}

fn dist_tri(p: vec2<f32>, ax: f32, ay: f32, bx: f32, by: f32, cx: f32, cy: f32) -> f32 {
    return min(min(dist_seg(p, ax, ay, bx, by), dist_seg(p, bx, by, cx, cy)), dist_seg(p, cx, cy, ax, ay));
}

// --- Main ---

fn main_1() {
    let uv = v_texcoord_1;
    let time = global.u_time;
    let base_sample = textureSample(tex, tex_sampler, uv);
    let base = base_sample.rgb;

    let pixel = 1.0 / 1080.0;
    let line_w = global.u_line_width * pixel * (1.0 + global.u_intensity * 0.5);
    let glow_r = global.u_glow_radius * pixel * (1.0 + global.u_intensity * 0.3);

    let scale = global.u_tri_scale;
    let y_off = global.u_tri_y_offset;
    let aspect = 16.0 / 9.0;
    let h = scale * 0.866;

    // Level 0: main triangle
    let tx = 0.5;                            let ty = 0.5 + y_off - h * 0.667;
    let bx_l = 0.5 - scale * 0.5 / aspect;  let by_l = 0.5 + y_off + h * 0.333;
    let bx_r = 0.5 + scale * 0.5 / aspect;  let by_r = 0.5 + y_off + h * 0.333;

    var min_d = dist_tri(uv, tx, ty, bx_l, by_l, bx_r, by_r);

    // Level 1 midpoints
    let m01x = (tx + bx_l) * 0.5;   let m01y = (ty + by_l) * 0.5;
    let m12x = (bx_l + bx_r) * 0.5; let m12y = (by_l + by_r) * 0.5;
    let m02x = (tx + bx_r) * 0.5;   let m02y = (ty + by_r) * 0.5;

    // Level 1: 4 sub-triangles
    min_d = min(min_d, dist_tri(uv, tx, ty, m01x, m01y, m02x, m02y));
    min_d = min(min_d, dist_tri(uv, m01x, m01y, bx_l, by_l, m12x, m12y));
    min_d = min(min_d, dist_tri(uv, m02x, m02y, m12x, m12y, bx_r, by_r));
    min_d = min(min_d, dist_tri(uv, m01x, m01y, m12x, m12y, m02x, m02y));

    // Level 2: subdivide corner 0 (top)
    let c0_m01x = (tx + m01x) * 0.5; let c0_m01y = (ty + m01y) * 0.5;
    let c0_m12x = (m01x + m02x) * 0.5; let c0_m12y = (m01y + m02y) * 0.5;
    let c0_m02x = (tx + m02x) * 0.5; let c0_m02y = (ty + m02y) * 0.5;
    min_d = min(min_d, dist_tri(uv, tx, ty, c0_m01x, c0_m01y, c0_m02x, c0_m02y));
    min_d = min(min_d, dist_tri(uv, c0_m01x, c0_m01y, m01x, m01y, c0_m12x, c0_m12y));
    min_d = min(min_d, dist_tri(uv, c0_m02x, c0_m02y, c0_m12x, c0_m12y, m02x, m02y));
    min_d = min(min_d, dist_tri(uv, c0_m01x, c0_m01y, c0_m12x, c0_m12y, c0_m02x, c0_m02y));

    // Level 2: subdivide corner 1 (bottom-left)
    let c1_m01x = (m01x + bx_l) * 0.5; let c1_m01y = (m01y + by_l) * 0.5;
    let c1_m12x = (bx_l + m12x) * 0.5; let c1_m12y = (by_l + m12y) * 0.5;
    let c1_m02x = (m01x + m12x) * 0.5; let c1_m02y = (m01y + m12y) * 0.5;
    min_d = min(min_d, dist_tri(uv, m01x, m01y, c1_m01x, c1_m01y, c1_m02x, c1_m02y));
    min_d = min(min_d, dist_tri(uv, c1_m01x, c1_m01y, bx_l, by_l, c1_m12x, c1_m12y));
    min_d = min(min_d, dist_tri(uv, c1_m02x, c1_m02y, c1_m12x, c1_m12y, m12x, m12y));
    min_d = min(min_d, dist_tri(uv, c1_m01x, c1_m01y, c1_m12x, c1_m12y, c1_m02x, c1_m02y));

    // Level 2: subdivide corner 2 (bottom-right)
    let c2_m01x = (m02x + m12x) * 0.5; let c2_m01y = (m02y + m12y) * 0.5;
    let c2_m12x = (m12x + bx_r) * 0.5; let c2_m12y = (m12y + by_r) * 0.5;
    let c2_m02x = (m02x + bx_r) * 0.5; let c2_m02y = (m02y + by_r) * 0.5;
    min_d = min(min_d, dist_tri(uv, m02x, m02y, c2_m01x, c2_m01y, c2_m02x, c2_m02y));
    min_d = min(min_d, dist_tri(uv, c2_m01x, c2_m01y, m12x, m12y, c2_m12x, c2_m12y));
    min_d = min(min_d, dist_tri(uv, c2_m02x, c2_m02y, c2_m12x, c2_m12y, bx_r, by_r));
    min_d = min(min_d, dist_tri(uv, c2_m01x, c2_m01y, c2_m12x, c2_m12y, c2_m02x, c2_m02y));

    // Line + glow
    let line_alpha = 1.0 - smoothstep(0.0, line_w, min_d);
    let glow_alpha = (1.0 - smoothstep(line_w, line_w + glow_r, min_d)) * 0.4;
    let total_alpha = max(line_alpha, glow_alpha) * global.u_opacity;

    let color_t = global.u_spectral_color + min_d * 50.0;
    let line_color = synthwave_color(color_t, time);

    let result = base + line_color * total_alpha;
    fragColor = vec4<f32>(result, base_sample.a);
    return;
}

@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> FragmentOutput {
    v_texcoord_1 = v_texcoord;
    main_1();
    let _e11 = fragColor;
    return FragmentOutput(_e11);
}
