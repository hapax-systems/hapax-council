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
    pub timestamp: f64,
}

// --- Smoothed state for GPU uniforms ---

#[derive(Debug, Clone)]
pub struct SmoothedParams {
    pub speed: f32,
    pub turbulence: f32,
    pub color_warmth: f32,
    pub brightness: f32,
    pub stance: Stance,
}

impl Default for SmoothedParams {
    fn default() -> Self {
        Self {
            speed: 0.08,
            turbulence: 0.1,
            color_warmth: 0.0,
            brightness: 0.25,
            stance: Stance::Nominal,
        }
    }
}

impl SmoothedParams {
    /// Lerp toward target values over dt seconds with ~2s smoothing.
    pub fn lerp_toward(&mut self, target: &AmbientParams, target_stance: Stance, dt: f32) {
        let alpha = 1.0 - (-dt / 2.0_f32).exp(); // ~2s time constant
        self.speed += (target.speed - self.speed) * alpha;
        self.turbulence += (target.turbulence - self.turbulence) * alpha;
        self.color_warmth += (target.color_warmth - self.color_warmth) * alpha;
        self.brightness += (target.brightness - self.brightness) * alpha;
        self.stance = target_stance;
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
