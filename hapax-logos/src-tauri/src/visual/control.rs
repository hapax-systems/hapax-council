//! Tauri commands for controlling the visual surface from the webview.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Current visual surface state — read from /dev/shm.
#[derive(Debug, Clone, Serialize)]
pub struct VisualSurfaceState {
    pub stance: String,
    pub speed: f64,
    pub turbulence: f64,
    pub color_warmth: f64,
    pub brightness: f64,
    pub layer_opacities: HashMap<String, f64>,
    pub fps: f64,
    pub frame_time_ms: f64,
}

#[derive(Deserialize)]
struct ShmVisualState {
    #[serde(default)]
    stance: String,
    #[serde(default)]
    speed: f64,
    #[serde(default)]
    turbulence: f64,
    #[serde(default)]
    color_warmth: f64,
    #[serde(default)]
    brightness: f64,
    #[serde(default)]
    layer_opacities: HashMap<String, f64>,
    #[serde(default)]
    fps: f64,
    #[serde(default)]
    frame_time_ms: f64,
}

#[tauri::command]
pub fn get_visual_surface_state() -> VisualSurfaceState {
    let path = "/dev/shm/hapax-visual/state.json";
    match std::fs::read_to_string(path) {
        Ok(data) => {
            if let Ok(state) = serde_json::from_str::<ShmVisualState>(&data) {
                return VisualSurfaceState {
                    stance: state.stance,
                    speed: state.speed,
                    turbulence: state.turbulence,
                    color_warmth: state.color_warmth,
                    brightness: state.brightness,
                    layer_opacities: state.layer_opacities,
                    fps: state.fps,
                    frame_time_ms: state.frame_time_ms,
                };
            }
        }
        Err(_) => {}
    }

    // Fall back to reading the visual-layer-state from compositor shm
    let fallback_path = "/dev/shm/hapax-compositor/visual-layer-state.json";
    if let Ok(data) = std::fs::read_to_string(fallback_path) {
        if let Ok(state) = serde_json::from_str::<serde_json::Value>(&data) {
            let ambient = state.get("ambient_params").cloned().unwrap_or_default();
            return VisualSurfaceState {
                stance: state
                    .get("stimmung_stance")
                    .and_then(|v| v.as_str())
                    .unwrap_or("nominal")
                    .to_string(),
                speed: ambient.get("speed").and_then(|v| v.as_f64()).unwrap_or(0.08),
                turbulence: ambient
                    .get("turbulence")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.1),
                color_warmth: ambient
                    .get("color_warmth")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0),
                brightness: ambient
                    .get("brightness")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.25),
                layer_opacities: HashMap::new(),
                fps: 0.0,
                frame_time_ms: 0.0,
            };
        }
    }

    VisualSurfaceState {
        stance: "nominal".into(),
        speed: 0.08,
        turbulence: 0.1,
        color_warmth: 0.0,
        brightness: 0.25,
        layer_opacities: HashMap::new(),
        fps: 0.0,
        frame_time_ms: 0.0,
    }
}

/// Set visual surface layer params by writing to shm control file.
#[derive(Deserialize)]
pub struct LayerParamUpdate {
    pub layer: String,
    pub opacity: f64,
}

#[tauri::command]
pub fn set_visual_layer_param(layer: String, opacity: f64) -> bool {
    let path = "/dev/shm/hapax-visual/control.json";

    // Read existing control, update the layer, write back
    let mut control: serde_json::Value = std::fs::read_to_string(path)
        .ok()
        .and_then(|d| serde_json::from_str(&d).ok())
        .unwrap_or(serde_json::json!({"layer_opacities": {}}));

    if let Some(opacities) = control
        .get_mut("layer_opacities")
        .and_then(|v| v.as_object_mut())
    {
        opacities.insert(layer, serde_json::json!(opacity));
    }

    std::fs::create_dir_all("/dev/shm/hapax-visual").ok();
    std::fs::write(path, serde_json::to_string(&control).unwrap_or_default()).is_ok()
}

/// Get a JPEG snapshot of the visual surface.
#[tauri::command]
pub fn get_visual_surface_snapshot() -> Result<Vec<u8>, String> {
    let path = "/dev/shm/hapax-visual/frame.jpg";
    std::fs::read(path).map_err(|e| format!("No visual snapshot: {}", e))
}

#[tauri::command]
pub fn toggle_visual_window(visible: bool) -> bool {
    super::bridge::set_window_visible(visible);
    visible
}
