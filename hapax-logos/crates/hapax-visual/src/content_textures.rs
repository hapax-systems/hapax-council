//! Content texture manager — loads JPEG content from shm, manages 4 texture slots
//! with per-frame fade animation.

use serde::Deserialize;
use std::path::Path;
use std::time::Instant;

const MAX_SLOTS: usize = 4;
const MANIFEST_PATH: &str = "/dev/shm/hapax-imagination/content/active/slots.json";
const TEXTURE_WIDTH: u32 = 1920;
const TEXTURE_HEIGHT: u32 = 1080;
const FADE_RATE: f32 = 2.0;

#[derive(Debug, Deserialize)]
struct SlotManifest {
    fragment_id: String,
    slots: Vec<ManifestSlot>,
    #[serde(default)]
    continuation: bool,
}

#[derive(Debug, Deserialize)]
struct ManifestSlot {
    index: usize,
    path: String,
    #[serde(default)]
    salience: f32,
}

struct SlotState {
    active: bool,
    opacity: f32,
    target_opacity: f32,
    path: String,
}

impl Default for SlotState {
    fn default() -> Self {
        Self {
            active: false,
            opacity: 0.0,
            target_opacity: 0.0,
            path: String::new(),
        }
    }
}

pub struct ContentTextureManager {
    textures: [wgpu::Texture; MAX_SLOTS],
    views: [wgpu::TextureView; MAX_SLOTS],
    placeholder_view: wgpu::TextureView,
    _placeholder_texture: wgpu::Texture,
    slots: [SlotState; MAX_SLOTS],
    current_fragment_id: String,
    last_poll: Instant,
    jpeg_decompressor: Option<turbojpeg::Decompressor>,
}

impl ContentTextureManager {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue) -> Self {
        let mut textures = Vec::new();
        let mut views = Vec::new();

        for i in 0..MAX_SLOTS {
            let tex = Self::create_slot_texture(device, i);
            let view = tex.create_view(&Default::default());
            textures.push(tex);
            views.push(view);
        }

        let (placeholder_texture, placeholder_view) = Self::create_placeholder(device, queue);

        Self {
            textures: textures.try_into().unwrap_or_else(|_| unreachable!()),
            views: views.try_into().unwrap_or_else(|_| unreachable!()),
            placeholder_view,
            _placeholder_texture: placeholder_texture,
            slots: Default::default(),
            current_fragment_id: String::new(),
            last_poll: Instant::now(),
            jpeg_decompressor: turbojpeg::Decompressor::new().ok(),
        }
    }

    fn create_slot_texture(device: &wgpu::Device, index: usize) -> wgpu::Texture {
        device.create_texture(&wgpu::TextureDescriptor {
            label: Some(&format!("content_slot_{}", index)),
            size: wgpu::Extent3d {
                width: TEXTURE_WIDTH,
                height: TEXTURE_HEIGHT,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        })
    }

    fn create_placeholder(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
    ) -> (wgpu::Texture, wgpu::TextureView) {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("content_placeholder"),
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
            &[0u8, 0, 0, 255],
            wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(4), rows_per_image: Some(1) },
            wgpu::Extent3d { width: 1, height: 1, depth_or_array_layers: 1 },
        );
        let view = texture.create_view(&Default::default());
        (texture, view)
    }

    /// Poll manifest for changes (call at ~500ms cadence).
    pub fn poll(&mut self, queue: &wgpu::Queue) {
        if self.last_poll.elapsed().as_millis() < 500 {
            return;
        }
        self.last_poll = Instant::now();

        let manifest = match Self::read_manifest() {
            Some(m) => m,
            None => return,
        };

        if manifest.fragment_id == self.current_fragment_id {
            return;
        }

        if !manifest.continuation {
            for slot in &mut self.slots {
                slot.target_opacity = 0.0;
            }
        }

        for ms in &manifest.slots {
            if ms.index >= MAX_SLOTS { continue; }
            if ms.path != self.slots[ms.index].path {
                self.upload_jpeg(queue, ms.index, &ms.path);
            }
            self.slots[ms.index].active = true;
            self.slots[ms.index].target_opacity = ms.salience.clamp(0.0, 1.0);
            self.slots[ms.index].path = ms.path.clone();
        }

        self.current_fragment_id = manifest.fragment_id;
    }

    /// Advance fade animations (call every frame).
    pub fn tick_fades(&mut self, dt: f32) {
        for slot in &mut self.slots {
            if !slot.active && slot.opacity <= 0.001 { continue; }
            let diff = slot.target_opacity - slot.opacity;
            let step = FADE_RATE * dt;
            if diff.abs() < step {
                slot.opacity = slot.target_opacity;
            } else {
                slot.opacity += diff.signum() * step;
            }
            if slot.opacity <= 0.001 && slot.target_opacity <= 0.001 {
                slot.active = false;
                slot.opacity = 0.0;
            }
        }
    }

    /// Get current slot opacities for uniform buffer.
    pub fn slot_opacities(&self) -> [f32; 4] {
        [self.slots[0].opacity, self.slots[1].opacity, self.slots[2].opacity, self.slots[3].opacity]
    }

    /// Get texture view for a slot (placeholder if inactive).
    pub fn slot_view(&self, index: usize) -> &wgpu::TextureView {
        if index < MAX_SLOTS && self.slots[index].active {
            &self.views[index]
        } else {
            &self.placeholder_view
        }
    }

    fn upload_jpeg(&mut self, queue: &wgpu::Queue, slot: usize, path: &str) {
        let Some(decompressor) = &mut self.jpeg_decompressor else { return; };
        let data = match std::fs::read(path) { Ok(d) => d, Err(_) => return };
        let header = match decompressor.read_header(&data) { Ok(h) => h, Err(_) => return };
        let w = header.width as u32;
        let h = header.height as u32;
        let mut pixels = vec![0u8; (w * h * 4) as usize];
        let image = turbojpeg::Image {
            pixels: pixels.as_mut_slice(),
            width: w as usize, height: h as usize,
            pitch: (w * 4) as usize,
            format: turbojpeg::PixelFormat::RGBA,
        };
        if decompressor.decompress(&data, image).is_err() { return; }

        let upload_w = w.min(TEXTURE_WIDTH);
        let upload_h = h.min(TEXTURE_HEIGHT);
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &self.textures[slot], mip_level: 0,
                origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All,
            },
            &pixels,
            wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(4 * w), rows_per_image: Some(h) },
            wgpu::Extent3d { width: upload_w, height: upload_h, depth_or_array_layers: 1 },
        );
    }

    fn read_manifest() -> Option<SlotManifest> {
        let data = std::fs::read_to_string(MANIFEST_PATH).ok()?;
        serde_json::from_str(&data).ok()
    }
}
