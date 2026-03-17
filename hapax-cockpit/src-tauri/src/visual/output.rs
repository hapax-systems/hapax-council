use std::fs;
use std::io::Write;

const OUTPUT_DIR: &str = "/dev/shm/hapax-visual";
const OUTPUT_FILE: &str = "/dev/shm/hapax-visual/frame.bgra";

/// Reads back frames from GPU to a staging buffer, then writes BGRA data to /dev/shm.
pub struct ShmOutput {
    staging_buffer: wgpu::Buffer,
    width: u32,
    height: u32,
    bytes_per_row: u32,
    /// Padded bytes per row (wgpu requires alignment to 256)
    padded_bytes_per_row: u32,
    enabled: bool,
}

impl ShmOutput {
    pub fn new(device: &wgpu::Device, width: u32, height: u32) -> Self {
        fs::create_dir_all(OUTPUT_DIR).ok();

        let bytes_per_row = width * 4; // BGRA = 4 bytes/pixel
        let padded_bytes_per_row = align_up(bytes_per_row, 256);

        let staging_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("shm output staging"),
            size: (padded_bytes_per_row * height) as u64,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        Self {
            staging_buffer,
            width,
            height,
            bytes_per_row,
            padded_bytes_per_row,
            enabled: true,
        }
    }

    /// Copy the composite texture to the staging buffer.
    /// Call during command encoding (before submit).
    pub fn copy_to_staging(
        &self,
        encoder: &mut wgpu::CommandEncoder,
        source_texture: &wgpu::Texture,
    ) {
        if !self.enabled {
            return;
        }

        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: source_texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &self.staging_buffer,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(self.padded_bytes_per_row),
                    rows_per_image: Some(self.height),
                },
            },
            wgpu::Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
        );
    }

    /// Map the staging buffer and write to /dev/shm. Call after queue submit.
    /// This is async — uses buffer mapping callback.
    pub fn write_frame(&self) {
        if !self.enabled {
            return;
        }

        let slice = self.staging_buffer.slice(..);
        let height = self.height;
        let bytes_per_row = self.bytes_per_row;
        let padded_bytes_per_row = self.padded_bytes_per_row;

        // Use a simple channel to wait for the map
        let (tx, rx) = std::sync::mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |result| {
            tx.send(result).ok();
        });

        // Poll until mapping completes (non-blocking in a real app, but we want the data now)
        // In practice the GPU has already finished since we submitted and presented.
        match rx.recv_timeout(std::time::Duration::from_millis(5)) {
            Ok(Ok(())) => {}
            _ => {
                // Mapping didn't complete in time, skip this frame
                return;
            }
        }

        let data = slice.get_mapped_range();

        // Write BGRA data, stripping row padding if needed
        if padded_bytes_per_row == bytes_per_row {
            // No padding — write directly
            if let Ok(mut file) = fs::File::create(OUTPUT_FILE) {
                file.write_all(&data).ok();
            }
        } else {
            // Strip padding
            let mut buf = Vec::with_capacity((bytes_per_row * height) as usize);
            for row in 0..height {
                let start = (row * padded_bytes_per_row) as usize;
                let end = start + bytes_per_row as usize;
                buf.extend_from_slice(&data[start..end]);
            }
            if let Ok(mut file) = fs::File::create(OUTPUT_FILE) {
                file.write_all(&buf).ok();
            }
        }

        drop(data);
        self.staging_buffer.unmap();
    }

    pub fn resize(&mut self, device: &wgpu::Device, width: u32, height: u32) {
        self.width = width;
        self.height = height;
        self.bytes_per_row = width * 4;
        self.padded_bytes_per_row = align_up(self.bytes_per_row, 256);

        self.staging_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("shm output staging"),
            size: (self.padded_bytes_per_row * height) as u64,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
    }
}

fn align_up(value: u32, alignment: u32) -> u32 {
    (value + alignment - 1) & !(alignment - 1)
}
