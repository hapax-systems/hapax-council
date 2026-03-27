//! Axum HTTP server serving the latest JPEG visual surface frame.
//!
//! - GET /frame — reads /dev/shm/hapax-visual/frame.jpg, returns image/jpeg
//! - GET /stats — reads /dev/shm/hapax-visual/state.json, returns application/json
//! - 503 if no frame available yet

use axum::{
    http::{header, StatusCode},
    response::IntoResponse,
    routing::get,
    Router,
};
use std::net::SocketAddr;

const DEFAULT_PORT: u16 = 8053;
const FRAME_PATH: &str = "/dev/shm/hapax-visual/frame.jpg";
const STATE_PATH: &str = "/dev/shm/hapax-visual/state.json";

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

/// Spawn the frame server as an async task. Call from setup().
pub fn start_frame_server() {
    let port = std::env::var("HAPAX_VISUAL_HTTP_PORT")
        .ok()
        .and_then(|v| v.parse::<u16>().ok())
        .unwrap_or(DEFAULT_PORT);

    tauri::async_runtime::spawn(async move {
        let app = Router::new()
            .route("/frame", get(serve_frame))
            .route("/stats", get(serve_stats));

        let addr = SocketAddr::from(([127, 0, 0, 1], port));
        log::info!("Visual frame server listening on http://{}", addr);

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
