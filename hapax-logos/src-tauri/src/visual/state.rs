use serde::Deserialize;
use std::collections::HashMap;
use std::path::Path;
use std::time::Instant;

// --- Stimmung (from shared/stimmung.py) ---

#[derive(Debug, Clone, Copy, Default, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Stance {
    #[default]
    Nominal,
    Cautious,
    Degraded,
    Critical,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct DimensionReading {
    #[serde(default)]
    pub value: f32,
    #[serde(default = "default_trend")]
    pub trend: String,
    #[serde(default)]
    pub freshness_s: f32,
}

fn default_trend() -> String {
    "stable".into()
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct SystemStimmung {
    #[serde(default)]
    pub health: DimensionReading,
    #[serde(default)]
    pub resource_pressure: DimensionReading,
    #[serde(default)]
    pub error_rate: DimensionReading,
    #[serde(default)]
    pub processing_throughput: DimensionReading,
    #[serde(default)]
    pub perception_confidence: DimensionReading,
    #[serde(default)]
    pub llm_cost_pressure: DimensionReading,
    #[serde(default)]
    pub overall_stance: Stance,
    #[serde(default)]
    pub timestamp: f64,
}

// --- Visual Layer State (from agents/visual_layer_state.py) ---

#[derive(Debug, Clone, Default, Deserialize)]
pub struct AmbientParams {
    #[serde(default = "default_speed")]
    pub speed: f32,
    #[serde(default = "default_turbulence")]
    pub turbulence: f32,
    #[serde(default)]
    pub color_warmth: f32,
    #[serde(default = "default_brightness")]
    pub brightness: f32,
    #[serde(default)]
    pub audio_energy: f32,
    #[serde(default = "default_noise_variant")]
    pub noise_variant: String,
}

fn default_noise_variant() -> String {
    "fbm".into()
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct EnvironmentalColor {
    #[serde(default)]
    pub hue_shift: f32,
    #[serde(default = "default_one")]
    pub chroma_scale: f32,
    #[serde(default)]
    pub lightness_bias: f32,
    #[serde(default)]
    pub source: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct TransitionMeta {
    #[serde(default)]
    pub from_state: String,
    #[serde(default)]
    pub to_state: String,
    #[serde(default)]
    pub started_at: f64,
    #[serde(default = "default_transition_duration")]
    pub duration_s: f32,
    #[serde(default = "default_transition_style")]
    pub style: String,
}

fn default_transition_duration() -> f32 {
    2.0
}
fn default_transition_style() -> String {
    "breathe".into()
}

fn default_speed() -> f32 {
    0.08
}
fn default_turbulence() -> f32 {
    0.1
}
fn default_brightness() -> f32 {
    0.25
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct SignalEntry {
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub severity: f32,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub detail: String,
    #[serde(default)]
    pub source_id: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct TemporalContext {
    #[serde(default)]
    pub trend_flow: f32,
    #[serde(default)]
    pub trend_audio: f32,
    #[serde(default)]
    pub trend_hr: f32,
    #[serde(default)]
    pub perception_age_s: f32,
    #[serde(default)]
    pub ring_depth: i32,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct BiometricState {
    #[serde(default)]
    pub heart_rate_bpm: i32,
    #[serde(default)]
    pub stress_elevated: bool,
    #[serde(default)]
    pub physiological_load: f32,
    #[serde(default = "default_one")]
    pub sleep_quality: f32,
    #[serde(default = "default_unknown")]
    pub watch_activity: String,
}

fn default_one() -> f32 {
    1.0
}
fn default_unknown() -> String {
    "unknown".into()
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct VisualLayerState {
    #[serde(default)]
    pub display_state: String,
    #[serde(default)]
    pub zone_opacities: HashMap<String, f32>,
    #[serde(default)]
    pub signals: HashMap<String, Vec<SignalEntry>>,
    #[serde(default)]
    pub ambient_params: AmbientParams,
    #[serde(default)]
    pub stimmung_stance: String,
    #[serde(default)]
    pub temporal_context: TemporalContext,
    #[serde(default)]
    pub biometrics: BiometricState,
    #[serde(default)]
    pub environmental_color: EnvironmentalColor,
    #[serde(default)]
    pub transition: TransitionMeta,
    #[serde(default = "default_half")]
    pub operator_x: f32,
    #[serde(default = "default_half")]
    pub operator_y: f32,
    #[serde(default)]
    pub timestamp: f64,
}

fn default_half() -> f32 {
    0.5
}

// --- Smoothed state for GPU uniforms ---

#[derive(Debug, Clone)]
pub struct SmoothedParams {
    pub speed: f32,
    pub turbulence: f32,
    pub color_warmth: f32,
    pub brightness: f32,
    pub stance: Stance,
    // Corpora next: audio reactivity (fast lerp ~0.3s)
    pub audio_energy: f32,
    // Corpora next: environmental color (slow lerp ~10s)
    pub env_hue_shift: f32,
    pub env_chroma_scale: f32,
    pub env_lightness_bias: f32,
    // Corpora next: parallax (slow lerp ~3s)
    pub parallax_x: f32,
    pub parallax_y: f32,
    // Corpora next: transition progress (computed, not lerped)
    pub transition_progress: f32,
    pub transition_type: u32, // 0=none, 1=breathe, 2=expand, 3=contract, 4=drift
}

impl Default for SmoothedParams {
    fn default() -> Self {
        Self {
            speed: 0.08,
            turbulence: 0.1,
            color_warmth: 0.0,
            brightness: 0.25,
            stance: Stance::Nominal,
            audio_energy: 0.0,
            env_hue_shift: 0.0,
            env_chroma_scale: 1.0,
            env_lightness_bias: 0.0,
            parallax_x: 0.0,
            parallax_y: 0.0,
            transition_progress: 1.0,
            transition_type: 0,
        }
    }
}

impl SmoothedParams {
    /// Lerp toward target values over dt seconds.
    /// Different time constants for different categories:
    /// - Base params: ~2s (ambient feel)
    /// - Audio: ~0.3s (music-responsive)
    /// - Environment: ~10s (weather-gradual)
    /// - Parallax: ~3s (head-tracking smooth)
    pub fn lerp_toward(
        &mut self,
        target: &AmbientParams,
        target_stance: Stance,
        state: &VisualLayerState,
        dt: f32,
    ) {
        // ~2s time constant for base ambient params
        let alpha = 1.0 - (-dt / 2.0_f32).exp();
        self.speed += (target.speed - self.speed) * alpha;
        self.turbulence += (target.turbulence - self.turbulence) * alpha;
        self.color_warmth += (target.color_warmth - self.color_warmth) * alpha;
        self.brightness += (target.brightness - self.brightness) * alpha;
        self.stance = target_stance;

        // ~0.3s for audio (music-responsive)
        let audio_alpha = 1.0 - (-dt / 0.3_f32).exp();
        self.audio_energy += (target.audio_energy - self.audio_energy) * audio_alpha;

        // ~10s for environmental color (gradual like weather)
        let env_alpha = 1.0 - (-dt / 10.0_f32).exp();
        let env = &state.environmental_color;
        self.env_hue_shift += (env.hue_shift - self.env_hue_shift) * env_alpha;
        self.env_chroma_scale += (env.chroma_scale - self.env_chroma_scale) * env_alpha;
        self.env_lightness_bias += (env.lightness_bias - self.env_lightness_bias) * env_alpha;

        // ~3s for parallax (smooth head tracking)
        let parallax_alpha = 1.0 - (-dt / 3.0_f32).exp();
        let target_px = (state.operator_x - 0.5) * 2.0; // normalize to [-1, 1]
        let target_py = (state.operator_y - 0.5) * 2.0;
        self.parallax_x += (target_px - self.parallax_x) * parallax_alpha;
        self.parallax_y += (target_py - self.parallax_y) * parallax_alpha;

        // Transition progress: computed from wall clock, not lerped
        let t = &state.transition;
        if !t.from_state.is_empty() && t.started_at > 0.0 && t.duration_s > 0.0 {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64();
            let elapsed = (now - t.started_at) as f32;
            self.transition_progress = (elapsed / t.duration_s).clamp(0.0, 1.0);
            self.transition_type = match t.style.as_str() {
                "breathe" => 1,
                "expand" => 2,
                "contract" => 3,
                "drift" => 4,
                _ => 0,
            };
        } else {
            self.transition_progress = 1.0;
            self.transition_type = 0;
        }
    }
}

// --- State reader ---

const VISUAL_STATE_PATH: &str = "/dev/shm/hapax-compositor/visual-layer-state.json";
const STIMMUNG_PATH: &str = "/dev/shm/hapax-stimmung/state.json";

pub struct StateReader {
    pub visual: VisualLayerState,
    pub stimmung: SystemStimmung,
    pub smoothed: SmoothedParams,
    last_poll: Instant,
}

impl StateReader {
    pub fn new() -> Self {
        let mut reader = Self {
            visual: VisualLayerState::default(),
            stimmung: SystemStimmung::default(),
            smoothed: SmoothedParams::default(),
            last_poll: Instant::now(),
        };
        reader.poll_now();
        reader
    }

    /// Poll state files if enough time has elapsed (~500ms).
    pub fn poll(&mut self, dt: f32) {
        if self.last_poll.elapsed().as_millis() >= 500 {
            self.poll_now();
        }
        self.smoothed.lerp_toward(
            &self.visual.ambient_params,
            self.parse_stance(),
            &self.visual,
            dt,
        );
    }

    fn poll_now(&mut self) {
        self.last_poll = Instant::now();
        if let Some(v) = Self::read_json::<VisualLayerState>(VISUAL_STATE_PATH) {
            self.visual = v;
        }
        if let Some(s) = Self::read_json::<SystemStimmung>(STIMMUNG_PATH) {
            self.stimmung = s;
        }
    }

    fn parse_stance(&self) -> Stance {
        // Prefer stimmung file, fall back to visual layer state field
        if self.stimmung.timestamp > 0.0 {
            self.stimmung.overall_stance
        } else {
            match self.visual.stimmung_stance.as_str() {
                "cautious" => Stance::Cautious,
                "degraded" => Stance::Degraded,
                "critical" => Stance::Critical,
                _ => Stance::Nominal,
            }
        }
    }

    fn read_json<T: serde::de::DeserializeOwned>(path: &str) -> Option<T> {
        let p = Path::new(path);
        if !p.exists() {
            return None;
        }
        match std::fs::read_to_string(p) {
            Ok(data) => match serde_json::from_str(&data) {
                Ok(v) => Some(v),
                Err(e) => {
                    log::warn!("JSON parse error for {}: {}", path, e);
                    None
                }
            },
            Err(e) => {
                log::warn!("File read error for {}: {}", path, e);
                None
            }
        }
    }
}
