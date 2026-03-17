use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader};
use std::path::Path;

// --- Health ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthSnapshot {
    pub overall_status: String,
    pub total_checks: u32,
    pub healthy: u32,
    pub degraded: u32,
    pub failed: u32,
    pub duration_ms: f64,
    pub failed_checks: Vec<String>,
    pub timestamp: String,
}

#[tauri::command]
pub fn get_health() -> Option<HealthSnapshot> {
    let path = expand_home("~/.hapax/profiles/health-history.jsonl");
    let file = std::fs::File::open(&path).ok()?;
    let reader = BufReader::new(file);
    let last_line = reader.lines().filter_map(|l| l.ok()).last()?;
    serde_json::from_str(&last_line).ok()
}

// --- GPU ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VramSnapshot {
    pub name: String,
    pub total_mb: f64,
    pub used_mb: f64,
    pub free_mb: f64,
    pub usage_pct: f64,
    pub temperature_c: f64,
    pub loaded_models: Vec<String>,
}

#[derive(Deserialize)]
struct InfraFile {
    #[serde(default)]
    gpu: Option<GpuSection>,
    #[serde(default)]
    containers: Option<Vec<ContainerRaw>>,
    #[serde(default)]
    timers: Option<Vec<TimerRaw>>,
}

#[derive(Deserialize)]
struct GpuSection {
    #[serde(default)]
    name: String,
    #[serde(default)]
    total_mb: f64,
    #[serde(default)]
    used_mb: f64,
    #[serde(default)]
    free_mb: f64,
    #[serde(default)]
    temperature_c: f64,
    #[serde(default)]
    loaded_models: Vec<String>,
}

#[tauri::command]
pub fn get_gpu() -> Option<VramSnapshot> {
    let infra: InfraFile = read_json(&expand_home("~/.hapax/profiles/infra-snapshot.json"))?;
    let gpu = infra.gpu?;
    let usage_pct = if gpu.total_mb > 0.0 {
        (gpu.used_mb / gpu.total_mb) * 100.0
    } else {
        0.0
    };
    Some(VramSnapshot {
        name: gpu.name,
        total_mb: gpu.total_mb,
        used_mb: gpu.used_mb,
        free_mb: gpu.free_mb,
        usage_pct,
        temperature_c: gpu.temperature_c,
        loaded_models: gpu.loaded_models,
    })
}

// --- Infrastructure ---

#[derive(Debug, Clone, Serialize)]
pub struct Infrastructure {
    pub containers: Vec<ContainerStatus>,
    pub timers: Vec<TimerStatus>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ContainerStatus {
    pub name: String,
    pub service: String,
    pub state: String,
    pub health: String,
    pub image: String,
    pub ports: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct TimerStatus {
    pub unit: String,
    pub next_fire: String,
    pub last_fired: String,
    pub activates: String,
}

#[derive(Deserialize)]
struct ContainerRaw {
    #[serde(default)]
    name: String,
    #[serde(default)]
    service: String,
    #[serde(default)]
    state: String,
    #[serde(default)]
    health: String,
    #[serde(default)]
    image: String,
    #[serde(default)]
    ports: Vec<String>,
}

#[derive(Deserialize)]
struct TimerRaw {
    #[serde(default)]
    unit: String,
    #[serde(default)]
    next_fire: String,
    #[serde(default)]
    last_fired: String,
    #[serde(default)]
    activates: String,
}

#[tauri::command]
pub fn get_infrastructure() -> Infrastructure {
    let path = expand_home("~/.hapax/profiles/infra-snapshot.json");
    let infra: Option<InfraFile> = read_json(&path);

    match infra {
        Some(data) => Infrastructure {
            containers: data
                .containers
                .unwrap_or_default()
                .into_iter()
                .map(|c| ContainerStatus {
                    name: c.name,
                    service: c.service,
                    state: c.state,
                    health: c.health,
                    image: c.image,
                    ports: c.ports,
                })
                .collect(),
            timers: data
                .timers
                .unwrap_or_default()
                .into_iter()
                .map(|t| TimerStatus {
                    unit: t.unit,
                    next_fire: t.next_fire,
                    last_fired: t.last_fired,
                    activates: t.activates,
                })
                .collect(),
        },
        None => Infrastructure {
            containers: vec![],
            timers: vec![],
        },
    }
}

// --- Health History ---

#[derive(Debug, Clone, Serialize)]
pub struct HealthHistory {
    pub entries: Vec<HealthSnapshot>,
    pub uptime_pct: f64,
    pub total_runs: u32,
}

#[tauri::command]
pub fn get_health_history(days: Option<u32>) -> HealthHistory {
    let days = days.unwrap_or(7);
    let path = expand_home("~/.hapax/profiles/health-history.jsonl");
    let file = match std::fs::File::open(&path) {
        Ok(f) => f,
        Err(_) => {
            return HealthHistory {
                entries: vec![],
                uptime_pct: 0.0,
                total_runs: 0,
            }
        }
    };

    let reader = BufReader::new(file);
    let cutoff = chrono_days_ago(days);
    let mut entries: Vec<HealthSnapshot> = reader
        .lines()
        .filter_map(|l| l.ok())
        .filter_map(|l| serde_json::from_str::<HealthSnapshot>(&l).ok())
        .filter(|e| e.timestamp.as_str() >= cutoff.as_str())
        .collect();

    let total_runs = entries.len() as u32;
    let healthy_runs = entries.iter().filter(|e| e.overall_status == "healthy").count() as f64;
    let uptime_pct = if total_runs > 0 {
        (healthy_runs / total_runs as f64) * 100.0
    } else {
        0.0
    };

    // Keep last 500 for display
    if entries.len() > 500 {
        entries = entries.split_off(entries.len() - 500);
    }

    HealthHistory {
        entries,
        uptime_pct,
        total_runs,
    }
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

fn chrono_days_ago(days: u32) -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let cutoff = now - (days as u64 * 86400);
    // Rough ISO timestamp for comparison (works because ISO strings sort lexicographically)
    let secs = cutoff;
    let days_since_epoch = secs / 86400;
    let remaining = secs % 86400;
    // Approximate date calculation
    let mut y = 1970i64;
    let mut d = days_since_epoch as i64;
    loop {
        let days_in_year = if y % 4 == 0 && (y % 100 != 0 || y % 400 == 0) {
            366
        } else {
            365
        };
        if d < days_in_year {
            break;
        }
        d -= days_in_year;
        y += 1;
    }
    let months = [31, 28 + if y % 4 == 0 && (y % 100 != 0 || y % 400 == 0) { 1 } else { 0 },
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let mut m = 0;
    for days_in_month in months {
        if d < days_in_month {
            break;
        }
        d -= days_in_month;
        m += 1;
    }
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
        y,
        m + 1,
        d + 1,
        remaining / 3600,
        (remaining % 3600) / 60,
        remaining % 60
    )
}
