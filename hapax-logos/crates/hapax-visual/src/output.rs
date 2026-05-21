use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

const OUTPUT_DIR: &str = "/dev/shm/hapax-visual";
const OUTPUT_FILE: &str = "/dev/shm/hapax-visual/frame.rgba";
const JPEG_FILE: &str = "/dev/shm/hapax-visual/frame.jpg";
const JPEG_TMP_FILE: &str = "/dev/shm/hapax-visual/frame.jpg.tmp";
const JPEG_QUALITY: i32 = 80;
const EGRESS_METRICS_FILE: &str = "/dev/shm/hapax-visual/egress.prom";
const EGRESS_METRICS_TMP_FILE: &str = "/dev/shm/hapax-visual/egress.prom.tmp";
const DEFAULT_DIAGNOSTIC_EVERY_N: u64 = 1;

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
    clean_data: Vec<u8>,
    jpeg_every_n: u64,
    side_output_every_n: u64,
    timings: OutputTimings,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
struct OutputTimings {
    readback_micros: u64,
    copy_micros: u64,
    raw_rgba_write_micros: u64,
    jpeg_write_micros: u64,
    v4l2_micros: u64,
    side_output_micros: u64,
    metrics_write_micros: u64,
    total_micros: u64,
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
        let clean_data = Vec::with_capacity((bytes_per_row * height) as usize);
        let jpeg_every_n = env_every_n("HAPAX_IMAGINATION_JPEG_EVERY_N");
        let side_output_every_n = env_every_n("HAPAX_IMAGINATION_SIDE_OUTPUT_EVERY_N");

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
            clean_data,
            jpeg_every_n,
            side_output_every_n,
            timings: OutputTimings::default(),
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
    fn write_jpeg(
        jpeg_compressor: &mut Option<turbojpeg::Compressor>,
        width: u32,
        height: u32,
        rgba_data: &[u8],
    ) {
        let compressor = match jpeg_compressor.as_mut() {
            Some(c) => c,
            None => return,
        };

        let image = turbojpeg::Image {
            pixels: rgba_data,
            width: width as usize,
            pitch: width as usize * 4,
            height: height as usize,
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

        let total_start = Instant::now();
        let mut timings = OutputTimings::default();
        let slice = self.staging_buffer.slice(..);
        let height = self.height;
        let bytes_per_row = self.bytes_per_row;
        let padded_bytes_per_row = self.padded_bytes_per_row;

        // Use a simple channel to wait for the map
        let (tx, rx) = std::sync::mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |result| {
            tx.send(result).ok();
        });

        // Block until GPU readback completes. The active direct-v4l2 3D
        // surface calls this every rendered frame to satisfy the 30fps
        // consumer-boundary contract; typical readback is <2ms.
        let readback_start = Instant::now();
        device.poll(wgpu::Maintain::Wait);

        match rx.recv_timeout(std::time::Duration::from_millis(5)) {
            Ok(Ok(())) => {}
            _ => {
                // Readback failed — skip this frame's SHM write.
                self.staging_buffer.unmap();
                return;
            }
        }
        timings.readback_micros = elapsed_micros(readback_start);

        let data = slice.get_mapped_range();

        // Build clean pixel data (strip row padding if needed).
        // Reuse the allocation across frames; at 1080p this avoids allocating
        // a fresh 8 MiB Vec every consumer-boundary tick.
        let copy_start = Instant::now();
        self.clean_data.clear();
        if padded_bytes_per_row == bytes_per_row {
            self.clean_data.extend_from_slice(&data);
        } else {
            for row in 0..height {
                let start = (row * padded_bytes_per_row) as usize;
                let end = start + bytes_per_row as usize;
                self.clean_data.extend_from_slice(&data[start..end]);
            }
        };
        timings.copy_micros = elapsed_micros(copy_start);

        // Release GPU mapping before further work
        drop(data);
        self.staging_buffer.unmap();

        // Write raw RGBA
        let raw_start = Instant::now();
        if let Ok(mut file) = fs::File::create(OUTPUT_FILE) {
            file.write_all(&self.clean_data).ok();
        }
        timings.raw_rgba_write_micros = elapsed_micros(raw_start);

        self.frame_count = self.frame_count.wrapping_add(1);

        if should_publish_every(self.frame_count, self.jpeg_every_n) {
            let jpeg_start = Instant::now();
            Self::write_jpeg(
                &mut self.jpeg_compressor,
                self.width,
                self.height,
                &self.clean_data,
            );
            timings.jpeg_write_micros = elapsed_micros(jpeg_start);
        }

        // Write to v4l2 loopback (if enabled)
        let v4l2_start = Instant::now();
        self.v4l2.write_frame(&self.clean_data);
        timings.v4l2_micros = elapsed_micros(v4l2_start);

        // Write the source-registry side output. Non-fatal on error —
        // reverie keeps rendering and the compositor's
        // compositor_source_frame_age_seconds metric catches chronic
        // staleness. Dormant in main until Phase D wires ShmRgbaReader.
        if should_publish_every(self.frame_count, self.side_output_every_n) {
            let side_start = Instant::now();
            let _ = write_side_output(
                Path::new(SIDE_OUTPUT_FILE),
                &self.clean_data,
                self.width,
                self.height,
                self.bytes_per_row,
                self.frame_count,
            );
            timings.side_output_micros = elapsed_micros(side_start);
        }

        timings.total_micros = elapsed_micros(total_start);
        // The metrics write duration is only known after writing the metrics
        // file, so publish the previous frame's observed metrics-write cost.
        timings.metrics_write_micros = self.timings.metrics_write_micros;
        self.timings = timings;

        let metrics_start = Instant::now();
        self.write_egress_metrics();
        self.timings.metrics_write_micros = elapsed_micros(metrics_start);
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
            "# HELP hapax_imagination_output_stage_duration_micros Last observed output-stage duration by stage".to_string(),
            "# TYPE hapax_imagination_output_stage_duration_micros gauge".to_string(),
            format!(
                "hapax_imagination_output_stage_duration_micros{{stage=\"readback\"}} {}",
                self.timings.readback_micros
            ),
            format!(
                "hapax_imagination_output_stage_duration_micros{{stage=\"copy\"}} {}",
                self.timings.copy_micros
            ),
            format!(
                "hapax_imagination_output_stage_duration_micros{{stage=\"raw_rgba_write\"}} {}",
                self.timings.raw_rgba_write_micros
            ),
            format!(
                "hapax_imagination_output_stage_duration_micros{{stage=\"jpeg_write\"}} {}",
                self.timings.jpeg_write_micros
            ),
            format!(
                "hapax_imagination_output_stage_duration_micros{{stage=\"v4l2\"}} {}",
                self.timings.v4l2_micros
            ),
            format!(
                "hapax_imagination_output_stage_duration_micros{{stage=\"side_output\"}} {}",
                self.timings.side_output_micros
            ),
            format!(
                "hapax_imagination_output_stage_duration_micros{{stage=\"metrics_write\"}} {}",
                self.timings.metrics_write_micros
            ),
            format!(
                "hapax_imagination_output_stage_duration_micros{{stage=\"total\"}} {}",
                self.timings.total_micros
            ),
            "# HELP hapax_imagination_v4l2_stage_duration_micros Last observed direct V4L2 stage duration".to_string(),
            "# TYPE hapax_imagination_v4l2_stage_duration_micros gauge".to_string(),
            format!(
                "hapax_imagination_v4l2_stage_duration_micros{{stage=\"convert\"}} {}",
                v4l2.last_conversion_micros
            ),
            format!(
                "hapax_imagination_v4l2_stage_duration_micros{{stage=\"write_syscall\"}} {}",
                v4l2.last_write_syscall_micros
            ),
            format!(
                "hapax_imagination_v4l2_stage_duration_micros{{stage=\"total\"}} {}",
                v4l2.last_frame_micros
            ),
            format!(
                "hapax_imagination_v4l2_stage_duration_micros{{stage=\"max_total\"}} {}",
                v4l2.max_frame_micros
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
        self.clean_data
            .reserve((self.bytes_per_row * height) as usize);

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

fn elapsed_micros(start: Instant) -> u64 {
    start.elapsed().as_micros().min(u128::from(u64::MAX)) as u64
}

fn env_every_n(name: &str) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.parse::<u64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(DEFAULT_DIAGNOSTIC_EVERY_N)
}

fn should_publish_every(frame_count: u64, every_n: u64) -> bool {
    every_n <= 1 || frame_count.is_multiple_of(every_n)
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

    #[test]
    fn should_publish_every_allows_default_every_frame() {
        assert!(should_publish_every(1, 1));
        assert!(should_publish_every(2, 1));
    }

    #[test]
    fn should_publish_every_decimates_on_modulus() {
        assert!(!should_publish_every(29, 30));
        assert!(should_publish_every(30, 30));
        assert!(!should_publish_every(31, 30));
    }
}
