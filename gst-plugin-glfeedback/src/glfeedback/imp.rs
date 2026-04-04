//! GStreamer GL temporal feedback filter — ping-pong FBO implementation.
//!
//! Provides `tex_accum` (the previous frame's output) to fragment shaders
//! that need temporal state (trail, feedback, echo, stutter, slitscan, diff).
//!
//! The fragment shader source and uniform values are set via GObject properties.
//! The ping-pong accumulation texture is managed internally; users never touch
//! the GL resources directly.

use std::sync::Mutex;

use glib::subclass::prelude::*;
use gst::prelude::*;
use gst::subclass::prelude::*;
use gst_gl::prelude::*;
use gst_gl::subclass::prelude::*;
use gst_gl::subclass::GLFilterMode;

// Default passthrough shader: output = input, no accumulation.
const DEFAULT_FRAGMENT: &str = r#"
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
void main() {
    gl_FragColor = texture2D(tex, v_texcoord);
}
"#;

struct State {
    /// Ping-pong accumulation textures.
    accum_textures: [u32; 2],
    /// FBOs bound to the accum textures for blit operations.
    accum_fbos: [u32; 2],
    /// Which accumulation buffer holds the "previous frame" output.
    current_idx: usize,
    /// Resolution (for reallocation on caps change).
    width: i32,
    height: i32,
    /// Compiled GL shader program.
    shader: gst_gl::GLShader,
}

/// Properties exposed to GStreamer (set from Python via set_property).
#[derive(Default)]
struct Props {
    fragment: Option<String>,
    uniforms: Vec<(String, f32)>,
    shader_dirty: bool,
}

pub struct GlFeedback {
    state: Mutex<Option<State>>,
    props: Mutex<Props>,
}

impl Default for GlFeedback {
    fn default() -> Self {
        Self {
            state: Mutex::new(None),
            props: Mutex::new(Props::default()),
        }
    }
}

#[glib::object_subclass]
impl ObjectSubclass for GlFeedback {
    const NAME: &'static str = "GstGlFeedback";
    type Type = super::GlFeedback;
    type ParentType = gst_gl::GLFilter;
}

impl ObjectImpl for GlFeedback {
    fn properties() -> &'static [glib::ParamSpec] {
        use once_cell::sync::Lazy;
        static PROPERTIES: Lazy<Vec<glib::ParamSpec>> = Lazy::new(|| {
            vec![
                glib::ParamSpecString::builder("fragment")
                    .nick("Fragment shader")
                    .blurb("GLSL fragment shader source (must declare tex and tex_accum samplers)")
                    .default_value(Some(DEFAULT_FRAGMENT))
                    .build(),
                glib::ParamSpecString::builder("uniforms")
                    .nick("Uniforms")
                    .blurb("Comma-separated key=value float uniforms (e.g. u_fade=0.04,u_opacity=0.5)")
                    .default_value(Some(""))
                    .build(),
            ]
        });
        PROPERTIES.as_ref()
    }

    fn set_property(&self, _id: usize, value: &glib::Value, pspec: &glib::ParamSpec) {
        match pspec.name() {
            "fragment" => {
                let frag = value.get::<Option<String>>().unwrap();
                self.props.lock().unwrap().fragment = frag;
                // Mark shader as needing recompile — actual GL compilation
                // happens in filter_texture on the GL thread
                self.props.lock().unwrap().shader_dirty = true;
            }
            "uniforms" => {
                let raw = value.get::<Option<String>>().unwrap().unwrap_or_default();
                let mut uniforms = Vec::new();
                for pair in raw.split(',') {
                    let pair = pair.trim();
                    if let Some((k, v)) = pair.split_once('=') {
                        if let Ok(val) = v.trim().parse::<f32>() {
                            uniforms.push((k.trim().to_string(), val));
                        }
                    }
                }
                self.props.lock().unwrap().uniforms = uniforms;
            }
            _ => {}
        }
    }

    fn property(&self, _id: usize, pspec: &glib::ParamSpec) -> glib::Value {
        match pspec.name() {
            "fragment" => self.props.lock().unwrap().fragment.clone().to_value(),
            "uniforms" => {
                let u = &self.props.lock().unwrap().uniforms;
                let s: String = u
                    .iter()
                    .map(|(k, v)| format!("{k}={v}"))
                    .collect::<Vec<_>>()
                    .join(",");
                s.to_value()
            }
            _ => unimplemented!(),
        }
    }
}

impl GstObjectImpl for GlFeedback {}

impl ElementImpl for GlFeedback {
    fn metadata() -> Option<&'static gst::subclass::ElementMetadata> {
        static ELEMENT_METADATA: std::sync::OnceLock<gst::subclass::ElementMetadata> =
            std::sync::OnceLock::new();
        Some(ELEMENT_METADATA.get_or_init(|| {
            gst::subclass::ElementMetadata::new(
                "GL Temporal Feedback",
                "Filter/Effect/Video",
                "Applies temporal feedback using ping-pong FBOs. Provides tex_accum uniform.",
                "Hapax System <noreply@hapax.dev>",
            )
        }))
    }
}

impl BaseTransformImpl for GlFeedback {
    const MODE: gst_base::subclass::base_transform::BaseTransformMode =
        gst_base::subclass::base_transform::BaseTransformMode::NeverInPlace;
    const PASSTHROUGH_ON_SAME_CAPS: bool = false;
    const TRANSFORM_IP_ON_PASSTHROUGH: bool = false;
}

impl GLBaseFilterImpl for GlFeedback {
    fn gl_start(&self) -> Result<(), gst::LoggableError> {
        gst_gl::subclass::prelude::GLBaseFilterImplExt::parent_gl_start(self)?;

        let filter = self.obj();
        let context = gst_gl::prelude::GLBaseFilterExt::context(&*filter)
            .ok_or_else(|| gst::loggable_error!(gst::CAT_RUST, "no GL context"))?;

        // Load GL function pointers from the GStreamer GL context
        gl::load_with(|name| context.proc_address(name) as *const _);

        // Compile default shader
        let shader = self.compile_shader(&context, DEFAULT_FRAGMENT)?;

        *self.state.lock().unwrap() = Some(State {
            accum_textures: [0; 2],
            accum_fbos: [0; 2],
            current_idx: 0,
            width: 0,
            height: 0,
            shader,
        });

        Ok(())
    }

    fn gl_stop(&self) {
        if let Some(state) = self.state.lock().unwrap().take() {
            unsafe {
                if state.accum_textures[0] != 0 {
                    gl::DeleteTextures(2, state.accum_textures.as_ptr());
                    gl::DeleteFramebuffers(2, state.accum_fbos.as_ptr());
                }
            }
        }
        gst_gl::subclass::prelude::GLBaseFilterImplExt::parent_gl_stop(self);
    }
}

impl GLFilterImpl for GlFeedback {
    const MODE: GLFilterMode = GLFilterMode::Texture;

    fn set_caps(
        &self,
        incaps: &gst::Caps,
        outcaps: &gst::Caps,
    ) -> Result<(), gst::LoggableError> {
        gst_gl::subclass::prelude::GLFilterImplExt::parent_set_caps(self, incaps, outcaps)?;

        let info = gst_video::VideoInfo::from_caps(incaps)
            .map_err(|_| gst::loggable_error!(gst::CAT_RUST, "bad video caps"))?;
        let w = info.width() as i32;
        let h = info.height() as i32;

        let mut guard = self.state.lock().unwrap();
        if let Some(state) = guard.as_mut() {
            if state.width != w || state.height != h {
                self.reallocate_accum(state, w, h);
            }
        }

        Ok(())
    }

    fn filter_texture(
        &self,
        input: &gst_gl::GLMemory,
        output: &gst_gl::GLMemory,
    ) -> Result<(), gst::LoggableError> {
        let filter = self.obj();

        // Lazy-recompile shader on GL thread if fragment property changed
        {
            let mut props = self.props.lock().unwrap();
            if props.shader_dirty {
                props.shader_dirty = false;
                if let Some(frag_src) = props.fragment.clone() {
                    drop(props); // release lock before GL calls
                    if let Some(context) = gst_gl::prelude::GLBaseFilterExt::context(&*filter) {
                        match self.compile_shader(&context, &frag_src) {
                            Ok(new_shader) => {
                                self.state.lock().unwrap().as_mut().unwrap().shader = new_shader;
                            }
                            Err(_e) => {
                                // Keep existing shader on failure — don't crash
                            }
                        }
                    }
                }
            }
        }

        // Snapshot what we need from state (minimise lock duration)
        let (prev_tex, next_fbo, next_idx, uniforms) = {
            let guard = self.state.lock().unwrap();
            let s = guard.as_ref().unwrap();
            let prev = s.accum_textures[s.current_idx];
            let next = 1 - s.current_idx;
            let props = self.props.lock().unwrap();
            (prev, s.accum_fbos[next], next, props.uniforms.clone())
        };

        // Borrow shader for the render callback
        let shader = {
            let guard = self.state.lock().unwrap();
            guard.as_ref().unwrap().shader.clone()
        };

        // Bind tex_accum on unit 1 BEFORE render_to_target_with_shader.
        // GStreamer's render_to_target_with_shader binds the input texture on unit 0
        // as "tex", sets up the FBO, draws the fullscreen quad, and returns.
        // We pre-bind our accumulation texture on unit 1 so the shader can read it.
        unsafe {
            gl::ActiveTexture(gl::TEXTURE1);
            gl::BindTexture(gl::TEXTURE_2D, prev_tex);
        }
        shader.set_uniform_1i("tex_accum", 1);

        // Set float uniforms
        for (name, val) in &uniforms {
            shader.set_uniform_1f(name, *val);
        }

        // render_to_target_with_shader handles: FBO bind, tex on unit 0, quad draw
        filter.render_to_target_with_shader(input, output, &shader);

        // Pass 2: blit output into next accumulation buffer
        unsafe {
            let out_tex = output.texture_id();
            let w = output.texture_width();
            let h = output.texture_height();

            let mut read_fbo = 0u32;
            gl::GenFramebuffers(1, &mut read_fbo);
            gl::BindFramebuffer(gl::READ_FRAMEBUFFER, read_fbo);
            gl::FramebufferTexture2D(
                gl::READ_FRAMEBUFFER,
                gl::COLOR_ATTACHMENT0,
                gl::TEXTURE_2D,
                out_tex,
                0,
            );
            gl::BindFramebuffer(gl::DRAW_FRAMEBUFFER, next_fbo);
            gl::BlitFramebuffer(0, 0, w, h, 0, 0, w, h, gl::COLOR_BUFFER_BIT, gl::NEAREST);
            gl::BindFramebuffer(gl::FRAMEBUFFER, 0);
            gl::DeleteFramebuffers(1, &read_fbo);
        }

        // Advance ping-pong index
        self.state.lock().unwrap().as_mut().unwrap().current_idx = next_idx;

        Ok(())
    }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

impl GlFeedback {
    fn compile_shader(
        &self,
        context: &gst_gl::GLContext,
        frag_src: &str,
    ) -> Result<gst_gl::GLShader, gst::LoggableError> {
        let shader = gst_gl::GLShader::new(context);

        let vert = gst_gl::GLSLStage::new_default_vertex(context);
        shader
            .compile_attach_stage(&vert)
            .map_err(|e| gst::loggable_error!(gst::CAT_RUST, "vertex: {e}"))?;

        let frag = gst_gl::GLSLStage::with_string(
            context,
            gl::FRAGMENT_SHADER,
            gst_gl::GLSLVersion::None,
            gst_gl::GLSLProfile::empty(),
            frag_src,
        );
        shader
            .compile_attach_stage(&frag)
            .map_err(|e| gst::loggable_error!(gst::CAT_RUST, "fragment: {e}"))?;

        shader
            .link()
            .map_err(|e| gst::loggable_error!(gst::CAT_RUST, "link: {e}"))?;

        Ok(shader)
    }

    fn reallocate_accum(&self, state: &mut State, w: i32, h: i32) {
        unsafe {
            if state.accum_textures[0] != 0 {
                gl::DeleteTextures(2, state.accum_textures.as_ptr());
                gl::DeleteFramebuffers(2, state.accum_fbos.as_ptr());
            }
            gl::GenTextures(2, state.accum_textures.as_mut_ptr());
            gl::GenFramebuffers(2, state.accum_fbos.as_mut_ptr());
            for i in 0..2 {
                gl::BindTexture(gl::TEXTURE_2D, state.accum_textures[i]);
                gl::TexImage2D(
                    gl::TEXTURE_2D,
                    0,
                    gl::RGBA8 as i32,
                    w,
                    h,
                    0,
                    gl::RGBA,
                    gl::UNSIGNED_BYTE,
                    std::ptr::null(),
                );
                gl::TexParameteri(
                    gl::TEXTURE_2D,
                    gl::TEXTURE_MIN_FILTER,
                    gl::LINEAR as i32,
                );
                gl::TexParameteri(
                    gl::TEXTURE_2D,
                    gl::TEXTURE_MAG_FILTER,
                    gl::LINEAR as i32,
                );
                gl::TexParameteri(
                    gl::TEXTURE_2D,
                    gl::TEXTURE_WRAP_S,
                    gl::CLAMP_TO_EDGE as i32,
                );
                gl::TexParameteri(
                    gl::TEXTURE_2D,
                    gl::TEXTURE_WRAP_T,
                    gl::CLAMP_TO_EDGE as i32,
                );
                gl::BindFramebuffer(gl::FRAMEBUFFER, state.accum_fbos[i]);
                gl::FramebufferTexture2D(
                    gl::FRAMEBUFFER,
                    gl::COLOR_ATTACHMENT0,
                    gl::TEXTURE_2D,
                    state.accum_textures[i],
                    0,
                );
            }
            // Clear both to black
            for i in 0..2 {
                gl::BindFramebuffer(gl::FRAMEBUFFER, state.accum_fbos[i]);
                gl::ClearColor(0.0, 0.0, 0.0, 1.0);
                gl::Clear(gl::COLOR_BUFFER_BIT);
            }
            gl::BindFramebuffer(gl::FRAMEBUFFER, 0);
            gl::BindTexture(gl::TEXTURE_2D, 0);
        }
        state.width = w;
        state.height = h;
        state.current_idx = 0;
        gst::info!(gst::CAT_RUST, "Allocated accum textures {}x{}", w, h);
    }
}
