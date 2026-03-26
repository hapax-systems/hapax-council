// gst-smooth-delay — GStreamer GL smooth delay filter
//
// Maintains a ring buffer of GL textures in VRAM. Each frame is written to
// the ring; the output is read from delay_frames behind the write head.
// Pure GPU — no CPU round-trip for the delayed frames.
//
// At 30fps with 5s delay: 150 textures × 1920×1080×4 ≈ 1.2GB VRAM.
// Configurable via delay-seconds property (0-30s range).

use gstreamer as gst;
use gst::glib;

mod delay;

fn plugin_init(plugin: &gst::Plugin) -> Result<(), glib::BoolError> {
    delay::register(plugin)
}

gst::plugin_define!(
    smoothdelay,
    env!("CARGO_PKG_DESCRIPTION"),
    plugin_init,
    env!("CARGO_PKG_VERSION"),
    "MIT/X11",
    env!("CARGO_PKG_NAME"),
    env!("CARGO_PKG_NAME"),
    "https://github.com/ryanklee/hapax-council",
    "2026-03-26"
);
