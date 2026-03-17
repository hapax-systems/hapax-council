// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod browser;
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
            // Visual surface control
            visual::control::get_visual_surface_state,
            visual::control::set_visual_layer_param,
            visual::control::get_visual_surface_snapshot,
            // Introspection: Hapax self-manipulation
            commands::introspect::navigate,
            commands::introspect::toggle_panel,
            commands::introspect::show_toast,
            commands::introspect::show_modal,
            commands::introspect::dismiss_modal,
            commands::introspect::highlight_element,
            commands::introspect::set_status,
            commands::introspect::get_window_state,
            commands::introspect::set_window_position,
            commands::introspect::set_window_fullscreen,
            commands::introspect::set_window_always_on_top,
            commands::introspect::focus_window,
            commands::introspect::set_visual_stance,
            commands::introspect::visual_ping,
            commands::introspect::ui_directive,
            // Browser (agent-controlled web access)
            browser::commands::browser_navigate,
            browser::commands::browser_eval,
            browser::commands::browser_screenshot,
            browser::commands::browser_get_url,
            browser::commands::browser_get_title,
            browser::commands::browser_click,
            browser::commands::browser_fill,
            browser::commands::browser_press_key,
            browser::a11y::browser_a11y_tree,
            browser::services::browser_get_services,
            browser::services::browser_resolve_url,
        ])
        .setup(|app| {
            // Spawn the wgpu visual surface on a dedicated thread
            visual::bridge::spawn_visual_surface(app.handle().clone());
            // Spawn the directive watcher (reads agent directives from shm)
            commands::directive_watcher::spawn_directive_watcher(app.handle().clone());
            // Spawn headless browser engine for agent web access
            browser::commands::spawn_browser_engine(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running hapax-logos");
}
