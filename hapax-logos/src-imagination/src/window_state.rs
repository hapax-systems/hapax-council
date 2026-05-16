//! Window state persistence for hapax-imagination.
//!
//! Persists window position, size, and mode to
//! `~/.config/hapax-imagination/window.json`.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub enum WindowMode {
    Windowed,
    Maximized,
    Fullscreen,
    Borderless,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct WindowState {
    pub mode: WindowMode,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub monitor: usize,
    pub always_on_top: bool,
}

impl Default for WindowState {
    fn default() -> Self {
        Self {
            mode: WindowMode::Windowed,
            x: 0,
            y: 0,
            width: 1920,
            height: 1080,
            monitor: 0,
            always_on_top: false,
        }
    }
}

// ---------------------------------------------------------------------------
// Config path
// ---------------------------------------------------------------------------

fn config_path() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from(".config"))
        .join("hapax-imagination")
        .join("window.json")
}

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

impl WindowState {
    /// Load window state from the config file.
    /// Returns [`Default`] if the file is missing or corrupt.
    pub fn load() -> Self {
        Self::load_from(&config_path())
    }

    /// Save window state to the config file, creating directories as needed.
    pub fn save(&self) -> Result<(), String> {
        self.save_to(&config_path())
    }

    // Internal helpers that accept a path (for testing).

    fn load_from(path: &PathBuf) -> Self {
        match fs::read_to_string(path) {
            Ok(contents) => serde_json::from_str(&contents).unwrap_or_default(),
            Err(_) => Self::default(),
        }
    }

    fn save_to(&self, path: &PathBuf) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("create dirs: {e}"))?;
        }
        let json = serde_json::to_string_pretty(self).map_err(|e| format!("serialize: {e}"))?;
        fs::write(path, json).map_err(|e| format!("write: {e}"))
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_values_correct() {
        let state = WindowState::default();
        assert_eq!(state.mode, WindowMode::Windowed);
        assert_eq!(state.x, 0);
        assert_eq!(state.y, 0);
        assert_eq!(state.width, 1920);
        assert_eq!(state.height, 1080);
        assert_eq!(state.monitor, 0);
        assert!(!state.always_on_top);
    }

    #[test]
    fn json_roundtrip() {
        let state = WindowState {
            mode: WindowMode::Fullscreen,
            x: 50,
            y: 75,
            width: 2560,
            height: 1440,
            monitor: 1,
            always_on_top: true,
        };

        let tmp = std::env::temp_dir().join("hapax-imagination-test-roundtrip.json");
        state.save_to(&tmp).unwrap();
        let loaded = WindowState::load_from(&tmp);
        assert_eq!(state, loaded);
        let _ = fs::remove_file(&tmp);
    }

    #[test]
    fn corrupt_json_returns_default() {
        let tmp = std::env::temp_dir().join("hapax-imagination-test-corrupt.json");
        fs::write(&tmp, "not valid json {{{").unwrap();
        let loaded = WindowState::load_from(&tmp);
        assert_eq!(loaded, WindowState::default());
        let _ = fs::remove_file(&tmp);
    }
}
