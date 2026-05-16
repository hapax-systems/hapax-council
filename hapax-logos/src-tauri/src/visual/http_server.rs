//! Axum HTTP + WebSocket server for visual surface frames.
//!
//! - GET /frame — reads /dev/shm/hapax-visual/frame.jpg, returns image/jpeg
//! - GET /stats — reads /dev/shm/hapax-visual/state.json, returns application/json
//! - GET /fx — reads /dev/shm/hapax-compositor/fx-snapshot.jpg (legacy polling)
//! - WS /ws/fx — live WebSocket stream of JPEG frames from compositor (30fps push)
//! - 503 if no frame available yet

use axum::{
    extract::{ws::WebSocket, State, WebSocketUpgrade},
    http::{header, StatusCode},
    response::IntoResponse,
    routing::get,
    Router,
};
use std::net::SocketAddr;
use std::sync::Arc;

use super::fx_relay::FxFrameRelay;

const DEFAULT_PORT: u16 = 8053;
const FRAME_PATH: &str = "/dev/shm/hapax-visual/frame.jpg";
const STATE_PATH: &str = "/dev/shm/hapax-visual/state.json";
const FX_FRAME_PATH: &str = "/dev/shm/hapax-compositor/fx-snapshot.jpg";

async fn serve_frame() -> impl IntoResponse {
    match tokio::fs::read(FRAME_PATH).await {
        Ok(bytes) => (
            StatusCode::OK,
            [
                (header::CONTENT_TYPE, "image/jpeg"),
                (header::CACHE_CONTROL, "no-store"),
            ],
            bytes,
        )
            .into_response(),
        Err(_) => (StatusCode::SERVICE_UNAVAILABLE, "no frame available").into_response(),
    }
}

async fn serve_stats() -> impl IntoResponse {
    match tokio::fs::read(STATE_PATH).await {
        Ok(bytes) => (
            StatusCode::OK,
            [
                (header::CONTENT_TYPE, "application/json"),
                (header::CACHE_CONTROL, "no-store"),
            ],
            bytes,
        )
            .into_response(),
        Err(_) => (StatusCode::SERVICE_UNAVAILABLE, "no state available").into_response(),
    }
}

async fn serve_fx_frame() -> impl IntoResponse {
    match tokio::fs::read(FX_FRAME_PATH).await {
        Ok(bytes) => (
            StatusCode::OK,
            [
                (header::CONTENT_TYPE, "image/jpeg"),
                (header::CACHE_CONTROL, "no-store"),
            ],
            bytes,
        )
            .into_response(),
        Err(_) => (StatusCode::SERVICE_UNAVAILABLE, "no fx frame available").into_response(),
    }
}

/// WebSocket upgrade handler for /ws/fx — pushes live JPEG frames.
async fn ws_fx_upgrade(
    ws: WebSocketUpgrade,
    State(relay): State<Arc<FxFrameRelay>>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| ws_fx_handler(socket, relay))
}

async fn ws_fx_handler(mut socket: WebSocket, relay: Arc<FxFrameRelay>) {
    let mut rx = relay.subscribe();
    loop {
        match rx.recv().await {
            Ok(frame) => {
                if socket
                    .send(axum::extract::ws::Message::Binary(frame.to_vec().into()))
                    .await
                    .is_err()
                {
                    break; // client disconnected
                }
            }
            Err(tokio::sync::broadcast::error::RecvError::Lagged(n)) => {
                log::debug!("FX WS client lagged by {} frames, catching up", n);
            }
            Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
        }
    }
}

/// Spawn the frame server as an async task. Call from setup().
pub fn start_frame_server() {
    let port = std::env::var("HAPAX_VISUAL_HTTP_PORT")
        .ok()
        .and_then(|v| v.parse::<u16>().ok())
        .unwrap_or(DEFAULT_PORT);

    // Start the FX frame relay (TCP listener for compositor → WS broadcast)
    let relay = Arc::new(FxFrameRelay::new());
    relay.start_tcp_listener();

    let relay_ws = relay.clone();
    tauri::async_runtime::spawn(async move {
        let app = Router::new()
            .route("/frame", get(serve_frame))
            .route("/fx", get(serve_fx_frame))
            .route("/stats", get(serve_stats))
            .route("/ws/fx", get(ws_fx_upgrade))
            .with_state(relay_ws);

        let addr = SocketAddr::from(([127, 0, 0, 1], port));
        log::info!(
            "Visual frame server listening on http://{} (WS at /ws/fx)",
            addr
        );

        let listener = match tokio::net::TcpListener::bind(addr).await {
            Ok(l) => l,
            Err(e) => {
                log::error!("Failed to bind visual frame server on {}: {}", addr, e);
                return;
            }
        };

        if let Err(e) = axum::serve(listener, app).await {
            log::error!("Visual frame server error: {}", e);
        }
    });
}
