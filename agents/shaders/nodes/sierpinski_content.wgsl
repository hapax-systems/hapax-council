// Sierpinski content — triangle-masked video compositing.
// 3 YouTube videos in corner triangle regions, waveform data in center.

struct Params {
    u_salience: f32,
    u_intensity: f32,
    u_time: f32,
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
@group(1) @binding(2) var content_slot_0: texture_2d<f32>;
@group(1) @binding(3) var content_slot_1: texture_2d<f32>;
@group(1) @binding(4) var content_slot_2: texture_2d<f32>;
@group(1) @binding(5) var content_slot_3: texture_2d<f32>;

@group(2) @binding(0) var<uniform> global: Params;

// --- Sierpinski geometry (flat functions, no nested arrays) ---

fn point_in_tri(p: vec2<f32>, ax: f32, ay: f32, bx: f32, by: f32, cx: f32, cy: f32) -> bool {
    let v0x = cx - ax; let v0y = cy - ay;
    let v1x = bx - ax; let v1y = by - ay;
    let v2x = p.x - ax; let v2y = p.y - ay;
    let d00 = v0x * v0x + v0y * v0y;
    let d01 = v0x * v1x + v0y * v1y;
    let d02 = v0x * v2x + v0y * v2y;
    let d11 = v1x * v1x + v1y * v1y;
    let d12 = v1x * v2x + v1y * v2y;
    let inv = 1.0 / (d00 * d11 - d01 * d01);
    let u = (d11 * d02 - d01 * d12) * inv;
    let v = (d00 * d12 - d01 * d02) * inv;
    return u >= 0.0 && v >= 0.0 && (u + v) <= 1.0;
}

fn tri_uv(p: vec2<f32>, ax: f32, ay: f32, bx: f32, by: f32, cx: f32, cy: f32) -> vec2<f32> {
    let min_x = min(min(ax, bx), cx);
    let min_y = min(min(ay, by), cy);
    let max_x = max(max(ax, bx), cx);
    let max_y = max(max(ay, by), cy);
    return clamp((p - vec2(min_x, min_y)) / vec2(max_x - min_x, max_y - min_y), vec2(0.0), vec2(1.0));
}

fn sample_slot(slot_tex: texture_2d<f32>, samp: sampler, uv: vec2<f32>, opacity: f32, base: vec3<f32>) -> vec3<f32> {
    if opacity < 0.001 { return base; }
    let c = textureSample(slot_tex, samp, uv);
    let lum = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    let presence = smoothstep(0.02, 0.08, lum);
    return mix(base, c.rgb, opacity * presence);
}

// --- Main ---

fn main_1() {
    let uv = v_texcoord_1;
    let scale = global.u_tri_scale;
    let y_off = global.u_tri_y_offset;
    let aspect = 16.0 / 9.0;
    let h = scale * 0.866;

    // Main triangle vertices (flattened, no arrays)
    let tx = 0.5;                              let ty = 0.5 + y_off - h * 0.667;
    let bx_l = 0.5 - scale * 0.5 / aspect;    let by_l = 0.5 + y_off + h * 0.333;
    let bx_r = 0.5 + scale * 0.5 / aspect;    let by_r = 0.5 + y_off + h * 0.333;

    // Midpoints
    let m01x = (tx + bx_l) * 0.5;   let m01y = (ty + by_l) * 0.5;
    let m12x = (bx_l + bx_r) * 0.5; let m12y = (by_l + by_r) * 0.5;
    let m02x = (tx + bx_r) * 0.5;   let m02y = (ty + by_r) * 0.5;

    let base_sample = textureSample(tex, tex_sampler, uv);
    let base = base_sample.rgb;
    var result = base;

    // Check if inside main triangle at all
    if !point_in_tri(uv, tx, ty, bx_l, by_l, bx_r, by_r) {
        fragColor = vec4<f32>(result, base_sample.a);
        return;
    }

    // Corner 0: top (tx,ty - m01 - m02)
    if point_in_tri(uv, tx, ty, m01x, m01y, m02x, m02y) {
        let suv = tri_uv(uv, tx, ty, m01x, m01y, m02x, m02y);
        result = sample_slot(content_slot_0, tex_sampler, suv, uniforms.slot_opacities[0], base);
    }
    // Corner 1: bottom-left (m01 - bx_l,by_l - m12)
    else if point_in_tri(uv, m01x, m01y, bx_l, by_l, m12x, m12y) {
        let suv = tri_uv(uv, m01x, m01y, bx_l, by_l, m12x, m12y);
        result = sample_slot(content_slot_1, tex_sampler, suv, uniforms.slot_opacities[1], base);
    }
    // Corner 2: bottom-right (m02 - m12 - bx_r,by_r)
    else if point_in_tri(uv, m02x, m02y, m12x, m12y, bx_r, by_r) {
        let suv = tri_uv(uv, m02x, m02y, m12x, m12y, bx_r, by_r);
        result = sample_slot(content_slot_2, tex_sampler, suv, uniforms.slot_opacities[2], base);
    }
    // Center void: waveform
    else {
        let wf_uv = tri_uv(uv, m01x, m01y, m12x, m12y, m02x, m02y);
        var wf = 0.0;
        // Simple 8-bar waveform
        for (var i = 0u; i < 8u; i++) {
            let amp = uniforms.custom[i / 4u][i % 4u] * 0.5 + 0.1;
            let bw = 1.0 / 8.0;
            let bx = f32(i) * bw;
            let in_bar = step(bx, wf_uv.x) * step(wf_uv.x, bx + bw * 0.7);
            let bh = amp * 0.8;
            let in_h = step(0.5 - bh * 0.5, wf_uv.y) * step(wf_uv.y, 0.5 + bh * 0.5);
            wf = max(wf, in_bar * in_h);
        }
        result = result + vec3<f32>(0.0, 0.9, 1.0) * wf * 1.5;
    }

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
