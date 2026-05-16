//! Direct v4l2 output — writes NV12 frames to a v4l2loopback device.
//!
//! The wgpu compositor output is `Rgba8UnormSrgb` (R,G,B,A byte order).
//! v4l2loopback expects NV12 (Y plane + interleaved UV plane).
//! Conversion is done on CPU — at 960×540 it takes ~0.2ms, well within
//! the 33ms frame budget.
//!
//! Env-gated: `HAPAX_IMAGINATION_V4L2_OUTPUT=1`

use log::{error, info, warn};
use std::time::Instant;

/// v4l2loopback device path for the StudioCompositor output.
const DEFAULT_DEVICE: &str = "/dev/video42";

/// Writes NV12-converted frames to a v4l2 loopback device.
pub struct V4l2Output {
    device_path: String,
    fd: i32,
    width: u32,
    height: u32,
    /// NV12 frame buffer: Y plane (w*h) + UV plane (w*h/2)
    nv12_buf: Vec<u8>,
    write_count: u64,
    write_bytes_total: u64,
    error_count: u64,
    reopen_count: u64,
    last_write: Instant,
    enabled: bool,
}

/// Snapshot counters for the direct v4l2 egress path.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct V4l2Metrics {
    pub enabled: bool,
    pub write_count: u64,
    pub write_bytes_total: u64,
    pub error_count: u64,
    pub reopen_count: u64,
    pub last_write_age_seconds: Option<f64>,
}

impl V4l2Output {
    pub fn new(width: u32, height: u32) -> Self {
        let device =
            std::env::var("HAPAX_V4L2_DEVICE").unwrap_or_else(|_| DEFAULT_DEVICE.to_string());
        let enabled = std::env::var("HAPAX_IMAGINATION_V4L2_OUTPUT")
            .map(|v| v == "1")
            .unwrap_or(false);

        let nv12_size = (width * height * 3 / 2) as usize;
        let nv12_buf = vec![0u8; nv12_size];

        let mut out = Self {
            device_path: device,
            fd: -1,
            width,
            height,
            nv12_buf,
            write_count: 0,
            write_bytes_total: 0,
            error_count: 0,
            reopen_count: 0,
            last_write: Instant::now(),
            enabled,
        };

        if enabled {
            out.open_device();
        } else {
            info!("v4l2 output disabled (set HAPAX_IMAGINATION_V4L2_OUTPUT=1 to enable)");
        }

        out
    }

    #[allow(dead_code)]
    pub fn is_enabled(&self) -> bool {
        self.enabled
    }

    pub fn metrics(&self) -> V4l2Metrics {
        V4l2Metrics {
            enabled: self.enabled,
            write_count: self.write_count,
            write_bytes_total: self.write_bytes_total,
            error_count: self.error_count,
            reopen_count: self.reopen_count,
            last_write_age_seconds: (self.write_count > 0)
                .then(|| self.last_write.elapsed().as_secs_f64()),
        }
    }

    fn open_device(&mut self) {
        if self.fd >= 0 {
            return;
        }

        let path = std::ffi::CString::new(self.device_path.as_str()).unwrap();
        let fd = unsafe { libc::open(path.as_ptr(), libc::O_WRONLY | libc::O_NONBLOCK) };

        if fd < 0 {
            let err = std::io::Error::last_os_error();
            error!("v4l2: failed to open {}: {}", self.device_path, err);
            return;
        }

        self.fd = fd;
        self.reopen_count += 1;
        info!(
            "v4l2: opened {} (fd={}) — NV12 {}×{} ({} bytes/frame, reopen #{})",
            self.device_path,
            fd,
            self.width,
            self.height,
            self.nv12_buf.len(),
            self.reopen_count
        );
    }

    fn close_device(&mut self) {
        if self.fd >= 0 {
            unsafe {
                libc::close(self.fd);
            }
            self.fd = -1;
        }
    }

    /// Convert RGBA to NV12 (BT.601) and write to the v4l2 device.
    ///
    /// `rgba_data` must be at least `width * height * 4` bytes in R,G,B,A order.
    pub fn write_frame(&mut self, rgba_data: &[u8]) -> bool {
        if !self.enabled {
            return false;
        }

        let w = self.width as usize;
        let h = self.height as usize;
        let expected = w * h * 4;

        if rgba_data.len() < expected {
            warn!("v4l2: frame too small ({} < {})", rgba_data.len(), expected);
            return false;
        }

        if self.fd < 0 {
            self.open_device();
            if self.fd < 0 {
                return false;
            }
        }

        // RGBA → NV12 conversion (BT.601 limited range)
        // Y plane: one byte per pixel
        // UV plane: one Cb,Cr pair per 2×2 block, interleaved
        let (y_plane, uv_plane) = self.nv12_buf.split_at_mut(w * h);

        for row in 0..h {
            let rgba_row = &rgba_data[row * w * 4..(row + 1) * w * 4];
            let y_row = &mut y_plane[row * w..(row + 1) * w];

            for col in 0..w {
                let r = rgba_row[col * 4] as f32;
                let g = rgba_row[col * 4 + 1] as f32;
                let b = rgba_row[col * 4 + 2] as f32;

                y_row[col] = (16.0 + 0.257 * r + 0.504 * g + 0.098 * b).clamp(16.0, 235.0) as u8;
            }

            // UV: process only even rows
            if row % 2 == 0 && row + 1 < h {
                let uv_row = &mut uv_plane[(row / 2) * w..((row / 2) + 1) * w];
                let rgba_row_next = &rgba_data[(row + 1) * w * 4..(row + 2) * w * 4];

                for col in (0..w).step_by(2) {
                    // Average 2×2 block
                    let r = (rgba_row[col * 4] as f32
                        + rgba_row[(col + 1) * 4] as f32
                        + rgba_row_next[col * 4] as f32
                        + rgba_row_next[(col + 1) * 4] as f32)
                        * 0.25;
                    let g = (rgba_row[col * 4 + 1] as f32
                        + rgba_row[(col + 1) * 4 + 1] as f32
                        + rgba_row_next[col * 4 + 1] as f32
                        + rgba_row_next[(col + 1) * 4 + 1] as f32)
                        * 0.25;
                    let b = (rgba_row[col * 4 + 2] as f32
                        + rgba_row[(col + 1) * 4 + 2] as f32
                        + rgba_row_next[col * 4 + 2] as f32
                        + rgba_row_next[(col + 1) * 4 + 2] as f32)
                        * 0.25;

                    let cb = (128.0 - 0.148 * r - 0.291 * g + 0.439 * b).clamp(16.0, 240.0) as u8;
                    let cr = (128.0 + 0.439 * r - 0.368 * g - 0.071 * b).clamp(16.0, 240.0) as u8;

                    uv_row[col] = cb;
                    uv_row[col + 1] = cr;
                }
            }
        }

        // Write NV12 frame to v4l2 device
        let written = unsafe {
            libc::write(
                self.fd,
                self.nv12_buf.as_ptr() as *const libc::c_void,
                self.nv12_buf.len(),
            )
        };

        if written < 0 {
            let err = std::io::Error::last_os_error();
            let errno = err.raw_os_error().unwrap_or(0);

            if errno == libc::EAGAIN
                || errno == libc::EIO
                || errno == libc::ENODEV
                || errno == libc::ENXIO
            {
                self.error_count += 1;
                if self.error_count % 100 == 1 {
                    warn!(
                        "v4l2: write error #{} (errno={}), closing for reopen",
                        self.error_count, errno
                    );
                }
                self.close_device();
                return false;
            }

            error!("v4l2: fatal write error: {}", err);
            self.close_device();
            self.enabled = false;
            return false;
        }

        self.write_count += 1;
        self.write_bytes_total += written as u64;
        self.last_write = Instant::now();

        if self.write_count % 900 == 0 {
            info!(
                "v4l2: {} frames written to {} (errors: {}, reopens: {})",
                self.write_count, self.device_path, self.error_count, self.reopen_count
            );
        }

        true
    }
}

impl Drop for V4l2Output {
    fn drop(&mut self) {
        self.close_device();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_by_default() {
        let out = V4l2Output::new(1280, 720);
        assert!(!out.is_enabled());
        assert_eq!(
            out.metrics(),
            V4l2Metrics {
                enabled: false,
                write_count: 0,
                write_bytes_total: 0,
                error_count: 0,
                reopen_count: 0,
                last_write_age_seconds: None,
            }
        );
    }

    #[test]
    fn nv12_buffer_size() {
        let out = V4l2Output::new(1280, 720);
        // NV12: Y (1280*720) + UV (1280*720/2) = 1382400
        assert_eq!(out.nv12_buf.len(), 1280 * 720 * 3 / 2);
    }

    #[test]
    fn nv12_buffer_960x540() {
        let out = V4l2Output::new(960, 540);
        assert_eq!(out.nv12_buf.len(), 960 * 540 * 3 / 2);
    }
}
