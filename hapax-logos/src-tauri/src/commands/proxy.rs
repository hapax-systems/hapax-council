//! Proxy commands that forward HTTP requests to the FastAPI logos API at :8051.
//!
//! These exist for endpoints that don't yet have native Rust implementations.
//! Each command is a thin IPC→HTTP bridge so the frontend never makes direct
//! HTTP calls — all traffic goes through Tauri invoke().

use serde_json::Value;
use tauri::{AppHandle, Manager};

const LOGOS_BASE: &str = "http://127.0.0.1:8051/api";

/// Shared reqwest client stored in Tauri managed state for connection pooling.
pub struct HttpClient(pub reqwest::Client);

// ── Reusable helpers ──────────────────────────────────────────────────────────

fn client(app: &AppHandle) -> reqwest::Client {
    app.state::<HttpClient>().0.clone()
}

async fn proxy_get(app: &AppHandle, path: &str) -> Result<Value, String> {
    let url = format!("{}{}", LOGOS_BASE, path);
    let resp = client(app)
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("proxy GET {}: {}", path, e))?;
    if !resp.status().is_success() {
        return Err(format!("proxy GET {} returned {}", path, resp.status()));
    }
    resp.json::<Value>()
        .await
        .map_err(|e| format!("proxy GET {} json: {}", path, e))
}

async fn proxy_post_json(app: &AppHandle, path: &str, body: Option<Value>) -> Result<Value, String> {
    let url = format!("{}{}", LOGOS_BASE, path);
    let c = client(app);
    let req = if let Some(b) = body {
        c.post(&url).json(&b)
    } else {
        c.post(&url)
    };
    let resp = req
        .send()
        .await
        .map_err(|e| format!("proxy POST {}: {}", path, e))?;
    if !resp.status().is_success() {
        return Err(format!("proxy POST {} returned {}", path, resp.status()));
    }
    resp.json::<Value>()
        .await
        .map_err(|e| format!("proxy POST {} json: {}", path, e))
}

async fn proxy_delete_req(app: &AppHandle, path: &str) -> Result<Value, String> {
    let url = format!("{}{}", LOGOS_BASE, path);
    let resp = client(app)
        .delete(&url)
        .send()
        .await
        .map_err(|e| format!("proxy DELETE {}: {}", path, e))?;
    if !resp.status().is_success() {
        return Err(format!("proxy DELETE {} returned {}", path, resp.status()));
    }
    resp.json::<Value>()
        .await
        .map_err(|e| format!("proxy DELETE {} json: {}", path, e))
}

// ── Generic proxy commands (for ChatProvider and other dynamic paths) ─────────

#[tauri::command]
pub async fn proxy_get_generic(app: AppHandle, path: String) -> Result<Value, String> {
    proxy_get(&app, &path).await
}

#[tauri::command]
pub async fn proxy_post(app: AppHandle, path: String, body: Option<Value>) -> Result<Value, String> {
    proxy_post_json(&app, &path, body).await
}

#[tauri::command]
pub async fn proxy_delete(app: AppHandle, path: String) -> Result<Value, String> {
    proxy_delete_req(&app, &path).await
}

// ── Studio ────────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn proxy_compositor_live(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/studio/compositor/live").await
}

#[tauri::command]
pub async fn proxy_studio_disk(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/studio/disk").await
}

#[tauri::command]
pub async fn proxy_enable_recording(app: AppHandle) -> Result<Value, String> {
    proxy_post_json(&app, "/studio/recording/enable", None).await
}

#[tauri::command]
pub async fn proxy_disable_recording(app: AppHandle) -> Result<Value, String> {
    proxy_post_json(&app, "/studio/recording/disable", None).await
}

// ── Copilot ───────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn proxy_copilot(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/copilot").await
}

// ── Scout mutations ───────────────────────────────────────────────────────────

#[tauri::command]
pub async fn proxy_scout_decide(
    app: AppHandle,
    component: String,
    decision: String,
    notes: String,
) -> Result<Value, String> {
    let body = serde_json::json!({ "decision": decision, "notes": notes });
    proxy_post_json(
        &app,
        &format!("/scout/{}/decide", component),
        Some(body),
    )
    .await
}

// ── Demo mutations ────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn proxy_delete_demo(app: AppHandle, id: String) -> Result<Value, String> {
    proxy_delete_req(&app, &format!("/demos/{}", id)).await
}

// ── Governance & Consent ──────────────────────────────────────────────────────

#[tauri::command]
pub async fn proxy_consent_contracts(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/consent/contracts").await
}

#[tauri::command]
pub async fn proxy_consent_trace(app: AppHandle, path: Option<String>) -> Result<Value, String> {
    match path {
        Some(p) => {
            let encoded = urlencoding::encode(&p);
            proxy_get(&app, &format!("/consent/trace?path={}", encoded)).await
        }
        None => proxy_get(&app, "/consent/trace").await,
    }
}

#[tauri::command]
pub async fn proxy_consent_coverage(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/consent/coverage").await
}

#[tauri::command]
pub async fn proxy_consent_overhead(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/consent/overhead").await
}

#[tauri::command]
pub async fn proxy_consent_precedents(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/consent/precedents").await
}

#[tauri::command]
pub async fn proxy_governance_heartbeat(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/governance/heartbeat").await
}

#[tauri::command]
pub async fn proxy_governance_coverage(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/governance/coverage").await
}

#[tauri::command]
pub async fn proxy_governance_carriers(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/governance/carriers").await
}

// ── Engine ────────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn proxy_engine_status(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/engine/status").await
}

#[tauri::command]
pub async fn proxy_engine_rules(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/engine/rules").await
}

#[tauri::command]
pub async fn proxy_engine_history(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/engine/history").await
}

// ── Profile ───────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn proxy_profile(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/profile").await
}

#[tauri::command]
pub async fn proxy_profile_dimension(app: AppHandle, dim: String) -> Result<Value, String> {
    proxy_get(&app, &format!("/profile/{}", dim)).await
}

#[tauri::command]
pub async fn proxy_profile_pending(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/profile/facts/pending").await
}

// ── Insight Queries ───────────────────────────────────────────────────────────

#[tauri::command]
pub async fn proxy_insight_queries(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/query/list").await
}

#[tauri::command]
pub async fn proxy_insight_query(app: AppHandle, id: String) -> Result<Value, String> {
    proxy_get(&app, &format!("/query/{}", id)).await
}

#[tauri::command]
pub async fn proxy_run_insight_query(app: AppHandle, query: String) -> Result<Value, String> {
    proxy_post_json(&app, "/query/run", Some(serde_json::json!({ "query": query }))).await
}

#[tauri::command]
pub async fn proxy_refine_insight_query(
    app: AppHandle,
    query: String,
    parent_id: String,
    prior_result: String,
    agent_type: String,
) -> Result<Value, String> {
    proxy_post_json(
        &app,
        "/query/refine",
        Some(serde_json::json!({
            "query": query,
            "parent_id": parent_id,
            "prior_result": prior_result,
            "agent_type": agent_type,
        })),
    )
    .await
}

#[tauri::command]
pub async fn proxy_delete_insight_query(app: AppHandle, id: String) -> Result<Value, String> {
    proxy_delete_req(&app, &format!("/query/{}", id)).await
}

// ── Fortress ──────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn proxy_fortress_state(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/fortress/state").await
}

#[tauri::command]
pub async fn proxy_fortress_governance(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/fortress/governance").await
}

#[tauri::command]
pub async fn proxy_fortress_goals(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/fortress/goals").await
}

#[tauri::command]
pub async fn proxy_fortress_events(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/fortress/events").await
}

#[tauri::command]
pub async fn proxy_fortress_metrics(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/fortress/metrics").await
}

#[tauri::command]
pub async fn proxy_fortress_sessions(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/fortress/sessions").await
}

#[tauri::command]
pub async fn proxy_fortress_chronicle(app: AppHandle) -> Result<Value, String> {
    proxy_get(&app, "/fortress/chronicle").await
}
