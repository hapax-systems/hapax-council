// gst-temporalfx — GStreamer GL temporal feedback filter
//
// FBO ping-pong accumulation for trails, ghosting, datamosh effects.
// Maintains a persistent accumulation texture across frames:
//
//   output = mix(current_input, accumulated * decay, blend_factor)
//   accumulated = output  (for next frame)
//
// This creates true compounding trails with exponential decay.

use gstreamer as gst;
use gst::glib;
use gst::prelude::*;

mod temporalfx;

fn plugin_init(plugin: &gst::Plugin) -> Result<(), glib::BoolError> {
    temporalfx::register(plugin)
}

gst::plugin_define!(
    temporalfx,
    env!("CARGO_PKG_DESCRIPTION"),
    plugin_init,
    env!("CARGO_PKG_VERSION"),
    "MIT/X11",
    env!("CARGO_PKG_NAME"),
    env!("CARGO_PKG_NAME"),
    "https://github.com/ryanklee/hapax-council",
    "2026-03-16"
);
