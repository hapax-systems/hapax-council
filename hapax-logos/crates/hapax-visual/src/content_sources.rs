//! Content source manager — scans shm for arbitrary RGBA/text content sources,
//! manages GPU textures, composites onto ground field.

use serde::Deserialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Instant;

const SOURCES_DIR: &str = "/dev/shm/hapax-imagination/sources";
const DEFAULT_TTL_MS: u64 = 5000;
const MAX_SOURCES: usize = 16;

#[derive(Debug, Clone, Deserialize)]
pub struct SourceManifest {
    pub source_id: String,
    pub content_type: String,
    #[serde(default = "default_width")]
    pub width: u32,
    #[serde(default = "default_height")]
    pub height: u32,
    #[serde(default)]
    pub text: String,
    #[serde(default = "default_font_weight")]
    pub font_weight: u32,
    #[serde(default = "default_layer")]
    pub layer: u32,
    #[serde(default = "default_blend_mode")]
    pub blend_mode: String,
    #[serde(default = "default_opacity")]
    pub opacity: f32,
    #[serde(default)]
    pub z_order: i32,
    #[serde(default = "default_ttl")]
    pub ttl_ms: u64,
    #[serde(default)]
    pub tags: Vec<String>,
}

fn default_width() -> u32 { 1920 }
fn default_height() -> u32 { 1080 }
fn default_font_weight() -> u32 { 400 }
fn default_layer() -> u32 { 1 }
fn default_blend_mode() -> String { "screen".to_string() }
fn default_opacity() -> f32 { 1.0 }
fn default_ttl() -> u64 { DEFAULT_TTL_MS }

#[derive(Debug)]
struct ContentSource {
    manifest: SourceManifest,
    texture: wgpu::Texture,
    view: wgpu::TextureView,
    current_opacity: f32,
    target_opacity: f32,
    last_refresh: Instant,
    frame_path: PathBuf,
}

pub struct ContentSourceManager {
    sources: HashMap<String, ContentSource>,
    sources_dir: PathBuf,
    last_scan: Instant,
    scan_interval_ms: u64,
    placeholder_view: wgpu::TextureView,
    _placeholder_texture: wgpu::Texture,
}

impl ContentSourceManager {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue) -> Self {
        let (placeholder_texture, placeholder_view) = Self::create_placeholder(device, queue);
        Self {
            sources: HashMap::new(),
            sources_dir: PathBuf::from(SOURCES_DIR),
            last_scan: Instant::now(),
            scan_interval_ms: 100,
            placeholder_view,
            _placeholder_texture: placeholder_texture,
        }
    }

    fn create_placeholder(device: &wgpu::Device, queue: &wgpu::Queue) -> (wgpu::Texture, wgpu::TextureView) {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("content_source_placeholder"),
            size: wgpu::Extent3d { width: 1, height: 1, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &texture, mip_level: 0,
                origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All,
            },
            &[0u8, 0, 0, 0],
            wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(4), rows_per_image: Some(1) },
            wgpu::Extent3d { width: 1, height: 1, depth_or_array_layers: 1 },
        );
        let view = texture.create_view(&Default::default());
        (texture, view)
    }

    pub fn scan(&mut self, device: &wgpu::Device, queue: &wgpu::Queue) {
        if self.last_scan.elapsed().as_millis() < self.scan_interval_ms as u128 {
            return;
        }
        self.last_scan = Instant::now();

        let entries = match std::fs::read_dir(&self.sources_dir) {
            Ok(e) => e,
            Err(_) => return,
        };

        let mut seen = Vec::new();
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_dir() { continue; }
            let source_id = match path.file_name().and_then(|n| n.to_str()) {
                Some(n) => n.to_string(),
                None => continue,
            };
            if self.sources.len() >= MAX_SOURCES && !self.sources.contains_key(&source_id) {
                continue;
            }

            let manifest_path = path.join("manifest.json");
            let manifest = match Self::read_manifest(&manifest_path) {
                Some(m) => m,
                None => continue,
            };

            let frame_path = path.join("frame.rgba");

            if manifest.content_type == "rgba" {
                self.update_rgba_source(device, queue, &source_id, manifest, &frame_path);
            }

            seen.push(source_id);
        }

        // Expire sources not seen or past TTL, clean up shm directories
        let now = Instant::now();
        let sources_dir = self.sources_dir.clone();
        self.sources.retain(|id, src| {
            let keep = seen.contains(id)
                && (src.manifest.ttl_ms == 0
                    || now.duration_since(src.last_refresh).as_millis()
                        <= src.manifest.ttl_ms as u128);
            if !keep {
                let dir = sources_dir.join(id);
                if dir.exists() {
                    let _ = std::fs::remove_dir_all(&dir);
                }
            }
            keep
        });

        // Also clean up orphaned directories not tracked by the manager
        // (e.g., from previous runs or sources that expired before being loaded)
        for id in &seen {
            if !self.sources.contains_key(id.as_str()) {
                let manifest_path = self.sources_dir.join(id).join("manifest.json");
                if let Some(manifest) = Self::read_manifest(&manifest_path) {
                    if manifest.ttl_ms > 0 {
                        // Check file age as proxy for staleness
                        if let Ok(metadata) = std::fs::metadata(&manifest_path) {
                            if let Ok(modified) = metadata.modified() {
                                if modified.elapsed().unwrap_or_default().as_millis() > manifest.ttl_ms as u128 {
                                    let dir = self.sources_dir.join(id);
                                    let _ = std::fs::remove_dir_all(&dir);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    fn read_manifest(path: &Path) -> Option<SourceManifest> {
        let data = std::fs::read_to_string(path).ok()?;
        serde_json::from_str(&data).ok()
    }

    fn update_rgba_source(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        source_id: &str,
        manifest: SourceManifest,
        frame_path: &Path,
    ) {
        let expected_size = (manifest.width * manifest.height * 4) as u64;
        let metadata = match std::fs::metadata(frame_path) {
            Ok(m) => m,
            Err(_) => return,
        };
        if metadata.len() != expected_size { return; }

        let pixels = match std::fs::read(frame_path) {
            Ok(p) => p,
            Err(_) => return,
        };

        let target_opacity = manifest.opacity;

        if let Some(source) = self.sources.get_mut(source_id) {
            if source.manifest.width != manifest.width || source.manifest.height != manifest.height {
                let (tex, view) = Self::create_source_texture(device, manifest.width, manifest.height, source_id);
                source.texture = tex;
                source.view = view;
            }
            Self::upload_rgba(queue, &source.texture, &pixels, manifest.width, manifest.height);
            source.manifest = manifest;
            source.target_opacity = target_opacity;
            source.last_refresh = Instant::now();
            source.frame_path = frame_path.to_path_buf();
        } else {
            let (texture, view) = Self::create_source_texture(device, manifest.width, manifest.height, source_id);
            Self::upload_rgba(queue, &texture, &pixels, manifest.width, manifest.height);
            self.sources.insert(source_id.to_string(), ContentSource {
                manifest,
                texture,
                view,
                current_opacity: 0.0,
                target_opacity,
                last_refresh: Instant::now(),
                frame_path: frame_path.to_path_buf(),
            });
        }
    }

    fn create_source_texture(device: &wgpu::Device, width: u32, height: u32, label: &str) -> (wgpu::Texture, wgpu::TextureView) {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(label),
            size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        (texture, view)
    }

    fn upload_rgba(queue: &wgpu::Queue, texture: &wgpu::Texture, pixels: &[u8], width: u32, height: u32) {
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture, mip_level: 0,
                origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All,
            },
            pixels,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(4 * width),
                rows_per_image: Some(height),
            },
            wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
        );
    }

    pub fn tick_fades(&mut self, dt: f32) {
        let fade_rate = 2.0f32;
        for source in self.sources.values_mut() {
            let diff = source.target_opacity - source.current_opacity;
            let step = fade_rate * dt;
            if diff.abs() < step {
                source.current_opacity = source.target_opacity;
            } else {
                source.current_opacity += diff.signum() * step;
            }
        }
    }

    pub fn active_sources(&self) -> Vec<(&str, &wgpu::TextureView, f32)> {
        let mut result: Vec<_> = self.sources.iter()
            .filter(|(_, s)| s.current_opacity > 0.001)
            .map(|(id, s)| (id.as_str(), &s.view, s.current_opacity))
            .collect();
        result.sort_by_key(|(id, _, _)| {
            self.sources.get(*id).map(|s| s.manifest.z_order).unwrap_or(0)
        });
        result
    }

    pub fn placeholder_view(&self) -> &wgpu::TextureView {
        &self.placeholder_view
    }

    pub fn has_active_sources(&self) -> bool {
        self.sources.values().any(|s| s.current_opacity > 0.001)
    }

    pub fn source_count(&self) -> usize {
        self.sources.len()
    }

    /// Get texture view for a content slot (maps active sources to slot indices by z_order).
    pub fn slot_view(&self, index: usize) -> &wgpu::TextureView {
        let mut sorted: Vec<&ContentSource> = self.sources.values()
            .filter(|s| s.current_opacity > 0.001)
            .collect();
        sorted.sort_by_key(|s| s.manifest.z_order);
        if let Some(source) = sorted.get(index) {
            &source.view
        } else {
            &self.placeholder_view
        }
    }

    /// Get opacities for up to 4 content slots.
    pub fn slot_opacities(&self) -> [f32; 4] {
        let mut sorted: Vec<&ContentSource> = self.sources.values()
            .filter(|s| s.current_opacity > 0.001)
            .collect();
        sorted.sort_by_key(|s| s.manifest.z_order);
        let mut opacities = [0.0f32; 4];
        for (i, source) in sorted.iter().take(4).enumerate() {
            opacities[i] = source.current_opacity;
        }
        opacities
    }
}
