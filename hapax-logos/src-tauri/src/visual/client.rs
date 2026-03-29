//! UDS client for communicating with the hapax-imagination binary.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;

static CONNECTION: Mutex<Option<UnixStream>> = Mutex::new(None);

fn socket_path() -> String {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".into());
    format!("{}/hapax-imagination.sock", runtime_dir)
}

fn connect() -> Option<UnixStream> {
    UnixStream::connect(socket_path()).ok().map(|s| {
        s.set_read_timeout(Some(Duration::from_secs(2))).ok();
        s.set_write_timeout(Some(Duration::from_secs(2))).ok();
        s
    })
}

fn get_or_connect() -> Option<UnixStream> {
    let mut guard = CONNECTION.lock().ok()?;
    if guard.is_none() {
        *guard = connect();
    }
    guard.as_ref().and_then(|s| s.try_clone().ok())
}

/// Send a JSON command and read the response line.
pub fn send_command(json: &str) -> Result<String, String> {
    let mut stream = get_or_connect().ok_or("imagination binary not connected")?;
    let mut msg = json.to_string();
    if !msg.ends_with('\n') {
        msg.push('\n');
    }
    stream.write_all(msg.as_bytes()).map_err(|e| {
        if let Ok(mut g) = CONNECTION.lock() {
            *g = None;
        }
        format!("write failed: {e}")
    })?;
    let mut reader = BufReader::new(&stream);
    let mut response = String::new();
    reader.read_line(&mut response).map_err(|e| {
        if let Ok(mut g) = CONNECTION.lock() {
            *g = None;
        }
        format!("read failed: {e}")
    })?;
    Ok(response)
}

pub fn window_command(action: &str) -> Result<String, String> {
    send_command(&format!(r#"{{"type":"window","action":"{}"}}"#, action))
}

pub fn status() -> Result<String, String> {
    send_command(r#"{"type":"status"}"#)
}

pub fn is_connected() -> bool {
    status().is_ok()
}
