// Crossfade filter — snapshot capture + alpha blend for smooth transitions.
//
// On "trigger", captures the current input frame into a snapshot texture.
// For the next transition_ms, blends: output = mix(current, snapshot, alpha)
// where alpha decays linearly from 1.0 to 0.0.
//
// When not transitioning, pure passthrough (no GPU cost beyond texture copy).

use std::sync::Mutex;
use std::time::Instant;

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
        "crossfade",
        gst::DebugColorFlags::empty(),
        Some("GL Crossfade Transition Filter"),
    )
});

#[derive(Debug, Clone)]
struct Settings {
    transition_ms: u32,
    trigger: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            transition_ms: 500,
            trigger: false,
        }
    }
}

struct GlState {
    shader: gst_gl::GLShader,
    gl: gl::Gles2,
    snapshot_tex: u32,
    width: i32,
    height: i32,
}

#[derive(Default)]
struct TransitionState {
    active: bool,
    start: Option<Instant>,
    duration_ms: u32,
}

#[derive(Default)]
pub struct Crossfade {
    settings: Mutex<Settings>,
    gl_state: Mutex<Option<GlState>>,
    transition: Mutex<TransitionState>,
}

const BLEND_FRAG: &str = r#"
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_snapshot;
uniform float u_alpha;

void main() {
    vec4 current = texture2D(tex, v_texcoord);
    vec4 snapshot = texture2D(tex_snapshot, v_texcoord);
    gl_FragColor = mix(current, snapshot, u_alpha);
}
"#;

// GObject wrapper type
mod imp_types {
    use super::*;

    glib::wrapper! {
        pub struct Crossfade(ObjectSubclass<super::Crossfade>)
            @extends gst_gl::GLFilter, gst_gl::GLBaseFilter, gst_base::BaseTransform, gst::Element, gst::Object;
    }
}

#[glib::object_subclass]
impl ObjectSubclass for Crossfade {
    const NAME: &'static str = "GstCrossfade";
    type Type = imp_types::Crossfade;
    type ParentType = gst_gl::GLFilter;
}

impl ObjectImpl for Crossfade {
    fn properties() -> &'static [glib::ParamSpec] {
        static PROPERTIES: LazyLock<Vec<glib::ParamSpec>> = LazyLock::new(|| {
            vec![
                glib::ParamSpecUInt::builder("transition-ms")
                    .nick("Transition Duration")
                    .blurb("Crossfade duration in milliseconds")
                    .minimum(50)
                    .maximum(5000)
                    .default_value(500)
                    .build(),
                glib::ParamSpecBoolean::builder("trigger")
                    .nick("Trigger")
                    .blurb("Set to true to capture snapshot and start crossfade")
                    .default_value(false)
                    .build(),
            ]
        });
        PROPERTIES.as_ref()
    }

    fn set_property(&self, _id: usize, value: &glib::Value, pspec: &glib::ParamSpec) {
        match pspec.name() {
            "transition-ms" => {
                self.settings.lock().unwrap().transition_ms = value.get().unwrap();
            }
            "trigger" => {
                let trigger: bool = value.get().unwrap();
                if trigger {
                    let duration_ms = self.settings.lock().unwrap().transition_ms;
                    let mut ts = self.transition.lock().unwrap();
                    ts.active = true;
                    ts.start = None; // Will be set on next filter_texture call
                    ts.duration_ms = duration_ms;
                    gst::debug!(CAT, imp = self, "Crossfade triggered ({duration_ms}ms)");
                }
                self.settings.lock().unwrap().trigger = false; // Auto-reset
            }
            _ => {}
        }
    }

    fn property(&self, _id: usize, pspec: &glib::ParamSpec) -> glib::Value {
        let settings = self.settings.lock().unwrap();
        match pspec.name() {
            "transition-ms" => settings.transition_ms.to_value(),
            "trigger" => settings.trigger.to_value(),
            _ => unimplemented!(),
        }
    }
}

impl GstObjectImpl for Crossfade {}

impl ElementImpl for Crossfade {
    fn metadata() -> Option<&'static gst::subclass::ElementMetadata> {
        static ELEMENT_METADATA: LazyLock<gst::subclass::ElementMetadata> = LazyLock::new(|| {
            gst::subclass::ElementMetadata::new(
                "Crossfade Transition Filter",
                "Filter/Effect/Video",
                "GPU crossfade via snapshot capture and alpha blend",
                "hapax",
            )
        });
        Some(&*ELEMENT_METADATA)
    }
}

impl BaseTransformImpl for Crossfade {
    const MODE: BaseTransformMode = BaseTransformMode::NeverInPlace;
    const PASSTHROUGH_ON_SAME_CAPS: bool = false;
    const TRANSFORM_IP_ON_PASSTHROUGH: bool = false;
}

impl GLBaseFilterImpl for Crossfade {
    fn gl_start(&self) -> Result<(), gst::LoggableError> {
        let filter = self.obj();
        let context = gst_gl::prelude::GLBaseFilterExt::context(&*filter).unwrap();

        let gl = gl::Gles2::load_with(|name| context.proc_address(name) as *const _);

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
            &[BLEND_FRAG],
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

        gst::debug!(CAT, imp = self, "Crossfade shader compiled and linked");

        *self.gl_state.lock().unwrap() = Some(GlState {
            shader,
            gl,
            snapshot_tex: 0,
            width: 0,
            height: 0,
        });

        self.parent_gl_start()
    }

    fn gl_stop(&self) {
        if let Some(state) = self.gl_state.lock().unwrap().take() {
            if state.snapshot_tex != 0 {
                unsafe {
                    state.gl.DeleteTextures(1, &state.snapshot_tex);
                }
            }
        }
        self.parent_gl_stop();
    }
}

impl GLFilterImpl for Crossfade {
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

        // Ensure snapshot texture exists at correct size
        if state.snapshot_tex == 0 || state.width != width || state.height != height {
            if state.snapshot_tex != 0 {
                unsafe { state.gl.DeleteTextures(1, &state.snapshot_tex); }
            }
            let mut tex = 0u32;
            unsafe {
                state.gl.GenTextures(1, &mut tex);
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
                state.gl.BindTexture(gl::TEXTURE_2D, 0);
            }
            state.snapshot_tex = tex;
            state.width = width;
            state.height = height;
            gst::debug!(CAT, imp = self, "Created snapshot texture {tex} ({width}x{height})");
        }

        let mut ts = self.transition.lock().unwrap();

        // If transition was just triggered, capture the current input as snapshot
        if ts.active && ts.start.is_none() {
            // Render input to output first (so we have a valid framebuffer)
            filter.render_to_target_with_shader(input, output, &state.shader);

            // Capture current output into snapshot texture
            unsafe {
                state.gl.BindTexture(gl::TEXTURE_2D, state.snapshot_tex);
                state.gl.CopyTexSubImage2D(gl::TEXTURE_2D, 0, 0, 0, 0, 0, width, height);
                state.gl.BindTexture(gl::TEXTURE_2D, 0);
            }
            ts.start = Some(Instant::now());
            gst::debug!(CAT, imp = self, "Captured snapshot for crossfade");
        }

        if ts.active {
            let elapsed = ts.start.map(|s| s.elapsed().as_millis() as f32).unwrap_or(0.0);
            let alpha = 1.0 - (elapsed / ts.duration_ms as f32).min(1.0);

            if alpha <= 0.0 {
                // Transition complete
                ts.active = false;
                ts.start = None;
                gst::debug!(CAT, imp = self, "Crossfade complete");
                drop(ts);

                // Pure passthrough
                filter.render_to_target_with_shader(input, output, &state.shader);
            } else {
                drop(ts);

                // Blend: mix(current, snapshot, alpha)
                let shader = &state.shader;
                shader.set_uniform_1f("u_alpha", alpha);

                // Bind snapshot to texture unit 1
                unsafe {
                    state.gl.ActiveTexture(gl::TEXTURE1);
                    state.gl.BindTexture(gl::TEXTURE_2D, state.snapshot_tex);
                }
                shader.set_uniform_1i("tex_snapshot", 1);

                filter.render_to_target_with_shader(input, output, shader);

                unsafe {
                    state.gl.ActiveTexture(gl::TEXTURE0);
                }
            }
        } else {
            drop(ts);
            // No transition — passthrough (u_alpha = 0 makes mix() return current)
            state.shader.set_uniform_1f("u_alpha", 0.0);
            filter.render_to_target_with_shader(input, output, &state.shader);
        }

        drop(gl_state);
        self.parent_filter_texture(input, output)
    }
}

pub fn register(plugin: &gst::Plugin) -> Result<(), glib::BoolError> {
    gst::Element::register(
        Some(plugin),
        "crossfade",
        gst::Rank::NONE,
        imp_types::Crossfade::static_type(),
    )
}
