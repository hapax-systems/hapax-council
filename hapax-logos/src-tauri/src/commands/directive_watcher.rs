//! Watches /dev/shm/hapax-logos/directives.jsonl for agent-posted directives.
//!
//! Each line is a JSON directive. The watcher tails the file, parses new lines,
//! and dispatches them as Tauri events that the React frontend handles.

use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader, Seek, SeekFrom};
use std::path::Path;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::browser::commands::BrowserState;
use crate::browser::services::ServiceRegistry;

const DIRECTIVE_FILE: &str = "/dev/shm/hapax-logos/directives.jsonl";
const POLL_INTERVAL_MS: u64 = 250;

/// Spawn the directive watcher on a background thread.
pub fn spawn_directive_watcher<R: Runtime>(app_handle: AppHandle<R>) {
    std::thread::Builder::new()
        .name("directive-watcher".into())
        .spawn(move || {
            // Ensure directory exists
            if let Err(e) = fs::create_dir_all("/dev/shm/hapax-logos") {
                log::error!("Failed to create directive directory: {}", e);
                return;
            }

            let path = Path::new(DIRECTIVE_FILE);
            let mut last_pos: u64 = if path.exists() {
                // Start at end of existing file (don't replay old directives)
                fs::metadata(path).map(|m| m.len()).unwrap_or(0)
            } else {
                0
            };

            loop {
                std::thread::sleep(Duration::from_millis(POLL_INTERVAL_MS));

                if !path.exists() {
                    last_pos = 0;
                    continue;
                }

                let file_len = match fs::metadata(path) {
                    Ok(m) => m.len(),
                    Err(_) => continue,
                };

                // File was truncated or recreated
                if file_len < last_pos {
                    last_pos = 0;
                }

                if file_len == last_pos {
                    continue;
                }

                // Read new lines
                let file = match fs::File::open(path) {
                    Ok(f) => f,
                    Err(_) => continue,
                };

                let mut reader = BufReader::new(file);
                if reader.seek(SeekFrom::Start(last_pos)).is_err() {
                    continue;
                }

                let mut new_pos = last_pos;
                let mut line = String::new();
                while let Ok(n) = reader.read_line(&mut line) {
                    if n == 0 {
                        break;
                    }
                    new_pos += n as u64;

                    let trimmed = line.trim();
                    if !trimmed.is_empty() {
                        dispatch_directive(&app_handle, trimmed);
                    }
                    line.clear();
                }

                last_pos = new_pos;
            }
        })
        .expect("Failed to spawn directive watcher thread");
}

fn dispatch_directive<R: Runtime>(app: &AppHandle<R>, json_line: &str) {
    let directive: serde_json::Value = match serde_json::from_str(json_line) {
        Ok(v) => v,
        Err(e) => {
            log::warn!("Invalid directive JSON: {}", e);
            return;
        }
    };

    log::info!(
        "Directive from {}: {}",
        directive
            .get("source")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown"),
        directive
            .as_object()
            .map(|o| {
                o.keys()
                    .filter(|k| !k.starts_with('_'))
                    .cloned()
                    .collect::<Vec<_>>()
                    .join(", ")
            })
            .unwrap_or_default()
    );

    // Navigation
    if let Some(route) = directive.get("navigate").and_then(|v| v.as_str()) {
        if let Err(e) = app.emit("hapax:navigate", route) {
            log::warn!("Failed to emit hapax:navigate: {}", e);
        }
    }

    if let Some(panel) = directive.get("open_panel").and_then(|v| v.as_str()) {
        if let Err(e) = app.emit(
            "hapax:toggle-panel",
            serde_json::json!({"panel": panel, "open": true}),
        ) {
            log::warn!("Failed to emit hapax:toggle-panel (open): {}", e);
        }
    }

    if let Some(panel) = directive.get("close_panel").and_then(|v| v.as_str()) {
        if let Err(e) = app.emit(
            "hapax:toggle-panel",
            serde_json::json!({"panel": panel, "open": false}),
        ) {
            log::warn!("Failed to emit hapax:toggle-panel (close): {}", e);
        }
    }

    // Content
    if let Some(msg) = directive.get("toast").and_then(|v| v.as_str()) {
        if let Err(e) = app.emit(
            "hapax:toast",
            serde_json::json!({
                "message": msg,
                "level": directive.get("toast_level").and_then(|v| v.as_str()).unwrap_or("info"),
                "duration_ms": directive.get("toast_duration_ms").and_then(|v| v.as_u64()).unwrap_or(5000),
            }),
        ) {
            log::warn!("Failed to emit hapax:toast: {}", e);
        }
    }

    if let Some(title) = directive.get("modal_title").and_then(|v| v.as_str()) {
        let content = directive
            .get("modal_content")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if let Err(e) = app.emit(
            "hapax:modal",
            serde_json::json!({
                "title": title,
                "content": content,
                "dismissable": true,
                "action": "show",
            }),
        ) {
            log::warn!("Failed to emit hapax:modal (show): {}", e);
        }
    }

    if directive
        .get("dismiss_modal")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        if let Err(e) = app.emit(
            "hapax:modal",
            serde_json::json!({
                "title": "",
                "content": "",
                "dismissable": true,
                "action": "dismiss",
            }),
        ) {
            log::warn!("Failed to emit hapax:modal (dismiss): {}", e);
        }
    }

    if let Some(selector) = directive.get("highlight").and_then(|v| v.as_str()) {
        if let Err(e) = app.emit(
            "hapax:highlight",
            serde_json::json!({
                "selector": selector,
                "duration_ms": directive.get("highlight_duration_ms").and_then(|v| v.as_u64()).unwrap_or(3000),
            }),
        ) {
            log::warn!("Failed to emit hapax:highlight: {}", e);
        }
    }

    if let Some(text) = directive.get("status").and_then(|v| v.as_str()) {
        if let Err(e) = app.emit(
            "hapax:status",
            serde_json::json!({
                "text": text,
                "level": directive.get("status_level").and_then(|v| v.as_str()).unwrap_or("info"),
            }),
        ) {
            log::warn!("Failed to emit hapax:status: {}", e);
        }
    }

    // Window management
    if directive
        .get("focus_window")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        if let Some(w) = app.get_webview_window("main") {
            if let Err(e) = w.unminimize() {
                log::warn!("Failed to unminimize window: {}", e);
            }
            if let Err(e) = w.show() {
                log::warn!("Failed to show window: {}", e);
            }
            if let Err(e) = w.set_focus() {
                log::warn!("Failed to set window focus: {}", e);
            }
        }
    }

    if let Some(fs) = directive.get("fullscreen").and_then(|v| v.as_bool()) {
        if let Some(w) = app.get_webview_window("main") {
            if let Err(e) = w.set_fullscreen(fs) {
                log::warn!("Failed to set fullscreen={}: {}", fs, e);
            }
        }
    }

    if let Some(on_top) = directive.get("always_on_top").and_then(|v| v.as_bool()) {
        if let Some(w) = app.get_webview_window("main") {
            if let Err(e) = w.set_always_on_top(on_top) {
                log::warn!("Failed to set always_on_top={}: {}", on_top, e);
            }
        }
    }

    // Window position/size
    let wx = directive.get("window_x").and_then(|v| v.as_i64());
    let wy = directive.get("window_y").and_then(|v| v.as_i64());
    if let (Some(x), Some(y)) = (wx, wy) {
        if let Some(w) = app.get_webview_window("main") {
            if let Err(e) = w.set_position(tauri::Position::Physical(tauri::PhysicalPosition {
                x: x as i32,
                y: y as i32,
            })) {
                log::warn!("Failed to set window position ({}, {}): {}", x, y, e);
            }
        }
    }

    let ww = directive.get("window_width").and_then(|v| v.as_u64());
    let wh = directive.get("window_height").and_then(|v| v.as_u64());
    if let (Some(width), Some(height)) = (ww, wh) {
        if let Some(w) = app.get_webview_window("main") {
            if let Err(e) = w.set_size(tauri::Size::Physical(tauri::PhysicalSize {
                width: width as u32,
                height: height as u32,
            })) {
                log::warn!("Failed to set window size ({}x{}): {}", width, height, e);
            }
        }
    }

    // Browser actions
    dispatch_browser_directives(app, &directive);

    // Visual surface
    if let Some(stance) = directive.get("visual_stance").and_then(|v| v.as_str()) {
        let path = "/dev/shm/hapax-visual/stance-override.json";
        let payload = serde_json::json!({
            "stance": stance,
            "source": "directive",
            "timestamp": now_epoch(),
        });
        if let Err(e) = fs::create_dir_all("/dev/shm/hapax-visual") {
            log::error!("Failed to create visual directory: {}", e);
        } else if let Err(e) = fs::write(path, payload.to_string()) {
            log::error!("Failed to write stance override to {}: {}", path, e);
        }
        if let Err(e) = app.emit("hapax:stance-override", stance) {
            log::warn!("Failed to emit hapax:stance-override: {}", e);
        }
    }

    if let Some(x) = directive.get("visual_ping_x").and_then(|v| v.as_f64()) {
        let y = directive
            .get("visual_ping_y")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.5);
        let energy = directive
            .get("visual_ping_energy")
            .and_then(|v| v.as_f64())
            .unwrap_or(1.0);

        let events_path = "/dev/shm/hapax-visual/events.jsonl";
        let event = serde_json::json!({
            "type": "wave",
            "x": x,
            "y": y,
            "energy": energy,
            "timestamp": now_epoch(),
        });
        use std::io::Write;
        match fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(events_path)
        {
            Ok(mut f) => {
                if let Err(e) = writeln!(f, "{}", event) {
                    log::warn!(
                        "Failed to write visual ping event to {}: {}",
                        events_path,
                        e
                    );
                }
            }
            Err(e) => log::warn!("Failed to open visual events file {}: {}", events_path, e),
        }
    }
}

/// Dispatch browser-related directive fields to the browser engine.
fn dispatch_browser_directives<R: Runtime>(app: &AppHandle<R>, directive: &serde_json::Value) {
    let state = match app.try_state::<BrowserState>() {
        Some(s) => s,
        None => {
            // Browser not ready yet — check if any browser fields present
            let has_browser = directive.get("browser_navigate").is_some()
                || directive.get("browser_eval").is_some()
                || directive.get("browser_screenshot").is_some()
                || directive.get("browser_extract_a11y").is_some()
                || directive.get("browser_click").is_some()
                || directive.get("browser_fill").is_some()
                || directive.get("browser_press_key").is_some();
            if has_browser {
                log::warn!("Browser directive received but engine not ready");
            }
            return;
        }
    };

    let engine = state.0.clone();

    if let Some(url) = directive.get("browser_navigate").and_then(|v| v.as_str()) {
        // Enforce service registry allowlist
        let registry = ServiceRegistry::load();
        if !registry.is_allowed(url) {
            log::warn!(
                "Browser navigate blocked — URL not in service registry: {}",
                url
            );
            return;
        }
        let url = url.to_string();
        tokio::spawn(async move {
            match engine.navigate(&url).await {
                Ok(title) => log::info!("Browser navigated to {}: {}", url, title),
                Err(e) => log::error!("Browser navigate failed: {}", e),
            }
        });
        return; // navigate is exclusive — don't process other browser actions in same directive
    }

    if let Some(expr) = directive.get("browser_eval").and_then(|v| v.as_str()) {
        let expr = expr.to_string();
        let eng = engine.clone();
        tokio::spawn(async move {
            match eng.eval(&expr).await {
                Ok(result) => {
                    log::info!("Browser eval result: {}", result);
                    let response = serde_json::json!({"action": "eval", "result": result});
                    let resp_path = "/dev/shm/hapax-logos/browser-response.json";
                    if let Err(e) = fs::create_dir_all("/dev/shm/hapax-logos") {
                        log::error!("Failed to create logos directory: {}", e);
                    } else if let Err(e) = fs::write(resp_path, response.to_string()) {
                        log::error!(
                            "Failed to write browser eval response to {}: {}",
                            resp_path,
                            e
                        );
                    }
                }
                Err(e) => log::error!("Browser eval failed: {}", e),
            }
        });
    }

    if directive
        .get("browser_screenshot")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        let eng = engine.clone();
        tokio::spawn(async move {
            match eng.screenshot().await {
                Ok(b64) => {
                    if let Ok(bytes) =
                        base64::Engine::decode(&base64::engine::general_purpose::STANDARD, &b64)
                    {
                        let shot_path = "/dev/shm/hapax-logos/browser-screenshot.png";
                        if let Err(e) = fs::create_dir_all("/dev/shm/hapax-logos") {
                            log::error!("Failed to create logos directory: {}", e);
                        } else if let Err(e) = fs::write(shot_path, bytes) {
                            log::error!(
                                "Failed to write browser screenshot to {}: {}",
                                shot_path,
                                e
                            );
                        } else {
                            log::info!("Browser screenshot saved to shm");
                        }
                    }
                }
                Err(e) => log::error!("Browser screenshot failed: {}", e),
            }
        });
    }

    if directive
        .get("browser_extract_a11y")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        let eng = engine.clone();
        tokio::spawn(async move {
            match eng.active_page().await {
                Ok(page) => {
                    use chromiumoxide::cdp::browser_protocol::accessibility::{
                        GetFullAxTreeParams, GetFullAxTreeReturns,
                    };
                    let params = GetFullAxTreeParams::default();
                    match page.execute(params).await {
                        Ok(cdp_response) => {
                            let response: GetFullAxTreeReturns = cdp_response.result;
                            let tree =
                                crate::browser::a11y::serialize_ax_nodes_pub(&response.nodes);
                            let a11y_path = "/dev/shm/hapax-logos/browser-a11y.txt";
                            if let Err(e) = fs::create_dir_all("/dev/shm/hapax-logos") {
                                log::error!("Failed to create logos directory: {}", e);
                            } else if let Err(e) = fs::write(a11y_path, &tree) {
                                log::error!(
                                    "Failed to write browser A11y tree to {}: {}",
                                    a11y_path,
                                    e
                                );
                            } else {
                                log::info!("Browser A11y tree extracted ({} bytes)", tree.len());
                            }
                        }
                        Err(e) => log::error!("A11y tree extraction failed: {}", e),
                    }
                }
                Err(e) => log::error!("Browser page not available: {}", e),
            }
        });
    }

    if let Some(selector) = directive.get("browser_click").and_then(|v| v.as_str()) {
        let selector = selector.to_string();
        let eng = engine.clone();
        tokio::spawn(async move {
            match eng.click(&selector).await {
                Ok(()) => log::info!("Browser clicked: {}", selector),
                Err(e) => log::error!("Browser click failed: {}", e),
            }
        });
    }

    if let Some(selector) = directive
        .get("browser_fill_selector")
        .and_then(|v| v.as_str())
    {
        if let Some(text) = directive.get("browser_fill_text").and_then(|v| v.as_str()) {
            let selector = selector.to_string();
            let text = text.to_string();
            let eng = engine.clone();
            tokio::spawn(async move {
                match eng.fill(&selector, &text).await {
                    Ok(()) => log::info!("Browser filled: {}", selector),
                    Err(e) => log::error!("Browser fill failed: {}", e),
                }
            });
        }
    }

    if let Some(key) = directive.get("browser_press_key").and_then(|v| v.as_str()) {
        let key = key.to_string();
        let eng = engine.clone();
        tokio::spawn(async move {
            match eng.press_key(&key).await {
                Ok(()) => log::info!("Browser pressed key: {}", key),
                Err(e) => log::error!("Browser press_key failed: {}", e),
            }
        });
    }

    // Service-resolved navigation: {"browser_service": "github", "browser_pattern": "pr", "browser_params": {"id": "145"}}
    if let Some(service) = directive.get("browser_service").and_then(|v| v.as_str()) {
        let pattern = directive
            .get("browser_pattern")
            .and_then(|v| v.as_str())
            .unwrap_or("repo");
        let params: HashMap<String, String> = directive
            .get("browser_params")
            .and_then(|v| serde_json::from_value(v.clone()).ok())
            .unwrap_or_default();

        let registry = ServiceRegistry::load();
        if let Some(url) = registry.resolve(service, pattern, &params) {
            let eng = engine.clone();
            tokio::spawn(async move {
                match eng.navigate(&url).await {
                    Ok(title) => log::info!("Browser navigated via service to {}: {}", url, title),
                    Err(e) => log::error!("Browser service navigate failed: {}", e),
                }
            });
        } else {
            log::warn!("Browser service resolution failed: {}/{}", service, pattern);
        }
    }
}

fn now_epoch() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}
