//! Tauri IPC commands for agent-controlled browser.
//!
//! These commands expose the browser engine to both the React frontend
//! (via IPC) and the directive watcher (via shared state).

use std::sync::Arc;

use tauri::{AppHandle, Emitter, Manager, Runtime};

use super::engine::BrowserEngine;

/// Spawn the browser engine on the tokio runtime and store in Tauri state.
pub fn spawn_browser_engine<R: Runtime>(app_handle: AppHandle<R>) {
    let handle = app_handle.clone();
    let Ok(rt_handle) = tokio::runtime::Handle::try_current() else {
        log::warn!("No tokio runtime available — browser engine disabled");
        return;
    };
    rt_handle.spawn(async move {
        match BrowserEngine::launch().await {
            Ok(engine) => {
                handle.manage(BrowserState(engine));
                log::info!("Browser engine ready");
                handle.emit("browser:ready", true).ok();
            }
            Err(e) => {
                log::error!("Browser engine failed to launch: {}", e);
                handle.emit("browser:error", e.to_string()).ok();
            }
        }
    });
}

/// Wrapper for Tauri managed state.
pub struct BrowserState(pub Arc<BrowserEngine>);

// ─── Tauri Commands ──────────────────────────────────────────────────────────

#[tauri::command]
pub async fn browser_navigate<R: Runtime>(
    app: AppHandle<R>,
    url: String,
) -> Result<String, String> {
    let state = app
        .try_state::<BrowserState>()
        .ok_or("Browser not ready")?;
    let title = state.0.navigate(&url).await?;
    write_response(&serde_json::json!({"action": "navigate", "url": url, "title": title}));
    Ok(title)
}

#[tauri::command]
pub async fn browser_eval<R: Runtime>(
    app: AppHandle<R>,
    expression: String,
) -> Result<serde_json::Value, String> {
    let state = app
        .try_state::<BrowserState>()
        .ok_or("Browser not ready")?;
    let result = state.0.eval(&expression).await?;
    write_response(&serde_json::json!({"action": "eval", "result": result}));
    Ok(result)
}

#[tauri::command]
pub async fn browser_screenshot<R: Runtime>(
    app: AppHandle<R>,
) -> Result<String, String> {
    let state = app
        .try_state::<BrowserState>()
        .ok_or("Browser not ready")?;
    let b64 = state.0.screenshot().await?;
    // Write screenshot to shm for agents to read (too large for JSONL response)
    let path = "/dev/shm/hapax-logos/browser-screenshot.png";
    if let Ok(bytes) = base64::Engine::decode(&base64::engine::general_purpose::STANDARD, &b64) {
        std::fs::write(path, bytes).ok();
    }
    write_response(&serde_json::json!({"action": "screenshot", "path": path}));
    Ok(b64)
}

#[tauri::command]
pub async fn browser_get_url<R: Runtime>(app: AppHandle<R>) -> Result<String, String> {
    let state = app
        .try_state::<BrowserState>()
        .ok_or("Browser not ready")?;
    state.0.get_url().await
}

#[tauri::command]
pub async fn browser_get_title<R: Runtime>(app: AppHandle<R>) -> Result<String, String> {
    let state = app
        .try_state::<BrowserState>()
        .ok_or("Browser not ready")?;
    state.0.get_title().await
}

#[tauri::command]
pub async fn browser_click<R: Runtime>(
    app: AppHandle<R>,
    selector: String,
) -> Result<(), String> {
    let state = app
        .try_state::<BrowserState>()
        .ok_or("Browser not ready")?;
    state.0.click(&selector).await?;
    write_response(&serde_json::json!({"action": "click", "selector": selector}));
    Ok(())
}

#[tauri::command]
pub async fn browser_fill<R: Runtime>(
    app: AppHandle<R>,
    selector: String,
    text: String,
) -> Result<(), String> {
    let state = app
        .try_state::<BrowserState>()
        .ok_or("Browser not ready")?;
    state.0.fill(&selector, &text).await?;
    write_response(&serde_json::json!({"action": "fill", "selector": selector}));
    Ok(())
}

#[tauri::command]
pub async fn browser_press_key<R: Runtime>(
    app: AppHandle<R>,
    key: String,
) -> Result<(), String> {
    let state = app
        .try_state::<BrowserState>()
        .ok_or("Browser not ready")?;
    state.0.press_key(&key).await?;
    write_response(&serde_json::json!({"action": "press_key", "key": key}));
    Ok(())
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/// Write a browser response to shm for agents to read.
fn write_response(payload: &serde_json::Value) {
    let path = "/dev/shm/hapax-logos/browser-response.json";
    std::fs::create_dir_all("/dev/shm/hapax-logos").ok();
    std::fs::write(path, payload.to_string()).ok();
}
