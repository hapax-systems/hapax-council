// Tech debt: 5 pre-existing warnings in dynamic_pipeline.rs and state.rs.
// Remove once dead fields/methods are cleaned up or used.
#![allow(dead_code, clippy::too_many_arguments)]
pub mod content_sources;
pub mod control;
pub mod dynamic_pipeline;
pub mod gpu;
pub mod output;
pub mod state;
pub mod transient_pool;
pub mod uniform_buffer;
pub mod scene;
pub mod scene_renderer;
pub mod v4l2_output;
