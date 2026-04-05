//! FX frame relay: TCP listener (:8054) receives JPEG frames from the Python
//! compositor, broadcasts them to all connected WebSocket clients via the
//! axum server at :8053/ws/fx.
//!
//! Protocol: each TCP message is [4-byte LE length][JPEG bytes].
//! WebSocket clients receive raw binary JPEG frames.

use std::sync::Arc;
use tokio::io::AsyncReadExt;
use tokio::sync::broadcast;

/// Capacity of the broadcast channel (frames). If a slow consumer falls behind,
/// it gets a Lagged error and skips to the latest frame.
const CHANNEL_CAPACITY: usize = 4;

/// TCP port the Python compositor pushes JPEG frames to.
const RELAY_PORT: u16 = 8054;

/// Shared state: a broadcast sender for JPEG frame bytes.
#[derive(Clone)]
pub struct FxFrameRelay {
    tx: Arc<broadcast::Sender<Arc<Vec<u8>>>>,
}

impl FxFrameRelay {
    pub fn new() -> Self {
        let (tx, _) = broadcast::channel(CHANNEL_CAPACITY);
        Self { tx: Arc::new(tx) }
    }

    /// Subscribe to receive frames.
    pub fn subscribe(&self) -> broadcast::Receiver<Arc<Vec<u8>>> {
        self.tx.subscribe()
    }

    /// Start the TCP listener that receives frames from the compositor.
    pub fn start_tcp_listener(&self) {
        let tx = self.tx.clone();
        tauri::async_runtime::spawn(async move {
            let listener = match tokio::net::TcpListener::bind(("127.0.0.1", RELAY_PORT)).await {
                Ok(l) => l,
                Err(e) => {
                    log::error!("FX relay: failed to bind TCP on :{}: {}", RELAY_PORT, e);
                    return;
                }
            };
            log::info!("FX relay: listening for compositor frames on TCP :{}", RELAY_PORT);

            loop {
                match listener.accept().await {
                    Ok((stream, addr)) => {
                        log::info!("FX relay: compositor connected from {}", addr);
                        let tx = tx.clone();
                        tauri::async_runtime::spawn(async move {
                            handle_compositor_connection(stream, tx).await;
                            log::info!("FX relay: compositor disconnected");
                        });
                    }
                    Err(e) => {
                        log::error!("FX relay: accept error: {}", e);
                    }
                }
            }
        });
    }
}

async fn handle_compositor_connection(
    mut stream: tokio::net::TcpStream,
    tx: Arc<broadcast::Sender<Arc<Vec<u8>>>>,
) {
    let mut len_buf = [0u8; 4];
    loop {
        // Read 4-byte LE length prefix
        if stream.read_exact(&mut len_buf).await.is_err() {
            break;
        }
        let len = u32::from_le_bytes(len_buf) as usize;
        if len == 0 || len > 4_000_000 {
            // Sanity check: skip invalid frames (>4MB is unreasonable for JPEG)
            break;
        }

        // Read JPEG payload
        let mut buf = vec![0u8; len];
        if stream.read_exact(&mut buf).await.is_err() {
            break;
        }

        // Broadcast to all WebSocket subscribers (non-blocking, drops if no consumers)
        let _ = tx.send(Arc::new(buf));
    }
}
