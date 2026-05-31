//! screwm_ward_atlas — GPU ward-atlas service (Cairo→GPU port).
//!
//! Spec: docs/superpowers/specs/2026-05-30-screwm-cairo-gpu-port-design.md.
//!
//! Headless wgpu on the 5060 Ti. Renders the 2048×2304 ward-atlas — animated
//! Gray-Scott RD substrate (GEM cell) + a baked Px437 no-AA glyph atlas drawn
//! as instanced quads (the graffiti mural + per-ward text) — into a
//! `Bgra8Unorm` target, reads it back byte-exact, and atomically writes the
//! BGRA the DarkPlaces engine blits.
//!
//! Ships DORMANT: writes the SHADOW path `quake-live-ward-atlas.gpu.bgra` by
//! default (the engine reads `quake-live-ward-atlas.bgra`). Set
//! `HAPAX_WARD_ATLAS_REAL=1` to own the real path (per-mount cutover). The
//! Python Cairo producer stays intact as instant rollback.
//!
//! Scene content is currently the structural placeholder (GEM mural + ward
//! labels); the live-content scene builder (read each ward's shm) is the next
//! increment — until then this validates the GPU pipeline + shadow output.
use fontdue::{Font, FontSettings};
use std::borrow::Cow;
use std::collections::HashMap;
use std::time::{Duration, Instant};

const AW: u32 = 2048;
const AH: u32 = 2304;
const CW: f32 = 512.0;
const CH: f32 = 256.0;
const PX: f32 = 42.667;
const LABEL_PX: f32 = 28.0;
const GW: usize = 230;
const GH: usize = 30;
const TEX: wgpu::TextureFormat = wgpu::TextureFormat::Bgra8Unorm;
const ATLAS_W: u32 = 1024;
const GEM_CELL: usize = 7;
const SHM_DIR: &str = "/dev/shm/hapax-compositor";

const WARD_LABELS: [&str; 36] = [
    "TOKEN POLE", "ALBUM", "STREAM", "AOA OARB", "REVERIE", "ACTIVITY", "STANCE", "GEM",
    "GROUNDING", "IMPINGEMENT", "RECRUITMENT", "THINKING", "PRESSURE", "VARIETY", "WHOS HERE",
    "DURF", "CODING", "M8", "STEAMDECK", "EGRESS", "PROGRAMME", "PRECEDENT", "HISTORY",
    "RESEARCH", "CBIP", "CHAT", "CHRONICLE", "PROG STATE", "POLYEND", "LORE", "POSTER",
    "TUFTE", "ASCII", "SEGMENT", "M8 SCOPE", "CBIP IR",
];

// ── Gray-Scott RD substrate (gem_substrate.py U-skate constants) ──────────────
struct Rd {
    u: Vec<f32>,
    v: Vec<f32>,
}
impl Rd {
    fn new() -> Self {
        let mut u = vec![1.0f32; GW * GH];
        let mut v = vec![0.0f32; GW * GH];
        let (cy, cx) = (GH / 2, GW / 2);
        for dy in -1i32..=1 {
            for dx in -3i32..=2 {
                v[((cy as i32 + dy) as usize) * GW + (cx as i32 + dx) as usize] = 0.5;
                u[((cy as i32 + dy) as usize) * GW + (cx as i32 + dx) as usize] = 0.5;
            }
        }
        Self { u, v }
    }
    fn step(&mut self) {
        let w = |i: i32, n: i32| (((i % n) + n) % n) as usize;
        for _ in 0..4 {
            let (u, v) = (&self.u, &self.v);
            let mut nu = u.clone();
            let mut nv = v.clone();
            for y in 0..GH as i32 {
                for x in 0..GW as i32 {
                    let c = (y as usize) * GW + x as usize;
                    let lu = u[w(y - 1, GH as i32) * GW + x as usize] + u[w(y + 1, GH as i32) * GW + x as usize]
                        + u[(y as usize) * GW + w(x - 1, GW as i32)] + u[(y as usize) * GW + w(x + 1, GW as i32)] - 4.0 * u[c];
                    let lv = v[w(y - 1, GH as i32) * GW + x as usize] + v[w(y + 1, GH as i32) * GW + x as usize]
                        + v[(y as usize) * GW + w(x - 1, GW as i32)] + v[(y as usize) * GW + w(x + 1, GW as i32)] - 4.0 * v[c];
                    let uvv = u[c] * v[c] * v[c];
                    nu[c] = u[c] + (0.16 * lu - uvv + 0.035 * (1.0 - u[c]));
                    nv[c] = v[c] + (0.08 * lv + uvv - 0.095 * v[c]);
                }
            }
            self.u = nu;
            self.v = nv;
        }
    }
    fn r8(&self) -> Vec<u8> {
        self.v.iter().map(|&x| (x.clamp(0.0, 1.0) * 255.0).round() as u8).collect()
    }
}

// ── Glyph atlas (baked Px437, 0/255 threshold = no-AA) ────────────────────────
#[derive(Clone, Copy)]
struct G {
    ax: u32,
    ay: u32,
    w: u32,
    h: u32,
    xmin: i32,
    ymin: i32,
}

fn bake(font: &Font, chars: &[char], sizes: &[f32]) -> (Vec<u8>, u32, HashMap<(char, u32), G>, (u32, u32)) {
    let pad = 1u32;
    let (mut x, mut y, mut row_h) = (5u32, 0u32, 4u32);
    let solid = (0u32, 0u32);
    let mut map = HashMap::new();
    let mut rows = Vec::new();
    for &sz in sizes {
        for &ch in chars {
            let (m, bm) = font.rasterize(ch, sz);
            let (gw, gh) = (m.width as u32, m.height as u32);
            if x + gw + pad > ATLAS_W {
                x = 0;
                y += row_h + pad;
                row_h = 0;
            }
            map.insert((ch, sz.to_bits()), G { ax: x, ay: y, w: gw, h: gh, xmin: m.xmin, ymin: m.ymin });
            rows.push((x, y, m, bm));
            x += gw + pad;
            row_h = row_h.max(gh);
        }
    }
    let atlas_h = y + row_h + pad;
    let mut atlas = vec![0u8; (ATLAS_W * atlas_h) as usize];
    for dy in 0..4 {
        for dx in 0..4 {
            atlas[((solid.1 + dy) * ATLAS_W + solid.0 + dx) as usize] = 255;
        }
    }
    for (ax, ay, m, bm) in rows {
        for gy in 0..m.height {
            for gx in 0..m.width {
                atlas[((ay + gy as u32) * ATLAS_W + ax + gx as u32) as usize] = if bm[gy * m.width + gx] > 127 { 255 } else { 0 };
            }
        }
    }
    (atlas, atlas_h, map, solid)
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Inst {
    dest: [f32; 4],
    uv: [f32; 4],
    color: [f32; 4],
}

fn ndc(x: f32, y: f32, w: f32, h: f32) -> [f32; 4] {
    [x / AW as f32 * 2.0 - 1.0, 1.0 - y / AH as f32 * 2.0, w / AW as f32 * 2.0, -h / AH as f32 * 2.0]
}

struct Builder<'a> {
    font: &'a Font,
    map: &'a HashMap<(char, u32), G>,
    solid: (u32, u32),
    atlas_h: u32,
    inst: Vec<Inst>,
}
impl<'a> Builder<'a> {
    fn uvr(&self, ax: u32, ay: u32, w: u32, h: u32) -> [f32; 4] {
        [ax as f32 / ATLAS_W as f32, ay as f32 / self.atlas_h as f32, w as f32 / ATLAS_W as f32, h as f32 / self.atlas_h as f32]
    }
    fn glyph(&mut self, ch: char, px: f32, penx: f32, baseline: f32, color: [f32; 4], asc: f32) {
        if ch == ' ' {
            return;
        }
        if let Some(g) = self.map.get(&(ch, px.to_bits())).copied() {
            if g.w == 0 || g.h == 0 {
                return;
            }
            let dx = (penx + g.xmin as f32).round();
            let dy = (baseline - g.ymin as f32 - g.h as f32).round();
            self.inst.push(Inst { dest: ndc(dx, dy, g.w as f32, g.h as f32), uv: self.uvr(g.ax, g.ay, g.w, g.h), color });
        } else if ch == '\u{2571}' || ch == '\u{2572}' {
            let adv = self.font.metrics(ch, px).advance_width;
            let (sx, sy, ex, ey) = if ch == '\u{2571}' { (penx + 2.0, baseline, penx + adv - 2.0, baseline - asc) } else { (penx + 2.0, baseline - asc, penx + adv - 2.0, baseline) };
            let suv = self.uvr(self.solid.0, self.solid.1, 2, 2);
            for i in 0..=22 {
                let t = i as f32 / 22.0;
                self.inst.push(Inst { dest: ndc((sx + (ex - sx) * t).round(), (sy + (ey - sy) * t).round(), 3.0, 3.0), uv: suv, color });
            }
        }
    }
    fn text(&mut self, text: &str, px: f32, x0: f32, baseline: f32, color: [f32; 4], asc: f32) {
        let mut penx = x0;
        for ch in text.chars() {
            self.glyph(ch, px, penx, baseline, color, asc);
            penx += self.font.metrics(ch, px).advance_width;
        }
    }
    fn width(&self, text: &str, px: f32) -> f32 {
        text.chars().map(|c| self.font.metrics(c, px).advance_width).sum()
    }
}

const SUB_SHADER: &str = r#"
@group(0) @binding(0) var rd: texture_2d<f32>;
@group(0) @binding(1) var sm: sampler;
struct V { @builtin(position) pos: vec4<f32>, @location(0) uv: vec2<f32> };
@vertex fn vs(@builtin(vertex_index) vi: u32) -> V {
  let x0 = 1536.0/2048.0*2.0-1.0; let y0 = 1.0-256.0/2304.0*2.0;
  let x1 = 2048.0/2048.0*2.0-1.0; let y1 = 1.0-512.0/2304.0*2.0;
  var c = array<vec2<f32>,4>(vec2<f32>(x0,y0), vec2<f32>(x1,y0), vec2<f32>(x0,y1), vec2<f32>(x1,y1));
  var u = array<vec2<f32>,4>(vec2<f32>(0.,0.), vec2<f32>(1.,0.), vec2<f32>(0.,1.), vec2<f32>(1.,1.));
  var o: V; o.pos = vec4<f32>(c[vi],0.,1.); o.uv = u[vi]; return o;
}
@fragment fn fs(i: V) -> @location(0) vec4<f32> {
  let b = textureSample(rd, sm, i.uv).r * 0.35;
  return vec4<f32>(min(vec3<f32>(0.02,0.03,0.05)+b*vec3<f32>(0.10,0.62,0.50), vec3<f32>(1.0)), 1.0);
}
"#;

const GLYPH_SHADER: &str = r#"
@group(0) @binding(0) var atlas: texture_2d<f32>;
@group(0) @binding(1) var sm: sampler;
struct V { @builtin(position) pos: vec4<f32>, @location(0) uv: vec2<f32>, @location(1) color: vec4<f32> };
@vertex fn vs(@builtin(vertex_index) vi: u32, @location(0) dest: vec4<f32>, @location(1) uvr: vec4<f32>, @location(2) color: vec4<f32>) -> V {
  var cs = array<vec2<f32>,4>(vec2<f32>(0.,0.), vec2<f32>(1.,0.), vec2<f32>(0.,1.), vec2<f32>(1.,1.));
  let c = cs[vi];
  var o: V; o.pos = vec4<f32>(dest.xy + c*dest.zw, 0., 1.); o.uv = uvr.xy + c*uvr.zw; o.color = color; return o;
}
@fragment fn fs(i: V) -> @location(0) vec4<f32> {
  if (textureSample(atlas, sm, i.uv).r < 0.5) { discard; }
  return vec4<f32>(i.color.rgb, i.color.a);
}
"#;

fn align_up(v: u32, a: u32) -> u32 {
    (v + a - 1) & !(a - 1)
}

fn build_scene(font: &Font, map: &HashMap<(char, u32), G>, solid: (u32, u32), atlas_h: u32, asc_px: f32, asc_lbl: f32, lh_px: f32) -> Vec<Inst> {
    let mut b = Builder { font, map, solid, atlas_h, inst: Vec::new() };
    let fg = [0.10f32, 1.0, 0.45];
    let off8: [(i32, i32); 8] = [(-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, -2), (-2, 2), (2, 2)];
    for idx in 0..36usize {
        let (col, row) = ((idx % 4) as f32, (idx / 4) as f32);
        let (ox, oy) = (col * CW, row * CH);
        if idx == GEM_CELL {
            let layers: [(&str, f32, f32, f32); 3] = [
                ("\u{2591}\u{2592} HAPAX \u{2592}\u{2591}", 0.36, -26.0, -18.0),
                ("\u{00bb} HAPAX \u{00ab}", 0.94, 0.0, 0.0),
                ("\u{2571}\u{2572} HAPAX \u{2572}\u{2571}", 0.28, 24.0, 18.0),
            ];
            for (text, opacity, lx, ly) in layers {
                let tw = b.width(text, PX);
                let x0 = ox + (CW - tw) / 2.0 + lx;
                let baseline = oy + (CH - lh_px) / 2.0 + ly + asc_px;
                for (dx, dy) in off8 {
                    b.text(text, PX, x0 + dx as f32, baseline + dy as f32, [0.0, 0.0, 0.0, 0.9 * opacity], asc_px);
                }
                b.text(text, PX, x0, baseline, [fg[0], fg[1], fg[2], opacity], asc_px);
            }
        } else {
            let label = WARD_LABELS[idx];
            let tw = b.width(label, LABEL_PX);
            b.text(label, LABEL_PX, ox + (CW - tw) / 2.0, oy + CH / 2.0 + asc_lbl / 2.0, [0.45, 0.85, 0.65, 0.9], asc_lbl);
        }
    }
    b.inst
}

fn pick_adapter(instance: &wgpu::Instance) -> wgpu::Adapter {
    let want = std::env::var("HAPAX_WARD_ATLAS_GPU").unwrap_or_else(|_| "5060".to_string());
    let adapters = instance.enumerate_adapters(wgpu::Backends::VULKAN);
    for a in &adapters {
        if a.get_info().name.to_lowercase().contains(&want.to_lowercase()) {
            log::info!("ward-atlas GPU: {} (matched '{want}')", a.get_info().name);
            return a.clone();
        }
    }
    let fb = adapters.into_iter().next().expect("no Vulkan adapter for ward-atlas");
    log::warn!("ward-atlas: no adapter matched '{want}', using {}", fb.get_info().name);
    fb
}

async fn run() {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/root".into());
    let font_path = std::env::var("HAPAX_WARD_ATLAS_FONT").unwrap_or_else(|_| format!("{home}/.local/share/fonts/Px437_IBM_VGA_8x16.ttf"));
    let data = std::fs::read(&font_path).unwrap_or_else(|e| panic!("ward-atlas: read font {font_path}: {e}"));
    let font = Font::from_bytes(data, FontSettings::default()).expect("ward-atlas: parse font");
    let asc_px = font.horizontal_line_metrics(PX).unwrap().ascent;
    let asc_lbl = font.horizontal_line_metrics(LABEL_PX).unwrap().ascent;
    let lh_px = { let m = font.horizontal_line_metrics(PX).unwrap(); m.ascent - m.descent + m.line_gap };

    let mut chars: Vec<char> = (0x20u8..=0x7e).map(|b| b as char).collect();
    chars.extend(['\u{2591}', '\u{2592}', '\u{2593}', '\u{2588}', '\u{00bb}', '\u{00ab}']);
    let (atlas_bytes, atlas_h, map, solid) = bake(&font, &chars, &[PX, LABEL_PX]);
    let instances = build_scene(&font, &map, solid, atlas_h, asc_px, asc_lbl, lh_px);

    let real = std::env::var("HAPAX_WARD_ATLAS_REAL").map(|v| v == "1").unwrap_or(false);
    let out_name = if real { "quake-live-ward-atlas.bgra" } else { "quake-live-ward-atlas.gpu.bgra" };
    let out_path = format!("{SHM_DIR}/{out_name}");
    let fps: f32 = std::env::var("HAPAX_WARD_ATLAS_FPS").ok().and_then(|s| s.parse().ok()).unwrap_or(2.0);
    let _ = std::fs::create_dir_all(SHM_DIR);

    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor { backends: wgpu::Backends::VULKAN, ..Default::default() });
    let adapter = pick_adapter(&instance);
    let (device, queue) = adapter
        .request_device(&wgpu::DeviceDescriptor { label: Some("screwm-ward-atlas"), required_features: wgpu::Features::empty(), required_limits: wgpu::Limits::default(), ..Default::default() }, None)
        .await
        .expect("ward-atlas: request_device");

    let mk = |w, h, f, u| device.create_texture(&wgpu::TextureDescriptor { label: None, size: wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 }, mip_level_count: 1, sample_count: 1, dimension: wgpu::TextureDimension::D2, format: f, usage: u, view_formats: &[] });
    let up = |t: &wgpu::Texture, w, h, d: &[u8]| queue.write_texture(wgpu::TexelCopyTextureInfo { texture: t, mip_level: 0, origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All }, d, wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(w), rows_per_image: Some(h) }, wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 });

    let rd_tex = mk(GW as u32, GH as u32, wgpu::TextureFormat::R8Unorm, wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST);
    let atlas_tex = mk(ATLAS_W, atlas_h, wgpu::TextureFormat::R8Unorm, wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST);
    up(&atlas_tex, ATLAS_W, atlas_h, &atlas_bytes);
    let out_tex = mk(AW, AH, TEX, wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC);
    let out_view = out_tex.create_view(&Default::default());

    let lin = device.create_sampler(&wgpu::SamplerDescriptor { mag_filter: wgpu::FilterMode::Linear, min_filter: wgpu::FilterMode::Linear, ..Default::default() });
    let near = device.create_sampler(&wgpu::SamplerDescriptor::default());
    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor { label: None, entries: &[
        wgpu::BindGroupLayoutEntry { binding: 0, visibility: wgpu::ShaderStages::FRAGMENT, ty: wgpu::BindingType::Texture { sample_type: wgpu::TextureSampleType::Float { filterable: true }, view_dimension: wgpu::TextureViewDimension::D2, multisampled: false }, count: None },
        wgpu::BindGroupLayoutEntry { binding: 1, visibility: wgpu::ShaderStages::FRAGMENT, ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering), count: None },
    ] });
    let bind = |t: &wgpu::Texture, s: &wgpu::Sampler| device.create_bind_group(&wgpu::BindGroupDescriptor { label: None, layout: &bgl, entries: &[
        wgpu::BindGroupEntry { binding: 0, resource: wgpu::BindingResource::TextureView(&t.create_view(&Default::default())) },
        wgpu::BindGroupEntry { binding: 1, resource: wgpu::BindingResource::Sampler(s) },
    ] });
    let sub_bind = bind(&rd_tex, &lin);
    let glyph_bind = bind(&atlas_tex, &near);
    let pl = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor { label: None, bind_group_layouts: &[&bgl], push_constant_ranges: &[] });

    let ss = device.create_shader_module(wgpu::ShaderModuleDescriptor { label: None, source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(SUB_SHADER)) });
    let sub_pipe = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor { label: None, layout: Some(&pl),
        vertex: wgpu::VertexState { module: &ss, entry_point: Some("vs"), buffers: &[], compilation_options: Default::default() },
        fragment: Some(wgpu::FragmentState { module: &ss, entry_point: Some("fs"), targets: &[Some(wgpu::ColorTargetState { format: TEX, blend: None, write_mask: wgpu::ColorWrites::ALL })], compilation_options: Default::default() }),
        primitive: wgpu::PrimitiveState { topology: wgpu::PrimitiveTopology::TriangleStrip, ..Default::default() }, depth_stencil: None, multisample: Default::default(), multiview: None, cache: None });

    let gs = device.create_shader_module(wgpu::ShaderModuleDescriptor { label: None, source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(GLYPH_SHADER)) });
    let il = wgpu::VertexBufferLayout { array_stride: std::mem::size_of::<Inst>() as u64, step_mode: wgpu::VertexStepMode::Instance, attributes: &[
        wgpu::VertexAttribute { offset: 0, shader_location: 0, format: wgpu::VertexFormat::Float32x4 },
        wgpu::VertexAttribute { offset: 16, shader_location: 1, format: wgpu::VertexFormat::Float32x4 },
        wgpu::VertexAttribute { offset: 32, shader_location: 2, format: wgpu::VertexFormat::Float32x4 },
    ] };
    let glyph_pipe = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor { label: None, layout: Some(&pl),
        vertex: wgpu::VertexState { module: &gs, entry_point: Some("vs"), buffers: &[il], compilation_options: Default::default() },
        fragment: Some(wgpu::FragmentState { module: &gs, entry_point: Some("fs"), targets: &[Some(wgpu::ColorTargetState { format: TEX, blend: Some(wgpu::BlendState::ALPHA_BLENDING), write_mask: wgpu::ColorWrites::ALL })], compilation_options: Default::default() }),
        primitive: wgpu::PrimitiveState { topology: wgpu::PrimitiveTopology::TriangleStrip, ..Default::default() }, depth_stencil: None, multisample: Default::default(), multiview: None, cache: None });

    use wgpu::util::DeviceExt;
    let inst_buf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor { label: None, contents: bytemuck::cast_slice(&instances), usage: wgpu::BufferUsages::VERTEX });
    let bpr = align_up(AW * 4, 256);
    let staging = device.create_buffer(&wgpu::BufferDescriptor { label: None, size: (bpr * AH) as u64, usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST, mapped_at_creation: false });

    let mut rd = Rd::new();
    for _ in 0..90 {
        rd.step(); // warm to a developed spotted pattern
    }
    log::info!("ward-atlas live: {} instances @ {fps}fps -> {out_path} (real={real})", instances.len());

    let period = Duration::from_secs_f32(1.0 / fps.max(0.5));
    loop {
        let t0 = Instant::now();
        rd.step();
        up(&rd_tex, GW as u32, GH as u32, &rd.r8());

        let mut enc = device.create_command_encoder(&Default::default());
        {
            let mut p = enc.begin_render_pass(&wgpu::RenderPassDescriptor { label: None, color_attachments: &[Some(wgpu::RenderPassColorAttachment { view: &out_view, resolve_target: None, ops: wgpu::Operations { load: wgpu::LoadOp::Clear(wgpu::Color { r: 0.015, g: 0.020, b: 0.030, a: 1.0 }), store: wgpu::StoreOp::Store } })], depth_stencil_attachment: None, timestamp_writes: None, occlusion_query_set: None });
            p.set_pipeline(&sub_pipe);
            p.set_bind_group(0, &sub_bind, &[]);
            p.draw(0..4, 0..1);
            p.set_pipeline(&glyph_pipe);
            p.set_bind_group(0, &glyph_bind, &[]);
            p.set_vertex_buffer(0, inst_buf.slice(..));
            p.draw(0..4, 0..instances.len() as u32);
        }
        enc.copy_texture_to_buffer(wgpu::TexelCopyTextureInfo { texture: &out_tex, mip_level: 0, origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All }, wgpu::TexelCopyBufferInfo { buffer: &staging, layout: wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(bpr), rows_per_image: Some(AH) } }, wgpu::Extent3d { width: AW, height: AH, depth_or_array_layers: 1 });
        queue.submit(Some(enc.finish()));

        let (tx, rx) = std::sync::mpsc::channel();
        staging.slice(..).map_async(wgpu::MapMode::Read, move |r| { let _ = tx.send(r); });
        device.poll(wgpu::Maintain::Wait);
        if rx.recv().map(|r| r.is_err()).unwrap_or(true) {
            staging.unmap();
            continue;
        }
        let mapped = staging.slice(..).get_mapped_range();
        // bpr == AW*4 (8192, 256-aligned) so no de-pad needed.
        let out = mapped[..(bpr * AH) as usize].to_vec();
        drop(mapped);
        staging.unmap();

        let tmp = format!("{out_path}.tmp");
        let _ = std::fs::write(&tmp, &out).and_then(|_| std::fs::rename(&tmp, &out_path));

        if let Some(rem) = period.checked_sub(t0.elapsed()) {
            std::thread::sleep(rem);
        }
    }
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    pollster::block_on(run());
}
