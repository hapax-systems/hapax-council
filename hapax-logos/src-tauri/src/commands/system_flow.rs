//! System flow state — unified snapshot of all shm-based subsystems.
//!
//! Reads every /dev/shm/hapax-* directory and returns a single JSON
//! object that the React Flow visualization consumes. Each subsystem
//! becomes a node; data freshness and throughput become edge metadata.

use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};

fn now_epoch() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

fn read_json(path: &str) -> Option<serde_json::Value> {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
}

fn age_s(val: &serde_json::Value) -> f64 {
    val.get("timestamp")
        .and_then(|t| t.as_f64())
        .map(|t| {
            if t < 1e9 {
                // Monotonic clock (time.monotonic() in Python) — small number.
                // We can't compute age from Rust since we don't share the
                // Python monotonic epoch. Fall back to file mtime instead.
                // For now, report 0.0 (fresh) since the file was just read.
                0.0
            } else {
                now_epoch() - t
            }
        })
        .unwrap_or(999.0)
}

// ── Node state structs ──────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Default)]
pub struct NodeState {
    pub id: String,
    pub label: String,
    pub status: String,        // "active" | "stale" | "offline"
    pub age_s: f64,            // seconds since last update
    pub metrics: serde_json::Value, // subsystem-specific key metrics
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct EdgeState {
    pub source: String,
    pub target: String,
    pub active: bool,
    pub label: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SystemFlowState {
    pub nodes: Vec<NodeState>,
    pub edges: Vec<EdgeState>,
    pub timestamp: f64,
}

// ── Main command ────────────────────────────────────────────────────

#[tauri::command]
pub fn get_system_flow() -> SystemFlowState {
    let now = now_epoch();
    let mut nodes = Vec::new();
    let mut edges = Vec::new();

    // ── Perception ──────────────────────────────────────────────
    let perception_path = format!(
        "{}/.cache/hapax-voice/perception-state.json",
        std::env::var("HOME").unwrap_or_default()
    );
    let perception = read_json(&perception_path);
    let perc_age = perception.as_ref().map(age_s).unwrap_or(999.0);
    nodes.push(NodeState {
        id: "perception".into(),
        label: "Perception".into(),
        status: if perc_age < 10.0 { "active" } else if perc_age < 30.0 { "stale" } else { "offline" }.into(),
        age_s: perc_age,
        metrics: perception.as_ref().map(|p| {
            serde_json::json!({
                "activity": p.get("production_activity").and_then(|v| v.as_str()).unwrap_or(""),
                "flow_score": p.get("flow_score").and_then(|v| v.as_f64()).unwrap_or(0.0),
                "presence_probability": p.get("presence_probability").and_then(|v| v.as_f64()),
                "face_count": p.get("face_count").and_then(|v| v.as_u64()).unwrap_or(0),
                "consent_phase": p.get("consent_phase").and_then(|v| v.as_str()).unwrap_or("none"),
            })
        }).unwrap_or(serde_json::json!({})),
    });

    // ── Stimmung ────────────────────────────────────────────────
    let stimmung = read_json("/dev/shm/hapax-stimmung/state.json");
    let stim_age = stimmung.as_ref().map(age_s).unwrap_or(999.0);
    nodes.push(NodeState {
        id: "stimmung".into(),
        label: "Stimmung".into(),
        status: if stim_age < 120.0 { "active" } else { "offline" }.into(),
        age_s: stim_age,
        metrics: stimmung.as_ref().map(|s| {
            serde_json::json!({
                "stance": s.get("overall_stance").and_then(|v| v.as_str()).unwrap_or("unknown"),
                "health": s.get("health").and_then(|v| v.get("value")).and_then(|v| v.as_f64()),
                "resource_pressure": s.get("resource_pressure").and_then(|v| v.get("value")).and_then(|v| v.as_f64()),
                "perception_confidence": s.get("perception_confidence").and_then(|v| v.get("value")).and_then(|v| v.as_f64()),
            })
        }).unwrap_or(serde_json::json!({})),
    });

    // ── Temporal Bands ──────────────────────────────────────────
    let temporal = read_json("/dev/shm/hapax-temporal/bands.json");
    let temp_age = temporal.as_ref().map(age_s).unwrap_or(999.0);
    nodes.push(NodeState {
        id: "temporal".into(),
        label: "Temporal Bands".into(),
        status: if temp_age < 10.0 { "active" } else if temp_age < 30.0 { "stale" } else { "offline" }.into(),
        age_s: temp_age,
        metrics: temporal.as_ref().map(|t| {
            serde_json::json!({
                "max_surprise": t.get("max_surprise").and_then(|v| v.as_f64()).unwrap_or(0.0),
                "retention_count": t.get("retention_count").and_then(|v| v.as_u64()).unwrap_or(0),
                "protention_count": t.get("protention_count").and_then(|v| v.as_u64()).unwrap_or(0),
                "surprise_count": t.get("surprise_count").and_then(|v| v.as_u64()).unwrap_or(0),
            })
        }).unwrap_or(serde_json::json!({})),
    });

    // ── Apperception ────────────────────────────────────────────
    let apperception = read_json("/dev/shm/hapax-apperception/self-band.json");
    let apper_age = apperception.as_ref().map(age_s).unwrap_or(999.0);
    nodes.push(NodeState {
        id: "apperception".into(),
        label: "Apperception".into(),
        status: if apper_age < 10.0 { "active" } else if apper_age < 30.0 { "stale" } else { "offline" }.into(),
        age_s: apper_age,
        metrics: apperception.as_ref().map(|a| {
            let model = a.get("self_model").cloned().unwrap_or(serde_json::json!({}));
            serde_json::json!({
                "coherence": model.get("coherence").and_then(|v| v.as_f64()).unwrap_or(0.0),
                "dimensions": model.get("dimensions").map(|d| {
                    if let Some(obj) = d.as_object() { obj.len() } else { 0 }
                }).unwrap_or(0),
                "observations": model.get("recent_observations").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
                "pending_actions": a.get("pending_actions").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
            })
        }).unwrap_or(serde_json::json!({})),
    });

    // ── Compositor (visual output) ──────────────────────────────
    let compositor = read_json("/dev/shm/hapax-compositor/visual-layer-state.json");
    let comp_age = compositor.as_ref().map(age_s).unwrap_or(999.0);
    nodes.push(NodeState {
        id: "compositor".into(),
        label: "Compositor".into(),
        status: if comp_age < 10.0 { "active" } else if comp_age < 30.0 { "stale" } else { "offline" }.into(),
        age_s: comp_age,
        metrics: compositor.as_ref().map(|c| {
            serde_json::json!({
                "display_state": c.get("display_state").and_then(|v| v.as_str()).unwrap_or("unknown"),
                "voice_active": c.get("voice_session").and_then(|v| v.get("active")).and_then(|v| v.as_bool()).unwrap_or(false),
            })
        }).unwrap_or(serde_json::json!({})),
    });

    // ── Voice Pipeline ──────────────────────────────────────────
    // Voice state is embedded in the compositor state
    let voice_active = compositor.as_ref()
        .and_then(|c| c.get("voice_session"))
        .and_then(|v| v.get("active"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let voice_state = compositor.as_ref()
        .and_then(|c| c.get("voice_session"))
        .and_then(|v| v.get("state"))
        .and_then(|v| v.as_str())
        .unwrap_or("off");
    let voice_session = compositor.as_ref()
        .and_then(|c| c.get("voice_session"));
    let routing_tier = voice_session
        .and_then(|v| v.get("routing_tier"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let routing_activation = voice_session
        .and_then(|v| v.get("routing_activation"))
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    nodes.push(NodeState {
        id: "voice".into(),
        label: "Voice Pipeline".into(),
        status: if voice_active { "active" } else { "offline" }.into(),
        age_s: comp_age,
        metrics: serde_json::json!({
            "active": voice_active,
            "state": voice_state,
            "tier": routing_tier,
            "activation": routing_activation,
        }),
    });

    // ── Phenomenal Context (renderer) ───────────────────────────
    // No separate shm file — it reads temporal + apperception + stimmung
    // Mark as active if its sources are active
    let phenom_active = temp_age < 30.0 || apper_age < 30.0;
    nodes.push(NodeState {
        id: "phenomenal".into(),
        label: "Phenomenal Context".into(),
        status: if phenom_active { "active" } else { "offline" }.into(),
        age_s: temp_age.min(apper_age),
        metrics: serde_json::json!({}),
    });

    // ── Reactive Engine ─────────────────────────────────────────
    // Engine status from cockpit (try reading cached state)
    let engine_cache = format!(
        "{}/.cache/hapax/cockpit/engine-status.json",
        std::env::var("HOME").unwrap_or_default()
    );
    let engine = read_json(&engine_cache);
    nodes.push(NodeState {
        id: "engine".into(),
        label: "Reactive Engine".into(),
        status: if engine.is_some() { "active" } else { "offline" }.into(),
        age_s: engine.as_ref().map(age_s).unwrap_or(999.0),
        metrics: engine.as_ref().map(|e| {
            serde_json::json!({
                "events_processed": e.get("events_processed").and_then(|v| v.as_u64()).unwrap_or(0),
                "actions_executed": e.get("actions_executed").and_then(|v| v.as_u64()).unwrap_or(0),
                "errors": e.get("errors").and_then(|v| v.as_u64()).unwrap_or(0),
            })
        }).unwrap_or(serde_json::json!({})),
    });

    // ── Consent ─────────────────────────────────────────────────
    let consent_phase = perception.as_ref()
        .and_then(|p| p.get("consent_phase"))
        .and_then(|v| v.as_str())
        .unwrap_or("none");
    nodes.push(NodeState {
        id: "consent".into(),
        label: "Consent".into(),
        status: if consent_phase != "none" { "active" } else { "offline" }.into(),
        age_s: perc_age,
        metrics: serde_json::json!({
            "phase": consent_phase,
        }),
    });

    // ── Edges (data flow topology) ──────────────────────────────
    // Perception → Stimmung (perception confidence feeds stimmung)
    edges.push(EdgeState {
        source: "perception".into(), target: "stimmung".into(),
        active: perc_age < 10.0, label: "perception confidence".into(),
    });
    // Perception → Temporal Bands (perception ring feeds formatter)
    edges.push(EdgeState {
        source: "perception".into(), target: "temporal".into(),
        active: perc_age < 10.0, label: "perception ring".into(),
    });
    // Perception → Consent (face count, speaker ID)
    edges.push(EdgeState {
        source: "perception".into(), target: "consent".into(),
        active: perc_age < 10.0, label: "faces + speaker".into(),
    });
    // Stimmung → Apperception (stance modulates cascade)
    edges.push(EdgeState {
        source: "stimmung".into(), target: "apperception".into(),
        active: stim_age < 120.0, label: "stance".into(),
    });
    // Temporal → Apperception (surprise → prediction_error events)
    edges.push(EdgeState {
        source: "temporal".into(), target: "apperception".into(),
        active: temp_age < 10.0, label: "surprise".into(),
    });
    // Temporal → Phenomenal Context
    edges.push(EdgeState {
        source: "temporal".into(), target: "phenomenal".into(),
        active: temp_age < 30.0, label: "bands".into(),
    });
    // Apperception → Phenomenal Context
    edges.push(EdgeState {
        source: "apperception".into(), target: "phenomenal".into(),
        active: apper_age < 30.0, label: "self-band".into(),
    });
    // Stimmung → Phenomenal Context
    edges.push(EdgeState {
        source: "stimmung".into(), target: "phenomenal".into(),
        active: stim_age < 120.0, label: "attunement".into(),
    });
    // Phenomenal Context → Voice Pipeline
    edges.push(EdgeState {
        source: "phenomenal".into(), target: "voice".into(),
        active: voice_active, label: "orientation".into(),
    });
    // Perception → Voice Pipeline (salience routing)
    edges.push(EdgeState {
        source: "perception".into(), target: "voice".into(),
        active: voice_active, label: "salience".into(),
    });
    // Voice → Compositor (voice session state)
    edges.push(EdgeState {
        source: "voice".into(), target: "compositor".into(),
        active: voice_active, label: "voice state".into(),
    });
    // Stimmung → Compositor (stance drives visual feel)
    edges.push(EdgeState {
        source: "stimmung".into(), target: "compositor".into(),
        active: stim_age < 120.0, label: "visual mood".into(),
    });
    // Perception → Compositor (signals, biometrics)
    edges.push(EdgeState {
        source: "perception".into(), target: "compositor".into(),
        active: perc_age < 10.0, label: "signals".into(),
    });
    // Engine → Compositor (engine status)
    edges.push(EdgeState {
        source: "engine".into(), target: "compositor".into(),
        active: engine.is_some(), label: "engine state".into(),
    });
    // Stimmung → Engine (stance gates phases)
    edges.push(EdgeState {
        source: "stimmung".into(), target: "engine".into(),
        active: stim_age < 120.0, label: "phase gating".into(),
    });
    // Consent → Voice Pipeline (consent phase gates behavior)
    edges.push(EdgeState {
        source: "consent".into(), target: "voice".into(),
        active: consent_phase != "none", label: "consent gate".into(),
    });

    SystemFlowState {
        nodes,
        edges,
        timestamp: now,
    }
}
