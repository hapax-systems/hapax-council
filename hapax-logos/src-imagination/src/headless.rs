//! Headless wgpu renderer scaffold — Phase 4a of the reverie source-registry
//! completion epic.
//!
//! Activated by `HAPAX_IMAGINATION_HEADLESS=1`. The **skeleton** constructor
//! lands here so the env-var branch compiles and the marker unit test pins
//! the module's public surface; the **real** offscreen render loop (owned
//! wgpu texture → `DynamicPipeline::render` → staging copy-out → SHM write
//! to `/dev/shm/hapax-sources/reverie.rgba`) lands in Phase 4b.
//!
//! Parent plan: `docs/superpowers/plans/2026-04-12-compositor-source-registry-foundation-plan.md`
//! Task 18. Deliberately deferred in PR #723 as "several hours of work I
//! don't want to half-ship" — Phase 4a delivers the scaffold so Phase 4b
//! can land the real loop behind an already-landed env var without another
//! schema-level change.
//!
//! The Phase 4 systemd unit update (Task 19) is intentionally NOT shipped
//! here: setting `HAPAX_IMAGINATION_HEADLESS=1` on the service unit while
//! `run_forever` is a stub would take the reverie visual surface dark.

use std::convert::Infallible;
use std::time::Duration;

/// Offscreen reverie render loop. Placeholder for Phase 4b.
pub struct Renderer {
    width: u32,
    height: u32,
}

impl Renderer {
    /// Test-only constructor — no GPU, no tokio runtime, just the dims.
    ///
    /// Used by the unit test at the bottom of this module and by any
    /// future callers that need a compile-time marker that the headless
    /// module is reachable from `main.rs`.
    #[cfg(test)]
    pub fn new_for_tests(width: u32, height: u32) -> Self {
        Self { width, height }
    }

    /// Async constructor. In Phase 4a this is a compile-only stub that
    /// records the requested dimensions; in Phase 4b it will build a
    /// `GpuContext::new_headless`, allocate an owned wgpu texture +
    /// staging buffer, and wire them to `DynamicPipeline::render`.
    pub async fn new(width: u32, height: u32) -> Self {
        log::warn!(
            "HAPAX_IMAGINATION_HEADLESS=1 is enabled but the Phase 4a \
             skeleton `headless::Renderer::new` does not yet own a GPU \
             context. The reverie surface is effectively paused in \
             headless mode until Phase 4b ships. Unset the env var to \
             return to the winit path."
        );
        Self { width, height }
    }

    /// Drive the render loop forever. Phase 4a stub sleeps in a 60fps
    /// tick so the binary does not busy-loop while the env var is set.
    /// Phase 4b will replace the body with:
    ///
    /// 1. Reuse `StateReader::poll` from the windowed path.
    /// 2. Call `DynamicPipeline::render` into a view of the owned
    ///    offscreen texture.
    /// 3. Encode a copy-to-buffer command submission and
    ///    `device.poll(Wait)` for it.
    /// 4. Map the staging buffer, read RGBA bytes, pass them to a
    ///    shared writer that publishes to
    ///    `/dev/shm/hapax-sources/reverie.rgba` + sidecar.
    pub async fn run_forever(self) -> Infallible {
        let mut interval = tokio::time::interval(Duration::from_millis(16));
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        log::info!(
            "headless::Renderer::run_forever stub started at {}x{} — \
             no frames will be rendered until Phase 4b",
            self.width,
            self.height,
        );
        loop {
            interval.tick().await;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_for_tests_records_dimensions() {
        let r = Renderer::new_for_tests(1920, 1080);
        assert_eq!(r.width, 1920);
        assert_eq!(r.height, 1080);
    }

    #[test]
    fn new_for_tests_accepts_arbitrary_dims() {
        let r = Renderer::new_for_tests(640, 360);
        assert_eq!(r.width, 640);
        assert_eq!(r.height, 360);
    }
}
