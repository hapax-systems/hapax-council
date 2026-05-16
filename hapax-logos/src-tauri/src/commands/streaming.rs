//! SSE streaming bridge: subscribes to FastAPI SSE endpoints and re-emits
//! events to the frontend via Tauri events.
//!
//! This replaces the browser-side fetch+ReadableStream SSE consumer so the
//! frontend never makes direct HTTP calls — all traffic goes through IPC.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

use futures::StreamExt;
use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager};
use tokio::sync::{oneshot, Mutex};

const LOGOS_BASE: &str = "http://127.0.0.1:8051/api";

/// Global stream ID counter.
static NEXT_STREAM_ID: AtomicU64 = AtomicU64::new(1);

/// Cancellation senders keyed by stream_id, stored in Tauri managed state.
pub struct StreamRegistry {
    senders: Mutex<HashMap<u64, oneshot::Sender<()>>>,
    /// Idempotency flag for `subscribe_flow_events` — once the background SSE
    /// task has been spawned for the app lifetime, subsequent calls are no-ops.
    /// Without this, every FlowPage effect re-run spawns a fresh tokio task +
    /// HTTP connection to /api/events/stream, accumulating into hundreds of
    /// orphan tasks and gigabytes of retained buffers.
    flow_events_subscribed: AtomicBool,
    /// Idempotency flag for `subscribe_awareness` — same rationale as
    /// `flow_events_subscribed`. The awareness stream relays
    /// `awareness:state` / `awareness:stale` / `awareness:heartbeat`
    /// to the webview.
    awareness_subscribed: AtomicBool,
}

impl StreamRegistry {
    pub fn new() -> Self {
        Self {
            senders: Mutex::new(HashMap::new()),
            flow_events_subscribed: AtomicBool::new(false),
            awareness_subscribed: AtomicBool::new(false),
        }
    }
}

/// Payload emitted for each Tauri event on the `stream:{id}` channel.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type")]
enum StreamPayload {
    #[serde(rename = "event")]
    Event { event: String, data: String },
    #[serde(rename = "done")]
    Done {},
    #[serde(rename = "error")]
    Error { data: String },
}

/// Start an SSE stream. Returns the stream_id used as the Tauri event channel name.
#[tauri::command]
pub async fn start_stream(
    app: AppHandle,
    path: String,
    method: Option<String>,
    body: Option<Value>,
) -> Result<u64, String> {
    let stream_id = NEXT_STREAM_ID.fetch_add(1, Ordering::Relaxed);
    let event_name = format!("stream:{}", stream_id);

    let (cancel_tx, cancel_rx) = oneshot::channel::<()>();

    // Register the cancellation sender
    let registry = app.state::<StreamRegistry>();
    registry.senders.lock().await.insert(stream_id, cancel_tx);

    let app_handle = app.clone();
    let evt = event_name.clone();

    tokio::spawn(async move {
        let result =
            run_sse_stream(&app_handle, &evt, stream_id, &path, method, body, cancel_rx).await;
        if let Err(e) = result {
            let _ = app_handle.emit(
                &evt,
                StreamPayload::Error {
                    data: e.to_string(),
                },
            );
        }
        // Clean up the registry entry
        let registry = app_handle.state::<StreamRegistry>();
        registry.senders.lock().await.remove(&stream_id);
    });

    Ok(stream_id)
}

/// Cancel a running stream.
#[tauri::command]
pub async fn cancel_stream(app: AppHandle, stream_id: u64) -> Result<(), String> {
    let registry = app.state::<StreamRegistry>();
    if let Some(tx) = registry.senders.lock().await.remove(&stream_id) {
        let _ = tx.send(());
    }
    Ok(())
}

/// Cancel a running stream AND tell the server to abort the current agent run.
#[tauri::command]
pub async fn cancel_stream_and_server(app: AppHandle, stream_id: u64) -> Result<(), String> {
    // Cancel the local stream
    cancel_stream(app.clone(), stream_id).await?;

    // Tell FastAPI to cancel the server-side run
    let url = format!("{}/agents/runs/current", LOGOS_BASE);
    let client = app.state::<super::proxy::HttpClient>();
    let _ = client.0.delete(&url).send().await;

    Ok(())
}

/// Subscribe to the system flow event stream (/api/events/stream).
/// Runs in a background task, emitting each SSE data payload as a
/// Tauri event named "flow-event". Returns immediately.
///
/// Idempotent: safe to call from frontend effects that re-run. Only the
/// first call spawns the background task; subsequent calls are no-ops.
#[tauri::command]
pub async fn subscribe_flow_events(app: AppHandle) -> Result<(), String> {
    let registry = app.state::<StreamRegistry>();
    if registry.flow_events_subscribed.swap(true, Ordering::AcqRel) {
        return Ok(());
    }

    let app_handle = app.clone();

    tokio::spawn(async move {
        let url = format!("{}/events/stream", LOGOS_BASE);
        let client = app_handle.state::<super::proxy::HttpClient>().0.clone();

        let resp = match client.get(&url).send().await {
            Ok(r) if r.status().is_success() => r,
            Ok(r) => {
                log::warn!("flow-event SSE: {}", r.status());
                return;
            }
            Err(e) => {
                log::warn!("flow-event SSE connect: {}", e);
                return;
            }
        };

        let mut byte_stream = resp.bytes_stream();
        let mut buffer = String::new();

        while let Some(chunk) = byte_stream.next().await {
            match chunk {
                Err(e) => {
                    log::warn!("flow-event SSE read: {}", e);
                    break;
                }
                Ok(bytes) => {
                    let text = String::from_utf8_lossy(&bytes);
                    buffer.push_str(&text);

                    while let Some(newline_pos) = buffer.find('\n') {
                        let line = buffer[..newline_pos].to_string();
                        buffer = buffer[newline_pos + 1..].to_string();
                        let line = line.trim_end_matches('\r');

                        if let Some(data) = line
                            .strip_prefix("data: ")
                            .or_else(|| line.strip_prefix("data:"))
                        {
                            let _ = app_handle.emit("flow-event", data.to_string());
                        }
                    }
                }
            }
        }
    });

    Ok(())
}

/// Subscribe to the operator-awareness state stream (/api/awareness/stream).
///
/// Relays three named SSE event types as Tauri events:
///   * `awareness:state` — full AwarenessState JSON payload (string)
///   * `awareness:stale` — emitted once when the state file age crosses TTL
///   * `awareness:heartbeat` — periodic liveness ping
///
/// Reconnection: exponential backoff with cap at 30s. Survives FastAPI
/// restarts so the webview can subscribe at boot and stay live for the
/// session lifetime.
///
/// Read-only by design: there is NO bidirectional command — the webview
/// cannot push state back through this path. Per the awareness substrate
/// constitutional invariant (refusal-as-data, full-automation-or-no-engagement),
/// awareness is a Hapax-emitted signal, never operator-edited.
///
/// Idempotent: only the first call spawns the background task; subsequent
/// calls are no-ops.
#[tauri::command]
pub async fn subscribe_awareness(app: AppHandle) -> Result<(), String> {
    let registry = app.state::<StreamRegistry>();
    if registry.awareness_subscribed.swap(true, Ordering::AcqRel) {
        return Ok(());
    }

    let app_handle = app.clone();

    tokio::spawn(async move {
        let url = format!("{}/awareness/stream", LOGOS_BASE);
        let client = app_handle.state::<super::proxy::HttpClient>().0.clone();

        // Exponential backoff: 1s → 2s → 4s → … capped at 30s.
        let mut backoff_ms = 1000u64;
        const BACKOFF_CAP_MS: u64 = 30_000;

        loop {
            let resp = match client.get(&url).send().await {
                Ok(r) if r.status().is_success() => {
                    backoff_ms = 1000;
                    r
                }
                Ok(r) => {
                    log::warn!("awareness SSE: HTTP {}", r.status());
                    tokio::time::sleep(std::time::Duration::from_millis(backoff_ms)).await;
                    backoff_ms = (backoff_ms * 2).min(BACKOFF_CAP_MS);
                    continue;
                }
                Err(e) => {
                    log::warn!("awareness SSE connect: {}", e);
                    tokio::time::sleep(std::time::Duration::from_millis(backoff_ms)).await;
                    backoff_ms = (backoff_ms * 2).min(BACKOFF_CAP_MS);
                    continue;
                }
            };

            let mut byte_stream = resp.bytes_stream();
            let mut buffer = String::new();
            let mut current_event = String::from("message");
            let mut data_lines: Vec<String> = Vec::new();

            while let Some(chunk) = byte_stream.next().await {
                match chunk {
                    Err(e) => {
                        log::warn!("awareness SSE read: {}", e);
                        break;
                    }
                    Ok(bytes) => {
                        let text = String::from_utf8_lossy(&bytes);
                        buffer.push_str(&text);

                        while let Some(newline_pos) = buffer.find('\n') {
                            let line = buffer[..newline_pos].to_string();
                            buffer = buffer[newline_pos + 1..].to_string();
                            let line = line.trim_end_matches('\r');

                            if line.is_empty() {
                                if !data_lines.is_empty() {
                                    let data = data_lines.join("\n");
                                    let event_name = format!("awareness:{}", current_event);
                                    let _ = app_handle.emit(&event_name, data);
                                    data_lines.clear();
                                    current_event = String::from("message");
                                }
                            } else if let Some(rest) = line.strip_prefix("event: ") {
                                current_event = rest.trim().to_string();
                            } else if let Some(rest) = line.strip_prefix("data: ") {
                                data_lines.push(rest.to_string());
                            } else if let Some(rest) = line.strip_prefix("data:") {
                                data_lines.push(rest.to_string());
                            }
                        }
                    }
                }
            }

            // Connection ended (server disconnect or read error). Reconnect
            // after backoff. The acceptance criterion calls for "auto-
            // reconnect on network/server disconnect with exponential
            // backoff" — `backoff_ms` resets to 1s on next successful
            // connect.
            log::info!(
                "awareness SSE disconnected; reconnecting in {}ms",
                backoff_ms
            );
            tokio::time::sleep(std::time::Duration::from_millis(backoff_ms)).await;
            backoff_ms = (backoff_ms * 2).min(BACKOFF_CAP_MS);
        }
    });

    Ok(())
}

/// Internal: connect to FastAPI SSE, parse events, emit to frontend.
async fn run_sse_stream(
    app: &AppHandle,
    event_name: &str,
    _stream_id: u64,
    path: &str,
    method: Option<String>,
    body: Option<Value>,
    cancel_rx: oneshot::Receiver<()>,
) -> Result<(), String> {
    let url = format!("{}{}", LOGOS_BASE, path);
    let client = app.state::<super::proxy::HttpClient>().0.clone();

    let method_str = method.as_deref().unwrap_or("POST");
    let req_builder = match method_str {
        "GET" => client.get(&url),
        "PUT" => client.put(&url),
        "DELETE" => client.delete(&url),
        _ => client.post(&url),
    };

    let req_builder = if let Some(b) = body {
        req_builder
            .header("Content-Type", "application/json")
            .json(&b)
    } else {
        req_builder
    };

    let resp = req_builder
        .send()
        .await
        .map_err(|e| format!("SSE connect {}: {}", path, e))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("SSE {} {}: {}", path, status, text));
    }

    let mut byte_stream = resp.bytes_stream();
    let mut buffer = String::new();
    let mut current_event = String::from("message");
    let mut data_lines: Vec<String> = Vec::new();

    // Use tokio::select! to allow cancellation
    let mut cancel_rx = cancel_rx;

    loop {
        tokio::select! {
            _ = &mut cancel_rx => {
                // Cancelled — emit done and exit
                let _ = app.emit(event_name, StreamPayload::Done {});
                return Ok(());
            }
            chunk = byte_stream.next() => {
                match chunk {
                    None => {
                        // Stream ended
                        let _ = app.emit(event_name, StreamPayload::Done {});
                        return Ok(());
                    }
                    Some(Err(e)) => {
                        let _ = app.emit(
                            event_name,
                            StreamPayload::Error { data: e.to_string() },
                        );
                        return Ok(());
                    }
                    Some(Ok(bytes)) => {
                        let text = String::from_utf8_lossy(&bytes);
                        buffer.push_str(&text);

                        // Parse SSE format per spec: accumulate data lines,
                        // dispatch on empty line (event boundary)
                        while let Some(newline_pos) = buffer.find('\n') {
                            let line = buffer[..newline_pos].to_string();
                            buffer = buffer[newline_pos + 1..].to_string();

                            let line = line.trim_end_matches('\r');

                            if line.is_empty() {
                                // Empty line = event boundary, dispatch accumulated data
                                if !data_lines.is_empty() {
                                    let data = data_lines.join("\n");
                                    let _ = app.emit(
                                        event_name,
                                        StreamPayload::Event {
                                            event: current_event.clone(),
                                            data,
                                        },
                                    );
                                    data_lines.clear();
                                    current_event = String::from("message");
                                }
                            } else if let Some(rest) = line.strip_prefix("event: ") {
                                current_event = rest.trim().to_string();
                            } else if let Some(rest) = line.strip_prefix("data: ") {
                                data_lines.push(rest.to_string());
                            } else if let Some(rest) = line.strip_prefix("data:") {
                                data_lines.push(rest.to_string());
                            }
                            // Other lines (comments starting with :, id:, retry:) ignored
                        }
                    }
                }
            }
        }
    }
}
