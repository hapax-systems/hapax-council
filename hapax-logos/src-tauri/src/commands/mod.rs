pub mod agents;
pub mod cost;
pub mod directive_watcher;
pub mod governance;
pub mod health;
pub mod introspect;
pub mod proxy;
pub mod relay;
pub mod state;
pub mod streaming;
pub mod studio;
pub mod system_flow;

/// Smoke-test command to verify IPC works.
#[tauri::command]
pub fn greet(name: &str) -> String {
    format!("Hello, {}! IPC is working.", name)
}
