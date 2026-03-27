use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

// --- Studio Snapshot ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompositorStatus {
    #[serde(default)]
    pub state: String,
    #[serde(default)]
    pub cameras: HashMap<String, String>,
    #[serde(default)]
    pub active_cameras: u32,
    #[serde(default)]
    pub total_cameras: u32,
    #[serde(default)]
    pub output_device: String,
    #[serde(default)]
    pub resolution: String,
    #[serde(default)]
    pub recording_enabled: bool,
    #[serde(default)]
    pub recording_cameras: HashMap<String, String>,
    #[serde(default)]
    pub hls_enabled: bool,
    #[serde(default)]
    pub hls_url: String,
    #[serde(default)]
    pub consent_recording_allowed: bool,
    #[serde(default)]
    pub guest_present: bool,
    #[serde(default)]
    pub consent_phase: String,
    #[serde(default)]
    pub audio_energy_rms: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct StudioSnapshot {
    pub compositor: CompositorStatus,
    pub capture: CaptureStatus,
}

#[derive(Debug, Clone, Serialize)]
pub struct CaptureStatus {
    pub audio_recorder_active: bool,
    pub video_cameras: Vec<String>,
}

#[tauri::command]
pub fn get_studio() -> StudioSnapshot {
    let compositor_path = "/dev/shm/hapax-compositor/status.json";
    let compositor: CompositorStatus =
        read_json(compositor_path).unwrap_or_else(|| CompositorStatus {
            state: "offline".into(),
            cameras: HashMap::new(),
            active_cameras: 0,
            total_cameras: 0,
            output_device: String::new(),
            resolution: String::new(),
            recording_enabled: false,
            recording_cameras: HashMap::new(),
            hls_enabled: false,
            hls_url: String::new(),
            consent_recording_allowed: false,
            guest_present: false,
            consent_phase: "solo".into(),
            audio_energy_rms: 0.0,
        });

    StudioSnapshot {
        compositor,
        capture: CaptureStatus {
            audio_recorder_active: false,
            video_cameras: vec![],
        },
    }
}

// --- Studio Stream Info ---

#[derive(Debug, Clone, Serialize)]
pub struct StudioStreamInfo {
    pub hls_url: String,
    pub hls_enabled: bool,
    pub mjpeg_url: String,
    pub mjpeg_enabled: bool,
    pub enabled: bool,
}

#[tauri::command]
pub fn get_studio_stream_info() -> StudioStreamInfo {
    let compositor_path = "/dev/shm/hapax-compositor/status.json";
    let compositor: Option<CompositorStatus> = read_json(compositor_path);

    match compositor {
        Some(c) => StudioStreamInfo {
            hls_url: c.hls_url.clone(),
            hls_enabled: c.hls_enabled,
            mjpeg_url: "/api/studio/stream/live/composite".into(),
            mjpeg_enabled: c.state == "running",
            enabled: c.hls_enabled || c.state == "running",
        },
        None => StudioStreamInfo {
            hls_url: String::new(),
            hls_enabled: false,
            mjpeg_url: String::new(),
            mjpeg_enabled: false,
            enabled: false,
        },
    }
}

// --- Studio Snapshot Image (binary) ---

#[tauri::command]
pub fn get_studio_snapshot() -> Result<Vec<u8>, String> {
    let path = "/dev/shm/hapax-compositor/snapshot.jpg";
    std::fs::read(path).map_err(|e| format!("No snapshot available: {}", e))
}

// --- Perception ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PerceptionState {
    #[serde(default)]
    pub available: bool,
    #[serde(default)]
    pub production_activity: String,
    #[serde(default)]
    pub music_genre: String,
    #[serde(default)]
    pub flow_state: String,
    #[serde(default)]
    pub flow_score: f64,
    #[serde(default)]
    pub emotion_valence: f64,
    #[serde(default)]
    pub emotion_arousal: f64,
    #[serde(default)]
    pub audio_energy_rms: f64,
    #[serde(default)]
    pub face_count: u32,
    #[serde(default)]
    pub vad_confidence: f64,
    #[serde(default)]
    pub activity_mode: String,
    #[serde(default)]
    pub interruptibility_score: f64,
    #[serde(default)]
    pub presence_score: f64,
    #[serde(default)]
    pub operator_present: bool,
    #[serde(default)]
    pub guest_present: bool,
    #[serde(default)]
    pub consent_phase: String,
    #[serde(default)]
    pub timestamp: f64,
    #[serde(default)]
    pub top_emotion: String,
    #[serde(default)]
    pub detected_objects: String,
    #[serde(default)]
    pub person_count: u32,
    #[serde(default)]
    pub pose_summary: String,
    #[serde(default)]
    pub scene_objects: String,
    #[serde(default)]
    pub scene_type: String,
    #[serde(default)]
    pub per_camera_scenes: HashMap<String, String>,
    #[serde(default)]
    pub gaze_direction: String,
    #[serde(default)]
    pub hand_gesture: String,
    #[serde(default)]
    pub nearest_person_distance: String,
    #[serde(default)]
    pub speech_emotion: String,
    #[serde(default)]
    pub audio_events: String,
    #[serde(default)]
    pub speech_language: String,
    #[serde(default)]
    pub ambient_brightness: f64,
    #[serde(default)]
    pub color_temperature: String,
    #[serde(default)]
    pub audio_scene: String,
    #[serde(default)]
    pub posture: String,
    #[serde(default)]
    pub detected_action: String,
    // Contact mic (desk vibration sensing)
    #[serde(default)]
    pub desk_activity: String,
    #[serde(default)]
    pub desk_energy: f64,
    #[serde(default)]
    pub desk_onset_rate: f64,
    #[serde(default)]
    pub desk_tap_gesture: String,
    #[serde(default)]
    pub desk_spectral_centroid: f64,
    #[serde(default)]
    pub desk_autocorr_peak: f64,
    // Overhead hand tracking
    #[serde(default)]
    pub overhead_hand_zones: String,
    #[serde(default)]
    pub usb_devices: String,
    #[serde(default)]
    pub bluetooth_nearby: String,
    #[serde(default)]
    pub network_devices: String,
}

#[tauri::command]
pub fn get_perception() -> PerceptionState {
    let path = "/dev/shm/hapax-compositor/perception-state.json";
    read_json(path).unwrap_or_else(|| PerceptionState {
        available: false,
        production_activity: String::new(),
        music_genre: String::new(),
        flow_state: String::new(),
        flow_score: 0.0,
        emotion_valence: 0.0,
        emotion_arousal: 0.0,
        audio_energy_rms: 0.0,
        face_count: 0,
        vad_confidence: 0.0,
        activity_mode: String::new(),
        interruptibility_score: 0.0,
        presence_score: 0.0,
        operator_present: false,
        guest_present: false,
        consent_phase: "solo".into(),
        timestamp: 0.0,
        top_emotion: String::new(),
        detected_objects: String::new(),
        person_count: 0,
        pose_summary: String::new(),
        scene_objects: String::new(),
        scene_type: String::new(),
        per_camera_scenes: HashMap::new(),
        gaze_direction: String::new(),
        hand_gesture: String::new(),
        nearest_person_distance: String::new(),
        speech_emotion: String::new(),
        audio_events: String::new(),
        speech_language: String::new(),
        ambient_brightness: 0.0,
        color_temperature: String::new(),
        audio_scene: String::new(),
        posture: String::new(),
        detected_action: String::new(),
        desk_activity: String::new(),
        desk_energy: 0.0,
        desk_onset_rate: 0.0,
        desk_tap_gesture: String::new(),
        desk_spectral_centroid: 0.0,
        desk_autocorr_peak: 0.0,
        overhead_hand_zones: String::new(),
        usb_devices: String::new(),
        bluetooth_nearby: String::new(),
        network_devices: String::new(),
    })
}

// --- Visual Layer ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalEntry {
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub severity: f64,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub detail: String,
    #[serde(default)]
    pub source_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AmbientParams {
    #[serde(default = "default_speed")]
    pub speed: f64,
    #[serde(default = "default_turbulence")]
    pub turbulence: f64,
    #[serde(default)]
    pub color_warmth: f64,
    #[serde(default = "default_brightness")]
    pub brightness: f64,
}

fn default_speed() -> f64 {
    0.08
}
fn default_turbulence() -> f64 {
    0.1
}
fn default_brightness() -> f64 {
    0.25
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VisualLayerState {
    #[serde(default)]
    pub available: bool,
    #[serde(default = "default_ambient")]
    pub display_state: String,
    #[serde(default)]
    pub zone_opacities: HashMap<String, f64>,
    #[serde(default)]
    pub signals: HashMap<String, Vec<SignalEntry>>,
    #[serde(default)]
    pub ambient_params: AmbientParams,
    #[serde(default)]
    pub readiness: String,
    #[serde(default)]
    pub timestamp: f64,
    // Voice session state
    #[serde(default)]
    pub voice_session: serde_json::Value,
    #[serde(default)]
    pub voice_content: serde_json::Value,
    // Biometrics and temporal
    #[serde(default)]
    pub biometrics: serde_json::Value,
    #[serde(default)]
    pub temporal_context: serde_json::Value,
    #[serde(default)]
    pub signal_staleness: serde_json::Value,
    // Stimmung and classification
    #[serde(default)]
    pub stimmung_stance: String,
    #[serde(default)]
    pub classification_detections: serde_json::Value,
    #[serde(default)]
    pub classification_directives: HashMap<String, String>,
    // Content fields
    #[serde(default)]
    pub ambient_text: String,
    #[serde(default)]
    pub secondary_ambient_text: String,
    #[serde(default)]
    pub activity_label: String,
    #[serde(default)]
    pub activity_detail: String,
    #[serde(default)]
    pub display_density: String,
    #[serde(default)]
    pub watershed_events: serde_json::Value,
    // Operator tracking
    #[serde(default)]
    pub operator_x: f64,
    #[serde(default)]
    pub operator_y: f64,
    // Environmental color
    #[serde(default)]
    pub environmental_color: serde_json::Value,
    // Transition state
    #[serde(default)]
    pub transition: serde_json::Value,
    // Scheduler
    #[serde(default)]
    pub scheduler_source: String,
    #[serde(default)]
    pub epoch: u64,
    #[serde(default)]
    pub recent_change_points: serde_json::Value,
    #[serde(default)]
    pub injected_feeds: serde_json::Value,
    #[serde(default)]
    pub aggregator: String,
}

fn default_ambient() -> String {
    "ambient".into()
}

impl Default for VisualLayerState {
    fn default() -> Self {
        Self {
            available: false,
            display_state: "ambient".into(),
            zone_opacities: HashMap::new(),
            signals: HashMap::new(),
            ambient_params: AmbientParams::default(),
            readiness: String::new(),
            timestamp: 0.0,
            voice_session: serde_json::Value::Null,
            voice_content: serde_json::Value::Null,
            biometrics: serde_json::Value::Null,
            temporal_context: serde_json::Value::Null,
            signal_staleness: serde_json::Value::Null,
            stimmung_stance: String::new(),
            classification_detections: serde_json::Value::Null,
            classification_directives: HashMap::new(),
            ambient_text: String::new(),
            secondary_ambient_text: String::new(),
            activity_label: String::new(),
            activity_detail: String::new(),
            display_density: String::new(),
            watershed_events: serde_json::Value::Null,
            operator_x: 0.0,
            operator_y: 0.0,
            environmental_color: serde_json::Value::Null,
            transition: serde_json::Value::Null,
            scheduler_source: String::new(),
            epoch: 0,
            recent_change_points: serde_json::Value::Null,
            injected_feeds: serde_json::Value::Null,
            aggregator: String::new(),
        }
    }
}

impl Default for AmbientParams {
    fn default() -> Self {
        Self {
            speed: 0.08,
            turbulence: 0.1,
            color_warmth: 0.0,
            brightness: 0.25,
        }
    }
}

#[tauri::command]
pub fn get_visual_layer() -> VisualLayerState {
    let path = "/dev/shm/hapax-compositor/visual-layer-state.json";
    let mut state: VisualLayerState = read_json(path).unwrap_or_default();
    state.available = state.timestamp > 0.0;
    state
}

// --- Effect Select ---

#[derive(Debug, Clone, Serialize)]
pub struct EffectSelectResponse {
    pub status: String,
    pub preset: String,
}

#[tauri::command]
pub fn select_effect(preset: String) -> EffectSelectResponse {
    // Write effect selection to shm for the compositor to pick up
    let path = "/dev/shm/hapax-compositor/effect-select.json";
    let payload = serde_json::json!({ "preset": preset, "timestamp": now_epoch() });
    std::fs::write(path, payload.to_string()).ok();

    EffectSelectResponse {
        status: "ok".into(),
        preset,
    }
}

// --- Helpers ---

fn read_json<T: serde::de::DeserializeOwned>(path: &str) -> Option<T> {
    let p = Path::new(path);
    let data = std::fs::read_to_string(p).ok()?;
    serde_json::from_str(&data).ok()
}

fn now_epoch() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}
