// Temporal feedback filter — FBO ping-pong for trail/ghost/datamosh effects.
//
// In filter_texture, we:
//   1. Bind the accumulation texture as a second sampler (tex_accum)
//   2. Run a shader: output = mix(current, accum * decay_color, feedback_amount)
//   3. Copy output to the accumulation texture for the next frame
//
// The accumulation texture persists across frames, creating compounding trails.

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

// Generated GL bindings
mod gl {
    include!(concat!(env!("OUT_DIR"), "/gl_bindings.rs"));
}

static CAT: LazyLock<gst::DebugCategory> = LazyLock::new(|| {
    gst::DebugCategory::new(
        "temporalfx",
        gst::DebugColorFlags::empty(),
        Some("GL Temporal Feedback Filter"),
    )
});

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(i32)]
enum BlendMode {
    #[default]
    Add = 0,
    Multiply = 1,
    Difference = 2,
    SourceOver = 3,
}

#[derive(Debug, Clone)]
struct Settings {
    feedback_amount: f32,
    decay_r: f32,
    decay_g: f32,
    decay_b: f32,
    hue_shift: f32,
    blend_mode: BlendMode,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            feedback_amount: 0.0,
            decay_r: 0.95,
            decay_g: 0.95,
            decay_b: 0.95,
            hue_shift: 0.0,
            blend_mode: BlendMode::Add,
        }
    }
}

struct GlState {
    shader: gst_gl::GLShader,
    gl: gl::Gles2,
    accum_tex: u32,
    width: i32,
    height: i32,
}

#[derive(Default)]
pub struct TemporalFx {
    settings: Mutex<Settings>,
    gl_state: Mutex<Option<GlState>>,
}

const FEEDBACK_FRAG: &str = r#"
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_accum;

uniform float u_feedback;
uniform float u_decay_r;
uniform float u_decay_g;
uniform float u_decay_b;
uniform float u_hue_shift;
uniform int u_blend_mode;

vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0/3.0, 2.0/3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0/3.0, 1.0/3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
    vec4 current = texture2D(tex, v_texcoord);

    if (u_feedback < 0.001) {
        gl_FragColor = current;
        return;
    }

    vec4 accum = texture2D(tex_accum, v_texcoord);
    accum.rgb *= vec3(u_decay_r, u_decay_g, u_decay_b);

    if (abs(u_hue_shift) > 0.1) {
        vec3 hsv = rgb2hsv(accum.rgb);
        hsv.x = fract(hsv.x + u_hue_shift / 360.0);
        accum.rgb = hsv2rgb(hsv);
    }

    vec3 result;
    if (u_blend_mode == 0) {
        // Additive
        result = current.rgb + accum.rgb * u_feedback;
    } else if (u_blend_mode == 1) {
        // Multiply
        result = current.rgb * (1.0 - u_feedback) + current.rgb * accum.rgb * u_feedback;
    } else if (u_blend_mode == 2) {
        // Difference
        result = current.rgb + abs(current.rgb - accum.rgb) * u_feedback;
    } else {
        // Source-over
        result = mix(current.rgb, accum.rgb, u_feedback);
    }

    gl_FragColor = vec4(clamp(result, 0.0, 1.0), 1.0);
}
"#;

// GObject wrapper type
mod imp_types {
    use super::*;

    glib::wrapper! {
        pub struct TemporalFx(ObjectSubclass<super::TemporalFx>)
            @extends gst_gl::GLFilter, gst_gl::GLBaseFilter, gst_base::BaseTransform, gst::Element, gst::Object;
    }
}

#[glib::object_subclass]
impl ObjectSubclass for TemporalFx {
    const NAME: &'static str = "GstTemporalFx";
    type Type = imp_types::TemporalFx;
    type ParentType = gst_gl::GLFilter;
}

impl ObjectImpl for TemporalFx {
    fn properties() -> &'static [glib::ParamSpec] {
        static PROPERTIES: LazyLock<Vec<glib::ParamSpec>> = LazyLock::new(|| {
            vec![
                glib::ParamSpecFloat::builder("feedback-amount")
                    .nick("Feedback Amount")
                    .blurb("How much of the accumulated frame feeds back (0=none, 1=full)")
                    .minimum(0.0)
                    .maximum(1.0)
                    .default_value(0.0)
                    .build(),
                glib::ParamSpecFloat::builder("decay-r")
                    .nick("Decay Red")
                    .blurb("Red channel decay per frame")
                    .minimum(0.0)
                    .maximum(1.0)
                    .default_value(0.95)
                    .build(),
                glib::ParamSpecFloat::builder("decay-g")
                    .nick("Decay Green")
                    .blurb("Green channel decay per frame")
                    .minimum(0.0)
                    .maximum(1.0)
                    .default_value(0.95)
                    .build(),
                glib::ParamSpecFloat::builder("decay-b")
                    .nick("Decay Blue")
                    .blurb("Blue channel decay per frame")
                    .minimum(0.0)
                    .maximum(1.0)
                    .default_value(0.95)
                    .build(),
                glib::ParamSpecFloat::builder("hue-shift")
                    .nick("Hue Shift")
                    .blurb("Hue rotation applied to accumulated frame (degrees)")
                    .minimum(-360.0)
                    .maximum(360.0)
                    .default_value(0.0)
                    .build(),
                glib::ParamSpecInt::builder("blend-mode")
                    .nick("Blend Mode")
                    .blurb("0=add, 1=multiply, 2=difference, 3=source-over")
                    .minimum(0)
                    .maximum(3)
                    .default_value(0)
                    .build(),
            ]
        });
        PROPERTIES.as_ref()
    }

    fn set_property(&self, _id: usize, value: &glib::Value, pspec: &glib::ParamSpec) {
        let mut settings = self.settings.lock().unwrap();
        match pspec.name() {
            "feedback-amount" => settings.feedback_amount = value.get().unwrap(),
            "decay-r" => settings.decay_r = value.get().unwrap(),
            "decay-g" => settings.decay_g = value.get().unwrap(),
            "decay-b" => settings.decay_b = value.get().unwrap(),
            "hue-shift" => settings.hue_shift = value.get().unwrap(),
            "blend-mode" => {
                settings.blend_mode = match value.get::<i32>().unwrap() {
                    1 => BlendMode::Multiply,
                    2 => BlendMode::Difference,
                    3 => BlendMode::SourceOver,
                    _ => BlendMode::Add,
                };
            }
            _ => {}
        }
    }

    fn property(&self, _id: usize, pspec: &glib::ParamSpec) -> glib::Value {
        let settings = self.settings.lock().unwrap();
        match pspec.name() {
            "feedback-amount" => settings.feedback_amount.to_value(),
            "decay-r" => settings.decay_r.to_value(),
            "decay-g" => settings.decay_g.to_value(),
            "decay-b" => settings.decay_b.to_value(),
            "hue-shift" => settings.hue_shift.to_value(),
            "blend-mode" => (settings.blend_mode as i32).to_value(),
            _ => unimplemented!(),
        }
    }
}

impl GstObjectImpl for TemporalFx {}

impl ElementImpl for TemporalFx {
    fn metadata() -> Option<&'static gst::subclass::ElementMetadata> {
        static ELEMENT_METADATA: LazyLock<gst::subclass::ElementMetadata> = LazyLock::new(|| {
            gst::subclass::ElementMetadata::new(
                "Temporal Feedback Filter",
                "Filter/Effect/Video",
                "GPU temporal feedback with FBO ping-pong for trails, ghosting, datamosh",
                "hapax",
            )
        });
        Some(&*ELEMENT_METADATA)
    }
}

impl BaseTransformImpl for TemporalFx {
    const MODE: BaseTransformMode = BaseTransformMode::NeverInPlace;
    const PASSTHROUGH_ON_SAME_CAPS: bool = false;
    const TRANSFORM_IP_ON_PASSTHROUGH: bool = false;
}

impl GLBaseFilterImpl for TemporalFx {
    fn gl_start(&self) -> Result<(), gst::LoggableError> {
        let filter = self.obj();
        let context = gst_gl::prelude::GLBaseFilterExt::context(&*filter).unwrap();

        // Load GL function pointers
        let gl = gl::Gles2::load_with(|name| context.proc_address(name) as *const _);

        // Compile feedback shader
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
            &[FEEDBACK_FRAG],
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

        gst::debug!(CAT, imp = self, "Feedback shader compiled and linked");

        *self.gl_state.lock().unwrap() = Some(GlState {
            shader,
            gl,
            accum_tex: 0,
            width: 0,
            height: 0,
        });

        self.parent_gl_start()
    }

    fn gl_stop(&self) {
        if let Some(state) = self.gl_state.lock().unwrap().take() {
            if state.accum_tex != 0 {
                unsafe {
                    state.gl.DeleteTextures(1, &state.accum_tex);
                }
            }
        }
        self.parent_gl_stop();
    }
}

impl GLFilterImpl for TemporalFx {
    const MODE: GLFilterMode = GLFilterMode::Texture;

    fn filter_texture(
        &self,
        input: &gst_gl::GLMemory,
        output: &gst_gl::GLMemory,
    ) -> Result<(), gst::LoggableError> {
        let filter = self.obj();
        let settings = self.settings.lock().unwrap().clone();

        let width = input.texture_width();
        let height = input.texture_height();

        let mut gl_state = self.gl_state.lock().unwrap();
        let state = gl_state.as_mut().ok_or_else(|| {
            gst::loggable_error!(CAT, "GL state not initialized")
        })?;

        // Create or resize accumulation texture
        if state.accum_tex == 0 || state.width != width || state.height != height {
            if state.accum_tex != 0 {
                unsafe { state.gl.DeleteTextures(1, &state.accum_tex); }
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
            state.accum_tex = tex;
            state.width = width;
            state.height = height;
            gst::debug!(CAT, imp = self, "Created accum texture {tex} ({width}x{height})");
        }

        let accum_tex = state.accum_tex;
        let shader = state.shader.clone();
        let gl_ref = &state.gl;

        // Set uniforms
        shader.set_uniform_1f("u_feedback", settings.feedback_amount);
        shader.set_uniform_1f("u_decay_r", settings.decay_r);
        shader.set_uniform_1f("u_decay_g", settings.decay_g);
        shader.set_uniform_1f("u_decay_b", settings.decay_b);
        shader.set_uniform_1f("u_hue_shift", settings.hue_shift);
        shader.set_uniform_1i("u_blend_mode", settings.blend_mode as i32);

        // Bind accumulation texture to unit 1
        unsafe {
            gl_ref.ActiveTexture(gl::TEXTURE1);
            gl_ref.BindTexture(gl::TEXTURE_2D, accum_tex);
        }
        shader.set_uniform_1i("tex_accum", 1);

        // Render with shader
        filter.render_to_target_with_shader(input, output, &shader);

        // Copy output to accumulation texture for next frame
        // (read from the FBO that render_to_target just wrote to)
        unsafe {
            gl_ref.BindTexture(gl::TEXTURE_2D, accum_tex);
            // CopyTexSubImage2D reads from the currently bound read framebuffer
            gl_ref.CopyTexSubImage2D(gl::TEXTURE_2D, 0, 0, 0, 0, 0, width, height);
            gl_ref.BindTexture(gl::TEXTURE_2D, 0);
            gl_ref.ActiveTexture(gl::TEXTURE0);
        }

        drop(gl_state);
        self.parent_filter_texture(input, output)
    }
}

pub fn register(plugin: &gst::Plugin) -> Result<(), glib::BoolError> {
    gst::Element::register(
        Some(plugin),
        "temporalfx",
        gst::Rank::NONE,
        imp_types::TemporalFx::static_type(),
    )
}
