// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;
mod visual;

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            commands::greet,
            // Health
            commands::health::get_health,
            commands::health::get_gpu,
            commands::health::get_infrastructure,
            commands::health::get_health_history,
            // State
            commands::state::get_cycle_mode,
            commands::state::set_cycle_mode,
            commands::state::get_accommodations,
            commands::state::get_manual,
            commands::state::get_goals,
            commands::state::get_scout,
            commands::state::get_scout_decisions,
            commands::state::get_drift,
            commands::state::get_management,
            commands::state::get_nudges,
            commands::state::get_readiness,
            // Studio
            commands::studio::get_studio,
            commands::studio::get_studio_stream_info,
            commands::studio::get_studio_snapshot,
            commands::studio::get_perception,
            commands::studio::get_visual_layer,
            commands::studio::select_effect,
            // Agents
            commands::agents::get_agents,
            commands::agents::get_demos,
            commands::agents::get_demo,
            // Governance
            commands::governance::get_briefing,
            // Cost (Tier 2: Langfuse)
            commands::cost::get_cost,
        ])
        .setup(|app| {
            // Spawn the wgpu visual surface on a dedicated thread
            visual::bridge::spawn_visual_surface(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running hapax-cockpit");
}
