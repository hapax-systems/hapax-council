//! IPC protocol for hapax-imagination.
//!
//! Newline-delimited JSON over Unix domain sockets.
//! Each message is a single JSON object terminated by `\n`.

use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// Inbound commands
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type")]
pub enum Command {
    Window { action: WindowAction },
    Render { action: RenderAction },
    Status,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "action")]
pub enum WindowAction {
    Fullscreen,
    Maximized,
    Windowed { x: i32, y: i32, w: u32, h: u32 },
    Borderless { monitor: usize },
    Hide,
    Show,
    AlwaysOnTop { enabled: bool },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "action")]
pub enum RenderAction {
    SetFps { fps: u32 },
    Pause,
    Resume,
}

// ---------------------------------------------------------------------------
// Outbound responses
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type")]
pub enum Response {
    Status {
        visible: bool,
        mode: String,
        monitor: usize,
        fps: u32,
        frame_count: u64,
        dimensions: (u32, u32),
    },
    Ack {
        for_type: String,
    },
    Error {
        message: String,
    },
    FrameStats {
        frame_time_ms: f64,
        stance: f64,
        warmth: f64,
        fps: u32,
    },
}

// ---------------------------------------------------------------------------
// Protocol functions
// ---------------------------------------------------------------------------

/// Parse a single line of JSON into a [`Command`].
pub fn parse_command(line: &str) -> Result<Command, String> {
    serde_json::from_str(line.trim()).map_err(|e| format!("parse error: {e}"))
}

/// Serialize a [`Response`] to a newline-terminated JSON string.
pub fn serialize_response(resp: &Response) -> String {
    let mut s = serde_json::to_string(resp).expect("Response must be serializable");
    s.push('\n');
    s
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_fullscreen() {
        let input = r#"{"type":"Window","action":{"action":"Fullscreen"}}"#;
        let cmd = parse_command(input).unwrap();
        assert_eq!(
            cmd,
            Command::Window {
                action: WindowAction::Fullscreen,
            }
        );
    }

    #[test]
    fn parse_windowed() {
        let input = r#"{"type":"Window","action":{"action":"Windowed","x":100,"y":200,"w":800,"h":600}}"#;
        let cmd = parse_command(input).unwrap();
        assert_eq!(
            cmd,
            Command::Window {
                action: WindowAction::Windowed {
                    x: 100,
                    y: 200,
                    w: 800,
                    h: 600,
                },
            }
        );
    }

    #[test]
    fn parse_status() {
        let input = r#"{"type":"Status"}"#;
        let cmd = parse_command(input).unwrap();
        assert_eq!(cmd, Command::Status);
    }

    #[test]
    fn parse_render_pause() {
        let input = r#"{"type":"Render","action":{"action":"Pause"}}"#;
        let cmd = parse_command(input).unwrap();
        assert_eq!(
            cmd,
            Command::Render {
                action: RenderAction::Pause,
            }
        );
    }

    #[test]
    fn serialize_ack() {
        let resp = Response::Ack {
            for_type: "Window".into(),
        };
        let json = serialize_response(&resp);
        assert!(json.ends_with('\n'));
        assert!(json.contains(r#""for_type":"Window"#));
    }

    #[test]
    fn serialize_status() {
        let resp = Response::Status {
            visible: true,
            mode: "Fullscreen".into(),
            monitor: 0,
            fps: 60,
            frame_count: 1234,
            dimensions: (1920, 1080),
        };
        let json = serialize_response(&resp);
        assert!(json.ends_with('\n'));
        // Round-trip through parse to verify structure
        let parsed: Response = serde_json::from_str(json.trim()).unwrap();
        assert_eq!(parsed, resp);
    }

    #[test]
    fn parse_invalid_returns_error() {
        let input = r#"{"not":"valid"}"#;
        let result = parse_command(input);
        assert!(result.is_err());
    }
}
