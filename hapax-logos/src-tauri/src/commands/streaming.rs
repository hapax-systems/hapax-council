//! SSE streaming bridge: subscribes to FastAPI SSE endpoints and re-emits
//! events to the frontend via Tauri events.
//!
//! This replaces the browser-side fetch+ReadableStream SSE consumer so the
//! frontend never makes direct HTTP calls — all traffic goes through IPC.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};

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
}

impl StreamRegistry {
    pub fn new() -> Self {
        Self {
            senders: Mutex::new(HashMap::new()),
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
        let result = run_sse_stream(&app_handle, &evt, stream_id, &path, method, body, cancel_rx).await;
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

/// Subscribe to the real-time flow-event SSE stream and re-emit each event
/// as a Tauri `flow-event` event. Runs in the background and returns immediately.
#[tauri::command]
pub async fn subscribe_flow_events(app: AppHandle) -> Result<(), String> {
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(e) = run_flow_event_stream(&app_handle).await {
            log::warn!("flow-event SSE stream ended: {}", e);
        }
    });
    Ok(())
}

/// Internal: connect to /api/events/stream SSE and emit each data payload as "flow-event".
async fn run_flow_event_stream(app: &AppHandle) -> Result<(), String> {
    let url = format!("{}/events/stream", LOGOS_BASE);
    let client = app.state::<super::proxy::HttpClient>().0.clone();

    let resp = client
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("flow-event SSE connect: {}", e))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("flow-event SSE {}: {}", status, text));
    }

    let mut byte_stream = resp.bytes_stream();
    let mut buffer = String::new();
    let mut data_lines: Vec<String> = Vec::new();

    while let Some(chunk) = byte_stream.next().await {
        match chunk {
            Err(e) => return Err(format!("flow-event SSE read: {}", e)),
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
                            let _ = app.emit("flow-event", data);
                            data_lines.clear();
                        }
                    } else if let Some(rest) = line.strip_prefix("data: ") {
                        data_lines.push(rest.to_string());
                    } else if let Some(rest) = line.strip_prefix("data:") {
                        data_lines.push(rest.to_string());
                    }
                }
            }
        }
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
