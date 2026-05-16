use serde::{Deserialize, Serialize};
use std::path::Path;

// --- Working Mode ---

#[derive(Debug, Clone, Serialize)]
pub struct WorkingModeResponse {
    pub mode: String,
    pub switched_at: Option<String>,
}

#[tauri::command]
pub fn get_working_mode() -> WorkingModeResponse {
    let path = expand_home("~/.cache/hapax/working-mode");
    match std::fs::read_to_string(&path) {
        Ok(content) => {
            let mode = content.trim().to_string();
            let switched_at = std::fs::metadata(&path)
                .ok()
                .and_then(|m| m.modified().ok())
                .map(|t| {
                    let d = t.duration_since(std::time::UNIX_EPOCH).unwrap_or_default();
                    format_timestamp(d.as_secs())
                });
            WorkingModeResponse { mode, switched_at }
        }
        Err(_) => WorkingModeResponse {
            mode: "rnd".into(),
            switched_at: None,
        },
    }
}

#[tauri::command]
pub fn set_working_mode(mode: String) -> WorkingModeResponse {
    let path = expand_home("~/.cache/hapax/working-mode");
    // Ensure parent dir exists
    if let Some(parent) = Path::new(&path).parent() {
        std::fs::create_dir_all(parent).ok();
    }
    std::fs::write(&path, &mode).ok();
    get_working_mode()
}

// --- Accommodations ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Accommodation {
    pub id: String,
    #[serde(default)]
    pub pattern_category: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub active: bool,
    #[serde(default)]
    pub proposed_at: String,
    #[serde(default)]
    pub confirmed_at: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct AccommodationSet {
    pub accommodations: Vec<Accommodation>,
    pub time_anchor_enabled: bool,
    pub soft_framing: bool,
    pub energy_aware: bool,
    pub peak_hours: Vec<u32>,
    pub low_hours: Vec<u32>,
}

#[derive(Deserialize)]
struct AccommodationFile {
    #[serde(default)]
    accommodations: Vec<Accommodation>,
    #[serde(default)]
    peak_hours: Vec<u32>,
    #[serde(default)]
    low_hours: Vec<u32>,
}

#[tauri::command]
pub fn get_accommodations() -> AccommodationSet {
    let path = expand_home("~/.hapax/profiles/accommodations.json");
    let data: Option<AccommodationFile> = read_json(&path);

    match data {
        Some(file) => {
            let time_anchor_enabled = file
                .accommodations
                .iter()
                .any(|a| a.active && a.pattern_category == "time_anchor");
            let soft_framing = file
                .accommodations
                .iter()
                .any(|a| a.active && a.pattern_category == "soft_framing");
            let energy_aware = file
                .accommodations
                .iter()
                .any(|a| a.active && a.pattern_category == "energy_aware");

            AccommodationSet {
                accommodations: file.accommodations,
                time_anchor_enabled,
                soft_framing,
                energy_aware,
                peak_hours: file.peak_hours,
                low_hours: file.low_hours,
            }
        }
        None => AccommodationSet {
            accommodations: vec![],
            time_anchor_enabled: false,
            soft_framing: false,
            energy_aware: false,
            peak_hours: vec![],
            low_hours: vec![],
        },
    }
}

// --- Manual ---

#[derive(Debug, Clone, Serialize)]
pub struct ManualResponse {
    pub content: String,
    pub updated_at: Option<String>,
}

#[tauri::command]
pub fn get_manual() -> ManualResponse {
    let candidates = [
        expand_home("~/projects/hapaxromana/operations-manual.md"),
        expand_home("~/projects/hapax-council/profiles/operations-manual.md"),
    ];

    for path in &candidates {
        if let Ok(content) = std::fs::read_to_string(path) {
            let updated_at = std::fs::metadata(path)
                .ok()
                .and_then(|m| m.modified().ok())
                .map(|t| {
                    let d = t.duration_since(std::time::UNIX_EPOCH).unwrap_or_default();
                    format_timestamp(d.as_secs())
                });
            return ManualResponse {
                content,
                updated_at,
            };
        }
    }

    ManualResponse {
        content: "Operations manual not found.".into(),
        updated_at: None,
    }
}

// --- Goals ---

#[derive(Debug, Clone, Serialize)]
pub struct GoalSnapshot {
    pub goals: Vec<GoalStatus>,
    pub active_count: u32,
    pub stale_count: u32,
    pub primary_stale: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct GoalStatus {
    pub id: String,
    pub name: String,
    pub status: String,
    pub category: String,
    pub last_activity_h: Option<f64>,
    pub stale: bool,
    pub progress_summary: String,
    pub description: String,
}

#[derive(Deserialize)]
struct OperatorFile {
    #[serde(default)]
    goals: Option<GoalsSection>,
}

#[derive(Deserialize)]
struct GoalsSection {
    #[serde(default)]
    primary: Vec<GoalRaw>,
    #[serde(default)]
    secondary: Vec<GoalRaw>,
}

#[derive(Deserialize)]
#[allow(dead_code)]
struct GoalRaw {
    #[serde(default)]
    id: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    status: String,
    #[serde(default)]
    category: String,
    #[serde(default)]
    last_activity_at: Option<String>,
    #[serde(default)]
    progress_summary: String,
    #[serde(default)]
    description: String,
}

#[tauri::command]
pub fn get_goals() -> GoalSnapshot {
    let op: Option<OperatorFile> = read_json_fallback(
        "~/.hapax/operator.json",
        "~/projects/hapax-council/profiles/operator-profile.json",
    );

    let goals_section = op.and_then(|o| o.goals);
    let mut goals = Vec::new();

    if let Some(section) = goals_section {
        for (raw, cat) in section
            .primary
            .into_iter()
            .map(|g| (g, "primary"))
            .chain(section.secondary.into_iter().map(|g| (g, "secondary")))
        {
            let stale = is_goal_stale(&raw.status, &raw.last_activity_at);
            let last_activity_h = raw.last_activity_at.as_ref().and_then(|ts| hours_since(ts));

            goals.push(GoalStatus {
                id: raw.id,
                name: raw.name,
                status: raw.status,
                category: cat.into(),
                last_activity_h,
                stale,
                progress_summary: raw.progress_summary,
                description: raw.description,
            });
        }
    }

    let active_count = goals.iter().filter(|g| g.status == "active").count() as u32;
    let stale_count = goals.iter().filter(|g| g.stale).count() as u32;
    let primary_stale: Vec<String> = goals
        .iter()
        .filter(|g| g.stale && g.category == "primary")
        .map(|g| g.name.clone())
        .collect();

    GoalSnapshot {
        goals,
        active_count,
        stale_count,
        primary_stale,
    }
}

// --- Scout ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScoutRecommendation {
    #[serde(default)]
    pub component: String,
    #[serde(default)]
    pub current: String,
    #[serde(default)]
    pub tier: String,
    #[serde(default)]
    pub summary: String,
    #[serde(default)]
    pub confidence: String,
    #[serde(default)]
    pub migration_effort: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ScoutData {
    pub generated_at: String,
    pub components_scanned: u32,
    pub recommendations: Vec<ScoutRecommendation>,
    pub adopt_count: u32,
    pub evaluate_count: u32,
}

#[derive(Deserialize)]
struct ScoutFile {
    #[serde(default)]
    generated_at: String,
    #[serde(default)]
    components_scanned: u32,
    #[serde(default)]
    recommendations: Vec<ScoutRecommendation>,
}

#[tauri::command]
pub fn get_scout() -> Option<ScoutData> {
    let path = expand_home("~/.hapax/profiles/scout-report.json");
    let file: ScoutFile = read_json(&path)?;

    let adopt_count = file
        .recommendations
        .iter()
        .filter(|r| r.tier == "adopt")
        .count() as u32;
    let evaluate_count = file
        .recommendations
        .iter()
        .filter(|r| r.tier == "evaluate")
        .count() as u32;

    Some(ScoutData {
        generated_at: file.generated_at,
        components_scanned: file.components_scanned,
        recommendations: file.recommendations,
        adopt_count,
        evaluate_count,
    })
}

// --- Scout Decisions ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScoutDecision {
    pub component: String,
    pub decision: String,
    pub timestamp: String,
    #[serde(default)]
    pub notes: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ScoutDecisionsResponse {
    pub decisions: Vec<ScoutDecision>,
}

#[tauri::command]
pub fn get_scout_decisions() -> ScoutDecisionsResponse {
    let path = expand_home("~/.hapax/profiles/scout-decisions.jsonl");
    let decisions = match std::fs::read_to_string(&path) {
        Ok(data) => data
            .lines()
            .filter_map(|l| serde_json::from_str::<ScoutDecision>(l).ok())
            .collect(),
        Err(_) => vec![],
    };
    ScoutDecisionsResponse { decisions }
}

// --- Drift ---

#[derive(Debug, Clone, Serialize)]
pub struct DriftSummary {
    pub drift_count: u32,
    pub docs_analyzed: u32,
    pub summary: String,
    pub latest_timestamp: String,
    pub items: Vec<DriftItem>,
    pub report_age_h: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DriftItem {
    #[serde(default)]
    pub severity: String,
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub doc_file: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub suggestion: String,
}

#[derive(Deserialize)]
struct DriftFile {
    #[serde(default)]
    drift_items: Vec<DriftItem>,
    #[serde(default)]
    docs_analyzed: u32,
    #[serde(default)]
    summary: String,
    #[serde(default)]
    timestamp: String,
}

#[tauri::command]
pub fn get_drift() -> Option<DriftSummary> {
    let path = expand_home("~/.hapax/profiles/drift-report.json");
    let file: DriftFile = read_json(&path)?;

    let drift_count = file.drift_items.len() as u32;
    let report_age_h = hours_since(&file.timestamp).unwrap_or(0.0);

    Some(DriftSummary {
        drift_count,
        docs_analyzed: file.docs_analyzed,
        summary: file.summary,
        latest_timestamp: file.timestamp,
        items: file.drift_items,
        report_age_h,
    })
}

// --- Management ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PersonState {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub team: String,
    #[serde(default)]
    pub role: String,
    #[serde(default)]
    pub cadence: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub cognitive_load: Option<f64>,
    #[serde(default)]
    pub growth_vector: String,
    #[serde(default)]
    pub feedback_style: String,
    #[serde(default)]
    pub last_1on1: String,
    #[serde(default)]
    pub coaching_active: bool,
    #[serde(default)]
    pub stale_1on1: bool,
    #[serde(default)]
    pub days_since_1on1: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CoachingState {
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub person: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub check_in_by: String,
    #[serde(default)]
    pub overdue: bool,
    #[serde(default)]
    pub days_overdue: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeedbackState {
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub person: String,
    #[serde(default)]
    pub direction: String,
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub follow_up_by: String,
    #[serde(default)]
    pub followed_up: bool,
    #[serde(default)]
    pub overdue: bool,
    #[serde(default)]
    pub days_overdue: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManagementSnapshot {
    #[serde(default)]
    pub people: Vec<PersonState>,
    #[serde(default)]
    pub coaching: Vec<CoachingState>,
    #[serde(default)]
    pub feedback: Vec<FeedbackState>,
}

#[tauri::command]
pub fn get_management() -> ManagementSnapshot {
    // Management data is computed by the Python management agent.
    // The logos API reads from a cached snapshot file.
    let path = expand_home("~/.hapax/profiles/management-snapshot.json");
    read_json(&path).unwrap_or(ManagementSnapshot {
        people: vec![],
        coaching: vec![],
        feedback: vec![],
    })
}

// --- Nudges ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Nudge {
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub priority_score: f64,
    #[serde(default)]
    pub priority_label: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub detail: String,
    #[serde(default)]
    pub suggested_action: String,
    #[serde(default)]
    pub command_hint: String,
    #[serde(default)]
    pub source_id: String,
}

#[tauri::command]
pub fn get_nudges() -> Vec<Nudge> {
    // Nudges are computed server-side from multiple sources.
    // Read the cached result from the logos snapshot file.
    let path = expand_home("~/.hapax/profiles/nudges.json");
    read_json::<Vec<Nudge>>(&path).unwrap_or_default()
}

// --- Readiness ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadinessSnapshot {
    #[serde(default)]
    pub level: String,
    #[serde(default)]
    pub interview_conducted: bool,
    #[serde(default)]
    pub interview_fact_count: u32,
    #[serde(default)]
    pub priorities_known: bool,
    #[serde(default)]
    pub neurocognitive_mapped: bool,
    #[serde(default)]
    pub profile_coverage_pct: f64,
    #[serde(default)]
    pub total_facts: u32,
    #[serde(default)]
    pub populated_dimensions: u32,
    #[serde(default)]
    pub total_dimensions: u32,
    #[serde(default)]
    pub missing_dimensions: Vec<String>,
    #[serde(default)]
    pub sparse_dimensions: Vec<String>,
    #[serde(default)]
    pub top_gap: String,
    #[serde(default)]
    pub gaps: Vec<String>,
}

#[tauri::command]
pub fn get_readiness() -> ReadinessSnapshot {
    let path = expand_home("~/.hapax/profiles/readiness-snapshot.json");
    read_json(&path).unwrap_or(ReadinessSnapshot {
        level: "bootstrapping".into(),
        interview_conducted: false,
        interview_fact_count: 0,
        priorities_known: false,
        neurocognitive_mapped: false,
        profile_coverage_pct: 0.0,
        total_facts: 0,
        populated_dimensions: 0,
        total_dimensions: 11,
        missing_dimensions: vec![],
        sparse_dimensions: vec![],
        top_gap: String::new(),
        gaps: vec![],
    })
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

fn read_json_fallback<T: serde::de::DeserializeOwned>(primary: &str, fallback: &str) -> Option<T> {
    read_json(&expand_home(primary)).or_else(|| read_json(&expand_home(fallback)))
}

fn is_goal_stale(status: &str, last_activity: &Option<String>) -> bool {
    let threshold_days = match status {
        "active" => 7.0,
        "ongoing" => 30.0,
        _ => return false, // planned/completed goals are never stale
    };
    match last_activity {
        Some(ts) => hours_since(ts).is_none_or(|h| h / 24.0 > threshold_days),
        None => true,
    }
}

fn hours_since(iso_ts: &str) -> Option<f64> {
    // Simple ISO timestamp parse — enough for YYYY-MM-DDTHH:MM:SS
    use std::time::{SystemTime, UNIX_EPOCH};
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()?
        .as_secs_f64();

    // Parse ISO: 2026-03-15T10:30:00 or similar
    let ts = iso_ts.replace('Z', "+00:00");
    let parts: Vec<&str> = ts.split('T').collect();
    if parts.len() < 2 {
        return None;
    }
    let date_parts: Vec<u32> = parts[0].split('-').filter_map(|s| s.parse().ok()).collect();
    if date_parts.len() < 3 {
        return None;
    }
    let time_str = parts[1].split('+').next().unwrap_or(parts[1]);
    let time_str = time_str.split('-').next().unwrap_or(time_str);
    let time_parts: Vec<u32> = time_str.split(':').filter_map(|s| s.parse().ok()).collect();

    let (y, m, d) = (date_parts[0], date_parts[1], date_parts[2]);
    let (h, min, s) = (
        *time_parts.first().unwrap_or(&0),
        *time_parts.get(1).unwrap_or(&0),
        *time_parts.get(2).unwrap_or(&0),
    );

    // Approximate epoch seconds (good enough for staleness)
    let epoch_days = days_from_civil(y as i64, m, d);
    let epoch_secs = epoch_days as f64 * 86400.0 + h as f64 * 3600.0 + min as f64 * 60.0 + s as f64;

    Some((now - epoch_secs) / 3600.0)
}

fn days_from_civil(y: i64, m: u32, d: u32) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y.rem_euclid(400) as u32;
    let m = m as i64;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d as i64 - 1;
    let doe = yoe as i64 * 365 + yoe as i64 / 4 - yoe as i64 / 100 + doy;
    era * 146097 + doe - 719468
}

fn format_timestamp(epoch_secs: u64) -> String {
    let d = days_from_epoch(epoch_secs);
    let remaining = epoch_secs % 86400;
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        d.0,
        d.1,
        d.2,
        remaining / 3600,
        (remaining % 3600) / 60,
        remaining % 60
    )
}

fn days_from_epoch(secs: u64) -> (u32, u32, u32) {
    let days = (secs / 86400) as i64;
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z.rem_euclid(146097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    (y as u32, m as u32, d as u32)
}
