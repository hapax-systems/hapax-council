use serde::{Deserialize, Serialize};
use std::path::Path;

// --- Agent Registry ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentFlag {
    #[serde(default)]
    pub flag: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub flag_type: String,
    #[serde(default)]
    pub default: Option<String>,
    #[serde(default)]
    pub choices: Option<Vec<String>>,
    #[serde(default)]
    pub metavar: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentInfo {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub uses_llm: bool,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub command: String,
    #[serde(default)]
    pub module: String,
    #[serde(default)]
    pub flags: Vec<AgentFlag>,
}

#[tauri::command]
pub fn get_agents() -> Vec<AgentInfo> {
    // The agent registry is computed from Python module introspection.
    // Read cached snapshot written by the logos API.
    let path = expand_home("~/.hapax/profiles/agent-registry.json");
    read_json::<Vec<AgentInfo>>(&path).unwrap_or_default()
}

// --- Demos ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Demo {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub audience: String,
    #[serde(default)]
    pub scope: String,
    #[serde(default)]
    pub scenes: u32,
    #[serde(default)]
    pub format: String,
    #[serde(default)]
    pub duration: u32,
    #[serde(default)]
    pub timestamp: String,
    #[serde(default)]
    pub primary_file: String,
    #[serde(default)]
    pub files: Vec<String>,
    #[serde(default)]
    pub dir: String,
    #[serde(default)]
    pub has_video: Option<bool>,
    #[serde(default)]
    pub has_audio: Option<bool>,
}

#[tauri::command]
pub fn get_demos() -> Vec<Demo> {
    let demos_dir = expand_home("~/projects/hapax-council/output/demos");
    let dir = Path::new(&demos_dir);
    if !dir.is_dir() {
        return vec![];
    }

    let mut demos: Vec<Demo> = std::fs::read_dir(dir)
        .into_iter()
        .flatten()
        .filter_map(|entry| entry.ok())
        .filter(|entry| entry.path().is_dir())
        .filter_map(|entry| {
            let demo_dir = entry.path();
            let meta_path = demo_dir.join("meta.json");
            if !meta_path.exists() {
                return None;
            }
            let data = std::fs::read_to_string(&meta_path).ok()?;
            let mut demo: Demo = serde_json::from_str(&data).ok()?;
            demo.id = entry.file_name().to_string_lossy().to_string();
            demo.dir = demo_dir.to_string_lossy().to_string();

            // List files in the demo directory
            demo.files = std::fs::read_dir(&demo_dir)
                .into_iter()
                .flatten()
                .filter_map(|f| f.ok())
                .filter(|f| f.path().is_file())
                .map(|f| f.file_name().to_string_lossy().to_string())
                .collect();

            demo.has_video = Some(demo.files.iter().any(|f| f.ends_with(".mp4")));
            demo.has_audio = Some(
                demo.files
                    .iter()
                    .any(|f| f.ends_with(".mp3") || f.ends_with(".wav")),
            );

            Some(demo)
        })
        .collect();

    demos.sort_by(|a, b| b.timestamp.cmp(&a.timestamp));
    demos
}

#[tauri::command]
pub fn get_demo(id: String) -> Option<Demo> {
    // Path traversal guard
    if id.contains("..") || id.contains('/') || id.contains('\\') {
        return None;
    }

    let demos_dir = expand_home("~/projects/hapax-council/output/demos");
    let demo_dir = Path::new(&demos_dir).join(&id);
    let meta_path = demo_dir.join("meta.json");

    if !meta_path.exists() {
        return None;
    }

    let data = std::fs::read_to_string(&meta_path).ok()?;
    let mut demo: Demo = serde_json::from_str(&data).ok()?;
    demo.id = id;
    demo.dir = demo_dir.to_string_lossy().to_string();

    demo.files = std::fs::read_dir(&demo_dir)
        .into_iter()
        .flatten()
        .filter_map(|f| f.ok())
        .filter(|f| f.path().is_file())
        .map(|f| f.file_name().to_string_lossy().to_string())
        .collect();

    demo.has_video = Some(demo.files.iter().any(|f| f.ends_with(".mp4")));
    demo.has_audio = Some(
        demo.files
            .iter()
            .any(|f| f.ends_with(".mp3") || f.ends_with(".wav")),
    );

    Some(demo)
}

// --- Helpers ---

fn expand_home(path: &str) -> String {
    if path.starts_with("~/") {
        if let Ok(home) = std::env::var("HOME") {
            return format!("{}{}", home, &path[1..]);
        }
    }
    path.to_string()
}

fn read_json<T: serde::de::DeserializeOwned>(path: &str) -> Option<T> {
    let p = Path::new(path);
    let data = std::fs::read_to_string(p).ok()?;
    serde_json::from_str(&data).ok()
}
