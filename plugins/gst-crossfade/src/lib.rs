// gst-crossfade — GStreamer GL crossfade filter
//
// Smooth preset transitions: captures a snapshot of the current output,
// then blends it with the new output over a configurable duration.
//
// Set "trigger" property to true to capture a snapshot and start the
// crossfade. The alpha ramps from 1.0 (all snapshot) to 0.0 (all current)
// over transition_ms milliseconds.

use gstreamer as gst;
use gst::glib;
use gst::prelude::*;

mod crossfade;

fn plugin_init(plugin: &gst::Plugin) -> Result<(), glib::BoolError> {
    crossfade::register(plugin)
}

gst::plugin_define!(
    crossfade,
    env!("CARGO_PKG_DESCRIPTION"),
    plugin_init,
    env!("CARGO_PKG_VERSION"),
    "MIT/X11",
    env!("CARGO_PKG_NAME"),
    env!("CARGO_PKG_NAME"),
    "https://github.com/ryanklee/hapax-council",
    "2026-03-26"
);
