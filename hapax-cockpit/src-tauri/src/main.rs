// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;
mod visual;

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![commands::greet])
        .setup(|app| {
            // Spawn the wgpu visual surface on a dedicated thread
            visual::bridge::spawn_visual_surface(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running hapax-cockpit");
}
