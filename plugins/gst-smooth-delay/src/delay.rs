// Smooth delay filter — GL texture ring buffer for temporal offset.
//
// Allocates a ring of GL textures on gl_start. Each filter_texture call:
//   1. Copies input into ring[write_head % capacity]
//   2. Outputs ring[(write_head - delay_frames + 1) % capacity] (oldest relevant frame)
//   3. Increments write_head
//
// Until the ring fills (write_head < capacity), outputs the oldest available
// frame to avoid reading uninitialized textures.

use std::sync::Mutex;

use glib::subclass::prelude::*;
use gstreamer as gst;
use gstreamer::prelude::*;
use gstreamer::subclass::prelude::*;
use gstreamer_base as gst_base;
use gst_base::subclass::BaseTransformMode;
use gstreamer_gl as gst_gl;
use gst_gl::prelude::*;
use gst_gl::subclass::prelude::*;
use gst_gl::subclass::GLFilterMode;

use std::sync::LazyLock;

mod gl {
    include!(concat!(env!("OUT_DIR"), "/gl_bindings.rs"));
}

static CAT: LazyLock<gst::DebugCategory> = LazyLock::new(|| {
    gst::DebugCategory::new(
        "smoothdelay",
        gst::DebugColorFlags::empty(),
        Some("GL Smooth Delay Filter"),
    )
});

#[derive(Debug, Clone)]
struct Settings {
    delay_seconds: f32,
    fps: u32,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            delay_seconds: 5.0,
            fps: 30,
        }
    }
}

struct GlState {
    gl: gl::Gles2,
    ring: Vec<u32>,       // GL texture IDs
    write_head: usize,
    capacity: usize,
    width: i32,
    height: i32,
    frames_written: usize, // total frames written (for fill tracking)
    // Simple blit shader for copy operations
    shader: gst_gl::GLShader,
}

#[derive(Default)]
pub struct SmoothDelay {
    settings: Mutex<Settings>,
    gl_state: Mutex<Option<GlState>>,
}

const PASSTHROUGH_FRAG: &str = r#"
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;

void main() {
    gl_FragColor = texture2D(tex, v_texcoord);
}
"#;

// GObject wrapper type
mod imp_types {
    use super::*;

    glib::wrapper! {
        pub struct SmoothDelay(ObjectSubclass<super::SmoothDelay>)
            @extends gst_gl::GLFilter, gst_gl::GLBaseFilter, gst_base::BaseTransform, gst::Element, gst::Object;
    }
}

#[glib::object_subclass]
impl ObjectSubclass for SmoothDelay {
    const NAME: &'static str = "GstSmoothDelay";
    type Type = imp_types::SmoothDelay;
    type ParentType = gst_gl::GLFilter;
}

impl ObjectImpl for SmoothDelay {
    fn properties() -> &'static [glib::ParamSpec] {
        static PROPERTIES: LazyLock<Vec<glib::ParamSpec>> = LazyLock::new(|| {
            vec![
                glib::ParamSpecFloat::builder("delay-seconds")
                    .nick("Delay Seconds")
                    .blurb("Temporal delay in seconds (ring buffer depth)")
                    .minimum(0.0)
                    .maximum(30.0)
                    .default_value(5.0)
                    .build(),
                glib::ParamSpecUInt::builder("fps")
                    .nick("FPS")
                    .blurb("Frames per second (determines ring capacity)")
                    .minimum(1)
                    .maximum(120)
                    .default_value(30)
                    .build(),
            ]
        });
        PROPERTIES.as_ref()
    }

    fn set_property(&self, _id: usize, value: &glib::Value, pspec: &glib::ParamSpec) {
        let mut settings = self.settings.lock().unwrap();
        match pspec.name() {
            "delay-seconds" => settings.delay_seconds = value.get().unwrap(),
            "fps" => settings.fps = value.get().unwrap(),
            _ => {}
        }
    }

    fn property(&self, _id: usize, pspec: &glib::ParamSpec) -> glib::Value {
        let settings = self.settings.lock().unwrap();
        match pspec.name() {
            "delay-seconds" => settings.delay_seconds.to_value(),
            "fps" => settings.fps.to_value(),
            _ => unimplemented!(),
        }
    }
}

impl GstObjectImpl for SmoothDelay {}

impl ElementImpl for SmoothDelay {
    fn metadata() -> Option<&'static gst::subclass::ElementMetadata> {
        static ELEMENT_METADATA: LazyLock<gst::subclass::ElementMetadata> = LazyLock::new(|| {
            gst::subclass::ElementMetadata::new(
                "Smooth Delay Filter",
                "Filter/Effect/Video",
                "GPU texture ring buffer for temporal delay — @smooth layer source",
                "hapax",
            )
        });
        Some(&*ELEMENT_METADATA)
    }
}

impl BaseTransformImpl for SmoothDelay {
    const MODE: BaseTransformMode = BaseTransformMode::NeverInPlace;
    const PASSTHROUGH_ON_SAME_CAPS: bool = false;
    const TRANSFORM_IP_ON_PASSTHROUGH: bool = false;
}

impl GLBaseFilterImpl for SmoothDelay {
    fn gl_start(&self) -> Result<(), gst::LoggableError> {
        let filter = self.obj();
        let context = gst_gl::prelude::GLBaseFilterExt::context(&*filter).unwrap();

        let gl = gl::Gles2::load_with(|name| context.proc_address(name) as *const _);

        // Compile passthrough shader for blit operations
        let shader = gst_gl::GLShader::new(&context);
        let vertex = gst_gl::GLSLStage::new_default_vertex(&context);
        vertex.compile().map_err(|e| {
            gst::loggable_error!(CAT, "Vertex compile failed: {e}")
        })?;
        shader.attach_unlocked(&vertex).map_err(|e| {
            gst::loggable_error!(CAT, "Vertex attach failed: {e}")
        })?;

        let fragment = gst_gl::GLSLStage::with_strings(
            &context,
            gl::FRAGMENT_SHADER,
            gst_gl::GLSLVersion::None,
            gst_gl::GLSLProfile::ES | gst_gl::GLSLProfile::COMPATIBILITY,
            &[PASSTHROUGH_FRAG],
        );
        fragment.compile().map_err(|e| {
            gst::loggable_error!(CAT, "Fragment compile failed: {e}")
        })?;
        shader.attach_unlocked(&fragment).map_err(|e| {
            gst::loggable_error!(CAT, "Fragment attach failed: {e}")
        })?;
        shader.link().map_err(|e| {
            gst::loggable_error!(CAT, "Shader link failed: {e}")
        })?;

        let settings = self.settings.lock().unwrap().clone();
        let capacity = (settings.delay_seconds * settings.fps as f32).ceil() as usize;
        let capacity = capacity.max(2); // minimum 2 frames

        gst::info!(
            CAT, imp = self,
            "Smooth delay: {:.1}s × {}fps = {} frame ring buffer",
            settings.delay_seconds, settings.fps, capacity
        );

        *self.gl_state.lock().unwrap() = Some(GlState {
            gl,
            ring: Vec::new(), // textures allocated lazily on first frame (need dimensions)
            write_head: 0,
            capacity,
            width: 0,
            height: 0,
            frames_written: 0,
            shader,
        });

        self.parent_gl_start()
    }

    fn gl_stop(&self) {
        if let Some(state) = self.gl_state.lock().unwrap().take() {
            if !state.ring.is_empty() {
                unsafe {
                    state.gl.DeleteTextures(state.ring.len() as i32, state.ring.as_ptr());
                }
                gst::debug!(CAT, imp = self, "Freed {} ring textures", state.ring.len());
            }
        }
        self.parent_gl_stop();
    }
}

impl GLFilterImpl for SmoothDelay {
    const MODE: GLFilterMode = GLFilterMode::Texture;

    fn filter_texture(
        &self,
        input: &gst_gl::GLMemory,
        output: &gst_gl::GLMemory,
    ) -> Result<(), gst::LoggableError> {
        let filter = self.obj();
        let width = input.texture_width();
        let height = input.texture_height();

        let mut gl_state = self.gl_state.lock().unwrap();
        let state = gl_state.as_mut().ok_or_else(|| {
            gst::loggable_error!(CAT, "GL state not initialized")
        })?;

        // Allocate ring textures on first frame or resolution change
        if state.ring.is_empty() || state.width != width || state.height != height {
            // Free old textures
            if !state.ring.is_empty() {
                unsafe {
                    state.gl.DeleteTextures(state.ring.len() as i32, state.ring.as_ptr());
                }
            }

            let mut textures = vec![0u32; state.capacity];
            unsafe {
                state.gl.GenTextures(state.capacity as i32, textures.as_mut_ptr());
                for &tex in &textures {
                    state.gl.BindTexture(gl::TEXTURE_2D, tex);
                    state.gl.TexImage2D(
                        gl::TEXTURE_2D, 0, gl::RGBA as i32,
                        width, height, 0,
                        gl::RGBA, gl::UNSIGNED_BYTE, std::ptr::null(),
                    );
                    state.gl.TexParameteri(gl::TEXTURE_2D, gl::TEXTURE_MIN_FILTER, gl::LINEAR as i32);
                    state.gl.TexParameteri(gl::TEXTURE_2D, gl::TEXTURE_MAG_FILTER, gl::LINEAR as i32);
                    state.gl.TexParameteri(gl::TEXTURE_2D, gl::TEXTURE_WRAP_S, gl::CLAMP_TO_EDGE as i32);
                    state.gl.TexParameteri(gl::TEXTURE_2D, gl::TEXTURE_WRAP_T, gl::CLAMP_TO_EDGE as i32);
                }
                state.gl.BindTexture(gl::TEXTURE_2D, 0);
            }

            let vram_mb = (state.capacity as f64 * width as f64 * height as f64 * 4.0) / (1024.0 * 1024.0);
            gst::info!(
                CAT, imp = self,
                "Allocated {} ring textures ({}x{}, {:.0}MB VRAM)",
                state.capacity, width, height, vram_mb
            );

            state.ring = textures;
            state.width = width;
            state.height = height;
            state.write_head = 0;
            state.frames_written = 0;
        }

        let write_idx = state.write_head % state.capacity;

        // Determine which frame to output
        let read_idx = if state.frames_written < state.capacity {
            // Ring not full yet — output the oldest available frame
            0
        } else {
            // Ring full — read from delay_frames behind write_head
            (state.write_head + 1) % state.capacity
        };

        // Render the delayed frame to output
        let delayed_tex = state.ring[read_idx];
        if state.frames_written == 0 {
            // No frames in ring yet — passthrough input directly
            filter.render_to_target_with_shader(input, output, &state.shader);
        } else {
            // Bind delayed texture as input and render to output
            unsafe {
                state.gl.ActiveTexture(gl::TEXTURE0);
                state.gl.BindTexture(gl::TEXTURE_2D, delayed_tex);
            }
            state.shader.set_uniform_1i("tex", 0);
            filter.render_to_target_with_shader(input, output, &state.shader);
        }

        // Copy current input into ring slot via FBO
        unsafe {
            let mut fbo = 0u32;
            state.gl.GenFramebuffers(1, &mut fbo);
            state.gl.BindFramebuffer(gl::FRAMEBUFFER, fbo);
            state.gl.FramebufferTexture2D(
                gl::FRAMEBUFFER, gl::COLOR_ATTACHMENT0,
                gl::TEXTURE_2D, input.texture_id(), 0,
            );
            // CopyTexSubImage2D reads from bound FRAMEBUFFER into the bound texture
            state.gl.BindTexture(gl::TEXTURE_2D, state.ring[write_idx]);
            state.gl.CopyTexSubImage2D(gl::TEXTURE_2D, 0, 0, 0, 0, 0, width, height);
            state.gl.BindTexture(gl::TEXTURE_2D, 0);
            state.gl.BindFramebuffer(gl::FRAMEBUFFER, 0);
            state.gl.DeleteFramebuffers(1, &fbo);
        }

        state.write_head = (state.write_head + 1) % state.capacity;
        state.frames_written += 1;

        drop(gl_state);
        self.parent_filter_texture(input, output)
    }
}

pub fn register(plugin: &gst::Plugin) -> Result<(), glib::BoolError> {
    gst::Element::register(
        Some(plugin),
        "smoothdelay",
        gst::Rank::NONE,
        imp_types::SmoothDelay::static_type(),
    )
}
