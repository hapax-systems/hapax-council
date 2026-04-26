// Tauri command: get_cc_hygiene_state
//
// Reads ~/.cache/hapax/cc-hygiene-state.json (canonical state from
// scripts/cc-hygiene-sweeper.py) and returns it raw to the frontend
// React panel (WorkstreamHygieneView). Schema parity is maintained
// at the JSON layer — we deserialize as serde_json::Value rather
// than a typed mirror so additions to the Python sweeper schema do
// not require coordinated Rust + TS updates.
//
// File-not-yet-present and parse errors both return None; the
// frontend renders a "no state yet" placeholder rather than an
// error toast (the sweeper may not have run on a fresh install).

use serde::Serialize;
use std::path::Path;

#[derive(Debug, Clone, Serialize)]
pub struct CcHygieneStateResponse {
    pub state: Option<serde_json::Value>,
    pub mtime_unix: Option<u64>,
}

#[tauri::command]
pub fn get_cc_hygiene_state() -> CcHygieneStateResponse {
    let path = expand_home("~/.cache/hapax/cc-hygiene-state.json");
    let p = Path::new(&path);

    let mtime_unix = std::fs::metadata(p)
        .ok()
        .and_then(|m| m.modified().ok())
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs());

    let state = std::fs::read_to_string(p)
        .ok()
        .and_then(|data| serde_json::from_str(&data).ok());

    CcHygieneStateResponse { state, mtime_unix }
}

fn expand_home(path: &str) -> String {
    if path.starts_with("~/") {
        if let Ok(home) = std::env::var("HOME") {
            return format!("{}{}", home, &path[1..]);
        }
    }
    path.to_string()
}
