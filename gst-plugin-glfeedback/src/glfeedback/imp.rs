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
    /// Cached FBO for blit read operations (avoids per-frame alloc/free).
    blit_read_fbo: u32,
    /// Which accumulation buffer holds the "previous frame" output.
    current_idx: usize,
    /// Resolution (for reallocation on caps change).
    width: i32,
    height: i32,
    /// Compiled GL shader program.
    shader: gst_gl::GLShader,
    /// When true, seed both accum buffers from the current input frame
    /// before the next shader pass. Set on shader recompile to avoid
    /// the new shader reading stale accum data from the old shader.
    seed_accum_from_input: bool,
}

/// Properties exposed to GStreamer (set from Python via set_property).
#[derive(Default)]
struct Props {
    fragment: Option<String>,
    uniforms: Vec<(String, f32)>,
    shader_dirty: bool,
    is_passthrough: bool,  // true when shader is DEFAULT_FRAGMENT (skip accum blit)
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
                // A shader is passthrough (skip accum blit) if it does NOT
                // reference tex_accum.  Previous exact-string comparison broke
                // when the Python PASSTHROUGH_SHADER diverged in whitespace /
                // #version from DEFAULT_FRAGMENT, leaving is_passthrough=false
                // for all 24 slots and causing a 24-blit cascade whose RGBA8
                // rounding errors produced the sawtooth/stripe artifact.
                let is_pt = frag.as_ref().map_or(true, |f| !f.contains("tex_accum"));
                let mut props = self.props.lock().unwrap();
                if props.fragment != frag {
                    props.fragment = frag;
                    props.is_passthrough = is_pt;
                    props.shader_dirty = true;
                }
                // else: identical value, no recompile, no accum clear
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
    const TRANSFORM_IP_ON_PASSTHROUGH: bool = true;
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
            blit_read_fbo: 0,
            current_idx: 0,
            width: 0,
            height: 0,
            shader,
            seed_accum_from_input: false,
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
                if state.blit_read_fbo != 0 {
                    gl::DeleteFramebuffers(1, &state.blit_read_fbo);
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
        // NOTE: Do NOT allocate GL resources here — set_caps runs on the
        // streaming thread which has no GL context.  Accum textures are
        // lazily (re)allocated in filter_texture on the GL thread.
        Ok(())
    }

    fn filter_texture(
        &self,
        input: &gst_gl::GLMemory,
        output: &gst_gl::GLMemory,
    ) -> Result<(), gst::LoggableError> {
        let filter = self.obj();

        // Lazy (re)allocate accum textures on the GL thread.
        // set_caps runs on the streaming thread (no GL context), so we
        // detect resolution changes here where GL calls are safe.
        {
            let w = output.texture_width();
            let h = output.texture_height();
            let mut guard = self.state.lock().unwrap();
            if let Some(state) = guard.as_mut() {
                if state.width != w || state.height != h {
                    self.reallocate_accum(state, w, h);
                }
            }
        }

        // Lazy-recompile shader on GL thread if fragment property changed
        {
            let mut props = self.props.lock().unwrap();
            gst::trace!(gst::CAT_RUST, "shader_dirty={}", props.shader_dirty);
            if props.shader_dirty {
                gst::info!(gst::CAT_RUST, "shader_dirty detected — recompiling");
                props.shader_dirty = false;
                if let Some(frag_src) = props.fragment.clone() {
                    drop(props); // release lock before GL calls
                    if let Some(context) = gst_gl::prelude::GLBaseFilterExt::context(&*filter) {
                        match self.compile_shader(&context, &frag_src) {
                            Ok(new_shader) => {
                                let mut guard = self.state.lock().unwrap();
                                let s = guard.as_mut().unwrap();
                                s.shader = new_shader;
                                // 2026-05-04: Seed accum from the current input
                                // frame on the next render pass. Preserving stale
                                // accum from the prior shader caused visible flashes
                                // (the new shader interprets old accum data as garbage).
                                // Clearing to black also flashed. Seeding from input
                                // gives the new shader a clean, visually-coherent
                                // starting frame.
                                s.seed_accum_from_input = true;
                                drop(guard);
                                gst::info!(gst::CAT_RUST, "Shader recompiled OK ({} chars), accum will seed from input", frag_src.len());
                            }
                            Err(e) => {
                                gst::error!(gst::CAT_RUST, "Shader recompile FAILED: {:?}", e);
                                // Log first 200 chars of fragment source for debugging
                                let preview: String = frag_src.chars().take(200).collect();
                                gst::error!(gst::CAT_RUST, "Fragment preview: {}", preview);
                            }
                        }
                    }
                }
            }
        }

        // Check if this is a passthrough shader (skip accum blit to avoid artifacts)
        let skip_blit = self.props.lock().unwrap().is_passthrough;

        // Seed accum from input if flagged (shader was just recompiled)
        {
            let mut guard = self.state.lock().unwrap();
            let s = guard.as_mut().unwrap();
            if s.seed_accum_from_input {
                s.seed_accum_from_input = false;
                let in_tex = input.texture_id();
                let w = input.texture_width();
                let h = input.texture_height();
                unsafe {
                    gl::BindFramebuffer(gl::READ_FRAMEBUFFER, s.blit_read_fbo);
                    gl::FramebufferTexture2D(
                        gl::READ_FRAMEBUFFER,
                        gl::COLOR_ATTACHMENT0,
                        gl::TEXTURE_2D,
                        in_tex,
                        0,
                    );
                    for i in 0..2 {
                        gl::BindFramebuffer(gl::DRAW_FRAMEBUFFER, s.accum_fbos[i]);
                        gl::BlitFramebuffer(0, 0, w, h, 0, 0, w, h, gl::COLOR_BUFFER_BIT, gl::NEAREST);
                    }
                    gl::BindFramebuffer(gl::FRAMEBUFFER, 0);
                }
                gst::info!(gst::CAT_RUST, "Accum seeded from input frame ({}x{})", w, h);
            }
        }

        // Snapshot what we need from state (minimise lock duration)
        let (prev_tex, next_fbo, next_idx, blit_fbo, uniforms) = {
            let guard = self.state.lock().unwrap();
            let s = guard.as_ref().unwrap();
            let prev = s.accum_textures[s.current_idx];
            let next = 1 - s.current_idx;
            let blit = s.blit_read_fbo;
            let props = self.props.lock().unwrap();
            (prev, s.accum_fbos[next], next, blit, props.uniforms.clone())
        };

        // Borrow shader for the render callback
        let shader = {
            let guard = self.state.lock().unwrap();
            guard.as_ref().unwrap().shader.clone()
        };

        // render_to_target binds the output FBO, sets viewport, then calls
        // our closure.  Without this wrapper filter_texture has NO FBO bound
        // and draw_fullscreen_quad() renders to framebuffer 0 (black).
        let prev_tex_copy = prev_tex;
        let uniforms_copy = uniforms;
        let shader_copy = shader.clone();
        filter.render_to_target(input, output, move |filt, in_tex| {
            shader_copy.use_();

            // Set attribute locations so draw_fullscreen_quad finds them
            let pos_loc = shader_copy.attribute_location("a_position");
            let tex_loc = shader_copy.attribute_location("a_texcoord");
            unsafe {
                // Access raw GstGLFilter struct to set attribute locations
                // that draw_fullscreen_quad reads for its VAO setup.
                let obj_ptr = filt.as_ptr();
                let raw = obj_ptr as *mut gst_gl::ffi::GstGLFilter;
                (*raw).draw_attr_position_loc = pos_loc;
                (*raw).draw_attr_texture_loc = tex_loc;
            }

            // tex (current frame) on unit 0
            unsafe {
                gl::ActiveTexture(gl::TEXTURE0);
                gl::BindTexture(gl::TEXTURE_2D, in_tex.texture_id());
            }
            shader_copy.set_uniform_1i("tex", 0);

            // tex_accum (previous frame) on unit 1
            unsafe {
                gl::ActiveTexture(gl::TEXTURE1);
                gl::BindTexture(gl::TEXTURE_2D, prev_tex_copy);
            }
            shader_copy.set_uniform_1i("tex_accum", 1);

            // Float uniforms
            for (name, val) in &uniforms_copy {
                shader_copy.set_uniform_1f(name, *val);
            }

            // Draw fullscreen quad — GStreamer's GLFilter provides the geometry
            filt.draw_fullscreen_quad();

            true
        }).map_err(|e| gst::loggable_error!(gst::CAT_RUST, "render_to_target: {e}"))?;

        // Pass 2: blit output into next accumulation buffer (cached FBO)
        // Skip for passthrough shaders — they don't use tex_accum and the
        // repeated blit accumulates rounding artifacts visible as a faint
        // sawtooth/stripe pattern.
        if skip_blit {
            return Ok(());
        }
        unsafe {
            let out_tex = output.texture_id();
            let w = output.texture_width();
            let h = output.texture_height();

            let read_fbo = blit_fbo;
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
            gst_gl::GLSLProfile::ES | gst_gl::GLSLProfile::COMPATIBILITY,
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
            if state.blit_read_fbo != 0 {
                gl::DeleteFramebuffers(1, &state.blit_read_fbo);
            }
            gl::GenTextures(2, state.accum_textures.as_mut_ptr());
            gl::GenFramebuffers(2, state.accum_fbos.as_mut_ptr());
            gl::GenFramebuffers(1, &mut state.blit_read_fbo);
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
            // Clear both to opaque black on initial allocation.
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
