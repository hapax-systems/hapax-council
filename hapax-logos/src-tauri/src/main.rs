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
            commands::state::get_working_mode,
            commands::state::set_working_mode,
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
            // System flow (live anatomy)
            commands::system_flow::get_system_flow,
            // Visual surface control
            visual::control::get_visual_surface_state,
            visual::control::set_visual_layer_param,
            visual::control::get_visual_surface_snapshot,
            visual::control::toggle_visual_window,
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
            // Proxy (HTTP-only endpoints → FastAPI :8051)
            commands::proxy::proxy_get_generic,
            commands::proxy::proxy_post,
            commands::proxy::proxy_delete,
            commands::proxy::proxy_compositor_live,
            commands::proxy::proxy_studio_disk,
            commands::proxy::proxy_enable_recording,
            commands::proxy::proxy_disable_recording,
            commands::proxy::proxy_copilot,
            commands::proxy::proxy_scout_decide,
            commands::proxy::proxy_delete_demo,
            commands::proxy::proxy_consent_contracts,
            commands::proxy::proxy_consent_trace,
            commands::proxy::proxy_consent_coverage,
            commands::proxy::proxy_consent_overhead,
            commands::proxy::proxy_consent_precedents,
            commands::proxy::proxy_governance_heartbeat,
            commands::proxy::proxy_governance_coverage,
            commands::proxy::proxy_governance_carriers,
            commands::proxy::proxy_engine_status,
            commands::proxy::proxy_engine_rules,
            commands::proxy::proxy_engine_history,
            commands::proxy::proxy_profile,
            commands::proxy::proxy_profile_dimension,
            commands::proxy::proxy_profile_pending,
            commands::proxy::proxy_insight_queries,
            commands::proxy::proxy_insight_query,
            commands::proxy::proxy_run_insight_query,
            commands::proxy::proxy_refine_insight_query,
            commands::proxy::proxy_delete_insight_query,
            commands::proxy::proxy_fortress_state,
            commands::proxy::proxy_fortress_governance,
            commands::proxy::proxy_fortress_goals,
            commands::proxy::proxy_fortress_events,
            commands::proxy::proxy_fortress_metrics,
            commands::proxy::proxy_fortress_sessions,
            commands::proxy::proxy_fortress_chronicle,
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
            // Streaming (SSE bridge)
            commands::streaming::start_stream,
            commands::streaming::cancel_stream,
            commands::streaming::cancel_stream_and_server,
        ])
        .manage(commands::streaming::StreamRegistry::new())
        .manage(commands::proxy::HttpClient(reqwest::Client::new()))
        .setup(|app| {
            // Spawn the wgpu visual surface on a dedicated thread
            // Skip if HAPAX_NO_VISUAL=1 (useful when visual surface conflicts with Wayland)
            if std::env::var("HAPAX_NO_VISUAL").unwrap_or_default() != "1" {
                visual::bridge::spawn_visual_surface(app.handle().clone());
            } else {
                log::info!("Visual surface disabled (HAPAX_NO_VISUAL=1)");
            }
            // Spawn the HTTP frame server (GET /frame, GET /stats on :8053)
            visual::http_server::start_frame_server();
            // Spawn the directive watcher (reads agent directives from shm)
            commands::directive_watcher::spawn_directive_watcher(app.handle().clone());
            // Spawn headless browser engine for agent web access
            browser::commands::spawn_browser_engine(app.handle().clone());
            // Spawn command relay WebSocket server for external clients (MCP, voice)
            commands::relay::spawn_relay_server(app.handle());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running hapax-logos");
}
