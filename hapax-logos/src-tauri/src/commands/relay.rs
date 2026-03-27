//! WebSocket command relay server.
//!
//! Accepts external clients (MCP, voice agents) on port 8052 and relays
//! command messages to/from the Tauri frontend via events.
//!
//! Protocol (JSON over WebSocket):
//!   → { type: "execute", id, path, args }
//!   → { type: "query",   id, path }
//!   → { type: "list",    id, domain? }
//!   → { type: "subscribe",   id, pattern }
//!   → { type: "unsubscribe", id }
//!   ← { type: "result", id, data }
//!   ← { type: "event",  path, args, result, timestamp, subscription? }

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use futures::stream::SplitSink;
use futures::{SinkExt, StreamExt};
use serde_json::Value;
use tauri::{AppHandle, Emitter, Listener};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{broadcast, oneshot, Mutex, RwLock};
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::WebSocketStream;

const DEFAULT_PORT: u16 = 8052;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);

type WsSink = SplitSink<WebSocketStream<TcpStream>, Message>;

/// Shared state across all connections and the Tauri event bridge.
struct RelayState {
    /// Pending request-id → oneshot sender for the result.
    pending: Mutex<HashMap<String, oneshot::Sender<Value>>>,
    /// Broadcast channel for registry events → subscribed external clients.
    event_tx: broadcast::Sender<Value>,
}

/// Subscription held by one external client.
struct Subscription {
    id: String,
    pattern: regex::Regex,
}

/// Start the relay WebSocket server. Call from `setup()`.
pub fn spawn_relay_server(app: &AppHandle) {
    let state = Arc::new(RelayState {
        pending: Mutex::new(HashMap::new()),
        event_tx: broadcast::channel(256).0,
    });

    // Listen for results coming back from the frontend.
    let state_for_listener = Arc::clone(&state);
    app.listen("command:result", move |event| {
        let payload = event.payload();
        let msg: Value = match serde_json::from_str(payload) {
            Ok(v) => v,
            Err(_) => return,
        };
        let id = match msg.get("id").and_then(|v| v.as_str()) {
            Some(s) => s.to_string(),
            None => return,
        };
        let state = Arc::clone(&state_for_listener);
        // Fire-and-forget: deliver result to the waiting oneshot.
        tokio::spawn(async move {
            if let Some(tx) = state.pending.lock().await.remove(&id) {
                let _ = tx.send(msg);
            }
        });
    });

    // Listen for registry events from the frontend and fan out.
    let state_for_events = Arc::clone(&state);
    app.listen("command:event", move |event| {
        let payload = event.payload();
        if let Ok(msg) = serde_json::from_str::<Value>(payload) {
            let _ = state_for_events.event_tx.send(msg);
        }
    });

    let handle = app.clone();
    let state_for_server = Arc::clone(&state);
    tauri::async_runtime::spawn(async move {
        run_server(handle, state_for_server).await;
    });
}

async fn run_server(app: AppHandle, state: Arc<RelayState>) {
    let port: u16 = std::env::var("HAPAX_RELAY_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(DEFAULT_PORT);

    let addr = format!("127.0.0.1:{port}");
    let listener = match TcpListener::bind(&addr).await {
        Ok(l) => {
            log::info!("Command relay listening on ws://{addr}");
            l
        }
        Err(e) => {
            log::error!("Command relay failed to bind {addr}: {e}");
            return;
        }
    };

    loop {
        match listener.accept().await {
            Ok((stream, peer)) => {
                log::debug!("Command relay: new connection from {peer}");
                let app = app.clone();
                let state = Arc::clone(&state);
                tokio::spawn(async move {
                    if let Err(e) = handle_connection(app, state, stream).await {
                        log::debug!("Command relay connection error: {e}");
                    }
                });
            }
            Err(e) => {
                log::error!("Command relay accept error: {e}");
            }
        }
    }
}

async fn handle_connection(
    app: AppHandle,
    state: Arc<RelayState>,
    stream: TcpStream,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let ws = tokio_tungstenite::accept_async(stream).await?;
    let (sink, mut read) = ws.split();
    let sink = Arc::new(Mutex::new(sink));
    let subscriptions: Arc<RwLock<Vec<Subscription>>> = Arc::new(RwLock::new(Vec::new()));

    // Spawn a task to forward matching events to this client.
    let mut event_rx = state.event_tx.subscribe();
    let sink_for_events = Arc::clone(&sink);
    let subs_for_events = Arc::clone(&subscriptions);
    let event_forwarder = tokio::spawn(async move {
        while let Ok(event) = event_rx.recv().await {
            let path = event
                .get("path")
                .and_then(|v| v.as_str())
                .unwrap_or_default();
            let subs = subs_for_events.read().await;
            for sub in subs.iter() {
                if sub.pattern.is_match(path) {
                    let mut forwarded = event.clone();
                    if let Some(obj) = forwarded.as_object_mut() {
                        obj.insert("subscription".into(), Value::String(sub.id.clone()));
                    }
                    let text = serde_json::to_string(&forwarded).unwrap_or_default();
                    let mut s = sink_for_events.lock().await;
                    if s.send(Message::Text(text.into())).await.is_err() {
                        return;
                    }
                }
            }
        }
    });

    // Process incoming messages from external client.
    while let Some(frame) = read.next().await {
        let frame = frame?;
        let text = match &frame {
            Message::Text(t) => t.as_ref(),
            Message::Close(_) => break,
            Message::Ping(_) => {
                let mut s = sink.lock().await;
                let _ = s.send(Message::Pong(vec![].into())).await;
                continue;
            }
            _ => continue,
        };

        let msg: Value = match serde_json::from_str(text) {
            Ok(v) => v,
            Err(_) => continue,
        };

        let msg_type = msg.get("type").and_then(|v| v.as_str()).unwrap_or_default();
        let msg_id = msg
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string();

        match msg_type {
            "subscribe" => {
                let pattern_str = msg
                    .get("pattern")
                    .and_then(|v| v.as_str())
                    .unwrap_or("*");
                // Convert glob to regex: escape dots, * → .*
                let regex_str = format!(
                    "^{}$",
                    regex::escape(pattern_str).replace(r"\*", ".*")
                );
                if let Ok(re) = regex::Regex::new(&regex_str) {
                    subscriptions.write().await.push(Subscription {
                        id: msg_id,
                        pattern: re,
                    });
                }
            }
            "unsubscribe" => {
                subscriptions
                    .write()
                    .await
                    .retain(|s| s.id != msg_id);
            }
            "execute" | "query" | "list" => {
                let (tx, rx) = oneshot::channel();
                state.pending.lock().await.insert(msg_id.clone(), tx);

                // Emit to frontend
                let event_name = format!("command:{msg_type}");
                if let Err(e) = app.emit(&event_name, msg.clone()) {
                    log::error!("Failed to emit {event_name}: {e}");
                    state.pending.lock().await.remove(&msg_id);
                    send_error(&sink, &msg_id, "internal: event emit failed").await;
                    continue;
                }

                // Wait for result with timeout
                let sink_c = Arc::clone(&sink);
                let id_c = msg_id.clone();
                let state_c = Arc::clone(&state);
                tokio::spawn(async move {
                    match tokio::time::timeout(REQUEST_TIMEOUT, rx).await {
                        Ok(Ok(result)) => {
                            let text = serde_json::to_string(&result).unwrap_or_default();
                            let mut s = sink_c.lock().await;
                            let _ = s.send(Message::Text(text.into())).await;
                        }
                        Ok(Err(_)) => {
                            // Sender dropped (connection closed)
                        }
                        Err(_) => {
                            // Timeout
                            state_c.pending.lock().await.remove(&id_c);
                            send_error(&sink_c, &id_c, "timeout: no response from frontend")
                                .await;
                        }
                    }
                });
            }
            _ => {
                log::debug!("Command relay: unknown message type '{msg_type}'");
            }
        }
    }

    // Cleanup
    event_forwarder.abort();
    // Remove any dangling pending requests for this connection
    // (they'll get oneshot::Sender dropped which is fine)

    Ok(())
}

async fn send_error(sink: &Arc<Mutex<WsSink>>, id: &str, error: &str) {
    let msg = serde_json::json!({
        "type": "result",
        "id": id,
        "data": { "ok": false, "error": error }
    });
    let text = serde_json::to_string(&msg).unwrap_or_default();
    let mut s = sink.lock().await;
    let _ = s.send(Message::Text(text.into())).await;
}
