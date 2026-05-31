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
//! Scene content is still an incremental port. The first live-content seam is
//! data-driven: the Rust manifest mirrors the Python atlas ward order and direct
//! texture exclusions, and external RGBA shm sources render from their declared
//! layout paths. Cairo-backed wards fail closed until their GPU IR is ported.
use fontdue::{Font, FontSettings};
use serde::{Deserialize, Serialize};
use std::borrow::Cow;
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

const AW: u32 = 2048;
const AH: u32 = 2304;
const CW: f32 = 512.0;
const CH: f32 = 256.0;
const PX: f32 = 42.667;
const GW: usize = 230;
const GH: usize = 30;
const TEX: wgpu::TextureFormat = wgpu::TextureFormat::Bgra8Unorm;
const EXT_TEX: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;
const ATLAS_W: u32 = 1024;
const GEM_CELL: usize = 7;
const SHM_DIR: &str = "/dev/shm/hapax-compositor";
const REAL_BGRA_NAME: &str = "quake-live-ward-atlas.bgra";
const SHADOW_BGRA_NAME: &str = "quake-live-ward-atlas.gpu.bgra";
const REAL_META_NAME: &str = "quake-live-ward-atlas.json";
const SHADOW_META_NAME: &str = "quake-live-ward-atlas.gpu.json";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct WardSpec {
    id: &'static str,
    label: &'static str,
    direct_texture: bool,
}

const WARD_SPECS: [WardSpec; 36] = [
    WardSpec {
        id: "token_pole",
        label: "TOKEN POLE",
        direct_texture: false,
    },
    WardSpec {
        id: "album",
        label: "ALBUM",
        direct_texture: false,
    },
    WardSpec {
        id: "stream_overlay",
        label: "STREAM",
        direct_texture: false,
    },
    WardSpec {
        id: "aoa_oarb_state",
        label: "AOA OARB",
        direct_texture: false,
    },
    WardSpec {
        id: "reverie",
        label: "REVERIE",
        direct_texture: true,
    },
    WardSpec {
        id: "activity_header",
        label: "ACTIVITY",
        direct_texture: false,
    },
    WardSpec {
        id: "stance_indicator",
        label: "STANCE",
        direct_texture: false,
    },
    WardSpec {
        id: "gem",
        label: "GEM",
        direct_texture: false,
    },
    WardSpec {
        id: "grounding_provenance_ticker",
        label: "GROUNDING",
        direct_texture: false,
    },
    WardSpec {
        id: "impingement_cascade",
        label: "IMPINGEMENT",
        direct_texture: false,
    },
    WardSpec {
        id: "recruitment_candidate_panel",
        label: "RECRUITMENT",
        direct_texture: false,
    },
    WardSpec {
        id: "thinking_indicator",
        label: "THINKING",
        direct_texture: false,
    },
    WardSpec {
        id: "pressure_gauge",
        label: "PRESSURE",
        direct_texture: false,
    },
    WardSpec {
        id: "activity_variety_log",
        label: "VARIETY",
        direct_texture: false,
    },
    WardSpec {
        id: "whos_here",
        label: "WHO'S HERE",
        direct_texture: false,
    },
    WardSpec {
        id: "durf",
        label: "DURF",
        direct_texture: false,
    },
    WardSpec {
        id: "coding_session_reveal",
        label: "CODING",
        direct_texture: false,
    },
    WardSpec {
        id: "m8-display",
        label: "M8 DISPLAY",
        direct_texture: false,
    },
    WardSpec {
        id: "steamdeck-display",
        label: "STEAM DECK",
        direct_texture: false,
    },
    WardSpec {
        id: "egress_footer",
        label: "EGRESS",
        direct_texture: false,
    },
    WardSpec {
        id: "programme_banner",
        label: "PROGRAMME",
        direct_texture: false,
    },
    WardSpec {
        id: "precedent_ticker",
        label: "PRECEDENT",
        direct_texture: false,
    },
    WardSpec {
        id: "programme_history",
        label: "HISTORY",
        direct_texture: false,
    },
    WardSpec {
        id: "research_instrument_dashboard",
        label: "RESEARCH",
        direct_texture: false,
    },
    WardSpec {
        id: "cbip_signal_density",
        label: "CBIP",
        direct_texture: false,
    },
    WardSpec {
        id: "chat_ambient",
        label: "CHAT",
        direct_texture: false,
    },
    WardSpec {
        id: "chronicle_ticker",
        label: "CHRONICLE",
        direct_texture: false,
    },
    WardSpec {
        id: "programme_state",
        label: "STATE",
        direct_texture: false,
    },
    WardSpec {
        id: "polyend_instrument_reveal",
        label: "POLYEND",
        direct_texture: false,
    },
    WardSpec {
        id: "interactive_lore_query",
        label: "LORE QUERY",
        direct_texture: false,
    },
    WardSpec {
        id: "constructivist_research_poster",
        label: "POSTER",
        direct_texture: false,
    },
    WardSpec {
        id: "tufte_density",
        label: "TUFTE",
        direct_texture: false,
    },
    WardSpec {
        id: "ascii_schematic",
        label: "ASCII",
        direct_texture: false,
    },
    WardSpec {
        id: "segment_content",
        label: "SEGMENT",
        direct_texture: false,
    },
    WardSpec {
        id: "m8_oscilloscope",
        label: "M8 SCOPE",
        direct_texture: false,
    },
    WardSpec {
        id: "cbip_dual_ir_displacement",
        label: "IR DUAL",
        direct_texture: false,
    },
];

#[derive(Debug, Clone)]
struct WardSource {
    spec: WardSpec,
    natural_w: Option<u32>,
    natural_h: Option<u32>,
    external_rgba: Option<PathBuf>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct OutputPaths {
    bgra: PathBuf,
    meta: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ExternalFrameRead {
    Ready(Vec<u8>),
    WrongSize { actual: usize, expected: usize },
    Missing { reason: String },
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
struct WardMetadata {
    index: usize,
    label: String,
    status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    texture: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    source_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    source_width: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    source_height: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    actual_bytes: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    expected_bytes: Option<usize>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
struct WardAtlasMetadata {
    w: u32,
    h: u32,
    stride: u32,
    frame_id: u64,
    ward_count: usize,
    layout_path: String,
    real: bool,
    output_path: String,
    meta_path: String,
    wards: BTreeMap<String, WardMetadata>,
}

#[derive(Debug, Deserialize)]
struct LayoutDoc {
    #[serde(default)]
    sources: Vec<LayoutSource>,
}

#[derive(Debug, Clone, Deserialize)]
struct LayoutSource {
    id: String,
    kind: String,
    #[serde(default)]
    params: LayoutParams,
}

#[derive(Debug, Clone, Default, Deserialize)]
struct LayoutParams {
    natural_w: Option<u32>,
    natural_h: Option<u32>,
    shm_path: Option<PathBuf>,
}

fn load_layout_sources(path: &Path) -> HashMap<String, LayoutSource> {
    let text = match std::fs::read_to_string(path) {
        Ok(text) => text,
        Err(err) => {
            log::warn!("ward-atlas: layout {} unavailable: {err}", path.display());
            return HashMap::new();
        }
    };
    let doc: LayoutDoc = match serde_json::from_str(&text) {
        Ok(doc) => doc,
        Err(err) => {
            log::warn!("ward-atlas: layout {} invalid: {err}", path.display());
            return HashMap::new();
        }
    };
    doc.sources
        .into_iter()
        .map(|src| (src.id.clone(), src))
        .collect()
}

fn load_ward_sources(layout_path: &Path) -> Vec<WardSource> {
    let layout = load_layout_sources(layout_path);
    WARD_SPECS
        .iter()
        .copied()
        .map(|spec| {
            let src = layout.get(spec.id);
            let external_rgba = src
                .filter(|source| source.kind == "external_rgba")
                .and_then(|source| source.params.shm_path.clone());
            WardSource {
                spec,
                natural_w: src.and_then(|source| source.params.natural_w),
                natural_h: src.and_then(|source| source.params.natural_h),
                external_rgba,
            }
        })
        .collect()
}

fn default_layout_path(_home: &str) -> PathBuf {
    std::env::var("HAPAX_WARD_ATLAS_LAYOUT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../../config/compositor-layouts/default.json")
        })
}

fn ward_atlas_output_paths(real: bool) -> OutputPaths {
    let (bgra_name, meta_name) = if real {
        (REAL_BGRA_NAME, REAL_META_NAME)
    } else {
        (SHADOW_BGRA_NAME, SHADOW_META_NAME)
    };
    OutputPaths {
        bgra: Path::new(SHM_DIR).join(bgra_name),
        meta: Path::new(SHM_DIR).join(meta_name),
    }
}

fn expected_rgba_bytes(width: u32, height: u32) -> Option<usize> {
    (width as usize)
        .checked_mul(height as usize)?
        .checked_mul(4)
}

fn read_external_rgba_frame_status(path: &Path, width: u32, height: u32) -> ExternalFrameRead {
    let Some(expected) = expected_rgba_bytes(width, height) else {
        return ExternalFrameRead::Missing {
            reason: "invalid dimensions".to_string(),
        };
    };
    match std::fs::read(path) {
        Ok(bytes) if bytes.len() == expected => ExternalFrameRead::Ready(bytes),
        Ok(bytes) => {
            log::warn!(
                "ward-atlas: external source {} wrong size: {} != {expected}",
                path.display(),
                bytes.len()
            );
            ExternalFrameRead::WrongSize {
                actual: bytes.len(),
                expected,
            }
        }
        Err(err) => {
            log::debug!(
                "ward-atlas: external source {} unavailable: {err}",
                path.display()
            );
            ExternalFrameRead::Missing {
                reason: err.to_string(),
            }
        }
    }
}

fn external_status_metadata(
    index: usize,
    source: &WardSource,
    status: &ExternalFrameRead,
) -> WardMetadata {
    let path = source
        .external_rgba
        .as_ref()
        .map(|p| p.display().to_string());
    let expected_bytes = source
        .natural_w
        .zip(source.natural_h)
        .and_then(|(w, h)| expected_rgba_bytes(w, h));
    match status {
        ExternalFrameRead::Ready(_) => WardMetadata {
            index,
            label: source.spec.label.to_string(),
            status: "rendered".to_string(),
            source_path: path,
            source_width: source.natural_w,
            source_height: source.natural_h,
            expected_bytes,
            ..Default::default()
        },
        ExternalFrameRead::WrongSize { actual, expected } => WardMetadata {
            index,
            label: source.spec.label.to_string(),
            status: "wrong-size".to_string(),
            reason: Some("external RGBA frame size mismatch".to_string()),
            source_path: path,
            source_width: source.natural_w,
            source_height: source.natural_h,
            actual_bytes: Some(*actual),
            expected_bytes: Some(*expected),
            ..Default::default()
        },
        ExternalFrameRead::Missing { reason } => WardMetadata {
            index,
            label: source.spec.label.to_string(),
            status: "missing".to_string(),
            reason: Some(reason.clone()),
            source_path: path,
            source_width: source.natural_w,
            source_height: source.natural_h,
            expected_bytes,
            ..Default::default()
        },
    }
}

fn build_metadata(
    frame_id: u64,
    real: bool,
    paths: &OutputPaths,
    layout_path: &Path,
    ward_sources: &[WardSource],
    external_statuses: &BTreeMap<&'static str, ExternalFrameRead>,
) -> WardAtlasMetadata {
    let mut wards = BTreeMap::new();
    for (index, source) in ward_sources.iter().enumerate() {
        let metadata = if source.spec.direct_texture {
            WardMetadata {
                index,
                label: source.spec.label.to_string(),
                status: "direct-texture-owned".to_string(),
                reason: Some("direct live texture owns this ward".to_string()),
                texture: Some("w05".to_string()),
                source_path: source
                    .external_rgba
                    .as_ref()
                    .map(|p| p.display().to_string()),
                source_width: source.natural_w,
                source_height: source.natural_h,
                ..Default::default()
            }
        } else if let Some(status) = external_statuses.get(source.spec.id) {
            external_status_metadata(index, source, status)
        } else if source.external_rgba.is_some() {
            external_status_metadata(
                index,
                source,
                &ExternalFrameRead::Missing {
                    reason: "not read this frame".to_string(),
                },
            )
        } else {
            WardMetadata {
                index,
                label: source.spec.label.to_string(),
                status: "fallback".to_string(),
                reason: Some("gpu ward IR not ported".to_string()),
                source_width: source.natural_w,
                source_height: source.natural_h,
                ..Default::default()
            }
        };
        wards.insert(source.spec.id.to_string(), metadata);
    }
    WardAtlasMetadata {
        w: AW,
        h: AH,
        stride: AW * 4,
        frame_id,
        ward_count: ward_sources.len(),
        layout_path: layout_path.display().to_string(),
        real,
        output_path: paths.bgra.display().to_string(),
        meta_path: paths.meta.display().to_string(),
        wards,
    }
}

fn tmp_path_for(path: &Path) -> PathBuf {
    let mut tmp = path.as_os_str().to_os_string();
    tmp.push(".tmp");
    PathBuf::from(tmp)
}

fn atomic_write(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let tmp = tmp_path_for(path);
    std::fs::write(&tmp, bytes).and_then(|_| std::fs::rename(&tmp, path))
}

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
                    let lu = u[w(y - 1, GH as i32) * GW + x as usize]
                        + u[w(y + 1, GH as i32) * GW + x as usize]
                        + u[(y as usize) * GW + w(x - 1, GW as i32)]
                        + u[(y as usize) * GW + w(x + 1, GW as i32)]
                        - 4.0 * u[c];
                    let lv = v[w(y - 1, GH as i32) * GW + x as usize]
                        + v[w(y + 1, GH as i32) * GW + x as usize]
                        + v[(y as usize) * GW + w(x - 1, GW as i32)]
                        + v[(y as usize) * GW + w(x + 1, GW as i32)]
                        - 4.0 * v[c];
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
        self.v
            .iter()
            .map(|&x| (x.clamp(0.0, 1.0) * 255.0).round() as u8)
            .collect()
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

fn bake(
    font: &Font,
    chars: &[char],
    sizes: &[f32],
) -> (Vec<u8>, u32, HashMap<(char, u32), G>, (u32, u32)) {
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
            map.insert(
                (ch, sz.to_bits()),
                G {
                    ax: x,
                    ay: y,
                    w: gw,
                    h: gh,
                    xmin: m.xmin,
                    ymin: m.ymin,
                },
            );
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
                atlas[((ay + gy as u32) * ATLAS_W + ax + gx as u32) as usize] =
                    if bm[gy * m.width + gx] > 127 { 255 } else { 0 };
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

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct ImageInst {
    dest: [f32; 4],
}

fn ndc(x: f32, y: f32, w: f32, h: f32) -> [f32; 4] {
    [
        x / AW as f32 * 2.0 - 1.0,
        1.0 - y / AH as f32 * 2.0,
        w / AW as f32 * 2.0,
        -h / AH as f32 * 2.0,
    ]
}

fn cell_ndc(index: usize) -> [f32; 4] {
    let col = (index % 4) as f32;
    let row = (index / 4) as f32;
    ndc(col * CW, row * CH, CW, CH)
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
        [
            ax as f32 / ATLAS_W as f32,
            ay as f32 / self.atlas_h as f32,
            w as f32 / ATLAS_W as f32,
            h as f32 / self.atlas_h as f32,
        ]
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
            self.inst.push(Inst {
                dest: ndc(dx, dy, g.w as f32, g.h as f32),
                uv: self.uvr(g.ax, g.ay, g.w, g.h),
                color,
            });
        } else if ch == '\u{2571}' || ch == '\u{2572}' {
            let adv = self.font.metrics(ch, px).advance_width;
            let (sx, sy, ex, ey) = if ch == '\u{2571}' {
                (penx + 2.0, baseline, penx + adv - 2.0, baseline - asc)
            } else {
                (penx + 2.0, baseline - asc, penx + adv - 2.0, baseline)
            };
            let suv = self.uvr(self.solid.0, self.solid.1, 2, 2);
            for i in 0..=22 {
                let t = i as f32 / 22.0;
                self.inst.push(Inst {
                    dest: ndc(
                        (sx + (ex - sx) * t).round(),
                        (sy + (ey - sy) * t).round(),
                        3.0,
                        3.0,
                    ),
                    uv: suv,
                    color,
                });
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
        text.chars()
            .map(|c| self.font.metrics(c, px).advance_width)
            .sum()
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

const IMAGE_SHADER: &str = r#"
@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var sm: sampler;
struct V { @builtin(position) pos: vec4<f32>, @location(0) uv: vec2<f32> };
@vertex fn vs(@builtin(vertex_index) vi: u32, @location(0) dest: vec4<f32>) -> V {
  var cs = array<vec2<f32>,4>(vec2<f32>(0.,0.), vec2<f32>(1.,0.), vec2<f32>(0.,1.), vec2<f32>(1.,1.));
  let c = cs[vi];
  var o: V; o.pos = vec4<f32>(dest.xy + c*dest.zw, 0., 1.); o.uv = c; return o;
}
@fragment fn fs(i: V) -> @location(0) vec4<f32> {
  return textureSample(src, sm, i.uv);
}
"#;

fn align_up(v: u32, a: u32) -> u32 {
    (v + a - 1) & !(a - 1)
}

fn build_scene(
    font: &Font,
    map: &HashMap<(char, u32), G>,
    solid: (u32, u32),
    atlas_h: u32,
    asc_px: f32,
    lh_px: f32,
) -> Vec<Inst> {
    let mut b = Builder {
        font,
        map,
        solid,
        atlas_h,
        inst: Vec::new(),
    };
    let fg = [0.10f32, 1.0, 0.45];
    let off8: [(i32, i32); 8] = [
        (-3, 0),
        (3, 0),
        (0, -3),
        (0, 3),
        (-2, -2),
        (2, -2),
        (-2, 2),
        (2, 2),
    ];
    for idx in 0..36usize {
        let (col, row) = ((idx % 4) as f32, (idx / 4) as f32);
        let (ox, oy) = (col * CW, row * CH);
        if idx == GEM_CELL {
            let layers: [(&str, f32, f32, f32); 3] = [
                (
                    "\u{2591}\u{2592} HAPAX \u{2592}\u{2591}",
                    0.36,
                    -26.0,
                    -18.0,
                ),
                ("\u{00bb} HAPAX \u{00ab}", 0.94, 0.0, 0.0),
                ("\u{2571}\u{2572} HAPAX \u{2572}\u{2571}", 0.28, 24.0, 18.0),
            ];
            for (text, opacity, lx, ly) in layers {
                let tw = b.width(text, PX);
                let x0 = ox + (CW - tw) / 2.0 + lx;
                let baseline = oy + (CH - lh_px) / 2.0 + ly + asc_px;
                for (dx, dy) in off8 {
                    b.text(
                        text,
                        PX,
                        x0 + dx as f32,
                        baseline + dy as f32,
                        [0.0, 0.0, 0.0, 0.9 * opacity],
                        asc_px,
                    );
                }
                b.text(
                    text,
                    PX,
                    x0,
                    baseline,
                    [fg[0], fg[1], fg[2], opacity],
                    asc_px,
                );
            }
        }
    }
    b.inst
}

struct ExternalWardGpu {
    source: WardSource,
    texture: wgpu::Texture,
    bind_group: wgpu::BindGroup,
    inst_buf: wgpu::Buffer,
}

impl ExternalWardGpu {
    fn new(
        device: &wgpu::Device,
        bgl: &wgpu::BindGroupLayout,
        sampler: &wgpu::Sampler,
        source: WardSource,
        index: usize,
    ) -> Option<Self> {
        let (width, height) = (source.natural_w?, source.natural_h?);
        if source.external_rgba.is_none() || width == 0 || height == 0 {
            return None;
        }
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(source.spec.id),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: EXT_TEX,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some(source.spec.id),
            layout: bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(sampler),
                },
            ],
        });
        use wgpu::util::DeviceExt;
        let inst = ImageInst {
            dest: cell_ndc(index),
        };
        let inst_buf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some(source.spec.id),
            contents: bytemuck::bytes_of(&inst),
            usage: wgpu::BufferUsages::VERTEX,
        });
        Some(Self {
            source,
            texture,
            bind_group,
            inst_buf,
        })
    }

    fn upload_status(&self, queue: &wgpu::Queue) -> ExternalFrameRead {
        let (Some(path), Some(width), Some(height)) = (
            self.source.external_rgba.as_ref(),
            self.source.natural_w,
            self.source.natural_h,
        ) else {
            return ExternalFrameRead::Missing {
                reason: "external RGBA source is not configured".to_string(),
            };
        };
        let status = read_external_rgba_frame_status(path, width, height);
        let ExternalFrameRead::Ready(bytes) = &status else {
            return status;
        };
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &self.texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            &bytes,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(width * 4),
                rows_per_image: Some(height),
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
        status
    }
}

fn pick_adapter(instance: &wgpu::Instance) -> wgpu::Adapter {
    let want = std::env::var("HAPAX_WARD_ATLAS_GPU").unwrap_or_else(|_| "5060".to_string());
    let adapters = instance.enumerate_adapters(wgpu::Backends::VULKAN);
    for a in &adapters {
        if a.get_info()
            .name
            .to_lowercase()
            .contains(&want.to_lowercase())
        {
            log::info!("ward-atlas GPU: {} (matched '{want}')", a.get_info().name);
            return a.clone();
        }
    }
    let fb = adapters
        .into_iter()
        .next()
        .expect("no Vulkan adapter for ward-atlas");
    log::warn!(
        "ward-atlas: no adapter matched '{want}', using {}",
        fb.get_info().name
    );
    fb
}

async fn run() {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/root".into());
    let font_path = std::env::var("HAPAX_WARD_ATLAS_FONT")
        .unwrap_or_else(|_| format!("{home}/.local/share/fonts/Px437_IBM_VGA_8x16.ttf"));
    let layout_path = default_layout_path(&home);
    let ward_sources = load_ward_sources(&layout_path);
    let data = std::fs::read(&font_path)
        .unwrap_or_else(|e| panic!("ward-atlas: read font {font_path}: {e}"));
    let font = Font::from_bytes(data, FontSettings::default()).expect("ward-atlas: parse font");
    let asc_px = font.horizontal_line_metrics(PX).unwrap().ascent;
    let lh_px = {
        let m = font.horizontal_line_metrics(PX).unwrap();
        m.ascent - m.descent + m.line_gap
    };

    let mut chars: Vec<char> = (0x20u8..=0x7e).map(|b| b as char).collect();
    chars.extend([
        '\u{2591}', '\u{2592}', '\u{2593}', '\u{2588}', '\u{00bb}', '\u{00ab}',
    ]);
    let (atlas_bytes, atlas_h, map, solid) = bake(&font, &chars, &[PX]);
    let instances = build_scene(&font, &map, solid, atlas_h, asc_px, lh_px);

    let real = std::env::var("HAPAX_WARD_ATLAS_REAL")
        .map(|v| v == "1")
        .unwrap_or(false);
    let output_paths = ward_atlas_output_paths(real);
    let fps: f32 = std::env::var("HAPAX_WARD_ATLAS_FPS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(2.0);
    let _ = std::fs::create_dir_all(SHM_DIR);

    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
        backends: wgpu::Backends::VULKAN,
        ..Default::default()
    });
    let adapter = pick_adapter(&instance);
    let (device, queue) = adapter
        .request_device(
            &wgpu::DeviceDescriptor {
                label: Some("screwm-ward-atlas"),
                required_features: wgpu::Features::empty(),
                required_limits: wgpu::Limits::default(),
                ..Default::default()
            },
            None,
        )
        .await
        .expect("ward-atlas: request_device");

    let mk = |w, h, f, u| {
        device.create_texture(&wgpu::TextureDescriptor {
            label: None,
            size: wgpu::Extent3d {
                width: w,
                height: h,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: f,
            usage: u,
            view_formats: &[],
        })
    };
    let up = |t: &wgpu::Texture, w, h, d: &[u8]| {
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: t,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            d,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(w),
                rows_per_image: Some(h),
            },
            wgpu::Extent3d {
                width: w,
                height: h,
                depth_or_array_layers: 1,
            },
        )
    };

    let rd_tex = mk(
        GW as u32,
        GH as u32,
        wgpu::TextureFormat::R8Unorm,
        wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
    );
    let atlas_tex = mk(
        ATLAS_W,
        atlas_h,
        wgpu::TextureFormat::R8Unorm,
        wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
    );
    up(&atlas_tex, ATLAS_W, atlas_h, &atlas_bytes);
    let out_tex = mk(
        AW,
        AH,
        TEX,
        wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
    );
    let out_view = out_tex.create_view(&Default::default());

    let lin = device.create_sampler(&wgpu::SamplerDescriptor {
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        ..Default::default()
    });
    let near = device.create_sampler(&wgpu::SamplerDescriptor::default());
    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: None,
        entries: &[
            wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                count: None,
            },
        ],
    });
    let bind = |t: &wgpu::Texture, s: &wgpu::Sampler| {
        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(
                        &t.create_view(&Default::default()),
                    ),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(s),
                },
            ],
        })
    };
    let sub_bind = bind(&rd_tex, &lin);
    let glyph_bind = bind(&atlas_tex, &near);
    let pl = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: None,
        bind_group_layouts: &[&bgl],
        push_constant_ranges: &[],
    });
    let external_gpus: Vec<ExternalWardGpu> = ward_sources
        .iter()
        .cloned()
        .enumerate()
        .filter(|(_, source)| !source.spec.direct_texture)
        .filter_map(|(idx, source)| ExternalWardGpu::new(&device, &bgl, &lin, source, idx))
        .collect();

    let ss = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: None,
        source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(SUB_SHADER)),
    });
    let sub_pipe = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: None,
        layout: Some(&pl),
        vertex: wgpu::VertexState {
            module: &ss,
            entry_point: Some("vs"),
            buffers: &[],
            compilation_options: Default::default(),
        },
        fragment: Some(wgpu::FragmentState {
            module: &ss,
            entry_point: Some("fs"),
            targets: &[Some(wgpu::ColorTargetState {
                format: TEX,
                blend: None,
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState {
            topology: wgpu::PrimitiveTopology::TriangleStrip,
            ..Default::default()
        },
        depth_stencil: None,
        multisample: Default::default(),
        multiview: None,
        cache: None,
    });

    let gs = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: None,
        source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(GLYPH_SHADER)),
    });
    let il = wgpu::VertexBufferLayout {
        array_stride: std::mem::size_of::<Inst>() as u64,
        step_mode: wgpu::VertexStepMode::Instance,
        attributes: &[
            wgpu::VertexAttribute {
                offset: 0,
                shader_location: 0,
                format: wgpu::VertexFormat::Float32x4,
            },
            wgpu::VertexAttribute {
                offset: 16,
                shader_location: 1,
                format: wgpu::VertexFormat::Float32x4,
            },
            wgpu::VertexAttribute {
                offset: 32,
                shader_location: 2,
                format: wgpu::VertexFormat::Float32x4,
            },
        ],
    };
    let glyph_pipe = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: None,
        layout: Some(&pl),
        vertex: wgpu::VertexState {
            module: &gs,
            entry_point: Some("vs"),
            buffers: &[il],
            compilation_options: Default::default(),
        },
        fragment: Some(wgpu::FragmentState {
            module: &gs,
            entry_point: Some("fs"),
            targets: &[Some(wgpu::ColorTargetState {
                format: TEX,
                blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState {
            topology: wgpu::PrimitiveTopology::TriangleStrip,
            ..Default::default()
        },
        depth_stencil: None,
        multisample: Default::default(),
        multiview: None,
        cache: None,
    });

    let img_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: None,
        source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(IMAGE_SHADER)),
    });
    let img_layout = wgpu::VertexBufferLayout {
        array_stride: std::mem::size_of::<ImageInst>() as u64,
        step_mode: wgpu::VertexStepMode::Instance,
        attributes: &[wgpu::VertexAttribute {
            offset: 0,
            shader_location: 0,
            format: wgpu::VertexFormat::Float32x4,
        }],
    };
    let image_pipe = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: None,
        layout: Some(&pl),
        vertex: wgpu::VertexState {
            module: &img_shader,
            entry_point: Some("vs"),
            buffers: &[img_layout],
            compilation_options: Default::default(),
        },
        fragment: Some(wgpu::FragmentState {
            module: &img_shader,
            entry_point: Some("fs"),
            targets: &[Some(wgpu::ColorTargetState {
                format: TEX,
                blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState {
            topology: wgpu::PrimitiveTopology::TriangleStrip,
            ..Default::default()
        },
        depth_stencil: None,
        multisample: Default::default(),
        multiview: None,
        cache: None,
    });

    use wgpu::util::DeviceExt;
    let inst_buf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: None,
        contents: bytemuck::cast_slice(&instances),
        usage: wgpu::BufferUsages::VERTEX,
    });
    let bpr = align_up(AW * 4, 256);
    let staging = device.create_buffer(&wgpu::BufferDescriptor {
        label: None,
        size: (bpr * AH) as u64,
        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });

    let mut rd = Rd::new();
    for _ in 0..90 {
        rd.step(); // warm to a developed spotted pattern
    }
    log::info!(
        "ward-atlas live: {} glyph instances, {} external RGBA source(s), layout={} @ {fps}fps -> {} (real={real})",
        instances.len(),
        external_gpus.len(),
        layout_path.display(),
        output_paths.bgra.display(),
    );

    let period = Duration::from_secs_f32(1.0 / fps.max(0.5));
    let mut frame_id = 0u64;
    loop {
        frame_id += 1;
        let t0 = Instant::now();
        rd.step();
        up(&rd_tex, GW as u32, GH as u32, &rd.r8());
        let mut external_statuses = BTreeMap::new();
        let mut present_external = Vec::new();
        for source in &external_gpus {
            let status = source.upload_status(&queue);
            if matches!(status, ExternalFrameRead::Ready(_)) {
                present_external.push(source);
            }
            external_statuses.insert(source.source.spec.id, status);
        }

        let mut enc = device.create_command_encoder(&Default::default());
        {
            let mut p = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: None,
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &out_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color {
                            r: 0.015,
                            g: 0.020,
                            b: 0.030,
                            a: 1.0,
                        }),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            p.set_pipeline(&sub_pipe);
            p.set_bind_group(0, &sub_bind, &[]);
            p.draw(0..4, 0..1);
            p.set_pipeline(&image_pipe);
            for source in present_external {
                p.set_bind_group(0, &source.bind_group, &[]);
                p.set_vertex_buffer(0, source.inst_buf.slice(..));
                p.draw(0..4, 0..1);
            }
            p.set_pipeline(&glyph_pipe);
            p.set_bind_group(0, &glyph_bind, &[]);
            p.set_vertex_buffer(0, inst_buf.slice(..));
            p.draw(0..4, 0..instances.len() as u32);
        }
        enc.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &out_tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &staging,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(bpr),
                    rows_per_image: Some(AH),
                },
            },
            wgpu::Extent3d {
                width: AW,
                height: AH,
                depth_or_array_layers: 1,
            },
        );
        queue.submit(Some(enc.finish()));

        let (tx, rx) = std::sync::mpsc::channel();
        staging.slice(..).map_async(wgpu::MapMode::Read, move |r| {
            let _ = tx.send(r);
        });
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

        let _ = atomic_write(&output_paths.bgra, &out);
        let metadata = build_metadata(
            frame_id,
            real,
            &output_paths,
            &layout_path,
            &ward_sources,
            &external_statuses,
        );
        if let Ok(bytes) = serde_json::to_vec(&metadata) {
            let _ = atomic_write(&output_paths.meta, &bytes);
        }

        if let Some(rem) = period.checked_sub(t0.elapsed()) {
            std::thread::sleep(rem);
        }
    }
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    pollster::block_on(run());
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn ward_manifest_matches_python_atlas_order_and_direct_texture_policy() {
        let ids: Vec<&str> = WARD_SPECS.iter().map(|spec| spec.id).collect();
        assert_eq!(
            ids,
            vec![
                "token_pole",
                "album",
                "stream_overlay",
                "aoa_oarb_state",
                "reverie",
                "activity_header",
                "stance_indicator",
                "gem",
                "grounding_provenance_ticker",
                "impingement_cascade",
                "recruitment_candidate_panel",
                "thinking_indicator",
                "pressure_gauge",
                "activity_variety_log",
                "whos_here",
                "durf",
                "coding_session_reveal",
                "m8-display",
                "steamdeck-display",
                "egress_footer",
                "programme_banner",
                "precedent_ticker",
                "programme_history",
                "research_instrument_dashboard",
                "cbip_signal_density",
                "chat_ambient",
                "chronicle_ticker",
                "programme_state",
                "polyend_instrument_reveal",
                "interactive_lore_query",
                "constructivist_research_poster",
                "tufte_density",
                "ascii_schematic",
                "segment_content",
                "m8_oscilloscope",
                "cbip_dual_ir_displacement",
            ]
        );
        assert_eq!(
            WARD_SPECS.iter().filter(|spec| spec.direct_texture).count(),
            1
        );
        assert!(WARD_SPECS
            .iter()
            .any(|spec| spec.id == "reverie" && spec.direct_texture));
    }

    #[test]
    fn layout_sources_project_external_rgba_into_ward_inventory() {
        let dir = tempdir().unwrap();
        let layout = dir.path().join("default.json");
        fs::write(
            &layout,
            r#"{
              "sources": [
                {
                  "id": "token_pole",
                  "kind": "cairo",
                  "params": {"natural_w": 300, "natural_h": 300}
                },
                {
                  "id": "reverie",
                  "kind": "external_rgba",
                  "params": {"natural_w": 640, "natural_h": 360, "shm_path": "/dev/shm/hapax-sources/reverie.rgba"}
                },
                {
                  "id": "m8-display",
                  "kind": "external_rgba",
                  "params": {"natural_w": 320, "natural_h": 240, "shm_path": "/dev/shm/hapax-sources/m8-display.rgba"}
                }
              ]
            }"#,
        )
        .unwrap();

        let sources = load_ward_sources(&layout);
        assert_eq!(sources.len(), 36);
        let aoa = sources
            .iter()
            .find(|source| source.spec.id == "aoa_oarb_state")
            .unwrap();
        assert!(aoa.external_rgba.is_none());
        assert!(aoa.natural_w.is_none());

        let reverie = sources
            .iter()
            .find(|source| source.spec.id == "reverie")
            .unwrap();
        assert!(reverie.spec.direct_texture);
        assert_eq!(
            reverie.external_rgba.as_deref(),
            Some(Path::new("/dev/shm/hapax-sources/reverie.rgba"))
        );

        let m8 = sources
            .iter()
            .find(|source| source.spec.id == "m8-display")
            .unwrap();
        assert!(!m8.spec.direct_texture);
        assert_eq!(m8.natural_w, Some(320));
        assert_eq!(m8.natural_h, Some(240));
        assert_eq!(
            m8.external_rgba.as_deref(),
            Some(Path::new("/dev/shm/hapax-sources/m8-display.rgba"))
        );
    }

    #[test]
    fn external_rgba_reader_requires_exact_tightly_packed_frame_size() {
        let dir = tempdir().unwrap();
        let frame = dir.path().join("source.rgba");
        fs::write(&frame, vec![7u8; 2 * 3 * 4]).unwrap();

        assert!(matches!(
            read_external_rgba_frame_status(&frame, 2, 3),
            ExternalFrameRead::Ready(bytes) if bytes.len() == 24
        ));
        assert!(matches!(
            read_external_rgba_frame_status(&frame, 2, 4),
            ExternalFrameRead::WrongSize {
                actual: 24,
                expected: 32
            }
        ));
        assert!(matches!(
            read_external_rgba_frame_status(&dir.path().join("missing.rgba"), 2, 3),
            ExternalFrameRead::Missing { .. }
        ));
    }

    #[test]
    fn output_paths_model_shadow_and_real_sidecars_without_env_flip() {
        let shadow = ward_atlas_output_paths(false);
        assert_eq!(shadow.bgra, Path::new(SHM_DIR).join(SHADOW_BGRA_NAME));
        assert_eq!(shadow.meta, Path::new(SHM_DIR).join(SHADOW_META_NAME));

        let real = ward_atlas_output_paths(true);
        assert_eq!(real.bgra, Path::new(SHM_DIR).join(REAL_BGRA_NAME));
        assert_eq!(real.meta, Path::new(SHM_DIR).join(REAL_META_NAME));
    }

    #[test]
    fn metadata_records_direct_texture_and_external_rgba_statuses() {
        let dir = tempdir().unwrap();
        let layout = dir.path().join("default.json");
        fs::write(
            &layout,
            r#"{
              "sources": [
                {
                  "id": "reverie",
                  "kind": "external_rgba",
                  "params": {"natural_w": 960, "natural_h": 540, "shm_path": "/dev/shm/hapax-sources/reverie.rgba"}
                },
                {
                  "id": "m8-display",
                  "kind": "external_rgba",
                  "params": {"natural_w": 320, "natural_h": 240, "shm_path": "/tmp/m8-display.rgba"}
                },
                {
                  "id": "steamdeck-display",
                  "kind": "external_rgba",
                  "params": {"natural_w": 640, "natural_h": 400, "shm_path": "/tmp/steamdeck-display.rgba"}
                }
              ]
            }"#,
        )
        .unwrap();
        let sources = load_ward_sources(&layout);
        let mut statuses = BTreeMap::new();
        statuses.insert("m8-display", ExternalFrameRead::Ready(Vec::new()));
        statuses.insert(
            "steamdeck-display",
            ExternalFrameRead::WrongSize {
                actual: 17,
                expected: 640 * 400 * 4,
            },
        );

        let paths = OutputPaths {
            bgra: dir.path().join("quake-live-ward-atlas.gpu.bgra"),
            meta: dir.path().join("quake-live-ward-atlas.gpu.json"),
        };
        let metadata = build_metadata(7, false, &paths, &layout, &sources, &statuses);

        assert_eq!(metadata.w, AW);
        assert_eq!(metadata.h, AH);
        assert_eq!(metadata.stride, AW * 4);
        assert_eq!(metadata.frame_id, 7);
        assert_eq!(metadata.ward_count, 36);
        assert!(!metadata.real);
        assert_eq!(metadata.output_path, paths.bgra.display().to_string());
        assert_eq!(metadata.meta_path, paths.meta.display().to_string());

        let reverie = metadata.wards.get("reverie").unwrap();
        assert_eq!(reverie.status, "direct-texture-owned");
        assert_eq!(reverie.texture.as_deref(), Some("w05"));
        assert_eq!(
            reverie.reason.as_deref(),
            Some("direct live texture owns this ward")
        );

        let m8 = metadata.wards.get("m8-display").unwrap();
        assert_eq!(m8.status, "rendered");
        assert_eq!(m8.source_width, Some(320));
        assert_eq!(m8.source_height, Some(240));
        assert_eq!(m8.expected_bytes, Some(320 * 240 * 4));

        let steamdeck = metadata.wards.get("steamdeck-display").unwrap();
        assert_eq!(steamdeck.status, "wrong-size");
        assert_eq!(steamdeck.actual_bytes, Some(17));
        assert_eq!(steamdeck.expected_bytes, Some(640 * 400 * 4));

        let aoa = metadata.wards.get("aoa_oarb_state").unwrap();
        assert_eq!(aoa.status, "fallback");
        assert_eq!(aoa.reason.as_deref(), Some("gpu ward IR not ported"));
    }

    #[test]
    fn atomic_write_uses_tmp_rename_path() {
        let dir = tempdir().unwrap();
        let sidecar = dir.path().join("quake-live-ward-atlas.gpu.json");
        let tmp = tmp_path_for(&sidecar);

        atomic_write(&sidecar, br#"{"ok":true}"#).unwrap();

        assert_eq!(fs::read_to_string(&sidecar).unwrap(), r#"{"ok":true}"#);
        assert!(!tmp.exists());
    }
}
