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
    last_conversion_micros: u64,
    last_write_syscall_micros: u64,
    last_frame_micros: u64,
    max_frame_micros: u64,
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
    pub last_conversion_micros: u64,
    pub last_write_syscall_micros: u64,
    pub last_frame_micros: u64,
    pub max_frame_micros: u64,
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
            last_conversion_micros: 0,
            last_write_syscall_micros: 0,
            last_frame_micros: 0,
            max_frame_micros: 0,
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
            last_conversion_micros: self.last_conversion_micros,
            last_write_syscall_micros: self.last_write_syscall_micros,
            last_frame_micros: self.last_frame_micros,
            max_frame_micros: self.max_frame_micros,
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

        let frame_start = Instant::now();
        let conversion_start = Instant::now();
        rgba_to_nv12_bt601(rgba_data, w, h, &mut self.nv12_buf);
        self.last_conversion_micros = elapsed_micros(conversion_start);

        // Write NV12 frame to v4l2 device
        let write_start = Instant::now();
        let written = unsafe {
            libc::write(
                self.fd,
                self.nv12_buf.as_ptr() as *const libc::c_void,
                self.nv12_buf.len(),
            )
        };
        self.last_write_syscall_micros = elapsed_micros(write_start);

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
        self.last_frame_micros = elapsed_micros(frame_start);
        self.max_frame_micros = self.max_frame_micros.max(self.last_frame_micros);

        if self.write_count % 900 == 0 {
            info!(
                "v4l2: {} frames written to {} (errors: {}, reopens: {}, last={}us convert={}us write={}us)",
                self.write_count,
                self.device_path,
                self.error_count,
                self.reopen_count,
                self.last_frame_micros,
                self.last_conversion_micros,
                self.last_write_syscall_micros
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

fn elapsed_micros(start: Instant) -> u64 {
    start.elapsed().as_micros().min(u128::from(u64::MAX)) as u64
}

fn y_limited_bt601(r: u8, g: u8, b: u8) -> u8 {
    let value = ((66 * i32::from(r) + 129 * i32::from(g) + 25 * i32::from(b) + 128) >> 8) + 16;
    value.clamp(16, 235) as u8
}

fn cb_limited_bt601(r: u8, g: u8, b: u8) -> u8 {
    let value = ((-38 * i32::from(r) - 74 * i32::from(g) + 112 * i32::from(b) + 128) >> 8) + 128;
    value.clamp(16, 240) as u8
}

fn cr_limited_bt601(r: u8, g: u8, b: u8) -> u8 {
    let value = ((112 * i32::from(r) - 94 * i32::from(g) - 18 * i32::from(b) + 128) >> 8) + 128;
    value.clamp(16, 240) as u8
}

fn avg4(a: u8, b: u8, c: u8, d: u8) -> u8 {
    ((u16::from(a) + u16::from(b) + u16::from(c) + u16::from(d) + 2) >> 2) as u8
}

fn rgba_to_nv12_bt601(rgba_data: &[u8], width: usize, height: usize, nv12_buf: &mut [u8]) {
    let y_len = width * height;
    let (y_plane, uv_plane) = nv12_buf.split_at_mut(y_len);

    for row in (0..height).step_by(2) {
        let row_a = &rgba_data[row * width * 4..(row + 1) * width * 4];
        let y_a = &mut y_plane[row * width..(row + 1) * width];
        let has_row_b = row + 1 < height;

        if has_row_b {
            let row_b = &rgba_data[(row + 1) * width * 4..(row + 2) * width * 4];
            let (upper_y, lower_y) = y_plane.split_at_mut((row + 1) * width);
            let y_b = &mut lower_y[..width];
            let y_a = &mut upper_y[row * width..(row + 1) * width];
            let uv_row = &mut uv_plane[(row / 2) * width..((row / 2) + 1) * width];

            for col in (0..width).step_by(2) {
                let a = col * 4;
                let b = ((col + 1).min(width - 1)) * 4;

                let r00 = row_a[a];
                let g00 = row_a[a + 1];
                let b00 = row_a[a + 2];
                let r01 = row_a[b];
                let g01 = row_a[b + 1];
                let b01 = row_a[b + 2];
                let r10 = row_b[a];
                let g10 = row_b[a + 1];
                let b10 = row_b[a + 2];
                let r11 = row_b[b];
                let g11 = row_b[b + 1];
                let b11 = row_b[b + 2];

                y_a[col] = y_limited_bt601(r00, g00, b00);
                if col + 1 < width {
                    y_a[col + 1] = y_limited_bt601(r01, g01, b01);
                }
                y_b[col] = y_limited_bt601(r10, g10, b10);
                if col + 1 < width {
                    y_b[col + 1] = y_limited_bt601(r11, g11, b11);
                }

                let r = avg4(r00, r01, r10, r11);
                let g = avg4(g00, g01, g10, g11);
                let b = avg4(b00, b01, b10, b11);
                uv_row[col] = cb_limited_bt601(r, g, b);
                if col + 1 < width {
                    uv_row[col + 1] = cr_limited_bt601(r, g, b);
                }
            }
        } else {
            for col in 0..width {
                let px = col * 4;
                y_a[col] = y_limited_bt601(row_a[px], row_a[px + 1], row_a[px + 2]);
            }
        }
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
                last_conversion_micros: 0,
                last_write_syscall_micros: 0,
                last_frame_micros: 0,
                max_frame_micros: 0,
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

    #[test]
    fn rgba_to_nv12_converts_black_and_white() {
        let rgba = [
            0, 0, 0, 255, 255, 255, 255, 255, 0, 0, 0, 255, 255, 255, 255, 255,
        ];
        let mut nv12 = vec![0; 2 * 2 * 3 / 2];

        rgba_to_nv12_bt601(&rgba, 2, 2, &mut nv12);

        assert_eq!(&nv12[..4], &[16, 235, 16, 235]);
        assert_eq!(&nv12[4..], &[128, 128]);
    }

    #[test]
    fn rgba_to_nv12_handles_odd_width_without_overrun() {
        let rgba = vec![0x80; 3 * 2 * 4];
        let mut nv12 = vec![0; 3 * 2 * 3 / 2];

        rgba_to_nv12_bt601(&rgba, 3, 2, &mut nv12);

        assert_eq!(nv12.len(), 9);
        assert!(nv12.iter().any(|v| *v != 0));
    }
}
