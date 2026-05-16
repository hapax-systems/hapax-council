//! Introspection & self-manipulation commands.
//!
//! These commands let Hapax agents control the UI programmatically —
//! navigate, show content, adjust windows, trigger visual feedback.
//! Exposed both as Tauri IPC commands (from webview) and as an HTTP
//! API (from agents via logos-api proxy).

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, Runtime};

// ─── Navigation ──────────────────────────────────────────────────────────────

/// Navigate the webview to a specific route.
#[tauri::command]
pub fn navigate<R: Runtime>(app: AppHandle<R>, route: String) {
    app.emit("hapax:navigate", &route).ok();
}

/// Open or close a sidebar panel by id.
#[tauri::command]
pub fn toggle_panel<R: Runtime>(app: AppHandle<R>, panel: String, open: bool) {
    app.emit("hapax:toggle-panel", PanelEvent { panel, open })
        .ok();
}

#[derive(Clone, Serialize)]
struct PanelEvent {
    panel: String,
    open: bool,
}

// ─── Content injection ───────────────────────────────────────────────────────

/// Show a toast notification in the UI.
#[tauri::command]
pub fn show_toast<R: Runtime>(
    app: AppHandle<R>,
    message: String,
    level: Option<String>,
    duration_ms: Option<u64>,
) {
    app.emit(
        "hapax:toast",
        ToastEvent {
            message,
            level: level.unwrap_or_else(|| "info".into()),
            duration_ms: duration_ms.unwrap_or(5000),
        },
    )
    .ok();
}

#[derive(Clone, Serialize)]
struct ToastEvent {
    message: String,
    level: String,
    duration_ms: u64,
}

/// Show a modal overlay with markdown content.
#[tauri::command]
pub fn show_modal<R: Runtime>(
    app: AppHandle<R>,
    title: String,
    content: String,
    dismissable: Option<bool>,
) {
    app.emit(
        "hapax:modal",
        ModalEvent {
            title,
            content,
            dismissable: dismissable.unwrap_or(true),
            action: "show".into(),
        },
    )
    .ok();
}

/// Dismiss any open modal.
#[tauri::command]
pub fn dismiss_modal<R: Runtime>(app: AppHandle<R>) {
    app.emit(
        "hapax:modal",
        ModalEvent {
            title: String::new(),
            content: String::new(),
            dismissable: true,
            action: "dismiss".into(),
        },
    )
    .ok();
}

#[derive(Clone, Serialize)]
struct ModalEvent {
    title: String,
    content: String,
    dismissable: bool,
    action: String,
}

/// Highlight a UI element by CSS selector (pulse animation).
#[tauri::command]
pub fn highlight_element<R: Runtime>(
    app: AppHandle<R>,
    selector: String,
    duration_ms: Option<u64>,
) {
    app.emit(
        "hapax:highlight",
        HighlightEvent {
            selector,
            duration_ms: duration_ms.unwrap_or(3000),
        },
    )
    .ok();
}

#[derive(Clone, Serialize)]
struct HighlightEvent {
    selector: String,
    duration_ms: u64,
}

/// Push a status message to the header bar.
#[tauri::command]
pub fn set_status<R: Runtime>(app: AppHandle<R>, text: String, level: Option<String>) {
    app.emit(
        "hapax:status",
        StatusEvent {
            text,
            level: level.unwrap_or_else(|| "info".into()),
        },
    )
    .ok();
}

#[derive(Clone, Serialize)]
struct StatusEvent {
    text: String,
    level: String,
}

// ─── Window management ───────────────────────────────────────────────────────

/// Get current window state.
#[tauri::command]
pub fn get_window_state<R: Runtime>(app: AppHandle<R>) -> Option<WindowState> {
    let window = app.get_webview_window("main")?;
    let pos = window.outer_position().ok()?;
    let size = window.outer_size().ok()?;
    let fullscreen = window.is_fullscreen().ok().unwrap_or(false);
    let focused = window.is_focused().ok().unwrap_or(false);
    let minimized = window.is_minimized().ok().unwrap_or(false);

    Some(WindowState {
        x: pos.x,
        y: pos.y,
        width: size.width,
        height: size.height,
        fullscreen,
        focused,
        minimized,
    })
}

#[derive(Clone, Serialize)]
pub struct WindowState {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub fullscreen: bool,
    pub focused: bool,
    pub minimized: bool,
}

/// Move/resize the main window.
#[tauri::command]
pub fn set_window_position<R: Runtime>(
    app: AppHandle<R>,
    x: Option<i32>,
    y: Option<i32>,
    width: Option<u32>,
    height: Option<u32>,
) -> bool {
    let Some(window) = app.get_webview_window("main") else {
        return false;
    };
    if let (Some(x), Some(y)) = (x, y) {
        window
            .set_position(tauri::Position::Physical(tauri::PhysicalPosition { x, y }))
            .ok();
    }
    if let (Some(w), Some(h)) = (width, height) {
        window
            .set_size(tauri::Size::Physical(tauri::PhysicalSize {
                width: w,
                height: h,
            }))
            .ok();
    }
    true
}

/// Set window fullscreen state.
#[tauri::command]
pub fn set_window_fullscreen<R: Runtime>(app: AppHandle<R>, fullscreen: bool) -> bool {
    app.get_webview_window("main")
        .map(|w| w.set_fullscreen(fullscreen).is_ok())
        .unwrap_or(false)
}

/// Set window always-on-top.
#[tauri::command]
pub fn set_window_always_on_top<R: Runtime>(app: AppHandle<R>, on_top: bool) -> bool {
    app.get_webview_window("main")
        .map(|w| w.set_always_on_top(on_top).is_ok())
        .unwrap_or(false)
}

/// Focus the main window (bring to front).
#[tauri::command]
pub fn focus_window<R: Runtime>(app: AppHandle<R>) -> bool {
    app.get_webview_window("main")
        .map(|w| {
            w.unminimize().ok();
            w.show().ok();
            w.set_focus().is_ok()
        })
        .unwrap_or(false)
}

// ─── Visual surface control ─────────────────────────────────────────────────

/// Set the visual surface stance override (agents can force a visual mood).
#[tauri::command]
pub fn set_visual_stance<R: Runtime>(app: AppHandle<R>, stance: String) {
    // Write to shm for the visual renderer to pick up
    let path = "/dev/shm/hapax-visual/stance-override.json";
    let payload = serde_json::json!({
        "stance": stance,
        "source": "introspect",
        "timestamp": now_epoch(),
    });
    std::fs::create_dir_all("/dev/shm/hapax-visual").ok();
    std::fs::write(path, payload.to_string()).ok();

    // Also emit to webview for UI indicators
    app.emit("hapax:stance-override", &stance).ok();
}

/// Inject a wave event into the visual surface (visual "ping").
#[tauri::command]
pub fn visual_ping<R: Runtime>(app: AppHandle<R>, x: f64, y: f64, energy: f64) {
    let path = "/dev/shm/hapax-visual/events.jsonl";
    let event = serde_json::json!({
        "type": "wave",
        "x": x,
        "y": y,
        "energy": energy,
        "timestamp": now_epoch(),
    });
    // Append to events file
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        writeln!(f, "{}", event).ok();
    }

    app.emit(
        "hapax:visual-ping",
        serde_json::json!({"x": x, "y": y, "energy": energy}),
    )
    .ok();
}

// ─── Composite: multi-action directives ──────────────────────────────────────

/// Execute a composite UI directive (navigate + toast + highlight in one call).
#[tauri::command]
pub fn ui_directive<R: Runtime>(app: AppHandle<R>, directive: UiDirective) {
    if let Some(route) = &directive.navigate {
        app.emit("hapax:navigate", route).ok();
    }
    if let Some(toast) = &directive.toast {
        app.emit(
            "hapax:toast",
            ToastEvent {
                message: toast.clone(),
                level: directive
                    .toast_level
                    .clone()
                    .unwrap_or_else(|| "info".into()),
                duration_ms: directive.toast_duration_ms.unwrap_or(5000),
            },
        )
        .ok();
    }
    if let Some(selector) = &directive.highlight {
        app.emit(
            "hapax:highlight",
            HighlightEvent {
                selector: selector.clone(),
                duration_ms: directive.highlight_duration_ms.unwrap_or(3000),
            },
        )
        .ok();
    }
    if let Some(panel) = &directive.open_panel {
        app.emit(
            "hapax:toggle-panel",
            PanelEvent {
                panel: panel.clone(),
                open: true,
            },
        )
        .ok();
    }
    if let Some(stance) = &directive.visual_stance {
        set_visual_stance(app, stance.clone());
    }
}

#[derive(Clone, Deserialize)]
pub struct UiDirective {
    pub navigate: Option<String>,
    pub toast: Option<String>,
    pub toast_level: Option<String>,
    pub toast_duration_ms: Option<u64>,
    pub highlight: Option<String>,
    pub highlight_duration_ms: Option<u64>,
    pub open_panel: Option<String>,
    pub visual_stance: Option<String>,
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

fn now_epoch() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}
