pub mod agents;
pub mod cost;
pub mod governance;
pub mod health;
pub mod state;
pub mod studio;

/// Smoke-test command to verify IPC works.
#[tauri::command]
pub fn greet(name: &str) -> String {
    format!("Hello, {}! IPC is working.", name)
}
