//! System flow state — unified snapshot of all shm-based subsystems.
//!
//! Reads every /dev/shm/hapax-* directory and returns a single JSON
//! object that the React Flow visualization consumes. Each subsystem
//! becomes a node; data freshness and throughput become edge metadata.

use serde::Serialize;
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
                // Monotonic clock — can't compute age from Rust. Report 0.0 (fresh).
                0.0
            } else {
                now_epoch() - t
            }
        })
        .unwrap_or(999.0)
}

fn status(age: f64, stale: f64) -> &'static str {
    if age < stale { "active" } else if age < 30.0 { "stale" } else { "offline" }
}

/// Extract stimmung dimensions: keys that are objects with a "value" field.
fn stimmung_dimensions(s: &serde_json::Value) -> serde_json::Value {
    let Some(obj) = s.as_object() else { return serde_json::json!({}) };
    let skip = ["overall_stance", "timestamp", "non_nominal_dimensions"];
    let mut dims = serde_json::Map::new();
    for (key, val) in obj {
        if skip.contains(&key.as_str()) { continue; }
        if let Some(inner) = val.as_object() {
            if inner.contains_key("value") {
                dims.insert(key.clone(), serde_json::json!({
                    "value": inner.get("value").and_then(|v| v.as_f64()).unwrap_or(0.0),
                    "trend": inner.get("trend").and_then(|v| v.as_str()).unwrap_or("stable"),
                    "freshness_s": inner.get("freshness_s").and_then(|v| v.as_f64()).unwrap_or(0.0),
                }));
            }
        }
    }
    serde_json::Value::Object(dims)
}

/// Fetch engine status from logos API (HTTP, 1s timeout).
fn fetch_engine_status() -> serde_json::Value {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(1))
        .build();
    let Ok(client) = client else { return serde_json::json!({}) };
    let resp = client.get("http://127.0.0.1:8051/api/engine/status").send();
    match resp {
        Ok(r) if r.status().is_success() => {
            r.json::<serde_json::Value>().unwrap_or(serde_json::json!({}))
        }
        _ => serde_json::json!({}),
    }
}

// ── Node state structs ──────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Default)]
pub struct NodeState {
    pub id: String,
    pub label: String,
    pub status: String,
    pub age_s: f64,
    pub metrics: serde_json::Value,
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
    let home = std::env::var("HOME").unwrap_or_default();

    // ── Read all shm files ────────────────────────────────────────
    let perception_path = format!("{home}/.cache/hapax-voice/perception-state.json");
    let perception = read_json(&perception_path);
    let perc_age = perception.as_ref().map(age_s).unwrap_or(999.0);
    let p = perception.as_ref();

    let stimmung = read_json("/dev/shm/hapax-stimmung/state.json");
    let stim_age = stimmung.as_ref().map(age_s).unwrap_or(999.0);

    let temporal = read_json("/dev/shm/hapax-temporal/bands.json");
    let temp_age = temporal.as_ref().map(age_s).unwrap_or(999.0);

    let apperception = read_json("/dev/shm/hapax-apperception/self-band.json");
    let apper_age = apperception.as_ref().map(age_s).unwrap_or(999.0);
    let model = apperception.as_ref()
        .and_then(|a| a.get("self_model"))
        .cloned()
        .unwrap_or(serde_json::json!({}));

    let compositor = read_json("/dev/shm/hapax-compositor/visual-layer-state.json");
    let comp_age = compositor.as_ref().map(age_s).unwrap_or(999.0);
    let c = compositor.as_ref();

    // ── Perception ────────────────────────────────────────────────
    nodes.push(NodeState {
        id: "perception".into(),
        label: "Perception".into(),
        status: status(perc_age, 10.0).into(),
        age_s: perc_age,
        metrics: p.map(|p| serde_json::json!({
            "activity": p.get("production_activity").and_then(|v| v.as_str()).unwrap_or(""),
            "flow_score": p.get("flow_score").and_then(|v| v.as_f64()).unwrap_or(0.0),
            "presence_probability": p.get("presence_probability").and_then(|v| v.as_f64()),
            "face_count": p.get("face_count").and_then(|v| v.as_u64()).unwrap_or(0),
            "consent_phase": p.get("consent_phase").and_then(|v| v.as_str()).unwrap_or("none"),
            "aggregate_confidence": p.get("aggregate_confidence").and_then(|v| v.as_f64()),
            "heart_rate_bpm": p.get("heart_rate_bpm").and_then(|v| v.as_f64()),
            "stress_elevated": p.get("stress_elevated").and_then(|v| v.as_bool()).unwrap_or(false),
            "interruptibility_score": p.get("interruptibility_score").and_then(|v| v.as_f64()),
        })).unwrap_or(serde_json::json!({})),
    });

    // ── Stimmung ──────────────────────────────────────────────────
    let dims = stimmung.as_ref().map(|s| stimmung_dimensions(s)).unwrap_or(serde_json::json!({}));
    let non_nominal: Vec<String> = if let Some(obj) = dims.as_object() {
        obj.iter()
            .filter(|(_, v)| v.get("value").and_then(|v| v.as_f64()).unwrap_or(0.0) > 0.4)
            .map(|(k, _)| k.clone())
            .collect()
    } else { vec![] };
    nodes.push(NodeState {
        id: "stimmung".into(),
        label: "Stimmung".into(),
        status: if stim_age < 120.0 { "active" } else { "offline" }.into(),
        age_s: stim_age,
        metrics: stimmung.as_ref().map(|s| serde_json::json!({
            "stance": s.get("overall_stance").and_then(|v| v.as_str()).unwrap_or("unknown"),
            "health": s.get("health").and_then(|v| v.get("value")).and_then(|v| v.as_f64()),
            "resource_pressure": s.get("resource_pressure").and_then(|v| v.get("value")).and_then(|v| v.as_f64()),
            "dimensions": dims,
            "non_nominal": non_nominal,
        })).unwrap_or(serde_json::json!({})),
    });

    // ── Temporal Bands ────────────────────────────────────────────
    let impression = temporal.as_ref().and_then(|t| t.get("impression")).cloned().unwrap_or(serde_json::json!({}));
    nodes.push(NodeState {
        id: "temporal".into(),
        label: "Temporal Bands".into(),
        status: status(temp_age, 10.0).into(),
        age_s: temp_age,
        metrics: temporal.as_ref().map(|t| serde_json::json!({
            "max_surprise": t.get("max_surprise").and_then(|v| v.as_f64()).unwrap_or(0.0),
            "retention_count": t.get("retention_count").and_then(|v| v.as_u64()).unwrap_or(0),
            "protention_count": t.get("protention_count").and_then(|v| v.as_u64()).unwrap_or(0),
            "surprise_count": t.get("surprise_count").and_then(|v| v.as_u64()).unwrap_or(0),
            "flow_state": impression.get("flow_state").and_then(|v| v.as_str()).unwrap_or("idle"),
            "impression": {
                "flow_score": impression.get("flow_score").and_then(|v| v.as_f64()),
                "audio_energy": impression.get("audio_energy").and_then(|v| v.as_f64()),
                "heart_rate": impression.get("heart_rate").and_then(|v| v.as_f64()),
                "presence": impression.get("presence").and_then(|v| v.as_bool()),
            },
        })).unwrap_or(serde_json::json!({})),
    });

    // ── Apperception ──────────────────────────────────────────────
    let raw_dims = model.get("dimensions").cloned().unwrap_or(serde_json::json!({}));
    let mut apper_dims = serde_json::Map::new();
    if let Some(obj) = raw_dims.as_object() {
        for (name, dim) in obj {
            if let Some(d) = dim.as_object() {
                apper_dims.insert(name.clone(), serde_json::json!({
                    "confidence": d.get("confidence").and_then(|v| v.as_f64()).unwrap_or(0.0),
                    "assessment": d.get("current_assessment").and_then(|v| v.as_str()).unwrap_or("").chars().take(60).collect::<String>(),
                    "affirming": d.get("affirming_count").and_then(|v| v.as_u64()).unwrap_or(0),
                    "problematizing": d.get("problematizing_count").and_then(|v| v.as_u64()).unwrap_or(0),
                }));
            }
        }
    }
    nodes.push(NodeState {
        id: "apperception".into(),
        label: "Apperception".into(),
        status: status(apper_age, 10.0).into(),
        age_s: apper_age,
        metrics: if apperception.is_some() { serde_json::json!({
            "coherence": model.get("coherence").and_then(|v| v.as_f64()).unwrap_or(0.0),
            "dimensions": serde_json::Value::Object(apper_dims),
            "observation_count": model.get("recent_observations").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
            "reflection_count": model.get("recent_reflections").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
            "pending_action_count": apperception.as_ref().and_then(|a| a.get("pending_actions")).and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
        }) } else { serde_json::json!({}) },
    });

    // ── Compositor ────────────────────────────────────────────────
    let zone_opacities = c.and_then(|c| c.get("zone_opacities")).cloned().unwrap_or(serde_json::json!({}));
    let signals = c.and_then(|c| c.get("signals"));
    let mut signal_count: usize = 0;
    let mut max_severity: f64 = 0.0;
    if let Some(sigs) = signals.and_then(|s| s.as_object()) {
        for cat_sigs in sigs.values() {
            if let Some(arr) = cat_sigs.as_array() {
                signal_count += arr.len();
                for sig in arr {
                    if let Some(sev) = sig.get("severity").and_then(|v| v.as_f64()) {
                        if sev > max_severity { max_severity = sev; }
                    }
                }
            }
        }
    }
    let ambient = c.and_then(|c| c.get("ambient_params"));
    nodes.push(NodeState {
        id: "compositor".into(),
        label: "Compositor".into(),
        status: status(comp_age, 10.0).into(),
        age_s: comp_age,
        metrics: if compositor.is_some() { serde_json::json!({
            "display_state": c.and_then(|c| c.get("display_state")).and_then(|v| v.as_str()).unwrap_or("unknown"),
            "zone_opacities": zone_opacities,
            "signal_count": signal_count,
            "max_severity": (max_severity * 100.0).round() / 100.0,
            "ambient_speed": ambient.and_then(|a| a.get("speed")).and_then(|v| v.as_f64()),
            "ambient_turbulence": ambient.and_then(|a| a.get("turbulence")).and_then(|v| v.as_f64()),
        }) } else { serde_json::json!({}) },
    });

    // ── Voice Pipeline ────────────────────────────────────────────
    let voice_session = c.and_then(|c| c.get("voice_session"));
    let voice_active = voice_session
        .and_then(|v| v.get("active")).and_then(|v| v.as_bool()).unwrap_or(false);
    nodes.push(NodeState {
        id: "voice".into(),
        label: "Voice Pipeline".into(),
        status: if voice_active { "active" } else { "offline" }.into(),
        age_s: comp_age,
        metrics: if voice_active {
            let vs = voice_session.unwrap();
            serde_json::json!({
                "active": true,
                "state": vs.get("state").and_then(|v| v.as_str()).unwrap_or("off"),
                "turn_count": vs.get("turn_count").and_then(|v| v.as_u64()).unwrap_or(0),
                "last_utterance": vs.get("last_utterance").and_then(|v| v.as_str()).unwrap_or(""),
                "last_response": vs.get("last_response").and_then(|v| v.as_str()).unwrap_or(""),
                "routing_tier": vs.get("routing_tier").and_then(|v| v.as_str()).unwrap_or(""),
                "routing_reason": vs.get("routing_reason").and_then(|v| v.as_str()).unwrap_or(""),
                "routing_activation": vs.get("routing_activation").and_then(|v| v.as_f64()).unwrap_or(0.0),
                "barge_in": vs.get("barge_in").and_then(|v| v.as_bool()).unwrap_or(false),
                "frustration_score": vs.get("frustration_score").and_then(|v| v.as_f64()).unwrap_or(0.0),
                "acceptance_type": vs.get("acceptance_type").and_then(|v| v.as_str()).unwrap_or(""),
            })
        } else {
            serde_json::json!({"active": false, "state": "off"})
        },
    });

    // ── Phenomenal Context ────────────────────────────────────────
    let phenom_active = temp_age < 30.0 || apper_age < 30.0;
    let bound = temp_age < 30.0 && apper_age < 30.0;
    let mut active_dims: usize = 0;
    if let Some(rd) = raw_dims.as_object() {
        for dim in rd.values() {
            if let Some(shift) = dim.get("last_shift_time").and_then(|v| v.as_f64()) {
                if (now - shift) < 300.0 { active_dims += 1; }
            }
        }
    }
    nodes.push(NodeState {
        id: "phenomenal".into(),
        label: "Phenomenal Context".into(),
        status: if phenom_active { "active" } else { "offline" }.into(),
        age_s: temp_age.min(apper_age),
        metrics: serde_json::json!({
            "bound": bound,
            "coherence": if apper_age < 30.0 { model.get("coherence").and_then(|v| v.as_f64()) } else { None },
            "surprise": if temp_age < 30.0 { temporal.as_ref().and_then(|t| t.get("max_surprise")).and_then(|v| v.as_f64()) } else { None },
            "active_dimensions": active_dims,
        }),
    });

    // ── Reactive Engine ───────────────────────────────────────────
    let engine_data = fetch_engine_status();
    let engine_running = engine_data.get("uptime_s").and_then(|v| v.as_f64()).unwrap_or(0.0) > 0.0;
    nodes.push(NodeState {
        id: "engine".into(),
        label: "Reactive Engine".into(),
        status: if engine_running { "active" } else { "offline" }.into(),
        age_s: if engine_running { 0.0 } else { 999.0 },
        metrics: if engine_running { serde_json::json!({
            "events_processed": engine_data.get("events_processed").and_then(|v| v.as_u64()).unwrap_or(0),
            "actions_executed": engine_data.get("actions_executed").and_then(|v| v.as_u64()).unwrap_or(0),
            "error_count": engine_data.get("errors").and_then(|v| v.as_u64()).unwrap_or(0),
            "rules_evaluated": engine_data.get("rules_evaluated").and_then(|v| v.as_u64()).unwrap_or(0),
            "novelty_score": engine_data.get("novelty_score").and_then(|v| v.as_f64()).unwrap_or(0.0),
            "shift_score": engine_data.get("shift_score").and_then(|v| v.as_f64()).unwrap_or(0.0),
            "uptime_s": engine_data.get("uptime_s").and_then(|v| v.as_f64()).unwrap_or(0.0),
        }) } else { serde_json::json!({}) },
    });

    // ── Consent ───────────────────────────────────────────────────
    let consent_phase = p
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
            "active_contracts": 0,
            "coverage_pct": 0.0,
        }),
    });

    // ── Edges ─────────────────────────────────────────────────────
    let e = |source: &str, target: &str, active: bool, label: &str| EdgeState {
        source: source.into(), target: target.into(), active, label: label.into(),
    };
    edges.push(e("perception", "stimmung", perc_age < 10.0, "perception confidence"));
    edges.push(e("perception", "temporal", perc_age < 10.0, "perception ring"));
    edges.push(e("perception", "consent", perc_age < 10.0, "faces + speaker"));
    edges.push(e("stimmung", "apperception", stim_age < 120.0, "stance"));
    edges.push(e("temporal", "apperception", temp_age < 10.0, "surprise"));
    edges.push(e("temporal", "phenomenal", temp_age < 30.0, "bands"));
    edges.push(e("apperception", "phenomenal", apper_age < 30.0, "self-band"));
    edges.push(e("stimmung", "phenomenal", stim_age < 120.0, "attunement"));
    edges.push(e("phenomenal", "voice", voice_active, "orientation"));
    edges.push(e("perception", "voice", voice_active, "salience"));
    edges.push(e("voice", "compositor", voice_active, "voice state"));
    edges.push(e("stimmung", "compositor", stim_age < 120.0, "visual mood"));
    edges.push(e("perception", "compositor", perc_age < 10.0, "signals"));
    edges.push(e("engine", "compositor", engine_running, "engine state"));
    edges.push(e("stimmung", "engine", stim_age < 120.0, "phase gating"));
    edges.push(e("consent", "voice", consent_phase != "none", "consent gate"));

    SystemFlowState { nodes, edges, timestamp: now }
}
