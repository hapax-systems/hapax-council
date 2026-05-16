use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

const OUTPUT_DIR: &str = "/dev/shm/hapax-visual";
const OUTPUT_FILE: &str = "/dev/shm/hapax-visual/frame.rgba";
const JPEG_FILE: &str = "/dev/shm/hapax-visual/frame.jpg";
const JPEG_TMP_FILE: &str = "/dev/shm/hapax-visual/frame.jpg.tmp";
const JPEG_QUALITY: i32 = 80;
const EGRESS_METRICS_FILE: &str = "/dev/shm/hapax-visual/egress.prom";
const EGRESS_METRICS_TMP_FILE: &str = "/dev/shm/hapax-visual/egress.prom.tmp";

/// Second RGBA output path, consumed by the studio compositor's
/// `ShmRgbaReader` as an `external_rgba` source. A sidecar JSON file at
/// `<path>.json` describes `{ w, h, stride, frame_id }` so the reader can
/// cache by `frame_id` and skip reprocessing identical frames.
///
/// Dormant until Phase D of the source-registry epic wires `ShmRgbaReader`
/// into `StudioCompositor.start()` — writing to this path is a no-op with
/// zero consumers until then.
const SIDE_OUTPUT_FILE: &str = "/dev/shm/hapax-sources/reverie.rgba";

/// Reads back frames from GPU to a staging buffer, then writes RGBA data to /dev/shm.
pub struct ShmOutput {
    staging_buffer: wgpu::Buffer,
    width: u32,
    height: u32,
    bytes_per_row: u32,
    /// Padded bytes per row (wgpu requires alignment to 256)
    padded_bytes_per_row: u32,
    enabled: bool,
    jpeg_compressor: Option<turbojpeg::Compressor>,
    /// Monotonic frame counter — used as `frame_id` in the side-output
    /// sidecar so the compositor's `ShmRgbaReader` can cache-by-id and
    /// skip reprocessing duplicate frames.
    frame_count: u64,
    /// Direct v4l2 output — writes RGBA frames to a loopback device.
    /// Initialized when HAPAX_IMAGINATION_V4L2_OUTPUT=1.
    v4l2: crate::v4l2_output::V4l2Output,
}

impl ShmOutput {
    pub fn new(device: &wgpu::Device, width: u32, height: u32) -> Self {
        fs::create_dir_all(OUTPUT_DIR).ok();

        let bytes_per_row = width * 4; // RGBA = 4 bytes/pixel
        let padded_bytes_per_row = align_up(bytes_per_row, 256);

        let staging_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("shm output staging"),
            size: (padded_bytes_per_row * height) as u64,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        let jpeg_compressor = turbojpeg::Compressor::new().ok().map(|mut c| {
            c.set_quality(JPEG_QUALITY).ok();
            c.set_subsamp(turbojpeg::Subsamp::Sub2x2).ok();
            c
        });

        let v4l2 = crate::v4l2_output::V4l2Output::new(width, height);

        Self {
            staging_buffer,
            width,
            height,
            bytes_per_row,
            padded_bytes_per_row,
            enabled: true,
            jpeg_compressor,
            frame_count: 0,
            v4l2,
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

    /// Convert RGBA pixels to JPEG, writing atomically to /dev/shm.
    /// The composite texture is Rgba8Unorm — bytes are in R,G,B,A order.
    fn write_jpeg(&mut self, rgba_data: &[u8]) {
        let compressor = match self.jpeg_compressor.as_mut() {
            Some(c) => c,
            None => return,
        };

        let image = turbojpeg::Image {
            pixels: rgba_data,
            width: self.width as usize,
            pitch: self.width as usize * 4,
            height: self.height as usize,
            format: turbojpeg::PixelFormat::RGBX,
        };

        if let Ok(jpeg_data) = compressor.compress_to_vec(image) {
            if let Ok(mut file) = fs::File::create(JPEG_TMP_FILE) {
                if file.write_all(&jpeg_data).is_ok() {
                    fs::rename(JPEG_TMP_FILE, JPEG_FILE).ok();
                }
            }
        }
    }

    /// Map the staging buffer and write to /dev/shm. Call after queue submit + device.poll.
    pub fn write_frame(&mut self, device: &wgpu::Device) {
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

        // Block until GPU readback completes. This runs every other frame
        // (~60ms cadence) so the stall is acceptable — typical readback is <2ms.
        device.poll(wgpu::Maintain::Wait);

        match rx.recv_timeout(std::time::Duration::from_millis(5)) {
            Ok(Ok(())) => {}
            _ => {
                // Readback failed — skip this frame's SHM write.
                self.staging_buffer.unmap();
                return;
            }
        }

        let data = slice.get_mapped_range();

        // Build clean pixel data (strip row padding if needed).
        // Always produce an owned Vec so we can drop the mapped range before
        // calling write_jpeg (which needs &mut self).
        let clean_data: Vec<u8> = if padded_bytes_per_row == bytes_per_row {
            data.to_vec()
        } else {
            let mut buf = Vec::with_capacity((bytes_per_row * height) as usize);
            for row in 0..height {
                let start = (row * padded_bytes_per_row) as usize;
                let end = start + bytes_per_row as usize;
                buf.extend_from_slice(&data[start..end]);
            }
            buf
        };

        // Release GPU mapping before further work
        drop(data);
        self.staging_buffer.unmap();

        // Write raw RGBA
        if let Ok(mut file) = fs::File::create(OUTPUT_FILE) {
            file.write_all(&clean_data).ok();
        }

        // Write JPEG
        self.write_jpeg(&clean_data);

        // Write the source-registry side output. Non-fatal on error —
        // reverie keeps rendering and the compositor's
        // compositor_source_frame_age_seconds metric catches chronic
        // staleness. Dormant in main until Phase D wires ShmRgbaReader.
        self.frame_count = self.frame_count.wrapping_add(1);

        // Write to v4l2 loopback (if enabled)
        self.v4l2.write_frame(&clean_data);

        let _ = write_side_output(
            Path::new(SIDE_OUTPUT_FILE),
            &clean_data,
            self.width,
            self.height,
            self.bytes_per_row,
            self.frame_count,
        );
        self.write_egress_metrics();
    }

    fn write_egress_metrics(&self) {
        let v4l2 = self.v4l2.metrics();
        let mut lines = vec![
            "# HELP hapax_imagination_output_frames_total 3D compositor frames written to the consumer-boundary SHM/JPEG output".to_string(),
            "# TYPE hapax_imagination_output_frames_total counter".to_string(),
            format!("hapax_imagination_output_frames_total {}", self.frame_count),
            "# HELP hapax_imagination_output_last_frame_seconds_ago Seconds since the 3D compositor last wrote the consumer-boundary output file".to_string(),
            "# TYPE hapax_imagination_output_last_frame_seconds_ago gauge".to_string(),
            "hapax_imagination_output_last_frame_seconds_ago 0".to_string(),
            "# HELP hapax_imagination_v4l2_output_enabled Whether direct v4l2 output is enabled in hapax-imagination".to_string(),
            "# TYPE hapax_imagination_v4l2_output_enabled gauge".to_string(),
            format!(
                "hapax_imagination_v4l2_output_enabled {}",
                if v4l2.enabled { 1 } else { 0 }
            ),
            "# HELP hapax_imagination_v4l2_write_frames_total Direct v4l2 frames written by hapax-imagination".to_string(),
            "# TYPE hapax_imagination_v4l2_write_frames_total counter".to_string(),
            format!("hapax_imagination_v4l2_write_frames_total {}", v4l2.write_count),
            "# HELP hapax_imagination_v4l2_write_bytes_total Direct v4l2 bytes written by hapax-imagination".to_string(),
            "# TYPE hapax_imagination_v4l2_write_bytes_total counter".to_string(),
            format!(
                "hapax_imagination_v4l2_write_bytes_total {}",
                v4l2.write_bytes_total
            ),
            "# HELP hapax_imagination_v4l2_write_errors_total Direct v4l2 write errors observed by hapax-imagination".to_string(),
            "# TYPE hapax_imagination_v4l2_write_errors_total counter".to_string(),
            format!("hapax_imagination_v4l2_write_errors_total {}", v4l2.error_count),
            "# HELP hapax_imagination_v4l2_reconnects_total Direct v4l2 reopen attempts by hapax-imagination".to_string(),
            "# TYPE hapax_imagination_v4l2_reconnects_total counter".to_string(),
            format!(
                "hapax_imagination_v4l2_reconnects_total {}",
                v4l2.reopen_count
            ),
        ];
        if let Some(age) = v4l2.last_write_age_seconds {
            lines.push(
                "# HELP hapax_imagination_v4l2_last_frame_seconds_ago Seconds since hapax-imagination last wrote a direct v4l2 frame".to_string(),
            );
            lines.push("# TYPE hapax_imagination_v4l2_last_frame_seconds_ago gauge".to_string());
            lines.push(format!(
                "hapax_imagination_v4l2_last_frame_seconds_ago {}",
                age
            ));
        }
        lines.push(String::new());

        if fs::write(EGRESS_METRICS_TMP_FILE, lines.join("\n")).is_ok() {
            let _ = fs::rename(EGRESS_METRICS_TMP_FILE, EGRESS_METRICS_FILE);
        }
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

/// Sidecar path for a given RGBA shm output path — appends `.json`, so
/// `reverie.rgba` → `reverie.rgba.json`. Matches the layout expected by
/// `agents/studio_compositor/shm_rgba_reader.py::ShmRgbaReader`.
fn sidecar_path(rgba_path: &Path) -> PathBuf {
    let mut as_os = rgba_path.as_os_str().to_os_string();
    as_os.push(".json");
    PathBuf::from(as_os)
}

/// Write pixel data and its metadata sidecar atomically.
///
/// The compositor-facing consumer is `agents/studio_compositor/shm_rgba_reader.py`
/// which loads the file as `cairo.ImageSurface(FORMAT_ARGB32)` — little-endian
/// BGRA in memory. The composite texture is `Rgba8Unorm`, so the GPU readback
/// is in R,G,B,A byte order. Without a channel swap here, red bytes display as
/// blue in the compositor (observed 2026-04-17 — reverie quadrant rendering
/// solid blue instead of the shader output). Swap R↔B before writing.
///
/// Both files are written via `tmp + rename` so a mid-write crash cannot
/// leave a partial frame visible to a reader: the rename is atomic on
/// tmpfs. The sidecar carries `{ w, h, stride, frame_id }`; the reader
/// caches by `frame_id` so a stale frame is never reprocessed.
pub fn write_side_output(
    path: &Path,
    pixels: &[u8],
    w: u32,
    h: u32,
    stride: u32,
    frame_id: u64,
) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }

    let mut bgra = pixels.to_vec();
    for px in bgra.chunks_exact_mut(4) {
        px.swap(0, 2);
    }

    let mut rgba_tmp_os = path.as_os_str().to_os_string();
    rgba_tmp_os.push(".tmp");
    let rgba_tmp = PathBuf::from(rgba_tmp_os);
    fs::write(&rgba_tmp, &bgra)?;
    fs::rename(&rgba_tmp, path)?;

    let sidecar = sidecar_path(path);
    let mut sidecar_tmp_os = sidecar.as_os_str().to_os_string();
    sidecar_tmp_os.push(".tmp");
    let sidecar_tmp = PathBuf::from(sidecar_tmp_os);
    let meta = serde_json::json!({
        "w": w,
        "h": h,
        "stride": stride,
        "frame_id": frame_id,
    });
    fs::write(&sidecar_tmp, meta.to_string())?;
    fs::rename(&sidecar_tmp, &sidecar)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn write_side_output_creates_rgba_and_sidecar() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("reverie.rgba");
        let pixels = vec![0xFFu8; 4 * 4 * 4];

        write_side_output(&path, &pixels, 4, 4, 16, 42).unwrap();

        assert!(path.exists(), "rgba file should exist");
        let written = fs::read(&path).unwrap();
        assert_eq!(written, pixels);

        let sidecar = sidecar_path(&path);
        assert!(sidecar.exists(), "sidecar should exist at {:?}", sidecar);
        let meta: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&sidecar).unwrap()).unwrap();
        assert_eq!(meta["w"], 4);
        assert_eq!(meta["h"], 4);
        assert_eq!(meta["stride"], 16);
        assert_eq!(meta["frame_id"], 42);
    }

    #[test]
    fn write_side_output_swaps_rgba_to_bgra() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("reverie.rgba");
        let rgba_red = vec![0xFF, 0x00, 0x00, 0xFF];
        write_side_output(&path, &rgba_red, 1, 1, 4, 1).unwrap();
        let written = fs::read(&path).unwrap();
        assert_eq!(written, vec![0x00, 0x00, 0xFF, 0xFF]);
    }

    #[test]
    fn write_side_output_is_atomic_via_rename() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("reverie.rgba");
        let pixels = vec![0x11u8; 64];

        write_side_output(&path, &pixels, 4, 4, 16, 1).unwrap();
        let pixels_b = vec![0x22u8; 64];
        write_side_output(&path, &pixels_b, 4, 4, 16, 2).unwrap();

        assert_eq!(fs::read(&path).unwrap(), pixels_b);
        let meta: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(sidecar_path(&path)).unwrap()).unwrap();
        assert_eq!(meta["frame_id"], 2);

        let leftovers: Vec<_> = fs::read_dir(dir.path())
            .unwrap()
            .map(|e| e.unwrap().file_name().into_string().unwrap())
            .filter(|n| n.ends_with(".tmp"))
            .collect();
        assert!(
            leftovers.is_empty(),
            "tmp files should be renamed: {:?}",
            leftovers
        );
    }

    #[test]
    fn write_side_output_creates_parent_dir() {
        let dir = tempdir().unwrap();
        let nested = dir
            .path()
            .join("nested")
            .join("deeper")
            .join("reverie.rgba");
        let pixels = vec![0u8; 16];

        write_side_output(&nested, &pixels, 2, 2, 8, 7).unwrap();

        assert!(nested.exists());
        assert!(sidecar_path(&nested).exists());
    }
}
